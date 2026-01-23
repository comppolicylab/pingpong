"""FastAPI routes for LTI Advantage Service."""

import json
import logging
from datetime import datetime
from typing import Any, cast
from urllib.parse import urlencode
import aiohttp
import jwt
from fastapi import APIRouter, BackgroundTasks, HTTPException, Depends, Request
from fastapi.responses import RedirectResponse

from pingpong.auth import encode_session_token
from pingpong.authz.openfga import OpenFgaAuthzClient
from pingpong.config import config
from pingpong.invite import send_lti_registration_submitted
from pingpong.lti.lti_course import (
    find_class_by_course_id,
    find_class_by_course_id_search_by_canvas_account_lti_guid,
)
from pingpong.lti.schemas import (
    LTIRegisterRequest,
    LTIPublicInstitutions,
    LTIPublicSSOProviders,
    LTISetupContext,
    LTISetupInstitution,
    LTILinkableGroup,
    LTILinkableGroupsResponse,
    LTISetupCreateRequest,
    LTISetupCreateResponse,
    LTISetupLinkRequest,
    LTISetupLinkResponse,
)
from pingpong.models import (
    Class,
    ExternalLogin,
    ExternalLoginProvider,
    Institution,
    LTIClass,
    LTIRegistration,
    LTIOIDCSession,
    User,
    UserClassRole,
)
from pingpong.server import get_now_fn
from pingpong.users import AddNewUsersManual, AddUserException
from pingpong.permission import LoggedIn
from .key_manager import LTIKeyManager
from pingpong.schemas import (
    ClassUserRoles,
    CreateUserClassRole,
    CreateUserClassRoles,
    ExternalLoginProviders,
    LMSPlatform,
    LTIRegistrationReviewStatus,
    LTIStatus,
    UserState,
)

logger = logging.getLogger(__name__)

lti_router: APIRouter = APIRouter()

SSO_FIELD_FULL_NAME: dict[str, str] = {
    "canvas.sisIntegrationId": "Canvas.user.sisIntegrationId",
    "canvas.sisSourceId": "Canvas.user.sisSourceId",
    "person.sourcedId": "Person.sourcedId",
}

ISSUER_KEY = "issuer"
AUTHORIZATION_ENDPOINT_KEY = "authorization_endpoint"
REGISTRATION_ENDPOINT_KEY = "registration_endpoint"
KEYS_ENDPOINT_KEY = "jwks_uri"
TOKEN_ENDPOINT_KEY = "token_endpoint"
SCOPES_SUPPORTED_KEY = "scopes_supported"
TOKEN_ALG_KEY = "id_token_signing_alg_values_supported"
SUBJECT_TYPES_KEY = "subject_types_supported"

PLATFORM_CONFIGURATION_KEY = (
    "https://purl.imsglobal.org/spec/lti-platform-configuration"
)
MESSAGE_TYPES_KEY = "messages_supported"
MESSAGE_TYPE = "LtiResourceLinkRequest"
CANVAS_MESSAGE_PLACEMENT = "https://canvas.instructure.com/lti/course_navigation"

CANVAS_ACCOUNT_NAME_KEY = "https://canvas.instructure.com/lti/account_name"
CANVAS_ACCOUNT_LTI_GUID_KEY = "https://canvas.instructure.com/lti/account_lti_guid"

REQUIRED_SCOPES = [
    "https://purl.imsglobal.org/spec/lti-nrps/scope/contextmembership.readonly"
]

LTI_DEPLOYMENT_ID_CLAIM = "https://purl.imsglobal.org/spec/lti/claim/deployment_id"

LTI_CUSTOM_PARAM_DEFAULT_VALUES = {
    "sso_provider_id": ["0"],
    "sso_value": [""] + [f"${field}" for field in SSO_FIELD_FULL_NAME.values()],
    "canvas_course_id": ["$Canvas.course.id"],
    "canvas_term_name": ["$Canvas.term.name"],
}


async def _fetch_jwks(jwks_url: str) -> dict[str, Any]:
    timeout = aiohttp.ClientTimeout(total=10)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.get(jwks_url, raise_for_status=True) as response:
            payload = await response.json()
            if not isinstance(payload, dict):
                raise HTTPException(status_code=500, detail="Invalid JWKS response")
            return cast(dict[str, Any], payload)


def _select_jwk(jwks: dict[str, Any], kid: str | None) -> dict[str, Any]:
    keys = jwks.get("keys")
    if not isinstance(keys, list) or not keys:
        raise HTTPException(status_code=500, detail="Invalid JWKS (missing keys)")

    if kid:
        for key in keys:
            if isinstance(key, dict) and key.get("kid") == kid:
                return cast(dict[str, Any], key)
        raise HTTPException(status_code=400, detail="Unknown JWT key id (kid)")

    if len(keys) == 1 and isinstance(keys[0], dict):
        return cast(dict[str, Any], keys[0])

    raise HTTPException(status_code=400, detail="Missing JWT key id (kid)")


async def _verify_lti_id_token(
    *,
    id_token: str,
    jwks_url: str,
    expected_issuer: str,
    expected_audience: str,
    expected_algorithm: str,
) -> dict[str, Any]:
    try:
        header = jwt.get_unverified_header(id_token)
    except jwt.PyJWTError as e:
        raise HTTPException(status_code=400, detail="Invalid id_token header") from e

    if header.get("typ") not in (None, "JWT", "at+jwt"):
        raise HTTPException(status_code=400, detail="Invalid id_token type")

    alg = header.get("alg")
    if not isinstance(alg, str) or not alg:
        raise HTTPException(status_code=400, detail="Invalid id_token algorithm")
    if alg != expected_algorithm:
        raise HTTPException(status_code=400, detail="Unexpected id_token algorithm")

    kid = header.get("kid")
    if kid is not None and not isinstance(kid, str):
        raise HTTPException(status_code=400, detail="Invalid id_token kid")

    jwks = await _fetch_jwks(jwks_url)
    jwk = _select_jwk(jwks, kid)
    try:
        public_key = jwt.algorithms.RSAAlgorithm.from_jwk(json.dumps(jwk))
    except Exception as e:
        raise HTTPException(status_code=500, detail="Invalid JWKS key material") from e

    try:
        claims = jwt.decode(
            id_token,
            key=public_key,
            algorithms=[expected_algorithm],
            audience=expected_audience,
            issuer=expected_issuer,
            options={
                "require": ["exp", "iat", "iss", "aud", "nonce"],
            },
            leeway=60,
        )
    except jwt.PyJWTError as e:
        raise HTTPException(status_code=400, detail="Invalid id_token") from e

    if not isinstance(claims, dict):
        raise HTTPException(status_code=400, detail="Invalid id_token claims")
    return cast(dict[str, Any], claims)


