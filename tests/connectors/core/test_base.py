from __future__ import annotations

import base64
from datetime import datetime, timedelta, timezone
from typing import Any, ClassVar
from unittest.mock import AsyncMock, MagicMock

import jwt
import pytest

from pingpong.connectors.core.base import OAuth2Connector
from pingpong.connectors.core.exceptions import ConnectorError, TokenRefreshError
from pingpong.connectors.core.models import (
    client_for_user_connector,
    upsert_user_connector,
)
from pingpong.connectors.core.types import ConnectorTokens, PKCEPair
from pingpong.models import Base, ConnectorConfig, User, UserConnector

pytestmark = pytest.mark.asyncio

NOW = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)


def fixed_now():
    return NOW


class _StubConnector(OAuth2Connector):
    slug = "stub"
    display_name = "Stub"
    scopes: ClassVar[tuple[str, ...]] = ("openid", "api")

    def __init__(self, *, nowfn=fixed_now) -> None:
        super().__init__(nowfn=nowfn)

    async def authorize_endpoint(self, connector_config):
        return f"https://{connector_config.host}/oauth/authorize"

    async def token_endpoint(self, connector_config):
        return f"https://{connector_config.host}/oauth/token"

    async def userinfo_endpoint(self, connector_config):
        return f"https://{connector_config.host}/oauth/userinfo"

    async def revoke_endpoint(self, connector_config):
        return f"https://{connector_config.host}/oauth/revoke"


class _IdTokenConnector(_StubConnector):
    async def userinfo_endpoint(self, connector_config):
        return None

    async def issuer(self, connector_config):
        return "https://issuer.example"

    async def jwks_endpoint(self, connector_config):
        return "https://issuer.example/jwks"


class _FakeOAuthClient:
    instances: ClassVar[list["_FakeOAuthClient"]] = []
    fetch_token_payload: ClassVar[dict[str, Any] | Exception] = {}
    refresh_token_payload: ClassVar[dict[str, Any] | Exception] = {}
    revoke_response: ClassVar[Any] = None
    get_payload: ClassVar[dict[str, Any]] = {}

    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []
        _FakeOAuthClient.instances.append(self)

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def aclose(self):
        self.calls.append(("aclose", (), {}))

    def create_authorization_url(self, url, state=None, code_verifier=None, **kwargs):
        self.calls.append(
            (
                "create_authorization_url",
                (url,),
                {"state": state, "code_verifier": code_verifier, **kwargs},
            )
        )
        return f"{url}?client_id={self.kwargs['client_id']}&state={state}", state

    async def fetch_token(self, url, **kwargs):
        self.calls.append(("fetch_token", (url,), kwargs))
        if isinstance(_FakeOAuthClient.fetch_token_payload, Exception):
            raise _FakeOAuthClient.fetch_token_payload
        return _FakeOAuthClient.fetch_token_payload

    async def refresh_token(self, url, **kwargs):
        self.calls.append(("refresh_token", (url,), kwargs))
        if isinstance(_FakeOAuthClient.refresh_token_payload, Exception):
            raise _FakeOAuthClient.refresh_token_payload
        return _FakeOAuthClient.refresh_token_payload

    async def revoke_token(self, url, **kwargs):
        self.calls.append(("revoke_token", (url,), kwargs))
        return _FakeOAuthClient.revoke_response

    async def get(self, url, **kwargs):
        self.calls.append(("get", (url,), kwargs))
        return _JsonResponse(_FakeOAuthClient.get_payload)

    async def post(self, url, **kwargs):
        self.calls.append(("post", (url,), kwargs))
        return _JsonResponse({"ok": True})


class _JsonResponse:
    status_code = 200
    text = ""

    def __init__(self, payload):
        self._payload = payload

    @property
    def is_error(self):
        return self.status_code >= 400

    def json(self):
        return self._payload


def _patch_jwks(monkeypatch, payload):
    client = MagicMock()
    client.get = AsyncMock(return_value=_JsonResponse(payload))
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=None)
    monkeypatch.setattr(
        "pingpong.connectors.core.identity.httpx.AsyncClient",
        MagicMock(return_value=client),
        raising=True,
    )
    return client


def _oct_jwks(secret: bytes, kid: str = "test-key") -> dict[str, Any]:
    encoded = base64.urlsafe_b64encode(secret).rstrip(b"=").decode("ascii")
    return {"keys": [{"kty": "oct", "kid": kid, "alg": "HS256", "k": encoded}]}


