from __future__ import annotations

import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any, ClassVar

from authlib.integrations.httpx_client import AsyncOAuth2Client
import httpx

from pingpong.now import NowFn, utcnow

from .exceptions import ConnectorError, TokenRefreshError
from .identity import ConnectorIdentityResolver
from .types import ConnectorTokens, PKCEPair, ProviderIdentity, expires_at_timestamp

if TYPE_CHECKING:
    from pingpong.models import ConnectorConfig, UserConnector

logger = logging.getLogger(__name__)

HTTP_TIMEOUT_SECONDS = 10.0


def generate_pkce_pair() -> PKCEPair:
    return PKCEPair(verifier=secrets.token_urlsafe(64))


def _scope_string(scopes: list[str]) -> str | None:
    return " ".join(scopes) if scopes else None


class OAuth2Connector:
    slug: ClassVar[str] = ""
    display_name: ClassVar[str] = ""
    icon: ClassVar[str | None] = None
    scopes: ClassVar[list[str]] = []
    use_pkce: ClassVar[bool] = True
    token_endpoint_auth_method: ClassVar[str] = "client_secret_post"
    revocation_endpoint_auth_method: ClassVar[str] = "client_secret_post"
    http_timeout_seconds: ClassVar[float] = HTTP_TIMEOUT_SECONDS

    def __init__(self, nowfn: NowFn = utcnow) -> None:
        self._nowfn = nowfn
        self._identity_resolver = ConnectorIdentityResolver()

    def now(self) -> datetime:
        return self._nowfn()

    async def authorize_endpoint(self, connector_config: "ConnectorConfig") -> str:
        raise NotImplementedError

    async def token_endpoint(self, connector_config: "ConnectorConfig") -> str:
        raise NotImplementedError

    async def userinfo_endpoint(
        self, connector_config: "ConnectorConfig"
    ) -> str | None:
        return None

    async def issuer(self, connector_config: "ConnectorConfig") -> str | None:
        return None

    async def jwks_endpoint(self, connector_config: "ConnectorConfig") -> str | None:
        return None

    async def revoke_endpoint(self, connector_config: "ConnectorConfig") -> str | None:
        return None

    async def build_authorize_url(
        self,
        *,
        connector_config: "ConnectorConfig",
        redirect_uri: str,
        state: str,
        pkce: PKCEPair | None = None,
        nonce: str | None = None,
        extra_params: dict[str, str] | None = None,
    ) -> str:
        authorize_url = await self.authorize_endpoint(connector_config)
        client = self._oauth_client(
            connector_config,
            redirect_uri=redirect_uri,
            code_challenge_method=pkce.method if pkce is not None else None,
        )
        try:
            params = dict(extra_params or {})
            if nonce is not None:
                params["nonce"] = nonce
            url, returned_state = client.create_authorization_url(
                authorize_url,
                state=state,
                code_verifier=pkce.verifier if pkce is not None else None,
                **params,
            )
            if returned_state != state:
                raise ConnectorError("Authlib returned a different OAuth state")
            return url
        finally:
            await client.aclose()

    async def exchange_code(
        self,
        *,
        connector_config: "ConnectorConfig",
        code: str,
        redirect_uri: str,
        state: str | None = None,
        pkce_verifier: str | None = None,
    ) -> ConnectorTokens:
        token_url = await self.token_endpoint(connector_config)
        async with self._oauth_client(
            connector_config,
            redirect_uri=redirect_uri,
            code_challenge_method="S256" if pkce_verifier else None,
        ) as client:
            try:
                payload = await client.fetch_token(
                    token_url,
                    grant_type="authorization_code",
                    code=code,
                    redirect_uri=redirect_uri,
                    state=state,
                    code_verifier=pkce_verifier,
                )
            except Exception as e:
                raise ConnectorError(f"Token exchange failed: {e}") from e
        return self._parse_token_response(payload)

    async def refresh(
        self,
        connector_config: "ConnectorConfig",
        connector: "UserConnector",
    ) -> ConnectorTokens:
        if not connector.refresh_token:
            raise TokenRefreshError(
                f"No refresh token stored for connector id={connector.id}"
            )
        token_url = await self.token_endpoint(connector_config)
        async with self._oauth_client(connector_config) as client:
            try:
                payload = await client.refresh_token(
                    token_url,
                    refresh_token=connector.refresh_token,
                )
            except Exception as e:
                raise TokenRefreshError(f"Token refresh failed: {e}") from e
        tokens = self._parse_token_response(payload)
        if tokens.refresh_token is None:
            tokens.refresh_token = connector.refresh_token
        return tokens

    async def revoke(
        self,
        connector_config: "ConnectorConfig",
        connector: "UserConnector",
    ) -> None:
        url = await self.revoke_endpoint(connector_config)
        if not url:
            return
        token = connector.refresh_token or connector.access_token
        token_type_hint = "refresh_token" if connector.refresh_token else "access_token"
        try:
            async with self._oauth_client(connector_config) as client:
                response = await client.revoke_token(
                    url,
                    token=token,
                    token_type_hint=token_type_hint,
                )
            if isinstance(response, httpx.Response) and response.is_error:
                logger.warning(
                    "Connector revoke returned %s for connector id=%s service=%s",
                    response.status_code,
                    connector.id,
                    self.slug,
                )
        except Exception as exc:
            logger.warning(
                "Connector revoke request failed for connector id=%s service=%s: %s",
                connector.id,
                self.slug,
                exc,
            )

    async def fetch_identity(
        self,
        *,
        connector_config: "ConnectorConfig",
        tokens: ConnectorTokens,
        expected_nonce: str | None = None,
    ) -> ProviderIdentity:
        return await self._identity_resolver.fetch_identity(
            self,
            connector_config=connector_config,
            tokens=tokens,
            expected_nonce=expected_nonce,
        )

    def identity_from_userinfo(self, payload: dict[str, Any]) -> ProviderIdentity:
        return self._identity_resolver.identity_from_userinfo(payload)

    def oauth_client(
        self,
        connector_config: "ConnectorConfig",
        *,
        redirect_uri: str | None = None,
        token: dict[str, Any] | None = None,
        code_challenge_method: str | None = None,
    ) -> AsyncOAuth2Client:
        return self._oauth_client(
            connector_config,
            redirect_uri=redirect_uri,
            token=token,
            code_challenge_method=code_challenge_method,
        )

    def _oauth_client(
        self,
        connector_config: "ConnectorConfig",
        *,
        redirect_uri: str | None = None,
        token: dict[str, Any] | None = None,
        code_challenge_method: str | None = None,
    ) -> AsyncOAuth2Client:
        return AsyncOAuth2Client(
            client_id=connector_config.client_id,
            client_secret=connector_config.client_secret,
            token_endpoint_auth_method=self.token_endpoint_auth_method,
            revocation_endpoint_auth_method=self.revocation_endpoint_auth_method,
            scope=_scope_string(self.scopes),
            redirect_uri=redirect_uri,
            token=token,
            code_challenge_method=code_challenge_method,
            timeout=self.http_timeout_seconds,
        )

    def _parse_token_response(self, payload: dict[str, Any]) -> ConnectorTokens:
        access_token = payload.get("access_token")
        if not isinstance(access_token, str) or not access_token:
            raise ConnectorError("Token response missing access_token")
        refresh_token = payload.get("refresh_token")
        expires_at = self._parse_expires_at(payload)
        scopes = payload.get("scope")
        if isinstance(scopes, list):
            scopes = " ".join(str(scope) for scope in scopes)
        return ConnectorTokens(
            access_token=access_token,
            refresh_token=refresh_token if isinstance(refresh_token, str) else None,
            expires_at=expires_at,
            scopes=scopes if isinstance(scopes, str) else None,
            raw=dict(payload),
        )

    def _parse_expires_at(self, payload: dict[str, Any]) -> datetime | None:
        expires_at = payload.get("expires_at")
        if isinstance(expires_at, (int, float)) and expires_at > 0:
            return datetime.fromtimestamp(expires_at, timezone.utc)
        expires_in = payload.get("expires_in")
        if isinstance(expires_in, (int, float)) and expires_in > 0:
            return self._nowfn() + timedelta(seconds=int(expires_in))
        return None

    def _token_dict(self, tokens: ConnectorTokens) -> dict[str, Any]:
        return {
            "access_token": tokens.access_token,
            "refresh_token": tokens.refresh_token,
            "token_type": "Bearer",
            "expires_at": expires_at_timestamp(tokens.expires_at),
        }
