from datetime import datetime, timedelta, timezone
from typing import ClassVar
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from pingpong.connectors import (
    ConnectorError,
    ConnectorTokens,
    OAuth2Connector,
    PKCEPair,
    TokenRefreshError,
    generate_pkce_pair,
)
from pingpong.models import UserConnector

pytestmark = pytest.mark.asyncio


NOW = datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)


def fixed_now():
    return NOW


class _StubConnector(OAuth2Connector):
    slug = "stub"
    display_name = "Stub"
    requires_tenant = False
    scopes: ClassVar[list[str]] = ["openid", "api"]

    def __init__(self, *, revoke_url: str | None = None, nowfn=fixed_now):
        super().__init__(nowfn=nowfn)
        self.revoke_url = revoke_url

    def client_credentials(self, tenant):
        return "stub-client-id", "stub-client-secret"

    async def authorize_endpoint(self, tenant):
        return "https://stub.example/oauth/authorize"

    async def token_endpoint(self, tenant):
        return "https://stub.example/oauth/token"

    async def revoke_endpoint(self, tenant):
        return self.revoke_url


def _make_httpx_response(
    status_code: int = 200,
    json_body: dict | None = None,
    text: str = "",
) -> httpx.Response:
    if json_body is not None:
        return httpx.Response(status_code, json=json_body)
    return httpx.Response(status_code, text=text)


def _patch_async_client(monkeypatch, post=None, get=None):
    """Replace ``httpx.AsyncClient`` with a mock that records calls."""
    instance = MagicMock()
    instance.post = AsyncMock(side_effect=post) if post else AsyncMock()
    instance.get = AsyncMock(side_effect=get) if get else AsyncMock()
    instance.__aenter__ = AsyncMock(return_value=instance)
    instance.__aexit__ = AsyncMock(return_value=None)
    ctor = MagicMock(return_value=instance)
    monkeypatch.setattr(
        "pingpong.connectors.base.httpx.AsyncClient", ctor, raising=True
    )
    return instance


async def test_build_authorize_url_encodes_params():
    connector = _StubConnector()
    pkce = PKCEPair(verifier="v" * 43, challenge="c" * 43)
    url = await connector.build_authorize_url(
        tenant=None,
        redirect_uri="https://pingpong.test/cb",
        state="state-jwt",
        pkce=pkce,
    )
    assert url.startswith("https://stub.example/oauth/authorize?")
    assert "response_type=code" in url
    assert "client_id=stub-client-id" in url
    assert "scope=openid+api" in url
    assert "code_challenge=" + "c" * 43 in url
    assert "code_challenge_method=S256" in url
    assert "state=state-jwt" in url
    assert "redirect_uri=https%3A%2F%2Fpingpong.test%2Fcb" in url


async def test_exchange_code_parses_tokens_and_sets_expiry(monkeypatch):
    connector = _StubConnector()

    async def post(url, data=None, headers=None):
        assert url == "https://stub.example/oauth/token"
        assert data["grant_type"] == "authorization_code"
        assert data["code"] == "auth-code-1"
        assert data["code_verifier"] == "verifier-xyz"
        return _make_httpx_response(
            json_body={
                "access_token": "at-1",
                "refresh_token": "rt-1",
                "expires_in": 3600,
                "scope": "openid api",
            }
        )

    _patch_async_client(monkeypatch, post=post)
    tokens = await connector.exchange_code(
        code="auth-code-1",
        tenant=None,
        redirect_uri="https://pingpong.test/cb",
        pkce_verifier="verifier-xyz",
    )
    assert tokens.access_token == "at-1"
    assert tokens.refresh_token == "rt-1"
    assert tokens.scopes == "openid api"
    assert tokens.expires_at == NOW + timedelta(seconds=3600)


async def test_exchange_code_raises_on_error_status(monkeypatch):
    connector = _StubConnector()

    async def post(url, data=None, headers=None):
        return _make_httpx_response(
            status_code=400,
            json_body={"error": "invalid_grant", "error_description": "bad code"},
        )

    _patch_async_client(monkeypatch, post=post)
    with pytest.raises(ConnectorError) as excinfo:
        await connector.exchange_code(
            code="bad",
            tenant=None,
            redirect_uri="https://pingpong.test/cb",
            pkce_verifier="v",
        )
    assert "400" in str(excinfo.value)
    assert "bad code" in str(excinfo.value)


async def test_refresh_reuses_refresh_token_when_provider_omits_it(monkeypatch):
    connector = _StubConnector()

    async def post(url, data=None, headers=None):
        assert data["grant_type"] == "refresh_token"
        assert data["refresh_token"] == "existing-rt"
        return _make_httpx_response(
            json_body={
                "access_token": "new-at",
                "expires_in": 3600,
            }
        )

    _patch_async_client(monkeypatch, post=post)

    row = UserConnector(
        id=1,
        user_id=1,
        service="stub",
        tenant=None,
        access_token="stale-at",
        refresh_token="existing-rt",
    )
    tokens = await connector.refresh(row)
    assert tokens.access_token == "new-at"
    # Provider omitted refresh_token; we should carry the existing one forward.
    assert tokens.refresh_token == "existing-rt"


