import secrets
from datetime import datetime

import pingpong.models as models
import pingpong.schemas as schemas
from .errors import OpenAccessError
from .settings import OpenAccessSettings, TierLimits
from . import store

DAY_MS = 24 * 60 * 60 * 1000
MINUTE_MS = 60 * 1000
DAILY_KEY_TTL_SECONDS = 2 * 24 * 60 * 60
UNLIMITED = -1

# Returns an error code, or "ok" once the turn is recorded (never on a dry run).
TURN_SCRIPT = """
local now = tonumber(ARGV[1])
local window = tonumber(ARGV[2])
redis.call('ZREMRANGEBYSCORE', KEYS[1], '-inf', now - window)
redis.call('ZREMRANGEBYSCORE', KEYS[2], '-inf', now - window)
local budget = tonumber(ARGV[7])
if budget >= 0 and tonumber(redis.call('GET', KEYS[3]) or '0') >= budget then
  return 'open_access_token_limit'
end
if redis.call('ZCARD', KEYS[2]) >= tonumber(ARGV[4]) then
  return 'open_access_thread_turn_limit'
end
if redis.call('ZCARD', KEYS[1]) >= tonumber(ARGV[5]) then
  return 'open_access_turn_limit'
end
if ARGV[8] == '1' then return 'ok' end
if redis.call('ZCOUNT', KEYS[1], now - 60000, '+inf') >= tonumber(ARGV[3]) then
  return 'open_access_burst_limit'
end
redis.call('ZADD', KEYS[1], now, ARGV[6])
redis.call('ZADD', KEYS[2], now, ARGV[6])
redis.call('PEXPIRE', KEYS[1], window)
redis.call('PEXPIRE', KEYS[2], window)
return 'ok'
"""

CEILING_SCRIPT = """
local turns = tonumber(ARGV[1])
local tokens = tonumber(ARGV[2])
if tokens >= 0 and tonumber(redis.call('GET', KEYS[2]) or '0') >= tokens then
  return 0
end
if turns >= 0 and tonumber(redis.call('GET', KEYS[1]) or '0') >= turns then
  return 0
end
if ARGV[4] ~= '1' then
  redis.call('INCR', KEYS[1])
  redis.call('EXPIRE', KEYS[1], ARGV[3])
end
return 1
"""

MESSAGES = {
    "open_access_token_limit": "You have reached today's usage limit.",
    "open_access_thread_turn_limit": "You have reached today's limit for this lesson.",
    "open_access_turn_limit": "You have reached today's message limit.",
    "open_access_burst_limit": "You're sending messages too quickly.",
    "open_access_capacity": "Chat is unavailable right now.",
}


def _limit(value: int | None) -> int:
    return UNLIMITED if value is None else value


def _day(now: datetime) -> str:
    return now.strftime("%Y%m%d")


def _ms(now: datetime) -> int:
    return int(now.timestamp() * 1000)


def global_key(settings: OpenAccessSettings, *parts: str) -> str:
    return ":".join(("pingpong", "oa", settings.client_id, "{global}", *parts))


def tier_limits(
    settings: OpenAccessSettings, principal: models.ExternalPrincipal
) -> TierLimits:
    return (
        settings.limits.anonymous
        if principal.tier == schemas.ExternalPrincipalTier.ANONYMOUS
        else settings.limits.registered
    )


def limit_error(error_code: str) -> OpenAccessError:
    return OpenAccessError(429, error_code, MESSAGES[error_code])


