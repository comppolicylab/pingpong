from __future__ import annotations

import logging

from pingpong.models import ConnectorConfig

from pingpong.connectors.core.base import OAuth2Connector, friendly_network_error
from pingpong.connectors.core.exceptions import (
    ConnectorError,
    ConnectorValidationError,
)
from .discovery import PanoptoDiscovery

logger = logging.getLogger(__name__)


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

    async def validate_host(self, connector_config: ConnectorConfig) -> None:
        try:
            doc = await self._discovery.document(connector_config)
        except ConnectorError as e:
            logger.info(
                "Panopto host validation failed for %s: %s",
                connector_config.host,
                e,
            )
            raise ConnectorValidationError(
                "host", self._friendly_discovery_error(e)
            ) from e
        for key in ("authorization_endpoint", "token_endpoint"):
            if not isinstance(doc.get(key), str) or not doc[key]:
                raise ConnectorValidationError(
                    "host",
                    "This host does not look like a Panopto OIDC endpoint.",
                )

    @staticmethod
    def _friendly_discovery_error(err: ConnectorError) -> str:
        cause = err.__cause__
        if cause is not None:
            return friendly_network_error(cause)
        text = str(err)
        if "returned " in text:
            return "Host is reachable but is not a Panopto OIDC endpoint."
        if "non-JSON" in text or "non-object" in text:
            return "Host responded but did not return a valid OIDC document."
        return "Could not reach this host."

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
