import asyncio
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from typing import Literal

import pingpong.models as models
from pingpong.schemas import (
    ClassThreadCount,
    MessageRole,
    RunDailyAssistantMessageAssistantStats,
    RunDailyAssistantMessageModelStats,
    RunDailyAssistantMessageStats,
    RunDailyAssistantMessageSummary,
    Statistics,
)
from sqlalchemy import case, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy.sql.sqltypes import Date


async def get_statistics(session: AsyncSession) -> Statistics:
    results = await asyncio.gather(
        session.execute(select(func.count()).select_from(models.Institution)),
        session.execute(select(func.count()).select_from(models.Class)),
        session.execute(select(func.count()).select_from(models.User)),
        session.execute(select(func.count()).select_from(models.UserClassRole)),
        session.execute(select(func.count()).select_from(models.Assistant)),
        session.execute(select(func.count()).select_from(models.Thread)),
        session.execute(select(func.count()).select_from(models.File)),
    )

    institutions_count = results[0].scalar_one()
    classes_count = results[1].scalar_one()
    users_count = results[2].scalar_one()
    enrollments_count = results[3].scalar_one()
    assistants_count = results[4].scalar_one()
    threads_count = results[5].scalar_one()
    files_count = results[6].scalar_one()

    # Return the result as a Statistics object
    return Statistics(
        institutions=institutions_count,
        classes=classes_count,
        users=users_count,
        enrollments=enrollments_count,
        assistants=assistants_count,
        threads=threads_count,
        files=files_count,
    )


async def get_statistics_by_institution(
    session: AsyncSession, institution_id: int
) -> Statistics:
    inst_id = institution_id

    classes_count_stmt = (
        select(func.count())
        .select_from(models.Class)
        .where(models.Class.institution_id == inst_id)
    )

    users_count_stmt = (
        select(func.count(func.distinct(models.UserClassRole.user_id)))
        .select_from(models.UserClassRole)
        .join(models.Class, models.UserClassRole.class_id == models.Class.id)
        .where(models.Class.institution_id == inst_id)
    )

    enrollments_count_stmt = (
        select(func.count())
        .select_from(models.UserClassRole)
        .join(models.Class, models.UserClassRole.class_id == models.Class.id)
        .where(models.Class.institution_id == inst_id)
    )

    assistants_count_stmt = (
        select(func.count())
        .select_from(models.Assistant)
        .join(models.Class, models.Assistant.class_id == models.Class.id)
        .where(models.Class.institution_id == inst_id)
    )

    threads_count_stmt = (
        select(func.count())
        .select_from(models.Thread)
        .join(models.Class, models.Thread.class_id == models.Class.id)
        .where(models.Class.institution_id == inst_id)
    )

    direct_file_ids_stmt = (
        select(models.File.id)
        .join(models.Class, models.File.class_id == models.Class.id)
        .where(models.Class.institution_id == inst_id)
    )

    associated_file_ids_stmt = (
        select(models.file_class_association.c.file_id)
        .join(
            models.Class,
            models.file_class_association.c.class_id == models.Class.id,
        )
        .where(models.Class.institution_id == inst_id)
    )

    files_union = direct_file_ids_stmt.union(associated_file_ids_stmt).subquery()
    files_count_stmt = select(func.count()).select_from(files_union)

    results = await asyncio.gather(
        session.execute(
            select(func.count())
            .select_from(models.Institution)
            .where(models.Institution.id == inst_id)
        ),
        session.execute(classes_count_stmt),
        session.execute(users_count_stmt),
        session.execute(enrollments_count_stmt),
        session.execute(assistants_count_stmt),
        session.execute(threads_count_stmt),
        session.execute(files_count_stmt),
    )

    institutions_count = results[0].scalar_one()
    classes_count = results[1].scalar_one()
    users_count = results[2].scalar_one()
    enrollments_count = results[3].scalar_one()
    assistants_count = results[4].scalar_one()
    threads_count = results[5].scalar_one()
    files_count = results[6].scalar_one()

    return Statistics(
        institutions=institutions_count,
        classes=classes_count,
        users=users_count,
        enrollments=enrollments_count,
        assistants=assistants_count,
        threads=threads_count,
        files=files_count,
    )


