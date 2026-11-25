import secrets
from datetime import datetime

import pingpong.models as models
import pingpong.schemas as schemas
from .errors import OpenAccessError
from .settings import OpenAccessSettings, RegisteredLimits, TierLimits
from ..audit import audit
from . import store

DAY_MS = 24 * 60 * 60 * 1000
MINUTE_MS = 60 * 1000
DAILY_KEY_TTL_SECONDS = 2 * 24 * 60 * 60
MONTHLY_KEY_TTL_SECONDS = 32 * 24 * 60 * 60
UNLIMITED = -1
MICRODOLLARS = 1_000_000
ALERT_PERCENTS = (50, 80, 100)

# Returns an error code, or "ok" once the turn is recorded (never on a dry run).
TURN_SCRIPT = """
local now = tonumber(ARGV[1])
local window = tonumber(ARGV[2])
redis.call('ZREMRANGEBYSCORE', KEYS[1], '-inf', now - window)
redis.call('ZREMRANGEBYSCORE', KEYS[2], '-inf', now - window)
local daily = tonumber(ARGV[7])
if daily >= 0 and tonumber(redis.call('GET', KEYS[3]) or '0') >= daily then
  return 'open_access_daily_budget'
end
local monthly = tonumber(ARGV[9])
if monthly >= 0 and tonumber(redis.call('GET', KEYS[4]) or '0') >= monthly then
  return 'open_access_monthly_budget'
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
if tonumber(redis.call('GET', KEYS[1]) or '0') >= tonumber(ARGV[1]) then
  return 0
end
redis.call('INCR', KEYS[1])
redis.call('EXPIRE', KEYS[1], ARGV[2])
return 1
"""

QUOTA_CODES = frozenset(
    {
        "open_access_daily_budget",
        "open_access_monthly_budget",
        "open_access_thread_turn_limit",
        "open_access_turn_limit",
        "open_access_capacity",
    }
)

CREDIT_SPEND_SCRIPT = """
if redis.call('HSETNX', KEYS[1], ARGV[1], '1') == 0 then
  return 0
end
redis.call('EXPIRE', KEYS[1], ARGV[2])
for i = 2, #KEYS do
  local amount = tonumber(ARGV[i + 1])
  if amount > 0 then
    redis.call('INCRBY', KEYS[i], amount)
    redis.call('EXPIRE', KEYS[i], ARGV[#KEYS + 2])
  end
end
return 1
"""

MESSAGES = {
    "open_access_daily_budget": "You have reached today's usage limit.",
    "open_access_monthly_budget": "You have reached this month's usage limit.",
    "open_access_thread_turn_limit": "You have reached today's limit for this lesson.",
    "open_access_turn_limit": "You have reached today's message limit.",
    "open_access_burst_limit": "You're sending messages too quickly.",
    "open_access_capacity": "Chat is unavailable right now.",
}


def _day(now: datetime) -> str:
    return now.strftime("%Y%m%d")


def _month(now: datetime) -> str:
    return now.strftime("%Y%m")


def _micro(dollars: float) -> int:
    return round(dollars * MICRODOLLARS)


def _ms(now: datetime) -> int:
    return int(now.timestamp() * 1000)


def global_key(settings: OpenAccessSettings, *parts: str) -> str:
    return ":".join(("pingpong", "oa", settings.client_id, "{global}", *parts))


def tier_limits(
    settings: OpenAccessSettings, principal: models.ExternalPrincipal
) -> TierLimits | RegisteredLimits:
    return (
        settings.limits.anonymous
        if principal.tier == schemas.ExternalPrincipalTier.ANONYMOUS
        else settings.limits.registered
    )


def _monthly_budget(limits: TierLimits | RegisteredLimits) -> int:
    return (
        _micro(limits.monthly_budget)
        if isinstance(limits, RegisteredLimits)
        else UNLIMITED
    )


def _spend_keys(
    settings: OpenAccessSettings, principal_id: int, now: datetime, kind: str
) -> tuple[str, str, str, str]:
    return (
        store.principal_key(settings, principal_id, kind, _day(now)),
        store.principal_key(settings, principal_id, kind, _month(now)),
        global_key(settings, _day(now), kind),
        global_key(settings, _month(now), kind),
    )


def limit_error(error_code: str) -> OpenAccessError:
    audit("oa.limit_hit", error_code=error_code)
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
        site_daily, site_monthly = await redis.mget(
            global_key(settings, _day(now), "spend"),
            global_key(settings, _month(now), "spend"),
        )
        if int(site_daily or 0) >= _micro(settings.limits.daily_budget) or int(
            site_monthly or 0
        ) >= _micro(settings.limits.monthly_budget):
            return "open_access_capacity"
        daily, monthly = _spend_keys(settings, principal.id, now, "spend")[:2]
        return await redis.eval(
            TURN_SCRIPT,
            4,
            store.principal_key(settings, principal.id, "turns"),
            store.principal_key(
                settings, principal.id, "thread", str(thread_id), "turns"
            ),
            daily,
            monthly,
            _ms(now),
            DAY_MS,
            settings.limits.turns_per_minute,
            tier.thread_turns_per_day,
            tier.principal_turns_per_day,
            member,
            _micro(tier.daily_budget),
            int(dry_run),
            _monthly_budget(tier),
        )


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


