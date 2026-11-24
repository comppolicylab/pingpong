import hashlib
import logging
import secrets
from contextlib import asynccontextmanager

from pydantic import BaseModel
from redis.exceptions import RedisError

from ..redis.client import RedisPool
from .errors import unavailable
from .settings import OpenAccessSettings

logger = logging.getLogger(__name__)

LAUNCH_RETRY_TTL_SECONDS = 10 * 60
ACTIVE_SESSION_TTL_SECONDS = 24 * 60 * 60

START_SESSION_SCRIPT = """
local existing = redis.call('GET', KEYS[1])
if existing then return existing end
redis.call('SET', KEYS[1], ARGV[1], 'EX', ARGV[2])
redis.call('SET', KEYS[2], ARGV[1], 'EX', ARGV[3])
return ARGV[1]
"""

EXTEND_SESSION_SCRIPT = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
  redis.call('EXPIRE', KEYS[1], ARGV[2])
  return 1
end
return 0
"""

_pool = RedisPool()


class LaunchCode(BaseModel):
    principal_id: int
    thread_id: int
    class_id: int
    assistant_id: int
    session_id: str


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def principal_key(settings: OpenAccessSettings, principal_id: int, *parts: str) -> str:
    # The hash tag keeps a principal's keys in one cluster slot for the scripts.
    return ":".join(
        ("pingpong", "oa", settings.client_id, f"{{{principal_id}}}", *parts)
    )


def _active_key(settings: OpenAccessSettings, principal_id: int) -> str:
    return principal_key(settings, principal_id, "active")


def _code_key(settings: OpenAccessSettings, code: str) -> str:
    return ":".join(("pingpong", "oa", settings.client_id, "code", _digest(code)))


@asynccontextmanager
async def redis_client(settings: OpenAccessSettings):
    try:
        async with _pool.client(settings) as client:
            yield client
    except RedisError as exc:
        logger.exception("Open Access Redis operation failed")
        raise unavailable() from exc


async def close_redis_clients():
    await _pool.close()


async def start_session(
    settings: OpenAccessSettings, principal_id: int, launch_id: str
) -> str:
    async with redis_client(settings) as redis:
        return await redis.eval(
            START_SESSION_SCRIPT,
            2,
            principal_key(settings, principal_id, "launch", _digest(launch_id)),
            _active_key(settings, principal_id),
            secrets.token_urlsafe(24),
            LAUNCH_RETRY_TTL_SECONDS,
            ACTIVE_SESSION_TTL_SECONDS,
        )


async def active_session(settings: OpenAccessSettings, principal_id: int) -> str | None:
    async with redis_client(settings) as redis:
        return await redis.get(_active_key(settings, principal_id))


async def is_active_session(
    settings: OpenAccessSettings, principal_id: int, session_id: str
) -> bool:
    active = await active_session(settings, principal_id)
    return active is not None and secrets.compare_digest(active, session_id)


async def extend_session(
    settings: OpenAccessSettings, principal_id: int, session_id: str
) -> bool:
    async with redis_client(settings) as redis:
        extended = await redis.eval(
            EXTEND_SESSION_SCRIPT,
            1,
            _active_key(settings, principal_id),
            session_id,
            ACTIVE_SESSION_TTL_SECONDS,
        )
    return bool(extended)


async def end_session(settings: OpenAccessSettings, principal_id: int) -> None:
    async with redis_client(settings) as redis:
        await redis.delete(_active_key(settings, principal_id))


async def issue_code(settings: OpenAccessSettings, launch: LaunchCode) -> str:
    code = secrets.token_urlsafe(32)
    async with redis_client(settings) as redis:
        stored = await redis.set(
            _code_key(settings, code),
            launch.model_dump_json(),
            ex=settings.launch_code_ttl_seconds,
            nx=True,
        )
    if not stored:
        raise unavailable()
    return code


async def consume_code(settings: OpenAccessSettings, code: str) -> LaunchCode | None:
    async with redis_client(settings) as redis:
        raw = await redis.getdel(_code_key(settings, code))
    return LaunchCode.model_validate_json(raw) if raw else None
