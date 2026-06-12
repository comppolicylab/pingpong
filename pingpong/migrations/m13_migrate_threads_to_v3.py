import logging
from datetime import datetime, timezone
from typing import TypeGuard

from openai import Omit, omit
from openai.types.beta.threads import Message
from openai.types.beta.threads.runs import (
    CodeInterpreterOutputImage,
    CodeInterpreterToolCall,
    FileSearchToolCall,
    ToolCall,
    ToolCallsStepDetails,
)
from openai.types.beta.threads.runs.code_interpreter_tool_call import (
    CodeInterpreterOutput,
    CodeInterpreterOutputLogs,
)
from sqlalchemy.ext.asyncio import AsyncSession

import pingpong.models as models
from pingpong.ai import (
    get_openai_client_by_class_id,
)
from pingpong.schemas import (
    AnnotationType,
    CodeInterpreterOutputType,
    InteractionMode,
    MessagePartType,
    MessageRole,
    MessageStatus,
    ToolCallStatus,
    ToolCallType,
)
from pingpong.server import OpenAIClient

logger = logging.getLogger(__name__)


async def migrate_threads_and_messages_to_v3(session: AsyncSession) -> None:
    async for thread in models.Thread.get_all_by_version_and_interaction_mode(
        session, version_lte=2, interaction_mode=InteractionMode.CHAT
    ):
        try:
            openai_client = await get_openai_client_by_class_id(
                session, thread.class_id
            )
        except Exception as e:
            logger.warning(
                f"Could not get OpenAI client for thread {thread.id} "
                f"(class_id={thread.class_id}): {e} — skipping"
            )
            continue

        await _migrate_thread(session, openai_client, thread)


async def _migrate_thread(
    session: AsyncSession, openai_client: OpenAIClient, thread: models.Thread
) -> None:
    oai_messages = await _fetch_openai_messages_in_thread(
        openai_client, thread.thread_id
    )

    # empty thread, nothing else to migrate
    if not oai_messages:
        thread.version = 3
        thread.thread_id = None
        session.add(thread)
        await session.flush()
        return

    output_index = -1
    for oai_msg in oai_messages:
        output_index = await _store_message_and_run(
            session, openai_client, thread, oai_msg, output_index
        )

    thread.version = 3
    thread.thread_id = None
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

        if not response.has_more:
            break

        if response.data:
            after = response.data[-1].id

    return messages


async def _store_message_and_run(
    session: AsyncSession,
    openai_client: OpenAIClient,
    thread: models.Thread,
    openai_msg: Message,
    current_output_index: int,
) -> int:
    next_output_index = current_output_index + 1

    user_id = await _extract_user_id(openai_msg, thread)
    local_run = await _store_run_and_tool_calls(
        session, openai_client, thread, openai_msg, user_id
    )

    local_message = await models.Message.create(
        session,
        {
            "message_id": openai_msg.id,
            "message_status": MessageStatus.COMPLETED,
            "role": MessageRole(openai_msg.role),
            "created": datetime.fromtimestamp(openai_msg.created_at, tz=timezone.utc),
            "thread_id": thread.id,
            "run_id": local_run.id if local_run else None,
            "assistant_id": thread.assistant_id,
            "user_id": user_id,
            "output_index": next_output_index,
        },
    )

    await _store_message_content(session, local_message, openai_msg)

    await session.flush()
    return next_output_index


async def _extract_user_id(openai_msg: Message, thread: models.Thread) -> int | None:
    user_id: int | None = None
    if openai_msg.metadata and "user_id" in openai_msg.metadata:
        try:
            user_id = int(openai_msg.metadata["user_id"])
        except (ValueError, TypeError):
            assistant: models.Assistant = thread.assistant
            user_id = assistant.creator_id
    return user_id


async def _store_run_and_tool_calls(
    session: AsyncSession,
    openai_client: OpenAIClient,
    thread: models.Thread,
    openai_msg: Message,
    user_id: int | None,
) -> models.Run | None:
    if not openai_msg.run_id:
        return None

    openai_run = await openai_client.beta.threads.runs.retrieve(
        thread_id=thread.thread_id, run_id=openai_msg.run_id
    )

    assistant: models.Assistant = thread.assistant
    local_run = models.Run(
        run_id=openai_msg.run_id,
        thread_id=thread.id,
        assistant_id=thread.assistant_id,
        creator_id=user_id,
        status=openai_run.status,
        error_code=openai_run.last_error and openai_run.last_error.code,
        error_message=openai_run.last_error and openai_run.last_error.message,
        incomplete_reason=(
            openai_run.incomplete_details and openai_run.incomplete_details.reason
        ),
        model=openai_run.model,
        temperature=openai_run.temperature,
        instructions=openai_run.instructions,
        created=datetime.fromtimestamp(openai_run.created_at),
        completed=(
            openai_run.completed_at and datetime.fromtimestamp(openai_run.completed_at)
        ),
        tools_available=thread.tools_available,
        reasoning_effort=assistant.reasoning_effort,
        verbosity=assistant.verbosity,
    )
    session.add(local_run)
    await session.flush()

    await _store_tool_calls(session, openai_client, thread, openai_msg, local_run)

    return local_run


