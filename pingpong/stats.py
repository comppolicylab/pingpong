import asyncio
from datetime import date, datetime, timedelta, timezone
from typing import Literal

from sqlalchemy import func, select

import pingpong.models as models
from pingpong.schemas import (
    MessageRole,
    RunDailyAssistantMessageAssistantStats,
    RunDailyAssistantMessageModelStats,
    RunDailyAssistantMessageStats,
    Statistics,
)
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload


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


async def get_runs_with_multiple_assistant_messages_stats(
    session: AsyncSession,
    *,
    days: int = 14,
    group_by: Literal["model", "assistant"] = "model",
    limit: int = 10,
) -> list[RunDailyAssistantMessageStats]:
    """Return daily run statistics for runs with multiple assistant messages."""

    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=days)

    run_day = func.date_trunc("day", models.Run.created).label("run_day")

    recent_runs = (
        select(
            models.Run.id.label("run_id"),
            run_day,
            models.Run.model.label("model"),
            models.Run.assistant_id.label("assistant_id"),
        )
        .where(models.Run.created >= cutoff)
        .cte("recent_runs")
    )

    assistant_counts = (
        select(
            recent_runs.c.run_id,
            recent_runs.c.run_day,
            recent_runs.c.model,
            recent_runs.c.assistant_id,
            func.count(models.Message.id).label("assistant_message_count"),
        )
        .join(models.Message, models.Message.run_id == recent_runs.c.run_id)
        .where(models.Message.role == MessageRole.ASSISTANT)
        .group_by(
            recent_runs.c.run_id,
            recent_runs.c.run_day,
            recent_runs.c.model,
            recent_runs.c.assistant_id,
        )
        .cte("assistant_counts")
    )

    multi_runs = (
        select(
            assistant_counts.c.run_day,
            assistant_counts.c.model,
            assistant_counts.c.run_id,
            assistant_counts.c.assistant_id,
        )
        .where(assistant_counts.c.assistant_message_count > 1)
        .cte("multi_runs")
    )

    daily_totals_stmt = (
        select(
            recent_runs.c.run_day,
            func.count().label("total_runs"),
        )
        .group_by(recent_runs.c.run_day)
        .order_by(recent_runs.c.run_day)
    )

    daily_matches_stmt = select(
        multi_runs.c.run_day,
        func.count().label("matching_runs"),
    ).group_by(multi_runs.c.run_day)

    totals_rows = (await session.execute(daily_totals_stmt)).all()
    matches_rows = (await session.execute(daily_matches_stmt)).all()

    def _normalize_date(value: date | datetime | None) -> date:
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, date):
            return value
        raise ValueError("run_day cannot be null")

    totals_map: dict[date, int] = {
        _normalize_date(row.run_day): int(row.total_runs or 0) for row in totals_rows
    }
    matches_map: dict[date, int] = {
        _normalize_date(row.run_day): int(row.matching_runs or 0)
        for row in matches_rows
    }

    model_totals_map: dict[tuple[date, str | None], int] = {}
    model_matches_map: dict[tuple[date, str | None], int] = {}
    assistant_totals_map: dict[tuple[date, int | None], int] = {}
    assistant_matches_map: dict[tuple[date, int | None], int] = {}
    assistant_names: dict[int, str] = {}

    if totals_map and group_by == "model":
        model_totals_stmt = (
            select(
                recent_runs.c.run_day,
                recent_runs.c.model,
                func.count().label("total_runs"),
            )
            .group_by(recent_runs.c.run_day, recent_runs.c.model)
            .order_by(recent_runs.c.run_day, recent_runs.c.model)
        )

        model_matches_stmt = select(
            multi_runs.c.run_day,
            multi_runs.c.model,
            func.count().label("matching_runs"),
        ).group_by(multi_runs.c.run_day, multi_runs.c.model)

        model_totals_rows = (await session.execute(model_totals_stmt)).all()
        model_matches_rows = (await session.execute(model_matches_stmt)).all()

        model_totals_map = {
            (
                _normalize_date(row.run_day),
                row.model,
            ): int(row.total_runs or 0)
            for row in model_totals_rows
        }
        model_matches_map = {
            (
                _normalize_date(row.run_day),
                row.model,
            ): int(row.matching_runs or 0)
            for row in model_matches_rows
        }
    elif totals_map and group_by == "assistant":
        assistant_totals_stmt = (
            select(
                recent_runs.c.run_day,
                recent_runs.c.assistant_id,
                func.count().label("total_runs"),
            )
            .group_by(recent_runs.c.run_day, recent_runs.c.assistant_id)
            .order_by(recent_runs.c.run_day, recent_runs.c.assistant_id)
        )

        assistant_matches_stmt = select(
            multi_runs.c.run_day,
            multi_runs.c.assistant_id,
            func.count().label("matching_runs"),
        ).group_by(multi_runs.c.run_day, multi_runs.c.assistant_id)

        assistant_totals_rows = (await session.execute(assistant_totals_stmt)).all()
        assistant_matches_rows = (await session.execute(assistant_matches_stmt)).all()

        assistant_totals_map = {
            (
                _normalize_date(row.run_day),
                row.assistant_id,
            ): int(row.total_runs or 0)
            for row in assistant_totals_rows
        }
        assistant_matches_map = {
            (
                _normalize_date(row.run_day),
                row.assistant_id,
            ): int(row.matching_runs or 0)
            for row in assistant_matches_rows
        }

        assistant_ids = {
            row.assistant_id
            for row in assistant_totals_rows + assistant_matches_rows
            if row.assistant_id is not None
        }

        if assistant_ids:
            assistants_with_class = (
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
            assistant_names = {a.id: a.name for a in assistants_with_class}
            assistant_class_ids = {a.id: a.class_id for a in assistants_with_class}
            assistant_class_names = {
                a.id: a.class_.name if a.class_ else None for a in assistants_with_class
            }

    statistics: list[RunDailyAssistantMessageStats] = []

    for day_key in sorted(totals_map.keys()):
        total_runs = totals_map[day_key]
        matching_runs = matches_map.get(day_key, 0)
        percentage = round((matching_runs / total_runs) * 100, 2) if total_runs else 0.0

        models_stats: list[RunDailyAssistantMessageModelStats] | None = None
        assistants_stats: list[RunDailyAssistantMessageAssistantStats] | None = None

        if group_by == "model":
            model_keys = [key for key in model_totals_map.keys() if key[0] == day_key]

            if model_keys:
                model_keys.sort(key=lambda item: item[1] or "")
                models_stats = []
                for _, model_name in model_keys:
                    model_total = model_totals_map[(day_key, model_name)]
                    model_matching = model_matches_map.get((day_key, model_name), 0)
                    model_percentage = (
                        round((model_matching / model_total) * 100, 2)
                        if model_total
                        else 0.0
                    )
                    models_stats.append(
                        RunDailyAssistantMessageModelStats(
                            model=model_name,
                            total_runs=model_total,
                            runs_with_multiple_assistant_messages=model_matching,
                            percentage=model_percentage,
                        )
                    )

                models_stats.sort(
                    key=lambda item: (
                        -item.percentage,
                        -item.runs_with_multiple_assistant_messages,
                        -item.total_runs,
                        item.model is None,
                        item.model or "",
                    )
                )
        elif group_by == "assistant":
            assistant_keys = [
                key for key in assistant_totals_map.keys() if key[0] == day_key
            ]

            if assistant_keys:
                assistants_stats = []
                for _, assistant_id in assistant_keys:
                    assistant_total = assistant_totals_map[(day_key, assistant_id)]
                    assistant_matching = assistant_matches_map.get(
                        (day_key, assistant_id), 0
                    )
                    assistant_percentage = (
                        round((assistant_matching / assistant_total) * 100, 2)
                        if assistant_total
                        else 0.0
                    )
                    assistants_stats.append(
                        RunDailyAssistantMessageAssistantStats(
                            assistant_id=assistant_id,
                            assistant_name=assistant_names.get(assistant_id)
                            if assistant_id is not None
                            else None,
                            total_runs=assistant_total,
                            runs_with_multiple_assistant_messages=assistant_matching,
                            percentage=assistant_percentage,
                            class_id=assistant_class_ids.get(assistant_id),
                            class_name=assistant_class_names.get(assistant_id),
                        )
                    )

                assistants_stats.sort(
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

                if limit > 0:
                    assistants_stats = assistants_stats[:limit]

        statistics.append(
            RunDailyAssistantMessageStats(
                date=day_key,
                total_runs=total_runs,
                runs_with_multiple_assistant_messages=matching_runs,
                percentage=percentage,
                models=models_stats,
                assistants=assistants_stats,
            )
        )

    return statistics
