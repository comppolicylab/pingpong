from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock

import httpx
import jwt
import pytest

from pingpong import connectors as connectors_pkg
from pingpong.config import config
from pingpong.models import UserConnector
from pingpong.testutil import with_user

pytestmark = pytest.mark.asyncio


DISCOVERY_PAYLOAD = {
    "authorization_endpoint": "https://demo.hosted.panopto.com/Panopto/oauth2/connect/authorize",
    "token_endpoint": "https://demo.hosted.panopto.com/Panopto/oauth2/connect/token",
    "revocation_endpoint": "https://demo.hosted.panopto.com/Panopto/oauth2/connect/revocation",
}


@pytest.fixture(autouse=True)
def _reset_panopto_cache():
    connectors_pkg.get("panopto")._discovery_cache.clear()
    yield
    connectors_pkg.get("panopto")._discovery_cache.clear()


def _make_httpx_mock(
    monkeypatch,
    *,
    discovery: httpx.Response | None = None,
    token: httpx.Response | None = None,
    revoke: httpx.Response | None = None,
):
    """Patch httpx.AsyncClient in both panopto and base modules."""
    discovery_response = discovery or httpx.Response(200, json=DISCOVERY_PAYLOAD)
    token_response = token or httpx.Response(
        200,
        json={
            "access_token": "at-new",
            "refresh_token": "rt-new",
            "expires_in": 3600,
            "scope": "openid api",
        },
    )
    revoke_response = revoke or httpx.Response(200, json={})

    calls: dict[str, list] = {"get": [], "post": []}

    async def get(url):
        calls["get"].append(url)
        return discovery_response

    async def post(url, data=None, headers=None):
        calls["post"].append({"url": url, "data": data, "headers": headers})
        if "token" in url and "revoke" not in url and "revocation" not in url:
            return token_response
        return revoke_response

    def make_client():
        client = MagicMock()
        client.get = AsyncMock(side_effect=get)
        client.post = AsyncMock(side_effect=post)
        client.__aenter__ = AsyncMock(return_value=client)
        client.__aexit__ = AsyncMock(return_value=None)
        return client

    monkeypatch.setattr(
        "pingpong.connectors.panopto.httpx.AsyncClient",
        MagicMock(side_effect=lambda *args, **kwargs: make_client()),
        raising=True,
    )
    monkeypatch.setattr(
        "pingpong.connectors.base.httpx.AsyncClient",
        MagicMock(side_effect=lambda *args, **kwargs: make_client()),
        raising=True,
    )
    return calls


