import asyncio
import logging
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from openai.types.beta.threads import Message as OpenAIMessage
from openai.types.beta.threads.runs import (
    CodeInterpreterToolCall,
    FileSearchToolCall,
    MessageCreationStepDetails,
    ToolCallsStepDetails,
)
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

import pingpong.models as models
import pingpong.schemas as schemas
from pingpong.ai import get_openai_client_by_class_id
from pingpong.migrations import m15_v3_migrate_threads_and_messages as m15
from pingpong.migrations.m21_finalize_v2_threads_to_v3 import (
    MIGRATION_KEY,
    _completely_migrated_v2_thread_filters,
)
from pingpong.server import OpenAIClient

logger = logging.getLogger(__name__)

LOCAL_BATCH_SIZE = 100


@dataclass(frozen=True)
class VerificationIssue:
    code: str
    detail: str


@dataclass
class ThreadVerificationResult:
    thread_id: int
    openai_thread_id: str
    issues: list[VerificationIssue] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return not self.issues


@dataclass
class VerificationSummary:
    selected_threads: int
    checked_threads: int = 0
    passed_threads: int = 0
    failed_threads: int = 0
    issue_counts: Counter[str] = field(default_factory=Counter)
    failed_thread_ids: list[int] = field(default_factory=list)


@dataclass(frozen=True)
class ExpectedRun:
    sequence: int
    message_ids: tuple[str, ...]
    run_id: str | None
    status: schemas.RunStatus
    created: datetime
    completed: datetime | None
    creator_message_id: str | None
    error_code: str | None
    error_message: str | None
    incomplete_reason: str | None


@dataclass(frozen=True)
class ExpectedToolCall:
    run_sequence: int
    tool_call_id: str
    type: schemas.ToolCallType
    status: schemas.ToolCallStatus
    output_index: int
    created: datetime
    completed: datetime | None
    code: str | None = None
    outputs: tuple[tuple[Any, ...], ...] = ()
    results: tuple[tuple[Any, ...], ...] = ()
    source_unavailable: bool = False


class _OpenAIClientCache:
    def __init__(self, *, max_retries: int) -> None:
        self._lock = asyncio.Lock()
        self._clients: dict[int, asyncio.Task[OpenAIClient]] = {}
        self._max_retries = max_retries

    async def _create_client(
        self, session: AsyncSession, class_id: int
    ) -> OpenAIClient:
        client = await get_openai_client_by_class_id(session, class_id)
        # The SDK retries the individual failed request and honors Retry-After. Doing
        # this at the client boundary avoids replaying all earlier calls for a thread.
        return client.with_options(max_retries=self._max_retries)

    async def get(self, session: AsyncSession, class_id: int) -> OpenAIClient:
        async with self._lock:
            task = self._clients.get(class_id)
            if task is None:
                task = asyncio.create_task(self._create_client(session, class_id))
                self._clients[class_id] = task
        return await task


