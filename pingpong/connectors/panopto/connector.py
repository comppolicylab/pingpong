from __future__ import annotations

from pingpong.models import ConnectorConfig

from pingpong.connectors.core.base import OAuth2Connector
from .discovery import PanoptoDiscovery


class PanoptoConnector(OAuth2Connector):
    slug = "panopto"
    display_name = "Panopto"
    icon = "/icons/panopto.svg"
    scopes = ("openid", "api", "offline_access")
    use_pkce = False

    def __init__(self) -> None:
        super().__init__()
        self._discovery = PanoptoDiscovery()

    async def authorize_endpoint(self, connector_config: ConnectorConfig) -> str:
        return await self._discovery.required_endpoint(
            connector_config, "authorization_endpoint"
        )

    async def token_endpoint(self, connector_config: ConnectorConfig) -> str:
        return await self._discovery.required_endpoint(
            connector_config, "token_endpoint"
        )

    async def userinfo_endpoint(self, connector_config: ConnectorConfig) -> str | None:
        return await self._discovery.optional_endpoint(
            connector_config, "userinfo_endpoint"
        )

    async def issuer(self, connector_config: ConnectorConfig) -> str | None:
        return await self._discovery.optional_endpoint(connector_config, "issuer")

    async def jwks_endpoint(self, connector_config: ConnectorConfig) -> str | None:
        return await self._discovery.optional_endpoint(connector_config, "jwks_uri")

    async def revoke_endpoint(self, connector_config: ConnectorConfig) -> str | None:
        return await self._discovery.optional_endpoint(
            connector_config, "revocation_endpoint"
        )