async def test_refresh_fails_without_refresh_token(monkeypatch):
    connector = _StubConnector()
    row = UserConnector(
        id=1,
        user_id=1,
        service="stub",
        tenant=None,
        access_token="at",
        refresh_token=None,
    )
    with pytest.raises(TokenRefreshError):
        await connector.refresh(row)


async def test_refresh_wraps_http_errors_as_token_refresh_error(monkeypatch):
    connector = _StubConnector()

    async def post(url, data=None, headers=None):
        return _make_httpx_response(
            status_code=401, json_body={"error": "unauthorized"}
        )

    _patch_async_client(monkeypatch, post=post)
    row = UserConnector(
        id=1,
        user_id=1,
        service="stub",
        tenant=None,
        access_token="at",
        refresh_token="rt",
    )
    with pytest.raises(TokenRefreshError):
        await connector.refresh(row)


async def test_revoke_is_noop_when_subclass_has_no_endpoint(monkeypatch):
    connector = _StubConnector(revoke_url=None)
    client = _patch_async_client(monkeypatch)
    row = UserConnector(
        id=1,
        user_id=1,
        service="stub",
        tenant=None,
        access_token="at",
        refresh_token="rt",
    )
    await connector.revoke(row)
    client.post.assert_not_called()


async def test_revoke_posts_when_endpoint_exists(monkeypatch):
    connector = _StubConnector(revoke_url="https://stub.example/oauth/revoke")
    captured = {}

    async def post(url, data=None):
        captured["url"] = url
        captured["data"] = data
        return _make_httpx_response(status_code=200, json_body={})

    _patch_async_client(monkeypatch, post=post)
    row = UserConnector(
        id=1,
        user_id=1,
        service="stub",
        tenant=None,
        access_token="at",
        refresh_token="rt",
    )
    await connector.revoke(row)
    assert captured["url"] == "https://stub.example/oauth/revoke"
    assert captured["data"]["token"] == "rt"
    assert captured["data"]["token_type_hint"] == "refresh_token"


async def test_revoke_swallows_http_errors(monkeypatch):
    connector = _StubConnector(revoke_url="https://stub.example/oauth/revoke")

    async def post(url, data=None):
        raise httpx.ConnectError("boom")

    _patch_async_client(monkeypatch, post=post)
    row = UserConnector(
        id=1,
        user_id=1,
        service="stub",
        tenant=None,
        access_token="at",
        refresh_token="rt",
    )
    # Should not raise — revoke is best-effort.
    await connector.revoke(row)


async def test_get_access_token_refreshes_when_expired(monkeypatch, db):
    connector = _StubConnector()

    async def post(url, data=None, headers=None):
        return _make_httpx_response(
            json_body={
                "access_token": "refreshed-at",
                "refresh_token": "new-rt",
                "expires_in": 3600,
            }
        )

    _patch_async_client(monkeypatch, post=post)

    from pingpong.models import Base, User

    await db.init(Base, drop_first=True)
    async with db.async_session() as session:
        user = User(id=42, email="u@example.com")
        session.add(user)
        await session.flush()
        row = UserConnector(
            user_id=user.id,
            service="stub",
            access_token="stale-at",
            refresh_token="old-rt",
            expires_at=NOW - timedelta(seconds=10),
        )
        session.add(row)
        await session.flush()

        token = await connector.get_access_token(session, row)
        assert token == "refreshed-at"
        assert row.refresh_token == "new-rt"


async def test_get_access_token_returns_existing_when_fresh(monkeypatch, db):
    connector = _StubConnector()
    client = _patch_async_client(monkeypatch)

    from pingpong.models import Base, User

    await db.init(Base, drop_first=True)
    async with db.async_session() as session:
        user = User(id=43, email="u2@example.com")
        session.add(user)
        await session.flush()
        row = UserConnector(
            user_id=user.id,
            service="stub",
            access_token="fresh-at",
            refresh_token="rt",
            expires_at=NOW + timedelta(hours=1),
        )
        session.add(row)
        await session.flush()
        token = await connector.get_access_token(session, row)
        assert token == "fresh-at"
    client.post.assert_not_called()


async def test_generate_pkce_pair_yields_valid_pair():
    pair = generate_pkce_pair()
    assert pair.method == "S256"
    assert len(pair.verifier) >= 43
    assert len(pair.challenge) >= 43
    assert "=" not in pair.challenge  # Base64URL without padding.


async def test_connector_tokens_dataclass_defaults():
    tokens = ConnectorTokens(
        access_token="a",
        refresh_token=None,
        expires_at=None,
        scopes=None,
    )
    assert tokens.external_user_id is None
    assert tokens.raw is None