async def check_v2_threads_to_v3(
    db_driver,
    *,
    concurrency: int = 8,
    openai_max_retries: int = 5,
    shard_count: int = 1,
    shard_index: int = 0,
    limit: int | None = None,
) -> VerificationSummary:
    """Compare every m21-eligible thread in one shard with its OpenAI source.

    The checker is read-only. Multiple processes can safely run it when each uses a
    distinct ``shard_index`` for the same ``shard_count``. Within one process, every
    worker owns a separate AsyncSession because AsyncSession is not task-safe.
    """

    if concurrency < 1:
        raise ValueError("concurrency must be at least 1")
    if openai_max_retries < 0:
        raise ValueError("openai_max_retries cannot be negative")
    if shard_count < 1:
        raise ValueError("shard_count must be at least 1")
    if not 0 <= shard_index < shard_count:
        raise ValueError("shard_index must be between 0 and shard_count - 1")
    if limit is not None and limit < 1:
        raise ValueError("limit must be at least 1")

    async with db_driver.async_session() as session:
        selected_threads = await _count_candidate_threads(
            session, shard_count=shard_count, shard_index=shard_index
        )
    if limit is not None:
        selected_threads = min(selected_threads, limit)

    summary = VerificationSummary(selected_threads=selected_threads)
    logger.info(
        "m21 check starting. selected_threads=%s concurrency=%s "
        "openai_max_retries=%s shard=%s/%s limit=%s",
        selected_threads,
        concurrency,
        openai_max_retries,
        shard_index,
        shard_count,
        limit,
    )

    queue: asyncio.Queue[tuple[int, int, str] | None] = asyncio.Queue(
        maxsize=concurrency * 2
    )
    client_cache = _OpenAIClientCache(max_retries=openai_max_retries)
    summary_lock = asyncio.Lock()

    async def worker(worker_index: int) -> None:
        async with db_driver.async_session() as session:
            while True:
                candidate = await queue.get()
                try:
                    if candidate is None:
                        return
                    thread_id, class_id, openai_thread_id = candidate
                    try:
                        client = await client_cache.get(session, class_id)
                        result = await _check_thread(session, client, thread_id)
                    except Exception as exc:
                        logger.exception(
                            "m21 check could not verify thread. thread_id=%s "
                            "openai_thread_id=%s worker=%s",
                            thread_id,
                            openai_thread_id,
                            worker_index,
                        )
                        result = ThreadVerificationResult(
                            thread_id=thread_id,
                            openai_thread_id=openai_thread_id,
                            issues=[
                                VerificationIssue(
                                    "verification_error",
                                    f"{type(exc).__name__}: {exc}",
                                )
                            ],
                        )

                    await session.rollback()
                    await _record_result(summary, summary_lock, result)
                finally:
                    queue.task_done()

    workers = [asyncio.create_task(worker(i)) for i in range(concurrency)]
    try:
        produced = 0
        async with db_driver.async_session() as session:
            after_id = 0
            while limit is None or produced < limit:
                batch_limit = min(
                    LOCAL_BATCH_SIZE,
                    (limit - produced) if limit is not None else LOCAL_BATCH_SIZE,
                )
                candidates = await _fetch_candidate_threads(
                    session,
                    after_id=after_id,
                    limit=batch_limit,
                    shard_count=shard_count,
                    shard_index=shard_index,
                )
                await session.rollback()
                if not candidates:
                    break
                for thread_id, class_id, openai_thread_id in candidates:
                    after_id = thread_id
                    await queue.put((thread_id, class_id, openai_thread_id))
                    produced += 1
        for _ in workers:
            await queue.put(None)
        await queue.join()
        await asyncio.gather(*workers)
    except BaseException:
        for task in workers:
            task.cancel()
        await asyncio.gather(*workers, return_exceptions=True)
        raise

    logger.info(
        "m21 check finished. selected_threads=%s checked_threads=%s "
        "passed_threads=%s failed_threads=%s issue_counts=%s",
        summary.selected_threads,
        summary.checked_threads,
        summary.passed_threads,
        summary.failed_threads,
        dict(summary.issue_counts),
    )
    return summary


async def _record_result(
    summary: VerificationSummary,
    lock: asyncio.Lock,
    result: ThreadVerificationResult,
) -> None:
    if result.passed:
        logger.info(
            "m21 check passed thread. thread_id=%s openai_thread_id=%s",
            result.thread_id,
            result.openai_thread_id,
        )
    else:
        for issue in result.issues:
            logger.error(
                "m21 check mismatch. thread_id=%s openai_thread_id=%s code=%s "
                "detail=%s",
                result.thread_id,
                result.openai_thread_id,
                issue.code,
                issue.detail,
            )

    async with lock:
        summary.checked_threads += 1
        if result.passed:
            summary.passed_threads += 1
        else:
            summary.failed_threads += 1
            summary.failed_thread_ids.append(result.thread_id)
            summary.issue_counts.update(issue.code for issue in result.issues)


def _candidate_filters(*, shard_count: int, shard_index: int) -> tuple:
    filters = _completely_migrated_v2_thread_filters()
    if shard_count == 1:
        return filters
    return (*filters, models.Thread.id % shard_count == shard_index)


async def _count_candidate_threads(
    session: AsyncSession, *, shard_count: int, shard_index: int
) -> int:
    stmt = (
        select(func.count())
        .select_from(models.Thread)
        .where(*_candidate_filters(shard_count=shard_count, shard_index=shard_index))
    )
    return await session.scalar(stmt) or 0