def get_lti_key_manager() -> LTIKeyManager:
    """Get the LTI key manager from config."""
    lti_settings = config.lti
    if lti_settings is None:
        raise HTTPException(status_code=404, detail="LTI service not enabled")
    return lti_settings.key_store.key_manager


@lti_router.get("/.well-known/jwks.json")
async def get_jwks(key_manager: LTIKeyManager = Depends(get_lti_key_manager)):
    """
    Get the JSON Web Key Set (JWKS) containing all valid public keys.

    This endpoint provides the public keys that LTI platforms can use to verify
    JWTs signed by this tool. The endpoint returns the last 3 valid keys as
    specified in the LTI Advantage specification.
    """
    try:
        jwks = await key_manager.get_public_keys_jwks()
        return jwks
    except Exception as e:
        logger.error(f"Error serving JWKS: {e}")
        raise HTTPException(status_code=500, detail="Error retrieving public keys")


@lti_router.get("/sso/providers", response_model=ExternalLoginProviders)
async def get_sso_ids(request: Request):
    """
    Get the SSO identifiers for the LTI instance.
    """
    external_login_providers = await ExternalLoginProvider.get_all(request.state.db)
    no_email_providers = [
        provider for provider in external_login_providers if provider.name != "email"
    ]
    return {"providers": no_email_providers}


@lti_router.get("/public/sso/providers", response_model=LTIPublicSSOProviders)
async def get_public_sso_providers(request: Request):
    providers = await ExternalLoginProvider.get_all(request.state.db)
    return {
        "providers": [
            {"id": p.id, "name": p.name, "display_name": p.display_name}
            for p in providers
            if p.name != "email"
        ]
    }


@lti_router.get("/public/institutions", response_model=LTIPublicInstitutions)
async def get_public_institutions(request: Request):
    institutions = await Institution.get_all_with_default_api_key(request.state.db)
    return {
        "institutions": [{"id": inst.id, "name": inst.name} for inst in institutions]
    }


