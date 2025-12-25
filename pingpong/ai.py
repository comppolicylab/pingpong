import asyncio
import csv
import functools
import hashlib
import io
import json
import logging
from fastapi import UploadFile
import openai
import orjson
from pingpong.ai_models import VERBOSITY_MAP, get_reasoning_effort_map
from pingpong.auth import encode_auth_token
from pingpong.authz.base import AuthzClient
from pingpong.db import db_session_handler
from pingpong.files import (
    _is_vision_supported,
    file_extension_to_mime_type,
    handle_create_file,
)
from pingpong.invite import send_export_download
import pingpong.models as models
from pingpong.prompt import replace_random_blocks
from pingpong.schemas import (
    APIKeyValidationResponse,
    AnnotationType,
    CodeInterpreterOutputType,
    FileSearchToolAnnotationResult,
    MessageStatus,
    ReasoningStatus,
    RunStatus,
    ThreadName,
    NewThreadMessage,
    MessagePartType,
    ToolCallStatus,
    ToolCallType,
    WebSearchActionType,
)
from starlette.requests import ClientDisconnect
from datetime import datetime, timezone
from openai.types.beta.assistant_stream_event import (
    ThreadRunStepCompleted,
    ThreadRunStepFailed,
    ThreadRunFailed,
)
from openai.types.responses import ToolParam, FileSearchToolParam, WebSearchToolParam
from openai._streaming import AsyncStream
from openai.types.responses.tool_param import (
    CodeInterpreter,
    Mcp,
    CodeInterpreterContainerCodeInterpreterToolAuto,
)
from openai.types.responses.response_output_item import (
    ResponseOutputMessage,
    ResponseCodeInterpreterToolCall,
    ResponseFileSearchToolCall,
    ResponseFunctionWebSearch,
    ResponseReasoningItem,
    McpCall,
    McpListTools,
)
from openai.types.responses.response_function_web_search import (
    ActionSearch,
    ActionFind,
    ActionOpenPage,
)
from openai.types.responses.response_output_text import ResponseOutputText
from openai.types.responses.response_stream_event import (
    ResponseStreamEvent,
    ResponseCreatedEvent,
    ResponseFailedEvent,
    ResponseIncompleteEvent,
    ResponseErrorEvent,
    ResponseInProgressEvent,
    ResponseTextDeltaEvent,
    ResponseCompletedEvent,
    ResponseCodeInterpreterCallInProgressEvent,
    ResponseCodeInterpreterCallCodeDeltaEvent,
    ResponseCodeInterpreterCallInterpretingEvent,
    ResponseCodeInterpreterCallCompletedEvent,
    ResponseFileSearchCallInProgressEvent,
    ResponseFileSearchCallSearchingEvent,
    ResponseFileSearchCallCompletedEvent,
    ResponseWebSearchCallInProgressEvent,
    ResponseWebSearchCallSearchingEvent,
    ResponseWebSearchCallCompletedEvent,
    ResponseReasoningSummaryPartAddedEvent,
    ResponseReasoningSummaryTextDeltaEvent,
    ResponseReasoningSummaryPartDoneEvent,
    ResponseMcpCallInProgressEvent,
    ResponseMcpCallArgumentsDeltaEvent,
    ResponseMcpCallCompletedEvent,
    ResponseMcpCallFailedEvent,
    ResponseMcpListToolsInProgressEvent,
    ResponseMcpListToolsCompletedEvent,
    ResponseMcpListToolsFailedEvent,
)
from openai.types.responses.response_input_item_param import (
    ResponseInputItemParam,
    EasyInputMessageParam,
    ResponseInputMessageContentListParam,
    ResponseCodeInterpreterToolCallParam,
    McpListToolsTool as McpListToolsToolParam,
    McpListTools as McpListToolsParam,
    McpCall as McpCallParam,
)
from openai.types.responses.response_output_message_param import (
    ResponseOutputMessageParam,
)
from openai.types.responses.response_input_image_param import ResponseInputImageParam
from openai.types.responses.response_input_text_param import ResponseInputTextParam
from openai.types.responses.response_output_message_param import (
    ResponseOutputTextParam,
    ResponseOutputRefusalParam,
)
from openai.types.responses.response_reasoning_item_param import (
    ResponseReasoningItemParam,
    Summary,
    Content,
)
from openai.types.responses.response_output_text_param import (
    Annotation,
    AnnotationFileCitation,
    AnnotationURLCitation,
    AnnotationContainerFileCitation,
    AnnotationFilePath,
)
from openai.types.responses.response_file_search_tool_call_param import (
    ResponseFileSearchToolCallParam,
    Result,
)
from openai.types.responses.response_code_interpreter_tool_call_param import (
    Output,
    OutputImage,
    OutputLogs,
)
from openai.types.responses.response_function_web_search_param import (
    ResponseFunctionWebSearchParam,
)
from openai.types.shared.reasoning import Reasoning
from openai.types.responses.response_text_config_param import ResponseTextConfigParam
from openai.types.beta.threads import ImageFile, MessageContentPartParam
from openai.types.beta.threads.annotation import FileCitationAnnotation
from openai.types.beta.threads.image_file_content_block import ImageFileContentBlock
from openai.types.beta.threads.image_url_content_block import ImageURLContentBlock
from openai.types.beta.threads.message_content import MessageContent
from openai.types.beta.threads.message_create_params import Attachment
from openai.types.beta.threads.runs import ToolCallsStepDetails, CodeInterpreterToolCall
from openai.types.beta.threads.text_content_block import TextContentBlock
from pingpong.now import NowFn, utcnow
from pingpong.ai_error import get_details_from_api_error
from pingpong.schemas import CodeInterpreterMessage, DownloadExport
from pingpong.config import config
from typing import Dict, Literal, Union, overload
from sqlalchemy.ext.asyncio import AsyncSession
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

logger = logging.getLogger(__name__)
responses_api_transition_logger = logging.getLogger("responses_api_transition")
OpenAIClientType = Union[openai.AsyncClient, openai.AsyncAzureOpenAI]


class GetOpenAIClientException(Exception):
    def __init__(self, detail: str = "", code: int | None = None):
        self.code = code
        self.detail = detail


async def get_openai_client_by_class_id(
    session: AsyncSession, class_id: int
) -> OpenAIClientType:
    result = await models.Class.get_api_key(session, class_id)
    if result.api_key_obj:
        if result.api_key_obj.provider == "openai":
            return get_openai_client(
                result.api_key_obj.api_key,
                provider=result.api_key_obj.provider,  # type: ignore
            )
        elif result.api_key_obj.provider == "azure":
            return get_openai_client(
                result.api_key_obj.api_key,
                provider=result.api_key_obj.provider,  # type: ignore
                endpoint=result.api_key_obj.endpoint,
                api_version=result.api_key_obj.api_version,
            )
        else:
            raise GetOpenAIClientException(
                code=400, detail="Unknown API key provider for class"
            )
    elif result.api_key:
        return get_openai_client(result.api_key)
    else:
        raise GetOpenAIClientException(code=401, detail="No API key for class")


async def upgrade_assistants_model(
    deprecated_model: str, replacement_model: str
) -> None:
    async with config.db.driver.async_session() as session:
        assistants_to_upgrade = await models.Assistant.get_by_model(
            session, deprecated_model
        )
        if not assistants_to_upgrade:
            logger.info(f"No assistants found with model name {deprecated_model}")
            return

        for assistant in assistants_to_upgrade:
            logger.info(
                f"Upgrading model for assistant {assistant.name} ({assistant.assistant_id}) from {deprecated_model} to {replacement_model}"
            )
            async with session.begin_nested() as session_:
                try:
                    # Update the model on OpenAI
                    await update_model_on_openai(session, assistant, replacement_model)
                    # Update the model in the database
                    assistant.model = replacement_model
                    session.add(assistant)
                except Exception as e:
                    logger.exception(
                        f"Failed to upgrade model for assistant {assistant.assistant_id} from {deprecated_model} to {replacement_model}: {e}"
                    )
                    await session_.rollback()
                    continue

        await session.commit()
        logger.info(
            f"Completed upgrading assistant models from {deprecated_model} to {replacement_model}"
        )


async def update_model_on_openai(
    session: AsyncSession, assistant: models.Assistant, new_model: str
) -> None:
    oai_client = await get_openai_client_by_class_id(session, assistant.class_id)
    return await oai_client.beta.assistants.update(
        assistant.assistant_id, model=new_model
    )


def get_azure_model_deployment_name_equivalent(model_name: str) -> str:
    """Get the equivalent model deployment name for Azure models.

    :param model_name: Model name
    :return: Equivalent model deployment name
    """
    match model_name:
        case "gpt-4-turbo":
            return "gpt-4-turbo-2024-04-09"
        case "gpt-4-turbo-preview":
            return "gpt-4-0125-Preview"
    return model_name


def get_original_model_name_by_azure_equivalent(model_name: str) -> str:
    """Get the original model name for Azure models.

    :param model_name: Model deployment name
    :return: Original model name
    """
    match model_name:
        case "gpt-4-turbo-2024-04-09":
            return "gpt-4-turbo"
        case "gpt-4-0125-Preview":
            return "gpt-4-turbo-preview"
    return model_name


async def generate_name(
    cli: openai.AsyncClient, transcript: str, model: str = "gpt-4o-mini"
) -> ThreadName | None:
    """Generate a name for a prompt using the given model.

    :param cli: OpenAI client
    :param prompt: Prompt to generate a name for
    :param model: Model to use
    :return: Generated name
    """
    system_prompt = 'You will be given a transcript between a user and an assistant. Messages the user sent are prepended with "USER", and messages the assistant sent are prepended with "ASSISTANT". Return a title of 3 to 4 words summarizing what the conversation is about. If you are unsure about the conversation topic, set name to None and set can_generate to false. DO NOT RETURN MORE THAN 4 WORDS!'
    try:
        response = await cli.beta.chat.completions.parse(
            messages=[
                {
                    "role": "system",
                    "content": system_prompt,
                },
                {
                    "role": "user",
                    "content": transcript,
                },
            ],
            model=model,
            response_format=ThreadName,
            temperature=0.0,
        )
        return response.choices[0].message.parsed
    except openai.RateLimitError as e:
        raise e
    except openai.BadRequestError:
        # We are typically seeing this error when the Azure content filter
        # is triggered. We should print the message that triggered the error
        # and return None.
        logger.exception(f"Error generating thread name. Message: {transcript}")
        return None
    except openai.APIError:
        logger.exception("Error generating thread name.")
        return None


async def get_thread_conversation_name(
    cli: openai.AsyncClient,
    session: AsyncSession,
    data: NewThreadMessage,
    thread_id: str,
    class_id: str,
    thread_version: int = 2,
) -> str | None:
    if thread_version <= 2:
        messages = await cli.beta.threads.messages.list(
            thread_id, limit=10, order="asc"
        )

        message_str = ""
        for message in messages.data:
            for content in message.content:
                if content.type == "text":
                    message_str += f"{message.role.upper()}: {' '.join(content.text.value.split()[:100])}\n"
                if content.type in ["image_file", "image_url"]:
                    message_str += f"{message.role.upper()}: Uploaded an image file\n"
        message_str += f"USER: {data.message}\n"
        if data.vision_file_ids:
            message_str += "USER: Uploaded an image file\n"
    elif thread_version == 3:
        messages_v3 = await models.Thread.list_messages(
            session=session, thread_id=int(thread_id), limit=10, order="asc"
        )

        message_str = ""
        for message in messages_v3:
            if message.role == "user":
                for content in message.content:
                    if content.type == MessagePartType.INPUT_TEXT:
                        message_str += f"{message.role.upper()}: {' '.join(content.text.split()[:100])}\n"
                    elif content.type == MessagePartType.INPUT_IMAGE:
                        message_str += (
                            f"{message.role.upper()}: Uploaded an image file\n"
                        )
        if data.vision_file_ids:
            message_str += "USER: Uploaded an image file\n"
    else:
        raise ValueError(f"Unsupported thread version: {thread_version}")
    return await generate_thread_name(cli, session, message_str, class_id)


async def get_initial_thread_conversation_name(
    cli: openai.AsyncClient,
    session: AsyncSession,
    message: str | None,
    vision_files: list[str],
    class_id: str,
) -> str | None:
    if not message:
        return None
    message_str = f"USER: {message}\n"
    for _ in vision_files:
        message_str += "USER: Uploaded an image file\n"
    return await generate_thread_name(cli, session, message_str, class_id)


async def generate_thread_name(
    cli: openai.AsyncClient, session: AsyncSession, transcript: str, class_id: str
) -> str | None:
    thread_name = None
    try:
        name_response = await generate_name(cli, transcript)
        thread_name = (
            name_response.name if name_response and name_response.can_generate else None
        )
        return thread_name
    except openai.RateLimitError:
        await models.Class.log_rate_limit_error(session=session, class_id=class_id)
        return None


async def validate_api_key(
    api_key: str,
    provider: Literal["azure", "openai"] = "openai",
    endpoint: str | None = None,
    api_version: str | None = None,
) -> APIKeyValidationResponse:
    """Validate an OpenAI API key.

    :param key: API key to validate
    :return: Whether the key is valid
    """
    if provider == "azure":
        cli = get_openai_client(
            api_key=api_key,
            provider=provider,
            endpoint=endpoint,
            api_version=api_version,
        )
        try:
            response = await cli.models.with_raw_response.list()
            _region = response.headers.get("x-ms-region", None)
            if not _region:
                logger.exception(
                    f"No region found in response headers in Azure API key validation. Response: {response.headers}"
                )
            # NOTE: For the async client: this will become a coroutine in the next major version.
            response.parse()
            return APIKeyValidationResponse(
                valid=True,
                region=_region,
            )
        except openai.AuthenticationError:
            return APIKeyValidationResponse(
                valid=False,
            )
    elif provider == "openai":
        cli = get_openai_client(api_key=api_key, provider=provider)
        try:
            await cli.models.list()
            return APIKeyValidationResponse(
                valid=True,
            )
        except openai.AuthenticationError:
            return APIKeyValidationResponse(
                valid=False,
            )


async def get_ci_messages_from_step(
    cli: openai.AsyncClient, thread_id: str, run_id: str, step_id: str
) -> list[CodeInterpreterMessage]:
    """
    Get code interpreter messages from a thread run step.

    :param cli: OpenAI client
    :param thread_id: Thread ID
    :param run_id: Run ID
    :param step_id: Step ID
    :return: List of code interpreter messages
    """
    run_step = await cli.beta.threads.runs.steps.retrieve(
        thread_id=thread_id, run_id=run_id, step_id=step_id
    )
    if not isinstance(run_step.step_details, ToolCallsStepDetails):
        return []
    messages: list[CodeInterpreterMessage] = []
    for tool_call in run_step.step_details.tool_calls:
        if tool_call.type == "code_interpreter":
            new_message = CodeInterpreterMessage.model_validate(
                {
                    "id": tool_call.id,
                    "assistant_id": run_step.assistant_id,
                    "created_at": run_step.created_at,
                    "content": [
                        {
                            "code": tool_call.code_interpreter.input,
                            "type": "code",
                        }
                    ],
                    "file_search_file_ids": [],
                    "code_interpreter": [],
                    "metadata": {},
                    "object": "thread.message",
                    "role": "assistant",
                    "run_id": run_step.run_id,
                    "thread_id": run_step.thread_id,
                }
            )
            for output in tool_call.code_interpreter.outputs:
                if output.type == "image":
                    new_message.content.append(
                        {
                            "image_file": {"file_id": output.image.file_id},
                            "type": "code_output_image_file",
                        }
                    )
            messages.append(new_message)
    return messages


