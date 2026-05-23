from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

from pingpong.models import ConnectorConfig

from pingpong.connectors.core.base import HTTP_TIMEOUT_SECONDS
from pingpong.connectors.core.discovery import (
    DiscoveryDocumentCache,
    optional_string_field,
    require_string_field,
)

DISCOVERY_PATH = "/Panopto/oauth2/.well-known/openid-configuration"
DISCOVERY_LABEL = "Panopto OIDC discovery"


class PanoptoDiscovery:
    def __init__(self) -> None:
        self._documents = DiscoveryDocumentCache(timeout=HTTP_TIMEOUT_SECONDS)

    async def document(self, connector_config: ConnectorConfig) -> dict[str, Any]:
        host = self.normalize_host(connector_config.host)
        url = f"https://{host}{DISCOVERY_PATH}"
        return await self._documents.get(url, label=DISCOVERY_LABEL)

    async def required_endpoint(
        self, connector_config: ConnectorConfig, key: str
    ) -> str:
        doc = await self.document(connector_config)
        return require_string_field(doc, key, label="Panopto discovery")

    async def optional_endpoint(
        self, connector_config: ConnectorConfig, key: str
    ) -> str | None:
        doc = await self.document(connector_config)
        return optional_string_field(doc, key)

    @staticmethod
    def normalize_host(host: str) -> str:
        parsed = urlparse(host)
        if parsed.scheme and parsed.netloc:
            return parsed.netloc.rstrip("/")
        return host.removeprefix("//").strip().strip("/")