async def _turn_status(
    settings: OpenAccessSettings,
    principal: models.ExternalPrincipal,
    thread_id: int,
    now: datetime,
    *,
    member: str = "",
    dry_run: bool,
) -> str:
    tier = tier_limits(settings, principal)
    async with store.redis_client(settings) as redis:
        status = await redis.eval(
            TURN_SCRIPT,
            3,
            store.principal_key(settings, principal.id, "turns"),
            store.principal_key(
                settings, principal.id, "thread", str(thread_id), "turns"
            ),
            store.principal_key(settings, principal.id, "tokens", _day(now)),
            _ms(now),
            DAY_MS,
            settings.limits.turns_per_minute,
            tier.thread_turns_per_day,
            tier.principal_turns_per_day,
            member,
            _limit(settings.limits.principal_daily_tokens),
            int(dry_run),
        )
        if status != "ok":
            return status
        if not await redis.eval(
            CEILING_SCRIPT,
            2,
            global_key(settings, _day(now), "turns"),
            global_key(settings, _day(now), "tokens"),
            _limit(settings.limits.daily_turns),
            _limit(settings.limits.daily_openai_tokens),
            DAILY_KEY_TTL_SECONDS,
            int(dry_run),
        ):
            if not dry_run:
                await redis.zrem(
                    store.principal_key(settings, principal.id, "turns"), member
                )
                await redis.zrem(
                    store.principal_key(
                        settings, principal.id, "thread", str(thread_id), "turns"
                    ),
                    member,
                )
            return "open_access_capacity"
    return "ok"


async def reserve_turn(
    settings: OpenAccessSettings,
    principal: models.ExternalPrincipal,
    thread_id: int,
    now: datetime,
) -> None:
    status = await _turn_status(
        settings,
        principal,
        thread_id,
        now,
        member=f"{thread_id}:{secrets.token_urlsafe(12)}",
        dry_run=False,
    )
    if status != "ok":
        raise limit_error(status)


async def chat_block(
    settings: OpenAccessSettings,
    principal: models.ExternalPrincipal,
    thread_id: int,
    now: datetime,
) -> str | None:
    status = await _turn_status(settings, principal, thread_id, now, dry_run=True)
    return None if status == "ok" else status


async def speech_available(settings: OpenAccessSettings, now: datetime) -> bool:
    budget = settings.limits.daily_tts_characters
    if budget is None:
        return True
    async with store.redis_client(settings) as redis:
        used = await redis.get(global_key(settings, _day(now), "tts"))
    return int(used or 0) < budget


async def record_usage(
    settings: OpenAccessSettings,
    principal_id: int,
    now: datetime,
    *,
    tokens: int,
    tts_characters: int,
) -> None:
    async with store.redis_client(settings) as redis:
        for key, amount in (
            (store.principal_key(settings, principal_id, "tokens", _day(now)), tokens),
            (global_key(settings, _day(now), "tokens"), tokens),
            (global_key(settings, _day(now), "tts"), tts_characters),
        ):
            if amount:
                await redis.incrby(key, amount)
                await redis.expire(key, DAILY_KEY_TTL_SECONDS)


async def reserve_new_thread(settings: OpenAccessSettings, now: datetime) -> None:
    async with store.redis_client(settings) as redis:
        allowed = await redis.eval(
            CEILING_SCRIPT,
            2,
            global_key(settings, _day(now), "threads"),
            global_key(settings, _day(now), "tokens"),
            _limit(settings.limits.daily_new_threads),
            UNLIMITED,
            DAILY_KEY_TTL_SECONDS,
            0,
        )
    if not allowed:
        raise OpenAccessError(
            503, "open_access_capacity", "New lessons are unavailable right now."
        )


async def paused_flags(settings: OpenAccessSettings) -> tuple[bool, bool]:
    async with store.redis_client(settings) as redis:
        paused, anonymous_paused = await redis.mget(
            global_key(settings, "paused"), global_key(settings, "anonymous_paused")
        )
    return paused is not None, anonymous_paused is not None


async def is_paused(settings: OpenAccessSettings, *, anonymous: bool) -> bool:
    paused, anonymous_paused = await paused_flags(settings)
    return (
        settings.paused
        or paused
        or (anonymous and (settings.anonymous_paused or anonymous_paused))
    )


async def set_paused(
    settings: OpenAccessSettings, paused: bool, *, anonymous_only: bool = False
) -> None:
    key = global_key(settings, "anonymous_paused" if anonymous_only else "paused")
    async with store.redis_client(settings) as redis:
        if paused:
            await redis.set(key, "1")
        else:
            await redis.delete(key)