async def _fetch_candidate_threads(
    session: AsyncSession,
    *,
    after_id: int,
    limit: int,
    shard_count: int,
    shard_index: int,
) -> list[tuple[int, int, str]]:
    stmt = (
        select(models.Thread.id, models.Thread.class_id, models.Thread.thread_id)
        .where(
            *_candidate_filters(shard_count=shard_count, shard_index=shard_index),
            models.Thread.id > after_id,
        )
        .order_by(models.Thread.id)
        .limit(limit)
    )
    rows = (await session.execute(stmt)).all()
    return [(int(row.id), int(row.class_id), str(row.thread_id)) for row in rows]


async def _load_thread(session: AsyncSession, thread_id: int) -> models.Thread | None:
    stmt = (
        select(models.Thread)
        .where(models.Thread.id == thread_id)
        .options(
            selectinload(models.Thread.messages)
            .selectinload(models.Message.content)
            .selectinload(models.MessagePart.annotations),
            selectinload(models.Thread.messages).selectinload(
                models.Message.file_search_attachments
            ),
            selectinload(models.Thread.messages).selectinload(
                models.Message.code_interpreter_attachments
            ),
            selectinload(models.Thread.runs),
            selectinload(models.Thread.tool_calls).selectinload(
                models.ToolCall.outputs
            ),
            selectinload(models.Thread.tool_calls).selectinload(
                models.ToolCall.results
            ),
        )
    )
    return await session.scalar(stmt)


async def _load_thread_header(session: AsyncSession, thread_id: int):
    stmt = select(
        models.Thread.id,
        models.Thread.thread_id,
        models.Thread.assistant_id,
        models.Thread.version,
        models.Thread.interaction_mode,
    ).where(models.Thread.id == thread_id)
    return (await session.execute(stmt)).one_or_none()


async def _check_thread(
    session: AsyncSession, client: OpenAIClient, thread_id: int
) -> ThreadVerificationResult:
    header = await _load_thread_header(session, thread_id)
    await session.rollback()
    if header is None:
        return ThreadVerificationResult(
            thread_id=thread_id,
            openai_thread_id="",
            issues=[VerificationIssue("thread_missing", "local thread no longer exists")],
        )

    result = ThreadVerificationResult(header.id, header.thread_id)
    if header.version != 2 or header.interaction_mode != schemas.InteractionMode.CHAT:
        result.issues.append(
            VerificationIssue(
                "thread_no_longer_eligible",
                "thread is no longer a v2 chat thread",
            )
        )
        return result

    openai_messages = await m15._fetch_openai_messages_in_thread(
        client, header.thread_id
    )
    expected_runs, expected_indexes, expected_tools = await _build_expected_history(
        client, header, openai_messages
    )

    # Keep PostgreSQL connections out of the slow OpenAI request path. Only load the
    # local snapshot after all remote calls for this thread have completed.
    thread = await _load_thread(session, thread_id)
    if thread is None:
        result.issues.append(
            VerificationIssue("thread_missing", "local thread no longer exists")
        )
        return result
    local_messages = {
        message.message_id: message
        for message in thread.messages
        if message.message_id is not None
    }
    openai_messages_by_id = {message.id: message for message in openai_messages}

    _compare_id_sets(
        result,
        "messages",
        set(openai_messages_by_id),
        set(local_messages),
    )
    if len(local_messages) != len(thread.messages):
        result.issues.append(
            VerificationIssue(
                "messages_local_only",
                "one or more local messages have no OpenAI message id",
            )
        )

    expected_user_ids = {
        message.id: await m15._resolve_user_id(session, message)
        for message in openai_messages
    }
    _compare_messages(
        result,
        thread,
        openai_messages_by_id,
        local_messages,
        expected_indexes,
        expected_user_ids,
    )
    local_run_ids_by_sequence = _compare_runs(
        result,
        thread,
        local_messages,
        expected_runs,
        expected_user_ids,
    )
    _compare_tool_calls(
        result, thread, expected_tools, local_run_ids_by_sequence
    )

    referenced_files: dict[int, set[str]] = {}
    for openai_message_id in sorted(set(openai_messages_by_id) & set(local_messages)):
        openai_message = openai_messages_by_id[openai_message_id]
        local_message = local_messages[openai_message_id]
        _compare_parts_and_annotations(
            result,
            openai_message,
            local_message,
            referenced_files,
        )
        if openai_message.role == "user":
            _compare_attachments(result, openai_message, local_message)

    await _check_backfilled_files(session, result, referenced_files)
    return result