@lti_router.post("/register")
async def register_lti_instance(request: Request, data: LTIRegisterRequest):
    """
    Register a new LTI instance.
    """
    if not data.openid_configuration or not data.registration_token:
        raise HTTPException(
            status_code=400, detail="Missing openid_configuration or registration_token"
        )

    if not data.institution_ids:
        raise HTTPException(
            status_code=400, detail="At least one institution must be selected"
        )

    if data.provider_id == 0:
        if data.sso_field is not None:
            raise HTTPException(
                status_code=400, detail="SSO field must be null when no SSO is selected"
            )
    elif data.sso_field is None:
        raise HTTPException(
            status_code=400, detail="SSO field is required when SSO is selected"
        )

    # Validate that all selected institutions have a default API key
    if not await Institution.all_have_default_api_key(
        request.state.db, data.institution_ids
    ):
        raise HTTPException(
            status_code=400,
            detail="All selected institutions must have a default API key configured",
        )

    sso_field_full_name = (
        None if data.sso_field is None else SSO_FIELD_FULL_NAME[data.sso_field]
    )

    headers = {"Authorization": f"Bearer {data.registration_token}"}

    response_data: dict[str, Any] | None = None
    async with aiohttp.ClientSession() as session:
        async with session.get(
            data.openid_configuration, raise_for_status=True, headers=headers
        ) as response:
            payload = await response.json()
            if not isinstance(payload, dict):
                raise HTTPException(
                    status_code=500,
                    detail="Invalid OpenID configuration response payload",
                )
            response_data = cast(dict[str, Any], payload)

    if not response_data:
        raise HTTPException(
            status_code=500, detail="Failed to fetch OpenID configuration"
        )

    issuer = response_data.get(ISSUER_KEY)
    authorization_endpoint = response_data.get(AUTHORIZATION_ENDPOINT_KEY)
    registration_endpoint = response_data.get(REGISTRATION_ENDPOINT_KEY)
    keys_endpoint = response_data.get(KEYS_ENDPOINT_KEY)
    token_endpoint = response_data.get(TOKEN_ENDPOINT_KEY)
    scopes_supported = response_data.get(SCOPES_SUPPORTED_KEY, [])
    token_algorithms = response_data.get(TOKEN_ALG_KEY, [])
    subject_types = response_data.get(SUBJECT_TYPES_KEY, [])

    platform_config = response_data.get(PLATFORM_CONFIGURATION_KEY)
    if not isinstance(platform_config, dict):
        raise HTTPException(
            status_code=400, detail="Missing platform configuration in OpenID response"
        )

    product_family_code = platform_config.get("product_family_code")

    # Check that the product family code exists in schema.LMSPlatform
    if product_family_code not in {platform.value for platform in LMSPlatform}:
        raise HTTPException(status_code=400, detail="Invalid product family")

    platform = LMSPlatform(product_family_code)

    if (
        not issuer
        or not authorization_endpoint
        or not registration_endpoint
        or not keys_endpoint
        or not token_endpoint
    ):
        raise HTTPException(
            status_code=400, detail="Missing required OpenID configuration fields"
        )

    if not all(scope in scopes_supported for scope in REQUIRED_SCOPES):
        raise HTTPException(
            status_code=400, detail="Missing required scopes in OpenID configuration"
        )

    message_types_supported = platform_config.get(MESSAGE_TYPES_KEY, [])
    if not any(msg.get("type") == MESSAGE_TYPE for msg in message_types_supported):
        raise HTTPException(
            status_code=400, detail="LtiResourceLinkRequest not supported by platform"
        )

    if not any(
        CANVAS_MESSAGE_PLACEMENT in msg.get("placements", [])
        for msg in message_types_supported
        if msg.get("type") == MESSAGE_TYPE
    ):
        raise HTTPException(
            status_code=400,
            detail="Canvas course navigation placement not supported by platform",
        )

    if "RS256" not in token_algorithms:
        raise HTTPException(
            status_code=400, detail="RS256 not supported for ID token signing"
        )

    if "public" not in subject_types:
        raise HTTPException(status_code=400, detail="public subject type not supported")

    canvas_account_name = platform_config.get(CANVAS_ACCOUNT_NAME_KEY)
    canvas_account_lti_guid = platform_config.get(CANVAS_ACCOUNT_LTI_GUID_KEY)

    tool_registration_data = {
        "application_type": "web",
        "grant_types": ["client_credentials", "implicit"],
        "initiate_login_uri": config.url("/api/v1/lti/login"),
        "redirect_uris": [config.url("/api/v1/lti/launch")],
        "response_types": ["id_token"],
        "client_name": "PingPong",
        "jwks_uri": config.url("/api/v1/lti/.well-known/jwks.json"),
        "token_endpoint_auth_method": "private_key_jwt",
        "logo_uri": config.url("/pingpong_icon_2x.png"),
        "scope": " ".join(REQUIRED_SCOPES + ["openid"]),
        "https://purl.imsglobal.org/spec/lti-tool-configuration": {
            "domain": config.public_url.replace("https://", "")
            .replace("http://", "")
            .replace("/", ""),
            "target_link_uri": config.url("/api/v1/lti/launch"),
            "description": "A platform carefully designed for AI-driven learning.",
            "custom_parameters": {
                "platform": platform.value,
                "pingpong_lti_tool_version": "1.0",
                "sso_provider_id": str(data.provider_id),
                "sso_value": f"${sso_field_full_name}" if sso_field_full_name else "",
            },
            "claims": [
                "sub",
                "iss",
                "given_name",
                "family_name",
                "email",
                "https://purl.imsglobal.org/spec/lti/claim/context",
                "https://purl.imsglobal.org/spec/lti/claim/roles",
                "https://purl.imsglobal.org/spec/lti/claim/resource_link",
                "https://purl.imsglobal.org/spec/lti/claim/tool_platform",
                "https://purl.imsglobal.org/spec/lti-nrps/claim/namesroleservice",
            ],
            "https://canvas.instructure.com/lti/vendor": "Computational Policy Lab",
            "messages": [
                {
                    "type": MESSAGE_TYPE,
                    "target_link_uri": config.url("/api/v1/lti/launch"),
                    "label": "PingPong",
                    "placements": ["course_navigation"],
                    "custom_parameters": {
                        "placement": "course_navigation",
                        "canvas_course_id": "$Canvas.course.id",
                        "canvas_term_name": "$Canvas.term.name",
                    },
                    "https://canvas.instructure.com/lti/display_type": "full_width_in_context",
                    "https://canvas.instructure.com/lti/course_navigation/default_enabled": data.show_in_course_navigation,
                    "https://canvas.instructure.com/lti/visibility": "members",
                }
            ],
        },
    }

    registration_response_data: dict[str, Any] | None = None
    async with aiohttp.ClientSession() as session:
        try:
            async with session.post(
                registration_endpoint,
                raise_for_status=True,
                headers={
                    "Authorization": f"Bearer {data.registration_token}",
                    "Content-Type": "application/json",
                },
                json=tool_registration_data,
            ) as response:
                payload = await response.json()
                if not isinstance(payload, dict):
                    raise HTTPException(
                        status_code=500,
                        detail="Invalid registration endpoint response payload",
                    )
                registration_response_data = cast(dict[str, Any], payload)
        except aiohttp.ClientResponseError as e:
            logger.error(f"Error during LTI tool registration: {e.status} {e.message}")
            raise HTTPException(
                status_code=e.status,
                detail=f"Failed to create registration: {e.message}",
            )

    if not registration_response_data:
        raise HTTPException(status_code=500, detail="Failed to create registration")

    client_id = registration_response_data.get("client_id")
    if not isinstance(client_id, str) or not client_id:
        raise HTTPException(
            status_code=500, detail="Missing client_id in registration response"
        )

    new_registration = {
        "issuer": issuer,
        "registration_data": json.dumps(registration_response_data),
        "openid_configuration": json.dumps(response_data),
        "client_id": client_id,
        "auth_login_url": authorization_endpoint,
        "auth_token_url": token_endpoint,
        "key_set_url": keys_endpoint,
        "lms_platform": platform,
        "token_algorithm": "RS256",
        "canvas_account_name": canvas_account_name,
        "canvas_account_lti_guid": canvas_account_lti_guid,
        "admin_name": data.admin_name,
        "admin_email": data.admin_email,
        "friendly_name": data.name,
    }

    await LTIRegistration.create(
        request.state.db, new_registration, data.institution_ids
    )

    try:
        await send_lti_registration_submitted(
            config.email.sender,
            admin_email=data.admin_email,
            admin_name=data.admin_name,
            integration_name=data.name,
        )
    except Exception:
        logger.exception(
            f"Failed to send LTI registration submitted email: {data.admin_email}",
        )

    return {"status": "ok"}


