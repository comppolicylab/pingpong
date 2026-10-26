from contextlib import asynccontextmanager
from unittest.mock import AsyncMock

from fastapi import HTTPException
import pytest

from ..redis.client import RedisUnavailable
from . import cache
from .settings import LoginExchangeSettings


async def test_disabled_exchange_does_not_open_redis(config, monkeypatch):
    monkeypatch.setattr(config.auth, "login_exchange", None)
    pool = AsyncMock()
    monkeypatch.setattr(cache, "_pool", pool)
    with pytest.raises(HTTPException) as raised:
        async with cache.redis_client():
            pytest.fail("Disabled login exchange must not open a connection")
    assert raised.value.status_code == 503
    assert raised.value.detail == "Login exchange is not configured"
    pool.client.assert_not_called()


@pytest.mark.parametrize("aws_failure", [False, True])
async def test_exchange_passes_settings_and_translates_connection_errors(
    config, monkeypatch, aws_failure
):
    settings = LoginExchangeSettings(
        redis_url="redis://localhost:6379/0",
        target_origin="https://target.example",
        source_origins=[],
    )
    monkeypatch.setattr(config.auth, "login_exchange", settings)
    client = object()

    @asynccontextmanager
    async def connect(received_settings):
        assert received_settings is settings
        if aws_failure:
            raise RedisUnavailable("Synthetic AWS credential failure")
        yield client

    monkeypatch.setattr(cache._pool, "client", connect)
    if aws_failure:
        with pytest.raises(HTTPException) as raised:
            async with cache.redis_client() as received_client:
                assert received_client is client
        assert raised.value.status_code == 503
        assert raised.value.detail == "Login exchange unavailable"
    else:
        async with cache.redis_client() as received_client:
            assert received_client is client