@pytest.fixture(autouse=True)
def _patch_authlib(monkeypatch):
    _FakeOAuthClient.instances = []
    _FakeOAuthClient.fetch_token_payload = {}
    _FakeOAuthClient.refresh_token_payload = {}
    _FakeOAuthClient.revoke_response = None
    _FakeOAuthClient.get_payload = {}
    monkeypatch.setattr(
        "pingpong.connectors.core.base.AsyncOAuth2Client",
        _FakeOAuthClient,
        raising=True,
    )


def _config(id: int = 1) -> ConnectorConfig:
    return ConnectorConfig(
        id=id,
        service="stub",
        account_scope="demo",
        display_name="Demo Stub",
        host="stub.example",
        client_id="client-id",
        client_secret="client-secret",
        enabled=True,
    )


async def test_authorize_url_generation_uses_pingpong_state():
    connector = _StubConnector()
    url = await connector.build_authorize_url(
        connector_config=_config(),
        redirect_uri="https://pingpong.test/callback",
        state="signed-state",
        pkce=PKCEPair(verifier="verifier-123"),
        nonce="nonce-123",
    )

    assert (
        url
        == "https://stub.example/oauth/authorize?client_id=client-id&state=signed-state"
    )
    client = _FakeOAuthClient.instances[0]
    assert client.kwargs["client_id"] == "client-id"
    assert client.kwargs["client_secret"] == "client-secret"
    assert client.kwargs["scope"] == "openid api"
    assert client.kwargs["code_challenge_method"] == "S256"
    assert client.calls[0][2]["state"] == "signed-state"
    assert client.calls[0][2]["code_verifier"] == "verifier-123"
    assert client.calls[0][2]["nonce"] == "nonce-123"


async def test_exchange_code_uses_authlib_fetch_token_and_parses_response():
    _FakeOAuthClient.fetch_token_payload = {
        "access_token": "at-1",
        "refresh_token": "rt-1",
        "expires_in": 3600,
        "scope": "openid api",
    }
    connector = _StubConnector()

    tokens = await connector.exchange_code(
        connector_config=_config(),
        code="auth-code",
        redirect_uri="https://pingpong.test/callback",
        state="signed-state",
        pkce_verifier="verifier-123",
    )

    assert tokens.access_token == "at-1"
    assert tokens.refresh_token == "rt-1"
    assert tokens.expires_at == NOW + timedelta(seconds=3600)
    call = _FakeOAuthClient.instances[0].calls[0]
    assert call[0] == "fetch_token"
    assert call[1] == ("https://stub.example/oauth/token",)
    assert call[2]["code"] == "auth-code"
    assert call[2]["state"] == "signed-state"
    assert call[2]["code_verifier"] == "verifier-123"


async def test_refresh_uses_authlib_and_reuses_existing_refresh_token():
    _FakeOAuthClient.refresh_token_payload = {
        "access_token": "new-at",
        "expires_in": 3600,
    }
    connector = _StubConnector()
    row = UserConnector(
        id=1,
        user_id=1,
        connector_config_id=1,
        service="stub",
        access_token="old-at",
        refresh_token="old-rt",
    )

    tokens = await connector.refresh(_config(), row)

    assert tokens.access_token == "new-at"
    assert tokens.refresh_token == "old-rt"
    call = _FakeOAuthClient.instances[0].calls[0]
    assert call[0] == "refresh_token"
    assert call[1] == ("https://stub.example/oauth/token",)
    assert call[2]["refresh_token"] == "old-rt"


async def test_refresh_without_refresh_token_raises():
    connector = _StubConnector()
    row = UserConnector(
        id=1,
        user_id=1,
        connector_config_id=1,
        service="stub",
        access_token="at",
        refresh_token=None,
    )
    with pytest.raises(TokenRefreshError):
        await connector.refresh(_config(), row)


async def test_revoke_is_best_effort_via_authlib():
    connector = _StubConnector()
    row = UserConnector(
        id=1,
        user_id=1,
        connector_config_id=1,
        service="stub",
        access_token="at",
        refresh_token="rt",
    )

    await connector.revoke(_config(), row)

    call = _FakeOAuthClient.instances[0].calls[0]
    assert call[0] == "revoke_token"
    assert call[1] == ("https://stub.example/oauth/revoke",)
    assert call[2]["token"] == "rt"
    assert call[2]["token_type_hint"] == "refresh_token"