@lti_router.api_route("/login", methods=["GET", "POST"])
async def lti_login(request: Request):
    """Handle LTI login requests.

    Receives an OIDC initiation request from the platform and responds with a browser redirect
    to the platform's OIDC authorization endpoint.
    """
    if request.method == "GET":
        payload = request.query_params
    else:
        payload = await request.form()

    client_id = payload.get("client_id")
    if not isinstance(client_id, str) or not client_id:
        raise HTTPException(status_code=400, detail="Missing or invalid client_id")

    iss = payload.get("iss")
    if not isinstance(iss, str) or not iss:
        raise HTTPException(status_code=400, detail="Missing or invalid iss")

    registration = await LTIRegistration.get_by_client_id(request.state.db, client_id)
    if registration is None:
        raise HTTPException(status_code=404, detail="Unknown LTI client_id")

    if registration.issuer != iss:
        raise HTTPException(status_code=400, detail="Issuer mismatch for client_id")

    login_hint = payload.get("login_hint")
    if not isinstance(login_hint, str) or not login_hint:
        raise HTTPException(status_code=400, detail="Missing or invalid login_hint")

    target_link_uri = payload.get("target_link_uri")
    if not isinstance(target_link_uri, str) or not target_link_uri:
        raise HTTPException(
            status_code=400, detail="Missing or invalid target_link_uri"
        )

    lti_message_hint = payload.get("lti_message_hint")
    if lti_message_hint is not None and not isinstance(lti_message_hint, str):
        raise HTTPException(status_code=400, detail="Invalid lti_message_hint")

    # Use the platform's authorization endpoint discovered during dynamic registration.
    oidc_authorization_endpoint = registration.auth_login_url
    if not oidc_authorization_endpoint:
        raise HTTPException(
            status_code=400, detail="No known OIDC authorization endpoint for issuer"
        )

    # Optional deployment binding if the platform supplies it at initiation time.
    request_deployment_id = payload.get("deployment_id") or payload.get(
        "lti_deployment_id"
    )
    if request_deployment_id is not None and not isinstance(request_deployment_id, str):
        raise HTTPException(status_code=400, detail="Invalid deployment_id")

    # Create a short-lived server-side session that binds state <-> nonce.
    now = get_now_fn(request)()
    redirect_uri = config.url("/api/v1/lti/launch")
    _, state, nonce = await LTIOIDCSession.create_pending(
        request.state.db,
        issuer=iss,
        client_id=client_id,
        deployment_id=request_deployment_id,
        redirect_uri=redirect_uri,
        target_link_uri=target_link_uri,
        login_hint=login_hint,
        lti_message_hint=lti_message_hint,
        now=now,
        ttl_seconds=600,
    )

    # Build the authorization redirect (must be a browser redirect, not server-to-server).
    auth_params: dict[str, str] = {
        "scope": "openid",
        "response_type": "id_token",
        "response_mode": "form_post",
        "prompt": "none",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "login_hint": login_hint,
        "state": state,
        "nonce": nonce,
    }
    if lti_message_hint:
        auth_params["lti_message_hint"] = lti_message_hint

    redirect_url = f"{oidc_authorization_endpoint}?{urlencode(auth_params)}"
    return RedirectResponse(url=redirect_url, status_code=302)


def _is_instructor(roles: list[str]) -> bool:
    """Check if the user has an instructor role."""
    instructor_roles = {
        "http://purl.imsglobal.org/vocab/lis/v2/membership#Instructor",
        "http://purl.imsglobal.org/vocab/lis/v2/membership#ContentDeveloper",
    }
    return any(role in instructor_roles for role in roles)


def _is_student(roles: list[str]) -> bool:
    """Check if the user has a student role."""
    student_roles = {
        "http://purl.imsglobal.org/vocab/lis/v2/membership#Learner",
        "http://purl.imsglobal.org/vocab/lis/v2/membership#Mentor",
    }
    return any(role in student_roles for role in roles)


def _is_admin(roles: list[str]) -> bool:
    """Check if the user has an admin role."""
    admin_roles = {
        "http://purl.imsglobal.org/vocab/lis/v2/institution/person#Administrator",
    }
    return any(role in admin_roles for role in roles)


async def _is_supervisor_by_class_id(
    client: OpenFgaAuthzClient,
    user_id: int,
    class_id: int,
):
    """Check if the user is a supervisor for the given class ID."""
    return await client.test(f"user:{user_id}", "supervisor", f"class:{class_id}")


async def _can_view_by_class_id(
    client: OpenFgaAuthzClient,
    user_id: int,
    class_id: int,
):
    """Check if the user can view the given class ID."""
    return await client.test(f"user:{user_id}", "can_view", f"class:{class_id}")


