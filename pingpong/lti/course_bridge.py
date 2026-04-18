import json
import logging
from collections.abc import AsyncIterator
from datetime import datetime, timedelta
from functools import partial
from typing import cast
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import aiohttp
from fastapi import BackgroundTasks
import jwt
import uuid_utils as uuid
from sqlalchemy.ext.asyncio import AsyncSession

from pingpong.authz.openfga import OpenFgaAuthzClient
from pingpong.config import LTISecuritySettings, LTIUrlSecuritySettings, config
from pingpong.lti.constants import (
    COURSE_BRIDGE_SYNC_WAIT_DEFAULT_SECONDS,
    CLIENT_ASSERTION_EXPIRY_SECONDS,
    CLIENT_ASSERTION_TYPE,
    CLIENT_CREDENTIALS_GRANT_TYPE,
    LTI_CLAIM_CUSTOM_KEY,
    LTI_CUSTOM_SSO_PROVIDER_ID_KEY,
    LTI_CUSTOM_SSO_VALUE_KEY,
    NRPS_ACCESS_TOKEN_FALLBACK_TTL_SECONDS,
    NRPS_ACCESS_TOKEN_REFRESH_BUFFER_SECONDS,
    NRPS_CONTEXT_ID_KEY,
    NRPS_CONTEXT_KEY,
    NRPS_CONTEXT_MEMBERSHIP_SCOPE,
    NRPS_MEMBER_ACTIVE_STATUS,
    NRPS_MEMBER_EMAIL_KEY,
    NRPS_MEMBER_MESSAGE_KEY,
    NRPS_MEMBER_NAME_KEY,
    NRPS_MEMBER_ROLES_KEY,
    NRPS_MEMBER_STATUS_KEY,
    NRPS_MEMBERSHIP_CONTAINER_CONTENT_TYPE,
    NRPS_MEMBERS_KEY,
    NRPS_NEXT_PAGE_KEY,
    NRPS_RESOURCE_LINK_QUERY_KEY,
    TOKEN_ENDPOINT_KEY,
    TOKEN_REQUEST_CONTENT_TYPE,
)
from pingpong.lti.endpoints import (
    allow_redirects,
    generate_names_and_role_api_url,
    generate_token_endpoint_url,
)
from pingpong.lti.http import (
    create_lti_redirect_trace_config,
    request_with_validated_redirects,
)
from pingpong.lti.key_manager import LTIKeyManager
from pingpong.lti.roles import class_user_roles_from_lti_roles
from pingpong.models import (
    ExternalLoginProvider,
    LTIClass,
    LTIRegistration,
)
from pingpong.now import NowFn, utcnow
from pingpong.schemas import (
    ClassUserRoles,
    CourseBridgeAccessToken,
    CreateUserClassRole,
    CreateUserClassRoles,
    CreateUserResults,
    LTIStatus,
    LMSType,
)
from pingpong.state_types import StateRequest
from pingpong.time import convert_seconds
from pingpong.users import AddNewUsersManual, AddNewUsersScript

logger = logging.getLogger(__name__)
SYNC_ROW_ERROR_DETAIL_LIMIT = 3


def exception_detail(e: Exception) -> str:
    detail = getattr(e, "detail", None)
    if isinstance(detail, str) and detail:
        return detail
    return str(e)


def _as_dict(value: object) -> dict[str, object] | None:
    if not isinstance(value, dict):
        return None
    if any(not isinstance(key, str) for key in value):
        return None
    return cast(dict[str, object], value)


def _as_optional_int(value: object) -> int | None:
    if value is None:
        return None
    if not isinstance(value, (int, float, str, bytes, bytearray)):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _extract_error_detail(payload: object) -> str | None:
    payload_dict = _as_dict(payload)
    if payload_dict is None:
        return None
    error_description = payload_dict.get("error_description")
    if isinstance(error_description, str) and error_description:
        return error_description
    error = payload_dict.get("error")
    if isinstance(error, str) and error:
        return error
    return None