class BufferedStreamHandler(openai.AsyncAssistantEventHandler):
    def __init__(self, file_names: dict[str, str], *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.__buffer = io.BytesIO()
        self.file_names = file_names

    def enqueue(self, data: Dict) -> None:
        self.__buffer.write(orjson.dumps(data))
        self.__buffer.write(b"\n")

    def flush(self) -> bytes:
        value = self.__buffer.getvalue()
        self.__buffer.truncate(0)
        self.__buffer.seek(0)
        return value

    async def on_image_file_done(self, image_file: ImageFile) -> None:
        self.enqueue(
            {
                "type": "image_file_done",
                "file_id": image_file.file_id,
            }
        )

    async def on_message_created(self, message) -> None:
        self.enqueue(
            {
                "type": "message_created",
                "role": "assistant",
                "message": message.model_dump(),
            }
        )

    async def on_message_delta(self, delta, snapshot) -> None:
        message_delta = delta.model_dump()
        for content in message_delta["content"]:
            if content.get("type") == "text" and content["text"].get("annotations"):
                for annotation in content["text"]["annotations"]:
                    if annotation.get("file_citation"):
                        annotation["file_citation"]["file_name"] = self.file_names.get(
                            annotation["file_citation"]["file_id"], ""
                        )
        self.enqueue(
            {
                "type": "message_delta",
                "delta": message_delta,
            }
        )

    async def on_tool_call_created(self, tool_call) -> None:
        self.enqueue(
            {
                "type": "tool_call_created",
                "tool_call": tool_call
                if isinstance(tool_call, Dict)
                else tool_call.model_dump(),
            }
        )

    async def on_tool_call_delta(self, delta, snapshot) -> None:
        self.enqueue(
            {
                "type": "tool_call_delta",
                "delta": delta.model_dump(),
            }
        )

    async def on_timeout(self) -> None:
        self.enqueue(
            {
                "type": "error",
                "detail": "Stream timed out waiting for response",
            }
        )

    async def on_done(self, run) -> None:
        self.enqueue({"type": "done"})

    async def on_exception(self, exception) -> None:
        self.enqueue(
            {
                "type": "error",
                "detail": str(exception),
            }
        )


async def build_response_input_item_list(
    session: AsyncSession, thread_id: int, uses_reasoning: bool = False
) -> list[ResponseInputItemParam]:
    """Build a list of ResponseInputItem from a thread run step."""
    response_input_items: list[ResponseInputItemParam] = []
    # Store ResponseInputItemParam and time created to sort later
    response_input_items_with_time: list[tuple[datetime, ResponseInputItemParam]] = []
    container_by_last_active_time: dict[int, datetime] = {}
    async for message in models.Thread.list_all_messages_gen(session, thread_id):
        content_list: list[ResponseInputMessageContentListParam] = []
        for content in message.content:
            match content.type:
                case MessagePartType.INPUT_TEXT:
                    content_list.append(
                        ResponseInputTextParam(text=content.text, type="input_text")
                    )
                case MessagePartType.INPUT_IMAGE:
                    content_list.append(
                        ResponseInputImageParam(
                            file_id=content.input_image_file_id, type="input_image"
                        )
                    )
                case MessagePartType.OUTPUT_TEXT:
                    annotations: list[Annotation] = []
                    for annotation in content.annotations:
                        match annotation.type:
                            case AnnotationType.FILE_CITATION:
                                annotations.append(
                                    AnnotationFileCitation(
                                        file_id=annotation.file_id,
                                        filename=annotation.filename,
                                        index=annotation.index or 0,
                                        type="file_citation",
                                    )
                                )
                            case AnnotationType.FILE_PATH:
                                annotations.append(
                                    AnnotationFilePath(
                                        file_path=annotation.file_path,
                                        index=annotation.index or 0,
                                        type="file_path",
                                    )
                                )
                            case AnnotationType.URL_CITATION:
                                annotations.append(
                                    AnnotationURLCitation(
                                        url=annotation.url,
                                        start_index=annotation.start_index or 0,
                                        end_index=annotation.end_index or 0,
                                        title=annotation.title,
                                        type="url_citation",
                                    )
                                )
                            case AnnotationType.CONTAINER_FILE_CITATION:
                                # The API currently rejects
                                # container_file_citation as input
                                continue
                                annotations.append(
                                    AnnotationContainerFileCitation(
                                        file_id=annotation.file_id,
                                        container_id=annotation.container_id,
                                        filename=annotation.filename,
                                        start_index=annotation.start_index or 0,
                                        end_index=annotation.end_index or 0,
                                        type="container_file_citation",
                                        index=0,
                                    )
                                )
                            case _:
                                continue  # Skip unsupported annotation types

                    content_list.append(
                        ResponseOutputTextParam(
                            text=content.text,
                            annotations=annotations,
                            type="output_text",
                        )
                    )
                case MessagePartType.REFUSAL:
                    content_list.append(
                        ResponseOutputRefusalParam(
                            refusal=content.refusal, type="output_refusal"
                        )
                    )
        response_input_items_with_time.append(
            (
                message.created,
                ResponseOutputMessageParam(
                    role=message.role,
                    content=content_list,
                    type="message",
                    id=message.message_id,
                ),
            )
        )

    async for tool_call in models.Thread.list_all_tool_calls_gen(session, thread_id):
        if tool_call.status == ToolCallStatus.INCOMPLETE:
            continue
        match tool_call.type:
            case ToolCallType.CODE_INTERPRETER:
                tool_call_outputs: list[Output] = []
                for output in tool_call.outputs:
                    match output.output_type:
                        case CodeInterpreterOutputType.LOGS:
                            tool_call_outputs.append(
                                OutputLogs(logs=output.logs, type="logs")
                            )
                        case CodeInterpreterOutputType.IMAGE:
                            tool_call_outputs.append(
                                OutputImage(url=output.url, type="image")
                            )
                response_input_items_with_time.append(
                    (
                        tool_call.created,
                        ResponseCodeInterpreterToolCallParam(
                            id=tool_call.tool_call_id,
                            code=tool_call.code,
                            container_id=tool_call.container_id,
                            outputs=tool_call_outputs,
                            status=ToolCallStatus(tool_call.status).value,
                            type="code_interpreter_call",
                        ),
                    )
                )

                existing_time = container_by_last_active_time.get(
                    tool_call.container_id
                )
                candidates: list[datetime] = []
                if existing_time is not None:
                    candidates.append(existing_time)
                if tool_call.created is not None:
                    candidates.append(tool_call.created)
                if getattr(tool_call, "completed", None) is not None:
                    candidates.append(tool_call.completed)
                if candidates:
                    container_by_last_active_time[tool_call.container_id] = max(
                        candidates
                    )

            case ToolCallType.FILE_SEARCH:
                file_search_results: list[Result] = []
                for result in tool_call.results:
                    file_search_results.append(
                        Result(
                            attributes=json.loads(result.attributes)
                            if result.attributes
                            else {},
                            file_id=result.file_id,
                            filename=result.filename,
                            score=result.score,
                            text=result.text,
                        )
                    )
                response_input_items_with_time.append(
                    (
                        tool_call.created,
                        ResponseFileSearchToolCallParam(
                            id=tool_call.tool_call_id,
                            queries=json.loads(tool_call.queries)
                            if tool_call.queries
                            else [],
                            status=ToolCallStatus(tool_call.status).value,
                            results=file_search_results,
                            type="file_search_call",
                        ),
                    )
                )

            case ToolCallType.WEB_SEARCH:
                action_rec = (
                    tool_call.web_search_actions[0]
                    if tool_call.web_search_actions
                    else None
                )

                action = None
                if action_rec:
                    match action_rec.type:
                        case WebSearchActionType.SEARCH:
                            action = ActionSearch(
                                type="search",
                                query=action_rec.query or "",
                            )
                        case WebSearchActionType.OPEN_PAGE:
                            action = ActionOpenPage(
                                type="open_page",
                                url=action_rec.url or "",
                            )
                        case WebSearchActionType.FIND:
                            action = ActionFind(
                                type="find",
                                pattern=action_rec.pattern or "",
                                url=action_rec.url or "",
                            )
                        case _:
                            action = None

                response_input_items_with_time.append(
                    (
                        tool_call.created,
                        ResponseFunctionWebSearchParam(
                            id=tool_call.tool_call_id,
                            action=action,
                            status=ToolCallStatus(tool_call.status).value,
                            type="web_search_call",
                        ),
                    )
                )

            case ToolCallType.MCP_SERVER:
                server_label = tool_call.mcp_server_label or (
                    tool_call.mcp_server_tool.server_label
                    if tool_call.mcp_server_tool
                    else None
                )
                if not server_label:
                    logger.warning(
                        "Skipping MCP tool call %s due to missing server label.",
                        tool_call.tool_call_id,
                    )
                    continue
                try:
                    error = json.loads(tool_call.error) if tool_call.error else None
                except json.JSONDecodeError:
                    error = {"message": tool_call.error}
                response_input_items_with_time.append(
                    (
                        tool_call.created,
                        McpCallParam(
                            id=tool_call.tool_call_id,
                            arguments=tool_call.mcp_arguments,
                            name=tool_call.mcp_tool_name,
                            server_label=server_label,
                            type="mcp_call",
                            approval_request_id=None,
                            error=error,
                            output=tool_call.mcp_output,
                            status=ToolCallStatus(tool_call.status).value,
                        ),
                    )
                )
            case ToolCallType.MCP_LIST_TOOLS:
                server_label = tool_call.mcp_server_label or (
                    tool_call.mcp_server_tool.server_label
                    if tool_call.mcp_server_tool
                    else None
                )
                if not server_label:
                    logger.warning(
                        "Skipping MCP list tools call %s due to missing server label.",
                        tool_call.tool_call_id,
                    )
                    continue
                mcp_tools: list[McpListToolsToolParam] = []
                for tool in tool_call.mcp_tools_listed:
                    mcp_tools.append(
                        McpListToolsToolParam(
                            input_schema=json.loads(tool.input_schema)
                            if tool.input_schema
                            else {},
                            name=tool.name,
                            description=tool.description,
                            annotations=json.loads(tool.annotations)
                            if tool.annotations
                            else {},
                        )
                    )
                try:
                    error = json.loads(tool_call.error) if tool_call.error else None
                except json.JSONDecodeError:
                    error = {"message": tool_call.error}

                response_input_items_with_time.append(
                    (
                        tool_call.created,
                        McpListToolsParam(
                            id=tool_call.tool_call_id,
                            server_label=server_label,
                            tools=mcp_tools,
                            type="mcp_list_tools",
                            error=error,
                        ),
                    )
                )

    async for reasoning in models.Thread.list_all_reasoning_steps_gen(
        session, thread_id
    ):
        summary_array: list[Summary] = []
        for summary_step in reasoning.summary_parts:
            summary_array.append(
                Summary(
                    text=summary_step.summary_text,
                    type="summary_text",
                )
            )

        content_array: list[Content] = []
        for content_step in reasoning.content_parts:
            content_array.append(
                Content(
                    text=content_step.content_text,
                    type="reasoning_text",
                )
            )

        response_input_items_with_time.append(
            (
                reasoning.created,
                ResponseReasoningItemParam(
                    id=reasoning.reasoning_id,
                    content=content_array if content_array else None,
                    summary=summary_array if summary_array else [],
                    encrypted_content=reasoning.encrypted_content,
                    type="reasoning",
                ),
            )
        )
    # Sort by created time
    response_input_items_with_time.sort(key=lambda x: x[0])
    # Extract the ResponseInputItemParam from the sorted list
    response_input_items.extend(item for _, item in response_input_items_with_time)

    def convert_to_message(
        item: ResponseCodeInterpreterToolCallParam, uses_reasoning: bool
    ) -> EasyInputMessageParam:
        tool_call_outputs: str = ""
        for output in item["outputs"] or []:
            match output["type"]:
                case "logs":
                    tool_call_outputs += f"LOGS: {output['logs']}\n"
                case "image":
                    tool_call_outputs += "Generated an image\n"

        return EasyInputMessageParam(
            role="developer" if uses_reasoning else "system",
            content=f"The assistant made use of the code interpreter tool.\n CODE RUN: {item['code']} \n OUTPUTS: {tool_call_outputs}",
        )

    for item in response_input_items:
        if item["type"] == "code_interpreter_call":
            if (
                item["container_id"] not in container_by_last_active_time
                or (
                    utcnow() - container_by_last_active_time[item["container_id"]]
                ).total_seconds()
                > 19 * 60
            ):
                response_input_items[response_input_items.index(item)] = (
                    convert_to_message(item, uses_reasoning)
                )
    return response_input_items


class BufferedResponseStreamHandler:
    def __init__(
        self,
        auth: AuthzClient,
        cli: openai.AsyncClient,
        run_id: int,
        run_status: RunStatus,
        prev_output_index: int,
        file_names: dict[str, str],
        class_id: int,
        thread_id: int,
        assistant_id: int,
        user_id: int,
        mcp_server_tools_by_server_label: dict[str, models.MCPServerTool] | None = None,
        user_auth: str | None = None,
        anonymous_link_auth: str | None = None,
        anonymous_user_auth: str | None = None,
        anonymous_session_id: int | None = None,
        anonymous_link_id: int | None = None,
        show_file_search_result_quotes: bool | None = None,
        show_file_search_document_names: bool | None = None,
        show_file_search_queries: bool | None = None,
        show_web_search_sources: bool | None = None,
        show_web_search_actions: bool | None = None,
        show_reasoning_summaries: bool | None = None,
        *args,
        **kwargs,
    ):
        self.__buffer = io.BytesIO()
        self.file_names = file_names
        self.auth = auth
        self.openai_cli = cli
        self.class_id = class_id
        self.user_id = user_id
        self.user_auth = user_auth
        self.anonymous_link_auth = anonymous_link_auth
        self.anonymous_user_auth = anonymous_user_auth
        self.anonymous_session_id = anonymous_session_id
        self.anonymous_link_id = anonymous_link_id
        self.run_id: int | None = run_id
        self.run_status: RunStatus | None = run_status
        self.message_id: int | None = None
        self.message_created_at: datetime | None = None
        self.message_part_id: int | None = None
        self.prev_output_index = prev_output_index
        self.tool_call_id: int | None = None
        self.tool_call_external_id: int | None = None
        self.reasoning_id: int | None = None
        self.reasoning_external_id: str | None = None
        self.prev_reasoning_summary_part_index = -1
        self.current_reasoning_summary_index: int | None = None
        self.current_summary_part_id: int | None = None
        self.prev_reasoning_content_part_index = -1
        self.current_reasoning_content_index: int | None = None
        self.thread_id: int = thread_id
        self.assistant_id: int = assistant_id
        self.mcp_server_tools_by_server_label = mcp_server_tools_by_server_label or {}
        self.prev_part_index = -1
        self.file_search_results: dict[str, FileSearchToolAnnotationResult] = {}
        self.file_ids_file_citation_annotation: set[str] = set()
        self.force_stopped = False
        self.force_stop_incomplete_reason: str | None = None
        self.last_output_item_type: str | None = None
        self.show_file_search_result_quotes = (
            show_file_search_result_quotes
            if show_file_search_result_quotes is not None
            else False
        )
        self.show_file_search_document_names = (
            show_file_search_document_names
            if show_file_search_document_names is not None
            else True
        )
        self.show_file_search_queries = (
            show_file_search_queries if show_file_search_queries is not None else False
        )
        self.show_reasoning_summaries = (
            show_reasoning_summaries if show_reasoning_summaries is not None else False
        )
        self.show_web_search_sources = (
            show_web_search_sources if show_web_search_sources is not None else True
        )
        self.show_web_search_actions = (
            show_web_search_actions if show_web_search_actions is not None else True
        )

    def enqueue(self, data: Dict) -> None:
        self.__buffer.write(orjson.dumps(data))
        self.__buffer.write(b"\n")

    def flush(self) -> bytes:
        value = self.__buffer.getvalue()
        self.__buffer.truncate(0)
        self.__buffer.seek(0)
        return value

    async def on_response_created(self, data: ResponseCreatedEvent):
        if not self.run_id:
            logger.exception(
                f"Received response created event without a cached run. Data: {data}"
            )
            return

        @db_session_handler
        async def update_run_on_response_created(session: AsyncSession):
            if not self.run_id:
                return
            await models.Run.update_run_id_status(
                session,
                id_=self.run_id,
                run_id=data.response.id,
                status=RunStatus(data.response.status),
            )
            await session.commit()

        await update_run_on_response_created()
        self.run_status = RunStatus(data.response.status)

    async def on_response_in_progress(self, data: ResponseInProgressEvent):
        if not self.run_id:
            logger.exception(
                f"Received response in progress event without a cached run. Data: {data}"
            )
            return

        @db_session_handler
        async def update_run_on_response_in_progress(session: AsyncSession):
            if not self.run_id:
                return
            await models.Run.update_status(
                session=session,
                id=self.run_id,
                status=RunStatus(data.response.status),
            )
            await session.commit()

        await update_run_on_response_in_progress()
        self.run_status = RunStatus(data.response.status)

    async def on_output_message_created(self, data: ResponseOutputMessage):
        if not self.run_id:
            logger.exception(
                f"Received output message created event without a cached run. Data: {data}"
            )
            return
        if self.message_id:
            logger.exception(
                f"Received output message created event with cached message. Data: {data}"
            )
            return

        if self.last_output_item_type == "message":
            logger.warning(
                "RESPONSES_MULTI_MESSAGE_CATCH: Received consecutive assistant messages in a single response. "
                "Stopping after detecting back-to-back messages."
            )
            await self.stop_after_additional_output_message()
            return

        self.prev_output_index += 1
        self.last_output_item_type = "message"

        message_data = {
            "output_index": self.prev_output_index,
            "thread_id": self.thread_id,
            "run_id": self.run_id,
            "message_id": data.id,
            "message_status": MessageStatus(data.status),
            "assistant_id": self.assistant_id,
            "role": data.role,
            "created": utcnow(),
        }

        @db_session_handler
        async def add_message_on_output_message_created(session: AsyncSession):
            message = await models.Message.create(session=session, data=message_data)
            await session.commit()
            return message

        message = await add_message_on_output_message_created()
        self.message_id = message.id
        self.message_created_at = message.created

    async def on_output_text_part_created(self, data: ResponseOutputText):
        if not self.run_id:
            logger.exception(
                f"Received text part created event without a cached run. Data: {data}"
            )
            return
        if not self.message_id:
            logger.exception(
                f"Received text part created without a cached message. Data: {data}"
            )
            return
        if self.message_part_id:
            logger.exception(
                f"Received text part created with a cached message part. Data: {data}"
            )
            return

        self.prev_part_index += 1

        part_data = {
            "message_id": self.message_id,
            "part_index": self.prev_part_index,
            "type": MessagePartType(data.type),
            "text": data.text,
        }

        @db_session_handler
        async def add_message_part_on_output_text_part_created(session: AsyncSession):
            message_part = await models.MessagePart.create(
                session=session, data=part_data
            )
            await session.commit()
            return message_part

        message_part = await add_message_part_on_output_text_part_created()
        self.message_part_id = message_part.id

        self.enqueue(
            {
                "type": "message_created",
                "role": "assistant",
                "message": {
                    "id": str(self.message_id),
                    "thread_id": str(self.thread_id),
                    "assistant_id": None,
                    "run_id": str(self.run_id),
                    "created_at": self.message_created_at.timestamp()
                    if self.message_created_at
                    else None,
                    "object": "thread.message",
                    "role": "assistant",
                    "content": [],
                    "status": "in_progress",
                    "output_index": self.prev_output_index,
                },
            }
        )

    async def on_output_text_delta(self, data: ResponseTextDeltaEvent):
        if not self.message_part_id:
            logger.exception(
                f"Received text delta without a cached message part. Data: {data}"
            )
            return

        @db_session_handler
        async def update_message_part_on_output_text_delta(session: AsyncSession):
            if not self.message_part_id:
                return
            await models.MessagePart.add_text_delta(
                session=session, id_=self.message_part_id, text_delta=data.delta
            )
            await session.commit()

        await update_message_part_on_output_text_delta()
        self.enqueue(
            {
                "type": "message_delta",
                "delta": {
                    "content": [
                        {
                            "index": 0,
                            "type": "text",
                            "text": {
                                "value": data.delta,
                                "annotations": [],
                            },
                        },
                    ],
                    "role": None,
                },
            }
        )

    async def on_output_text_container_file_citation_added(
        self, data: AnnotationContainerFileCitation, annotation_index: int | None = None
    ):
        if not self.run_id:
            logger.exception(
                f"Received text container file citation added event without a cached run. Data: {data}"
            )
            return

        file_content = await self.openai_cli.containers.files.content.retrieve(
            file_id=data["file_id"], container_id=data["container_id"]
        )
        extension = file_extension_to_mime_type(data["filename"].split(".")[-1])
        upload_file = UploadFile(
            file=io.BytesIO(file_content.content),
            filename=data["filename"] or f"container_file_{data['file_id']}",
            headers={
                "content-type": file_extension_to_mime_type(
                    data["filename"].split(".")[-1]
                )
            },
        )

        @db_session_handler
        async def create_file_on_output_text_container_file_citation_added(
            session_: AsyncSession,
        ):
            file = await handle_create_file(
                session=session_,
                authz=self.auth,
                oai_client=self.openai_cli,
                upload=upload_file,
                class_id=self.class_id,
                uploader_id=self.user_id,
                private=True,
                purpose="vision"
                if extension and _is_vision_supported(extension)
                else "assistants",
                user_auth=self.user_auth,
                anonymous_link_auth=self.anonymous_link_auth,
                anonymous_user_auth=self.anonymous_user_auth,
                anonymous_session_id=self.anonymous_session_id,
                anonymous_link_id=self.anonymous_link_id,
            )
            await session_.commit()
            return file

        file = await create_file_on_output_text_container_file_citation_added()
        if not file:
            logger.error(f"Failed to create file from citation. Data: {data}")
            return

        @db_session_handler
        async def add_code_interpreter_files_on_output_text_container_file_citation_added(
            session: AsyncSession,
        ):
            if file.code_interpreter_file_id:
                await models.Thread.add_code_interpreter_files(
                    session=session,
                    thread_id=self.thread_id,
                    file_ids=[file.code_interpreter_file_id],
                )
                await session.commit()

        if file.code_interpreter_file_id:
            await add_code_interpreter_files_on_output_text_container_file_citation_added()

        @db_session_handler
        async def add_image_files_on_output_text_container_file_citation_added(
            session: AsyncSession,
        ):
            if file.vision_file_id:
                await models.Thread.add_image_files(
                    session=session,
                    thread_id=self.thread_id,
                    file_ids=[file.vision_file_id],
                )
                await session.commit()

        if file.vision_file_id:
            await add_image_files_on_output_text_container_file_citation_added()

        if not self.message_part_id:
            logger.exception(
                f"Received file citation annotation without a cached message part. Data: {data}"
            )
            return

        annotation_data = {
            "type": AnnotationType.CONTAINER_FILE_CITATION,
            "file_id": file.file_id,
            "file_object_id": file.id if not file.vision_file_id else None,
            "vision_file_id": file.vision_file_id,
            "vision_file_object_id": file.id if file.vision_file_id else None,
            "filename": file.name,
            "container_id": data["container_id"],
            "start_index": data["start_index"],
            "end_index": data["end_index"],
            "annotation_index": annotation_index,
            "message_part_id": self.message_part_id,
        }

        @db_session_handler
        async def add_cached_message_part_on_output_text_container_file_citation_added(
            session_: AsyncSession,
        ):
            await models.Annotation.create(session=session_, data=annotation_data)
            await session_.commit()

        await add_cached_message_part_on_output_text_container_file_citation_added()

        if file.vision_file_id:
            self.enqueue(
                {
                    "type": "message_delta",
                    "delta": {
                        "content": [
                            {
                                "type": "image_file",
                                "image_file": {
                                    "file_id": str(file.vision_file_id),
                                },
                            },
                        ],
                        "role": None,
                    },
                }
            )
        else:
            self.enqueue(
                {
                    "type": "message_delta",
                    "delta": {
                        "content": [
                            {
                                "index": 0,
                                "type": "text",
                                "text": {
                                    "value": "",
                                    "annotations": [
                                        {
                                            "type": "file_path",
                                            "end_index": data["end_index"],
                                            "start_index": data["start_index"],
                                            "file_path": {"file_id": str(file.id)},
                                            "text": "",
                                        }
                                    ],
                                },
                            },
                        ],
                        "role": None,
                    },
                }
            )

    async def on_output_text_file_citation_added(
        self, data: AnnotationFileCitation, annotation_index: int | None = None
    ):
        if not self.message_part_id:
            logger.exception(
                f"Received file citation annotation without a cached message part. Data: {data}"
            )
            return

        annotation_data = {
            "message_part_id": self.message_part_id,
            "type": AnnotationType.FILE_CITATION,
            "file_id": data["file_id"],
            "filename": data["filename"],
            "index": data["index"],
            "annotation_index": annotation_index,
        }

        @db_session_handler
        async def add_cached_message_part_on_output_text_file_citation_added(
            session_: AsyncSession,
        ):
            await models.Annotation.create(session=session_, data=annotation_data)
            await session_.commit()

        await add_cached_message_part_on_output_text_file_citation_added()

        _file_record = self.file_search_results.get(data["file_id"])
        if _file_record:
            if data["file_id"] not in self.file_ids_file_citation_annotation:
                self.file_ids_file_citation_annotation.add(data["file_id"])
                if not self.show_file_search_document_names:
                    return
                self.enqueue(
                    {
                        "type": "message_delta",
                        "delta": {
                            "content": [
                                {
                                    "index": 0,
                                    "type": "text",
                                    "text": {
                                        "value": "",
                                        "annotations": [
                                            {
                                                "type": "file_citation",
                                                "end_index": 0,
                                                "start_index": 0,
                                                "file_citation": {
                                                    "file_id": data["file_id"],
                                                    "file_name": data["filename"],
                                                    "quote": _file_record.text
                                                    if self.show_file_search_result_quotes
                                                    else "",
                                                },
                                                "text": "responses_v3",
                                            }
                                        ],
                                    },
                                },
                            ],
                            "role": None,
                        },
                    }
                )

    async def on_output_text_url_citation_added(
        self, data: AnnotationURLCitation, annotation_index: int | None = None
    ):
        if not self.message_part_id:
            logger.exception(
                f"Received URL citation annotation without a cached message part. Data: {data}"
            )
            return

        annotation_data = {
            "message_part_id": self.message_part_id,
            "type": AnnotationType.URL_CITATION,
            "end_index": data["end_index"],
            "start_index": data["start_index"],
            "title": data["title"],
            "url": data["url"],
            "annotation_index": annotation_index,
        }

        @db_session_handler
        async def add_cached_message_part_on_output_text_url_citation_added(
            session_: AsyncSession,
        ):
            await models.Annotation.create(session=session_, data=annotation_data)
            await session_.commit()

        await add_cached_message_part_on_output_text_url_citation_added()

        self.enqueue(
            {
                "type": "message_delta",
                "delta": {
                    "content": [
                        {
                            "index": 0,
                            "type": "text",
                            "text": {
                                "value": "",
                                "annotations": [
                                    {
                                        "type": "url_citation",
                                        "end_index": data["end_index"],
                                        "start_index": data["start_index"],
                                        "url": data["url"],
                                        "title": data["title"],
                                    }
                                ],
                            },
                        },
                    ],
                    "role": None,
                },
            }
        )

    async def on_output_text_part_done(self, data: ResponseOutputText):
        if not self.message_part_id:
            logger.exception(
                f"Received text part done event without a cached message part. Data: {data}"
            )
            return

        if not self.message_id:
            logger.exception(
                f"Received text part done event without a cached message. Data: {data}"
            )
            return

        self.message_part_id = None

    async def on_output_message_done(self, data: ResponseOutputMessage):
        if not self.run_id:
            logger.exception(
                f"Received output message done event without a cached run. Data: {data}"
            )
            return
        if not self.message_id:
            logger.exception(
                f"Received output message done event without a cached message. Data: {data}"
            )
            return

        if self.message_part_id:
            logger.exception(
                f"Output message done event received with a cached message part. Data: {data}"
            )
            self.message_part_id = None

        completed_time = utcnow()

        @db_session_handler
        async def add_cached_message_add_cached_message(session_: AsyncSession):
            if not self.message_id:
                return
            await models.Message.mark_status(
                session_,
                self.message_id,
                MessageStatus(data.status),
                completed=completed_time,
            )
            await session_.commit()

        await add_cached_message_add_cached_message()
        self.message_id = None

    async def _finalize_active_message(
        self, status: MessageStatus = MessageStatus.COMPLETED
    ) -> None:
        if not self.message_id:
            self.message_part_id = None
            return

        completed_time = utcnow()

        @db_session_handler
        async def finalize_message(session_: AsyncSession):
            if not self.message_id:
                return
            await models.Message.mark_status(
                session_,
                self.message_id,
                status,
                completed=completed_time,
            )
            await session_.commit()

        await finalize_message()
        self.message_id = None
        self.message_part_id = None

    async def stop_after_additional_output_message(self) -> None:
        if self.force_stopped:
            return
        self.force_stopped = True
        self.force_stop_incomplete_reason = "multi_message_truncate"
        logger.info(
            "RESPONSES_MULTI_MESSAGE_TRUNCATE: Stopping response due to multiple output messages."
        )
        await self._finalize_active_message()
        await self.on_response_completed(None)

    async def on_code_interpreter_tool_call_created(
        self, data: ResponseCodeInterpreterToolCall
    ):
        if not self.run_id:
            logger.exception(
                f"Received code interpreter tool call created event without a cached run. Data: {data}"
            )
            return
        if self.tool_call_id:
            logger.exception(
                f"Received code interpreter tool call created with an existing tool call. Data: {data}"
            )
            return

        self.prev_output_index += 1
        self.last_output_item_type = "code_interpreter_call"

        tool_call_data = {
            "run_id": self.run_id,
            "tool_call_id": data.id,
            "type": ToolCallType.CODE_INTERPRETER,
            "status": ToolCallStatus(data.status),
            "thread_id": self.thread_id,
            "output_index": self.prev_output_index,
            "container_id": data.container_id,
            "code": data.code,
            "created": utcnow(),
        }

        @db_session_handler
        async def add_cached_tool_call_on_code_interpreter_tool_call_created(
            session_: AsyncSession,
        ):
            tool_call = await models.ToolCall.create(session_, tool_call_data)
            await session_.commit()
            return tool_call

        tool_call = await add_cached_tool_call_on_code_interpreter_tool_call_created()
        self.tool_call_id = tool_call.id
        self.tool_call_external_id = tool_call.tool_call_id

        self.enqueue(
            {
                "type": "tool_call_created",
                "tool_call": {
                    "id": str(data.id),
                    "index": self.prev_output_index,
                    "output_index": self.prev_output_index,
                    "type": "code_interpreter",
                    "code_interpreter": {"input": data.code or "", "outputs": None},
                    "status": data.status,
                    "run_id": str(self.run_id),
                },
            }
        )

    async def on_code_interpreter_tool_call_in_progress(
        self, data: ResponseCodeInterpreterCallInProgressEvent
    ):
        if not self.tool_call_id:
            logger.exception(
                f"Received code interpreter tool call in progress without a current tool call. Data: {data}"
            )
            return
        if self.tool_call_external_id != data.item_id:
            logger.exception(
                f"Received code interpreter tool call in progress with a different tool call ID. Data: {data}"
            )
            return

        @db_session_handler
        async def add_cached_tool_call_on_code_interpreter_tool_call_in_progress(
            session_: AsyncSession,
        ):
            if not self.tool_call_id:
                return
            await models.ToolCall.update_status(
                session_, self.tool_call_id, ToolCallStatus.IN_PROGRESS
            )
            await session_.commit()

        await add_cached_tool_call_on_code_interpreter_tool_call_in_progress()

    async def on_code_interpreter_tool_call_code_delta(
        self, data: ResponseCodeInterpreterCallCodeDeltaEvent
    ):
        if not self.tool_call_id:
            logger.exception(
                f"Received code interpreter tool call code delta without a current tool call. Data: {data}"
            )
            return
        if self.tool_call_external_id != data.item_id:
            logger.exception(
                f"Received code interpreter tool call code delta with a different tool call ID. Data: {data}"
            )
            return

        @db_session_handler
        async def add_cached_tool_call_on_code_interpreter_tool_call_in_progress(
            session_: AsyncSession,
        ):
            if not self.tool_call_id:
                return
            await models.ToolCall.add_code_delta(
                session_, self.tool_call_id, data.delta
            )
            await session_.commit()

        await add_cached_tool_call_on_code_interpreter_tool_call_in_progress()

        self.enqueue(
            {
                "type": "tool_call_delta",
                "delta": {
                    "index": data.output_index,
                    "type": "code_interpreter",
                    "id": data.item_id,
                    "code_interpreter": {"input": data.delta, "outputs": None},
                },
            }
        )

    async def on_code_interpreter_tool_call_interpreting(
        self, data: ResponseCodeInterpreterCallInterpretingEvent
    ):
        if not self.tool_call_id:
            logger.exception(
                f"Received code interpreter tool call interpreting without a current tool call. Data: {data}"
            )
            return
        if self.tool_call_external_id != data.item_id:
            logger.exception(
                f"Received code interpreter tool call interpreting with a different tool call ID. Data: {data}"
            )
            return

        @db_session_handler
        async def add_cached_tool_call_on_code_interpreter_tool_call_interpreting(
            session_: AsyncSession,
        ):
            if not self.tool_call_id:
                return
            await models.ToolCall.update_status(
                session_, self.tool_call_id, ToolCallStatus.INTERPRETING
            )
            await session_.commit()

        await add_cached_tool_call_on_code_interpreter_tool_call_interpreting()

    async def on_code_interpreter_tool_call_completed(
        self, data: ResponseCodeInterpreterCallCompletedEvent
    ):
        if not self.tool_call_id:
            logger.exception(
                f"Received code interpreter tool call completed without a current tool call. Data: {data}"
            )
            return
        if self.tool_call_external_id != data.item_id:
            logger.exception(
                f"Received code interpreter tool call completed with a different tool call ID. Data: {data}"
            )
            return

        completed_at = utcnow()

        @db_session_handler
        async def add_cached_tool_call_on_code_interpreter_tool_call_completed(
            session_: AsyncSession,
        ):
            if not self.tool_call_id:
                return
            await models.ToolCall.update_status(
                session_,
                self.tool_call_id,
                ToolCallStatus.COMPLETED,
                completed=completed_at,
            )
            await session_.commit()

        await add_cached_tool_call_on_code_interpreter_tool_call_completed()

    async def on_code_interpreter_tool_call_done(
        self, data: ResponseCodeInterpreterToolCall
    ):
        if not self.run_id:
            logger.exception(
                f"Received code interpreter tool call done without a cached run. Data: {data}"
            )
            return
        if not self.tool_call_id:
            logger.exception(
                f"Received code interpreter tool call done without a current tool call. Data: {data}"
            )
            return
        if self.tool_call_external_id != data.id:
            logger.exception(
                f"Received code interpreter tool call done with a different tool call ID. Data: {data}"
            )
            return

        @db_session_handler
        async def add_code_interpreter_call_output(session_: AsyncSession, data: dict):
            await models.CodeInterpreterCallOutput.create(session_, data)
            await session_.commit()

        if data.outputs:
            for output in data.outputs:
                match output.type:
                    case "image":
                        if not output.url:
                            logger.warning(
                                f"Received image output without a URL. Data: {output}"
                            )
                            return
                        image_data = {
                            "tool_call_id": self.tool_call_id,
                            "output_type": CodeInterpreterOutputType.IMAGE,
                            "url": output.url,
                            "created": utcnow(),
                        }
                        await add_code_interpreter_call_output(image_data)
                        self.enqueue(
                            {
                                "type": "tool_call_delta",
                                "delta": {
                                    "index": self.prev_output_index,
                                    "type": "code_interpreter",
                                    "id": data.id,
                                    "code_interpreter": {
                                        "input": None,
                                        "outputs": [
                                            {
                                                "type": "code_output_image_url",
                                                "url": output.url,
                                            }
                                        ],
                                    },
                                },
                            }
                        )
                    case "logs":
                        logs_data = {
                            "tool_call_id": self.tool_call_id,
                            "output_type": CodeInterpreterOutputType.LOGS,
                            "created": utcnow(),
                            "logs": output.logs,
                        }
                        await add_code_interpreter_call_output(logs_data)

                        self.enqueue(
                            {
                                "type": "tool_call_delta",
                                "delta": {
                                    "index": self.prev_output_index,
                                    "type": "code_interpreter",
                                    "id": data.id,
                                    "code_interpreter": {
                                        "input": None,
                                        "outputs": [
                                            {
                                                "type": "code_output_logs",
                                                "logs": output.logs,
                                            }
                                        ],
                                    },
                                },
                            }
                        )

        @db_session_handler
        async def add_cached_tool_call_on_code_interpreter_tool_call_done(
            session_: AsyncSession,
        ):
            if not self.tool_call_id:
                return
            await models.ToolCall.update_status(
                session_,
                self.tool_call_id,
                ToolCallStatus(data.status),
            )
            await session_.commit()

        await add_cached_tool_call_on_code_interpreter_tool_call_done()
        self.tool_call_id = None
        self.tool_call_external_id = None

    def get_action_payload(
        self,
        action: ActionSearch | ActionFind | ActionOpenPage | None,
    ):
        if not action:
            return None

        match action.type:
            case "search":
                return {
                    "type": WebSearchActionType.SEARCH.value,
                    "query": action.query,
                    "sources": [{"url": source.url} for source in action.sources or []]
                    if self.show_web_search_sources
                    else [],
                }
            case "find":
                return {
                    "type": WebSearchActionType.FIND.value,
                    "pattern": action.pattern,
                    "url": action.url,
                }
            case "open_page":
                return {
                    "type": WebSearchActionType.OPEN_PAGE.value,
                    "url": action.url,
                }
            case _:
                return None
        return None

    async def on_mcp_tool_call_created(self, data: McpCall):
        if not self.run_id:
            logger.exception(
                f"Received MCP tool call created event without a cached run. Data: {data}"
            )
            return

        if self.tool_call_id:
            logger.exception(
                f"Received MCP tool call created with an existing tool call. Data: {data}"
            )
            return

        self.prev_output_index += 1
        self.last_output_item_type = "mcp_call"

        mcp_server_tool = self.mcp_server_tools_by_server_label.get(data.server_label)
        if not mcp_server_tool:
            logger.exception(
                f"Received MCP tool call created for unknown MCP server label: {data.server_label}. Data: {data}"
            )
            return

        tool_call_data = {
            "run_id": self.run_id,
            "tool_call_id": data.id,
            "type": ToolCallType.MCP_SERVER,
            "status": ToolCallStatus(data.status),
            "thread_id": self.thread_id,
            "output_index": self.prev_output_index,
            "mcp_server_tool_id": mcp_server_tool.id,
            "mcp_server_label": data.server_label,
            "mcp_tool_name": data.name,
            "mcp_arguments": data.arguments,
            "mcp_output": data.output,
            "created": utcnow(),
        }

        @db_session_handler
        async def add_cached_tool_call_on_mcp_tool_call_created(
            session_: AsyncSession,
        ):
            tool_call = await models.ToolCall.create(session_, tool_call_data)
            await session_.commit()
            return tool_call

        tool_call = await add_cached_tool_call_on_mcp_tool_call_created()
        self.tool_call_id = tool_call.id
        self.tool_call_external_id = tool_call.tool_call_id

        self.enqueue(
            {
                "type": "tool_call_created",
                "tool_call": {
                    "id": str(data.id),
                    "index": self.prev_output_index,
                    "output_index": self.prev_output_index,
                    "type": "mcp_call",
                    "server_label": data.server_label,
                    "server_name": mcp_server_tool.display_name,
                    "name": data.name,
                    "arguments": data.arguments,
                    "output": data.output,
                    "error": data.error,
                    "status": data.status,
                    "run_id": str(self.run_id),
                },
            }
        )

    async def on_mcp_tool_call_in_progress(self, data: ResponseMcpCallInProgressEvent):
        if not self.tool_call_id:
            logger.exception(
                f"Received MCP call in progress without a current tool call. Data: {data}"
            )
            return
        if self.tool_call_external_id != data.item_id:
            logger.exception(
                f"Received MCP call in progress with a different tool call ID. Data: {data}"
            )
            return

        @db_session_handler
        async def add_cached_tool_call_on_mcp_tool_call_in_progress(
            session_: AsyncSession,
        ):
            if not self.tool_call_id:
                return

            await models.ToolCall.update_status(
                session_, self.tool_call_id, ToolCallStatus.IN_PROGRESS
            )
            await session_.commit()

        await add_cached_tool_call_on_mcp_tool_call_in_progress()

    async def on_mcp_tool_call_arguments_delta(
        self, data: ResponseMcpCallArgumentsDeltaEvent
    ):
        if not self.tool_call_id:
            logger.exception(
                f"Received MCP tool call arguments delta without a current tool call. Data: {data}"
            )
            return
        if self.tool_call_external_id != data.item_id:
            logger.exception(
                f"Received MCP tool call arguments delta with a different tool call ID. Data: {data}"
            )
            return

        @db_session_handler
        async def add_cached_tool_call_on_mcp_tool_call_arguments_delta(
            session_: AsyncSession,
        ):
            if not self.tool_call_id:
                return
            await models.ToolCall.add_mcp_arguments_delta(
                session_, self.tool_call_id, data.delta
            )
            await session_.commit()

        await add_cached_tool_call_on_mcp_tool_call_arguments_delta()

        self.enqueue(
            {
                "type": "tool_call_delta",
                "delta": {
                    "index": data.output_index,
                    "output_index": data.output_index,
                    "type": "mcp_call",
                    "id": data.item_id,
                    "arguments_delta": data.delta,
                },
            }
        )

    async def on_mcp_tool_call_completed(self, data: ResponseMcpCallCompletedEvent):
        if not self.tool_call_id:
            logger.exception(
                f"Received MCP call completed without a current tool call. Data: {data}"
            )
            return
        if self.tool_call_external_id != data.item_id:
            logger.exception(
                f"Received MCP call completed with a different tool call ID. Data: {data}"
            )
            return

        completed_at = utcnow()

        @db_session_handler
        async def add_cached_tool_call_on_mcp_tool_call_completed(
            session_: AsyncSession,
        ):
            if not self.tool_call_id:
                return
            await models.ToolCall.update_status(
                session_,
                self.tool_call_id,
                ToolCallStatus.COMPLETED,
                completed=completed_at,
            )
            await session_.commit()

        await add_cached_tool_call_on_mcp_tool_call_completed()

    async def on_mcp_tool_call_failed(self, data: ResponseMcpCallFailedEvent):
        if not self.tool_call_id:
            logger.exception(
                f"Received MCP call failed without a current tool call. Data: {data}"
            )
            return
        if self.tool_call_external_id != data.item_id:
            logger.exception(
                f"Received MCP call failed with a different tool call ID. Data: {data}"
            )
            return

        completed_at = utcnow()

        @db_session_handler
        async def add_cached_tool_call_on_mcp_tool_call_failed(
            session_: AsyncSession,
        ):
            if not self.tool_call_id:
                return
            await models.ToolCall.update_status(
                session_,
                self.tool_call_id,
                ToolCallStatus.FAILED,
                completed=completed_at,
            )
            await session_.commit()

        await add_cached_tool_call_on_mcp_tool_call_failed()

    async def on_mcp_tool_call_done(self, data: McpCall):
        if not self.run_id:
            logger.exception(
                f"Received MCP call done without a cached run. Data: {data}"
            )
            return
        if not self.tool_call_id:
            logger.exception(
                f"Received MCP call done without a current tool call. Data: {data}"
            )
            return
        if self.tool_call_external_id != data.id:
            logger.exception(
                f"Received MCP call done with a different tool call ID. Data: {data}"
            )
            return

        @db_session_handler
        async def add_cached_tool_call_on_mcp_call_done(
            session_: AsyncSession,
        ):
            if not self.tool_call_id:
                return
            await models.ToolCall.update_mcp_call(
                session_,
                self.tool_call_id,
                status=ToolCallStatus(data.status),
                error=json.dumps(data.error) if data.error else None,
                mcp_tool_name=data.name,
                mcp_arguments=data.arguments,
                mcp_output=data.output,
            )
            await session_.commit()

        await add_cached_tool_call_on_mcp_call_done()

        self.enqueue(
            {
                "type": "tool_call_delta",
                "delta": {
                    "type": "mcp_call",
                    "id": data.id,
                    "index": self.prev_output_index,
                    "output_index": self.prev_output_index,
                    "run_id": str(self.run_id),
                    "server_label": data.server_label,
                    "name": data.name,
                    "arguments": data.arguments,
                    "output": data.output,
                    "error": data.error,
                    "status": data.status,
                },
            }
        )
        self.tool_call_id = None
        self.tool_call_external_id = None

    async def on_mcp_list_tools_call_created(self, data: McpListTools):
        if not self.run_id:
            logger.exception(
                f"Received MCP list tools call created event without a cached run. Data: {data}"
            )
            return

        if self.tool_call_id:
            logger.exception(
                f"Received MCP list tools call created with an existing tool call. Data: {data}"
            )
            return

        self.prev_output_index += 1
        self.last_output_item_type = "mcp_list_tools"

        mcp_server_tool = self.mcp_server_tools_by_server_label.get(data.server_label)
        if not mcp_server_tool:
            logger.exception(
                f"Received MCP list tools call created for unknown MCP server label: {data.server_label}. Data: {data}"
            )
            return

        tool_call_data = {
            "run_id": self.run_id,
            "tool_call_id": data.id,
            "type": ToolCallType.MCP_LIST_TOOLS,
            "status": ToolCallStatus.IN_PROGRESS,
            "thread_id": self.thread_id,
            "output_index": self.prev_output_index,
            "mcp_server_tool_id": mcp_server_tool.id,
            "mcp_server_label": data.server_label,
            "created": utcnow(),
        }

        @db_session_handler
        async def add_cached_tool_call_on_mcp_list_tools_call_created(
            session_: AsyncSession,
        ):
            tool_call = await models.ToolCall.create(session_, tool_call_data)
            await session_.commit()
            return tool_call

        tool_call = await add_cached_tool_call_on_mcp_list_tools_call_created()
        self.tool_call_id = tool_call.id
        self.tool_call_external_id = tool_call.tool_call_id

        tools = [tool.model_dump() for tool in (data.tools or [])]

        self.enqueue(
            {
                "type": "tool_call_created",
                "tool_call": {
                    "id": str(data.id),
                    "index": self.prev_output_index,
                    "output_index": self.prev_output_index,
                    "type": "mcp_list_tools",
                    "server_label": data.server_label,
                    "server_name": mcp_server_tool.display_name,
                    "tools": tools,
                    "error": data.error,
                    "status": ToolCallStatus.IN_PROGRESS.value,
                    "run_id": str(self.run_id),
                },
            }
        )

    async def on_mcp_list_tools_call_in_progress(
        self, data: ResponseMcpListToolsInProgressEvent
    ):
        if not self.tool_call_id:
            logger.exception(
                f"Received MCP list tools call in progress without a current tool call. Data: {data}"
            )
            return
        if self.tool_call_external_id != data.item_id:
            logger.exception(
                f"Received MCP list tools call in progress with a different tool call ID. Data: {data}"
            )
            return

        @db_session_handler
        async def add_cached_tool_call_on_mcp_list_tools_call_in_progress(
            session_: AsyncSession,
        ):
            if not self.tool_call_id:
                return

            await models.ToolCall.update_status(
                session_, self.tool_call_id, ToolCallStatus.IN_PROGRESS
            )
            await session_.commit()

        await add_cached_tool_call_on_mcp_list_tools_call_in_progress()

    async def on_mcp_list_tools_call_completed(
        self, data: ResponseMcpListToolsCompletedEvent
    ):
        if not self.tool_call_id:
            logger.exception(
                f"Received MCP list tools call completed without a current tool call. Data: {data}"
            )
            return
        if self.tool_call_external_id != data.item_id:
            logger.exception(
                f"Received MCP list tools call completed with a different tool call ID. Data: {data}"
            )
            return

        completed_at = utcnow()

        @db_session_handler
        async def add_cached_tool_call_on_mcp_list_tools_call_completed(
            session_: AsyncSession,
        ):
            if not self.tool_call_id:
                return
            await models.ToolCall.update_status(
                session_,
                self.tool_call_id,
                ToolCallStatus.COMPLETED,
                completed=completed_at,
            )
            await session_.commit()

        await add_cached_tool_call_on_mcp_list_tools_call_completed()

    async def on_mcp_list_tools_call_failed(
        self, data: ResponseMcpListToolsFailedEvent
    ):
        if not self.tool_call_id:
            logger.exception(
                f"Received MCP list tools call failed without a current tool call. Data: {data}"
            )
            return
        if self.tool_call_external_id != data.item_id:
            logger.exception(
                f"Received MCP list tools call failed with a different tool call ID. Data: {data}"
            )
            return

        completed_at = utcnow()

        @db_session_handler
        async def add_cached_tool_call_on_mcp_list_tools_call_failed(
            session_: AsyncSession,
        ):
            if not self.tool_call_id:
                return
            await models.ToolCall.update_status(
                session_,
                self.tool_call_id,
                ToolCallStatus.FAILED,
                completed=completed_at,
            )
            await session_.commit()

        await add_cached_tool_call_on_mcp_list_tools_call_failed()

    async def on_mcp_list_tools_call_done(self, data: McpListTools):
        if not self.run_id:
            logger.exception(
                f"Received MCP list tools call done without a cached run. Data: {data}"
            )
            return
        if not self.tool_call_id:
            logger.exception(
                f"Received MCP list tools call done without a current tool call. Data: {data}"
            )
            return
        if self.tool_call_external_id != data.id:
            logger.exception(
                f"Received MCP list tools call done with a different tool call ID. Data: {data}"
            )
            return

        mcp_server_tool = self.mcp_server_tools_by_server_label.get(data.server_label)
        if not mcp_server_tool:
            logger.exception(
                f"Received MCP list tools call created for unknown MCP server label: {data.server_label}. Data: {data}"
            )
            return

        @db_session_handler
        async def add_mcp_list_tools_tool_on_mcp_list_tools_call_done(
            session_: AsyncSession, data: dict
        ):
            await models.MCPListToolsTool.create(session_, data)
            await session_.commit()

        for tool in data.tools:
            list_tools_tool_data = {
                "mcp_server_tool_id": mcp_server_tool.id,
                "name": tool.name,
                "description": tool.description,
                "input_schema": json.dumps(tool.input_schema),
                "annotations": json.dumps(tool.annotations),
                "tool_call_id": self.tool_call_id,
                "created": utcnow(),
            }
            await add_mcp_list_tools_tool_on_mcp_list_tools_call_done(
                list_tools_tool_data
            )

        @db_session_handler
        async def add_cached_tool_call_on_mcp_list_tools_call_done(
            session_: AsyncSession,
        ):
            if not self.tool_call_id:
                return
            await models.ToolCall.update_mcp_call(
                session_,
                self.tool_call_id,
                error=json.dumps(data.error) if data.error else None,
            )
            await session_.commit()

        await add_cached_tool_call_on_mcp_list_tools_call_done()

        tools = [tool.model_dump() for tool in (data.tools or [])]

        self.enqueue(
            {
                "type": "tool_call_delta",
                "delta": {
                    "type": "mcp_list_tools",
                    "id": data.id,
                    "index": self.prev_output_index,
                    "output_index": self.prev_output_index,
                    "run_id": str(self.run_id),
                    "server_label": data.server_label,
                    "server_name": mcp_server_tool.display_name
                    if mcp_server_tool
                    else None,
                    "tools": tools,
                    "error": data.error,
                    "status": ToolCallStatus.COMPLETED.value
                    if data.error is None
                    else ToolCallStatus.FAILED.value,
                },
            }
        )
        self.tool_call_id = None
        self.tool_call_external_id = None

    async def on_web_search_call_created(self, data: ResponseFunctionWebSearch):
        if not self.run_id:
            logger.exception(
                f"Received web search call created event without a cached run. Data: {data}"
            )
            return
        if self.tool_call_id:
            logger.exception(
                f"Received web search tool call created with an existing tool call. Data: {data}"
            )
            return

        self.prev_output_index += 1
        self.last_output_item_type = "web_search_call"

        tool_call_data = {
            "run_id": self.run_id,
            "tool_call_id": data.id,
            "type": ToolCallType.WEB_SEARCH,
            "status": ToolCallStatus(data.status),
            "thread_id": self.thread_id,
            "output_index": self.prev_output_index,
            "created": utcnow(),
        }

        @db_session_handler
        async def add_cached_tool_call_on_web_search_call_created(
            session_: AsyncSession,
        ):
            tool_call = await models.ToolCall.create(session_, tool_call_data)
            await session_.commit()
            return tool_call

        tool_call = await add_cached_tool_call_on_web_search_call_created()
        self.tool_call_id = tool_call.id
        self.tool_call_external_id = tool_call.tool_call_id

        self.enqueue(
            {
                "type": "tool_call_created",
                "tool_call": {
                    "id": str(data.id),
                    "index": self.prev_output_index,
                    "output_index": self.prev_output_index,
                    "type": "web_search",
                    "web_search": {
                        "action": self.get_action_payload(data.action)
                        if self.show_web_search_actions
                        else None,
                    },
                    "run_id": str(self.run_id),
                },
            }
        )

    async def on_web_search_call_in_progress(
        self, data: ResponseWebSearchCallInProgressEvent
    ):
        if not self.tool_call_id:
            logger.exception(
                f"Received web search call in progress without a current tool call. Data: {data}"
            )
            return
        if self.tool_call_external_id != data.item_id:
            logger.exception(
                f"Received web search call in progress with a different tool call ID. Data: {data}"
            )
            return

        @db_session_handler
        async def add_cached_tool_call_on_web_search_call_in_progress(
            session_: AsyncSession,
        ):
            if not self.tool_call_id:
                return

            await models.ToolCall.update_status(
                session_, self.tool_call_id, ToolCallStatus.IN_PROGRESS
            )
            await session_.commit()

        await add_cached_tool_call_on_web_search_call_in_progress()

    async def on_web_search_call_searching(
        self, data: ResponseWebSearchCallSearchingEvent
    ):
        if not self.tool_call_id:
            logger.exception(
                f"Received web search call searching without a current tool call. Data: {data}"
            )
            return
        if self.tool_call_external_id != data.item_id:
            logger.exception(
                f"Received web search call searching with a different tool call ID. Data: {data}"
            )
            return

        @db_session_handler
        async def add_cached_tool_call_on_web_search_call_searching(
            session_: AsyncSession,
        ):
            if not self.tool_call_id:
                return
            await models.ToolCall.update_status(
                session_, self.tool_call_id, ToolCallStatus.SEARCHING
            )
            await session_.commit()

        await add_cached_tool_call_on_web_search_call_searching()

    async def on_web_search_call_completed(
        self, data: ResponseWebSearchCallCompletedEvent
    ):
        if not self.tool_call_id:
            logger.exception(
                f"Received web search call completed without a current tool call. Data: {data}"
            )
            return
        if self.tool_call_external_id != data.item_id:
            logger.exception(
                f"Received web search call completed with a different tool call ID. Data: {data}"
            )
            return

        completed_at = utcnow()

        @db_session_handler
        async def add_cached_tool_call_on_web_search_call_completed(
            session_: AsyncSession,
        ):
            if not self.tool_call_id:
                return
            await models.ToolCall.update_status(
                session_,
                self.tool_call_id,
                ToolCallStatus.COMPLETED,
                completed=completed_at,
            )
            await session_.commit()

        await add_cached_tool_call_on_web_search_call_completed()

    async def on_web_search_call_done(self, data: ResponseFunctionWebSearch):
        if not self.run_id:
            logger.exception(
                f"Received web search call done without a cached run. Data: {data}"
            )
            return
        if not self.tool_call_id:
            logger.exception(
                f"Received web search call done without a current tool call. Data: {data}"
            )
            return
        if self.tool_call_external_id != data.id:
            logger.exception(
                f"Received web search call done with a different tool call ID. Data: {data}"
            )
            return

        @db_session_handler
        async def add_web_search_call_action_on_web_search_call_done(
            session_: AsyncSession, data: dict
        ):
            result = await models.WebSearchCallAction.create(session_, data)
            await session_.commit()
            return result

        @db_session_handler
        async def add_web_search_call_source_on_web_search_call_done(
            session_: AsyncSession, data: dict
        ):
            await models.WebSearchCallSearchSource.create(session_, data)
            await session_.commit()

        if data.action:
            match data.action.type:
                case "search":
                    search_data = {
                        "tool_call_id": self.tool_call_id,
                        "query": data.action.query,
                        "type": WebSearchActionType.SEARCH,
                        "created": utcnow(),
                    }
                    search_action = (
                        await add_web_search_call_action_on_web_search_call_done(
                            search_data
                        )
                    )

                    for source in data.action.sources or []:
                        source_data = {
                            "web_search_call_action_id": search_action.id,
                            "tool_call_id": self.tool_call_id,
                            "url": source.url if hasattr(source, "url") else None,
                            "created": utcnow(),
                            "name": source.name if hasattr(source, "name") else None,
                        }
                        await add_web_search_call_source_on_web_search_call_done(
                            source_data
                        )

                case "find":
                    find_data = {
                        "tool_call_id": self.tool_call_id,
                        "pattern": data.action.pattern,
                        "url": data.action.url,
                        "type": WebSearchActionType.FIND,
                        "created": utcnow(),
                    }

                    await add_web_search_call_action_on_web_search_call_done(find_data)

                case "open_page":
                    open_page_data = {
                        "tool_call_id": self.tool_call_id,
                        "url": data.action.url,
                        "type": WebSearchActionType.OPEN_PAGE,
                        "created": utcnow(),
                    }

                    await add_web_search_call_action_on_web_search_call_done(
                        open_page_data
                    )

        @db_session_handler
        async def add_cached_tool_call_on_web_search_call_done(
            session_: AsyncSession,
        ):
            if not self.tool_call_id:
                return
            await models.ToolCall.update_status(
                session_,
                self.tool_call_id,
                ToolCallStatus(data.status),
            )
            await session_.commit()

        self.enqueue(
            {
                "type": "tool_call_delta",
                "delta": {
                    "type": "web_search",
                    "id": data.id,
                    "index": self.prev_output_index,
                    "run_id": str(self.run_id),
                    "status": data.status,
                    "action": self.get_action_payload(data.action)
                    if self.show_web_search_actions
                    else None,
                },
            }
        )

        await add_cached_tool_call_on_web_search_call_done()
        self.tool_call_id = None
        self.tool_call_external_id = None

    async def on_file_search_call_created(self, data: ResponseFileSearchToolCall):
        if not self.run_id:
            logger.exception(
                f"Received file search call created event without a cached run. Data: {data}"
            )
            return
        if self.tool_call_id:
            logger.exception(
                f"Received code interpreter tool call created with an existing tool call. Data: {data}"
            )
            return

        self.prev_output_index += 1
        self.last_output_item_type = "file_search_call"

        tool_call_data = {
            "run_id": self.run_id,
            "tool_call_id": data.id,
            "type": ToolCallType.FILE_SEARCH,
            "status": ToolCallStatus(data.status),
            "thread_id": self.thread_id,
            "output_index": self.prev_output_index,
            "queries": json.dumps(data.queries),
            "created": utcnow(),
        }

        @db_session_handler
        async def add_cached_tool_call_on_file_search_call_created(
            session_: AsyncSession,
        ):
            tool_call = await models.ToolCall.create(session_, tool_call_data)
            await session_.commit()
            return tool_call

        tool_call = await add_cached_tool_call_on_file_search_call_created()
        self.tool_call_id = tool_call.id
        self.tool_call_external_id = tool_call.tool_call_id

        self.enqueue(
            {
                "type": "tool_call_created",
                "tool_call": {
                    "id": str(data.id),
                    "index": self.prev_output_index,
                    "output_index": self.prev_output_index,
                    "type": "file_search",
                    "queries": data.queries if self.show_file_search_queries else [],
                    "status": data.status,
                    "run_id": str(self.run_id),
                },
            }
        )

    async def on_file_search_call_in_progress(
        self, data: ResponseFileSearchCallInProgressEvent
    ):
        if not self.tool_call_id:
            logger.exception(
                f"Received file search call in progress without a current tool call. Data: {data}"
            )
            return
        if self.tool_call_external_id != data.item_id:
            logger.exception(
                f"Received file search call in progress with a different tool call ID. Data: {data}"
            )
            return

        @db_session_handler
        async def add_cached_tool_call_on_file_search_call_in_progress(
            session_: AsyncSession,
        ):
            if not self.tool_call_id:
                return

            await models.ToolCall.update_status(
                session_, self.tool_call_id, ToolCallStatus.IN_PROGRESS
            )
            await session_.commit()

        await add_cached_tool_call_on_file_search_call_in_progress()

    async def on_file_search_call_searching(
        self, data: ResponseFileSearchCallSearchingEvent
    ):
        if not self.tool_call_id:
            logger.exception(
                f"Received file search call searching without a current tool call. Data: {data}"
            )
            return
        if self.tool_call_external_id != data.item_id:
            logger.exception(
                f"Received file search call searching with a different tool call ID. Data: {data}"
            )
            return

        @db_session_handler
        async def add_cached_tool_call_on_file_search_call_searching(
            session_: AsyncSession,
        ):
            if not self.tool_call_id:
                return
            await models.ToolCall.update_status(
                session_, self.tool_call_id, ToolCallStatus.SEARCHING
            )
            await session_.commit()

        await add_cached_tool_call_on_file_search_call_searching()

    async def on_file_search_call_completed(
        self, data: ResponseFileSearchCallCompletedEvent
    ):
        if not self.tool_call_id:
            logger.exception(
                f"Received file search call completed without a current tool call. Data: {data}"
            )
            return
        if self.tool_call_external_id != data.item_id:
            logger.exception(
                f"Received file search call completed with a different tool call ID. Data: {data}"
            )
            return

        completed_at = utcnow()

        @db_session_handler
        async def add_cached_tool_call_on_file_search_call_completed(
            session_: AsyncSession,
        ):
            if not self.tool_call_id:
                return
            await models.ToolCall.update_status(
                session_,
                self.tool_call_id,
                ToolCallStatus.COMPLETED,
                completed=completed_at,
            )
            await session_.commit()

        await add_cached_tool_call_on_file_search_call_completed()

    async def on_file_search_call_done(self, data: ResponseFileSearchToolCall):
        if not self.run_id:
            logger.exception(
                f"Received file search call done without a cached run. Data: {data}"
            )
            return
        if not self.tool_call_id:
            logger.exception(
                f"Received file search call done without a current tool call. Data: {data}"
            )
            return
        if self.tool_call_external_id != data.id:
            logger.exception(
                f"Received file search call done with a different tool call ID. Data: {data}"
            )
            return

        @db_session_handler
        async def get_file_object_id_on_file_search_call_done(
            session_: AsyncSession, file_id: str
        ):
            return await models.File.get_obj_id_by_file_id(session_, file_id)

        @db_session_handler
        async def add_current_tool_call_on_file_search_call_done(
            session_: AsyncSession, data: dict
        ):
            await models.FileSearchCallResult.create(session_, data)
            await session_.commit()

        for result in data.results:
            if result.file_id:
                if self.file_search_results.get(result.file_id):
                    self.file_search_results[result.file_id].text += (
                        "\n\n <hr/> \n\n" + result.text
                    )
                else:
                    self.file_search_results[result.file_id] = (
                        FileSearchToolAnnotationResult(
                            file_id=result.file_id,
                            filename=result.filename,
                            text=result.text,
                        )
                    )

            fs_result_data = {
                "attributes": json.dumps(result.attributes),
                "file_id": result.file_id,
                "file_object_id": await get_file_object_id_on_file_search_call_done(
                    result.file_id
                )
                if result.file_id
                else None,
                "filename": result.filename,
                "score": result.score,
                "text": result.text,
                "created": utcnow(),
                "tool_call_id": self.tool_call_id,
            }

            await add_current_tool_call_on_file_search_call_done(fs_result_data)

        @db_session_handler
        async def update_status_queries_on_file_search_call_done(
            session_: AsyncSession,
        ):
            if not self.tool_call_id:
                return
            await models.ToolCall.add_status_queries(
                session_,
                self.tool_call_id,
                ToolCallStatus(data.status),
                json.dumps(data.queries),
            )
            await session_.commit()

        await update_status_queries_on_file_search_call_done()

        self.enqueue(
            {
                "type": "tool_call_delta",
                "delta": {
                    "type": "file_search",
                    "id": data.id,
                    "index": self.prev_output_index,
                    "run_id": str(self.run_id),
                    "queries": data.queries if self.show_file_search_queries else [],
                    "status": data.status,
                },
            }
        )

        self.tool_call_id = None
        self.tool_call_external_id = None

    async def on_reasoning_created(self, data: ResponseReasoningItem):
        if not self.run_id:
            logger.exception(
                f"Received reasoning created event without a cached run. Data: {data}"
            )
            return
        if self.reasoning_id:
            logger.exception(
                f"Received reasoning created with an existing reasoning. Data: {data}"
            )
            return

        self.prev_output_index += 1
        self.last_output_item_type = "reasoning"

        reasoning_data = {
            "run_id": self.run_id,
            "reasoning_id": data.id,
            "output_index": self.prev_output_index,
            "status": ReasoningStatus(data.status or "in_progress"),
            "encrypted_content": data.encrypted_content,
            "thread_id": self.thread_id,
            "created": utcnow(),
        }

        @db_session_handler
        async def add_cached_reasoning_step_on_reasoning_created(
            session_: AsyncSession,
        ):
            reasoning = await models.ReasoningStep.create(session_, reasoning_data)
            await session_.commit()
            return reasoning

        reasoning = await add_cached_reasoning_step_on_reasoning_created()
        self.reasoning_id = reasoning.id
        self.reasoning_external_id = reasoning.reasoning_id

        summary_parts: list[dict] = []

        @db_session_handler
        async def add_reasoning_summary_part_on_reasoning_created(
            session_: AsyncSession, data: dict
        ):
            part = await models.ReasoningSummaryPart.create(session_, data)
            await session_.commit()
            return part

        @db_session_handler
        async def add_reasoning_content_part_on_reasoning_created(
            session_: AsyncSession, data: dict
        ):
            await models.ReasoningContentPart.create(session_, data)
            await session_.commit()

        for summary_part in data.summary or []:
            self.prev_reasoning_summary_part_index += 1

            summary_part_data = {
                "reasoning_step_id": self.reasoning_id,
                "part_index": self.prev_reasoning_summary_part_index,
                "summary_text": summary_part.text,
                "created": utcnow(),
            }
            part_obj = await add_reasoning_summary_part_on_reasoning_created(
                summary_part_data
            )
            if not self.show_reasoning_summaries:
                continue
            summary_parts.append(
                {
                    "reasoning_step_id": self.reasoning_id,
                    "part_index": self.prev_reasoning_summary_part_index,
                    "summary_text": summary_part.text,
                    "summary_part_id": part_obj.id,
                }
            )

        for content_part in data.content or []:
            self.prev_reasoning_content_part_index += 1

            content_part_data = {
                "reasoning_step_id": self.reasoning_id,
                "part_index": self.prev_reasoning_content_part_index,
                "content_text": content_part.text,
                "created": utcnow(),
            }

            await add_reasoning_content_part_on_reasoning_created(content_part_data)

        self.enqueue(
            {
                "type": "reasoning_step_created",
                "reasoning_step": {
                    "id": self.reasoning_id,
                    "index": self.prev_output_index,
                    "output_index": self.prev_output_index,
                    "status": data.status,
                    "run_id": str(self.run_id),
                    "summary": summary_parts,
                },
            }
        )

    async def on_reasoning_summary_part_added(
        self, data: ResponseReasoningSummaryPartAddedEvent
    ):
        if not self.reasoning_id:
            logger.exception(
                f"Received reasoning summary part added event without a current reasoning. Data: {data}"
            )
            return
        if self.reasoning_external_id != data.item_id:
            logger.exception(
                f"Received reasoning summary part added with a different reasoning ID. Data: {data}"
            )
            return

        self.prev_reasoning_summary_part_index += 1

        summary_part_data = {
            "reasoning_step_id": self.reasoning_id,
            "part_index": self.prev_reasoning_summary_part_index,
            "summary_text": data.part.text,
            "created": utcnow(),
        }

        @db_session_handler
        async def add_reasoning_summary_part_on_reasoning_summary_part_added(
            session_: AsyncSession, data: dict
        ):
            result = await models.ReasoningSummaryPart.create(session_, data)
            await session_.commit()
            return result

        summary_part = await add_reasoning_summary_part_on_reasoning_summary_part_added(
            summary_part_data
        )
        self.current_reasoning_summary_index = data.summary_index
        self.current_summary_part_id = summary_part.id
        if not self.show_reasoning_summaries:
            return
        self.enqueue(
            {
                "type": "reasoning_step_summary_part_added",
                "summary_part": {
                    "reasoning_step_id": self.reasoning_id,
                    "part_index": self.prev_reasoning_summary_part_index,
                    "summary_text": data.part.text,
                    "summary_part_id": summary_part.id,
                },
            }
        )

    async def on_reasoning_summary_text_delta(
        self, data: ResponseReasoningSummaryTextDeltaEvent
    ):
        if not self.reasoning_id:
            logger.exception(
                f"Received reasoning summary text delta event without a current reasoning. Data: {data}"
            )
            return
        if self.reasoning_external_id != data.item_id:
            logger.exception(
                f"Received reasoning summary text delta with a different reasoning ID. Data: {data}"
            )
            return
        if data.summary_index != self.current_reasoning_summary_index:
            logger.exception(
                f"Received reasoning summary text delta with a different summary index. Data: {data}"
            )
            return
        if not self.current_summary_part_id:
            logger.exception(
                f"Received reasoning summary text delta without a current summary part ID. Data: {data}"
            )
            return

        @db_session_handler
        async def update_reasoning_summary_part_on_reasoning_summary_text_delta(
            session_: AsyncSession, part_id: int, delta: str
        ):
            await models.ReasoningSummaryPart.add_summary_text_delta(
                session_, part_id, delta
            )
            await session_.commit()

        await update_reasoning_summary_part_on_reasoning_summary_text_delta(
            self.current_summary_part_id, data.delta
        )

        if not self.show_reasoning_summaries:
            return
        self.enqueue(
            {
                "type": "reasoning_summary_text_delta",
                "reasoning_step_id": self.reasoning_id,
                "summary_part_id": self.current_summary_part_id,
                "delta": data.delta,
            }
        )

    async def on_reasoning_summary_part_done(
        self, data: ResponseReasoningSummaryPartDoneEvent
    ):
        if not self.reasoning_id:
            logger.exception(
                f"Received reasoning summary part done event without a current reasoning. Data: {data}"
            )
            return
        if self.reasoning_external_id != data.item_id:
            logger.exception(
                f"Received reasoning summary part done with a different reasoning ID. Data: {data}"
            )
            return
        if data.summary_index != self.current_reasoning_summary_index:
            logger.exception(
                f"Received reasoning summary part done with a different summary index. Data: {data}"
            )
            return
        if not self.current_summary_part_id:
            logger.exception(
                f"Received reasoning summary part done without a current summary part ID. Data: {data}"
            )
            return

        self.current_summary_part_id = None
        self.current_reasoning_summary_index = None

    async def on_reasoning_completed(self, data: ResponseReasoningItem):
        if not self.run_id:
            logger.exception(
                f"Received reasoning completed event without a cached run. Data: {data}"
            )
            return
        if not self.reasoning_id:
            logger.exception(
                f"Received reasoning completed event without a current reasoning. Data: {data}"
            )
            return
        if self.reasoning_external_id != data.id:
            logger.exception(
                f"Received reasoning completed event with a different reasoning ID. Data: {data}"
            )
            return

        @db_session_handler
        async def update_reasoning_step_on_reasoning_completed(
            session_: AsyncSession,
            status: ReasoningStatus,
            encrypted_content: str | None,
        ):
            if not self.reasoning_id:
                return
            await models.ReasoningStep.mark_status(
                session_,
                self.reasoning_id,
                status,
                encrypted_content,
            )
            await session_.commit()

        await update_reasoning_step_on_reasoning_completed(
            status=ReasoningStatus(data.status or "completed"),
            encrypted_content=data.encrypted_content,
        )

        @db_session_handler
        async def get_thought_for_on_reasoning_completed(session_: AsyncSession):
            if not self.reasoning_id:
                return None
            created, updated = await models.ReasoningStep.get_timestamps_by_id(
                session_, self.reasoning_id
            )
            return models.ReasoningStep.format_thought_for(created, updated)

        thought_for = await get_thought_for_on_reasoning_completed()
        self.enqueue(
            {
                "type": "reasoning_step_completed",
                "reasoning_step_id": self.reasoning_id,
                "status": ReasoningStatus(data.status or "completed").value,
                "thought_for": thought_for,
            }
        )
        self.reasoning_id = None
        self.reasoning_external_id = None
        self.prev_reasoning_summary_part_index = -1
        self.prev_reasoning_content_part_index = -1
        self.current_reasoning_summary_index = None
        self.current_summary_part_id = None

    async def cleanup(
        self,
        run_status: RunStatus,
        response_error_code: str | None = None,
        response_error_message: str | None = None,
        response_incomplete_reason: str | None = None,
        send_error_message_only_if_active: bool = False,
        restore_to_pending_if_queued: bool = False,
    ):
        logger.info(f"Starting to clean up run: {self.run_id}")

        has_active_run = False
        if self.run_id:

            @db_session_handler
            async def mark_cached_run_as_pending_on_cleanup(session_: AsyncSession):
                if self.run_id:
                    await models.Run.mark_as_pending(session_, self.run_id)
                    await session_.commit()

            @db_session_handler
            async def mark_cached_run_status_on_cleanup(
                session_: AsyncSession,
                run_status: RunStatus,
                error_code: str | None,
                error_message: str | None,
                incomplete_reason: str | None,
            ):
                if self.run_id:
                    await models.Run.mark_as_status(
                        session_,
                        self.run_id,
                        status=run_status,
                        error_code=error_code,
                        error_message=error_message,
                        incomplete_reason=incomplete_reason,
                    )
                    await session_.commit()

            @db_session_handler
            async def mark_cached_message_as_incomplete_on_cleanup(
                session_: AsyncSession,
            ):
                if self.message_id:
                    await models.Message.mark_as_incomplete(session_, self.message_id)
                    await session_.commit()

            @db_session_handler
            async def mark_cached_tool_call_as_incomplete_on_cleanup(
                session_: AsyncSession,
            ):
                if self.tool_call_id:
                    await models.ToolCall.mark_as_incomplete(
                        session_, self.tool_call_id
                    )
                    await session_.commit()

            @db_session_handler
            async def mark_cached_reasoning_as_incomplete_on_cleanup(
                session_: AsyncSession,
            ):
                if self.reasoning_id:
                    await models.ReasoningStep.mark_as_incomplete(
                        session_, self.reasoning_id
                    )
                    await session_.commit()

            if self.run_status == RunStatus.QUEUED and restore_to_pending_if_queued:
                await mark_cached_run_as_pending_on_cleanup()
                self.run_id = None
                self.run_status = None
                self.enqueue({"type": "done"})
                return

            has_active_run = True
            if self.message_id:
                await mark_cached_message_as_incomplete_on_cleanup()
                self.message_id = None
            if self.tool_call_id:
                await mark_cached_tool_call_as_incomplete_on_cleanup()
                self.tool_call_id = None
            if self.reasoning_id:
                await mark_cached_reasoning_as_incomplete_on_cleanup()
                self.reasoning_id = None

            logger.info(f"About to save run data while cleaning up run: {self.run_id}")
            await mark_cached_run_status_on_cleanup(
                run_status,
                response_error_code,
                response_error_message,
                response_incomplete_reason,
            )
            self.run_id = None
            self.run_status = None

        if response_error_message and (
            not send_error_message_only_if_active or has_active_run
        ):
            self.enqueue(
                {
                    "type": "error",
                    "detail": str(response_error_message),
                }
            )
        if (
            response_incomplete_reason
            and (not send_error_message_only_if_active or has_active_run)
            # We shouldn't alert users when we force stop a response
            # after detecting multiple output messages due to the
            # RESPONSES_MULTI_MESSAGE_FIX
            # See stop_after_additional_output_message() for more details.
            and self.force_stop_incomplete_reason != response_incomplete_reason
        ):
            self.enqueue(
                {
                    "type": "error",
                    "detail": f"Response incomplete: {response_incomplete_reason}",
                }
            )
        self.enqueue({"type": "done"})

    async def on_response_completed(
        self,
        data: Union[
            ResponseCompletedEvent,
            ResponseFailedEvent,
            ResponseIncompleteEvent,
            None,
        ],
    ):
        if not self.run_id:
            logger.exception(
                f"Received response completed event without a cached run. Data: {data}"
            )
            return

        if data is None:
            self.run_status = RunStatus.COMPLETED
            await self.cleanup(
                run_status=RunStatus.COMPLETED,
                response_incomplete_reason=self.force_stop_incomplete_reason,
            )
            self.force_stop_incomplete_reason = None
            return

        await self.cleanup(
            run_status=RunStatus(data.response.status),
            response_error_code=data.response.error.code
            if data.response.error
            else None,
            response_error_message=data.response.error.message
            if data.response.error
            else None,
            response_incomplete_reason=data.response.incomplete_details.reason
            if data.response.incomplete_details
            else None,
        )

    async def on_response_error(self, data: ResponseErrorEvent) -> None:
        if not self.run_id:
            logger.exception(
                f"Received response error event without a cached run. Data: {data}"
            )
            return

        @db_session_handler
        async def log_rate_limit_error_on_response_error(session_: AsyncSession):
            await models.Class.log_rate_limit_error(
                session_, class_id=str(self.class_id)
            )
            await session_.commit()

        if data.code == "rate_limit_exceeded":
            await log_rate_limit_error_on_response_error()

        await self.cleanup(
            run_status=RunStatus.FAILED,
            response_error_code=data.code,
            response_error_message=data.message,
        )

        self.enqueue(
            {
                "type": "error",
                "detail": str(data.message),
            }
        )

    async def on_response_canceled(self) -> None:
        await self.cleanup(
            run_status=RunStatus.INCOMPLETE,
            response_incomplete_reason="User canceled the request.",
            send_error_message_only_if_active=False,
        )


async def run_response(
    cli: openai.AsyncClient,
    *,
    run: models.Run,
    class_id: str,
    file_names: dict[str, str] = {},
    assistant_vector_store_id: str | None = None,
    thread_vector_store_id: str | None = None,
    attached_file_search_file_ids: list[str] | None = None,
    code_interpreter_file_ids: list[str] | None = None,
    mcp_server_tools_by_server_label: dict[str, models.MCPServerTool] | None = None,
    show_file_search_result_quotes: bool | None = None,
    show_file_search_document_names: bool | None = None,
    show_file_search_queries: bool | None = None,
    show_web_search_sources: bool | None = None,
    show_web_search_actions: bool | None = None,
    show_reasoning_summaries: bool | None = None,
    user_auth: str | None = None,
    anonymous_link_auth: str | None = None,
    anonymous_user_auth: str | None = None,
    anonymous_session_id: int | None = None,
    anonymous_link_id: int | None = None,
):
    is_canceled = False
    await config.authz.driver.init()
    async with config.authz.driver.get_client() as c:
        handler: BufferedResponseStreamHandler | None = None

        try:
            reasoning_settings: Reasoning | openai.NotGiven = openai.NOT_GIVEN
            text_settings: ResponseTextConfigParam | openai.NotGiven = openai.NOT_GIVEN
            include_with = []
            reasoning_effort_map = get_reasoning_effort_map(run.model)

            if run.reasoning_effort is not None:
                if run.reasoning_effort not in reasoning_effort_map:
                    raise ValueError(
                        f"Invalid reasoning effort: {run.reasoning_effort}. Must be one of {list(reasoning_effort_map.keys())}."
                    )
                reasoning_settings = Reasoning(
                    effort=reasoning_effort_map[run.reasoning_effort],
                    summary="auto",
                )
                include_with.append("reasoning.encrypted_content")

            if run.verbosity is not None:
                if run.verbosity not in VERBOSITY_MAP:
                    raise ValueError(
                        f"Invalid verbosity: {run.verbosity}. Must be one of {list(VERBOSITY_MAP.keys())}."
                    )
                text_settings = ResponseTextConfigParam(
                    verbosity=VERBOSITY_MAP[run.verbosity]
                )

            temperature_setting: float | openai.NotGiven = (
                run.temperature if run.temperature is not None else openai.NOT_GIVEN
            )
            async with config.db.driver.async_session() as session_:
                input_items = await build_response_input_item_list(
                    session_,
                    thread_id=run.thread_id,
                    uses_reasoning=not isinstance(reasoning_settings, openai.NotGiven),
                )
                max_output_index = await models.Thread.get_max_output_sequence(
                    session_, run.thread_id
                )

            tools: list[ToolParam] = []
            if run.tools_available and "web_search" in run.tools_available:
                tools.append(
                    WebSearchToolParam(
                        type="web_search",
                    )
                )
                include_with.append("web_search_call.action.sources")

            if run.tools_available and "mcp_server" in run.tools_available:
                if mcp_server_tools_by_server_label:
                    for (
                        server_label,
                        mcp_tool,
                    ) in mcp_server_tools_by_server_label.items():
                        tools.append(
                            Mcp(
                                server_url=mcp_tool.server_url,
                                server_label=server_label,
                                type="mcp",
                                headers=json.loads(mcp_tool.headers)
                                if mcp_tool.headers
                                else {},
                                authorization=mcp_tool.authorization_token,
                                require_approval="never",
                                server_description=mcp_tool.description
                                or ("MCP server: " + mcp_tool.display_name),
                            )
                        )

            if run.tools_available and "file_search" in run.tools_available:
                vector_store_ids = []
                if assistant_vector_store_id is not None:
                    vector_store_ids.append(assistant_vector_store_id)
                if thread_vector_store_id is not None:
                    vector_store_ids.append(thread_vector_store_id)
                if attached_file_search_file_ids:
                    if not thread_vector_store_id:
                        raise ValueError("Vector store ID is required for file search")
                    await asyncio.gather(
                        *[
                            cli.vector_stores.files.poll(
                                file_id=file_id,
                                vector_store_id=thread_vector_store_id,
                            )
                            for file_id in attached_file_search_file_ids
                        ]
                    )
                if vector_store_ids:
                    tools.append(
                        FileSearchToolParam(
                            type="file_search", vector_store_ids=vector_store_ids
                        )
                    )
                    include_with.append("file_search_call.results")

            if run.tools_available and "code_interpreter" in run.tools_available:
                tools.append(
                    CodeInterpreter(
                        container=CodeInterpreterContainerCodeInterpreterToolAuto(
                            file_ids=code_interpreter_file_ids or [], type="auto"
                        ),
                        type="code_interpreter",
                    )
                )
                include_with.append("code_interpreter_call.outputs")

            try:
                stream: AsyncStream[ResponseStreamEvent] = await cli.responses.create(
                    include=include_with,
                    input=input_items,
                    instructions=run.instructions,
                    model=run.model,
                    parallel_tool_calls=False,
                    reasoning=reasoning_settings,
                    tools=tools,
                    store=True,
                    stream=True,
                    temperature=temperature_setting,
                    truncation="auto",
                    text=text_settings,
                )
                handler = BufferedResponseStreamHandler(
                    session=session_,
                    auth=c,
                    cli=cli,
                    run_id=run.id,
                    run_status=RunStatus(run.status),
                    prev_output_index=max_output_index,
                    file_names=file_names,
                    class_id=int(class_id),
                    thread_id=run.thread_id,
                    assistant_id=run.assistant_id,
                    mcp_server_tools_by_server_label=mcp_server_tools_by_server_label,
                    show_file_search_queries=show_file_search_queries,
                    show_file_search_result_quotes=show_file_search_result_quotes,
                    show_file_search_document_names=show_file_search_document_names,
                    show_web_search_sources=show_web_search_sources,
                    show_web_search_actions=show_web_search_actions,
                    show_reasoning_summaries=show_reasoning_summaries,
                    user_id=run.creator_id,
                    user_auth=user_auth,
                    anonymous_user_auth=anonymous_user_auth,
                    anonymous_link_auth=anonymous_link_auth,
                    anonymous_session_id=anonymous_session_id,
                    anonymous_link_id=anonymous_link_id,
                )

                async for event in stream:
                    match event.type:
                        case "response.created":
                            await handler.on_response_created(event)
                        case "response.in_progress":
                            await handler.on_response_in_progress(event)
                        case "response.output_item.added":
                            match event.item.type:
                                case "message":
                                    if handler.last_output_item_type == "message":
                                        logger.info(
                                            "RESPONSES_MULTI_MESSAGE_FIX: Stopping response due to consecutive output messages in event streamer."
                                        )
                                        await handler.stop_after_additional_output_message()
                                        break
                                    await handler.on_output_message_created(event.item)
                                    if handler.force_stopped:
                                        break
                                case "code_interpreter_call":
                                    await handler.on_code_interpreter_tool_call_created(
                                        event.item
                                    )
                                case "file_search_call":
                                    await handler.on_file_search_call_created(
                                        event.item
                                    )
                                case "web_search_call":
                                    await handler.on_web_search_call_created(event.item)
                                case "reasoning":
                                    await handler.on_reasoning_created(event.item)
                                case "mcp_call":
                                    await handler.on_mcp_tool_call_created(event.item)
                                case "mcp_list_tools":
                                    await handler.on_mcp_list_tools_call_created(
                                        event.item
                                    )
                                case _:
                                    pass
                        case "response.content_part.added":
                            match event.part.type:
                                case "output_text":
                                    await handler.on_output_text_part_created(
                                        event.part
                                    )
                                case _:
                                    pass
                        case "response.output_text.delta":
                            await handler.on_output_text_delta(event)
                        case "response.output_text.annotation.added":
                            match event.annotation["type"]:
                                case "container_file_citation":
                                    await handler.on_output_text_container_file_citation_added(
                                        event.annotation, event.annotation_index
                                    )
                                case "file_citation":
                                    await handler.on_output_text_file_citation_added(
                                        event.annotation, event.annotation_index
                                    )
                                case "url_citation":
                                    await handler.on_output_text_url_citation_added(
                                        event.annotation, event.annotation_index
                                    )
                                case _:
                                    pass
                        case "response.content_part.done":
                            match event.part.type:
                                case "output_text":
                                    await handler.on_output_text_part_done(event.part)
                                case _:
                                    pass
                        case "response.code_interpreter_call.in_progress":
                            await handler.on_code_interpreter_tool_call_in_progress(
                                event
                            )
                        case "response.code_interpreter_call_code.delta":
                            await handler.on_code_interpreter_tool_call_code_delta(
                                event
                            )
                        case "response.code_interpreter_call.interpreting":
                            await handler.on_code_interpreter_tool_call_interpreting(
                                event
                            )
                        case "response.code_interpreter_call.completed":
                            await handler.on_code_interpreter_tool_call_completed(event)
                        case "response.file_search_call.completed":
                            await handler.on_file_search_call_completed(event)
                        case "response.file_search_call.in_progress":
                            await handler.on_file_search_call_in_progress(event)
                        case "response.file_search_call.searching":
                            await handler.on_file_search_call_searching(event)
                        case "response.web_search_call.in_progress":
                            await handler.on_web_search_call_in_progress(event)
                        case "response.web_search_call.searching":
                            await handler.on_web_search_call_searching(event)
                        case "response.web_search_call.completed":
                            await handler.on_web_search_call_completed(event)
                        case "response.mcp_call.in_progress":
                            await handler.on_mcp_tool_call_in_progress(event)
                        case "response.mcp_call_arguments.delta":
                            await handler.on_mcp_tool_call_arguments_delta(event)
                        case "response.mcp_call.completed":
                            await handler.on_mcp_tool_call_completed(event)
                        case "response.mcp_call.failed":
                            await handler.on_mcp_tool_call_failed(event)
                        case "response.mcp_list_tools.in_progress":
                            await handler.on_mcp_list_tools_call_in_progress(event)
                        case "response.mcp_list_tools.completed":
                            await handler.on_mcp_list_tools_call_completed(event)
                        case "response.mcp_list_tools.failed":
                            await handler.on_mcp_list_tools_call_failed(event)
                        case "response.reasoning_summary_part.added":
                            await handler.on_reasoning_summary_part_added(event)
                        case "response.reasoning_summary_text.delta":
                            await handler.on_reasoning_summary_text_delta(event)
                        case "response.reasoning_summary_part.done":
                            await handler.on_reasoning_summary_part_done(event)
                        case "response.output_item.done":
                            match event.item.type:
                                case "message":
                                    await handler.on_output_message_done(event.item)
                                case "code_interpreter_call":
                                    await handler.on_code_interpreter_tool_call_done(
                                        event.item
                                    )
                                case "file_search_call":
                                    await handler.on_file_search_call_done(event.item)
                                case "web_search_call":
                                    await handler.on_web_search_call_done(event.item)
                                case "reasoning":
                                    await handler.on_reasoning_completed(event.item)
                                case "mcp_call":
                                    await handler.on_mcp_tool_call_done(event.item)
                                case "mcp_list_tools":
                                    await handler.on_mcp_list_tools_call_done(
                                        event.item
                                    )
                                case _:
                                    pass
                        case "response.completed":
                            await handler.on_response_completed(event)
                        case "response.incomplete":
                            await handler.on_response_completed(event)
                        case "response.failed":
                            await handler.on_response_completed(event)
                        case "error":
                            await handler.on_response_error(event)
                        case _:
                            pass
                    yield handler.flush()
            except (
                BrokenPipeError,
                ConnectionResetError,
                ConnectionAbortedError,
                asyncio.CancelledError,
                ClientDisconnect,
            ):
                is_canceled = True
                print("Response stream was canceled by the client.")
                if handler:
                    await asyncio.shield(handler.on_response_canceled())
                return
            except openai.APIError as openai_error:
                if openai_error.type == "server_error":
                    try:
                        logger.exception(
                            f"Server error in response stream: {openai_error}"
                        )
                        if handler:
                            await handler.cleanup(
                                run_status=RunStatus.FAILED,
                                response_error_code=openai_error.code,
                                response_error_message="OpenAI was unable to process your request. If the issue persists, check <a class='underline' href='https://pingpong-hks.statuspage.io' target='_blank'>PingPong's status page</a> for updates.",
                                send_error_message_only_if_active=False,
                            )
                            yield handler.flush()
                        else:
                            async with config.db.driver.async_session() as session_:
                                run.status = RunStatus.FAILED
                                run.error_code = openai_error.type
                                run.error_message = (
                                    f"Error in response stream: {openai_error}"
                                )
                                session_.add(run)
                                await session_.commit()

                            yield (
                                orjson.dumps(
                                    {
                                        "type": "error",
                                        "detail": "OpenAI was unable to process your request. If the issue persists, check <a class='underline' href='https://pingpong-hks.statuspage.io' target='_blank'>PingPong's status page</a> for updates.",
                                    }
                                )
                                + b"\n"
                            )

                    except Exception as e:
                        logger.exception(f"Error writing to stream: {e}")
                        pass
                else:
                    try:
                        logger.exception("Error in response stream")
                        if handler:
                            await handler.cleanup(
                                run_status=RunStatus.FAILED,
                                response_error_code=openai_error.code,
                                response_error_message="OpenAI was unable to process your request. "
                                + get_details_from_api_error(
                                    openai_error, "Please try again later."
                                ),
                                send_error_message_only_if_active=False,
                            )

                            yield handler.flush()
                        else:
                            async with config.db.driver.async_session() as session_:
                                run.status = RunStatus.FAILED
                                run.error_code = openai_error.type
                                run.error_message = (
                                    f"Error in response stream: {openai_error}"
                                )
                                session_.add(run)
                                await session_.commit()

                            yield (
                                orjson.dumps(
                                    {
                                        "type": "error",
                                        "detail": "OpenAI was unable to process your request. "
                                        + get_details_from_api_error(
                                            openai_error, "Please try again later."
                                        ),
                                    }
                                )
                                + b"\n"
                            )

                    except Exception as e:
                        logger.exception(f"Error writing to stream: {e}")
                        pass
            except (ValueError, Exception) as e:
                try:
                    logger.exception(f"Error in response stream: {e}")
                    if handler:
                        await handler.cleanup(
                            run_status=RunStatus.FAILED,
                            response_error_code="pingpong_error",
                            response_error_message="We were unable to process your request. If the issue persists, check <a class='underline' href='https://pingpong-hks.statuspage.io' target='_blank'>PingPong's status page</a> for updates.",
                            send_error_message_only_if_active=False,
                        )

                        yield handler.flush()
                    else:
                        async with config.db.driver.async_session() as session_:
                            run.status = RunStatus.FAILED
                            run.error_code = "pingpong_error"
                            run.error_message = f"Error in response stream: {e}"
                            session_.add(run)
                            await session_.commit()

                        yield (
                            orjson.dumps(
                                {
                                    "type": "error",
                                    "detail": "We were unable to process your request. If the issue persists, check <a class='underline' href='https://pingpong-hks.statuspage.io' target='_blank'>PingPong's status page</a> for updates.",
                                }
                            )
                            + b"\n"
                        )
                except Exception as e_:
                    logger.exception(f"Error writing to stream: {e_}")
                    pass
            finally:
                if not is_canceled:
                    if handler:
                        yield handler.flush()
                    yield b'{"type":"done"}\n'
        except (asyncio.CancelledError, ClientDisconnect):
            logger.info("Response stream was cancelled")
            return
        except Exception as e:
            logger.exception(f"Error in response creating responses handler: {e}")
            if handler:
                # If we reach here, it means the handler was not able to complete successfully.
                # We should clean up the run and notify the user.
                await handler.cleanup(
                    run_status=RunStatus.FAILED,
                    response_error_code="pingpong_error",
                    response_error_message="We were unable to process your request.",
                    send_error_message_only_if_active=False,
                )
                yield handler.flush()
            else:
                async with config.db.driver.async_session() as session_:
                    run.status = RunStatus.FAILED
                    run.error_code = "pingpong_error"
                    run.error_message = f"Error in response stream: {e}"
                    session_.add(run)
                    await session_.commit()
            yield (
                orjson.dumps(
                    {
                        "type": "error",
                        "detail": "We were unable to process your request. If the issue persists, check <a class='underline' href='https://pingpong-hks.statuspage.io' target='_blank'>PingPong's status page</a> for updates.",
                    }
                )
                + b"\n"
            )


async def run_thread(
    cli: openai.AsyncClient,
    *,
    class_id: str,
    thread_id: str,
    assistant_id: int,
    message: list[MessageContentPartParam],
    file_names: dict[str, str] = {},
    metadata: Dict[str, str | int] | None = None,
    vector_store_id: str | None = None,
    file_search_file_ids: list[str] | None = None,
    code_interpreter_file_ids: list[str] | None = None,
    instructions: str | None = None,
):
    try:
        if message:
            attachments: list[Attachment] = []
            attachments_dict: dict[str, list[dict[str, str]]] = {}

            if file_search_file_ids:
                for file_id in file_search_file_ids:
                    attachments_dict.setdefault(file_id, []).append(
                        {"type": "file_search"}
                    )

            if code_interpreter_file_ids:
                for file_id in code_interpreter_file_ids:
                    attachments_dict.setdefault(file_id, []).append(
                        {"type": "code_interpreter"}
                    )

            for file_id, tools in attachments_dict.items():
                attachments.append({"file_id": file_id, "tools": tools})

            await cli.beta.threads.messages.create(
                thread_id,
                role="user",
                content=message,
                metadata=metadata,
                attachments=attachments,
            )

            if file_search_file_ids:
                if not vector_store_id:
                    raise ValueError("Vector store ID is required for file search")
                await asyncio.gather(
                    *[
                        cli.vector_stores.files.poll(
                            file_id=file_id, vector_store_id=vector_store_id
                        )
                        for file_id in file_search_file_ids
                    ]
                )
        handler = BufferedStreamHandler(file_names=file_names)
        async with cli.beta.threads.runs.stream(
            thread_id=thread_id,
            assistant_id=assistant_id,
            event_handler=handler,
            instructions=instructions,
        ) as run:
            async for event in run:
                if (
                    isinstance(event, ThreadRunStepCompleted)
                    and isinstance(event.data.step_details, ToolCallsStepDetails)
                    and any(
                        isinstance(tool_call, CodeInterpreterToolCall)
                        for tool_call in event.data.step_details.tool_calls
                    )
                ):
                    data = {
                        "version": 2,
                        "run_id": event.data.run_id,
                        "step_id": event.data.id,
                        "thread_id": event.data.thread_id,
                        "created_at": event.data.created_at,
                    }
                    # Create a new DB session to commit the new CI call
                    await config.authz.driver.init()
                    async with config.db.driver.async_session() as session:
                        await models.CodeInterpreterCall.create(session, data)
                        await session.commit()
                elif isinstance(event, ThreadRunStepFailed) or isinstance(
                    event, ThreadRunFailed
                ):
                    if event.data.last_error.code == "rate_limit_exceeded":
                        await config.authz.driver.init()
                        async with config.db.driver.async_session() as session:
                            await models.Class.log_rate_limit_error(
                                session, class_id=class_id
                            )
                            await session.commit()
                        yield (
                            orjson.dumps(
                                {
                                    "type": "error",
                                    "detail": "Your account's OpenAI rate limit was exceeded. Please try again later. If you're seeing this message frequently, please contact your group's moderators.",
                                }
                            )
                            + b"\n"
                        )
                    yield (
                        orjson.dumps(
                            {
                                "type": "error",
                                "detail": f"{event.data.last_error.message}",
                            }
                        )
                        + b"\n"
                    )
                yield handler.flush()
    except openai.APIError as openai_error:
        if openai_error.type == "invalid_request_error" and (
            "add messages to" in openai_error.message
            or "already has an active run" in openai_error.message
        ):
            try:
                logger.exception(f"Active run error in thread run: {openai_error}")
                yield (
                    orjson.dumps(
                        {
                            "type": "run_active_error",
                            "detail": "OpenAI is still processing your last request. We're fetching the latest status...",
                        }
                    )
                    + b"\n"
                )
            except Exception as e:
                logger.exception(f"Error writing to stream: {e}")
                pass
        if openai_error.type == "server_error":
            try:
                logger.exception(f"Server error in thread run: {openai_error}")
                yield (
                    orjson.dumps(
                        {
                            "type": "presend_error",
                            "detail": "OpenAI was unable to process your request. If the issue persists, check <a class='underline' href='https://pingpong-hks.statuspage.io' target='_blank'>PingPong's status page</a> for updates.",
                        }
                    )
                    + b"\n"
                )
            except Exception as e:
                logger.exception(f"Error writing to stream: {e}")
                pass
        else:
            try:
                logger.exception("Error adding new thread message")
                yield (
                    # openai_error.message returns the entire error message in a string with all parameters. We can use the body to get the message if it exists, or we fall back to the whole thing.
                    orjson.dumps(
                        {
                            "type": "presend_error",
                            "detail": "OpenAI was unable to process your request. "
                            + get_details_from_api_error(
                                openai_error, "Please try again later."
                            ),
                        }
                    )
                    + b"\n"
                )
            except Exception as e:
                logger.exception(f"Error writing to stream: {e}")
                pass
    except (ValueError, Exception) as e:
        try:
            logger.exception(f"Error adding new thread message: {e}")
            yield orjson.dumps({"type": "presend_error", "detail": str(e)}) + b"\n"
        except Exception as e_:
            logger.exception(f"Error writing to stream: {e_}")
            pass
    finally:
        yield b'{"type":"done"}\n'


def format_instructions(
    instructions: str,
    use_latex: bool = False,
    use_image_descriptions: bool = False,
    thread_id: str | None = None,
    user_id: int | None = None,
) -> str:
    """Format instructions for a prompt."""

    if use_latex:
        instructions += (
            "\n\n"
            "---Formatting: LaTeX---\n"
            "Use LaTeX with math mode delimiters when outputting "
            "mathematical tokens. Use the single dollar sign $ with spaces "
            "surrounding it to delimit "
            "inline math. For block-level math, use double dollar signs $$ "
            "with newlines before and after them as the opening and closing "
            "delimiter. Do not use LaTeX inside backticks."
        )

    if use_image_descriptions:
        instructions += (
            "\n"
            """
            When the user's message contains a JSON object with the top-level key "Rd1IFKf5dl" in this format:

            {
                "Rd1IFKf5dl": [
                    {
                    "name": <file_name>,
                    "desc": <image_desc>,
                    "content_type": <content_type>,
                    "complements": <file_id>
                    },
                    ...
                ]
            }

            …treat it as if the user has uploaded one or more images. The "name" is the file name, "desc" is the image description, and "content_type" is the media type. The "complements" field should be ignored.

            FOLLOW THESE GUIDELINES:
            1. Reference Image Descriptions
            - Use the user-provided descriptions to inform your answers.
            - Do not explicitly state that you are relying on those descriptions.

            2. Handle Multiple Images
            - Be prepared for multiple images in the JSON array or across multiple user messages.
            - Refer to them collectively as images the user has uploaded.

            3. Consistent Terminology
            - Always refer to the images based on their descriptions as "the images you uploaded," "your images," etc.

            4. Non-essential Data
            - Disregard the "complements" field (and any other extraneous data not mentioned above).

            5. Nonexistent JSON Handling
            - If no JSON is provided, or the JSON does not have the "Rd1IFKf5dl" key at the top level, treat all text (including any JSON snippet) as part of the user's actual message or query. Act as if no images were uploaded in this message.

            EXAMPLE SCENARIO:
            - User: "Help, I can't understand this graph.
            {"Rd1IFKf5dl": [{"name": "image.png", "desc": "A diagram showing photosynthesis... glucose and oxygen.", "content_type": "image/png", "complements": ""}]}"

            - Assistant might respond:
            "What role do the sun's rays play in this process? Understanding how they power a plant can clarify photosynthesis."

            - User: "Can you see the image I uploaded?"
            - Assistant:
            "Yes, you've uploaded one image. How can I help you further with photosynthesis?"

            - User: "I'm also uploading a new image I took of my notes. Could you go over the differences in these two images for me {"Rd1IFKf5dl": [{"name": "notes.png", "desc": "Handwritten notes about plant cell structures.", "content_type": "image/png", "complements": ""}]}"
            - Assistant:
            "You've uploaded another image with handwritten notes. What are you hoping to clarify about the differences between your diagram and your notes?"

            - User: "How many images have I uploaded so far?"
            - Assistant:
            "You've uploaded two images in total. Would you like more details on either one?"
            """
        )

    if thread_id is not None and user_id is not None:
        logger.debug(f"Replacing random blocks in instructions for thread {thread_id}")
        instructions = replace_random_blocks(instructions, thread_id, user_id)
        logger.debug(
            f"Instructions after replacing random blocks for thread {thread_id}: {instructions}"
        )

    return instructions


def inject_timestamp_to_instructions(
    instructions: str, timezone: str | None = None
) -> str:
    """Inject a timestamp into the instructions for the assistant."""
    # Inject the current time into the instructions
    if timezone:
        try:
            tz = ZoneInfo(timezone)
        except ZoneInfoNotFoundError:
            logger.warning(f"Invalid timezone: {timezone}. Using UTC instead.")
            tz = ZoneInfo("UTC")
    else:
        tz = ZoneInfo("UTC")

    dt = datetime.now(tz)
    return instructions + (
        "\n---Other context---\n"
        "The current date and time is "
        f"{dt.strftime('%Y-%m-%d %H:%M:%S')} ({dt.tzname()})."
    )


def generate_user_hash(class_: models.Class, user: models.User) -> str:
    combined_input = (
        f"{user.id}_{user.created.isoformat()}-{class_.id}_{class_.created.isoformat()}"
    )
    hash_object = hashlib.sha256()
    hash_object.update(combined_input.encode("utf-8"))
    return hash_object.hexdigest().rstrip("=")[0:10]


async def export_class_threads_anonymized(
    cli: openai.AsyncClient,
    class_id: str,
    user_id: int,
    nowfn: NowFn = utcnow,
) -> None:
    await export_class_threads(
        cli=cli,
        class_id=class_id,
        user_id=user_id,
        nowfn=nowfn,
        include_user_emails=False,
    )


async def export_class_threads_with_emails(
    cli: openai.AsyncClient,
    class_id: str,
    user_id: int,
    nowfn: NowFn = utcnow,
) -> None:
    await export_class_threads(
        cli=cli,
        class_id=class_id,
        user_id=user_id,
        nowfn=nowfn,
        include_user_emails=True,
    )


async def export_threads_multiple_classes(
    class_ids: list[int],
    requestor_id: int,
    include_user_emails: bool = False,
    include_only_user_ids: list[int] | None = None,
    include_only_user_emails: list[str] | None = None,
    nowfn: NowFn = utcnow,
) -> None:
    async with config.db.driver.async_session() as session:
        # Get details about the person we should send the export to
        requestor = await models.User.get_by_id(session, requestor_id)
        if not requestor:
            raise ValueError(f"User with ID {requestor_id} not found")
        # Get details about the users we should filter by
        user_ids = None
        if include_only_user_ids:
            user_ids = include_only_user_ids
        if include_only_user_emails:
            include_only_user_emails = list(
                set(email.lower() for email in include_only_user_emails)
            )
            user_ids = await models.User.get_by_emails_check_external_logins(
                session, include_only_user_emails
            )

        # Set up the CSV writer
        csv_buffer = io.StringIO()
        csvwriter = csv.writer(csv_buffer)
        header = ["User ID"]
        if include_user_emails:
            header.append("User Email")
        header.extend(
            [
                "Class ID",
                "Class Name",
                "Assistant ID",
                "Assistant Name",
                "Role",
                "Thread ID",
                "Created At",
                "Content",
            ]
        )
        csvwriter.writerow(header)

        class_id = None
        async for class_ in models.Class.get_by_ids(
            session, ids=class_ids, exclude_private=True, with_api_key=True
        ):
            cli = await get_openai_client_by_class_id(session, class_.id)
            class_id = class_.id
            async for thread in models.Thread.get_thread_by_class_id(
                session,
                class_id=int(class_.id),
                desc=False,
                include_only_user_ids=user_ids,
            ):
                (
                    assistant,
                    file_names,
                ) = await models.Thread.get_file_search_files_assistant(
                    session, thread.id
                )
                assistant_id = assistant.id if assistant else "Deleted Assistant"
                assistant_name = assistant.name if assistant else "Deleted Assistant"

                user_hashes = [
                    generate_user_hash(class_, user) for user in thread.users
                ] or ["Unknown user"]
                user_hashes_str = ", ".join(user_hashes)

                user_emails_str = "REDACTED"
                if include_user_emails:
                    user_emails = [user.email for user in thread.users] or [
                        "Unknown email"
                    ]
                    user_emails_str = ", ".join(user_emails)

                prompt_row = [user_hashes_str]
                if include_user_emails:
                    prompt_row.append(user_emails_str)
                prompt_row.extend(
                    [
                        class_.id,
                        class_.name,
                        assistant_id,
                        assistant_name,
                        "system_prompt",
                        thread.id,
                        thread.created.astimezone(ZoneInfo("America/New_York"))
                        .replace(microsecond=0)
                        .isoformat(),
                        thread.assistant.instructions
                        if thread.assistant
                        else "Unknown Prompt (Deleted Assistant)",
                    ]
                )
                csvwriter.writerow(prompt_row)

                after = None
                if thread.version <= 2:
                    while True:
                        messages = await cli.beta.threads.messages.list(
                            thread_id=thread.thread_id,
                            after=after,
                            order="asc",
                        )

                        for message in messages.data:
                            row = [user_hashes_str]

                            if include_user_emails:
                                row.append(user_emails_str)

                            row.extend(
                                [
                                    class_.id,
                                    class_.name,
                                    assistant_id,
                                    assistant_name,
                                    message.role,
                                    thread.id,
                                    datetime.fromtimestamp(
                                        message.created_at, tz=timezone.utc
                                    )
                                    .astimezone(ZoneInfo("America/New_York"))
                                    .isoformat(),
                                    process_message_content(
                                        message.content, file_names
                                    ),
                                ]
                            )
                            csvwriter.writerow(row)

                        if len(messages.data) == 0:
                            break
                        after = messages.data[-1].id
                elif thread.version == 3:
                    while True:
                        messages = await models.Thread.list_messages(
                            session,
                            thread.id,
                            after=after,
                            order="asc",
                            include_annotations=True,
                        )

                        for message in messages:
                            row = [user_hashes_str]

                            if include_user_emails:
                                row.append(user_emails_str)

                            row.extend(
                                [
                                    class_.id,
                                    class_.name,
                                    assistant_id,
                                    assistant_name,
                                    message.role,
                                    thread.id,
                                    message.created.astimezone(
                                        ZoneInfo("America/New_York")
                                    )
                                    .replace(microsecond=0)
                                    .isoformat(),
                                    process_message_content_v3(
                                        message.content, file_names
                                    ),
                                ]
                            )
                            csvwriter.writerow(row)

                        if len(messages) == 0:
                            break
                        after = messages[-1].id
                else:
                    logger.exception(f"Unknown thread version: {thread.version}")
                    continue
        if not class_id:
            logger.warning(f"Found no classes with IDs {class_ids}")
            return

        csv_buffer.seek(0)

        file_name = (
            f"thread_export_multiple_{requestor_id}_{datetime.now().isoformat()}.csv"
        )
        await config.artifact_store.store.put(
            file_name, csv_buffer, "text/csv;charset=utf-8"
        )
        csv_buffer.close()

        tok = encode_auth_token(
            sub=json.dumps(
                {
                    "user_id": requestor_id,
                    "download_name": file_name,
                }
            ),
            expiry=config.artifact_store.download_link_expiration,
            nowfn=nowfn,
        )

        download_link = config.url(
            f"/api/v1/class/{class_id}/export/download?token={tok}"
        )

        export_opts = DownloadExport(
            class_name="multiple classes",
            email=requestor.email,
            link=download_link,
        )
        await send_export_download(
            config.email.sender,
            export_opts,
            expires=config.artifact_store.download_link_expiration,
        )


async def export_class_threads(
    cli: openai.AsyncClient,
    class_id: str,
    user_id: int,
    nowfn: NowFn = utcnow,
    include_user_emails: bool = False,
) -> None:
    async with config.db.driver.async_session() as session:
        class_ = await models.Class.get_by_id(session, int(class_id))
        if not class_:
            raise ValueError(f"Class with ID {class_id} not found")

        user = await models.User.get_by_id(session, user_id)
        if not user:
            raise ValueError(f"User with ID {user_id} not found")

        csv_buffer = io.StringIO()
        csvwriter = csv.writer(csv_buffer)
        header = ["User ID"]
        if include_user_emails:
            header.append("User Email")
        header.extend(
            [
                "Class ID",
                "Class Name",
                "Assistant ID",
                "Assistant Name",
                "Role",
                "Thread ID",
                "Created At",
                "Content",
            ]
        )
        csvwriter.writerow(header)

        async for thread in models.Thread.get_thread_by_class_id(
            session, class_id=int(class_id), desc=False
        ):
            assistant, file_names = await models.Thread.get_file_search_files_assistant(
                session, thread.id
            )
            assistant_id = assistant.id if assistant else "Deleted Assistant"
            assistant_name = assistant.name if assistant else "Deleted Assistant"

            user_hashes_str = ""
            if thread.conversation_id:
                user_hashes_str = thread.conversation_id
            else:
                user_hashes = [
                    generate_user_hash(class_, user) for user in thread.users
                ] or ["Unknown user"]
                user_hashes_str = ", ".join(user_hashes)

            user_emails_str = "REDACTED"
            if include_user_emails:
                user_emails = [user.email for user in thread.users] or ["Unknown email"]
                user_emails_str = ", ".join(user_emails)

            prompt_row = [user_hashes_str]
            if include_user_emails:
                prompt_row.append(user_emails_str)
            prompt_row.extend(
                [
                    class_.id,
                    class_.name,
                    assistant_id,
                    assistant_name,
                    "system_prompt",
                    thread.id,
                    thread.created.astimezone(ZoneInfo("America/New_York"))
                    .replace(microsecond=0)
                    .isoformat(),
                    thread.assistant.instructions
                    if thread.assistant
                    else "Unknown Prompt (Deleted Assistant)",
                ]
            )
            csvwriter.writerow(prompt_row)

            after = None
            if thread.version <= 2:
                while True:
                    messages = await cli.beta.threads.messages.list(
                        thread_id=thread.thread_id,
                        after=after,
                        order="asc",
                    )

                    for message in messages.data:
                        row = [user_hashes_str]

                        if include_user_emails:
                            row.append(user_emails_str)

                        row.extend(
                            [
                                class_.id,
                                class_.name,
                                assistant_id,
                                assistant_name,
                                message.role,
                                thread.id,
                                datetime.fromtimestamp(
                                    message.created_at, tz=timezone.utc
                                )
                                .astimezone(ZoneInfo("America/New_York"))
                                .isoformat(),
                                process_message_content(message.content, file_names),
                            ]
                        )
                        csvwriter.writerow(row)

                    if len(messages.data) == 0:
                        break
                    after = messages.data[-1].id
            elif thread.version == 3:
                while True:
                    messages = await models.Thread.list_messages(
                        session,
                        thread.id,
                        after=after,
                        order="asc",
                        include_annotations=True,
                    )

                    for message in messages:
                        row = [user_hashes_str]

                        if include_user_emails:
                            row.append(user_emails_str)

                        row.extend(
                            [
                                class_.id,
                                class_.name,
                                assistant_id,
                                assistant_name,
                                message.role,
                                thread.id,
                                message.created.astimezone(ZoneInfo("America/New_York"))
                                .replace(microsecond=0)
                                .isoformat(),
                                process_message_content_v3(message.content, file_names),
                            ]
                        )
                        csvwriter.writerow(row)

                    if len(messages) == 0:
                        break
                    after = messages[-1].id
            else:
                logger.exception(f"Unknown thread version: {thread.version}")
                continue

        csv_buffer.seek(0)

        file_name = (
            f"thread_export_{class_id}_{user_id}_{datetime.now().isoformat()}.csv"
        )
        await config.artifact_store.store.put(
            file_name, csv_buffer, "text/csv;charset=utf-8"
        )
        csv_buffer.close()

        tok = encode_auth_token(
            sub=json.dumps(
                {
                    "user_id": user_id,
                    "download_name": file_name,
                }
            ),
            expiry=config.artifact_store.download_link_expiration,
            nowfn=nowfn,
        )

        download_link = config.url(
            f"/api/v1/class/{class_id}/export/download?token={tok}"
        )

        export_opts = DownloadExport(
            class_name=class_.name,
            email=user.email,
            link=download_link,
        )
        await send_export_download(
            config.email.sender,
            export_opts,
            expires=config.artifact_store.download_link_expiration,
        )


def process_message_content(
    content: list[MessageContent], file_names: dict[str, str]
) -> str:
    """Process message content for CSV export. The end result is a single string with all the content combined.
    Images are replaced with their file names, and text is extracted from the content parts.
    File citations are replaced with their file names inside the text
    """
    processed_content = []
    for part in content:
        match part:
            case TextContentBlock():
                processed_content.append(
                    replace_annotations_in_text(text=part, file_names=file_names)
                )
            case ImageFileContentBlock():
                processed_content.append(
                    f"[Image file: {part.image_file.file_id if part.image_file else 'Unknown image file'}]"
                )
            case ImageURLContentBlock():
                processed_content.append(
                    f"[Image URL: {part.image_url.url if part.image_url else 'Unknown image URL'}]"
                )
            case _:
                logger.warning(f"Unknown content type: {part}")
    return "\n".join(processed_content)


def process_message_content_v3(
    content: list[models.MessagePart], file_names: dict[str, str]
) -> str:
    """Process message content for CSV export. The end result is a single string with all the content combined.
    Images are replaced with their file names, and text is extracted from the content parts.
    File citations are replaced with their file names inside the text
    """
    processed_content = []
    for part in content:
        match part.type:
            case MessagePartType.INPUT_TEXT:
                processed_content.append(
                    replace_annotations_in_text_v3(part=part, file_names=file_names)
                )
            case MessagePartType.INPUT_IMAGE:
                processed_content.append(
                    f"[Image file: {part.input_image_file_id or 'Unknown image file'}]"
                )
            case MessagePartType.OUTPUT_TEXT:
                processed_content.append(
                    replace_annotations_in_text_v3(part=part, file_names=file_names)
                )
            case MessagePartType.REFUSAL:
                processed_content.append(
                    f"[Refusal: {part.refusal or 'Unknown refusal'}]"
                )
            case _:
                logger.warning(f"Unknown content type: {part}")
    return "\n".join(processed_content)


def replace_annotations_in_text(
    text: TextContentBlock, file_names: dict[str, str]
) -> str:
    updated_text = text.text.value
    for annotation in text.text.annotations:
        if isinstance(annotation, FileCitationAnnotation) and annotation.text:
            updated_text = updated_text.replace(
                annotation.text,
                f" [{file_names.get(annotation.file_citation.file_id, 'Unknown citation/Deleted Assistant')}] ",
            )
    return updated_text


def replace_annotations_in_text_v3(
    part: models.MessagePart, file_names: dict[str, str]
) -> str:
    updated_text = part.text
    for annotation in part.annotations:
        match annotation.type:
            case AnnotationType.FILE_PATH:
                updated_text += f"\n [File Path Annotation: {file_names.get(annotation.file_object_id, 'Unknown citation/Deleted Assistant')}] "
            case AnnotationType.FILE_CITATION:
                updated_text += f"\n [File Citation Annotation: {annotation.filename or 'Unknown file/Deleted Assistant'}] "
            case AnnotationType.CONTAINER_FILE_CITATION:
                updated_text += f"\n [Code Interpreter Output File Annotation: {annotation.filename or 'Unknown file/Deleted Assistant'}] "
            case AnnotationType.URL_CITATION:
                updated_text += f"\n [URL Citation Annotation: {annotation.title or 'Unknown Website/Deleted Assistant'} ({annotation.url or 'Unknown URL/Deleted Assistant'})] "
    return updated_text


@overload
def get_openai_client(
    api_key: str, provider: Literal["openai"] = "openai"
) -> openai.AsyncClient: ...


@overload
def get_openai_client(
    api_key: str, *, provider: Literal["azure"], endpoint: str | None
) -> openai.AsyncAzureOpenAI: ...


@overload
def get_openai_client(
    api_key: str,
    *,
    provider: Literal["azure"],
    endpoint: str | None,
    api_version: str | None,
) -> openai.AsyncAzureOpenAI: ...


@functools.cache
def get_openai_client(api_key, provider="openai", endpoint=None, api_version=None):
    """Create an OpenAI client instance with the provided configuration.

    This function creates either a standard OpenAI client or an Azure OpenAI client
    depending on the provider parameter.

    Args:
        api_key: The API key for authentication
        provider: The API provider - either "openai" or "azure"
        endpoint: The Azure endpoint URL (required if provider is "azure")
        api_version: The Azure API version (optional)

    Returns:
        An AsyncClient instance for OpenAI or an AsyncAzureOpenAI instance for Azure

    Raises:
        ValueError: If api_key is empty, if provider is unknown, or if endpoint is missing for Azure
    """
    if not api_key:
        raise ValueError("API key is required")
    match provider:
        case "azure":
            _api_version = api_version or "2025-03-01-preview"
            if not endpoint:
                raise ValueError("Azure client requires endpoint.")
            return openai.AsyncAzureOpenAI(
                api_key=api_key, azure_endpoint=endpoint, api_version=_api_version
            )
        case "openai":
            return openai.AsyncClient(api_key=api_key)
        case _:
            raise ValueError(f"Unknown provider {provider}")
