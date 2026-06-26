import logging
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass
from datetime import datetime, timezone
from itertools import groupby

from openai import Omit, omit
from openai.types.beta.threads import Message, Run
from sqlalchemy import delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

import pingpong.models as models
from pingpong.ai import get_openai_client_by_class_id
from pingpong.schemas import InteractionMode, MessageRole, MessageStatus, RunStatus
from pingpong.server import OpenAIClient

logger = logging.getLogger(__name__)

LOCAL_BATCH_SIZE = 100


async def migrate_threads_and_messages_to_v3(session: AsyncSession) -> None:
    """
    Step 1 in multi-step migration from the Assistants API-based interactions with
    OpenAI and those based on the Responses API. In v2, most objects were stored in
    OpenAI's datastores rather than in our own. In this first step, we fetch all v2
    threads and messages in those threads and create local copies of those two types
    of objects.
    NOTE: this migration does not cover persisting objects other than `models.Thread`
    and `models.Message`. Future migrations will handle creation message parts,
    attachments, tool calls, and annotations.
    """
    logger.info(
        "m15 starting thread/message migration. classes=%s assistants=%s",
        await _count_v2_thread_classes(session),
        await _count_assistants_with_v2_threads(session),
    )

    failed_threads: list[str] = []
    async for class_id in _v2_thread_class_ids(session):
        try:
            openai_client = await get_openai_client_by_class_id(session, class_id)
        except Exception as e:
            logger.warning(
                f"Could not get OpenAI client for class {class_id}: {e} — skipping"
            )
            continue

        async for assistant in _assistants_with_v2_threads(session, class_id):
            async for thread in _v2_threads_for_assistant(session, assistant.id):
                # Keep each OpenAI-backed thread sync isolated. _migrate_thread may
                # flush several local rows before a later OpenAI request fails, so the
                # savepoint lets us undo only this thread's partial work.
                async with session.begin_nested() as savepoint:
                    try:
                        await _migrate_thread(session, openai_client, thread, assistant)
                        # NOTE: we deliberately keep thread versions as `2` for now since
                        # we are not ready to have the client interpret these objects as v3
                        # threads
                    except Exception:
                        await savepoint.rollback()
                        logger.exception(
                            f"Could not migrate thread {thread.id} "
                            f"for assistant {assistant.id}"
                        )
                        failed_threads.append(
                            f"class {class_id} assistant {assistant.id} thread {thread.id}"
                        )
            # Commit the successful threads for this assistant even if another thread
            # failed and was rolled back to its savepoint.
            await session.commit()

    if failed_threads:
        # Surface the incomplete migration to the operator after preserving all
        # successful thread work. The migration is rerunnable, so failed thread IDs can
        # be retried after the underlying OpenAI/API issue is fixed.
        raise RuntimeError(
            f"Failed to migrate {len(failed_threads)} thread(s): {failed_threads}"
        )


async def _count_v2_thread_classes(session: AsyncSession) -> int:
    class_ids = (
        select(models.Assistant.class_id)
        .join(models.Thread, models.Thread.assistant_id == models.Assistant.id)
        .where(
            models.Thread.version == 2,
            models.Thread.interaction_mode == InteractionMode.CHAT,
        )
        .distinct()
        .subquery()
    )
    return await session.scalar(select(func.count()).select_from(class_ids)) or 0


async def _count_assistants_with_v2_threads(session: AsyncSession) -> int:
    assistant_ids = (
        select(models.Assistant.id)
        .join(models.Thread, models.Thread.assistant_id == models.Assistant.id)
        .where(
            models.Thread.version == 2,
            models.Thread.interaction_mode == InteractionMode.CHAT,
        )
        .distinct()
        .subquery()
    )
    return await session.scalar(select(func.count()).select_from(assistant_ids)) or 0


async def _v2_thread_class_ids(session: AsyncSession) -> AsyncIterator[int]:
    last_class_id = 0
    while True:
        stmt = (
            select(models.Assistant.class_id)
            .join(models.Thread, models.Thread.assistant_id == models.Assistant.id)
            .where(
                models.Thread.version == 2,
                models.Thread.interaction_mode == InteractionMode.CHAT,
                models.Assistant.class_id > last_class_id,
            )
            .distinct()
            .order_by(models.Assistant.class_id)
            .limit(LOCAL_BATCH_SIZE)
        )
        result = await session.execute(stmt)
        class_ids = list(result.scalars())
        if not class_ids:
            break
        for class_id in class_ids:
            last_class_id = class_id
            yield class_id