async def _build_expected_history(
    client: OpenAIClient,
    thread,
    openai_messages: list[OpenAIMessage],
) -> tuple[
    list[ExpectedRun],
    dict[str, int],
    list[ExpectedToolCall],
]:
    expected_runs: list[ExpectedRun] = []
    message_indexes: dict[str, int] = {}
    expected_tools: list[ExpectedToolCall] = []
    output_index = -1

    async for turn in m15._iter_migration_turns(client, thread, openai_messages):
        run_sequence = len(expected_runs)
        if turn.openai_runs:
            run_fields = m15._openai_run_fields(
                turn.openai_runs[-1], created=m15._collapsed_run_started_at(turn)
            )
            openai_run_id = turn.openai_runs[-1].id
        else:
            placeholder = turn.user_message or turn.assistant_messages[0]
            run_fields = m15._placeholder_run_fields(placeholder)
            openai_run_id = None

        expected_runs.append(
            ExpectedRun(
                sequence=run_sequence,
                message_ids=tuple(message.id for message in turn.messages()),
                run_id=openai_run_id,
                status=run_fields["status"],
                created=run_fields["created"],
                completed=run_fields["completed"],
                creator_message_id=(
                    turn.user_message.id if turn.user_message is not None else None
                ),
                error_code=run_fields.get("error_code"),
                error_message=run_fields.get("error_message"),
                incomplete_reason=run_fields.get("incomplete_reason"),
            )
        )

        if turn.user_message is not None:
            output_index += 1
            message_indexes[turn.user_message.id] = output_index

        assistant_messages = {message.id: message for message in turn.assistant_messages}
        stored_assistant_message_ids: set[str] = set()
        for openai_run in turn.openai_runs:
            for run_step in await m15._list_run_steps(
                client, thread.thread_id, openai_run.id
            ):
                if isinstance(run_step.step_details, MessageCreationStepDetails):
                    message_id = (
                        run_step.step_details.message_creation.message_id
                    )
                    if (
                        message_id in assistant_messages
                        and message_id not in stored_assistant_message_ids
                    ):
                        output_index += 1
                        message_indexes[message_id] = output_index
                        stored_assistant_message_ids.add(message_id)
                    continue

                if not isinstance(run_step.step_details, ToolCallsStepDetails):
                    continue
                status = m15._map_run_step_status(run_step.status)
                created = m15._require_dt(run_step.created_at)
                completed = m15._dt_from_ts(
                    run_step.completed_at
                    or run_step.failed_at
                    or run_step.cancelled_at
                    or run_step.expired_at
                )
                for tool_call in run_step.step_details.tool_calls:
                    expected = await _expected_tool_call(
                        client,
                        run_sequence,
                        tool_call,
                        status,
                        output_index + 1,
                        created,
                        completed,
                    )
                    if expected is None:
                        continue
                    output_index += 1
                    expected_tools.append(expected)

        for message in turn.assistant_messages:
            if message.id not in stored_assistant_message_ids:
                output_index += 1
                message_indexes[message.id] = output_index

    return expected_runs, message_indexes, expected_tools