def _extract_sync_row_errors(results: CreateUserResults) -> list[str]:
    row_errors: list[str] = []
    for row_result in results.results:
        if not row_result.error:
            continue
        row_errors.append(f"{row_result.email}: {row_result.error}")
    return row_errors


def _require_lti_security() -> LTISecuritySettings:
    lti_settings = config.lti
    if lti_settings is None:
        raise CourseBridgeGlobalException(detail="LTI service is not configured")
    return lti_settings.security


def _allow_redirects_or_raise(security_config: LTIUrlSecuritySettings) -> bool:
    try:
        return allow_redirects(security_config)
    except ValueError as e:
        raise CourseBridgeException(detail=str(e)) from e


class CourseBridgeException(Exception):
    def __init__(self, detail: str = ""):
        self.detail = detail
        super().__init__(detail)


class CourseBridgeGlobalException(CourseBridgeException):
    """Raised for deployment-wide failures that should not mutate class state."""


class CourseBridgeWarning(Exception):
    def __init__(self, detail: str = ""):
        self.detail = detail
        super().__init__(detail)


class CourseBridgeClient:
    def __init__(
        self,
        db: AsyncSession,
        lti_class_id: int,
        key_manager: LTIKeyManager | None = None,
        nowfn: NowFn = utcnow,
    ):
        self.db = db
        self.lti_class_id = lti_class_id
        self.nowfn = nowfn
        if key_manager is None:
            if config.lti is None:
                raise CourseBridgeGlobalException(
                    detail="LTI service is not configured",
                )
            key_manager = config.lti.key_store.key_manager
        self.key_manager = key_manager
        self.http_session: aiohttp.ClientSession | None = None
        self._cached_lti_class: LTIClass | None = None
        self._cached_nrps_access_token: CourseBridgeAccessToken | None = None
        self._cached_nrps_access_token_valid_until: int | None = None

    async def __aenter__(self):
        self.http_session = aiohttp.ClientSession(
            trace_configs=[create_lti_redirect_trace_config()]
        )
        return self

    async def __aexit__(self, exc_type, exc, tb):
        if self.http_session is not None:
            await self.http_session.close()
            self.http_session = None

    def _require_http_session(self) -> aiohttp.ClientSession:
        if self.http_session is None:
            raise RuntimeError(
                "CourseBridgeClient must be used as an async context manager"
            )
        return self.http_session

    @staticmethod
    def _get_token_endpoint(registration: LTIRegistration) -> str:
        if registration.openid_configuration:
            try:
                openid_configuration = json.loads(registration.openid_configuration)
            except json.JSONDecodeError as e:
                raise CourseBridgeException(
                    detail="Invalid OpenID configuration for LTI registration",
                ) from e

            openid_configuration_dict = _as_dict(openid_configuration)
            if openid_configuration_dict is not None:
                token_endpoint = openid_configuration_dict.get(TOKEN_ENDPOINT_KEY)
                if isinstance(token_endpoint, str) and token_endpoint:
                    return token_endpoint

        if isinstance(registration.auth_token_url, str) and registration.auth_token_url:
            return registration.auth_token_url

        raise CourseBridgeException(
            detail="LTI registration is missing a token endpoint",
        )

    async def _get_lti_class(self) -> LTIClass:
        if self._cached_lti_class is not None:
            return self._cached_lti_class

        lti_class = await LTIClass.get_by_id_with_registration(
            self.db, self.lti_class_id
        )
        if not lti_class:
            raise CourseBridgeException(detail="LTI class not found")
        if lti_class.registration is None:
            raise CourseBridgeException(
                detail="LTI registration not found for class",
            )

        self._cached_lti_class = lti_class
        return lti_class

    async def _build_client_assertion(self, client_id: str, token_endpoint: str) -> str:
        key = await self.key_manager.get_current_key()
        if key is None:
            raise CourseBridgeException(
                detail="No LTI signing key is available",
            )
        if key.algorithm != "RS256":
            raise CourseBridgeException(
                detail="LTI signing key algorithm must be RS256",
            )

        now = self.nowfn()
        issued_at = int(now.timestamp())
        expires_at = int(
            (now + timedelta(seconds=CLIENT_ASSERTION_EXPIRY_SECONDS)).timestamp()
        )
        payload = {
            "iss": client_id,
            "sub": client_id,
            "aud": token_endpoint,
            "iat": issued_at,
            "exp": expires_at,
            "jti": str(uuid.uuid7()),
        }
        headers = {
            "typ": "JWT",
            "alg": "RS256",
            "kid": key.kid,
        }

        return jwt.encode(
            payload,
            key.private_key_pem,
            algorithm="RS256",
            headers=headers,
        )

    async def get_context_memberships_url(self) -> str:
        lti_class = await self._get_lti_class()
        existing_context_memberships_url = lti_class.context_memberships_url
        if (
            isinstance(existing_context_memberships_url, str)
            and existing_context_memberships_url
        ):
            return existing_context_memberships_url

        raise CourseBridgeException(
            detail="LTI class is missing context_memberships_url",
        )

    @staticmethod
    def _merge_query_param(url: str, key: str, value: str) -> str:
        parsed = urlparse(url)
        query_items = dict(parse_qsl(parsed.query, keep_blank_values=True))
        query_items[key] = value
        updated_query = urlencode(query_items)
        return urlunparse(
            (
                parsed.scheme,
                parsed.netloc,
                parsed.path,
                parsed.params,
                updated_query,
                parsed.fragment,
            )
        )

    @staticmethod
    def _extract_next_page_url(
        response: aiohttp.ClientResponse, payload: dict[str, object]
    ) -> str | None:
        next_page = payload.get(NRPS_NEXT_PAGE_KEY)
        if isinstance(next_page, str) and next_page:
            return next_page

        link_header = response.headers.get("Link")
        if not link_header:
            return None
        links = link_header.split(",")
        for link in links:
            if 'rel="next"' in link:
                next_url = link[link.find("<") + 1 : link.find(">")]
                return next_url if next_url else None
        return None

    async def _make_authed_nrps_get(
        self,
        url: str,
    ) -> tuple[dict[str, object], str | None]:
        http_session = self._require_http_session()
        security_settings = _require_lti_security()
        redirects_allowed = _allow_redirects_or_raise(
            security_settings.names_and_role_endpoint
        )

        try:
            generated_url = generate_names_and_role_api_url(url)
        except ValueError as e:
            raise CourseBridgeException(
                detail=f"Invalid NRPS URL: {e!s}",
            ) from e
        access_token = await self.get_short_lived_auth_token()
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Accept": NRPS_MEMBERSHIP_CONTAINER_CONTENT_TYPE,
        }
        try:
            async with request_with_validated_redirects(
                session=http_session,
                method="GET",
                url=generated_url,
                validate_redirect_url=partial(
                    generate_names_and_role_api_url, validation_mode="redirect"
                ),
                redirects_allowed=redirects_allowed,
                headers=headers,
            ) as response:
                response_payload: object = None
                try:
                    response_payload = await response.json(content_type=None)
                except (
                    json.JSONDecodeError,
                    ValueError,
                    aiohttp.ContentTypeError,
                ) as e:
                    logger.warning(
                        "Failed to parse NRPS response payload as JSON: %s", e
                    )
                    response_payload = None

                if response.status >= 400:
                    detail = _extract_error_detail(response_payload)
                    if not detail:
                        detail = (await response.text()).strip()
                    raise CourseBridgeException(
                        detail=detail or "Failed to fetch NRPS page",
                    )

                response_payload_dict = _as_dict(response_payload)
                if response_payload_dict is None:
                    raise CourseBridgeException(
                        detail="Invalid NRPS response payload",
                    )

                next_page_url = self._extract_next_page_url(
                    response, response_payload_dict
                )
                return response_payload_dict, next_page_url
        except ValueError as e:
            raise CourseBridgeException(detail=f"Invalid NRPS URL: {e!s}") from e
        except aiohttp.TooManyRedirects as e:
            raise CourseBridgeException(
                detail="Too many redirects for NRPS endpoint",
            ) from e

    async def _request_all_nrps_pages(
        self, start_url: str
    ) -> AsyncIterator[dict[str, object]]:
        next_page: str | None = start_url
        seen_pages: set[str] = set()
        while next_page:
            try:
                normalized_next_page = generate_names_and_role_api_url(next_page)
            except ValueError as e:
                raise CourseBridgeException(
                    detail=f"Invalid NRPS URL: {e!s}",
                ) from e

            if normalized_next_page in seen_pages:
                logger.warning(
                    "Detected NRPS pagination loop for lti_class_id=%s at url=%s",
                    self.lti_class_id,
                    normalized_next_page,
                )
                raise CourseBridgeException(
                    detail="NRPS pagination loop detected while fetching memberships",
                )
            seen_pages.add(normalized_next_page)
            response_payload, next_page = await self._make_authed_nrps_get(
                normalized_next_page
            )
            yield response_payload

    @staticmethod
    def _get_member_roles(roles: object) -> ClassUserRoles | None:
        return class_user_roles_from_lti_roles(roles)

    @staticmethod
    def _role_priority(roles: ClassUserRoles) -> int:
        if roles.admin:
            return 3
        if roles.teacher:
            return 2
        if roles.student:
            return 1
        return 0

    def _member_dict_to_create_user_class_role(
        self,
        member_dict: dict[str, object],
        sso_value: str | None = None,
    ) -> CreateUserClassRole | None:
        status = member_dict.get(NRPS_MEMBER_STATUS_KEY)
        if not isinstance(status, str) or status.lower() != NRPS_MEMBER_ACTIVE_STATUS:
            return None

        email = member_dict.get(NRPS_MEMBER_EMAIL_KEY)
        if not isinstance(email, str) or not email:
            return None
        email = email.strip()
        if not email:
            return None

        class_roles = self._get_member_roles(member_dict.get(NRPS_MEMBER_ROLES_KEY))
        if class_roles is None:
            return None

        display_name = member_dict.get(NRPS_MEMBER_NAME_KEY)

        return CreateUserClassRole(
            email=email,
            display_name=display_name if isinstance(display_name, str) else None,
            sso_id=sso_value,
            roles=class_roles,
        )

    @staticmethod
    def _extract_member_custom_claim(
        member: dict[str, object],
    ) -> dict[str, object] | None:
        message_items = member.get(NRPS_MEMBER_MESSAGE_KEY)
        if not isinstance(message_items, list):
            return None
        for item in message_items:
            item_dict = _as_dict(item)
            if item_dict is None:
                continue
            custom_claim = _as_dict(item_dict.get(LTI_CLAIM_CUSTOM_KEY))
            if custom_claim is not None:
                return custom_claim
        return None

    @staticmethod
    def _parse_sso_provider_id(value: object) -> int | None:
        if value is None:
            return None
        if isinstance(value, int):
            return value
        if isinstance(value, str):
            value = value.strip()
            if not value:
                return None
            try:
                return int(value)
            except ValueError:
                return None
        return None

    def _extract_member_sso(
        self, member: dict[str, object]
    ) -> tuple[int | None, str | None]:
        custom_claim = self._extract_member_custom_claim(member)
        if custom_claim is None:
            return None, None

        sso_provider_id = self._parse_sso_provider_id(
            custom_claim.get(LTI_CUSTOM_SSO_PROVIDER_ID_KEY)
        )
        if sso_provider_id is None or sso_provider_id <= 0:
            return None, None

        sso_value = custom_claim.get(LTI_CUSTOM_SSO_VALUE_KEY)
        if not isinstance(sso_value, str):
            return sso_provider_id, None
        sso_value = sso_value.strip()
        if not sso_value or sso_value.startswith("$"):
            return sso_provider_id, None
        return sso_provider_id, sso_value

    async def get_resource_link_id(
        self, allow_nrps_context_fallback: bool = False
    ) -> str | None:
        lti_class = await self._get_lti_class()
        existing_resource_link_id = lti_class.resource_link_id
        if isinstance(existing_resource_link_id, str) and existing_resource_link_id:
            return existing_resource_link_id

        if not allow_nrps_context_fallback:
            return None

        # One-time fallback for legacy rows: use NRPS context.id to scope this sync only.
        # Do not persist this value to LTIClass.resource_link_id.
        self._require_http_session()
        context_memberships_url = await self.get_context_memberships_url()
        response_payload, _ = await self._make_authed_nrps_get(context_memberships_url)
        context_payload = _as_dict(response_payload.get(NRPS_CONTEXT_KEY))
        if context_payload is None:
            logger.warning(
                "NRPS response missing context for transient resource-link fallback (lti_class_id=%s)",
                self.lti_class_id,
            )
            return None

        context_id = context_payload.get(NRPS_CONTEXT_ID_KEY)
        if not isinstance(context_id, str) or not context_id:
            logger.warning(
                "NRPS response missing context.id for transient resource-link fallback (lti_class_id=%s)",
                self.lti_class_id,
            )
            return None
        return context_id

    async def get_nrps_create_user_class_roles(self) -> CreateUserClassRoles:
        lti_class = await self._get_lti_class()
        context_memberships_url = await self.get_context_memberships_url()
        resource_link_id = await self.get_resource_link_id()
        if resource_link_id is None:
            resource_link_id = await self.get_resource_link_id(
                allow_nrps_context_fallback=True
            )
        memberships_url = context_memberships_url
        if resource_link_id:
            memberships_url = self._merge_query_param(
                context_memberships_url,
                NRPS_RESOURCE_LINK_QUERY_KEY,
                resource_link_id,
            )

        unique_users: dict[str, CreateUserClassRole] = {}
        sso_provider_ids: set[int] = set()
        async for response_payload in self._request_all_nrps_pages(memberships_url):
            members = response_payload.get(NRPS_MEMBERS_KEY, [])
            if members is None:
                members = []
            if not isinstance(members, list):
                raise CourseBridgeException(detail="NRPS response has invalid members")

            for member in members:
                member_dict = _as_dict(member)
                if member_dict is None:
                    continue
                member_sso_provider_id, member_sso_value = self._extract_member_sso(
                    member_dict
                )
                user_role = self._member_dict_to_create_user_class_role(
                    member_dict, member_sso_value
                )
                if user_role is None:
                    continue
                if member_sso_provider_id is not None:
                    sso_provider_ids.add(member_sso_provider_id)

                key = user_role.email.lower()
                existing = unique_users.get(key)
                if existing is None:
                    unique_users[key] = user_role
                    continue

                existing_priority = self._role_priority(existing.roles)
                current_priority = self._role_priority(user_role.roles)
                if current_priority > existing_priority:
                    unique_users[key] = user_role
                elif (
                    current_priority == existing_priority and not existing.display_name
                ):
                    unique_users[key] = user_role

        sso_tenant = None
        if sso_provider_ids:
            if len(sso_provider_ids) > 1:
                raise CourseBridgeException(
                    detail="NRPS response contains multiple sso_provider_id values",
                )

            sso_provider_id = next(iter(sso_provider_ids))
            provider = await ExternalLoginProvider.get_by_id(self.db, sso_provider_id)
            if provider is None:
                raise CourseBridgeException(
                    detail=f"Unknown SSO provider id in NRPS response: {sso_provider_id}",
                )
            sso_tenant = provider.name

        return CreateUserClassRoles(
            roles=list(unique_users.values()),
            silent=True,
            lms_type=LMSType.from_lti_platform(lti_class.lti_platform),
            lti_class_id=lti_class.id,
            sso_tenant=sso_tenant,
        )

    async def _get_sync_context(self) -> tuple[LTIClass, int, int]:
        lti_class = await self._get_lti_class()

        class_id = lti_class.class_id
        if not isinstance(class_id, int):
            raise CourseBridgeException(
                detail="LTI class is not linked to a PingPong class",
            )

        setup_user_id = lti_class.setup_user_id
        if not isinstance(setup_user_id, int):
            raise CourseBridgeException(
                detail="LTI class is missing setup_user_id",
            )

        return lti_class, class_id, setup_user_id

    async def _mark_sync_success(self, lti_class: LTIClass) -> None:
        lti_class.last_synced = self.nowfn()
        lti_class.last_sync_error = None
        lti_class.lti_status = LTIStatus.LINKED
        self.db.add(lti_class)
        await self.db.flush()

    async def _mark_sync_error(
        self, lti_class: LTIClass, detail: str | None = None
    ) -> None:
        lti_class.last_sync_error = detail or "CourseBridge sync failed"
        lti_class.lti_status = LTIStatus.ERROR
        self.db.add(lti_class)
        await self.db.flush()

    def _sync_allowed(self, last_synced: datetime | None, now: datetime) -> None:
        """Guard whether sync should proceed.

        Implementations should raise an exception (typically CourseBridgeWarning)
        when sync must be blocked; otherwise they should simply return.
        """
        raise NotImplementedError(
            "CourseBridgeClient subclasses must implement _sync_allowed"
        )

    async def _update_user_roles(
        self,
        class_id: int,
        setup_user_id: int,
        new_ucr: CreateUserClassRoles,
    ) -> CreateUserResults:
        raise NotImplementedError(
            "CourseBridgeClient subclasses must implement _update_user_roles"
        )

    def _raise_sync_error_if_manual(self) -> None:
        raise NotImplementedError(
            "CourseBridgeClient subclasses must implement _raise_sync_error_if_manual"
        )

    async def sync_roster(self) -> CreateUserResults:
        lti_class, class_id, setup_user_id = await self._get_sync_context()
        self._sync_allowed(lti_class.last_synced, self.nowfn())

        try:
            new_ucr = await self.get_nrps_create_user_class_roles()
            results = await self._update_user_roles(class_id, setup_user_id, new_ucr)
            row_errors = _extract_sync_row_errors(results)
            if row_errors:
                displayed_row_errors = "; ".join(
                    row_errors[:SYNC_ROW_ERROR_DETAIL_LIMIT]
                )
                overflow_count = len(row_errors) - SYNC_ROW_ERROR_DETAIL_LIMIT
                overflow_suffix = (
                    f"; and {overflow_count} more row errors"
                    if overflow_count > 0
                    else ""
                )
                raise CourseBridgeException(
                    detail=(
                        f"CourseBridge sync had {len(row_errors)} failed roster updates: "
                        f"{displayed_row_errors}{overflow_suffix}"
                    )
                )
        except (CourseBridgeWarning, CourseBridgeGlobalException):
            raise
        except Exception as e:
            await self._mark_sync_error(lti_class, exception_detail(e))
            self._raise_sync_error_if_manual()
            raise

        await self._mark_sync_success(lti_class)
        return results

    def _has_valid_cached_nrps_access_token(self) -> bool:
        if self._cached_nrps_access_token is None:
            return False
        if self._cached_nrps_access_token_valid_until is None:
            return False
        return (
            int(self.nowfn().timestamp()) < self._cached_nrps_access_token_valid_until
        )

    def _cache_nrps_access_token(self, token: CourseBridgeAccessToken) -> None:
        now_ts = int(self.nowfn().timestamp())
        expires_in = token.expires_in
        if expires_in is None:
            valid_for = NRPS_ACCESS_TOKEN_FALLBACK_TTL_SECONDS
        else:
            valid_for = max(expires_in - NRPS_ACCESS_TOKEN_REFRESH_BUFFER_SECONDS, 0)

        self._cached_nrps_access_token = token
        self._cached_nrps_access_token_valid_until = now_ts + valid_for

    async def _request_nrps_access_token(self) -> CourseBridgeAccessToken:
        http_session = self._require_http_session()
        security_settings = _require_lti_security()

        lti_class = await self._get_lti_class()
        registration = lti_class.registration
        client_id = registration.client_id
        if not isinstance(client_id, str) or not client_id:
            raise CourseBridgeException(
                detail="LTI registration is missing a client_id",
            )

        token_endpoint = self._get_token_endpoint(registration)
        try:
            generated_token_endpoint = generate_token_endpoint_url(token_endpoint)
        except ValueError as e:
            raise CourseBridgeException(
                detail=f"Invalid token endpoint URL: {e!s}",
            ) from e
        client_assertion = await self._build_client_assertion(
            client_id, generated_token_endpoint
        )

        request_data = {
            "client_id": client_id,
            "client_assertion_type": CLIENT_ASSERTION_TYPE,
            "grant_type": CLIENT_CREDENTIALS_GRANT_TYPE,
            "client_assertion": client_assertion,
            "scope": NRPS_CONTEXT_MEMBERSHIP_SCOPE,
        }
        redirects_allowed = _allow_redirects_or_raise(security_settings.token_endpoint)
        response_payload: object = None
        try:
            async with request_with_validated_redirects(
                session=http_session,
                method="POST",
                url=generated_token_endpoint,
                validate_redirect_url=partial(
                    generate_token_endpoint_url, validation_mode="redirect"
                ),
                redirects_allowed=redirects_allowed,
                headers={"Content-Type": TOKEN_REQUEST_CONTENT_TYPE},
                data=request_data,
            ) as response:
                try:
                    response_payload = await response.json(content_type=None)
                except Exception:
                    response_payload = None

                if response.status >= 400:
                    detail = _extract_error_detail(response_payload)
                    if not detail:
                        detail = (await response.text()).strip()
                    raise CourseBridgeException(
                        detail=detail or "Failed to request NRPS access token",
                    )
        except ValueError as e:
            raise CourseBridgeException(
                detail=f"Invalid token endpoint URL: {e!s}",
            ) from e
        except aiohttp.TooManyRedirects as e:
            raise CourseBridgeException(
                detail="Too many redirects for token endpoint",
            ) from e

        response_payload_dict = _as_dict(response_payload)
        if response_payload_dict is None:
            raise CourseBridgeException(
                detail="Invalid token response payload",
            )

        access_token = response_payload_dict.get("access_token")
        if not isinstance(access_token, str) or not access_token:
            raise CourseBridgeException(
                detail="Token endpoint response is missing access_token",
            )

        token_type = response_payload_dict.get("token_type")
        scope = response_payload_dict.get("scope")

        return CourseBridgeAccessToken(
            access_token=access_token,
            expires_in=_as_optional_int(response_payload_dict.get("expires_in")),
            token_type=token_type if isinstance(token_type, str) else None,
            scope=scope if isinstance(scope, str) else None,
        )

    async def get_nrps_access_token(self) -> CourseBridgeAccessToken:
        if self._has_valid_cached_nrps_access_token():
            cached_token = self._cached_nrps_access_token
            if cached_token is not None:
                return cached_token

        token = await self._request_nrps_access_token()
        self._cache_nrps_access_token(token)
        return token

    async def get_short_lived_auth_token(self) -> str:
        token = await self.get_nrps_access_token()
        return token.access_token


