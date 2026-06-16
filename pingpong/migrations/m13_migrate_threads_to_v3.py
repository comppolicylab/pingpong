import logging
from datetime import datetime, timezone

from openai import Omit, omit
from openai.types.beta.threads import Message, Run
from sqlalchemy.ext.asyncio import AsyncSession

from pingpong.authz.openfga import OpenFgaAuthzClient
import pingpong.models as models
from pingpong.ai import (
    get_openai_client_by_class_id,
)
from pingpong.schemas import (
    MessageRole,
    RunStatus,
)
from pingpong.server import OpenAIClient

logger = logging.getLogger(__name__)

"""
TODO:
- images and attachments that are in OAI should be copied and stored in S3 like the files
in 
- what does our handler add to the database
- what does our app expect to have based on our output message to handle the streaming
- have i put everything that our server expects to have for every message type?
- small conversions

pay attention to files! they're very tricky to manage and there are a lot of places where
something can get 

"""

# TODO: rename
async def migrate_threads_and_messages_to_v3(
    session: AsyncSession, authz_client: OpenFgaAuthzClient
) -> None:
    async for assistant in models.Assistant.get_all_assistants_by_version(
        session, version=2
    ):
        async for thread in models.Thread.get_by_class_id(session, assistant.class_id):
            try:
                openai_client = await get_openai_client_by_class_id(
                    session, assistant.class_id
                )
            except Exception as e:
                logger.warning(
                    f"Could not get OpenAI client for thread {thread.id} "
                    f"(class_id={assistant.class_id}): {e} — skipping"
                )
                continue

            await _migrate_thread(
                session, authz_client, openai_client, thread, assistant
            )
            await session.flush()


async def _migrate_thread(
    session: AsyncSession,
    authz_client: OpenFgaAuthzClient,
    openai_client: OpenAIClient,
    thread: models.Thread,
    assistant: models.Assistant,
) -> None:
    openai_messages = await _fetch_openai_messages_in_thread(
        openai_client, thread.thread_id
    )
    # empty thread, nothing else to do
    if not openai_messages:
        return

    # User messages seen since the last assistant block, awaiting a run.
    pending_user_messages: list[Message] = []
    idx = 0
    prev_output_index = -1
    total = len(openai_messages)

    while idx < len(openai_messages):
        openai_message = openai_messages[idx]
        if openai_message.role != "assistant":
            pending_user_messages.append(openai_message)
            idx += 1
            continue

        # find block of consecutive assistant messages and assign them all
        # the same run, which gets its data from the run of the last assistant message
        # but with the start time of the first user message.

        consecutive_assistant_messages: list[Message] = []
        runs_in_assistant_block: list[Run] = []
        while idx < total and openai_messages[idx].role == "assistant":
            block_message = openai_messages[idx]
            consecutive_assistant_messages.append(block_message)
            if block_message.run_id is not None:
                runs_in_assistant_block.append(
                    await openai_client.beta.threads.runs.retrieve(
                        block_message.run_id, thread_id=thread.thread_id
                    )
                )
            idx += 1

        if runs_in_assistant_block:
            local_run = await _get_or_create_collapsed_run(
                session, thread, assistant, runs_in_assistant_block
            )
        else:
            # should never happen?
            logger.warning(
                f"Assistant block in thread {thread.id} had no run_id; "
                "using a dummy incomplete run"
            )
            # store with created ts from the first assistant message in the block
            local_run = await _store_dummy_run(
                session, thread, assistant, consecutive_assistant_messages[0]
            )

        if pending_user_messages:
            # all user messages that don't have an assistant response immediately after
            # get assigned a dummy run. last user message gets the real run form the
            # assistant response
            final_user_message = pending_user_messages[-1]
            for orphan in pending_user_messages[:-1]:
                prev_output_index = await _store_message_with_dummy_run(
                    session, thread, assistant, orphan, prev_output_index
                )
            prev_output_index = await _store_message(
                session,
                thread,
                assistant,
                final_user_message,
                local_run,
                prev_output_index,
            )
            pending_user_messages = []

        for block_message in consecutive_assistant_messages:
            prev_output_index = await _store_message(
                session,
                thread,
                assistant,
                block_message,
                local_run,
                prev_output_index,
            )

    # user messages with no assistant response at the end also get dummy runs
    for orphan in pending_user_messages:
        prev_output_index = await _store_message_with_dummy_run(
            session, thread, assistant, orphan, prev_output_index
        )

    session.add(thread)
    await session.flush()


