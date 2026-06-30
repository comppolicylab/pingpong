import base64
import logging
from datetime import datetime
from pathlib import Path
from typing import AsyncIterator

from openai import Omit, omit
from openai.types.beta.threads.runs import (
    CodeInterpreterToolCall,
    FileSearchToolCall,
    RunStep,
    ToolCallsStepDetails,
)
from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy.orm.attributes import flag_modified

import pingpong.models as models
import pingpong.schemas as schemas
from pingpong.ai import get_openai_client_by_class_id
from pingpong.files import file_extension_to_mime_type
from pingpong.migrations.m15_v3_migrate_threads_and_messages import (
    _dt_from_ts,
    _fetch_openai_messages_in_thread,
    _iter_migration_turns,
    _require_dt,
)
from pingpong.server import OpenAIClient

logger = logging.getLogger(__name__)

LOCAL_BATCH_SIZE = 100


ThreadTurnCache = dict[
    int, dict[str, list[str]]
]  # {last_openai_run_id: [all_openai_run_ids_in_that_turn]}


async def migrate_tool_calls(session: AsyncSession) -> None:
    """Backfill `tool_calls` (and their CodeInterpreterCallOutput/FileSearchCallResult
    children) onto the `Run` objects created by m15. Assumes m15, m16, and m17 have
    run. Each processed message gets `tool_calls`="complete".

    A v3 Run collapses a whole turn but m15 stored only the turn's last OpenAI run id.
    To capture tool calls from every OpenAI run in the turn we re-derive the turn's
    full OpenAI-run-id set (reusing m15's grouping helpers) and attach all resulting
    tool calls to the single existing local Run. We never create new Runs here.
    """

    logger.info(
        "m18 starting tool call migration. classes=%s messages=%s",
        await _count_tool_call_classes(session),
        await _count_tool_call_messages(session),
    )

    async for class_id in _tool_call_class_ids(session):
        try:
            openai_client = await get_openai_client_by_class_id(session, class_id)
        except Exception:
            logger.exception(
                "Could not get OpenAI client during tool call "
                f"backfill. class_id={class_id}",
            )
            continue

        # so we don't have to keep finding the local run <> OpenAI run correspondence
        # each time.
        thread_cache: ThreadTurnCache = {}
        processed_run_ids: set[int] = set()

        last_message_id = 0
        while True:
            local_messages = await _fetch_messages(
                session,
                class_id=class_id,
                after_id=last_message_id,
                limit=LOCAL_BATCH_SIZE,
            )
            if not local_messages:
                break

            logger.info(
                "m18 processing message batch. class_id=%s messages=%s first_id=%s "
                "last_id=%s",
                class_id,
                len(local_messages),
                local_messages[0].id,
                local_messages[-1].id,
            )

            for local_message in local_messages:
                # I define these outside of the nested session so we can use them in the
                # `except` block. Otherwise an error occurs because we're accessing fields
                # on an object from a cancelled/reversed transaction
                thread_id = local_message.thread_id
                openai_thread_id = local_message.thread.thread_id
                async with session.begin_nested() as savepoint:
                    try:
                        await _migrate_message_tool_calls(
                            session,
                            openai_client,
                            local_message,
                            processed_run_ids,
                            thread_cache,
                        )
                        local_message.message_metadata[
                            "assistants_to_responses_api_thread_migration"
                        ]["tool_calls"] = "complete"
                        # Notifies SQLAlchemy that `message_metadata` changed (since
                        # it's JSON it wouldn't be detected otherwise).
                        flag_modified(local_message, "message_metadata")
                    except Exception:
                        await savepoint.rollback()
                        logger.exception(
                            f"Unexpected error backfilling tool calls. "
                            f"thread_id={thread_id} "
                            f"openai_thread_id={openai_thread_id}"
                        )

                await session.commit()

            last_message_id = local_messages[-1].id