class ManualCourseBridgeClient(CourseBridgeClient):
    def __init__(
        self,
        lti_class_id: int,
        request: StateRequest,
        tasks: BackgroundTasks,
        key_manager: LTIKeyManager | None = None,
        nowfn: NowFn = utcnow,
    ):
        super().__init__(
            db=request.state["db"],
            lti_class_id=lti_class_id,
            key_manager=key_manager,
            nowfn=nowfn,
        )
        self.request = request
        self.tasks = tasks

    def _sync_allowed(self, last_synced: datetime | None, now: datetime) -> None:
        lti_settings = config.lti
        sync_wait_seconds = (
            lti_settings.sync_wait
            if lti_settings is not None
            else COURSE_BRIDGE_SYNC_WAIT_DEFAULT_SECONDS
        )
        if last_synced and last_synced + timedelta(seconds=sync_wait_seconds) > now:
            time_remaining = (
                last_synced + timedelta(seconds=sync_wait_seconds) - now
            ).total_seconds() + 1
            raise CourseBridgeWarning(
                detail=(
                    "A roster sync through CourseBridge was recently completed. "
                    "Please wait before trying again. You can request a manual sync in "
                    f"{convert_seconds(int(time_remaining)) if int(time_remaining) > 60 else 'a minute'}."
                ),
            )

    async def _update_user_roles(
        self,
        class_id: int,
        setup_user_id: int,
        new_ucr: CreateUserClassRoles,
    ) -> CreateUserResults:
        return await AddNewUsersManual(
            str(class_id),
            new_ucr,
            self.request,
            self.tasks,
            user_id=setup_user_id,
        ).add_new_users()

    def _raise_sync_error_if_manual(self) -> None:
        raise CourseBridgeException(
            detail="Syncing your roster through CourseBridge failed. Please try again later.",
        )


