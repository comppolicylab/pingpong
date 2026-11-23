import hashlib
import secrets
from contextlib import asynccontextmanager

from fastapi import HTTPException
from pydantic import BaseModel
from redis.exceptions import RedisError

from ..redis.client import RedisPool
from .settings import OpenAccessSettings

LAUNCH_RETRY_TTL_SECONDS = 10 * 60
ACTIVE_SESSION_TTL_SECONDS = 24 * 60 * 60

_pool = RedisPool()


class LaunchCode(BaseModel):
    principal_id: int
    thread_id: int
    class_id: int
    session_id: str


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _key(settings: OpenAccessSettings, *parts: str | int) -> str:
    return ":".join(("pingpong", "oa", settings.client_id, *map(str, parts)))


@asynccontextmanager
async def redis_client(settings: OpenAccessSettings):
    try:
        async with _pool.client(settings) as client:
            yield client
    except RedisError as exc:
        raise HTTPException(503, "Open Access is temporarily unavailable") from exc


async def close_redis_clients():
    await _pool.close()


async def start_session(
    settings: OpenAccessSettings, principal_id: int, launch_id: str
) -> str:
    launch_key = _key(settings, "launch", principal_id, _digest(launch_id))
    session_id = secrets.token_urlsafe(24)
    async with redis_client(settings) as redis:
        if await redis.set(
            launch_key, session_id, nx=True, ex=LAUNCH_RETRY_TTL_SECONDS
        ):
            await redis.set(
                _key(settings, "active", principal_id),
                session_id,
                ex=ACTIVE_SESSION_TTL_SECONDS,
            )
            return session_id
        existing = await redis.get(launch_key)
    if existing is None:
        raise HTTPException(503, "Open Access is temporarily unavailable")
    return existing


async def is_active_session(
    settings: OpenAccessSettings, principal_id: int, session_id: str
) -> bool:
    async with redis_client(settings) as redis:
        active = await redis.get(_key(settings, "active", principal_id))
    return active is not None and secrets.compare_digest(active, session_id)


async def extend_session(
    settings: OpenAccessSettings, principal_id: int, session_id: str
) -> bool:
    key = _key(settings, "active", principal_id)
    async with redis_client(settings) as redis:
        active = await redis.get(key)
        if active is None or not secrets.compare_digest(active, session_id):
            return False
        await redis.expire(key, ACTIVE_SESSION_TTL_SECONDS)
    return True


async def issue_code(settings: OpenAccessSettings, launch: LaunchCode) -> str:
    code = secrets.token_urlsafe(32)
    async with redis_client(settings) as redis:
        stored = await redis.set(
            _key(settings, "code", _digest(code)),
            launch.model_dump_json(),
            ex=settings.launch_code_ttl_seconds,
            nx=True,
        )
    if not stored:
        raise HTTPException(503, "Open Access is temporarily unavailable")
    return code


async def consume_code(settings: OpenAccessSettings, code: str) -> LaunchCode | None:
    async with redis_client(settings) as redis:
        raw = await redis.getdel(_key(settings, "code", _digest(code)))
    return LaunchCode.model_validate_json(raw) if raw else None