async def _tool_call_class_ids(session: AsyncSession) -> AsyncIterator[int]:
    last_class_id = 0
    while True:
        stmt = (
            select(models.Thread.class_id)
            .join(models.Message, models.Message.thread_id == models.Thread.id)
            .where(*_tool_call_filters(), models.Thread.class_id > last_class_id)
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


def _tool_call_filters():
    migration_metadata = models.Message.message_metadata[
        "assistants_to_responses_api_thread_migration"
    ]
    attachments_state = migration_metadata["attachments"].as_string()
    tool_calls_state = migration_metadata["tool_calls"].as_string()
    return (
        attachments_state == "complete",
        models.Message.message_id.is_not(None),
        or_(
            tool_calls_state.is_(None),
            tool_calls_state != "complete",
        ),
    )


async def _count_tool_call_messages(session: AsyncSession) -> int:
    stmt = select(func.count()).select_from(models.Message).where(*_tool_call_filters())
    return await session.scalar(stmt) or 0


async def _count_tool_call_classes(session: AsyncSession) -> int:
    class_ids = (
        select(models.Thread.class_id)
        .join(models.Message, models.Message.thread_id == models.Thread.id)
        .where(*_tool_call_filters())
        .distinct()
        .subquery()
    )
    return await session.scalar(select(func.count()).select_from(class_ids)) or 0


async def _fetch_messages(
    session: AsyncSession,
    *,
    class_id: int | None = None,
    after_id: int | None = None,
    limit: int | None = None,
) -> list[models.Message]:
    stmt = select(models.Message).where(*_tool_call_filters())
    if class_id is not None:
        stmt = stmt.join(models.Thread, models.Message.thread_id == models.Thread.id)
        stmt = stmt.where(models.Thread.class_id == class_id)
    if after_id is not None:
        stmt = stmt.where(models.Message.id > after_id)
    stmt = stmt.order_by(models.Message.id).options(
        selectinload(models.Message.thread),
        selectinload(models.Message.run),
    )
    if limit is not None:
        stmt = stmt.limit(limit)
    result = await session.execute(stmt)
    return list(result.scalars())


async def _migrate_message_tool_calls(
    session: AsyncSession,
    openai_client: OpenAIClient,
    local_message: models.Message,
    processed_run_ids: set[int],
    thread_cache: ThreadTurnCache,
) -> None:
    local_run = local_message.run
    if local_run is None or local_run.run_id is None:
        logger.info(
            "m18 skipping message with no upstream run. message_id_local=%s run_id_local=%s",
            local_message.id,
            local_run.id if local_run is not None else None,
        )
        return

    if local_run.id in processed_run_ids:
        return

    openai_run_ids = await _turn_openai_run_ids(
        openai_client, local_message.thread, local_run, thread_cache
    )

    insertion_index = await _tool_call_insertion_index(session, local_run)

    output_index = insertion_index - 1
    tool_calls_created = 0
    for openai_run_id in openai_run_ids:
        for run_step in await _list_run_steps(
            openai_client, local_message.thread.thread_id, openai_run_id
        ):
            output_index, created = await _persist_run_step_tool_calls(
                session,
                openai_client,
                local_run,
                run_step,
                output_index,
            )
            tool_calls_created += created

    processed_run_ids.add(local_run.id)
    await session.flush()
    logger.info(
        "m18 backfilled run tool calls. run_id_local=%s openai_run_ids=%s "
        "tool_calls_created=%s insertion_index=%s message_id_local=%s",
        local_run.id,
        openai_run_ids,
        tool_calls_created,
        insertion_index,
        local_message.id,
    )


async def _tool_call_insertion_index(
    session: AsyncSession, local_run: models.Run
) -> int:
    """Where in the thread's output_index sequence this run's tool calls belong.

    Tool calls precede the assistant's reply, so we target the output_index of the
    run's first assistant message. If the run has no assistant message (e.g. an
    orphan/user-only turn) we plan to put it at the end.
    """
    first_assistant_index = await session.scalar(
        select(func.min(models.Message.output_index)).where(
            models.Message.run_id == local_run.id,
            models.Message.role == schemas.MessageRole.ASSISTANT,
        )
    )
    if first_assistant_index is not None:
        return first_assistant_index

    max_index = await models.Thread.get_max_output_sequence(
        session, local_run.thread_id
    )
    return max_index + 1


async def _shift_output_indexes_for_tool_calls(
    session: AsyncSession, thread_id: int, insertion_index: int, shift_by: int
) -> None:
    """Increments the output_index of everything after the object at `insertion_index`
    position. This is done for each tool call, which means we're updating the same
    objects multiple times, but that shouldn't come with too much of a transaction cost?
    The reason I think we have to do this is we're not guaranteed that we're going to
    see the messages in the order they appear in the thread/we may not even be seeing
    every message in a thread if we have to re-run the migration. So even though we
    could update these fields one at a time by doing `local_message.output_index = ...`
    that could get really complicated since it would rely on knowing where in the thread
    and where in the run we are AND if we're looking at all messages in a thread or only
    a subset.
    """
    if shift_by <= 0:
        return

    await session.execute(
        update(models.Message)
        .where(
            models.Message.thread_id == thread_id,
            models.Message.output_index >= insertion_index,
        )
        .values(output_index=models.Message.output_index + shift_by),
    )
    await session.execute(
        update(models.ToolCall)
        .where(
            models.ToolCall.thread_id == thread_id,
            models.ToolCall.output_index >= insertion_index,
        )
        .values(output_index=models.ToolCall.output_index + shift_by),
    )
    await session.flush()


async def _turn_openai_run_ids(
    openai_client: OpenAIClient,
    thread: models.Thread,
    local_run: models.Run,
    thread_cache: ThreadTurnCache,
) -> list[str]:
    """Re-fetch OpenAI run ids that the local Run's collapsed.

    m15 grouped a thread's OpenAI messages into turns and stored only each turn's last
    OpenAI run id on the local Run. We rebuild those same turns and cache per thread.
    """
    assert local_run.run_id is not None

    if thread.id not in thread_cache:
        thread_cache[thread.id] = await _build_turn_run_id_map(openai_client, thread)

    # Fall back to the single known id if the turn can't be reconstructed (I don't
    # think this should happen?)
    return thread_cache[thread.id].get(local_run.run_id, [local_run.run_id])


async def _build_turn_run_id_map(
    openai_client: OpenAIClient, thread: models.Thread
) -> dict[str, list[str]]:
    openai_messages = await _fetch_openai_messages_in_thread(
        openai_client, thread.thread_id
    )
    turn_run_id_map: dict[str, list[str]] = {}
    async for turn in _iter_migration_turns(openai_client, thread, openai_messages):
        if not turn.openai_runs:
            continue
        run_ids = [run.id for run in turn.openai_runs]
        turn_run_id_map[run_ids[-1]] = run_ids
    return turn_run_id_map


async def _list_run_steps(
    openai_client: OpenAIClient,
    openai_thread_id: str,
    openai_run_id: str,
) -> list[RunStep]:
    run_steps: list[RunStep] = []
    after: str | Omit = omit

    while True:
        page = await openai_client.beta.threads.runs.steps.list(
            openai_run_id,
            thread_id=openai_thread_id,
            order="asc",
            after=after,
            include=["step_details.tool_calls[*].file_search.results[*].content"],
        )
        run_steps.extend(page.data)
        if not page.has_more or not page.data:
            break

        after = page.data[-1].id

    return run_steps


async def _persist_run_step_tool_calls(
    session: AsyncSession,
    openai_client: OpenAIClient,
    local_run: models.Run,
    run_step: RunStep,
    output_index: int,
) -> tuple[int, int]:
    """Returns the updated output_index and the number of tool calls created.

    `output_index` is the index of the tool call before this step (or
    `insertion_index - 1` for the run's first step). Each newly created tool call opens
    a 1-wide gap at its target index by shifting the assistant message and everything
    after it in the thread up by one.
    """
    if not isinstance(run_step.step_details, ToolCallsStepDetails):
        return output_index, 0

    status = _map_run_step_status(run_step.status)
    created = _require_dt(run_step.created_at)
    completed = _dt_from_ts(
        run_step.completed_at or run_step.failed_at or run_step.cancelled_at
    )

    created_count = 0
    for tool_call in run_step.step_details.tool_calls:
        if isinstance(tool_call, (CodeInterpreterToolCall, FileSearchToolCall)):
            # Always advance output_index if valid tool call, even if already exists
            output_index += 1
            if await _does_tool_call_exist(session, local_run.id, tool_call.id):
                logger.info(
                    "m18 skipping already-persisted tool call. run_id_local=%s "
                    "tool_call_id=%s",
                    local_run.id,
                    tool_call.id,
                )
                continue

            await _shift_output_indexes_for_tool_calls(
                session, local_run.thread_id, output_index, 1
            )

        if isinstance(tool_call, CodeInterpreterToolCall):
            await _persist_code_interpreter_tool_call(
                session,
                openai_client,
                local_run,
                tool_call,
                status,
                output_index,
                created,
                completed,
            )
            created_count += 1
        elif isinstance(tool_call, FileSearchToolCall):
            await _persist_file_search_tool_call(
                session,
                local_run,
                tool_call,
                status,
                output_index,
                created,
                completed,
            )
            created_count += 1
        else:
            # No support for function tool calls, so this should never be executed?
            logger.info(
                "m18 skipping unsupported tool call type. run_id_local=%s type=%s",
                local_run.id,
                getattr(tool_call, "type", None),
            )

    return output_index, created_count


async def _does_tool_call_exist(
    session: AsyncSession, local_run_id: int, tool_call_id: str
) -> bool:
    stmt = select(models.ToolCall.id).where(
        models.ToolCall.run_id == local_run_id,
        models.ToolCall.tool_call_id == tool_call_id,
    )
    return await session.scalar(stmt) is not None


async def _persist_code_interpreter_tool_call(
    session: AsyncSession,
    openai_client: OpenAIClient,
    local_run: models.Run,
    tool_call: CodeInterpreterToolCall,
    status: schemas.ToolCallStatus,
    output_index: int,
    created: datetime,
    completed: datetime | None,
) -> None:
    local_tool_call = await models.ToolCall.create(
        session,
        {
            "run_id": local_run.id,
            "tool_call_id": tool_call.id,
            "type": schemas.ToolCallType.CODE_INTERPRETER,
            "status": status,
            "thread_id": local_run.thread_id,
            "output_index": output_index,
            "container_id": None,  # because v2
            "code": tool_call.code_interpreter.input,
            "created": created,
            "completed": completed,
        },
    )

    for output in tool_call.code_interpreter.outputs:
        if output.type == "logs":
            await models.CodeInterpreterCallOutput.create(
                session,
                {
                    "tool_call_id": local_tool_call.id,
                    "output_type": schemas.CodeInterpreterOutputType.LOGS,
                    "logs": output.logs,
                    "created": created,
                },
            )
        elif output.type == "image":
            file_id = output.image.file_id if output.image else None
            if file_id is None:
                logger.warning(
                    "m18 skipping code interpreter image output without a file_id. "
                    "run_id_local=%s tool_call_id=%s",
                    local_run.id,
                    tool_call.id,
                )
                continue
            # v2 only gives a file_id (no URL), so fetch the content and store it as a
            # base64 data URL in the `url` column.
            data_url = await _image_output_to_data_url(openai_client, file_id)
            await models.CodeInterpreterCallOutput.create(
                session,
                {
                    "tool_call_id": local_tool_call.id,
                    "output_type": schemas.CodeInterpreterOutputType.IMAGE,
                    "url": data_url,
                    "created": created,
                },
            )


async def _persist_file_search_tool_call(
    session: AsyncSession,
    local_run: models.Run,
    tool_call: FileSearchToolCall,
    status: schemas.ToolCallStatus,
    output_index: int,
    created: datetime,
    completed: datetime | None,
) -> None:
    local_tool_call = await models.ToolCall.create(
        session,
        {
            "run_id": local_run.id,
            "tool_call_id": tool_call.id,
            "type": schemas.ToolCallType.FILE_SEARCH,
            "status": status,
            "thread_id": local_run.thread_id,
            "output_index": output_index,
            # v2 file_search run steps have no queries.
            "queries": "",
            "created": created,
            "completed": completed,
        },
    )

    for result in tool_call.file_search.results or []:
        text = "\n\n".join(c.text for c in (result.content or []) if c.text)
        local_file = await session.scalar(
            select(models.File).where(models.File.file_id == result.file_id)
        )
        await models.FileSearchCallResult.create(
            session,
            {
                # v2 file_search results have no attributes.
                "attributes": None,
                "file_id": result.file_id,
                "file_object_id": local_file.id if local_file else None,
                "filename": result.file_name,
                "score": result.score,
                "text": text,
                "created": created,
                "tool_call_id": local_tool_call.id,
            },
        )


async def _image_output_to_data_url(openai_client: OpenAIClient, file_id: str) -> str:
    """Fetch a code interpreter image file's content from OpenAI and return it as a
    base64 data URL. Any failure bubbles up so the caller's savepoint rolls back.

    Essentially replicates files.generate_image_description where the image_url is set.
    """
    response = await openai_client.files.with_raw_response.retrieve_content(file_id)
    if response.status_code != 200:
        raise RuntimeError(
            f"OpenAI returned {response.status_code} while fetching code interpreter "
            f"image content during tool call migration (file_id: {file_id})"
        )

    openai_file = await openai_client.files.retrieve(file_id)
    suffix = Path(openai_file.filename or "").suffix.lstrip(".")
    content_type = (
        file_extension_to_mime_type(suffix) if suffix else None
    ) or "image/png"

    b64 = base64.b64encode(response.content).decode("utf-8")
    return f"data:{content_type};base64,{b64}"


def _map_run_step_status(run_step_status: str) -> schemas.ToolCallStatus:
    """Cancelled and expired are not valid statuses for our local Tool Call models,
    so we map them to `incomplete`."""
    override = {
        "cancelled": schemas.ToolCallStatus.INCOMPLETE,
        "expired": schemas.ToolCallStatus.INCOMPLETE,
    }.get(run_step_status)
    if override is not None:
        return override
    return schemas.ToolCallStatus(run_step_status)
