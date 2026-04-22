from __future__ import annotations

import base64
import hashlib
import logging
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any, ClassVar
from urllib.parse import urlencode

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from pingpong.now import NowFn, utcnow

from .exceptions import ConnectorError, TokenRefreshError

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from pingpong.models import UserConnector


REFRESH_THRESHOLD_SECONDS = 60

# Any call that runs inline with an HTTP request (authorize/callback/refresh)
# should hard-cap provider latency so a hung connection doesn't tie up a
# worker or propagate to end users as a blank screen.  httpx's implicit
# default is 5s but being explicit (and a touch more generous) makes the
# behavior predictable across connectors.
HTTP_TIMEOUT_SECONDS = 10.0


@dataclass
class ConnectorTokens:
    """Normalized OAuth2 token response."""

    access_token: str
    refresh_token: str | None
    expires_at: datetime | None
    scopes: str | None
    external_user_id: str | None = None
    raw: dict[str, Any] | None = None


@dataclass
class PKCEPair:
    verifier: str
    challenge: str
    method: str = "S256"


def generate_pkce_pair() -> PKCEPair:
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return PKCEPair(verifier=verifier, challenge=challenge)


class OAuth2Connector:
    """Abstract base class for OAuth2-based connectors.

    Subclasses declare ``slug``, ``display_name``, ``scopes`` and implement
    ``authorize_endpoint`` / ``token_endpoint`` (plus optionally
    ``revoke_endpoint``). Everything else — authorize URL construction, code
    exchange, refresh, revoke, transparent refresh — is shared.
    """

    slug: ClassVar[str] = ""
    display_name: ClassVar[str] = ""
    icon: ClassVar[str | None] = None
    requires_tenant: ClassVar[bool] = False
    scopes: ClassVar[list[str]] = []
    # Confidential clients (those that send a client_secret) often don't need
    # PKCE and some servers (notably Panopto's server-side-web-app flow)
    # reject requests that send both.
    use_pkce: ClassVar[bool] = True

    def __init__(self, nowfn: NowFn = utcnow) -> None:
        self._nowfn = nowfn

    # ---- abstract endpoint hooks -----------------------------------------

    async def authorize_endpoint(self, tenant: str | None) -> str:
        raise NotImplementedError

    async def token_endpoint(self, tenant: str | None) -> str:
        raise NotImplementedError

    async def revoke_endpoint(self, tenant: str | None) -> str | None:
        """Return the revoke endpoint URL, or None if the provider has none."""
        return None

    # ---- credentials / tenant hooks --------------------------------------

    def client_credentials(self, tenant: str | None) -> tuple[str, str]:
        """Return (client_id, client_secret) for this tenant."""
        raise NotImplementedError

    def tenant_friendly_name(self, tenant: str | None) -> str | None:
        """Return a human-readable name for the tenant (for UI display)."""
        return None

    # ---- authorize URL ---------------------------------------------------

    async def build_authorize_url(
        self,
        *,
        tenant: str | None,
        redirect_uri: str,
        state: str,
        pkce: PKCEPair | None = None,
        extra_params: dict[str, str] | None = None,
    ) -> str:
        authorize = await self.authorize_endpoint(tenant)
        client_id, _ = self.client_credentials(tenant)
        params: dict[str, str] = {
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "state": state,
        }
        if self.scopes:
            params["scope"] = " ".join(self.scopes)
        if pkce is not None:
            params["code_challenge"] = pkce.challenge
            params["code_challenge_method"] = pkce.method
        if extra_params:
            params.update(extra_params)
        sep = "&" if "?" in authorize else "?"
        return f"{authorize}{sep}{urlencode(params)}"

    # ---- code exchange ---------------------------------------------------

    async def exchange_code(
        self,
        *,
        code: str,
        tenant: str | None,
        redirect_uri: str,
        pkce_verifier: str | None = None,
    ) -> ConnectorTokens:
        client_id, client_secret = self.client_credentials(tenant)
        token_url = await self.token_endpoint(tenant)
        data: dict[str, str] = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
            "client_id": client_id,
            "client_secret": client_secret,
        }
        if pkce_verifier is not None:
            data["code_verifier"] = pkce_verifier
        payload = await self._post_token_request(token_url, data)
        return self._parse_token_response(payload)

    # ---- refresh ---------------------------------------------------------

    async def refresh(self, connector: "UserConnector") -> ConnectorTokens:
        if not connector.refresh_token:
            raise TokenRefreshError(
                f"No refresh token stored for connector id={connector.id}"
            )
        client_id, client_secret = self.client_credentials(connector.tenant)
        token_url = await self.token_endpoint(connector.tenant)
        data = {
            "grant_type": "refresh_token",
            "refresh_token": connector.refresh_token,
            "client_id": client_id,
            "client_secret": client_secret,
        }
        try:
            payload = await self._post_token_request(token_url, data)
        except ConnectorError as e:
            raise TokenRefreshError(str(e)) from e
        tokens = self._parse_token_response(payload)
        # Spec-compliant providers may omit the refresh_token on refresh. Keep
        # the existing one in that case so the next refresh still works.
        if tokens.refresh_token is None:
            tokens.refresh_token = connector.refresh_token
        return tokens

    # ---- revoke ----------------------------------------------------------

    async def revoke(self, connector: "UserConnector") -> None:
        url = await self.revoke_endpoint(connector.tenant)
        if not url:
            # Providers without a revoke endpoint (Panopto is one) have no
            # server-side way to invalidate the token; deletion of the DB row
            # is the only hand we have to play.
            return
        client_id, client_secret = self.client_credentials(connector.tenant)
        data: dict[str, str] = {"client_id": client_id, "client_secret": client_secret}
        if connector.refresh_token:
            data["token"] = connector.refresh_token
            data["token_type_hint"] = "refresh_token"
        else:
            data["token"] = connector.access_token
            data["token_type_hint"] = "access_token"
        try:
            async with httpx.AsyncClient(timeout=HTTP_TIMEOUT_SECONDS) as client:
                response = await client.post(url, data=data)
            if response.is_error:
                logger.warning(
                    "Connector revoke returned %s for connector id=%s (service=%s): %s",
                    response.status_code,
                    connector.id,
                    self.slug,
                    response.text[:200],
                )
        except httpx.HTTPError as exc:
            # Best-effort revoke: the caller always deletes the row, and a
            # failed revoke should not block that.
            logger.warning(
                "Connector revoke request failed for connector id=%s (service=%s): %s",
                connector.id,
                self.slug,
                exc,
            )

    # ---- transparent access token ---------------------------------------

    async def get_access_token(
        self,
        session: AsyncSession,
        connector: "UserConnector",
    ) -> str:
        if not self._token_expired(connector):
            return connector.access_token
        tokens = await self.refresh(connector)
        self._apply_tokens(connector, tokens)
        await session.flush()
        return connector.access_token

    # ---- internals -------------------------------------------------------

    def _token_expired(self, connector: "UserConnector") -> bool:
        if connector.expires_at is None:
            return False
        now = self._nowfn()
        if connector.expires_at.tzinfo is None:
            now = now.replace(tzinfo=None)
        return connector.expires_at - now <= timedelta(
            seconds=REFRESH_THRESHOLD_SECONDS
        )

    def _apply_tokens(
        self, connector: "UserConnector", tokens: ConnectorTokens
    ) -> None:
        connector.access_token = tokens.access_token
        if tokens.refresh_token is not None:
            connector.refresh_token = tokens.refresh_token
        connector.expires_at = tokens.expires_at
        if tokens.scopes is not None:
            connector.scopes = tokens.scopes
        if tokens.external_user_id is not None:
            connector.external_user_id = tokens.external_user_id

    def _parse_token_response(self, payload: dict[str, Any]) -> ConnectorTokens:
        access_token = payload.get("access_token")
        if not isinstance(access_token, str) or not access_token:
            raise ConnectorError("Token response missing access_token")
        expires_at: datetime | None = None
        expires_in = payload.get("expires_in")
        if isinstance(expires_in, (int, float)) and expires_in > 0:
            expires_at = self._nowfn() + timedelta(seconds=int(expires_in))
        refresh_token = payload.get("refresh_token")
        scopes = payload.get("scope")
        return ConnectorTokens(
            access_token=access_token,
            refresh_token=refresh_token if isinstance(refresh_token, str) else None,
            expires_at=expires_at,
            scopes=scopes if isinstance(scopes, str) else None,
            raw=payload,
        )

    async def _post_token_request(
        self, url: str, data: dict[str, str]
    ) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(timeout=HTTP_TIMEOUT_SECONDS) as client:
                response = await client.post(
                    url,
                    data=data,
                    headers={
                        "Accept": "application/json",
                        "Content-Type": "application/x-www-form-urlencoded",
                    },
                )
        except httpx.HTTPError as e:
            raise ConnectorError(f"Token endpoint request failed: {e}") from e
        if response.status_code >= 400:
            detail = self._extract_error_detail(response)
            raise ConnectorError(
                f"Token endpoint returned {response.status_code}: {detail}"
            )
        try:
            payload = response.json()
        except ValueError as e:
            raise ConnectorError("Token endpoint returned non-JSON response") from e
        if not isinstance(payload, dict):
            raise ConnectorError("Token endpoint returned non-object payload")
        return payload

    @staticmethod
    def _extract_error_detail(response: httpx.Response) -> str:
        try:
            payload = response.json()
            if isinstance(payload, dict):
                return (
                    payload.get("error_description")
                    or payload.get("error")
                    or response.text.strip()
                )
        except ValueError:
            pass
        return response.text.strip()
