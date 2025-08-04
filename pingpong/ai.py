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
from pingpong.auth import encode_auth_token
from pingpong.authz.base import AuthzClient
from pingpong.files import handle_create_file
from pingpong.invite import send_export_download
import pingpong.models as models
from pingpong.prompt import replace_random_blocks
from pingpong.schemas import (
    APIKeyValidationResponse,
    AnnotationType,
    CodeInterpreterOutputType,
    MessageStatus,
    RunStatus,
    ThreadName,
    NewThreadMessage,
    MessagePartType,
    ToolCallType,
)

from datetime import datetime, timezone
from openai.types.beta.assistant_stream_event import (
    ThreadRunStepCompleted,
    ThreadRunStepFailed,
    ThreadRunFailed,
)
from openai.types.responses import ToolParam, FileSearchToolParam
from openai.types.responses.tool_param import (
    CodeInterpreter,
    CodeInterpreterContainerCodeInterpreterToolAuto,
)
from openai.types.responses.response_output_item import ResponseOutputMessage
from openai.types.responses.response_output_text import ResponseOutputText
from openai.types.responses.response_stream_event import (
    ResponseCreatedEvent,
    ResponseTextDeltaEvent,
)
from openai.types.responses.response_input_item_param import (
    ResponseInputItemParam,
    EasyInputMessageParam,
    ResponseInputMessageContentListParam,
)
from openai.types.responses.response_input_image_param import ResponseInputImageParam
from openai.types.responses.response_input_text_param import ResponseInputTextParam
from openai.types.responses.response_output_message_param import (
    ResponseOutputTextParam,
    ResponseOutputRefusalParam,
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
    ResponseCodeInterpreterToolCallParam,
    OutputLogs,
    OutputImage,
    Output,
)
from openai.types.shared.reasoning import Reasoning
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


class GetOpenAIClientException(Exception):
    def __init__(self, detail: str = "", code: int | None = None):
        self.code = code
        self.detail = detail


REASONING_EFFORT_MAP = {
    0: "low",
    1: "medium",
    2: "high",
}

OpenAIClientType = Union[openai.AsyncClient, openai.AsyncAzureOpenAI]


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
) -> str | None:
    messages = await cli.beta.threads.messages.list(thread_id, limit=10, order="asc")

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
    session: AsyncSession,
    thread_id: int,
) -> list[ResponseInputItemParam]:
    """Build a list of ResponseInputItem from a thread run step."""
    response_input_items: list[ResponseInputItemParam] = []

    async for run in models.Run.get_runs_by_thread_id(session, thread_id):
        # Store ResponseInputItemParam and time created to sort later
        response_input_items_with_time: list[
            tuple[datetime, ResponseInputItemParam]
        ] = []

        # Messages
        for message in run.messages:
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
                                            index=annotation.index,
                                            type="file_citation",
                                        )
                                    )
                                case AnnotationType.FILE_PATH:
                                    annotations.append(
                                        AnnotationFilePath(
                                            file_path=annotation.file_path,
                                            index=annotation.index,
                                            type="file_path",
                                        )
                                    )
                                case AnnotationType.URL_CITATION:
                                    annotations.append(
                                        AnnotationURLCitation(
                                            url=annotation.url,
                                            start_index=annotation.start_index,
                                            end_index=annotation.end_index,
                                            title=annotation.title,
                                            type="url_citation",
                                        )
                                    )
                                case AnnotationType.CONTAINER_FILE_CITATION:
                                    annotations.append(
                                        AnnotationContainerFileCitation(
                                            file_id=annotation.file_id,
                                            container_id=annotation.container_id,
                                            filename=annotation.filename,
                                            start_index=annotation.start_index,
                                            end_index=annotation.end_index,
                                            type="container_file_citation",
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
                    EasyInputMessageParam(
                        role="user", content=content_list, type="message"
                    ),
                )
            )

        # Tool Calls
        for tool_call in run.tool_calls:
            match tool_call.type:
                case ToolCallType.CODE_INTERPRETER:
                    tool_call_outputs: list[Output] = []
                    for output in tool_call.outputs:
                        match output.type:
                            case CodeInterpreterOutputType.LOGS:
                                tool_call_outputs.append(
                                    OutputLogs(logs=output.logs, type="logs")
                                )
                            case CodeInterpreterOutputType.IMAGE:
                                tool_call_outputs.append(
                                    OutputImage(url=output.image.url, type="image")
                                )
                    response_input_items_with_time.append(
                        (
                            tool_call.created_at,
                            ResponseCodeInterpreterToolCallParam(
                                id=tool_call.tool_call_id,
                                code=tool_call.code,
                                container_id=tool_call.container_id,
                                outputs=tool_call_outputs,
                                status=tool_call.status,
                                type="code_interpreter_call",
                            ),
                        )
                    )
                case ToolCallType.FILE_SEARCH:
                    file_search_results: list[Result] = []
                    for result in tool_call.file_search.results:
                        file_search_results.append(
                            Result(
                                attributes=json.loads(result.attributes),
                                file_id=result.file_id,
                                filename=result.filename,
                                score=result.score,
                                text=result.text,
                            )
                        )
                    response_input_items_with_time.append(
                        (
                            tool_call.created_at,
                            ResponseFileSearchToolCallParam(
                                id=tool_call.tool_call_id,
                                queries=json.loads(tool_call.file_search.queries),
                                status=tool_call.status,
                                results=file_search_results,
                                type="file_search_call",
                            ),
                        )
                    )

        # Sort by created time
        response_input_items_with_time.sort(key=lambda x: x[0])
        # Extract the ResponseInputItemParam from the sorted list
        response_input_items.extend(item for _, item in response_input_items_with_time)

    return response_input_items