async def _expected_tool_call(
    client: OpenAIClient,
    run_sequence: int,
    tool_call,
    status: schemas.ToolCallStatus,
    output_index: int,
    created: datetime,
    completed: datetime | None,
) -> ExpectedToolCall | None:
    if isinstance(tool_call, CodeInterpreterToolCall):
        payload = getattr(tool_call, "code_interpreter", None)
        if payload is None:
            return None
        outputs: list[tuple[Any, ...]] = []
        source_unavailable = False
        for output in payload.outputs:
            if output.type == "logs":
                outputs.append(
                    (
                        schemas.CodeInterpreterOutputType.LOGS,
                        output.logs,
                        None,
                        _normalized_datetime(created),
                    )
                )
            elif output.type == "image" and output.image is not None:
                data_url = await m15._image_output_to_data_url(
                    client, output.image.file_id
                )
                if data_url is None:
                    source_unavailable = True
                else:
                    outputs.append(
                        (
                            schemas.CodeInterpreterOutputType.IMAGE,
                            None,
                            data_url,
                            _normalized_datetime(created),
                        )
                    )
        return ExpectedToolCall(
            run_sequence=run_sequence,
            tool_call_id=tool_call.id,
            type=schemas.ToolCallType.CODE_INTERPRETER,
            status=status,
            output_index=output_index,
            created=created,
            completed=completed,
            code=payload.input,
            outputs=tuple(outputs),
            source_unavailable=source_unavailable,
        )

    if isinstance(tool_call, FileSearchToolCall):
        payload = getattr(tool_call, "file_search", None)
        if payload is None:
            return None
        results = tuple(
            (
                result.file_id,
                result.file_name,
                result.score,
                "\n\n".join(c.text for c in (result.content or []) if c.text),
                _normalized_datetime(created),
            )
            for result in (payload.results or [])
        )
        return ExpectedToolCall(
            run_sequence=run_sequence,
            tool_call_id=tool_call.id,
            type=schemas.ToolCallType.FILE_SEARCH,
            status=status,
            output_index=output_index,
            created=created,
            completed=completed,
            results=results,
        )

    return None


def _compare_messages(
    result: ThreadVerificationResult,
    thread: models.Thread,
    openai_messages: dict[str, OpenAIMessage],
    local_messages: dict[str, models.Message],
    expected_indexes: dict[str, int],
    expected_user_ids: dict[str, int | None],
) -> None:
    for message_id in sorted(set(openai_messages) & set(local_messages)):
        source = openai_messages[message_id]
        local = local_messages[message_id]
        metadata = (local.message_metadata or {}).get(MIGRATION_KEY, {})
        required_states = {"message": "complete", "message_parts": "complete"}
        if source.role == "user":
            required_states["attachments"] = "complete"
        for key, expected_state in required_states.items():
            if metadata.get(key) != expected_state:
                result.issues.append(
                    VerificationIssue(
                        "migration_marker_mismatch",
                        f"message_id={message_id} marker={key}",
                    )
                )

        expected_fields = {
            "role": schemas.MessageRole(source.role),
            "message_status": m15._map_message_status(source.status),
            "created": m15._require_dt(source.created_at),
            "completed": m15._dt_from_ts(source.completed_at),
            "output_index": expected_indexes.get(message_id),
            "assistant_id": thread.assistant_id if source.role == "assistant" else None,
            "user_id": expected_user_ids.get(message_id),
        }
        for field_name, expected in expected_fields.items():
            if not _values_equal(getattr(local, field_name), expected):
                result.issues.append(
                    VerificationIssue(
                        "message_field_mismatch",
                        f"message_id={message_id} field={field_name}",
                    )
                )


def _compare_runs(
    result: ThreadVerificationResult,
    thread: models.Thread,
    local_messages: dict[str, models.Message],
    expected_runs: list[ExpectedRun],
    expected_user_ids: dict[str, int | None],
) -> dict[int, int]:
    matched_run_ids: set[int] = set()
    local_run_ids_by_sequence: dict[int, int] = {}
    for expected in expected_runs:
        matched_messages = [
            local_messages[message_id]
            for message_id in expected.message_ids
            if message_id in local_messages
        ]
        if not matched_messages:
            continue
        run_ids = {message.run_id for message in matched_messages}
        if len(run_ids) != 1:
            result.issues.append(
                VerificationIssue(
                    "run_group_mismatch",
                    f"source turn sequence={expected.sequence} spans local runs",
                )
            )
            continue
        local_run_id = next(iter(run_ids))
        local_run = next((run for run in thread.runs if run.id == local_run_id), None)
        if local_run is None:
            result.issues.append(
                VerificationIssue(
                    "run_missing",
                    f"source turn sequence={expected.sequence}",
                )
            )
            continue
        matched_run_ids.add(local_run.id)
        local_run_ids_by_sequence[expected.sequence] = local_run.id
        expected_fields = {
            "run_id": expected.run_id,
            "status": expected.status,
            "created": expected.created,
            "completed": expected.completed,
            "creator_id": (
                expected_user_ids.get(expected.creator_message_id)
                if expected.creator_message_id is not None
                else None
            ),
            "error_code": expected.error_code,
            "error_message": expected.error_message,
            "incomplete_reason": expected.incomplete_reason,
            "thread_id": thread.id,
            "assistant_id": thread.assistant_id,
        }
        for field_name, expected_value in expected_fields.items():
            if not _values_equal(getattr(local_run, field_name), expected_value):
                result.issues.append(
                    VerificationIssue(
                        "run_field_mismatch",
                        f"source turn sequence={expected.sequence} field={field_name}",
                    )
                )

    extra_run_ids = {run.id for run in thread.runs} - matched_run_ids
    if extra_run_ids:
        result.issues.append(
            VerificationIssue(
                "runs_local_only",
                f"count={len(extra_run_ids)}",
            )
        )
    return local_run_ids_by_sequence


