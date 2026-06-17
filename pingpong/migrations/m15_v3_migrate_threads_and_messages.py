import logging
from collections.abc import AsyncIterator, Iterator
from dataclasses import dataclass
from datetime import datetime, timezone
from itertools import groupby

from openai import Omit, omit
from openai.types.beta.threads import Message, Run
from sqlalchemy import delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

import pingpong.models as models
from pingpong.ai import get_openai_client_by_class_id
from pingpong.schemas import InteractionMode, MessageRole, MessageStatus, RunStatus
from pingpong.server import OpenAIClient

logger = logging.getLogger(__name__)


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
    # Drive off assistants that own a v2 chat thread (any assistant version), so
    # the OpenAI client is resolved once per class, not once per thread.
    assistants_by_class: dict[int, list[models.Assistant]] = {}
    for assistant in await _assistants_with_v2_threads(session):
        assistants_by_class.setdefault(assistant.class_id, []).append(assistant)

    for class_id, assistants in assistants_by_class.items():
        try:
            openai_client = await get_openai_client_by_class_id(session, class_id)
        except Exception as e:
            logger.warning(
                f"Could not get OpenAI client for class {class_id}: {e} — skipping"
            )
            continue

        for assistant in assistants:
            async for thread in _v2_threads_for_assistant(session, assistant.id):
                await _migrate_thread(session, openai_client, thread, assistant)
                # NOTE: we deliberately keep thread versions as `2` for now since we
                # are not ready to have the client interpret these objects as v3 threads
            await session.commit()


async def _assistants_with_v2_threads(
    session: AsyncSession,
) -> list[models.Assistant]:
    # Any assistant (any version) owning a v2 chat thread; distinct per assistant.
    stmt = (
        select(models.Assistant)
        .join(models.Thread, models.Thread.assistant_id == models.Assistant.id)
        .where(
            models.Thread.version == 2,
            models.Thread.interaction_mode == InteractionMode.CHAT,
        )
        .distinct()
    )
    result = await session.execute(stmt)
    return list(result.scalars())


async def _v2_threads_for_assistant(
    session: AsyncSession, assistant_id: int
) -> AsyncIterator[models.Thread]:
    stmt = select(models.Thread).where(
        models.Thread.assistant_id == assistant_id,
        models.Thread.version == 2,
        models.Thread.interaction_mode == InteractionMode.CHAT,
    )
    result = await session.execute(stmt)
    for thread in result.scalars():
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

    await _delete_stale_messages(session, thread, openai_messages)
    await _prune_orphan_runs(session, thread)

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
) -> None:
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
    await session.execute(stmt)
    await session.flush()


async def _prune_orphan_runs(session: AsyncSession, thread: models.Thread) -> None:
    """Delete runs in this thread no message points to (placeholder/duplicate debris)."""
    orphan_run_ids = (
        select(models.Run.id)
        .outerjoin(models.Message, models.Message.run_id == models.Run.id)
        .where(models.Run.thread_id == thread.id, models.Message.id.is_(None))
    )
    await session.execute(delete(models.Run).where(models.Run.id.in_(orphan_run_ids)))
    await session.flush()


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
        session, thread, assistant, turn.user_message, existing_run, fields
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
        run = models.Run(**values)
        session.add(run)
    else:
        for key, value in values.items():
            setattr(run, key, value)
    await session.flush()
    await session.refresh(run)
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
        "message_status": MessageStatus(openai_message.status),
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
        await models.Message.create(
            session,
            {
                "message_id": openai_message.id,
                **fields,
            },
        )
    else:
        for key, value in fields.items():
            setattr(existing, key, value)
        await session.flush()

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