async def _assistants_with_v2_threads(
    session: AsyncSession, class_id: int
) -> AsyncIterator[models.Assistant]:
    last_assistant_id = 0
    while True:
        # Any assistant (any version) owning a v2 chat thread; distinct per assistant.
        stmt = (
            select(models.Assistant)
            .join(models.Thread, models.Thread.assistant_id == models.Assistant.id)
            .where(
                models.Assistant.id > last_assistant_id,
                models.Assistant.class_id == class_id,
                models.Thread.version == 2,
                models.Thread.interaction_mode == InteractionMode.CHAT,
            )
            .distinct()
            .order_by(models.Assistant.id)
            .limit(LOCAL_BATCH_SIZE)
        )
        result = await session.execute(stmt)
        assistants = list(result.scalars())
        if not assistants:
            break
        for assistant in assistants:
            last_assistant_id = assistant.id
            yield assistant


async def _fetch_threads_for_assistant_batch(
    session: AsyncSession, assistant_id: int, after_id: int
) -> list[models.Thread]:
    stmt = (
        select(models.Thread)
        .where(
            models.Thread.id > after_id,
            models.Thread.assistant_id == assistant_id,
            models.Thread.version == 2,
            models.Thread.interaction_mode == InteractionMode.CHAT,
        )
        .order_by(models.Thread.id)
        .limit(LOCAL_BATCH_SIZE)
    )
    result = await session.execute(stmt)
    return list(result.scalars())


async def _v2_threads_for_assistant(
    session: AsyncSession, assistant_id: int
) -> AsyncIterator[models.Thread]:
    last_thread_id = 0
    while True:
        threads = await _fetch_threads_for_assistant_batch(
            session, assistant_id, last_thread_id
        )
        if not threads:
            break
        for thread in threads:
            last_thread_id = thread.id
            yield thread


@dataclass
class MigrationTurn:
    user_message: Message | None
    assistant_messages: list[Message]
    openai_runs: list[Run]

    @classmethod
    def orphan(cls, user_message: Message) -> "MigrationTurn":
        return cls(user_message=user_message, assistant_messages=[], openai_runs=[])

    def messages(self) -> Iterator[Message]:
        if self.user_message is not None:
            yield self.user_message
        yield from self.assistant_messages


def _require_dt(timestamp: int) -> datetime:
    return datetime.fromtimestamp(timestamp, tz=timezone.utc)


def _dt_from_ts(timestamp: int | None) -> datetime | None:
    if timestamp is None:
        return None
    return _require_dt(timestamp)


def _terminal_run_completed_at(openai_run: Run) -> datetime | None:
    if openai_run.status == "expired":
        return _dt_from_ts(openai_run.expires_at)

    return _dt_from_ts(
        openai_run.completed_at or openai_run.failed_at or openai_run.cancelled_at
    )


def _collapsed_run_started_at(turn: MigrationTurn) -> datetime:
    if turn.user_message is not None:
        return _require_dt(turn.user_message.created_at)

    first_run = turn.openai_runs[0]
    return _require_dt(first_run.started_at or first_run.created_at)


async def _resolve_run(
    openai_client: OpenAIClient,
    thread: models.Thread,
    run_id: str,
    cache: dict[str, Run],
) -> Run:
    run = cache.get(run_id)
    if run is None:
        run = await openai_client.beta.threads.runs.retrieve(
            run_id,
            thread_id=thread.thread_id,
        )
        cache[run_id] = run
    return run


async def _iter_migration_turns(
    openai_client: OpenAIClient,
    thread: models.Thread,
    openai_messages: list[Message],
) -> AsyncIterator[MigrationTurn]:
    run_cache: dict[str, Run] = {}
    pending_owner: Message | None = None

    for is_assistant, group in groupby(
        openai_messages, key=lambda m: m.role == "assistant"
    ):
        messages = list(group)

        if not is_assistant:
            # A run of non-assistant messages: every message but the last is an
            # orphan turn; the last is held as the owner of the next assistant run.
            *orphans, pending_owner = messages
            for orphan in orphans:
                yield MigrationTurn.orphan(orphan)
            continue

        openai_runs = [
            await _resolve_run(openai_client, thread, m.run_id, run_cache)
            for m in messages
            if m.run_id is not None
        ]
        yield MigrationTurn(
            user_message=pending_owner,
            assistant_messages=messages,
            openai_runs=openai_runs,
        )
        pending_owner = None

    if pending_owner is not None:
        yield MigrationTurn.orphan(pending_owner)