def _compare_tool_calls(
    result: ThreadVerificationResult,
    thread: models.Thread,
    expected_tools: list[ExpectedToolCall],
    local_run_ids_by_sequence: dict[int, int],
) -> None:
    local_by_id: dict[str, list[models.ToolCall]] = {}
    for tool_call in thread.tool_calls:
        local_by_id.setdefault(tool_call.tool_call_id, []).append(tool_call)
    expected_by_id = {tool_call.tool_call_id: tool_call for tool_call in expected_tools}
    _compare_id_sets(result, "tool_calls", set(expected_by_id), set(local_by_id))

    for expected in expected_tools:
        local_calls = local_by_id.get(expected.tool_call_id, [])
        if len(local_calls) != 1:
            if len(local_calls) > 1:
                result.issues.append(
                    VerificationIssue(
                        "tool_call_duplicate",
                        f"tool_call_id={expected.tool_call_id} count={len(local_calls)}",
                    )
                )
            continue
        local = local_calls[0]
        expected_local_run_id = local_run_ids_by_sequence.get(expected.run_sequence)
        if expected_local_run_id is not None and local.run_id != expected_local_run_id:
            result.issues.append(
                VerificationIssue(
                    "tool_call_run_mismatch",
                    f"tool_call_id={expected.tool_call_id}",
                )
            )
        expected_fields = {
            "type": expected.type,
            "status": expected.status,
            "output_index": expected.output_index,
            "created": expected.created,
            "completed": expected.completed,
            "code": expected.code,
            "queries": "" if expected.type == schemas.ToolCallType.FILE_SEARCH else None,
            "container_id": None,
        }
        for field_name, expected_value in expected_fields.items():
            if not _values_equal(getattr(local, field_name), expected_value):
                result.issues.append(
                    VerificationIssue(
                        "tool_call_field_mismatch",
                        f"tool_call_id={expected.tool_call_id} field={field_name}",
                    )
                )
        if expected.source_unavailable:
            result.issues.append(
                VerificationIssue(
                    "openai_tool_output_unavailable",
                    f"tool_call_id={expected.tool_call_id}",
                )
            )
        if expected.type == schemas.ToolCallType.CODE_INTERPRETER:
            actual_outputs = Counter(
                (
                    output.output_type,
                    output.logs,
                    output.url,
                    _normalized_datetime(output.created),
                )
                for output in local.outputs
            )
            if actual_outputs != Counter(expected.outputs):
                result.issues.append(
                    VerificationIssue(
                        "tool_call_outputs_mismatch",
                        f"tool_call_id={expected.tool_call_id}",
                    )
                )
        elif expected.type == schemas.ToolCallType.FILE_SEARCH:
            actual_results = Counter(
                (
                    item.file_id,
                    item.filename,
                    item.score,
                    item.text,
                    _normalized_datetime(item.created),
                )
                for item in local.results
            )
            if actual_results != Counter(expected.results):
                result.issues.append(
                    VerificationIssue(
                        "tool_call_results_mismatch",
                        f"tool_call_id={expected.tool_call_id}",
                    )
                )


