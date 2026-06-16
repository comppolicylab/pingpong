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
    MessageStatus,
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
    run_id_map: dict[str, models.Run] = {}

    (
        openai_messages_by_run,
        openai_orphan_messages,
    ) = await _fetch_openai_messages_in_thread(openai_client, thread.thread_id)

    # empty thread, nothing else to do
    if not openai_messages_by_run:
        return

    prev_output_index = -1
    for openai_run_id, openai_messages in openai_messages_by_run.items():
        local_run = await _get_or_create_run(
            session, openai_client, thread, assistant, openai_run_id, run_id_map
        )

        for openai_message in openai_messages:
            await _store_message(
                session,
                authz_client,
                openai_client,
                thread,
                assistant,
                openai_message,
                local_run,
                prev_output_index,
            )

    for openai_message in openai_orphan_messages:
        await _store_message(
            session,
            authz_client,
            openai_client,
            thread,
            assistant,
            openai_message,
            local_run,
            prev_output_index,
        )

    session.add(thread)
    await session.flush()


async def _get_or_create_run(
    session: AsyncSession,
    openai_client: OpenAIClient,
    thread: models.Thread,
    assistant: models.Assistant,
    openai_run_id: str,
    run_id_map: dict[str, models.Run],
) -> models.Run:
    cached = run_id_map.get(openai_run_id)
    if cached:
        return cached

    existing = await models.Run.get_by_run_id(session, openai_run_id)
    if existing:
        run_id_map[openai_run_id] = existing
        return existing

    openai_run = await openai_client.beta.threads.runs.retrieve(
        openai_run_id, thread_id=thread.thread_id
    )
    run = await _store_run(session, thread, assistant, openai_run)
    run_id_map[openai_run_id] = run
    return run


async def _store_run(
    session: AsyncSession,
    thread: models.Thread,
    assistant: models.Assistant,
    openai_run: Run,
) -> models.Run:
    run = models.Run(
        run_id=openai_run.id,
        thread_id=thread.id,
        assistant_id=assistant.id,
        creator_id=None,
        status=openai_run.status,
        error_code=openai_run.last_error and openai_run.last_error.code,
        error_message=openai_run.last_error and openai_run.last_error.message,
        incomplete_reason=(
            openai_run.incomplete_details and openai_run.incomplete_details.reason
        ),
        model=assistant.model,
        temperature=assistant.temperature,
        instructions=thread.instructions,
        created=datetime.fromtimestamp(openai_run.created_at),
        completed=(
            openai_run.completed_at and datetime.fromtimestamp(openai_run.completed_at)
        ),
        tools_available=thread.tools_available,
        reasoning_effort=assistant.reasoning_effort,
        verbosity=assistant.verbosity,
        messages=[],  # gets filled in later
    )
    session.add(run)
    await session.flush()
    await session.refresh(run)

    return run


async def _fetch_openai_messages_in_thread(
    openai_client: OpenAIClient, openai_thread_id: str
) -> tuple[dict[str, list[Message]], list[Message]]:
    messages_by_run_id: dict[str, list[Message]] = {}
    after: str | Omit = omit
    message_stack: list[Message] = []

    while True:
        response = await openai_client.beta.threads.messages.list(
            thread_id=openai_thread_id, order="asc", after=after
        )

        for message in response.data:
            if message.run_id is not None:
                messages_by_run_id.setdefault(message.run_id, []).extend(
                    message_stack[:] + [message]
                )
                message_stack = []
            else:
                message_stack.append(message)

        if not response.has_more or not response.data:
            break

        after = response.data[-1].id

    return messages_by_run_id, message_stack

async def _store_message(
    session: AsyncSession,
    authz_client: OpenFgaAuthzClient,
    openai_client: OpenAIClient,
    thread: models.Thread,
    assistant: models.Assistant,
    openai_message: Message,
    local_run: models.Run,
    prev_output_index: int,
) -> int:
    existing_local_message = await models.Message.get_by_message_id(
        session, openai_message.id
    )
    if existing_local_message:
        return existing_local_message.output_index

    # TODO: store tool calls

    prev_output_index += 1
    await models.Message.create(
        session,
        {
            "message_id": openai_message.id,
            "message_status": MessageStatus.COMPLETED,
            "role": MessageRole(openai_message.role),
            "created": datetime.fromtimestamp(
                openai_message.created_at, tz=timezone.utc
            ),
            "completed": openai_message.completed_at
            and datetime.fromtimestamp(openai_message.completed_at, tz=timezone.utc),
            "thread_id": thread.id,
            "run_id": local_run.id,
            "assistant_id": thread.assistant_id,
            "user_id": assistant.creator_id,
            "output_index": prev_output_index,  # TODO: needs to be consistent with ToolCall
        },
    )

    # TODO: store message call

    return prev_output_index
