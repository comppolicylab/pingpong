"""Lazy Redis connections with per-event-loop ownership and safe pool rotation."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from time import monotonic
from weakref import WeakKeyDictionary

from botocore.exceptions import BotoCoreError, ClientError
from redis.asyncio import Redis, RedisCluster
from redis.asyncio.retry import Retry
from redis.backoff import NoBackoff
from redis.exceptions import RedisError

from .elasticache import ElastiCacheIAMCredentials
from .settings import RedisSettings


class RedisUnavailable(RedisError):
    """Connection configuration or AWS authentication could not be resolved."""


async def create_redis_client(settings: RedisSettings) -> Redis | RedisCluster:
    options = {
        "decode_responses": True,
        "socket_connect_timeout": 2,
        "socket_timeout": 2,
        "socket_keepalive": True,
        "health_check_interval": 30,
        "max_connections": settings.max_connections,
        # Callers may perform operations that cannot be safely replayed.
        "retry": Retry(NoBackoff(), 0),
    }
    try:
        redis_url = settings.redis_url.get_secret_value()
        if settings.cache_name is None:
            return Redis.from_url(redis_url, **options)
        assert settings.elasticache_user is not None
        assert settings.region is not None
        client_class = RedisCluster if settings.cache_type == "serverless" else Redis
        if settings.cache_type == "serverless":
            options.update(require_full_coverage=False)
        return client_class.from_url(
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
    except (BotoCoreError, ClientError, ValueError, KeyError, IndexError) as exc:
        raise RedisUnavailable("Redis connection unavailable") from exc


@dataclass
class _PoolEntry:
    client: Redis | RedisCluster
    settings: RedisSettings
    created: float
    users: int = 0
    retired: bool = False


class _LoopPool:
    def __init__(self):
        self.lock = asyncio.Lock()
        self.entry: _PoolEntry | None = None


# Rotate pools before the IAM connection limit.
POOL_MAX_AGE = 11 * 60 * 60


class RedisPool:
    """Own a feature's lazy connections without sharing mutable pool state."""

    def __init__(self):
        self._pools: WeakKeyDictionary[asyncio.AbstractEventLoop, _LoopPool] = (
            WeakKeyDictionary()
        )

    @asynccontextmanager
    async def client(
        self, settings: RedisSettings
    ) -> AsyncIterator[Redis | RedisCluster]:
        loop = asyncio.get_running_loop()
        pool = self._pools.setdefault(loop, _LoopPool())
        async with pool.lock:
            entry = pool.entry
            if (
                entry is None
                or entry.settings != settings
                or monotonic() - entry.created >= POOL_MAX_AGE
            ):
                client = await create_redis_client(settings)
                if entry is not None:
                    entry.retired = True
                    if not entry.users:
                        try:
                            await entry.client.aclose()
                        except BaseException:
                            pool.entry = None
                            await client.aclose()
                            raise
                entry = _PoolEntry(client, settings.model_copy(deep=True), monotonic())
                pool.entry = entry
            entry.users += 1
        try:
            yield entry.client
        except (BotoCoreError, ClientError) as exc:
            raise RedisUnavailable("Redis authentication unavailable") from exc
        finally:
            entry.users -= 1
            if entry.retired and not entry.users:
                await entry.client.aclose()

    async def close(self) -> None:
        pool = self._pools.pop(asyncio.get_running_loop(), None)
        if pool is not None and pool.entry is not None:
            pool.entry.retired = True
            if not pool.entry.users:
                await pool.entry.client.aclose()
