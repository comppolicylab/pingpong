from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

from authlib.integrations.httpx_client import AsyncOAuth2Client
from sqlalchemy.ext.asyncio import AsyncSession

from .exceptions import ConnectorNotConfigured
from .types import ConnectorTokens, ProviderIdentity

if TYPE_CHECKING:
    from pingpong.models import ConnectorConfig, UserConnector

    from .base import OAuth2Connector

REFRESH_THRESHOLD_SECONDS = 60


async def load_connector_config(
    session: AsyncSession, row: "UserConnector"
) -> "ConnectorConfig":
    from pingpong.models import ConnectorConfig

    connector_config = await session.get(ConnectorConfig, row.connector_config_id)
    if connector_config is None:
        raise ConnectorNotConfigured(
            f"ConnectorConfig id={row.connector_config_id} not found"
        )
    return connector_config


async def load_connector_config_by_id(
    session: AsyncSession, connector_config_id: int
) -> "ConnectorConfig":
    from pingpong.models import ConnectorConfig

    connector_config = await session.get(ConnectorConfig, connector_config_id)
    if connector_config is None:
        raise ConnectorNotConfigured(
            f"ConnectorConfig id={connector_config_id} not found"
        )
    return connector_config


async def upsert_user_connector(
    session: AsyncSession,
    *,
    user_id: int,
    connector_config: "ConnectorConfig",
    tokens: ConnectorTokens,
    identity: ProviderIdentity | None = None,
) -> "UserConnector":
    from pingpong.models import UserConnector

    external_user_id = identity.external_user_id if identity else None
    row = await UserConnector.get_for_user_connector_config(
        session,
        user_id,
        connector_config.id,
        external_user_id=external_user_id,
    )
    if row is None:
        row = UserConnector(
            user_id=user_id,
            connector_config_id=connector_config.id,
            service=connector_config.service,
            access_token=tokens.access_token,
            refresh_token=tokens.refresh_token,
            expires_at=tokens.expires_at,
            scopes=tokens.scopes,
            external_user_id=external_user_id,
            external_identity=identity.external_identity if identity else None,
        )
        session.add(row)
    else:
        apply_tokens(row, tokens)
        row.external_user_id = external_user_id
        row.external_identity = identity.external_identity if identity else None
    await session.flush()
    return row


async def client_for_user_connector(
    session: AsyncSession,
    connector: "OAuth2Connector",
    row: "UserConnector",
) -> AsyncOAuth2Client:
    connector_config = await load_connector_config(session, row)
    if token_expired(row, now=connector.now()):
        tokens = await connector.refresh(connector_config, row)
        apply_tokens(row, tokens)
        await session.flush()
    return connector.oauth_client(
        connector_config,
        token={
            "access_token": row.access_token,
            "refresh_token": row.refresh_token,
            "token_type": "Bearer",
            "expires_at": expires_at_timestamp(row.expires_at),
        },
    )


def apply_tokens(connector: "UserConnector", tokens: ConnectorTokens) -> None:
    connector.access_token = tokens.access_token
    if tokens.refresh_token is not None:
        connector.refresh_token = tokens.refresh_token
    expires_at = tokens.expires_at
    if expires_at is not None and expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    connector.expires_at = expires_at
    if tokens.scopes is not None:
        connector.scopes = tokens.scopes


def token_expired(connector: "UserConnector", *, now: datetime) -> bool:
    if connector.expires_at is None:
        return False
    expires_at = connector.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    return expires_at - now <= timedelta(seconds=REFRESH_THRESHOLD_SECONDS)


def expires_at_timestamp(expires_at: datetime | None) -> int | None:
    if expires_at is None:
        return None
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    return int(expires_at.timestamp())