async def _migrate_thread(
    session: AsyncSession,
    openai_client: OpenAIClient,
    thread: models.Thread,
    assistant: models.Assistant,
) -> None:
    """Sync the thread's local runs/messages to current OpenAI state: upsert
    everything OpenAI reports, delete local rows that no longer exist upstream."""
    openai_messages = await _fetch_openai_messages_in_thread(
        openai_client,
        thread.thread_id,
    )
    logger.info(
        "m15 fetched thread messages. class_id=%s assistant_id=%s thread_id=%s "
        "openai_thread_id=%s openai_message_count=%s",
        thread.class_id,
        assistant.id,
        thread.id,
        thread.thread_id,
        len(openai_messages),
    )

    prev_output_index = -1

    async for turn in _iter_migration_turns(openai_client, thread, openai_messages):
        local_run = await _store_turn_run(session, thread, assistant, turn)
        for message in turn.messages():
            prev_output_index = await _store_message(
                session,
                thread,
                message,
                local_run,
                prev_output_index,
            )

    deleted_stale_messages = await _delete_stale_messages(
        session, thread, openai_messages
    )
    pruned_orphan_runs = await _prune_orphan_runs(session, thread)
    logger.info(
        "m15 cleaned thread. thread_id=%s stale_messages_deleted=%s "
        "orphan_runs_deleted=%s",
        thread.id,
        deleted_stale_messages,
        pruned_orphan_runs,
    )

    session.add(thread)
    await session.flush()


async def _fetch_openai_messages_in_thread(
    openai_client: OpenAIClient, openai_thread_id: str
) -> list[Message]:
    messages: list[Message] = []
    after: str | Omit = omit

    while True:
        response = await openai_client.beta.threads.messages.list(
            thread_id=openai_thread_id, order="asc", after=after
        )
        messages.extend(response.data)
        if not response.has_more or not response.data:
            break

        after = response.data[-1].id

    return messages


async def _delete_stale_messages(
    session: AsyncSession,
    thread: models.Thread,
    openai_messages: list[Message],
) -> int:
    """Delete local messages no longer present upstream (empty fetch clears all)."""
    keep_ids = [m.id for m in openai_messages]
    stmt = delete(models.Message).where(models.Message.thread_id == thread.id)
    if keep_ids:
        stmt = stmt.where(
            or_(
                models.Message.message_id.is_(None),
                models.Message.message_id.not_in(keep_ids),
            )
        )
    result = await session.execute(stmt)
    await session.flush()
    return _rowcount(result.rowcount)


async def _prune_orphan_runs(session: AsyncSession, thread: models.Thread) -> int:
    """Delete runs in this thread no message points to (placeholder/duplicate debris)."""
    orphan_run_ids = (
        select(models.Run.id)
        .outerjoin(models.Message, models.Message.run_id == models.Run.id)
        .where(models.Run.thread_id == thread.id, models.Message.id.is_(None))
    )
    result = await session.execute(
        delete(models.Run).where(models.Run.id.in_(orphan_run_ids))
    )
    await session.flush()
    return _rowcount(result.rowcount)


def _rowcount(rowcount: int | None) -> int:
    if rowcount is None or rowcount < 0:
        return 0
    return rowcount


async def _store_turn_run(
    session: AsyncSession,
    thread: models.Thread,
    assistant: models.Assistant,
    turn: MigrationTurn,
) -> models.Run:
    if turn.openai_runs:
        fields = _openai_run_fields(
            turn.openai_runs[-1], created=_collapsed_run_started_at(turn)
        )
    else:
        placeholder = turn.user_message or turn.assistant_messages[0]
        fields = _placeholder_run_fields(placeholder)

    existing_run = await _find_existing_turn_run(session, turn)
    return await _upsert_run(
        session,
        thread,
        assistant,
        turn.user_message,
        existing_run,
        fields,
        turn_message_count=sum(1 for _ in turn.messages()),
    )


async def _find_existing_turn_run(
    session: AsyncSession, turn: MigrationTurn
) -> models.Run | None:
    """Find this turn's existing run: by unique run_id for real runs, else via an
    already-stored message (which also upgrades a placeholder run in place)."""
    if turn.openai_runs:
        by_run_id = await models.Run.get_by_openai_run_id(
            session, turn.openai_runs[-1].id
        )
        if by_run_id is not None:
            return by_run_id

    for message in turn.messages():
        stored = await models.Message.get_by_openai_message_id(session, message.id)
        if stored is not None:
            return await session.get(models.Run, stored.run_id)
    return None