class ScriptCourseBridgeClient(CourseBridgeClient):
    def __init__(
        self,
        db: AsyncSession,
        client: OpenFgaAuthzClient,
        lti_class_id: int,
        key_manager: LTIKeyManager | None = None,
        nowfn: NowFn = utcnow,
    ):
        super().__init__(
            db=db,
            lti_class_id=lti_class_id,
            key_manager=key_manager,
            nowfn=nowfn,
        )
        self.client = client

    def _sync_allowed(self, last_synced: datetime | None, now: datetime) -> None:
        # Background script syncs are not rate-limited.
        pass

    async def _update_user_roles(
        self,
        class_id: int,
        setup_user_id: int,
        new_ucr: CreateUserClassRoles,
    ) -> CreateUserResults:
        return await AddNewUsersScript(
            class_id=str(class_id),
            user_id=setup_user_id,
            session=self.db,
            client=self.client,
            new_ucr=new_ucr,
        ).add_new_users()

    def _raise_sync_error_if_manual(self) -> None:
        return None


async def course_bridge_sync_all(
    session: AsyncSession,
    authz_client: OpenFgaAuthzClient,
    sync_classes_with_error_status: bool = False,
) -> None:
    async for lti_class in LTIClass.get_all_to_sync(
        session, sync_classes_with_error_status=sync_classes_with_error_status
    ):
        logger.info(f"Syncing LTI class {lti_class.id}...")
        async with session.begin_nested() as savepoint:
            try:
                async with ScriptCourseBridgeClient(
                    db=session,
                    client=authz_client,
                    lti_class_id=lti_class.id,
                ) as client:
                    await client.sync_roster()
            except Exception as e:
                logger.exception(f"Error syncing LTI class {lti_class.id}: {e}")
                await savepoint.rollback()

                if isinstance(e, CourseBridgeGlobalException):
                    continue

                # sync_roster() already marks the class as errored, but that write is part
                # of the rolled-back savepoint above. Re-apply the error marker outside the
                # savepoint so the class retains an actionable failure state.
                lti_class.lti_status = LTIStatus.ERROR
                lti_class.last_sync_error = exception_detail(e)
                session.add(lti_class)

    await session.commit()
