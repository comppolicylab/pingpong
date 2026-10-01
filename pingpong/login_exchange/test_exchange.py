import asyncio
import importlib
import os
import re
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI, HTTPException, Request
from redis.asyncio import Redis
from redis.exceptions import ConnectionError

from . import cache, exchange, integration
from .settings import LoginExchangeSettings

NEW = "http://pingpong.test:5173"
OLD = "http://hks.pingpong.test:5173"


@pytest.fixture
def exchange_config(config, monkeypatch):
    monkeypatch.setattr(config, "public_url", OLD)
    monkeypatch.setattr(
        config.auth,
        "login_exchange",
        LoginExchangeSettings(
            redis_url="redis://localhost:6379/0",
            target_origin=NEW,
            source_origins=[OLD],
        ),
    )
    return config


@pytest.fixture
async def real_redis(exchange_config):
    url = os.environ.get("LOGIN_EXCHANGE_TEST_REDIS_URL")
    if not url:
        pytest.skip(
            "Set LOGIN_EXCHANGE_TEST_REDIS_URL to a disposable Redis 6.2+ instance"
        )
    exchange_config.auth.login_exchange = LoginExchangeSettings(
        redis_url=url,
        target_origin=NEW,
        source_origins=[OLD],
    )
    async with Redis.from_url(url, decode_responses=True) as client:
        await client.ping()
        try:
            yield client
        finally:
            await cache.close_redis_clients()
    # No FLUSHDB: tests only create random, expiring keys.


def post_request(host=NEW, code="", origin=OLD):
    body = f"code={code}".encode()

    async def receive():
        return {"type": "http.request", "body": body}

    return Request(
        {
            "type": "http",
            "method": "POST",
            "scheme": "http",
            "path": exchange.EXCHANGE_PATH,
            "query_string": b"",
            "headers": [
                (b"host", host.removeprefix("http://").encode()),
                (b"origin", origin.encode()),
                (b"content-type", b"application/x-www-form-urlencoded"),
            ],
        },
        receive,
    )


@pytest.mark.parametrize(
    "destination",
    [
        "//evil.test",
        "https://evil.test/",
        "/\\evil.test",
        "/%2fevil.test",
        "/x%0d%0aevil",
        "javascript:alert(1)",
    ],
)
def test_reject_unsafe_destinations(exchange_config, destination):
    with pytest.raises(HTTPException):
        exchange.relative_destination(destination)


def test_legacy_destination_becomes_relative(exchange_config):
    assert (
        exchange.relative_destination(OLD + "/group/1?x=2#part") == "/group/1?x=2#part"
    )


def test_exchange_target_does_not_replace_public_origin(exchange_config):
    assert exchange.public_origin() == OLD
    assert exchange.exchange_target_origin() == NEW


def test_relay_state_uses_the_host_that_started_login(exchange_config):
    assert exchange.relay_state(post_request(OLD), "/group/1?x=2") == (
        OLD + "/group/1?x=2"
    )
    assert exchange.relay_state(post_request(NEW), "/group/1?x=2") == (
        NEW + "/group/1?x=2"
    )
    # A redirect parameter cannot override the host on which login was initiated.
    assert exchange.relay_state(post_request(OLD), NEW + "/group/1") == (
        OLD + "/group/1"
    )


@pytest.mark.asyncio
async def test_target_host_callback_needs_no_redis(exchange_config):
    response = await exchange.finish_saml_login(post_request(), 1, "/group/1")
    assert response.status_code == 303
    assert response.headers["location"] == NEW + "/group/1"
    assert "session=" in response.headers["set-cookie"]
    assert "domain=" not in response.headers["set-cookie"].lower()
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.asyncio
async def test_untrusted_source_rejected(exchange_config):
    with pytest.raises(HTTPException) as exc:
        await exchange.finish_saml_login(post_request("http://evil.test"), 1, "/")
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_redis_unavailable_fails_closed(exchange_config, monkeypatch):
    client = AsyncMock()
    client.__aenter__.return_value = client
    client.set.side_effect = ConnectionError("offline")
    client.getdel.side_effect = ConnectionError("offline")
    monkeypatch.setattr(exchange, "redis_client", lambda: client)
    with pytest.raises(HTTPException) as exc:
        await exchange.finish_saml_login(post_request(OLD), 1, NEW + "/")
    assert exc.value.status_code == 503
    with pytest.raises(HTTPException) as exc:
        await exchange.consume_grant(post_request(code="a" * 43))
    assert exc.value.status_code == 503


@pytest.mark.asyncio
async def test_real_redis_atomic_redemption_and_expiry(real_redis):
    code = await exchange.issue_grant(1, "/group/1")
    assert 0 < await real_redis.ttl(exchange.exchange_key(code)) <= 60
    results = await asyncio.gather(
        exchange.consume_grant(post_request(code=code)),
        exchange.consume_grant(post_request(code=code)),
        return_exceptions=True,
    )
    assert sum(isinstance(r, exchange.LoginGrant) for r in results) == 1
    assert (
        sum(isinstance(r, HTTPException) and r.status_code == 400 for r in results) == 1
    )
    code = await exchange.issue_grant(1, "/")
    await real_redis.pexpire(exchange.exchange_key(code), 1)
    await asyncio.sleep(0.02)
    with pytest.raises(HTTPException):
        await exchange.consume_grant(post_request(code=code))
    with pytest.raises(HTTPException):
        await exchange.consume_grant(post_request(code="a" * 43))


