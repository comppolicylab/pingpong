from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from pingpong.connectors.core.exceptions import ConnectorError
from pingpong.connectors.panopto import DISCOVERY_PATH, PanoptoConnector
from pingpong.models import ConnectorConfig

pytestmark = pytest.mark.asyncio


DISCOVERY_PAYLOAD = {
    "authorization_endpoint": "https://demo.hosted.panopto.com/Panopto/oauth2/connect/authorize",
    "token_endpoint": "https://demo.hosted.panopto.com/Panopto/oauth2/connect/token",
    "userinfo_endpoint": "https://demo.hosted.panopto.com/Panopto/oauth2/connect/userinfo",
    "revocation_endpoint": "https://demo.hosted.panopto.com/Panopto/oauth2/connect/revocation",
    "issuer": "https://demo.hosted.panopto.com/Panopto/oauth2",
    "jwks_uri": "https://demo.hosted.panopto.com/Panopto/oauth2/.well-known/jwks",
}


def _config(host: str = "demo.hosted.panopto.com") -> ConnectorConfig:
    return ConnectorConfig(
        id=1,
        service="panopto",
        account_scope="demo",
        display_name="Demo Panopto",
        host=host,
        client_id="client-id",
        client_secret="client-secret",
        enabled=True,
    )


def _patch_client(monkeypatch, responses: list[httpx.Response]):
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
        "pingpong.connectors.core.discovery.httpx.AsyncClient",
        ctor,
        raising=True,
    )
    return calls


async def test_discovery_fetches_demo_host_endpoints(monkeypatch):
    calls = _patch_client(monkeypatch, [httpx.Response(200, json=DISCOVERY_PAYLOAD)])
    connector = PanoptoConnector()

    assert (
        await connector.authorize_endpoint(_config())
        == DISCOVERY_PAYLOAD["authorization_endpoint"]
    )
    assert calls == [f"https://demo.hosted.panopto.com{DISCOVERY_PATH}"]


async def test_discovery_is_cached_per_host(monkeypatch):
    calls = _patch_client(monkeypatch, [httpx.Response(200, json=DISCOVERY_PAYLOAD)])
    connector = PanoptoConnector()
    config = _config()

    assert (
        await connector.authorize_endpoint(config)
        == DISCOVERY_PAYLOAD["authorization_endpoint"]
    )
    assert await connector.token_endpoint(config) == DISCOVERY_PAYLOAD["token_endpoint"]
    assert (
        await connector.userinfo_endpoint(config)
        == DISCOVERY_PAYLOAD["userinfo_endpoint"]
    )
    assert await connector.issuer(config) == DISCOVERY_PAYLOAD["issuer"]
    assert await connector.jwks_endpoint(config) == DISCOVERY_PAYLOAD["jwks_uri"]
    assert (
        await connector.revoke_endpoint(config)
        == DISCOVERY_PAYLOAD["revocation_endpoint"]
    )
    assert len(calls) == 1


async def test_missing_required_discovery_field_raises(monkeypatch):
    _patch_client(
        monkeypatch,
        [
            httpx.Response(
                200, json={"token_endpoint": DISCOVERY_PAYLOAD["token_endpoint"]}
            )
        ],
    )
    connector = PanoptoConnector()
    with pytest.raises(ConnectorError, match="authorization_endpoint"):
        await connector.authorize_endpoint(_config())


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
    assert await connector.revoke_endpoint(_config()) is None


async def test_discovery_error_status_raises(monkeypatch):
    _patch_client(monkeypatch, [httpx.Response(500, text="boom")])
    connector = PanoptoConnector()
    with pytest.raises(ConnectorError, match="500"):
        await connector.authorize_endpoint(_config())