@lti_router.post("/launch")
async def lti_launch(
    request: Request,
    tasks: BackgroundTasks,
):
    form = await request.form()

    state = form.get("state")
    if not isinstance(state, str) or not state:
        raise HTTPException(status_code=400, detail="Missing or invalid state")

    id_token = form.get("id_token")
    if not isinstance(id_token, str) or not id_token:
        raise HTTPException(status_code=400, detail="Missing or invalid id_token")

    now: datetime = get_now_fn(request)()

    oidc_session = await LTIOIDCSession.get_by_state(request.state.db, state)
    if oidc_session is None:
        raise HTTPException(status_code=400, detail="Unknown state")
    if oidc_session.is_consumed():
        raise HTTPException(status_code=400, detail="State already consumed")
    if oidc_session.is_expired(now):
        raise HTTPException(status_code=400, detail="State expired")

    expected_redirect_uri = config.url("/api/v1/lti/launch")
    if oidc_session.redirect_uri and oidc_session.redirect_uri != expected_redirect_uri:
        raise HTTPException(status_code=400, detail="OIDC redirect_uri mismatch")

    registration = await LTIRegistration.get_by_client_id(
        request.state.db, oidc_session.client_id
    )
    if registration is None:
        raise HTTPException(status_code=404, detail="Unknown LTI client_id")
    if registration.issuer != oidc_session.issuer:
        raise HTTPException(status_code=400, detail="Issuer mismatch for state")

    claims = await _verify_lti_id_token(
        id_token=id_token,
        jwks_url=registration.key_set_url,
        expected_issuer=oidc_session.issuer,
        expected_audience=oidc_session.client_id,
        expected_algorithm=registration.token_algorithm,
    )

    nonce = claims.get("nonce")
    if not isinstance(nonce, str) or not nonce:
        raise HTTPException(status_code=400, detail="Missing nonce in id_token")

    deployment_id_claim = claims.get(LTI_DEPLOYMENT_ID_CLAIM)
    if deployment_id_claim is not None and not isinstance(deployment_id_claim, str):
        raise HTTPException(status_code=400, detail="Invalid deployment_id in id_token")

    deployment_id_to_check: str | None = None
    if oidc_session.deployment_id is not None:
        if not deployment_id_claim:
            raise HTTPException(
                status_code=400, detail="Missing deployment_id in id_token"
            )
        deployment_id_to_check = deployment_id_claim

    consumed = await LTIOIDCSession.validate_and_consume(
        request.state.db,
        state=state,
        nonce=nonce,
        now=now,
        issuer=oidc_session.issuer,
        client_id=oidc_session.client_id,
        deployment_id=deployment_id_to_check,
    )
    if consumed is None:
        raise HTTPException(status_code=400, detail="Invalid or expired state/nonce")
    launch_custom_params = claims.get(
        "https://purl.imsglobal.org/spec/lti/claim/custom", {}
    )

    if (
        registration.review_status != LTIRegistrationReviewStatus.APPROVED
        or not registration.enabled
    ):
        return RedirectResponse(url=config.url("/lti/inactive"), status_code=302)

    course_id = launch_custom_params.get("canvas_course_id")
    if (
        not isinstance(course_id, str)
        or not course_id
        or course_id in LTI_CUSTOM_PARAM_DEFAULT_VALUES["canvas_course_id"]
    ):
        raise HTTPException(status_code=400, detail="Missing or invalid course_id")

    if registration.canvas_account_lti_guid:
        class_ = await find_class_by_course_id_search_by_canvas_account_lti_guid(
            request.state.db,
            registration_id=registration.id,
            canvas_account_lti_guid=registration.canvas_account_lti_guid,
            course_id=course_id,
        )
    else:
        class_ = await find_class_by_course_id(
            request.state.db,
            registration.id,
            course_id,
        )

    user_roles = claims.get("https://purl.imsglobal.org/spec/lti/claim/roles", [])
    is_instructor = _is_instructor(user_roles)
    is_student = _is_student(user_roles)
    is_admin = _is_admin(user_roles)

    if not is_instructor and not is_student and not is_admin:
        logger.exception(f"LTI launch with no recognized roles: roles={user_roles}")
        return RedirectResponse(url=config.url("/lti/no-role"), status_code=302)

    user_email = claims.get("email")
    if user_email is None or not isinstance(user_email, str):
        raise HTTPException(status_code=400, detail="Invalid email in id_token")

    sso_provider_id_str = launch_custom_params.get("sso_provider_id", "0")
    user: User | None = None
    sso_provider: ExternalLoginProvider | None = None
    sso_value: str | None = None

    if int(sso_provider_id_str) != 0:
        sso_provider = await ExternalLoginProvider.get_by_id(
            request.state.db, int(sso_provider_id_str)
        )
        if sso_provider is None:
            raise HTTPException(status_code=400, detail="Unknown SSO provider id")
        sso_value = launch_custom_params.get("sso_value", None)
        if not sso_value or sso_value in LTI_CUSTOM_PARAM_DEFAULT_VALUES["sso_value"]:
            sso_value = None
        user = await User.get_by_email_sso(
            request.state.db,
            user_email,
            provider=sso_provider.name,
            identifier=sso_value,
        )
        if user:
            user.email = user_email
            if sso_value:
                await ExternalLogin.create_or_update(
                    request.state.db,
                    user.id,
                    provider=sso_provider.name,
                    identifier=sso_value,
                    called_by="lti_launch",
                )
    else:
        user = await User.get_by_email(request.state.db, user_email)

    if not user:
        if is_admin and not (is_instructor or is_student):
            logger.exception(
                f"Admin user attempted LTI launch but no existing account: email={user_email}"
            )
            return RedirectResponse(url=config.url("/lti/no-role"), status_code=302)
        user = User(
            email=user_email,
        )

    user_first_name = claims.get("given_name") or ""
    if user_first_name:
        user.first_name = user_first_name
    user_last_name = claims.get("family_name") or ""
    if user_last_name:
        user.last_name = user_last_name

    user.state = UserState.VERIFIED

    request.state.db.add(user)
    await request.state.db.flush()
    await request.state.db.refresh(user)
    request.state.session.user = user
    user_token = encode_session_token(user.id, nowfn=get_now_fn(request))

    if class_ is None or (
        isinstance(class_, LTIClass) and class_.lti_status == LTIStatus.PENDING
    ):
        # User is launching into a class that is not yet linked
        # Or the class is pending setup
        if is_instructor or is_admin:
            # Check for existing pending LTIClass (re-launch scenario)
            if isinstance(class_, LTIClass) and class_.lti_status == LTIStatus.PENDING:
                # Resume existing setup
                pending_lti_class = class_
                pending_lti_class.setup_user_id = user.id
                request.state.db.add(pending_lti_class)
                await request.state.db.flush()
            else:
                # Create new pending LTIClass to store context
                course_details = claims.get(
                    "https://purl.imsglobal.org/spec/lti/claim/context", {}
                )
                course_code = course_details.get("label")
                course_name = course_details.get("title")
                course_term = launch_custom_params.get("canvas_term_name")
                if (
                    not course_term
                    or course_term
                    in LTI_CUSTOM_PARAM_DEFAULT_VALUES["canvas_term_name"]
                ):
                    course_term = None
                nrps_claim = claims.get(
                    "https://purl.imsglobal.org/spec/lti-nrps/claim/namesroleservice",
                    {},
                )
                context_memberships_url = nrps_claim.get("context_memberships_url")

                pending_lti_class = LTIClass(
                    registration_id=registration.id,
                    lti_status=LTIStatus.PENDING,
                    lti_platform=registration.lms_platform,
                    course_id=course_id,
                    course_code=course_code,
                    course_name=course_name,
                    course_term=course_term,
                    class_id=None,
                    setup_user_id=user.id,
                    context_memberships_url=context_memberships_url,
                )
                request.state.db.add(pending_lti_class)
                await request.state.db.flush()

            return RedirectResponse(
                url=config.url(
                    f"/lti/setup?lti_session={user_token}&lti_class_id={pending_lti_class.id}"
                ),
                status_code=302,
            )
        else:
            # Student launching into unlinked class
            return RedirectResponse(
                url=config.url(f"/lti/no-group?lti_session={user_token}"),
                status_code=302,
            )
    else:
        if isinstance(class_, LTIClass) and class_.registration_id == registration.id:
            if user.id == class_.setup_user_id:
                return RedirectResponse(
                    url=config.url(
                        f"/group/{class_.class_id}?lti_session={user_token}"
                    ),
                    status_code=302,
                )
            else:
                if is_admin and not (is_instructor or is_student):
                    if not await _can_view_by_class_id(
                        request.state.authz,
                        user.id,
                        class_.class_id,
                    ):
                        # We should not redirect supervisors to groups they
                        # do not have access to
                        return RedirectResponse(
                            url=config.url("/lti/no-role"), status_code=302
                        )
                    # No role is being added, but allow access
                    return RedirectResponse(
                        url=config.url(
                            f"/group/{class_.class_id}?lti_session={user_token}"
                        ),
                        status_code=302,
                    )
                new_ucr = CreateUserClassRoles(
                    roles=[
                        CreateUserClassRole(
                            email=user.email,
                            sso_id=sso_value,
                            roles=ClassUserRoles(
                                teacher=is_instructor,
                                student=is_student,
                                admin=False,
                            ),
                        )
                    ],
                    silent=True,
                    lms_tenant=None,
                    lms_type=registration.lms_platform,
                    lti_class_id=class_.id,
                    sso_tenant=sso_provider.name if sso_provider else None,
                    is_lti_launch=True,
                )
                try:
                    await AddNewUsersManual(
                        str(class_.class_id),
                        new_ucr,
                        request,
                        tasks,
                        user_id=class_.setup_user_id,
                    ).add_new_users()
                except AddUserException as e:
                    logger.exception("lti_launch: AddUserException occurred")
                    raise HTTPException(
                        status_code=e.code or 500,
                        detail="Failed to add user to class",
                    )
                return RedirectResponse(
                    url=config.url(
                        f"/group/{class_.class_id}?lti_session={user_token}"
                    ),
                    status_code=302,
                )
        elif isinstance(class_, LTIClass):
            second_lti_class = None
            pp_class = await Class.get_by_id(request.state.db, class_.class_id)
            if pp_class is None:
                raise HTTPException(status_code=404, detail="Class not found")

            is_admin_supervisor = False
            if is_admin:
                is_admin_supervisor = await _can_view_by_class_id(
                    request.state.authz,
                    user.id,
                    pp_class.id,
                )

            if is_instructor or is_admin_supervisor:
                course_details = claims.get(
                    "https://purl.imsglobal.org/spec/lti/claim/context", {}
                )
                course_code = course_details.get("label")
                course_name = course_details.get("title")
                course_term = launch_custom_params.get("canvas_term_name")
                if (
                    not course_term
                    or course_term
                    in LTI_CUSTOM_PARAM_DEFAULT_VALUES["canvas_term_name"]
                ):
                    course_term = None
                nrps_claim = claims.get(
                    "https://purl.imsglobal.org/spec/lti-nrps/claim/namesroleservice",
                    {},
                )
                context_memberships_url = nrps_claim.get("context_memberships_url")
                second_lti_class = LTIClass(
                    registration_id=registration.id,
                    lti_status=LTIStatus.LINKED,
                    lti_platform=registration.lms_platform,
                    course_id=course_id,
                    course_code=course_code,
                    course_name=course_name,
                    course_term=course_term,
                    class_id=pp_class.id,
                    setup_user_id=user.id,
                    context_memberships_url=context_memberships_url,
                )
                request.state.db.add(second_lti_class)
                await request.state.db.flush()
                await request.state.db.refresh(second_lti_class)

            if pp_class.lms_user_id == user.id:
                return RedirectResponse(
                    url=config.url(f"/group/{pp_class.id}?lti_session={user_token}"),
                    status_code=302,
                )
            else:
                if is_admin and not (is_instructor or is_student):
                    if not await _can_view_by_class_id(
                        request.state.authz,
                        user.id,
                        class_.class_id,
                    ):
                        # We should not redirect supervisors to groups they
                        # do not have access to
                        return RedirectResponse(
                            url=config.url("/lti/no-role"), status_code=302
                        )
                    # No role is being added, but allow access
                    return RedirectResponse(
                        url=config.url(
                            f"/group/{class_.class_id}?lti_session={user_token}"
                        ),
                        status_code=302,
                    )
                new_ucr = CreateUserClassRoles(
                    roles=[
                        CreateUserClassRole(
                            email=user.email,
                            sso_id=sso_value,
                            roles=ClassUserRoles(
                                teacher=is_instructor,
                                student=is_student,
                                admin=False,
                            ),
                        )
                    ],
                    silent=True,
                    sso_tenant=sso_provider.name if sso_provider else None,
                    lms_type=class_.lti_platform if not second_lti_class else None,
                    lti_class_id=second_lti_class.id if second_lti_class else class_.id,
                    is_lti_launch=True,
                )
                try:
                    await AddNewUsersManual(
                        pp_class.id,
                        new_ucr,
                        request,
                        tasks,
                        user_id=pp_class.lms_user_id,
                    ).add_new_users()
                except AddUserException as e:
                    logger.exception("lti_launch: AddUserException occurred")
                    raise HTTPException(
                        status_code=e.code or 500,
                        detail="Failed to add user to class",
                    )
            return RedirectResponse(
                url=config.url(f"/group/{pp_class.id}?lti_session={user_token}"),
                status_code=302,
            )
        else:
            new_lti_class = None

            is_admin_supervisor = False
            if is_admin:
                is_admin_supervisor = await _can_view_by_class_id(
                    request.state.authz,
                    user.id,
                    class_.id,
                )

            if is_instructor or is_admin_supervisor:
                course_details = claims.get(
                    "https://purl.imsglobal.org/spec/lti/claim/context", {}
                )
                course_code = course_details.get("label")
                course_name = course_details.get("title")
                course_term = launch_custom_params.get("canvas_term_name")
                if (
                    not course_term
                    or course_term
                    in LTI_CUSTOM_PARAM_DEFAULT_VALUES["canvas_term_name"]
                ):
                    course_term = None
                nrps_claim = claims.get(
                    "https://purl.imsglobal.org/spec/lti-nrps/claim/namesroleservice",
                    {},
                )
                context_memberships_url = nrps_claim.get("context_memberships_url")
                new_lti_class = LTIClass(
                    registration_id=registration.id,
                    lti_status=LTIStatus.LINKED,
                    lti_platform=registration.lms_platform,
                    course_id=course_id,
                    course_code=course_code,
                    course_name=course_name,
                    course_term=course_term,
                    class_id=class_.id,
                    setup_user_id=user.id,
                    context_memberships_url=context_memberships_url,
                )
                request.state.db.add(new_lti_class)
                await request.state.db.flush()
                await request.state.db.refresh(new_lti_class)

            if class_.lms_user_id == user.id:
                return RedirectResponse(
                    url=config.url(f"/group/{class_.id}?lti_session={user_token}"),
                    status_code=302,
                )
            elif is_admin and not (is_instructor or is_student):
                if not await _can_view_by_class_id(
                    request.state.authz,
                    user.id,
                    class_.id,
                ):
                    # We should not redirect supervisors to groups they
                    # do not have access to
                    return RedirectResponse(
                        url=config.url("/lti/no-role"), status_code=302
                    )
                # No role is being added, but allow access
                return RedirectResponse(
                    url=config.url(f"/group/{class_.id}?lti_session={user_token}"),
                    status_code=302,
                )
            elif str(class_.lms_course_id) == course_id:
                new_ucr = CreateUserClassRoles(
                    roles=[
                        CreateUserClassRole(
                            email=user.email,
                            sso_id=sso_value,
                            roles=ClassUserRoles(
                                teacher=is_instructor,
                                student=is_student,
                                admin=False,
                            ),
                        )
                    ],
                    silent=True,
                    lms_tenant=class_.lms_tenant if not new_lti_class else None,
                    lms_type=class_.lms_type
                    if not new_lti_class
                    else new_lti_class.lti_platform,
                    lti_class_id=new_lti_class.id if new_lti_class else None,
                    sso_tenant=sso_provider.name if sso_provider else None,
                    is_lti_launch=True,
                )
                try:
                    await AddNewUsersManual(
                        class_.id, new_ucr, request, tasks, user_id=class_.lms_user_id
                    ).add_new_users()
                except AddUserException as e:
                    logger.exception("lti_launch: AddUserException occurred")
                    raise HTTPException(
                        status_code=e.code or 500,
                        detail="Failed to add user to class",
                    )
            else:
                new_ucr = CreateUserClassRoles(
                    roles=[
                        CreateUserClassRole(
                            email=user.email,
                            sso_id=sso_value,
                            roles=ClassUserRoles(
                                teacher=is_instructor,
                                student=is_student,
                                admin=False,
                            ),
                        )
                    ],
                    silent=True,
                    sso_tenant=sso_provider.name if sso_provider else None,
                    is_lti_launch=True,
                )
                try:
                    await AddNewUsersManual(
                        class_.id, new_ucr, request, tasks, user_id=class_.lms_user_id
                    ).add_new_users()
                except AddUserException as e:
                    logger.exception("lti_launch: AddUserException occurred")
                    raise HTTPException(
                        status_code=e.code or 500,
                        detail="Failed to add user to class",
                    )
            return RedirectResponse(
                url=config.url(f"/group/{class_.id}?lti_session={user_token}"),
                status_code=302,
            )


