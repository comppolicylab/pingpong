"""Login-exchange configuration and HTTP errors for shared Redis connections."""

from contextlib import asynccontextmanager

from fastapi import HTTPException

from ..config import config
from ..redis.client import RedisPool, RedisUnavailable

_pool = RedisPool()


@asynccontextmanager
async def redis_client():
    settings = config.auth.login_exchange
    if settings is None:
        raise HTTPException(503, "Login exchange is not configured")
    try:
        async with _pool.client(settings) as client:
            yield client
    except RedisUnavailable as exc:
        raise HTTPException(503, "Login exchange unavailable") from exc


async def close_redis_clients():
    await _pool.close()
