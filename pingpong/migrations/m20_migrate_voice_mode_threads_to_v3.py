import logging
from collections.abc import AsyncIterator
from datetime import datetime, timezone
from typing import Any

from openai import Omit, omit
from openai.types.beta.threads import Message as OpenAIMessage
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

import pingpong.models as models
import pingpong.schemas as schemas
from pingpong.ai import get_openai_client_by_class_id
from pingpong.server import OpenAIClient

logger = logging.getLogger(__name__)

LOCAL_BATCH_SIZE = 100
MIGRATION_KEY = "v2_voice_mode_thread_migration"


async def migrate_voice_mode_threads_to_v3(session: AsyncSession) -> None:
    """Convert v2 Voice mode threads from OpenAI-backed messages to local v3 rows.

    Voice mode v2 stored only transcript messages in OpenAI threads. There is no
    durable v2 run history to preserve, so each converted thread gets one synthetic
    completed local run containing all migrated transcript messages.
    """

    logger.info(
        "m20 starting voice thread migration. classes=%s threads=%s",
        await _count_v2_voice_thread_classes(session),
        await _count_v2_voice_threads(session),
    )

    failed_threads: list[str] = []
    skipped_classes = 0
    converted_threads = 0
    converted_messages = 0
    empty_threads = 0
    async for class_id in _v2_voice_thread_class_ids(session):
        try:
            openai_client = await get_openai_client_by_class_id(session, class_id)
        except Exception:
            skipped_classes += 1
            logger.exception(
                "Could not get OpenAI client during v2 voice thread migration. "
                "class_id=%s",
                class_id,
            )
            continue

        last_thread_id = 0
        while True:
            threads = await _fetch_v2_voice_threads(
                session,
                class_id=class_id,
                after_id=last_thread_id,
                limit=LOCAL_BATCH_SIZE,
            )
            if not threads:
                break

            logger.info(
                "m20 processing voice thread batch. class_id=%s threads=%s "
                "first_id=%s last_id=%s",
                class_id,
                len(threads),
                threads[0].id,
                threads[-1].id,
            )

            for thread in threads:
                last_thread_id = thread.id
                async with session.begin_nested() as savepoint:
                    try:
                        message_count = await _migrate_thread(
                            session, openai_client, thread
                        )
                        converted_threads += 1
                        converted_messages += message_count
                        if message_count == 0:
                            empty_threads += 1
                    except Exception:
                        await savepoint.rollback()
                        logger.exception(
                            "Could not migrate v2 voice thread. thread_id=%s "
                            "openai_thread_id=%s class_id=%s",
                            thread.id,
                            thread.thread_id,
                            thread.class_id,
                        )
                        failed_threads.append(
                            f"class {thread.class_id} thread {thread.id}"
                        )

                await session.commit()

    logger.info(
        "m20 finished voice thread migration. converted_threads=%s "
        "converted_messages=%s empty_threads=%s failed_threads=%s "
        "skipped_classes=%s",
        converted_threads,
        converted_messages,
        empty_threads,
        len(failed_threads),
        skipped_classes,
    )

    if failed_threads:
        raise RuntimeError(
            f"Failed to migrate {len(failed_threads)} voice thread(s): {failed_threads}"
        )


def _v2_voice_thread_filters() -> tuple[Any, ...]:
    return (
        models.Thread.version == 2,
        models.Thread.interaction_mode == schemas.InteractionMode.VOICE,
    )


async def _count_v2_voice_threads(session: AsyncSession) -> int:
    stmt = (
        select(func.count())
        .select_from(models.Thread)
        .where(*_v2_voice_thread_filters())
    )
    return await session.scalar(stmt) or 0


async def _count_v2_voice_thread_classes(session: AsyncSession) -> int:
    class_ids = (
        select(models.Thread.class_id)
        .where(*_v2_voice_thread_filters())
        .distinct()
        .subquery()
    )
    return await session.scalar(select(func.count()).select_from(class_ids)) or 0