async def _get_lti_class_for_setup(request: Request, lti_class_id: int) -> LTIClass:
    lti_class = await LTIClass.get_by_id_for_setup(request.state.db, lti_class_id)

    if not lti_class:
        raise HTTPException(status_code=404, detail="LTI class not found")

    if lti_class.setup_user_id != request.state.session.user.id:
        raise HTTPException(
            status_code=403, detail="Not authorized to setup this class"
        )

    if lti_class.lti_status != LTIStatus.PENDING:
        raise HTTPException(status_code=400, detail="LTI class is not in pending state")

    return lti_class


@lti_router.get(
    "/setup/{lti_class_id}",
    dependencies=[Depends(LoggedIn())],
    response_model=LTISetupContext,
)
async def get_lti_setup_context(request: Request, lti_class_id: int):
    lti_class = await _get_lti_class_for_setup(request, lti_class_id)

    can_create_class_institution_ids = await request.state.authz.list(
        f"user:{request.state.session.user.id}",
        "can_create_class",
        "institution",
    )

    institutions = [
        LTISetupInstitution(id=inst.id, name=inst.name)
        for inst in lti_class.registration.institutions
        if inst.default_api_key_id is not None
        and inst.id in can_create_class_institution_ids
    ]

    return LTISetupContext(
        lti_class_id=lti_class.id,
        course_name=lti_class.course_name,
        course_code=lti_class.course_code,
        course_term=lti_class.course_term,
        institutions=institutions,
    )