async def _get_or_create_collapsed_run(
    session: AsyncSession,
    thread: models.Thread,
    assistant: models.Assistant,
    runs_in_assistant_block: list[Run],
) -> models.Run:
    last_run = runs_in_assistant_block[-1]

    # check if local run exists (for some reason) before creating to avoid duplicates
    existing = await models.Run.get_by_run_id(session, last_run.id)
    if existing:
        return existing

    created = datetime.fromtimestamp(runs_in_assistant_block[0].created_at)
    return await _store_run(session, thread, assistant, last_run, created)


async def _store_run(
    session: AsyncSession,
    thread: models.Thread,
    assistant: models.Assistant,
    openai_run: Run,
    created: datetime,
) -> models.Run:
    run = models.Run(
        run_id=openai_run.id,
        thread_id=thread.id,
        assistant_id=assistant.id,
        creator_id=assistant.creator_id,
        status=openai_run.status,
        error_code=openai_run.last_error and openai_run.last_error.code,
        error_message=openai_run.last_error and openai_run.last_error.message,
        incomplete_reason=(
            openai_run.incomplete_details and openai_run.incomplete_details.reason
        ),
        model=assistant.model,
        temperature=assistant.temperature,
        instructions=thread.instructions,
        created=created,
        completed=(
            openai_run.completed_at and datetime.fromtimestamp(openai_run.completed_at)
        ),
        tools_available=thread.tools_available,
        reasoning_effort=assistant.reasoning_effort,
        verbosity=assistant.verbosity,
    )
    session.add(run)
    await session.flush()
    await session.refresh(run)

    return run


async def _store_dummy_run(
    session: AsyncSession,
    thread: models.Thread,
    assistant: models.Assistant,
    openai_message: Message,
) -> models.Run:
    run = models.Run(
        run_id=None,
        thread_id=thread.id,
        assistant_id=assistant.id,
        creator_id=assistant.creator_id,
        status=RunStatus.INCOMPLETE,
        model=assistant.model,
        temperature=assistant.temperature,
        instructions=thread.instructions,
        created=datetime.fromtimestamp(openai_message.created_at, tz=timezone.utc),
        completed=None,
        tools_available=thread.tools_available,
        reasoning_effort=assistant.reasoning_effort,
        verbosity=assistant.verbosity,
    )
    session.add(run)
    await session.flush()
    await session.refresh(run)

    return run


async def _store_message_with_dummy_run(
    session: AsyncSession,
    thread: models.Thread,
    assistant: models.Assistant,
    openai_message: Message,
    prev_output_index: int,
) -> int:
    dummy_run = await _store_dummy_run(session, thread, assistant, openai_message)
    return await _store_message(
        session, thread, assistant, openai_message, dummy_run, prev_output_index
    )


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

async def _store_message(
    session: AsyncSession,
    thread: models.Thread,
    assistant: models.Assistant,
    openai_message: Message,
    local_run: models.Run,
    prev_output_index: int,
) -> int:
    # Check if there's a local copy of the message before creating it
    existing_local_message = await models.Message.get_by_message_id(
        session, openai_message.id
    )
    if existing_local_message:
        return prev_output_index

    # TODO: store tool calls
    # TODO: for next time: only attachments and message parts. put message parts inline with the models.Message as a field in there

    # no need to re-upload user created images to AWS bc they're lost forever
    # message part type -> input text or input image or output text
    # input image file id -> we can fetch these from open ai and upload them to s3

    user_id = _maybe_extract_user_id(openai_message)

    prev_output_index += 1
    await models.Message.create(
        session,
        {
            "message_id": openai_message.id,
            "message_status": openai_message.status,
            "role": MessageRole(openai_message.role),
            "created": datetime.fromtimestamp(
                openai_message.created_at, tz=timezone.utc
            ),
            "completed": openai_message.completed_at
            and datetime.fromtimestamp(openai_message.completed_at, tz=timezone.utc),
            "thread_id": thread.id,
            "run_id": local_run.id,
            "assistant_id": thread.assistant_id
            if openai_message.role == "assistant"
            else None,
            "user_id": user_id,
            "output_index": prev_output_index,  # TODO: needs to be consistent with ToolCall
            # TODO: fill message parts
        },
    )

    # TODO-later: annotations

    return prev_output_index

def _maybe_extract_user_id(openai_message: Message) -> int | None:
    if openai_message.role != "user":
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
            f"Couldn't get user_id from OpenAI message with id {openai_message.id}"
        )
        return None