async def _v2_voice_thread_class_ids(session: AsyncSession) -> AsyncIterator[int]:
    last_class_id = 0
    while True:
        stmt = (
            select(models.Thread.class_id)
            .where(
                *_v2_voice_thread_filters(),
                models.Thread.class_id > last_class_id,
            )
            .distinct()
            .order_by(models.Thread.class_id)
            .limit(LOCAL_BATCH_SIZE)
        )
        result = await session.execute(stmt)
        class_ids = list(result.scalars())
        if not class_ids:
            break
        for class_id in class_ids:
            last_class_id = class_id
            yield class_id


async def _fetch_v2_voice_threads(
    session: AsyncSession,
    *,
    class_id: int,
    after_id: int,
    limit: int,
) -> list[models.Thread]:
    stmt = (
        select(models.Thread)
        .options(selectinload(models.Thread.assistant))
        .where(
            *_v2_voice_thread_filters(),
            models.Thread.class_id == class_id,
            models.Thread.id > after_id,
        )
        .order_by(models.Thread.id)
        .limit(limit)
    )
    result = await session.execute(stmt)
    return list(result.scalars())


async def _migrate_thread(
    session: AsyncSession,
    openai_client: OpenAIClient,
    thread: models.Thread,
) -> int:
    openai_messages = await _fetch_openai_messages_in_thread(
        openai_client, thread.thread_id
    )
    logger.info(
        "m20 fetched v2 voice thread messages. class_id=%s thread_id=%s "
        "openai_thread_id=%s openai_message_count=%s",
        thread.class_id,
        thread.id,
        thread.thread_id,
        len(openai_messages),
    )

    if openai_messages:
        run = await _get_or_create_voice_run(session, thread, openai_messages)
        prev_output_index = await _max_output_index(session, thread.id)
        stored_messages = 0
        for openai_message in openai_messages:
            prev_output_index, stored = await _store_message(
                session, thread, run, openai_message, prev_output_index
            )
            if stored:
                stored_messages += 1
    else:
        stored_messages = 0

    thread.version = 3
    session.add(thread)
    await session.flush()
    logger.info(
        "m20 converted v2 voice thread. thread_id=%s fetched_messages=%s "
        "stored_messages=%s",
        thread.id,
        len(openai_messages),
        stored_messages,
    )
    return stored_messages


async def _fetch_openai_messages_in_thread(
    openai_client: OpenAIClient, openai_thread_id: str
) -> list[OpenAIMessage]:
    messages: list[OpenAIMessage] = []
    after: str | Omit = omit

    while True:
        response = await openai_client.beta.threads.messages.list(
            thread_id=openai_thread_id,
            order="asc",
            after=after,
        )
        messages.extend(response.data)
        if not response.has_more or not response.data:
            break
        after = response.data[-1].id

    return messages


async def _get_or_create_voice_run(
    session: AsyncSession,
    thread: models.Thread,
    openai_messages: list[OpenAIMessage],
) -> models.Run:
    existing = await session.scalar(
        select(models.Run)
        .where(models.Run.thread_id == thread.id)
        .order_by(models.Run.id)
        .limit(1)
    )
    if existing is not None:
        return existing

    first_message = openai_messages[0]
    last_message = openai_messages[-1]
    run = models.Run(
        status=schemas.RunStatus.COMPLETED,
        thread_id=thread.id,
        assistant_id=thread.assistant_id,
        model=thread.assistant.model if thread.assistant else None,
        reasoning_effort=(
            thread.assistant.reasoning_effort if thread.assistant else None
        ),
        verbosity=thread.assistant.verbosity if thread.assistant else None,
        temperature=thread.assistant.temperature if thread.assistant else None,
        tools_available=thread.tools_available,
        creator_id=_maybe_extract_user_id(first_message),
        instructions=thread.instructions,
        created=_dt_from_ts(first_message.created_at),
        completed=_dt_from_ts(last_message.completed_at or last_message.created_at),
    )
    session.add(run)
    await session.flush()
    await session.refresh(run)
    return run


async def _max_output_index(session: AsyncSession, thread_id: int) -> int:
    return (
        await session.scalar(
            select(func.coalesce(func.max(models.Message.output_index), -1)).where(
                models.Message.thread_id == thread_id
            )
        )
        or -1
    )


