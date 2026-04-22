from __future__ import annotations

import asyncio
from typing import Any

import httpx

from pingpong.config import PanoptoTenantSettings, config
from pingpong.now import NowFn, utcnow

from .base import HTTP_TIMEOUT_SECONDS, OAuth2Connector
from .exceptions import ConnectorError, ConnectorNotConfigured

DISCOVERY_PATH = "/Panopto/oauth2/.well-known/openid-configuration"


class PanoptoConnector(OAuth2Connector):
    slug = "panopto"
    display_name = "Panopto"
    icon = "/icons/panopto.svg"
    requires_tenant = True
    # ``openid`` + ``api`` let us call the Panopto API; ``offline_access``
    # returns a refresh token so we can renew tokens without a reauth.
    scopes = ["openid", "api", "offline_access"]
    # Panopto's server-side-web-app flow authenticates via client_secret and
    # rejects PKCE parameters alongside it (returns invalid_grant).
    use_pkce = False

    def __init__(self, nowfn: NowFn = utcnow) -> None:
        super().__init__(nowfn=nowfn)
        self._discovery_cache: dict[str, dict[str, Any]] = {}
        self._discovery_lock = asyncio.Lock()

    # ---- tenant resolution ----------------------------------------------

    def _tenant(self, tenant: str | None) -> PanoptoTenantSettings:
        if tenant is None:
            raise ConnectorNotConfigured("Panopto connector requires a tenant")
        resolved = config.connectors.panopto.tenant(tenant)
        if resolved is None:
            raise ConnectorNotConfigured(f"Panopto tenant '{tenant}' is not configured")
        return resolved

    def client_credentials(self, tenant: str | None) -> tuple[str, str]:
        t = self._tenant(tenant)
        return t.client_id, t.client_secret

    def tenant_friendly_name(self, tenant: str | None) -> str | None:
        # Intentionally returns None for unknown/unconfigured tenants rather
        # than raising ConnectorNotConfigured (unlike tenant_host and
        # client_credentials which go through _tenant()).  This method is used
        # for UI display; returning None lets the caller fall back gracefully
        # instead of surfacing a 500 to the user.
        if tenant is None:
            return None
        resolved = config.connectors.panopto.tenant(tenant)
        return resolved.tenant_friendly_name if resolved else None

    def tenant_host(self, tenant: str | None) -> str:
        return self._tenant(tenant).host

    # ---- discovery ------------------------------------------------------

    async def _discovery(self, tenant: str | None) -> dict[str, Any]:
        host = self.tenant_host(tenant)
        if host in self._discovery_cache:
            return self._discovery_cache[host]
        async with self._discovery_lock:
            # Another coroutine may have filled the cache while we waited.
            if host in self._discovery_cache:
                return self._discovery_cache[host]
            url = f"https://{host}{DISCOVERY_PATH}"
            try:
                async with httpx.AsyncClient(timeout=HTTP_TIMEOUT_SECONDS) as client:
                    response = await client.get(url)
            except httpx.HTTPError as e:
                raise ConnectorError(
                    f"Panopto OIDC discovery failed for {host}: {e}"
                ) from e
            if response.status_code >= 400:
                raise ConnectorError(
                    f"Panopto OIDC discovery for {host} returned {response.status_code}"
                )
            try:
                payload = response.json()
            except ValueError as e:
                raise ConnectorError(
                    f"Panopto OIDC discovery for {host} returned non-JSON"
                ) from e
            if not isinstance(payload, dict):
                raise ConnectorError(
                    f"Panopto OIDC discovery for {host} returned non-object"
                )
            self._discovery_cache[host] = payload
            return payload

    async def authorize_endpoint(self, tenant: str | None) -> str:
        doc = await self._discovery(tenant)
        endpoint = doc.get("authorization_endpoint")
        if not isinstance(endpoint, str) or not endpoint:
            raise ConnectorError("Panopto discovery missing authorization_endpoint")
        return endpoint

    async def token_endpoint(self, tenant: str | None) -> str:
        doc = await self._discovery(tenant)
        endpoint = doc.get("token_endpoint")
        if not isinstance(endpoint, str) or not endpoint:
            raise ConnectorError("Panopto discovery missing token_endpoint")
        return endpoint

    async def revoke_endpoint(self, tenant: str | None) -> str | None:
        doc = await self._discovery(tenant)
        endpoint = doc.get("revocation_endpoint")
        return endpoint if isinstance(endpoint, str) and endpoint else None
