from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, ClassVar

import pytest

from pingpong.connectors.core.base import OAuth2Connector
from pingpong.connectors.core.exceptions import ConnectorFlowError
from pingpong.connectors.core.flow import begin_connect, complete_callback
from pingpong.connectors.core.registry import register
from pingpong.connectors.core.state import decode_state, encode_state
from pingpong.connectors.core.types import ConnectorTokens, ProviderIdentity
from pingpong.models import Base, ConnectorConfig, User

pytestmark = pytest.mark.asyncio

NOW = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
REDIRECT_URI = "https://pingpong.test/api/v1/connectors/flowtest/callback"


def fixed_now():
    return NOW


class _FlowConnector(OAuth2Connector):
    slug = "flowtest"
    display_name = "Flow Test"
    scopes: ClassVar[list[str]] = ["openid"]
    use_pkce = True

    def __init__(self) -> None:
        super().__init__(nowfn=fixed_now)
        self.authorize_calls: list[dict[str, Any]] = []
        self.exchange_calls: list[dict[str, Any]] = []
        self.identity_calls: list[dict[str, Any]] = []

    async def authorize_endpoint(self, connector_config):
        return f"https://{connector_config.host}/authorize"

    async def token_endpoint(self, connector_config):
        return f"https://{connector_config.host}/token"

    async def build_authorize_url(self, **kwargs):
        self.authorize_calls.append(kwargs)
        return f"https://{kwargs['connector_config'].host}/authorize?state={kwargs['state']}"

    async def exchange_code(self, **kwargs):
        self.exchange_calls.append(kwargs)
        return ConnectorTokens(
            access_token="at-flow",
            refresh_token="rt-flow",
            expires_at=NOW + timedelta(hours=1),
            scopes="openid",
            raw={"id_token": "not-used"},
        )

    async def fetch_identity(self, **kwargs):
        self.identity_calls.append(kwargs)
        return ProviderIdentity(
            external_user_id="external-flow-user",
            external_identity={
                "source": "test",
                "claims": {"sub": "external-flow-user"},
            },
        )


@pytest.fixture
def flow_connector():
    connector = _FlowConnector()
    register(connector)
    return connector


def _config(id: int = 1, *, service: str = "flowtest", enabled: bool = True):
    return ConnectorConfig(
        id=id,
        service=service,
        account_scope=f"{service}-scope",
        display_name="Flow Config",
        host="flow.example",
        client_id="client-id",
        client_secret="client-secret",
        enabled=enabled,
    )


async def test_begin_connect_builds_signed_state_and_authorize_url(db, flow_connector):
    await db.init(Base, drop_first=True)
    async with db.async_session() as session:
        connector_config = _config(id=10)
        session.add(connector_config)
        await session.flush()

        intent = await begin_connect(
            session,
            user_id=42,
            service="flowtest",
            connector_config_id=connector_config.id,
            redirect_uri=REDIRECT_URI,
            nowfn=fixed_now,
        )

        decoded = decode_state(intent.state, nowfn=fixed_now)
        assert decoded["sub"] == "42"
        assert decoded["service"] == "flowtest"
        assert decoded["connector_config_id"] == connector_config.id
        assert decoded["nonce"] == intent.nonce
        assert decoded["pkce_verifier"] == intent.pkce.verifier
        assert intent.url.startswith("https://flow.example/authorize?state=")

        call = flow_connector.authorize_calls[0]
        assert call["connector_config"].id == connector_config.id
        assert call["redirect_uri"] == REDIRECT_URI
        assert call["state"] == intent.state
        assert call["pkce"] == intent.pkce
        assert call["nonce"] == intent.nonce


async def test_complete_callback_exchanges_fetches_identity_and_upserts(
    db, flow_connector
):
    await db.init(Base, drop_first=True)
    async with db.async_session() as session:
        user = User(id=42, email="student@example.com")
        connector_config = _config(id=10)
        session.add_all([user, connector_config])
        await session.flush()

        state = encode_state(
            user_id=user.id,
            service="flowtest",
            connector_config_id=connector_config.id,
            pkce_verifier="pkce-verifier",
            nonce="nonce-123",
            nowfn=fixed_now,
        )

        result = await complete_callback(
            session,
            service="flowtest",
            code="auth-code",
            state=state,
            session_user_id=user.id,
            redirect_uri=REDIRECT_URI,
            nowfn=fixed_now,
        )

        assert result.row.user_id == user.id
        assert result.row.connector_config_id == connector_config.id
        assert result.row.service == "flowtest"
        assert result.row.access_token == "at-flow"
        assert result.row.refresh_token == "rt-flow"
        assert result.row.external_user_id == "external-flow-user"
        assert result.row.external_identity["source"] == "test"

        exchange_call = flow_connector.exchange_calls[0]
        assert exchange_call["connector_config"].id == connector_config.id
        assert exchange_call["code"] == "auth-code"
        assert exchange_call["redirect_uri"] == REDIRECT_URI
        assert exchange_call["state"] == state
        assert exchange_call["pkce_verifier"] == "pkce-verifier"

        identity_call = flow_connector.identity_calls[0]
        assert identity_call["connector_config"].id == connector_config.id
        assert identity_call["tokens"].access_token == "at-flow"
        assert identity_call["expected_nonce"] == "nonce-123"


async def test_complete_callback_rejects_service_mismatch(db, flow_connector):
    await db.init(Base, drop_first=True)
    async with db.async_session() as session:
        connector_config = _config(id=10)
        session.add(connector_config)
        await session.flush()
        state = encode_state(
            user_id=42,
            service="other-service",
            connector_config_id=connector_config.id,
            pkce_verifier=None,
            nonce="nonce-123",
            nowfn=fixed_now,
        )

        with pytest.raises(ConnectorFlowError) as excinfo:
            await complete_callback(
                session,
                service="flowtest",
                code="auth-code",
                state=state,
                session_user_id=42,
                redirect_uri=REDIRECT_URI,
                nowfn=fixed_now,
            )
        assert excinfo.value.code == "service_mismatch"


async def test_begin_connect_rejects_disabled_config(db, flow_connector):
    await db.init(Base, drop_first=True)
    async with db.async_session() as session:
        connector_config = _config(id=10, enabled=False)
        session.add(connector_config)
        await session.flush()

        with pytest.raises(ConnectorFlowError) as excinfo:
            await begin_connect(
                session,
                user_id=42,
                service="flowtest",
                connector_config_id=connector_config.id,
                redirect_uri=REDIRECT_URI,
                nowfn=fixed_now,
            )
        assert excinfo.value.code == "connector_config_disabled"


async def test_begin_connect_rejects_config_service_mismatch(db, flow_connector):
    await db.init(Base, drop_first=True)
    async with db.async_session() as session:
        connector_config = _config(id=10, service="other-service")
        session.add(connector_config)
        await session.flush()

        with pytest.raises(ConnectorFlowError) as excinfo:
            await begin_connect(
                session,
                user_id=42,
                service="flowtest",
                connector_config_id=connector_config.id,
                redirect_uri=REDIRECT_URI,
                nowfn=fixed_now,
            )
        assert excinfo.value.code == "connector_config_mismatch"
