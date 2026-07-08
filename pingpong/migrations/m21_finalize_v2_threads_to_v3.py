import logging
from collections.abc import AsyncIterator

from sqlalchemy import and_, exists, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

import pingpong.models as models
import pingpong.schemas as schemas

logger = logging.getLogger(__name__)

LOCAL_BATCH_SIZE = 100
MIGRATION_KEY = "assistants_to_responses_api_thread_migration"


async def finalize_v2_threads_to_v3(session: AsyncSession) -> None:
    """Flip fully migrated v2 chat threads to v3.

    Earlier migration steps keep threads at version 2 while they copy OpenAI-backed
    data into local rows. m15 stores runs, messages, and tool calls in one
    per-thread savepoint, so the message completion marker is the durable m15
    thread-sync signal. This final step only upgrades threads whose migrated
    OpenAI messages also have completed part and attachment backfills.
    """

    logger.info(
        "m21 starting v2 thread finalization. eligible_threads=%s blocked_threads=%s",
        await _count_completely_migrated_v2_threads(session),
        await _count_blocked_v2_threads(session),
    )

    finalized_threads = 0
    async for thread in _completely_migrated_v2_threads(session):
        thread.version = 3
        session.add(thread)
        finalized_threads += 1

        if finalized_threads % LOCAL_BATCH_SIZE == 0:
            await session.commit()

    await session.commit()
    logger.info(
        "m21 finished v2 thread finalization. finalized_threads=%s",
        finalized_threads,
    )


async def revert_finalized_v3_threads_to_v2(session: AsyncSession) -> None:
    """Flip migrated chat threads finalized by m21 back to v2.

    m21 does not add thread-level metadata. The durable rollback signal is the
    Assistants-to-Responses migration metadata written on m15-created local
    messages. To avoid rewriting native v3 traffic, this only reverts v3 chat
    threads that have migrated messages and no non-migrated local messages.
    """

    logger.info(
        "m21 starting v3 thread finalization revert. revertible_threads=%s "
        "blocked_threads=%s",
        await _count_revertible_finalized_v3_threads(session),
        await _count_mixed_finalized_v3_threads(session),
    )

    reverted_threads = 0
    async for thread in _revertible_finalized_v3_threads(session):
        thread.version = 2
        session.add(thread)
        reverted_threads += 1

        if reverted_threads % LOCAL_BATCH_SIZE == 0:
            await session.commit()

    await session.commit()
    logger.info(
        "m21 finished v3 thread finalization revert. reverted_threads=%s",
        reverted_threads,
    )


def _migration_metadata():
    return models.Message.message_metadata[MIGRATION_KEY]


def _message_has_migration_metadata():
    migration_metadata = _migration_metadata()
    message_state = migration_metadata["message"].as_string()
    return (
        models.Message.thread_id == models.Thread.id,
        models.Message.message_id.is_not(None),
        message_state == "complete",
    )


def _message_lacks_migration_metadata():
    migration_metadata = _migration_metadata()
    message_state = migration_metadata["message"].as_string()
    return (
        models.Message.thread_id == models.Thread.id,
        or_(
            models.Message.message_id.is_(None),
            message_state.is_(None),
            message_state != "complete",
        ),
    )


def _migrated_message_filters():
    return _message_has_migration_metadata()


def _incomplete_migrated_message_filters():
    migration_metadata = _migration_metadata()
    message_state = migration_metadata["message"].as_string()
    message_parts_state = migration_metadata["message_parts"].as_string()
    attachments_state = migration_metadata["attachments"].as_string()
    return (
        models.Message.thread_id == models.Thread.id,
        models.Message.message_id.is_not(None),
        or_(
            message_state.is_(None),
            message_state != "complete",
            message_parts_state.is_(None),
            message_parts_state != "complete",
            and_(
                models.Message.role == schemas.MessageRole.USER,
                or_(attachments_state.is_(None), attachments_state != "complete"),
            ),
        ),
    )


def _completely_migrated_v2_thread_filters():
    has_migrated_message = exists(
        select(models.Message.id).where(*_migrated_message_filters())
    )
    has_incomplete_migrated_message = exists(
        select(models.Message.id).where(*_incomplete_migrated_message_filters())
    )
    return (
        models.Thread.version == 2,
        models.Thread.interaction_mode == schemas.InteractionMode.CHAT,
        has_migrated_message,
        ~has_incomplete_migrated_message,
    )


