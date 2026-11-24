from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

from genai_prices import Usage, calc_price
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

import pingpong.models as models
import pingpong.schemas as schemas
from . import limits
from .settings import OpenAccessSettings

Granularity = Literal["day", "week", "month"]


class UsageRow(BaseModel):
    period: date
    tier: schemas.ExternalPrincipalTier
    assistant_id: int | None
    runs: int = 0
    input_tokens: int = 0
    cached_input_tokens: int = 0
    output_tokens: int = 0
    tts_characters: int = 0
    openai_cost: float = 0
    speech_cost: float = 0


class SignupRow(BaseModel):
    period: date
    signups: int


class Lesson(BaseModel):
    assistant_id: int
    number: int
    name: str | None


class TopUser(BaseModel):
    subject: str
    tier: schemas.ExternalPrincipalTier
    runs: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    tts_characters: int = 0
    openai_cost: float = 0
    speech_cost: float = 0
    last_active: datetime


class Limits(BaseModel):
    daily_budget: float
    monthly_budget: float
    paused: bool
    anonymous_paused: bool


class UsageSummary(BaseModel):
    start: date
    end: date
    granularity: Granularity
    periods: list[date]
    lessons: list[Lesson]
    rows: list[UsageRow]
    signups: list[SignupRow]
    top_users: list[TopUser]
    limits: Limits


def ledger_row(
    run: models.Run,
    principal_id: int,
    tier: schemas.ExternalPrincipalTier,
    tts_characters: int,
    tts_model: str | None,
) -> models.OpenAccessUsage:
    usage = run.usage or {}
    return models.OpenAccessUsage(
        principal_id=principal_id,
        tier=tier,
        assistant_id=run.assistant_id,
        model=run.model,
        service_tier=usage.get("service_tier"),
        status=run.status.value if run.status else None,
        metered=bool(usage),
        input_tokens=int(usage.get("input_tokens") or 0),
        cached_input_tokens=int(
            (usage.get("input_tokens_details") or {}).get("cached_tokens") or 0
        ),
        output_tokens=int(usage.get("output_tokens") or 0),
        tts_model=tts_model,
        tts_characters=tts_characters,
    )


def _period(day: date, granularity: Granularity) -> date:
    if granularity == "week":
        return day - timedelta(days=day.weekday())
    if granularity == "month":
        return day.replace(day=1)
    return day


def _periods(start: date, end: date, granularity: Granularity) -> list[date]:
    periods: list[date] = []
    day = _period(start, granularity)
    while day <= end:
        periods.append(day)
        if granularity == "day":
            day += timedelta(days=1)
        elif granularity == "week":
            day += timedelta(weeks=1)
        else:
            day = (day + timedelta(days=32)).replace(day=1)
    return periods


def _hour(db: AsyncSession, column):
    if db.bind.dialect.name == "postgresql":
        return func.date_trunc("hour", column)
    return func.strftime("%Y-%m-%d %H:00:00", column)


def _utc(hour: datetime | str) -> datetime:
    if isinstance(hour, str):
        hour = datetime.fromisoformat(hour)
    return hour if hour.tzinfo else hour.replace(tzinfo=UTC)


def _openai_cost(
    model: str | None,
    service_tier: str | None,
    input_tokens: int,
    cached_input_tokens: int,
    output_tokens: int,
    at: datetime,
) -> float | None:
    try:
        return float(
            calc_price(
                Usage(
                    input_tokens=input_tokens,
                    cache_read_tokens=cached_input_tokens,
                    output_tokens=output_tokens,
                ),
                model_ref=model or "",
                provider_id="openai",
                genai_request_timestamp=at,
                price_context={"service_tier": service_tier} if service_tier else None,
            ).total_price
        )
    except LookupError:
        return None


def cost(
    settings: OpenAccessSettings,
    model: str | None,
    service_tier: str | None,
    tts_model: str | None,
    input_tokens: int,
    cached_input_tokens: int,
    output_tokens: int,
    tts_characters: int,
    at: datetime,
) -> tuple[float, float]:
    openai = _openai_cost(
        model, service_tier, input_tokens, cached_input_tokens, output_tokens, at
    )
    speech = settings.pricing.tts_per_thousand_characters.get(tts_model or "", 0)
    return openai or 0, tts_characters * speech / 1000


