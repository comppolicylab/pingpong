from __future__ import annotations

from .base import OAuth2Connector
from .exceptions import ConnectorNotRegistered

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
