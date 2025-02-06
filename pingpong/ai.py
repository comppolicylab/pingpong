import asyncio
import csv
import functools
import hashlib
import io
import json
import logging
import openai
import orjson
from pingpong.auth import encode_auth_token
from pingpong.invite import send_export_download
import pingpong.models as models
from pingpong.schemas import ThreadName, NewThreadMessage

from datetime import datetime, timezone
from openai.types.beta.assistant_stream_event import (
    ThreadRunStepCompleted,
    ThreadRunStepFailed,
    ThreadRunFailed,
)
from openai._exceptions import APIError
from openai.types.beta.threads import ImageFile, MessageContentPartParam
from openai.types.beta.threads.annotation import FileCitationAnnotation
from openai.types.beta.threads.image_file_content_block import ImageFileContentBlock
from openai.types.beta.threads.image_url_content_block import ImageURLContentBlock
from openai.types.beta.threads.message_content import MessageContent
from openai.types.beta.threads.message_create_params import Attachment
from openai.types.beta.threads.runs import ToolCallsStepDetails, CodeInterpreterToolCall
from openai.types.beta.threads.text_content_block import TextContentBlock
from pingpong.now import NowFn, utcnow
from pingpong.schemas import CodeInterpreterMessage, DownloadExport
from pingpong.config import config
from typing import Dict, Literal, overload
from sqlalchemy.ext.asyncio import AsyncSession
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)


def get_details_from_api_error(e: APIError, custom_fallback: str | None = None) -> str:
    fallback = custom_fallback or "OpenAI was unable to process your request."
    if hasattr(e, "body") and isinstance(e.body, dict):
        message = e.body.get("message")
        if message:
            return message
    if hasattr(e, "message") and e.message:
        return e.message
    return fallback


class GetOpenAIClientException(Exception):
    def __init__(self, detail: str = "", code: int | None = None):
        self.code = code
        self.detail = detail


REASONING_EFFORT_MAP = {
    0: "low",
    1: "medium",
    2: "high",
}


async def get_openai_client_by_class_id(
    session: AsyncSession, class_id: int
) -> openai.AsyncClient:
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
    message: str,
    vision_files: list[str],
    class_id: str,
) -> str | None:
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
) -> bool:
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
    elif provider == "openai":
        cli = get_openai_client(api_key=api_key, provider=provider)
    try:
        await cli.models.list()
        return True
    except openai.AuthenticationError:
        return False


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
                "tool_call": tool_call.model_dump(),
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
                        cli.beta.vector_stores.files.poll(
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
        if openai_error.type == "server_error":
            try:
                logger.warning(f"Server error in thread run: {openai_error}")
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
            logger.warning(f"Error adding new thread message: {e}")
            yield orjson.dumps({"type": "presend_error", "detail": str(e)}) + b"\n"
        except Exception as e_:
            logger.exception(f"Error writing to stream: {e_}")
            pass
    finally:
        yield b'{"type":"done"}\n'


def format_instructions(instructions: str, use_latex: bool = False) -> str:
    """Format instructions for a prompt."""
    if use_latex:
        return instructions + (
            "\n"
            "---Formatting: LaTeX---"
            "Use LaTeX with math mode delimiters when outputting "
            "mathematical tokens. Use the single dollar sign $ with spaces "
            "surrounding it to delimit "
            "inline math. For block-level math, use double dollar signs $$ "
            "with newlines before and after them as the opening and closing "
            "delimiter. Do not use LaTeX inside backticks."
        )

    # Inject the current time into the instructions
    instructions += (
        "\n---Other context---\n"
        "The current date and time is "
        f"{datetime.utcnow().strftime('%Y-%m-%d %H:%M:%S')} (UTC)."
    )

    return instructions


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
                "Class Name",
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
                        class_.name,
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
                                class_.name,
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
                "Class Name",
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
            assistant_name = assistant.name if assistant else "Deleted Assistant"

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
                    class_.name,
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
                            class_.name,
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
            _api_version = api_version or "2025-01-01-preview"
            if not endpoint:
                raise ValueError("Azure client requires endpoint.")
            return openai.AsyncAzureOpenAI(
                api_key=api_key, azure_endpoint=endpoint, api_version=_api_version
            )
        case "openai":
            return openai.AsyncClient(api_key=api_key)
        case _:
            raise ValueError(f"Unknown provider {provider}")