async def _upsert_run(
    session: AsyncSession,
    thread: models.Thread,
    assistant: models.Assistant,
    openai_message: Message | None,
    run: models.Run | None,
    fields: dict,
    *,
    turn_message_count: int,
) -> models.Run:
    values = dict(
        thread_id=thread.id,
        assistant_id=assistant.id,
        creator_id=_maybe_extract_user_id(openai_message),
        model=assistant.model,
        temperature=assistant.temperature,
        instructions=thread.instructions,
        tools_available=thread.tools_available,
        reasoning_effort=assistant.reasoning_effort,
        verbosity=assistant.verbosity,
        **fields,
    )
    if run is None:
        action = "created"
        run = models.Run(**values)
        session.add(run)
    else:
        action = "updated"
        for key, value in values.items():
            setattr(run, key, value)
    await session.flush()
    await session.refresh(run)
    logger.info(
        "m15 stored run. thread_id=%s run_pk=%s openai_run_id=%s action=%s "
        "status=%s creator_id=%s turn_messages=%s",
        thread.id,
        run.id,
        run.run_id,
        action,
        run.status,
        run.creator_id,
        turn_message_count,
    )
    return run


def _map_run_status(openai_status: str) -> RunStatus:
    override = {
        "requires_action": RunStatus.IN_PROGRESS,
        "cancelling": RunStatus.INCOMPLETE,
        "cancelled": RunStatus.INCOMPLETE,
        "expired": RunStatus.INCOMPLETE,
    }.get(openai_status)
    if override is not None:
        return override
    return RunStatus(openai_status)


def _map_message_status(openai_status: str | None) -> MessageStatus:
    if openai_status is None:
        return MessageStatus.COMPLETED

    return MessageStatus(openai_status)


def _openai_run_fields(openai_run: Run, *, created: datetime) -> dict:
    return dict(
        run_id=openai_run.id,
        status=_map_run_status(openai_run.status),
        error_code=openai_run.last_error and openai_run.last_error.code,
        error_message=openai_run.last_error and openai_run.last_error.message,
        incomplete_reason=(
            openai_run.incomplete_details and openai_run.incomplete_details.reason
        ),
        created=created,
        completed=_terminal_run_completed_at(openai_run),
    )


def _placeholder_run_fields(openai_message: Message) -> dict:
    return dict(
        run_id=None,
        status=RunStatus.INCOMPLETE,
        created=_dt_from_ts(openai_message.created_at),
        completed=None,
    )


async def _store_message(
    session: AsyncSession,
    thread: models.Thread,
    openai_message: Message,
    local_run: models.Run,
    prev_output_index: int,
) -> int:
    prev_output_index += 1
    fields = {
        "message_metadata": {
            "assistants_to_responses_api_thread_migration": {
                "message": "complete",
            }
        },
        "message_status": _map_message_status(openai_message.status),
        "role": MessageRole(openai_message.role),
        "created": _require_dt(openai_message.created_at),
        "completed": _dt_from_ts(openai_message.completed_at),
        "thread_id": thread.id,
        "run_id": local_run.id,
        "assistant_id": (
            thread.assistant_id if openai_message.role == "assistant" else None
        ),
        "user_id": _maybe_extract_user_id(openai_message),
        "output_index": prev_output_index,
    }

    existing = await models.Message.get_by_openai_message_id(session, openai_message.id)
    if existing is None:
        action = "created"
        local_message = await models.Message.create(
            session,
            {
                "message_id": openai_message.id,
                **fields,
            },
        )
    else:
        action = "updated"
        for key, value in fields.items():
            setattr(existing, key, value)
        await session.flush()
        local_message = existing
    logger.info(
        "m15 stored message. message_pk=%s openai_message_id=%s thread_id=%s "
        "run_pk=%s action=%s role=%s user_id=%s output_index=%s status=%s",
        local_message.id,
        openai_message.id,
        thread.id,
        local_run.id,
        action,
        local_message.role,
        local_message.user_id,
        local_message.output_index,
        local_message.message_status,
    )

    return prev_output_index


def _maybe_extract_user_id(openai_message: Message | None) -> int | None:
    if not openai_message or openai_message.role != "user":
        return None
    metadata = openai_message.metadata or {}
    raw_user_id = metadata.get("user_id")
    if raw_user_id is None:
        logger.warning(
            f"Couldn't get user_id from OpenAI message with id {openai_message.id}"
        )
        return None
    try:
        return int(raw_user_id)
    except (ValueError, TypeError):
        logger.warning(
            f"Couldn't get user_id from OpenAI message with id {openai_message.id} "
            "because it couldn't be converted to an integer"
        )
        return None