async def get_thread_counts_by_class(
    session: AsyncSession, institution_id: int
) -> list[ClassThreadCount]:
    stmt = (
        select(
            models.Class.id.label("class_id"),
            models.Class.name.label("class_name"),
            func.count(models.Thread.id).label("thread_count"),
        )
        .select_from(models.Class)
        .join(models.Thread, models.Thread.class_id == models.Class.id, isouter=True)
        .where(models.Class.institution_id == institution_id)
        .group_by(models.Class.id, models.Class.name)
        .order_by(models.Class.name, models.Class.id)
    )

    result = await session.execute(stmt)
    return [
        ClassThreadCount(
            class_id=row.class_id,
            class_name=row.class_name,
            thread_count=row.thread_count,
        )
        for row in result
    ]


async def get_runs_with_multiple_assistant_messages_stats(
    session: AsyncSession,
    *,
    days: int = 14,
    group_by: Literal["model", "assistant"] = "model",
    limit: int = 10,
    summary_only: bool = False,
    sort_priority: Literal["count", "percentage"] = "count",
) -> tuple[list[RunDailyAssistantMessageStats], RunDailyAssistantMessageSummary]:
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=days)

    run_day = cast(func.date_trunc("day", models.Run.created), Date).label("run_day")
    group_field = models.Run.model if group_by == "model" else models.Run.assistant_id

    def _sort_model_entries(items: list[RunDailyAssistantMessageModelStats]) -> None:
        if sort_priority == "percentage":
            items.sort(
                key=lambda item: (
                    -item.percentage,
                    -item.runs_with_multiple_assistant_messages,
                    -item.total_runs,
                    item.model is None,
                    item.model or "",
                )
            )
        else:
            items.sort(
                key=lambda item: (
                    -item.runs_with_multiple_assistant_messages,
                    -item.total_runs,
                    -item.percentage,
                    item.model is None,
                    item.model or "",
                )
            )

    def _sort_assistant_entries(
        items: list[RunDailyAssistantMessageAssistantStats],
    ) -> None:
        if sort_priority == "percentage":
            items.sort(
                key=lambda item: (
                    -item.percentage,
                    -item.runs_with_multiple_assistant_messages,
                    -item.total_runs,
                    item.assistant_name is None,
                    item.assistant_name or "",
                    item.assistant_id
                    if item.assistant_id is not None
                    else float("inf"),
                )
            )
        else:
            items.sort(
                key=lambda item: (
                    -item.runs_with_multiple_assistant_messages,
                    -item.total_runs,
                    -item.percentage,
                    item.assistant_name is None,
                    item.assistant_name or "",
                    item.assistant_id
                    if item.assistant_id is not None
                    else float("inf"),
                )
            )

    # ---- Step 1: Count assistant messages per run ----
    run_message_counts = (
        select(
            models.Run.id.label("run_id"),
            run_day,
            group_field.label("group_field"),
            func.count(models.Message.id)
            .filter(models.Message.role == MessageRole.ASSISTANT)
            .label("assistant_message_count"),
        )
        .join(models.Message, models.Message.run_id == models.Run.id)
        .where(models.Run.created >= cutoff)
        .group_by(models.Run.id, run_day, group_field)
        .cte("run_message_counts")
    )

    # ---- Step 2: Aggregate daily totals ----
    agg_stmt = (
        select(
            run_message_counts.c.run_day,
            run_message_counts.c.group_field,
            func.count().label("total_runs"),
            func.sum(
                case(
                    (run_message_counts.c.assistant_message_count > 1, 1),
                    else_=0,
                )
            ).label("matching_runs"),
        )
        .group_by(run_message_counts.c.run_day, run_message_counts.c.group_field)
        .order_by(run_message_counts.c.run_day)
    )

    rows = (await session.execute(agg_stmt)).all()

    if not rows:
        summary = RunDailyAssistantMessageSummary(
            total_runs=0,
            runs_with_multiple_assistant_messages=0,
            percentage=0.0,
            models=[] if group_by == "model" else None,
            assistants=[] if group_by == "assistant" else None,
        )
        return [], summary

    # ---- Step 3: Fetch assistant metadata (only if grouping by assistant) ----
    assistant_names = {}
    assistant_class_ids = {}
    assistant_class_names = {}

    if group_by == "assistant":
        assistant_ids = {r.group_field for r in rows if r.group_field is not None}
        if assistant_ids:
            assistants = (
                (
                    await session.execute(
                        select(models.Assistant)
                        .options(selectinload(models.Assistant.class_))
                        .where(models.Assistant.id.in_(list(assistant_ids)))
                    )
                )
                .scalars()
                .all()
            )
            assistant_names = {a.id: a.name for a in assistants}
            assistant_class_ids = {a.id: a.class_id for a in assistants}
            assistant_class_names = {
                a.id: a.class_.name if a.class_ else None for a in assistants
            }

    # ---- Step 4: Aggregate in Python ----
    daily_totals: dict[date, int] = defaultdict(int)
    daily_matches: dict[date, int] = defaultdict(int)
    collect_daily = not summary_only
    grouped_stats = defaultdict(list)
    summary_totals: dict[str | int | None, int] = defaultdict(int)
    summary_matches: dict[str | int | None, int] = defaultdict(int)

    for row in rows:
        run_day = row.run_day
        key = row.group_field
        total = int(row.total_runs or 0)
        matches = int(row.matching_runs or 0)

        daily_totals[run_day] += total
        daily_matches[run_day] += matches
        summary_totals[key] += total
        summary_matches[key] += matches

        pct = round(matches / total * 100, 2) if total else 0.0

        if collect_daily and group_by == "model":
            grouped_stats[run_day].append(
                RunDailyAssistantMessageModelStats(
                    model=key,
                    total_runs=total,
                    runs_with_multiple_assistant_messages=matches,
                    percentage=pct,
                )
            )
        elif collect_daily and group_by == "assistant":
            grouped_stats[run_day].append(
                RunDailyAssistantMessageAssistantStats(
                    assistant_id=key,
                    assistant_name=assistant_names.get(key),
                    total_runs=total,
                    runs_with_multiple_assistant_messages=matches,
                    percentage=pct,
                    class_id=assistant_class_ids.get(key),
                    class_name=assistant_class_names.get(key),
                )
            )

    # ---- Step 5: Per-day stats ----
    daily_stats: list[RunDailyAssistantMessageStats] = []
    if collect_daily:
        for day in sorted(daily_totals.keys()):
            total = daily_totals[day]
            matches = daily_matches[day]
            pct = round(matches / total * 100, 2) if total else 0.0
            entries = grouped_stats.get(day)

            if entries:
                if group_by == "model":
                    _sort_model_entries(entries)
                else:
                    _sort_assistant_entries(entries)
                if limit > 0:
                    entries = entries[:limit]

            daily_stats.append(
                RunDailyAssistantMessageStats(
                    date=day,
                    total_runs=total,
                    runs_with_multiple_assistant_messages=matches,
                    percentage=pct,
                    models=entries if group_by == "model" else None,
                    assistants=entries if group_by == "assistant" else None,
                )
            )

    # ---- Step 6: Summary ----
    summary_total = sum(daily_totals.values())
    summary_matching = sum(daily_matches.values())
    summary_pct = (
        round(summary_matching / summary_total * 100, 2) if summary_total else 0.0
    )

    if group_by == "model":
        summary_entries = [
            RunDailyAssistantMessageModelStats(
                model=m,
                total_runs=summary_totals[m],
                runs_with_multiple_assistant_messages=summary_matches[m],
                percentage=round(summary_matches[m] / summary_totals[m] * 100, 2)
                if summary_totals[m]
                else 0.0,
            )
            for m in summary_totals
        ]
    else:
        summary_entries = [
            RunDailyAssistantMessageAssistantStats(
                assistant_id=a,
                assistant_name=assistant_names.get(a),
                total_runs=summary_totals[a],
                runs_with_multiple_assistant_messages=summary_matches[a],
                percentage=round(summary_matches[a] / summary_totals[a] * 100, 2)
                if summary_totals[a]
                else 0.0,
                class_id=assistant_class_ids.get(a),
                class_name=assistant_class_names.get(a),
            )
            for a in summary_totals
        ]

    if group_by == "model":
        _sort_model_entries(summary_entries)
    else:
        _sort_assistant_entries(summary_entries)
    if limit > 0:
        summary_entries = summary_entries[:limit]

    summary = RunDailyAssistantMessageSummary(
        total_runs=summary_total,
        runs_with_multiple_assistant_messages=summary_matching,
        percentage=summary_pct,
        models=summary_entries if group_by == "model" else None,
        assistants=summary_entries if group_by == "assistant" else None,
    )

    return daily_stats, summary