def _revertible_finalized_v3_thread_filters():
    has_migrated_message = exists(
        select(models.Message.id).where(*_message_has_migration_metadata())
    )
    has_non_migrated_message = exists(
        select(models.Message.id).where(*_message_lacks_migration_metadata())
    )
    return (
        models.Thread.version == 3,
        models.Thread.interaction_mode == schemas.InteractionMode.CHAT,
        has_migrated_message,
        ~has_non_migrated_message,
    )


def _mixed_finalized_v3_thread_filters():
    has_migrated_message = exists(
        select(models.Message.id).where(*_message_has_migration_metadata())
    )
    has_non_migrated_message = exists(
        select(models.Message.id).where(*_message_lacks_migration_metadata())
    )
    return (
        models.Thread.version == 3,
        models.Thread.interaction_mode == schemas.InteractionMode.CHAT,
        has_migrated_message,
        has_non_migrated_message,
    )


async def _count_completely_migrated_v2_threads(session: AsyncSession) -> int:
    stmt = (
        select(func.count())
        .select_from(models.Thread)
        .where(*_completely_migrated_v2_thread_filters())
    )
    return await session.scalar(stmt) or 0


async def _count_revertible_finalized_v3_threads(session: AsyncSession) -> int:
    stmt = (
        select(func.count())
        .select_from(models.Thread)
        .where(*_revertible_finalized_v3_thread_filters())
    )
    return await session.scalar(stmt) or 0


async def _count_mixed_finalized_v3_threads(session: AsyncSession) -> int:
    stmt = (
        select(func.count())
        .select_from(models.Thread)
        .where(*_mixed_finalized_v3_thread_filters())
    )
    return await session.scalar(stmt) or 0


async def _count_blocked_v2_threads(session: AsyncSession) -> int:
    has_migrated_message = exists(
        select(models.Message.id).where(*_migrated_message_filters())
    )
    has_incomplete_migrated_message = exists(
        select(models.Message.id).where(*_incomplete_migrated_message_filters())
    )
    stmt = (
        select(func.count())
        .select_from(models.Thread)
        .where(
            models.Thread.version == 2,
            models.Thread.interaction_mode == schemas.InteractionMode.CHAT,
            has_migrated_message,
            has_incomplete_migrated_message,
        )
    )
    return await session.scalar(stmt) or 0


async def _fetch_completely_migrated_v2_threads(
    session: AsyncSession,
    *,
    after_id: int,
    limit: int,
) -> list[models.Thread]:
    stmt = (
        select(models.Thread)
        .where(
            *_completely_migrated_v2_thread_filters(),
            models.Thread.id > after_id,
        )
        .order_by(models.Thread.id)
        .limit(limit)
    )
    result = await session.execute(stmt)
    return list(result.scalars())


async def _fetch_revertible_finalized_v3_threads(
    session: AsyncSession,
    *,
    after_id: int,
    limit: int,
) -> list[models.Thread]:
    stmt = (
        select(models.Thread)
        .where(
            *_revertible_finalized_v3_thread_filters(),
            models.Thread.id > after_id,
        )
        .order_by(models.Thread.id)
        .limit(limit)
    )
    result = await session.execute(stmt)
    return list(result.scalars())


async def _completely_migrated_v2_threads(
    session: AsyncSession,
) -> AsyncIterator[models.Thread]:
    last_thread_id = 0
    while True:
        threads = await _fetch_completely_migrated_v2_threads(
            session,
            after_id=last_thread_id,
            limit=LOCAL_BATCH_SIZE,
        )
        if not threads:
            break

        for thread in threads:
            last_thread_id = thread.id
            yield thread


async def _revertible_finalized_v3_threads(
    session: AsyncSession,
) -> AsyncIterator[models.Thread]:
    last_thread_id = 0
    while True:
        threads = await _fetch_revertible_finalized_v3_threads(
            session,
            after_id=last_thread_id,
            limit=LOCAL_BATCH_SIZE,
        )
        if not threads:
            break

        for thread in threads:
            last_thread_id = thread.id
            yield thread