async def test_fetch_identity_maps_userinfo_to_external_identity():
    _FakeOAuthClient.get_payload = {
        "sub": "provider-user-1",
        "email": "student@example.com",
        "name": "Student User",
        "access_token": "should-not-persist",
        "headers": {"Authorization": "Bearer should-not-persist"},
    }
    connector = _StubConnector()
    tokens = ConnectorTokens(
        access_token="at",
        refresh_token="rt",
        expires_at=NOW + timedelta(hours=1),
        scopes="openid api",
    )

    identity = await connector.fetch_identity(
        connector_config=_config(),
        tokens=tokens,
    )

    assert identity.external_user_id == "provider-user-1"
    assert identity.external_identity == {
        "source": "userinfo",
        "claims": {
            "sub": "provider-user-1",
            "email": "student@example.com",
            "name": "Student User",
        },
    }
    call = _FakeOAuthClient.instances[0].calls[0]
    assert call[0] == "get"
    assert call[1] == ("https://stub.example/oauth/userinfo",)


async def test_fetch_identity_requires_userinfo_sub():
    _FakeOAuthClient.get_payload = {"email": "student@example.com"}
    connector = _StubConnector()
    tokens = ConnectorTokens(
        access_token="at",
        refresh_token="rt",
        expires_at=None,
        scopes=None,
    )

    with pytest.raises(ConnectorError, match="sub"):
        await connector.fetch_identity(connector_config=_config(), tokens=tokens)


async def test_fetch_identity_falls_back_to_validated_id_token(monkeypatch):
    secret = b"id-token-secret-for-tests-32-bytes"
    exp = int((datetime.now(timezone.utc) + timedelta(hours=1)).timestamp())
    id_token = jwt.encode(
        {
            "sub": "id-token-user-1",
            "iss": "https://issuer.example",
            "aud": "client-id",
            "exp": exp,
            "nonce": "nonce-123",
            "email": "student@example.com",
            "access_token": "should-not-persist",
        },
        secret,
        algorithm="HS256",
        headers={"kid": "test-key"},
    )
    jwks_client = _patch_jwks(monkeypatch, _oct_jwks(secret))
    connector = _IdTokenConnector()
    tokens = ConnectorTokens(
        access_token="at",
        refresh_token="rt",
        expires_at=NOW + timedelta(hours=1),
        scopes="openid api",
        raw={"id_token": id_token},
    )

    identity = await connector.fetch_identity(
        connector_config=_config(),
        tokens=tokens,
        expected_nonce="nonce-123",
    )

    assert identity.external_user_id == "id-token-user-1"
    assert identity.external_identity == {
        "source": "id_token",
        "claims": {
            "sub": "id-token-user-1",
            "iss": "https://issuer.example",
            "aud": "client-id",
            "exp": exp,
            "nonce": "nonce-123",
            "email": "student@example.com",
        },
    }
    jwks_client.get.assert_awaited_once_with("https://issuer.example/jwks")


async def test_fetch_identity_refreshes_cached_jwks_on_kid_miss(monkeypatch):
    old_secret = b"old-id-token-secret-for-tests-32-bytes"
    new_secret = b"new-id-token-secret-for-tests-32-bytes"
    exp = int((datetime.now(timezone.utc) + timedelta(hours=1)).timestamp())

    old_id_token = jwt.encode(
        {
            "sub": "old-user",
            "iss": "https://issuer.example",
            "aud": "client-id",
            "exp": exp,
        },
        old_secret,
        algorithm="HS256",
        headers={"kid": "old-key"},
    )
    new_id_token = jwt.encode(
        {
            "sub": "new-user",
            "iss": "https://issuer.example",
            "aud": "client-id",
            "exp": exp,
        },
        new_secret,
        algorithm="HS256",
        headers={"kid": "new-key"},
    )

    client = MagicMock()
    client.get = AsyncMock(
        side_effect=[
            _JsonResponse(_oct_jwks(old_secret, kid="old-key")),
            _JsonResponse(_oct_jwks(new_secret, kid="new-key")),
        ]
    )
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=None)
    monkeypatch.setattr(
        "pingpong.connectors.core.identity.httpx.AsyncClient",
        MagicMock(return_value=client),
        raising=True,
    )
    connector = _IdTokenConnector()

    old_identity = await connector.fetch_identity(
        connector_config=_config(),
        tokens=ConnectorTokens(
            access_token="at",
            refresh_token="rt",
            expires_at=NOW + timedelta(hours=1),
            scopes="openid api",
            raw={"id_token": old_id_token},
        ),
    )
    new_identity = await connector.fetch_identity(
        connector_config=_config(),
        tokens=ConnectorTokens(
            access_token="at",
            refresh_token="rt",
            expires_at=NOW + timedelta(hours=1),
            scopes="openid api",
            raw={"id_token": new_id_token},
        ),
    )

    assert old_identity.external_user_id == "old-user"
    assert new_identity.external_user_id == "new-user"
    assert client.get.await_count == 2