async def speech_available(
    settings: OpenAccessSettings, principal: models.ExternalPrincipal, now: datetime
) -> bool:
    tier = tier_limits(settings, principal)
    site = settings.limits.elevenlabs_budget_percent / 100
    own = (
        site
        if tier.elevenlabs_budget_percent is None
        else tier.elevenlabs_budget_percent / 100
    )
    budgets = (
        _micro(tier.daily_budget) * own,
        _monthly_budget(tier) * own,
        _micro(settings.limits.daily_budget) * site,
        _micro(settings.limits.monthly_budget) * site,
    )
    async with store.redis_client(settings) as redis:
        spent = [
            await redis.get(key)
            for key in _spend_keys(settings, principal.id, now, "speech")
        ]
    return all(
        budget < 0 or int(used or 0) < budget for used, budget in zip(spent, budgets)
    )


async def record_usage(
    settings: OpenAccessSettings,
    principal_id: int,
    now: datetime,
    *,
    openai_cost: float,
    speech_cost: float,
) -> None:
    share = settings.limits.elevenlabs_budget_percent / 100
    async with store.redis_client(settings) as redis:
        for kind, amount, scale in (
            ("spend", _micro(openai_cost + speech_cost), 1),
            ("speech", _micro(speech_cost), share),
        ):
            if not amount:
                continue
            spent = []
            for key, ttl in zip(
                _spend_keys(settings, principal_id, now, kind),
                (
                    DAILY_KEY_TTL_SECONDS,
                    MONTHLY_KEY_TTL_SECONDS,
                    DAILY_KEY_TTL_SECONDS,
                    MONTHLY_KEY_TTL_SECONDS,
                ),
            ):
                spent.append(await redis.incrby(key, amount))
                await redis.expire(key, ttl)
            for period, total, budget in (
                ("daily", spent[2], settings.limits.daily_budget),
                ("monthly", spent[3], settings.limits.monthly_budget),
            ):
                limit = _micro(budget) * scale
                for percent in ALERT_PERCENTS:
                    if total - amount < limit * percent / 100 <= total:
                        audit(
                            "oa.budget_threshold",
                            budget=kind,
                            period=period,
                            percent=percent,
                            spent=total / MICRODOLLARS,
                            limit=limit / MICRODOLLARS,
                        )


async def transfer_usage(
    settings: OpenAccessSettings,
    source_id: int,
    target_id: int,
    thread_id: int | None,
    now: datetime,
) -> None:
    copies: list[tuple[str, ...]] = [("turns",)]
    if thread_id is not None:
        copies.append(("thread", str(thread_id), "turns"))
    async with store.redis_client(settings) as redis:
        for parts in copies:
            turns = await redis.zrangebyscore(
                store.principal_key(settings, source_id, *parts),
                _ms(now) - DAY_MS,
                "+inf",
                withscores=True,
            )
            if turns:
                target = store.principal_key(settings, target_id, *parts)
                await redis.zadd(target, dict(turns))
                await redis.pexpire(target, DAY_MS)
        sources = [
            *_spend_keys(settings, source_id, now, "spend")[:2],
            *_spend_keys(settings, source_id, now, "speech")[:2],
        ]
        targets = [
            *_spend_keys(settings, target_id, now, "spend")[:2],
            *_spend_keys(settings, target_id, now, "speech")[:2],
        ]
        amounts = await redis.mget(sources)
        await redis.eval(
            CREDIT_SPEND_SCRIPT,
            1 + len(targets),
            store.principal_key(settings, target_id, "credited"),
            *targets,
            str(source_id),
            MONTHLY_KEY_TTL_SECONDS,
            *(int(amount or 0) for amount in amounts),
            MONTHLY_KEY_TTL_SECONDS,
        )


async def reserve_new_thread(settings: OpenAccessSettings, now: datetime) -> None:
    async with store.redis_client(settings) as redis:
        allowed = await redis.eval(
            CEILING_SCRIPT,
            1,
            global_key(settings, _day(now), "threads"),
            settings.limits.daily_new_threads,
            DAILY_KEY_TTL_SECONDS,
        )
    if not allowed:
        audit("oa.limit_hit", error_code="open_access_thread_capacity")
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
    audit("oa.kill_switch", paused=paused, anonymous_only=anonymous_only)