@with_user(500)
async def test_get_my_connectors_lists_empty_when_none_exist(
    api, valid_user_token, authz
):
    response = api.get(
        "/api/v1/me/connectors",
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["connectors"] == []
    assert any(
        entry["service"] == "panopto" and entry["requires_tenant"]
        for entry in data["available"]
    )
    panopto_def = next(e for e in data["available"] if e["service"] == "panopto")
    assert any(t["tenant"] == "demo" for t in panopto_def["tenants"])


@with_user(501)
async def test_get_my_connectors_returns_existing_rows(
    api, db, valid_user_token, user, authz
):
    async with db.async_session() as session:
        session.add(
            UserConnector(
                user_id=user.id,
                service="panopto",
                tenant="demo",
                access_token="at",
                refresh_token="rt",
                expires_at=datetime(2027, 1, 1, tzinfo=timezone.utc),
                scopes="openid api",
            )
        )
        await session.commit()

    response = api.get(
        "/api/v1/me/connectors",
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )
    assert response.status_code == 200
    data = response.json()
    assert len(data["connectors"]) == 1
    row = data["connectors"][0]
    assert row["service"] == "panopto"
    assert row["tenant"] == "demo"
    assert row["tenant_friendly_name"] == "Demo Panopto"
    assert row["status"] == "active"


@with_user(502)
async def test_connect_requires_tenant_for_panopto(api, valid_user_token, authz):
    response = api.post(
        "/api/v1/connectors/panopto/connect",
        json={},
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )
    assert response.status_code == 400


@with_user(503)
async def test_connect_rejects_unknown_tenant(api, valid_user_token, authz):
    response = api.post(
        "/api/v1/connectors/panopto/connect",
        json={"tenant": "mars"},
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )
    assert response.status_code == 400


@with_user(504)
async def test_connect_rejects_unknown_service(api, valid_user_token, authz):
    response = api.post(
        "/api/v1/connectors/unknown/connect",
        json={},
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )
    assert response.status_code == 404


@with_user(505)
async def test_connect_returns_authorize_url_with_signed_state(
    api, valid_user_token, monkeypatch, authz
):
    _make_httpx_mock(monkeypatch)

    response = api.post(
        "/api/v1/connectors/panopto/connect",
        json={"tenant": "demo"},
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )
    assert response.status_code == 200
    url = response.json()["url"]
    # URL should be rooted at the tenant's configured host.
    assert url.startswith(
        "https://demo.hosted.panopto.com/Panopto/oauth2/connect/authorize?"
    )
    assert "client_id=test-panopto-client-id" in url
    # Extract state and verify it decodes to our user + tenant.
    from urllib.parse import parse_qs, urlparse

    qs = parse_qs(urlparse(url).query)
    state = qs["state"][0]
    secret = config.auth.secret_keys[0]
    decoded = jwt.decode(
        state,
        secret.key,
        algorithms=[secret.algorithm],
        options={"verify_exp": False},
    )
    assert decoded["sub"] == "505"
    assert decoded["service"] == "panopto"
    assert decoded["tenant"] == "demo"
    # Panopto's server-side flow opts out of PKCE (authenticates via
    # client_secret instead); the authorize URL should not include PKCE
    # params and the state should not carry a verifier payload.
    assert "pkce_v" not in decoded
    assert "code_challenge=" not in url


@with_user(506)
async def test_callback_exchanges_code_and_upserts_row(
    api, db, valid_user_token, user, monkeypatch, authz
):
    _make_httpx_mock(monkeypatch)

    state = connectors_pkg.encode_state(
        user_id=user.id,
        service="panopto",
        tenant="demo",
        pkce_verifier="verifier-abc",
    )
    response = api.get(
        f"/api/v1/connectors/panopto/callback?code=auth-code&state={state}",
        follow_redirects=False,
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )
    assert response.status_code == 303
    assert response.headers["location"].endswith("/profile?connected=panopto")

    async with db.async_session() as session:
        rows = await UserConnector.get_for_user(session, user.id)
        assert len(rows) == 1
        assert rows[0].service == "panopto"
        assert rows[0].tenant == "demo"
        assert rows[0].access_token == "at-new"
        assert rows[0].refresh_token == "rt-new"
        assert rows[0].expires_at is not None


@with_user(507)
async def test_callback_overwrites_existing_row_for_same_tenant(
    api, db, valid_user_token, user, monkeypatch, authz
):
    _make_httpx_mock(monkeypatch)
    async with db.async_session() as session:
        session.add(
            UserConnector(
                user_id=user.id,
                service="panopto",
                tenant="demo",
                access_token="old-at",
                refresh_token="old-rt",
            )
        )
        await session.commit()

    state = connectors_pkg.encode_state(
        user_id=user.id,
        service="panopto",
        tenant="demo",
        pkce_verifier="verifier-abc",
    )
    response = api.get(
        f"/api/v1/connectors/panopto/callback?code=auth-code&state={state}",
        follow_redirects=False,
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )
    assert response.status_code == 303

    async with db.async_session() as session:
        rows = await UserConnector.get_for_user(session, user.id)
        assert len(rows) == 1
        assert rows[0].access_token == "at-new"


@with_user(508)
async def test_callback_rejects_bad_state(api, valid_user_token, authz):
    response = api.get(
        "/api/v1/connectors/panopto/callback?code=x&state=not-a-jwt",
        follow_redirects=False,
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )
    assert response.status_code == 303
    assert "connector_error=bad_state" in response.headers["location"]


@with_user(509)
async def test_callback_rejects_service_mismatch(
    api, valid_user_token, user, authz
):
    state = connectors_pkg.encode_state(
        user_id=user.id,
        service="some-other",
        tenant=None,
        pkce_verifier=None,
    )
    response = api.get(
        f"/api/v1/connectors/panopto/callback?code=x&state={state}",
        follow_redirects=False,
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )
    assert response.status_code == 303
    assert "connector_error=service_mismatch" in response.headers["location"]


@with_user(510)
async def test_callback_propagates_provider_error(api, valid_user_token, authz):
    response = api.get(
        "/api/v1/connectors/panopto/callback?error=access_denied",
        follow_redirects=False,
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )
    assert response.status_code == 303
    assert "connector_error=access_denied" in response.headers["location"]


@with_user(511)
async def test_disconnect_removes_row_when_owner(
    api, db, valid_user_token, user, monkeypatch, authz
):
    _make_httpx_mock(monkeypatch)
    async with db.async_session() as session:
        row = UserConnector(
            user_id=user.id,
            service="panopto",
            tenant="demo",
            access_token="at",
            refresh_token="rt",
        )
        session.add(row)
        await session.commit()
        row_id = row.id

    response = api.delete(
        f"/api/v1/me/connectors/{row_id}",
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )
    assert response.status_code == 200
    assert response.json() == {"status": "disconnected"}

    async with db.async_session() as session:
        assert await UserConnector.get_by_id(session, row_id) is None


@with_user(512)
async def test_disconnect_returns_404_for_non_owner(
    api, db, valid_user_token, user, authz
):
    async with db.async_session() as session:
        from pingpong.models import User

        other = User(id=9999, email="other@example.com")
        session.add(other)
        await session.flush()
        row = UserConnector(
            user_id=other.id,
            service="panopto",
            tenant="demo",
            access_token="at",
            refresh_token="rt",
        )
        session.add(row)
        await session.commit()
        row_id = row.id

    response = api.delete(
        f"/api/v1/me/connectors/{row_id}",
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )
    assert response.status_code == 404

    async with db.async_session() as session:
        assert await UserConnector.get_by_id(session, row_id) is not None


@with_user(513)
async def test_disconnect_returns_404_for_missing_id(api, valid_user_token, authz):
    response = api.delete(
        "/api/v1/me/connectors/999999",
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )
    assert response.status_code == 404


@with_user(514)
async def test_list_connectors_unauthenticated_is_403(api):
    response = api.get("/api/v1/me/connectors")
    assert response.status_code == 403


@with_user(515)
async def test_callback_rejects_state_for_different_user(
    api, db, valid_user_token, user, authz
):
    """A state token minted for user A must not link tokens to logged-in user B."""
    # State claims sub=user.id+1 but the session is user.id.
    state = connectors_pkg.encode_state(
        user_id=user.id + 1,
        service="panopto",
        tenant="demo",
        pkce_verifier=None,
    )
    response = api.get(
        f"/api/v1/connectors/panopto/callback?code=auth-code&state={state}",
        follow_redirects=False,
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )
    assert response.status_code == 303
    assert "connector_error=user_mismatch" in response.headers["location"]

    async with db.async_session() as session:
        assert await UserConnector.get_for_user(session, user.id) == []


@with_user(516)
async def test_callback_rejects_when_no_session(api, db, user):
    state = connectors_pkg.encode_state(
        user_id=user.id,
        service="panopto",
        tenant="demo",
        pkce_verifier=None,
    )
    response = api.get(
        f"/api/v1/connectors/panopto/callback?code=auth-code&state={state}",
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert "connector_error=not_logged_in" in response.headers["location"]


@with_user(517)
async def test_callback_url_encodes_provider_error(api, valid_user_token, authz):
    from urllib.parse import parse_qs, urlparse

    response = api.get(
        "/api/v1/connectors/panopto/callback?error=access_denied%26injected%3D1",
        follow_redirects=False,
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )
    assert response.status_code == 303
    # The provider-supplied '&' must be URL-encoded so a crafted error
    # value like "access_denied&injected=1" can't smuggle an extra query
    # parameter into our /profile redirect.
    qs = parse_qs(urlparse(response.headers["location"]).query)
    assert list(qs.keys()) == ["connector_error"]
    assert qs["connector_error"] == ["access_denied&injected=1"]
