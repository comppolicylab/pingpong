from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pytest
from sqlalchemy import func, select

from pingpong.connectors.core.base import OAuth2Connector
from pingpong.connectors.core.models import upsert_user_connector
from pingpong.connectors.core.types import ConnectorTokens, ProviderIdentity
from pingpong.models import ConnectorConfig, User, UserConnector


class ScopedConnector(OAuth2Connector):
    scopes = ("openid", "api", "offline_access")

    async def authorize_endpoint(self, connector_config: Any) -> str:
        return "https://example.test/authorize"

    async def token_endpoint(self, connector_config: Any) -> str:
        return "https://example.test/token"


def connector_config() -> ConnectorConfig:
    return ConnectorConfig(
        service="panopto",
        account_scope="test",
        display_name="Test Panopto",
        host="https://example.test",
        client_id="client-id",
        client_secret="client-secret",
    )


def user_connector() -> UserConnector:
    return UserConnector(
        id=123,
        user_id=1,
        connector_config_id=1,
        service="panopto",
        access_token="old-access-token",
        refresh_token="stored-refresh-token",
    )


@pytest.mark.asyncio
async def test_oauth_client_can_omit_configured_scopes() -> None:
    connector = ScopedConnector()
    scoped_client = connector._oauth_client(connector_config())
    scopeless_client = connector._oauth_client(connector_config(), include_scope=False)

    try:
        assert scoped_client.scope == "openid api offline_access"
        assert scopeless_client.scope is None
    finally:
        await scoped_client.aclose()
        await scopeless_client.aclose()


@pytest.mark.asyncio
async def test_refresh_uses_scopeless_oauth_client() -> None:
    class RefreshClient:
        async def __aenter__(self) -> "RefreshClient":
            return self

        async def __aexit__(self, *args: object) -> None:
            return None

        async def refresh_token(
            self, token_url: str, *, refresh_token: str
        ) -> dict[str, str]:
            assert token_url == "https://example.test/token"
            assert refresh_token == "stored-refresh-token"
            return {"access_token": "new-access-token"}

    class RecordingConnector(ScopedConnector):
        include_scope: bool | None = None

        def _oauth_client(
            self,
            connector_config: ConnectorConfig,
            *,
            redirect_uri: str | None = None,
            token: dict[str, Any] | None = None,
            code_challenge_method: str | None = None,
            include_scope: bool = True,
        ) -> RefreshClient:
            self.include_scope = include_scope
            return RefreshClient()

    connector = RecordingConnector()
    tokens = await connector.refresh(
        connector_config(),
        user_connector(),
    )

    assert connector.include_scope is False
    assert tokens.access_token == "new-access-token"
    assert tokens.refresh_token == "stored-refresh-token"


@pytest.mark.asyncio
async def test_upsert_user_connector_updates_existing_identity_row(db) -> None:
    async with db.async_session() as session:
        user = User(email="identity@example.test")
        config = connector_config()
        session.add_all([user, config])
        await session.flush()

        first = await upsert_user_connector(
            session,
            user_id=user.id,
            connector_config=config,
            tokens=ConnectorTokens(
                access_token="first-access-token",
                refresh_token="first-refresh-token",
                expires_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
                scopes="openid offline_access",
            ),
            identity=ProviderIdentity(
                external_user_id="provider-user-1",
                external_identity={"email": "first@example.test"},
            ),
        )
        second = await upsert_user_connector(
            session,
            user_id=user.id,
            connector_config=config,
            tokens=ConnectorTokens(
                access_token="second-access-token",
                refresh_token=None,
                expires_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
                scopes=None,
            ),
            identity=ProviderIdentity(
                external_user_id="provider-user-1",
                external_identity={"email": "second@example.test"},
            ),
        )

        count = await session.scalar(select(func.count(UserConnector.id)))

        assert first.id == second.id
        assert count == 1
        assert second.access_token == "second-access-token"
        assert second.refresh_token == "first-refresh-token"
        assert second.scopes == "openid offline_access"
        assert second.external_identity == {"email": "second@example.test"}


@pytest.mark.asyncio
async def test_upsert_user_connector_updates_existing_no_identity_row(db) -> None:
    async with db.async_session() as session:
        user = User(email="no-identity@example.test")
        config = connector_config()
        session.add_all([user, config])
        await session.flush()

        first = await upsert_user_connector(
            session,
            user_id=user.id,
            connector_config=config,
            tokens=ConnectorTokens(
                access_token="first-access-token",
                refresh_token="first-refresh-token",
                expires_at=None,
                scopes=None,
            ),
        )
        second = await upsert_user_connector(
            session,
            user_id=user.id,
            connector_config=config,
            tokens=ConnectorTokens(
                access_token="second-access-token",
                refresh_token="second-refresh-token",
                expires_at=None,
                scopes="api",
            ),
        )

        count = await session.scalar(select(func.count(UserConnector.id)))

        assert first.id == second.id
        assert count == 1
        assert second.access_token == "second-access-token"
        assert second.refresh_token == "second-refresh-token"
        assert second.scopes == "api"
        assert second.external_user_id is None
