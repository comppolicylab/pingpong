"""Third-party service connectors.

The connectors package houses the OAuth2-based framework for connecting a
PingPong user to external services (Panopto today, Zoom / Zotero / etc. in
future PRs). :class:`OAuth2Connector` is the shared base class; concrete
subclasses like :class:`PanoptoConnector` plug in per-service details.

The module-level registry (``_REGISTRY``) maps stable slugs (``"panopto"``)
to singleton connector instances. Routes look up connectors by slug rather
than instantiating them directly.
"""

from __future__ import annotations

from .base import ConnectorTokens, OAuth2Connector, PKCEPair, generate_pkce_pair
from .exceptions import (
    ConnectorError,
    ConnectorNotConfigured,
    ConnectorNotRegistered,
    OAuthStateError,
    TokenRefreshError,
)
from .panopto import PanoptoConnector
from .state import decode_state, encode_state

_REGISTRY: dict[str, OAuth2Connector] = {}


def register(connector: OAuth2Connector) -> None:
    if not connector.slug:
        raise ValueError("Connector must declare a slug")
    _REGISTRY[connector.slug] = connector


def get(slug: str) -> OAuth2Connector:
    try:
        return _REGISTRY[slug]
    except KeyError as e:
        raise ConnectorNotRegistered(f"Unknown connector: {slug}") from e


def all_connectors() -> list[OAuth2Connector]:
    return list(_REGISTRY.values())


# Register the shipping connectors. A new connector is made live by adding
# one line here.
register(PanoptoConnector())


__all__ = [
    "ConnectorError",
    "ConnectorNotConfigured",
    "ConnectorNotRegistered",
    "ConnectorTokens",
    "OAuth2Connector",
    "OAuthStateError",
    "PKCEPair",
    "PanoptoConnector",
    "TokenRefreshError",
    "all_connectors",
    "decode_state",
    "encode_state",
    "generate_pkce_pair",
    "get",
    "register",
]
