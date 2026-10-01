import asyncio
import ssl
from unittest.mock import AsyncMock, MagicMock
from urllib.parse import parse_qs, urlsplit

import pytest
from botocore.credentials import Credentials
from botocore.exceptions import NoCredentialsError
from pydantic import ValidationError

from . import cache, elasticache
from .settings import LoginExchangeSettings


@pytest.mark.parametrize("serverless", [True, False])
def test_iam_signing_uses_cache_identity_and_fresh_credentials(monkeypatch, serverless):
    credentials = [
        Credentials("first", "secret", "session-one"),
        Credentials("second", "secret", "session-two"),
    ]
    session = MagicMock()
    session.get_credentials.side_effect = credentials
    monkeypatch.setattr(elasticache.boto3, "Session", lambda: session)
    provider = elasticache.ElastiCacheIAMCredentials(
        "MY-CACHE", "my-user", "us-east-1", serverless
    )
    for access_key, session_token in [
        ("first", "session-one"),
        ("second", "session-two"),
    ]:
        user, token = provider.get_credentials()
        parsed = urlsplit("http://" + token)
        query = parse_qs(parsed.query)
        assert user == "my-user"
        assert parsed.hostname == "my-cache"
        assert query["Action"] == ["connect"]
        assert query["User"] == ["my-user"]
        assert query["X-Amz-Expires"] == ["900"]
        assert query["X-Amz-Security-Token"] == [session_token]
        assert query["X-Amz-Credential"][0].startswith(access_key + "/")
        assert "/us-east-1/elasticache/aws4_request" in query["X-Amz-Credential"][0]
        assert bool(query.get("ResourceType")) == serverless
        assert "X-Amz-Signature" in query


@pytest.mark.parametrize(
    "kwargs",
    [
        {},
        {"cache_name": "test"},
        {
            "redis_url": "rediss://endpoint.example:6379",
            "cache_name": "test",
            "elasticache_user": "user",
        },
        {
            "redis_url": "redis://endpoint.example:6379",
            "cache_name": "test",
            "elasticache_user": "user",
            "region": "us-east-1",
        },
    ],
)
def test_connection_modes_are_unambiguous(kwargs):
    with pytest.raises(ValidationError):
        LoginExchangeSettings(
            target_origin="https://target.example", source_origins=[], **kwargs
        )


@pytest.mark.parametrize(
    "suffix",
    [
        "?max_connections=10000",
        "?socket_timeout=0",
        "?retry_on_timeout=true",
        "?ssl_cert_reqs=none",
        "?ssl_check_hostname=false",
        "?%73sl_check_hostname=false",
        "#ignored",
    ],
)
def test_redis_url_cannot_override_connection_safety(suffix):
    with pytest.raises(ValidationError):
        LoginExchangeSettings(
            redis_url="rediss://cache.example/0" + suffix,
            target_origin="https://target.example",
            source_origins=[],
        )


@pytest.mark.asyncio
async def test_redis_url_preserves_effective_pool_and_tls_settings(config, monkeypatch):
    monkeypatch.setattr(
        config.auth,
        "login_exchange",
        LoginExchangeSettings(
            redis_url="rediss://cache.example/2",
            target_origin="https://target.example",
            source_origins=[],
        ),
    )
    client = await cache.create_redis_client()
    try:
        pool = client.connection_pool
        assert pool.max_connections == 10
        connection = pool.make_connection()
        assert connection.db == 2
        assert connection.retry.get_retries() == 0
        assert connection.socket_timeout == 2
        assert connection.socket_connect_timeout == 2
        tls = connection.ssl_context.get()
        assert tls.check_hostname is True
        assert tls.verify_mode == ssl.CERT_REQUIRED
    finally:
        await client.aclose()


@pytest.mark.asyncio
async def test_aws_client_uses_configured_endpoint_and_requires_tls(
    config, monkeypatch
):
    settings = LoginExchangeSettings(
        redis_url="rediss://endpoint.example:6379",
        cache_name="test",
        elasticache_user="user",
        region="us-east-1",
        target_origin="https://target.example",
        source_origins=[],
    )
    monkeypatch.setattr(config.auth, "login_exchange", settings)
    async with cache.redis_client() as client:
        assert isinstance(client, cache.RedisCluster)
        options = client.connection_kwargs
        startup_nodes = list(client.nodes_manager.startup_nodes.values())
        assert [(node.host, node.port) for node in startup_nodes] == [
            ("endpoint.example", 6379)
        ]
        assert options["ssl_cert_reqs"] == "required"
        assert options["ssl_check_hostname"] is True
        assert isinstance(
            options["credential_provider"], elasticache.ElastiCacheIAMCredentials
        )
        assert options["max_connections"] == 10
        assert client.retry.get_retries() == 0
    await cache.close_redis_clients()


def test_iam_provider_fails_without_aws_credentials(monkeypatch):
    session = MagicMock()
    session.get_credentials.return_value = None
    monkeypatch.setattr(elasticache.boto3, "Session", lambda: session)
    provider = elasticache.ElastiCacheIAMCredentials("test", "user", "us-east-1", True)
    with pytest.raises(NoCredentialsError):
        provider.get_credentials()


@pytest.mark.asyncio
async def test_pool_reuse_rotation_and_shutdown(config, monkeypatch):
    settings = LoginExchangeSettings(
        redis_url="rediss://endpoint.example:6379",
        cache_name="TEST",
        elasticache_user="user",
        region="us-east-1",
        target_origin="https://target.example",
        source_origins=[],
    )
    assert settings.cache_name == "test"
    monkeypatch.setattr(config.auth, "login_exchange", settings)
    clients = [AsyncMock(), AsyncMock()]
    factory = AsyncMock(side_effect=clients)
    monkeypatch.setattr(cache, "create_redis_client", factory)
    clock = [0]
    monkeypatch.setattr(cache, "monotonic", lambda: clock[0])
    async with cache.redis_client() as first:
        async with cache.redis_client() as same:
            assert same is first
        factory.assert_awaited_once()
        clock[0] = cache.POOL_MAX_AGE
        async with cache.redis_client() as replacement:
            assert replacement is clients[1]
            first.aclose.assert_not_awaited()
        replacement.aclose.assert_not_awaited()
    first.aclose.assert_awaited_once()
    await cache.close_redis_clients()
    replacement.aclose.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("error_type", [RuntimeError, asyncio.CancelledError])
async def test_rotation_close_failure_cleans_replacement(
    config, monkeypatch, error_type
):
    settings = LoginExchangeSettings(
        redis_url="redis://localhost:6379/0",
        target_origin="https://target.example",
        source_origins=[],
    )
    monkeypatch.setattr(config.auth, "login_exchange", settings)
    clients = [AsyncMock(), AsyncMock(), AsyncMock()]
    monkeypatch.setattr(cache, "create_redis_client", AsyncMock(side_effect=clients))
    clock = [0]
    monkeypatch.setattr(cache, "monotonic", lambda: clock[0])
    async with cache.redis_client():
        pass
    clients[0].aclose.side_effect = error_type("close failed")
    clock[0] = cache.POOL_MAX_AGE
    try:
        with pytest.raises(error_type, match="close failed"):
            async with cache.redis_client():
                pytest.fail("Rotation failure should prevent checkout")
        clients[1].aclose.assert_awaited_once()
        async with cache.redis_client() as recovered:
            assert recovered is clients[2]
        clients[0].aclose.assert_awaited_once()
    finally:
        await cache.close_redis_clients()
    clients[2].aclose.assert_awaited_once()
