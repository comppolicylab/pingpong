from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any


@dataclass
class ConnectorTokens:
    access_token: str
    refresh_token: str | None
    expires_at: datetime | None
    scopes: str | None
    raw: dict[str, Any] | None = None


@dataclass
class ProviderIdentity:
    external_user_id: str | None
    external_identity: dict[str, Any] | None


@dataclass
class PKCEPair:
    verifier: str
    method: str = "S256"


def expires_at_timestamp(expires_at: datetime | None) -> int | None:
    if expires_at is None:
        return None
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    return int(expires_at.timestamp())