@lti_router.get(
    "/setup/{lti_class_id}/linkable-groups",
    dependencies=[Depends(LoggedIn())],
    response_model=LTILinkableGroupsResponse,
)
async def get_lti_linkable_groups(request: Request, lti_class_id: int):
    teacher_class_ids = await request.state.authz.list(
        f"user:{request.state.session.user.id}",
        "supervisor",
        "class",
    )

    if not teacher_class_ids:
        return LTILinkableGroupsResponse(groups=[])

    classes = await Class.get_all_by_id_simple(request.state.db, teacher_class_ids)

    linkable_groups = [
        LTILinkableGroup(
            id=cls.id,
            name=cls.name,
            term=cls.term or "",
            institution_name=cls.institution.name if cls.institution else "",
        )
        for cls in classes
    ]

    return LTILinkableGroupsResponse(groups=linkable_groups)


@lti_router.post(
    "/setup/{lti_class_id}/create",
    dependencies=[Depends(LoggedIn())],
    response_model=LTISetupCreateResponse,
)
async def create_lti_group(
    request: Request, lti_class_id: int, body: LTISetupCreateRequest
):
    """Create a new group and link it to the pending LTIClass."""
    lti_class = await _get_lti_class_for_setup(request, lti_class_id)

    valid_institution = None
    for inst in lti_class.registration.institutions:
        if inst.id == body.institution_id and inst.default_api_key_id is not None:
            valid_institution = inst
            break

    if not valid_institution:
        raise HTTPException(
            status_code=400,
            detail="Invalid institution or institution has no default billing",
        )

    can_create_class_institution_ids = await request.state.authz.test(
        f"user:{request.state.session.user.id}",
        "can_create_class",
        f"institution:{valid_institution.id}",
    )
    if not can_create_class_institution_ids:
        raise HTTPException(
            status_code=403,
            detail="Not authorized to create classes for this institution",
        )

    new_class = Class(
        name=body.name,
        term=body.term,
        institution_id=valid_institution.id,
        api_key_id=valid_institution.default_api_key_id,
    )
    request.state.db.add(new_class)
    await request.state.db.flush()
    await request.state.db.refresh(new_class)

    lti_class.class_id = new_class.id
    lti_class.lti_status = LTIStatus.LINKED
    request.state.db.add(lti_class)

    user = await User.get_by_id(request.state.db, request.state.session.user.id)
    user_class_role = UserClassRole(
        user_id=request.state.session.user.id,
        class_id=new_class.id,
        subscribed_to_summaries=not user.dna_as_create,
    )
    request.state.db.add(user_class_role)

    grants = [
        (f"institution:{valid_institution.id}", "parent", f"class:{new_class.id}"),
        (f"user:{request.state.session.user.id}", "teacher", f"class:{new_class.id}"),
    ]

    if not new_class.private:
        grants.append(
            (
                f"class:{new_class.id}#supervisor",
                "can_manage_threads",
                f"class:{new_class.id}",
            )
        )
        grants.append(
            (
                f"class:{new_class.id}#supervisor",
                "can_manage_assistants",
                f"class:{new_class.id}",
            )
        )

    if new_class.any_can_create_assistant:
        grants.append(
            (
                f"class:{new_class.id}#student",
                "can_create_assistants",
                f"class:{new_class.id}",
            )
        )

    if new_class.any_can_publish_assistant:
        grants.append(
            (
                f"class:{new_class.id}#student",
                "can_publish_assistants",
                f"class:{new_class.id}",
            )
        )

        if new_class.any_can_share_assistant:
            grants.append(
                (
                    f"class:{new_class.id}#student",
                    "can_share_assistants",
                    f"class:{new_class.id}",
                )
            )

    if new_class.any_can_publish_thread:
        grants.append(
            (
                f"class:{new_class.id}#student",
                "can_publish_threads",
                f"class:{new_class.id}",
            )
        )

    if new_class.any_can_upload_class_file:
        grants.append(
            (
                f"class:{new_class.id}#student",
                "can_upload_class_files",
                f"class:{new_class.id}",
            )
        )

    await request.state.authz.write(grant=grants)

    return LTISetupCreateResponse(class_id=new_class.id)


@lti_router.post(
    "/setup/{lti_class_id}/link",
    dependencies=[Depends(LoggedIn())],
    response_model=LTISetupLinkResponse,
)
async def link_lti_group(
    request: Request, lti_class_id: int, body: LTISetupLinkRequest
):
    """Link an existing group to the pending LTIClass."""
    lti_class = await _get_lti_class_for_setup(request, lti_class_id)
    user = request.state.session.user

    # Verify user has teacher role on the target class using authz
    has_teacher_role = await request.state.authz.test(
        f"user:{user.id}", "teacher", f"class:{body.class_id}"
    )
    if not has_teacher_role:
        raise HTTPException(status_code=403, detail="Not authorized to link this class")

    # Verify class doesn't already have an LTI link for this registration
    has_link = await LTIClass.has_link_for_registration_and_class(
        request.state.db, lti_class.registration_id, body.class_id
    )
    if has_link:
        raise HTTPException(
            status_code=400,
            detail="This class is already linked to an LTI course from this registration",
        )

    # Update the LTIClass to link it
    lti_class.class_id = body.class_id
    lti_class.lti_status = LTIStatus.LINKED
    request.state.db.add(lti_class)

    return LTISetupLinkResponse(class_id=body.class_id)