def _compare_parts_and_annotations(
    result: ThreadVerificationResult,
    source: OpenAIMessage,
    local: models.Message,
    referenced_files: dict[int, set[str]],
) -> None:
    expected_parts = _expected_parts(source)
    local_parts_by_index: dict[int, list[models.MessagePart]] = {}
    for part in local.content:
        local_parts_by_index.setdefault(part.part_index, []).append(part)

    expected_indexes = {part["part_index"] for part in expected_parts}
    _compare_id_sets(
        result,
        f"message_parts message_id={source.id}",
        expected_indexes,
        set(local_parts_by_index),
    )
    for part_index, parts in local_parts_by_index.items():
        if len(parts) > 1:
            result.issues.append(
                VerificationIssue(
                    "message_part_duplicate",
                    f"message_id={source.id} part_index={part_index}",
                )
            )

    for expected in expected_parts:
        matches = local_parts_by_index.get(expected["part_index"], [])
        if len(matches) != 1:
            continue
        part = matches[0]
        for field_name in ("type", "text", "input_image_file_id"):
            if not _values_equal(getattr(part, field_name), expected.get(field_name)):
                result.issues.append(
                    VerificationIssue(
                        "message_part_field_mismatch",
                        f"message_id={source.id} part_index={part.part_index} "
                        f"field={field_name}",
                    )
                )
        if expected.get("input_image_file_id"):
            if part.input_image_file_object_id is None:
                result.issues.append(
                    VerificationIssue(
                        "message_part_file_missing",
                        f"message_id={source.id} part_index={part.part_index}",
                    )
                )
            else:
                referenced_files.setdefault(
                    part.input_image_file_object_id, set()
                ).add(expected["input_image_file_id"])

        expected_annotations = Counter(expected["annotations"])
        actual_annotations = Counter(_annotation_key(annotation) for annotation in part.annotations)
        if actual_annotations != expected_annotations:
            result.issues.append(
                VerificationIssue(
                    "annotations_mismatch",
                    f"message_id={source.id} part_index={part.part_index}",
                )
            )
        for annotation in part.annotations:
            if annotation.type == schemas.AnnotationType.CONTAINER_FILE_CITATION:
                object_id = (
                    annotation.vision_file_object_id or annotation.file_object_id
                )
                if object_id is None:
                    result.issues.append(
                        VerificationIssue(
                            "annotation_file_missing",
                            f"message_id={source.id} part_index={part.part_index} "
                            f"annotation_index={annotation.annotation_index}",
                        )
                    )
                else:
                    openai_file_id = (
                        annotation.vision_file_id or annotation.file_id
                    )
                    if openai_file_id:
                        referenced_files.setdefault(object_id, set()).add(
                            openai_file_id
                        )


def _expected_parts(source: OpenAIMessage) -> list[dict[str, Any]]:
    contents = [
        content
        for content in source.content
        if not (
            content.type == "image_file"
            and not (getattr(content.image_file, "file_id", "") or "").strip()
        )
    ]
    ci_images = []
    if source.role == "assistant":
        ci_images = [content for content in contents if content.type == "image_file"]
        contents = [content for content in contents if content.type != "image_file"]

    parts: list[dict[str, Any]] = []
    first_output_text: dict[str, Any] | None = None
    first_output_text_source_annotation_count = 0
    for part_index, content in enumerate(contents):
        if content.type == "text":
            part = {
                "part_index": part_index,
                "type": (
                    schemas.MessagePartType.INPUT_TEXT
                    if source.role == "user"
                    else schemas.MessagePartType.OUTPUT_TEXT
                ),
                "text": content.text.value,
                "input_image_file_id": None,
                "annotations": [
                    key
                    for annotation_index, annotation in enumerate(
                        content.text.annotations or []
                    )
                    if (
                        key := _source_annotation_key(
                            annotation_index, annotation
                        )
                    )
                    is not None
                ],
            }
            parts.append(part)
            if first_output_text is None and source.role == "assistant":
                first_output_text = part
                first_output_text_source_annotation_count = len(
                    content.text.annotations or []
                )
        elif content.type == "image_file":
            parts.append(
                {
                    "part_index": part_index,
                    "type": schemas.MessagePartType.INPUT_IMAGE,
                    "text": None,
                    "input_image_file_id": content.image_file.file_id,
                    "annotations": [],
                }
            )

    if ci_images:
        if first_output_text is None:
            first_output_text = {
                "part_index": len(contents),
                "type": schemas.MessagePartType.OUTPUT_TEXT,
                "text": "",
                "input_image_file_id": None,
                "annotations": [],
            }
            parts.append(first_output_text)
        for offset, content in enumerate(ci_images):
            first_output_text["annotations"].append(
                (
                    first_output_text_source_annotation_count + offset,
                    schemas.AnnotationType.CONTAINER_FILE_CITATION,
                    None,
                    None,
                    None,
                    None,
                    content.image_file.file_id,
                )
            )
    return parts