class BufferedResponseStreamHandler:
    def __init__(
        self,
        session: AsyncSession,
        auth: AuthzClient,
        cli: openai.AsyncClient,
        run: models.Run,
        file_names: dict[str, str],
        class_id: int,
        user_id: int,
        user_auth: str | None = None,
        anonymous_link_auth: str | None = None,
        anonymous_user_auth: str | None = None,
        anonymous_session_id: int | None = None,
        anonymous_link_id: int | None = None,
        *args,
        **kwargs,
    ):
        self.__buffer = io.BytesIO()
        self.file_names = file_names
        self.db = session
        self.auth = auth
        self.openai_cli = cli
        self.class_id = class_id
        self.user_id = user_id
        self.user_auth = user_auth
        self.anonymous_link_auth = anonymous_link_auth
        self.anonymous_user_auth = anonymous_user_auth
        self.anonymous_session_id = anonymous_session_id
        self.anonymous_link_id = anonymous_link_id
        self.__cached_run: models.Run = run
        self.__cached_message: models.Message | None = None
        self.__cached_message_part: models.MessagePart | None = None
        self.__cached_tool_calls: list[models.ToolCall] = []
        self.__current_tool_call: models.ToolCall | None = None

    def enqueue(self, data: Dict) -> None:
        self.__buffer.write(orjson.dumps(data))
        self.__buffer.write(b"\n")

    def flush(self) -> bytes:
        value = self.__buffer.getvalue()
        self.__buffer.truncate(0)
        self.__buffer.seek(0)
        return value

    async def on_response_created(self, data: ResponseCreatedEvent):
        self.__cached_run.run_id = data.response.id
        self.__cached_run.status = RunStatus(data.response.status)

    async def on_output_message_created(self, data: ResponseOutputMessage):
        self.__cached_message = models.Message(
            message_id=data.id,
            message_status=MessageStatus(data.status),
            role=data.role,
            created=utcnow(),
            run_id=self.__cached_run.id,
        )

    async def on_output_text_part_created(self, data: ResponseOutputText):
        self.__cached_message_part = models.MessagePart(
            message_part_id=data.id,
            type=MessagePartType(data.type),
            text=data.text,
        )

    async def on_output_text_delta(self, data: ResponseTextDeltaEvent):
        if not self.__cached_message_part:
            logger.exception(
                f"Received text delta without a cached message part. Data: {data}"
            )
            return
        self.__cached_message_part.text += data.delta.text

    async def on_output_text_container_file_citation_added(
        self, data: AnnotationContainerFileCitation
    ):
        file_content = await self.openai_cli.containers.files.content.retrieve(
            file_id=data.file_id, container_id=data.container_id
        )

        upload_file = UploadFile(
            file=io.BytesIO(file_content.content),
            filename=data.filename or f"container_file_{data.file_id}",
            headers={"content-type": "application/octet-stream"},
        )

        file = await handle_create_file(
            session=self.db,
            authz=self.auth,
            oai_client=self.openai_cli,
            upload=upload_file,
            class_id=self.class_id,
            uploader_id=self.user_id,
            private=True,
            user_auth=f"user:{self.user_id}",
            anonymous_link_auth=self.anonymous_link_auth,
            anonymous_user_auth=self.anonymous_user_auth,
            anonymous_session_id=self.anonymous_session_id,
            anonymous_link_id=self.anonymous_link_id,
        )

        if file.code_interpreter_file_id:
            await models.Thread.add_code_interpeter_files(
                session=self.db,
                thread_id=self.__cached_run.thread_id,
                file_ids=[file.code_interpreter_file_id],
            )

        if not self.__cached_message_part:
            logger.exception(
                f"Received file citation annotation without a cached message part. Data: {data}"
            )
            return

        self.__cached_message_part.annotations.append(
            models.Annotation(
                type=AnnotationType(data.type),
                file_id=file.file_id,
                file_object_id=file.id,
                filename=file.name,
                start_index=data.start_index,
                end_index=data.end_index,
            )
        )

    async def on_output_text_part_done(self, data: ResponseOutputText):
        if not self.__cached_message_part:
            logger.exception(
                f"Received text part done event without a cached message part. Data: {data}"
            )
            return

        # self.__content_message.