async def _top_users(
    db: AsyncSession,
    settings: OpenAccessSettings,
    lower: datetime,
    upper: datetime,
    limit: int = 10,
) -> list[TopUser]:
    usage = models.OpenAccessUsage
    principal = models.ExternalPrincipal
    result = await db.execute(
        select(
            principal.id,
            principal.subject,
            principal.tier,
            usage.model,
            usage.service_tier,
            usage.tts_model,
            func.count(usage.id),
            func.sum(usage.input_tokens),
            func.sum(usage.cached_input_tokens),
            func.sum(usage.output_tokens),
            func.sum(usage.tts_characters),
            func.max(usage.created),
        )
        .join(principal, principal.id == usage.principal_id)
        .where(usage.created >= lower, usage.created < upper)
        .group_by(
            principal.id,
            principal.subject,
            principal.tier,
            usage.model,
            usage.service_tier,
            usage.tts_model,
        )
    )
    users: dict[int, TopUser] = {}
    for (
        principal_id,
        subject,
        tier,
        model,
        service_tier,
        tts_model,
        runs,
        input_tokens,
        cached,
        output,
        tts,
        last,
    ) in result:
        last = _utc(last)
        user = users.setdefault(
            principal_id, TopUser(subject=subject, tier=tier, last_active=last)
        )
        user.runs += runs
        user.input_tokens += int(input_tokens or 0)
        user.output_tokens += int(output or 0)
        user.tts_characters += int(tts or 0)
        user.last_active = max(user.last_active, last)
        openai, speech = cost(
            settings,
            model,
            service_tier,
            tts_model,
            int(input_tokens or 0),
            int(cached or 0),
            int(output or 0),
            int(tts or 0),
            last,
        )
        user.openai_cost += openai
        user.speech_cost += speech
    return sorted(
        users.values(),
        key=lambda user: (
            user.openai_cost + user.speech_cost,
            user.input_tokens + user.output_tokens,
        ),
        reverse=True,
    )[:limit]


def priced(model: str) -> bool:
    return _openai_cost(model, None, 0, 0, 0, datetime.now(UTC)) is not None


def _bounds(start: date, end: date, tz: ZoneInfo) -> tuple[datetime, datetime]:
    return (
        datetime.combine(start, datetime.min.time(), tz).astimezone(UTC),
        datetime.combine(end + timedelta(days=1), datetime.min.time(), tz).astimezone(
            UTC
        ),
    )


async def _limits(settings: OpenAccessSettings) -> Limits:
    paused, anonymous_paused = await limits.paused_flags(settings)
    return Limits(
        daily_budget=settings.limits.daily_budget,
        monthly_budget=settings.limits.monthly_budget,
        paused=settings.paused or paused,
        anonymous_paused=settings.anonymous_paused or anonymous_paused,
    )


async def summarize(
    db: AsyncSession,
    settings: OpenAccessSettings,
    start: date,
    end: date,
    tz: ZoneInfo,
    granularity: Granularity,
) -> UsageSummary:
    lower, upper = _bounds(start, end, tz)
    usage = models.OpenAccessUsage
    hour = _hour(db, usage.created)
    result = await db.execute(
        select(
            hour,
            usage.tier,
            usage.assistant_id,
            usage.model,
            usage.service_tier,
            usage.tts_model,
            func.count(usage.id),
            func.sum(usage.input_tokens),
            func.sum(usage.cached_input_tokens),
            func.sum(usage.output_tokens),
            func.sum(usage.tts_characters),
        )
        .where(usage.created >= lower, usage.created < upper)
        .group_by(
            hour,
            usage.tier,
            usage.assistant_id,
            usage.model,
            usage.service_tier,
            usage.tts_model,
        )
    )
    rows: dict[tuple, UsageRow] = {}
    for (
        bucket,
        tier,
        assistant_id,
        model,
        service_tier,
        tts_model,
        runs,
        input_tokens,
        cached,
        output,
        tts,
    ) in result:
        at = _utc(bucket)
        day = at.astimezone(tz).date()
        if not start <= day <= end:
            continue
        period = _period(day, granularity)
        row = rows.setdefault(
            (period, tier, assistant_id),
            UsageRow(period=period, tier=tier, assistant_id=assistant_id),
        )
        row.runs += runs
        row.input_tokens += int(input_tokens or 0)
        row.cached_input_tokens += int(cached or 0)
        row.output_tokens += int(output or 0)
        row.tts_characters += int(tts or 0)
        openai, speech = cost(
            settings,
            model,
            service_tier,
            tts_model,
            int(input_tokens or 0),
            int(cached or 0),
            int(output or 0),
            int(tts or 0),
            at,
        )
        row.openai_cost += openai
        row.speech_cost += speech

    signup_hour = _hour(db, models.OpenAccessSignup.created)
    signups: dict[date, int] = defaultdict(int)
    for bucket, count in await db.execute(
        select(signup_hour, func.count(models.OpenAccessSignup.id))
        .where(
            models.OpenAccessSignup.created >= lower,
            models.OpenAccessSignup.created < upper,
        )
        .group_by(signup_hour)
    ):
        day = _utc(bucket).astimezone(tz).date()
        if start <= day <= end:
            signups[_period(day, granularity)] += count

    names = dict(
        (
            await db.execute(
                select(models.Assistant.id, models.Assistant.name).where(
                    models.Assistant.id.in_(settings.assistant_ids)
                )
            )
        ).all()
    )
    return UsageSummary(
        start=start,
        end=end,
        granularity=granularity,
        periods=_periods(start, end, granularity),
        lessons=[
            Lesson(
                assistant_id=assistant_id, number=number, name=names.get(assistant_id)
            )
            for number, assistant_id in enumerate(settings.assistant_ids, start=1)
        ],
        rows=sorted(rows.values(), key=lambda row: (row.period, row.tier)),
        signups=[
            SignupRow(period=period, signups=count)
            for period, count in sorted(signups.items())
        ],
        top_users=await _top_users(db, settings, lower, upper),
        limits=await _limits(settings),
    )