def _source_annotation_key(
    annotation_index: int, annotation
) -> tuple[Any, ...] | None:
    common = (
        annotation.start_index,
        annotation.end_index,
        annotation.text,
    )
    if annotation.type == "file_citation":
        return (
            annotation_index,
            schemas.AnnotationType.FILE_CITATION,
            *common,
            annotation.file_citation.file_id,
            None,
        )
    if annotation.type == "file_path":
        return (
            annotation_index,
            schemas.AnnotationType.CONTAINER_FILE_CITATION,
            *common,
            annotation.file_path.file_id,
            None,
        )
    return None


def _annotation_key(annotation: models.Annotation) -> tuple[Any, ...]:
    vision_file_id = (
        annotation.vision_file_id
        if annotation.type == schemas.AnnotationType.CONTAINER_FILE_CITATION
        and annotation.vision_file_id is not None
        else None
    )
    return (
        annotation.annotation_index,
        annotation.type,
        annotation.start_index,
        annotation.end_index,
        annotation.text,
        annotation.file_id,
        vision_file_id,
    )


def _compare_attachments(
    result: ThreadVerificationResult,
    source: OpenAIMessage,
    local: models.Message,
) -> None:
    expected_file_search: set[str] = set()
    expected_code_interpreter: set[str] = set()
    local_file_search_available = {
        file.file_id for file in local.file_search_attachments
    }
    local_code_interpreter_available = {
        file.file_id for file in local.code_interpreter_attachments
    }

    for attachment in source.attachments or []:
        file_id = attachment.file_id
        tool_types = {
            tool.type for tool in (attachment.tools or []) if tool.type is not None
        }
        if not file_id or not tool_types:
            continue
        if "file_search" in tool_types:
            expected_file_search.add(file_id)
        if "code_interpreter" in tool_types:
            expected_code_interpreter.add(file_id)

    _compare_id_sets(
        result,
        f"file_search_attachments message_id={source.id}",
        expected_file_search,
        local_file_search_available,
    )
    _compare_id_sets(
        result,
        f"code_interpreter_attachments message_id={source.id}",
        expected_code_interpreter,
        local_code_interpreter_available,
    )


async def _check_backfilled_files(
    session: AsyncSession,
    result: ThreadVerificationResult,
    referenced_files: dict[int, set[str]],
) -> None:
    if not referenced_files:
        return
    rows = list(
        (
            await session.scalars(
                select(models.File).where(models.File.id.in_(referenced_files))
            )
        ).all()
    )
    found_ids = {file.id for file in rows}
    if missing_ids := set(referenced_files) - found_ids:
        result.issues.append(
            VerificationIssue(
                "backfilled_file_missing",
                f"count={len(missing_ids)}",
            )
        )
    missing_s3 = [file.id for file in rows if file.s3_file_id is None]
    if missing_s3:
        result.issues.append(
            VerificationIssue(
                "backfilled_file_content_missing",
                f"count={len(missing_s3)}",
            )
        )
    mismatched_source_ids = [
        file.id
        for file in rows
        if file.file_id not in referenced_files.get(file.id, set())
    ]
    if mismatched_source_ids:
        result.issues.append(
            VerificationIssue(
                "backfilled_file_source_mismatch",
                f"count={len(mismatched_source_ids)}",
            )
        )


def _compare_id_sets(
    result: ThreadVerificationResult,
    label: str,
    expected: set,
    actual: set,
) -> None:
    if missing := expected - actual:
        result.issues.append(
            VerificationIssue(
                f"{label.split()[0]}_missing",
                f"{label} count={len(missing)} ids={sorted(missing)}",
            )
        )
    if extra := actual - expected:
        result.issues.append(
            VerificationIssue(
                f"{label.split()[0]}_local_only",
                f"{label} count={len(extra)} ids={sorted(extra)}",
            )
        )


def _values_equal(actual, expected) -> bool:
    if isinstance(actual, datetime) or isinstance(expected, datetime):
        return _normalized_datetime(actual) == _normalized_datetime(expected)
    return actual == expected


def _normalized_datetime(value: datetime | None):
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