async def _store_message(
    session: AsyncSession,
    thread: models.Thread,
    run: models.Run,
    openai_message: OpenAIMessage,
    prev_output_index: int,
) -> tuple[int, bool]:
    message_id = _message_id(openai_message)
    existing = await models.Message.get_by_openai_message_id(session, message_id)
    if existing is not None:
        return max(prev_output_index, existing.output_index), False

    output_index = _output_index(openai_message, prev_output_index + 1)
    text_parts = _text_parts(openai_message)
    if not text_parts:
        logger.warning(
            "Skipping v2 voice message without text content. thread_id=%s "
            "openai_message_id=%s role=%s",
            thread.id,
            openai_message.id,
            openai_message.role,
        )
        return output_index, False

    role = schemas.MessageRole(openai_message.role)
    message = await models.Message.create(
        session,
        {
            "message_id": message_id,
            "message_status": _map_message_status(openai_message.status),
            "run_id": run.id,
            "thread_id": thread.id,
            "assistant_id": thread.assistant_id
            if role == schemas.MessageRole.ASSISTANT
            else None,
            "output_index": output_index,
            "role": role,
            "user_id": _maybe_extract_user_id(openai_message),
            "message_metadata": _message_metadata(openai_message),
            "created": _dt_from_ts(openai_message.created_at),
            "completed": _dt_from_ts(openai_message.completed_at),
        },
    )

    part_type = (
        schemas.MessagePartType.INPUT_TEXT
        if role == schemas.MessageRole.USER
        else schemas.MessagePartType.OUTPUT_TEXT
    )
    for part_index, text in enumerate(text_parts):
        await models.MessagePart.create(
            session,
            {
                "message_id": message.id,
                "part_index": part_index,
                "type": part_type,
                "text": text,
            },
        )

    logger.info(
        "m20 stored voice message. message_pk=%s message_id=%s thread_id=%s "
        "run_pk=%s role=%s user_id=%s output_index=%s status=%s",
        message.id,
        message.message_id,
        thread.id,
        run.id,
        message.role,
        message.user_id,
        message.output_index,
        message.message_status,
    )
    return output_index, True


def _message_id(openai_message: OpenAIMessage) -> str:
    metadata = openai_message.metadata or {}
    item_id = metadata.get("item_id")
    if isinstance(item_id, str) and item_id:
        return item_id
    return openai_message.id


def _message_metadata(openai_message: OpenAIMessage) -> dict[str, Any]:
    return {
        MIGRATION_KEY: {
            "message": "complete",
            "openai_message_id": openai_message.id,
        },
    }


def _text_parts(openai_message: OpenAIMessage) -> list[str]:
    parts: list[str] = []
    for content in openai_message.content:
        if content.type != "text":
            continue
        text = content.text.value if content.text else None
        if text is not None and text.strip():
            parts.append(text)
    return parts


def _output_index(openai_message: OpenAIMessage, fallback: int) -> int:
    metadata = openai_message.metadata or {}
    raw_output_index = metadata.get("output_index")
    if raw_output_index is None:
        return fallback
    try:
        return int(raw_output_index)
    except (TypeError, ValueError):
        logger.warning(
            "Could not parse v2 voice output_index. openai_message_id=%s "
            "output_index=%r",
            openai_message.id,
            raw_output_index,
        )
        return fallback


def _maybe_extract_user_id(openai_message: OpenAIMessage | None) -> int | None:
    if not openai_message or openai_message.role != "user":
        return None
    metadata = openai_message.metadata or {}
    raw_user_id = metadata.get("user_id")
    if raw_user_id is None:
        return None
    try:
        return int(raw_user_id)
    except (TypeError, ValueError):
        logger.warning(
            "Could not parse v2 voice user_id. openai_message_id=%s user_id=%r",
            openai_message.id,
            raw_user_id,
        )
        return None


def _map_message_status(status: str | None) -> schemas.MessageStatus:
    if status is None:
        return schemas.MessageStatus.COMPLETED
    return schemas.MessageStatus(status)


def _dt_from_ts(timestamp: int | None) -> datetime | None:
    if timestamp is None:
        return None
    return datetime.fromtimestamp(timestamp, tz=timezone.utc)