@pytest.mark.asyncio
async def test_wrong_host_and_origin_do_not_consume_code(real_redis):
    code = await exchange.issue_grant(1, "/")
    for request in (
        post_request(OLD, code),
        post_request(code=code, origin="https://evil.test"),
        post_request(code=code, origin="null"),
    ):
        with pytest.raises(HTTPException):
            await exchange.consume_grant(request)
    assert (await exchange.consume_grant(post_request(code=code))).user_id == 1


@pytest.mark.asyncio
async def test_wrong_audience_rejected(real_redis):
    code = await exchange.issue_grant(1, "/")
    await real_redis.set(
        exchange.exchange_key(code),
        exchange.LoginGrant(user_id=1, audience=OLD, destination="/").model_dump_json(),
        ex=60,
    )
    with pytest.raises(HTTPException) as exc:
        await exchange.consume_grant(post_request(code=code))
    assert exc.value.status_code == 400


@pytest.fixture
def saml_app(exchange_config, monkeypatch, now):
    server = importlib.import_module("pingpong.server")

    user = SimpleNamespace(id=42)
    login_calls = []
    saml = SimpleNamespace(
        process_response=lambda: None,
        get_errors=list,
        is_authenticated=lambda: True,
        login=lambda relay_state: login_calls.append(relay_state)
        or "https://idp.test/login",
        login_calls=login_calls,
        _request_data={
            "get_data": {},
            "post_data": {"RelayState": NEW + "/group/1?x=2"},
        },
    )
    monkeypatch.setattr(
        server,
        "get_saml2_settings",
        lambda provider: SimpleNamespace(protocol="saml"),
    )
    monkeypatch.setattr(server, "get_saml2_client", AsyncMock(return_value=saml))
    monkeypatch.setattr(
        server,
        "get_saml2_attrs",
        lambda *args: SimpleNamespace(
            email="test@example.com",
            first_name="Test",
            last_name="User",
            name="Test User",
            identifier="",
        ),
    )
    monkeypatch.setattr(
        server.models.User, "get_by_email_sso", AsyncMock(return_value=user)
    )
    monkeypatch.setattr(server.models.User, "get_by_id", AsyncMock(return_value=user))
    db = SimpleNamespace(add=lambda user: None, flush=AsyncMock(), refresh=AsyncMock())
    app = FastAPI()
    app.state["now"] = now

    @app.middleware("http")
    async def inject_db(request, call_next):
        request.state["db"] = db
        return await call_next(request)

    app.add_api_route(
        "/api/v1/login/sso/saml/acs", server.login_sso_saml_acs, methods=["POST"]
    )
    app.add_api_route("/api/v1/login/sso", server.login_sso, methods=["GET"])
    app.add_api_route(
        exchange.EXCHANGE_PATH, server.login_sso_exchange, methods=["POST"]
    )
    return app, saml


@pytest.mark.asyncio
async def test_login_relay_state_tracks_the_initiating_host(saml_app):
    app, saml = saml_app
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app)) as client:
        for origin in (OLD, NEW):
            response = await client.get(
                origin
                + "/api/v1/login/sso?provider=harvardkey&redirect=/group/1%3Fx%3D2"
            )
            assert response.status_code == 307
            assert response.headers["location"] == "https://idp.test/login"
            assert saml.login_calls[-1] == origin + "/group/1?x=2"

        response = await client.get(
            "http://evil.test/api/v1/login/sso?provider=harvardkey"
        )
        assert response.status_code == 400


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", ["harvardkey", "other-saml"])
async def test_saml_callback_and_exchange_on_two_hosts(real_redis, saml_app, provider):
    app, saml = saml_app
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app)) as client:
        response = await client.post(
            OLD + f"/api/v1/login/sso/saml/acs?provider={provider}"
        )
        assert response.status_code == 200
        assert "set-cookie" not in response.headers
        assert response.headers["cache-control"] == "no-store"
        assert response.headers["referrer-policy"] == "strict-origin"
        assert "default-src 'none'" in response.headers["content-security-policy"]
        assert f'action="{NEW}{exchange.EXCHANGE_PATH}"' in response.text
        code = re.search(r'name="code" value="([^"]+)"', response.text)[1]
        assert code not in str(response.url)
        response = await client.post(
            NEW + exchange.EXCHANGE_PATH, data={"code": code}, headers={"Origin": OLD}
        )
        assert response.status_code == 303
        assert response.headers["location"] == NEW + "/group/1?x=2"
        assert any(
            c.name == "session" and c.domain == "pingpong.test"
            for c in client.cookies.jar
        )
        assert not any(c.domain == "hks.pingpong.test" for c in client.cookies.jar)
        assert (
            await client.post(NEW + exchange.EXCHANGE_PATH, data={"code": code})
        ).status_code == 400

        saml.get_errors = lambda: ["invalid_signature"]
        response = await client.post(
            OLD + f"/api/v1/login/sso/saml/acs?provider={provider}"
        )
        assert response.status_code == 400
        assert "set-cookie" not in response.headers


