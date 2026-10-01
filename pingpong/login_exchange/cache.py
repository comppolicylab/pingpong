"""Redis connection ownership for the optional login exchange."""

import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass
from time import monotonic
from weakref import WeakKeyDictionary

from botocore.exceptions import BotoCoreError, ClientError
from fastapi import HTTPException
from redis.asyncio import Redis, RedisCluster
from redis.asyncio.retry import Retry
from redis.backoff import NoBackoff

from ..config import config
from .elasticache import ElastiCacheIAMCredentials
from .settings import LoginExchangeSettings


async def create_redis_client():
    settings = config.auth.login_exchange
    if settings is None:
        raise HTTPException(503, "Login exchange is not configured")
    options = {
        "decode_responses": True,
        "socket_connect_timeout": 2,
        "socket_timeout": 2,
        "socket_keepalive": True,
        "health_check_interval": 30,
        "max_connections": settings.max_connections,
        # GETDEL cannot be replayed after an ambiguous response loss.
        "retry": Retry(NoBackoff(), 0),
    }
    try:
        redis_url = settings.redis_url.get_secret_value()
        if settings.cache_name is None:
            client = Redis.from_url(settings.redis_url.get_secret_value(), **options)
        else:
            assert settings.elasticache_user is not None
            assert settings.region is not None
            client_class = (
                RedisCluster if settings.cache_type == "serverless" else Redis
            )
            if settings.cache_type == "serverless":
                options.update(require_full_coverage=False)
            client = client_class.from_url(
                redis_url,
                ssl_cert_reqs="required",
                ssl_check_hostname=True,
                credential_provider=ElastiCacheIAMCredentials(
                    settings.cache_name,
                    settings.elasticache_user,
                    settings.region,
                    settings.cache_type == "serverless",
                ),
                **options,
            )
        return client
    except (BotoCoreError, ClientError, ValueError, KeyError, IndexError) as exc:
        raise HTTPException(503, "Login exchange unavailable") from exc


@dataclass
class _PoolEntry:
    client: Redis | RedisCluster
    settings: LoginExchangeSettings
    created: float
    users: int = 0
    retired: bool = False


class _LoopPool:
    def __init__(self):
        self.lock = asyncio.Lock()
        self.entry: _PoolEntry | None = None


_pools: WeakKeyDictionary[asyncio.AbstractEventLoop, _LoopPool] = WeakKeyDictionary()
# Rotate pools before the IAM connection limit.
POOL_MAX_AGE = 11 * 60 * 60


@asynccontextmanager
async def redis_client():
    loop = asyncio.get_running_loop()
    pool = _pools.setdefault(loop, _LoopPool())
    async with pool.lock:
        entry = pool.entry
        settings = config.auth.login_exchange
        if (
            entry is None
            or entry.settings != settings
            or monotonic() - entry.created >= POOL_MAX_AGE
        ):
            client = await create_redis_client()
            if entry is not None:
                entry.retired = True
                if not entry.users:
                    await entry.client.aclose()
            entry = _PoolEntry(client, settings.model_copy(deep=True), monotonic())
            pool.entry = entry
        entry.users += 1
    try:
        yield entry.client
    except (BotoCoreError, ClientError) as exc:
        raise HTTPException(503, "Login exchange unavailable") from exc
    finally:
        entry.users -= 1
        if entry.retired and not entry.users:
            await entry.client.aclose()


async def close_redis_clients():
    pool = _pools.pop(asyncio.get_running_loop(), None)
    if pool is not None and pool.entry is not None:
        pool.entry.retired = True
        if not pool.entry.users:
            await pool.entry.client.aclose()