async def _store_tool_calls(
    session: AsyncSession,
    openai_client: OpenAIClient,
    thread: models.Thread,
    openai_msg: Message,
    local_run: models.Run,
) -> None:
    openai_steps = (
        await openai_client.beta.threads.runs.steps.list(
            thread_id=thread.thread_id,
            run_id=openai_msg.run_id,
            include=["step_details.tool_calls[*].file_search.results[*].content"],
        )
    ).data

    for openai_step in openai_steps:
        if not isinstance(openai_step.step_details, ToolCallsStepDetails):
            continue

        for tool_call in openai_step.step_details.tool_calls:
            tool_call_type_map = {
                "file_search": ToolCallType.FILE_SEARCH,
                "code_interpreter": ToolCallType.CODE_INTERPRETER,
            }
            tool_call_type = tool_call_type_map.get(tool_call.type)
            if not tool_call_type:
                continue

            tool_call_db_obj = await models.ToolCall.create(
                session,
                {
                    "tool_call_id": tool_call.id,
                    "type": tool_call_type,
                    "status": ToolCallStatus(openai_step.status),
                    "run_id": local_run.id,
                    "thread_id": thread.id,
                },
            )

            if _is_file_search_tool_call(tool_call) and tool_call.file_search.results:
                for result in tool_call.file_search.results:
                    await models.FileSearchCallResult.create(
                        session,
                        {
                            "tool_call_id": tool_call_db_obj.id,
                            "file_id": result.file_id,
                            "filename": result.file_name,
                            "text": result.content,
                        },
                    )

            elif _is_code_interpreter_tool_call(tool_call):
                await _store_code_interpreter_outputs(
                    session, tool_call_db_obj, tool_call
                )


async def _store_code_interpreter_outputs(
    session: AsyncSession,
    tool_call_db_obj: models.ToolCall,
    tool_call: CodeInterpreterToolCall,
) -> None:
    for output in tool_call.code_interpreter.outputs:
        code_interpreter_output_type_map = {
            "image": CodeInterpreterOutputType.IMAGE,
            "logs": CodeInterpreterOutputType.LOGS,
        }
        code_interpreter_output_type = code_interpreter_output_type_map.get(output.type)
        if not code_interpreter_output_type:
            continue

        output_data = {
            "tool_call_id": tool_call_db_obj.id,
            "output_type": code_interpreter_output_type,
        }

        if _is_code_interpreter_output_image(output):
            await models.CodeInterpreterCallOutput.create(
                session,
                {
                    **output_data,
                    "url": output.image and output.image.file_id,
                },
            )
        elif _is_code_interpreter_output_logs(output):
            await models.CodeInterpreterCallOutput.create(
                session,
                {
                    **output_data,
                    "logs": output.logs,
                },
            )


async def _store_message_content(
    session: AsyncSession,
    local_message: models.Message,
    openai_msg: Message,
) -> None:
    part_index = 0
    for content_block in openai_msg.content:
        if content_block.type == "text":
            await _store_text_part(
                session, local_message, content_block, openai_msg.role, part_index
            )
        elif content_block.type in {"image_file", "image_url"}:
            await _store_image_part(session, local_message, content_block, part_index)
        elif content_block.type == "refusal":
            await models.MessagePart.create(
                session,
                {
                    "message_id": local_message.id,
                    "type": MessagePartType.REFUSAL,
                    "refusal": content_block.refusal,
                    "part_index": part_index,
                },
            )
        part_index += 1


async def _store_text_part(
    session: AsyncSession,
    local_message: models.Message,
    content_block,
    message_role: str,
    part_index: int,
) -> None:
    part_type = (
        MessagePartType.INPUT_TEXT
        if message_role == "user"
        else MessagePartType.OUTPUT_TEXT
    )
    part = await models.MessagePart.create(
        session,
        {
            "message_id": local_message.id,
            "type": part_type,
            "text": content_block.text.value,
            "part_index": part_index,
        },
    )

    annotation_index = 0
    for annotation in content_block.text.annotations:
        annotation_data = {
            "message_part_id": part.id,
            "text": annotation.text,
            "start_index": annotation.start_index,
            "end_index": annotation.end_index,
            "annotation_index": annotation_index,
        }
        if annotation.type == "file_citation":
            await models.Annotation.create(
                session,
                {
                    **annotation_data,
                    "type": AnnotationType.FILE_CITATION,
                    "file_id": annotation.file_citation.file_id,
                },
            )
        elif annotation.type == "file_path":
            await models.Annotation.create(
                session,
                {
                    **annotation_data,
                    "type": AnnotationType.FILE_PATH,
                    "file_id": annotation.file_path.file_id,
                },
            )
        annotation_index += 1


async def _store_image_part(
    session: AsyncSession,
    local_message: models.Message,
    content_block,
    part_index: int,
) -> None:
    image_block_data = {
        "message_id": local_message.id,
        "type": MessagePartType.INPUT_IMAGE,
        "part_index": part_index,
    }
    if content_block.type == "image_file":
        await models.MessagePart.create(
            session,
            {
                **image_block_data,
                "input_image_file_id": content_block.image_file.file_id,
            },
        )
    elif content_block.type == "image_url":
        await models.MessagePart.create(
            session,
            {
                **image_block_data,
                "text": content_block.image_url.url,
            },
        )


def _is_file_search_tool_call(tool_call: ToolCall) -> TypeGuard[FileSearchToolCall]:
    return tool_call.type == "file_search"


def _is_code_interpreter_tool_call(
    tool_call: ToolCall,
) -> TypeGuard[CodeInterpreterToolCall]:
    return tool_call.type == "code_interpreter"


def _is_code_interpreter_output_image(
    interp_output: CodeInterpreterOutput,
) -> TypeGuard[CodeInterpreterOutputImage]:
    return interp_output.type == "image"


def _is_code_interpreter_output_logs(
    interp_output: CodeInterpreterOutput,
) -> TypeGuard[CodeInterpreterOutputLogs]:
    return interp_output.type == "logs"