async def run_response(
    cli: openai.AsyncClient,
    *,
    run: models.Run,
    class_id: str,
    thread_id: int,
    assistant_id: int,
    model: str,
    reasoning_effort: int | None = None,
    temperature: float | None = None,
    file_names: dict[str, str] = {},
    assistant_vector_store_id: str | None = None,
    thread_vector_store_id: str | None = None,
    attached_file_search_file_ids: list[str] | None = None,
    code_interpreter_file_ids: list[str] | None = None,
    available_tools: str | None = None,
    instructions: str | None = None,
):
    reasoning_settings: Reasoning | openai.NotGiven = openai.NOT_GIVEN

    if reasoning_effort is not None:
        if reasoning_effort not in REASONING_EFFORT_MAP:
            raise ValueError(
                f"Invalid reasoning effort: {reasoning_effort}. Must be one of {list(REASONING_EFFORT_MAP.keys())}."
            )
        reasoning_settings = Reasoning(
            effort=REASONING_EFFORT_MAP[reasoning_effort], summary="auto"
        )

    temperature_setting: float | openai.NotGiven = (
        temperature if temperature is not None else openai.NOT_GIVEN
    )

    async with config.db.driver.async_session() as session_:
        input_items = await build_response_input_item_list(
            session_, thread_id=thread_id
        )

        tools: list[ToolParam] = []

        if available_tools and "file_search" in available_tools:
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
                            file_id=file_id, vector_store_id=thread_vector_store_id
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

        if available_tools and "code_interpreter" in available_tools:
            tools.append(
                CodeInterpreter(
                    container=CodeInterpreterContainerCodeInterpreterToolAuto(
                        file_ids=code_interpreter_file_ids or [], type="auto"
                    ),
                    type="code_interpreter",
                )
            )
        stream = await cli.responses.create(
            include=[
                "code_interpreter_call.outputs",
                "file_search_call.results",
            ],
            input=input_items,
            instructions=instructions,
            model=model,
            parallel_tool_calls=False,
            reasoning=reasoning_settings,
            tools=tools,
            store=False,
            stream=True,
            temperature=temperature_setting,
            truncation="auto",
        )

        try:
            async for event in stream:
                # Yield the event as JSON bytes for streaming
                print(f"Event: {event}")
                yield (
                    orjson.dumps(
                        {"type": "response_event", "event": event.model_dump()}
                    )
                    + b"\n"
                )
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError) as e:
            logger.info(f"Client disconnected: {e}")
            return
        except asyncio.CancelledError:
            logger.info("Stream cancelled")
            return
        except openai.APIError as openai_error:
            if openai_error.type == "server_error":
                try:
                    logger.exception(f"Server error in response stream: {openai_error}")
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
                yield orjson.dumps({"type": "error", "detail": str(e)}) + b"\n"
            except Exception as e_:
                logger.exception(f"Error writing to stream: {e_}")
                pass
        finally:
            yield b'{"type":"done"}\n'


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
                            datetime.fromtimestamp(message.created_at, tz=timezone.utc)
                            .astimezone(ZoneInfo("America/New_York"))
                            .isoformat(),
                            process_message_content(message.content, file_names),
                        ]
                    )
                    csvwriter.writerow(row)

                if len(messages.data) == 0:
                    break
                after = messages.data[-1].id

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