async def test_fetch_identity_rejects_id_token_nonce_mismatch(monkeypatch):
    secret = b"id-token-secret-for-tests-32-bytes"
    id_token = jwt.encode(
        {
            "sub": "id-token-user-1",
            "iss": "https://issuer.example",
            "aud": "client-id",
            "exp": int((datetime.now(timezone.utc) + timedelta(hours=1)).timestamp()),
        },
        secret,
        algorithm="HS256",
        headers={"kid": "test-key"},
    )
    _patch_jwks(monkeypatch, _oct_jwks(secret))
    connector = _IdTokenConnector()
    tokens = ConnectorTokens(
        access_token="at",
        refresh_token="rt",
        expires_at=NOW + timedelta(hours=1),
        scopes="openid api",
        raw={"id_token": id_token},
    )

    with pytest.raises(ConnectorError, match="nonce"):
        await connector.fetch_identity(
            connector_config=_config(),
            tokens=tokens,
            expected_nonce="nonce-123",
        )


async def test_fetch_identity_without_userinfo_or_id_token_returns_none(monkeypatch):
    connector = _IdTokenConnector()
    tokens = ConnectorTokens(
        access_token="at",
        refresh_token="rt",
        expires_at=None,
        scopes=None,
        raw={},
    )

    identity = await connector.fetch_identity(connector_config=_config(), tokens=tokens)

    assert identity.external_user_id is None
    assert identity.external_identity is None


async def test_upsert_uses_user_config_and_external_user_id(db):
    connector = _StubConnector()
    await db.init(Base, drop_first=True)
    async with db.async_session() as session:
        user = User(id=10, email="student@example.com")
        config = _config(id=20)
        session.add_all([user, config])
        await session.flush()

        identity = connector.identity_from_userinfo(
            {"sub": "provider-user-1", "email": "student@example.com"}
        )
        row = await upsert_user_connector(
            session,
            user_id=user.id,
            connector_config=config,
            tokens=ConnectorTokens(
                access_token="at",
                refresh_token="rt",
                expires_at=NOW + timedelta(hours=1),
                scopes="openid api",
            ),
            identity=identity,
        )

        assert row.user_id == user.id
        assert row.connector_config_id == config.id
        assert row.service == "stub"
        assert row.external_user_id == "provider-user-1"
        assert row.external_identity["source"] == "userinfo"

        same = await upsert_user_connector(
            session,
            user_id=user.id,
            connector_config=config,
            tokens=ConnectorTokens(
                access_token="at-2",
                refresh_token=None,
                expires_at=None,
                scopes=None,
            ),
            identity=identity,
        )
        assert same.id == row.id
        assert same.access_token == "at-2"
        assert same.refresh_token == "rt"


async def test_client_for_user_connector_refreshes_before_api_calls(db):
    _FakeOAuthClient.refresh_token_payload = {
        "access_token": "fresh-at",
        "refresh_token": "fresh-rt",
        "expires_in": 3600,
    }
    connector = _StubConnector()
    await db.init(Base, drop_first=True)
    async with db.async_session() as session:
        user = User(id=11, email="student2@example.com")
        config = _config(id=21)
        row = UserConnector(
            user_id=user.id,
            connector_config_id=config.id,
            service="stub",
            access_token="stale-at",
            refresh_token="stale-rt",
            expires_at=NOW - timedelta(seconds=10),
        )
        session.add_all([user, config, row])
        await session.flush()

        client = await client_for_user_connector(session, connector, row)
        await client.get("https://stub.example/api/items")
        await client.post("https://stub.example/api/items")

        assert row.access_token == "fresh-at"
        assert row.refresh_token == "fresh-rt"
        assert client.kwargs["token"]["access_token"] == "fresh-at"
        assert client.calls[0][0] == "get"
        assert client.calls[1][0] == "post"