@pytest.mark.asyncio
@pytest.mark.parametrize("provider", ["harvardkey", "other-saml"])
async def test_disabled_exchange_preserves_saml_redirect(
    saml_app, exchange_config, monkeypatch, provider
):
    app, saml = saml_app
    monkeypatch.setattr(exchange_config.auth, "login_exchange", None)
    saml._request_data["post_data"]["RelayState"] = OLD + "/group/1?x=2"
    saml.redirect_to = lambda destination: destination
    redis_factory = AsyncMock(
        side_effect=AssertionError("Disabled exchange opened Redis")
    )
    monkeypatch.setattr(cache, "create_redis_client", redis_factory)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app)) as client:
        response = await client.post(
            OLD + f"/api/v1/login/sso/saml/acs?provider={provider}"
        )
        assert response.status_code == 303
        assert response.headers["location"] == OLD + "/group/1?x=2"
        assert any(c.domain == "hks.pingpong.test" for c in client.cookies.jar)
        response = await client.post(
            NEW + exchange.EXCHANGE_PATH, data={"code": "a" * 43}
        )
        assert response.status_code == 404
        assert "set-cookie" not in response.headers
    redis_factory.assert_not_awaited()


@pytest.mark.asyncio
async def test_enabled_same_host_callback_skips_redis(saml_app, monkeypatch):
    app, _ = saml_app
    redis_factory = AsyncMock(
        side_effect=AssertionError("Same-host login opened Redis")
    )
    monkeypatch.setattr(cache, "create_redis_client", redis_factory)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app)) as client:
        response = await client.post(
            NEW + "/api/v1/login/sso/saml/acs?provider=harvardkey"
        )
    assert response.status_code == 303
    assert response.headers["location"] == NEW + "/group/1?x=2"
    assert "domain=" not in response.headers["set-cookie"].lower()
    redis_factory.assert_not_awaited()


@pytest.mark.asyncio
async def test_hks_login_preserves_existing_host_without_redis(saml_app, monkeypatch):
    app, saml = saml_app
    saml._request_data["post_data"]["RelayState"] = OLD + "/group/1?x=2"
    redis_factory = AsyncMock(side_effect=AssertionError("HKS login opened Redis"))
    monkeypatch.setattr(cache, "create_redis_client", redis_factory)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app)) as client:
        response = await client.post(
            OLD + "/api/v1/login/sso/saml/acs?provider=harvardkey"
        )
    assert response.status_code == 303
    assert response.headers["location"] == OLD + "/group/1?x=2"
    assert "domain=" not in response.headers["set-cookie"].lower()
    redis_factory.assert_not_awaited()


@pytest.mark.asyncio
async def test_exchange_rejects_deleted_user(real_redis, saml_app, monkeypatch):
    app, _ = saml_app
    monkeypatch.setattr(
        importlib.import_module("pingpong.server").models.User,
        "get_by_id",
        AsyncMock(return_value=None),
    )
    code = await exchange.issue_grant(42, "/")
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app)) as client:
        response = await client.post(NEW + exchange.EXCHANGE_PATH, data={"code": code})
        assert response.status_code == 400
        assert "set-cookie" not in response.headers
        response = await client.post(NEW + exchange.EXCHANGE_PATH, data={"code": code})
        assert response.status_code == 400


@pytest.mark.asyncio
async def test_lifespan_closes_pools_on_error(monkeypatch):
    close = AsyncMock()
    monkeypatch.setattr(integration, "close_redis_clients", close)

    async def fail_during_lifespan():
        raise RuntimeError("shutdown")

    with pytest.raises(RuntimeError, match="shutdown"):
        async with integration.lifespan():
            await fail_during_lifespan()
    close.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("callback_origin", [OLD, NEW])
async def test_source_alias_login_reaches_target(
    real_redis, saml_app, exchange_config, callback_origin
):
    alias = "http://alias.pingpong.test:5173"
    exchange_config.auth.login_exchange.source_origins.append(alias)
    app, saml = saml_app
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app)) as client:
        response = await client.get(
            alias + "/api/v1/login/sso?provider=harvardkey&redirect=/group/1%3Fx%3D2"
        )
        assert response.status_code == 307
        saml._request_data["post_data"]["RelayState"] = saml.login_calls[-1]
        response = await client.post(
            callback_origin + "/api/v1/login/sso/saml/acs?provider=harvardkey"
        )
        assert response.status_code == 200
        assert response.headers["referrer-policy"] == "strict-origin"
        code = re.search(r'name="code" value="([^"]+)"', response.text)[1]
        response = await client.post(
            NEW + exchange.EXCHANGE_PATH,
            data={"code": code},
            headers={"Origin": callback_origin},
        )
        assert response.status_code == 303
        assert response.headers["location"] == NEW + "/group/1?x=2"
        assert any(
            c.name == "session" and c.domain == "pingpong.test"
            for c in client.cookies.jar
        )
