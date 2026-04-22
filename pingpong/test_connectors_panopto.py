from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from pingpong.connectors import ConnectorError, ConnectorNotConfigured, PanoptoConnector

pytestmark = pytest.mark.asyncio


DISCOVERY_PAYLOAD = {
    "authorization_endpoint": "https://demo.hosted.panopto.com/Panopto/oauth2/connect/authorize",
    "token_endpoint": "https://demo.hosted.panopto.com/Panopto/oauth2/connect/token",
    "revocation_endpoint": "https://demo.hosted.panopto.com/Panopto/oauth2/connect/revocation",
}


def _patch_client(monkeypatch, responses: list[httpx.Response]):
    """Return a mock httpx.AsyncClient whose .get returns each response in turn."""
    calls: list[str] = []
    iterator = iter(responses)

    async def get(url):
        calls.append(url)
        return next(iterator)

    client = MagicMock()
    client.get = AsyncMock(side_effect=get)
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=None)
    ctor = MagicMock(return_value=client)
    monkeypatch.setattr(
        "pingpong.connectors.panopto.httpx.AsyncClient", ctor, raising=True
    )
    return calls


async def test_discovery_resolves_endpoints(monkeypatch):
    calls = _patch_client(
        monkeypatch,
        [httpx.Response(200, json=DISCOVERY_PAYLOAD)],
    )
    connector = PanoptoConnector()
    authorize = await connector.authorize_endpoint("demo")
    assert authorize == DISCOVERY_PAYLOAD["authorization_endpoint"]
    assert calls == [
        "https://demo.hosted.panopto.com/Panopto/oauth2/.well-known/openid-configuration"
    ]


async def test_discovery_is_cached_per_host(monkeypatch):
    calls = _patch_client(
        monkeypatch,
        [httpx.Response(200, json=DISCOVERY_PAYLOAD)],
    )
    connector = PanoptoConnector()
    a = await connector.authorize_endpoint("demo")
    b = await connector.token_endpoint("demo")
    c = await connector.revoke_endpoint("demo")
    assert a == DISCOVERY_PAYLOAD["authorization_endpoint"]
    assert b == DISCOVERY_PAYLOAD["token_endpoint"]
    assert c == DISCOVERY_PAYLOAD["revocation_endpoint"]
    # All three endpoint lookups should share one discovery HTTP call.
    assert len(calls) == 1


async def test_discovery_raises_for_unknown_tenant():
    connector = PanoptoConnector()
    with pytest.raises(ConnectorNotConfigured):
        await connector.authorize_endpoint("does-not-exist")


async def test_missing_required_endpoint_raises(monkeypatch):
    _patch_client(
        monkeypatch,
        [
            httpx.Response(
                200,
                json={
                    "token_endpoint": DISCOVERY_PAYLOAD["token_endpoint"],
                    # no authorization_endpoint
                },
            )
        ],
    )
    connector = PanoptoConnector()
    with pytest.raises(ConnectorError):
        await connector.authorize_endpoint("demo")


async def test_revoke_endpoint_returns_none_when_absent(monkeypatch):
    _patch_client(
        monkeypatch,
        [
            httpx.Response(
                200,
                json={
                    "authorization_endpoint": DISCOVERY_PAYLOAD[
                        "authorization_endpoint"
                    ],
                    "token_endpoint": DISCOVERY_PAYLOAD["token_endpoint"],
                },
            )
        ],
    )
    connector = PanoptoConnector()
    assert await connector.revoke_endpoint("demo") is None


async def test_discovery_error_status_raises(monkeypatch):
    _patch_client(monkeypatch, [httpx.Response(500, text="boom")])
    connector = PanoptoConnector()
    with pytest.raises(ConnectorError):
        await connector.authorize_endpoint("demo")


async def test_tenant_friendly_name_from_config():
    connector = PanoptoConnector()
    # ``demo`` is configured in test_config.toml.
    assert connector.tenant_friendly_name("demo") == "Demo Panopto"
    assert connector.tenant_friendly_name("unknown") is None
