from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, ConfigDict

from pingpong.models import ConnectorConfig, UserConnector


class ConnectorTypeModel(BaseModel):
    model_config = ConfigDict(arbitrary_types_allowed=True)


class ConnectorTokens(ConnectorTypeModel):
    access_token: str
    refresh_token: str | None
    expires_at: datetime | None
    scopes: str | None
    raw: dict[str, Any] | None = None


class ProviderIdentity(ConnectorTypeModel):
    external_user_id: str | None
    external_identity: dict[str, Any] | None


class PKCEPair(ConnectorTypeModel):
    verifier: str
    method: str = "S256"


class ConnectIntent(ConnectorTypeModel):
    url: str
    state: str
    nonce: str
    pkce: PKCEPair | None
    connector_config: ConnectorConfig


class CallbackResult(ConnectorTypeModel):
    row: UserConnector
    connector_config: ConnectorConfig
    tokens: ConnectorTokens
    identity: ProviderIdentity


def expires_at_timestamp(expires_at: datetime | None) -> int | None:
    if expires_at is None:
        return None
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    return int(expires_at.timestamp())
