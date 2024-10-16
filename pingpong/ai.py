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

from datetime import datetime, timezone
from openai.types.beta.assistant_stream_event import ThreadRunStepCompleted
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
from typing import Dict
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)


async def generate_name(
    cli: openai.AsyncClient, transcript: str, model: str = "gpt-4o-mini"
) -> str | None:
    """Generate a name for a prompt using the given model.

    :param cli: OpenAI client
    :param prompt: Prompt to generate a name for
    :param model: Model to use
    :return: Generated name
    """
    system_prompt = 'You will be provided with a transcript between a user and an assistant. Return A TITLE OF 3-4 WORDS summarizing what the conversation is about. Messages the user sent are prepended with "USER", and messages the assistant sent are prepended with "ASSISTANT". DO NOT RETURN MORE THAN 4 WORDS!'

    try:
        response = await cli.chat.completions.create(
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
        )
        return response.choices[0].message.content
    except openai.APIError as e:
        logger.exception(f"Error generating name, {e}")
        return None


async def validate_api_key(api_key: str) -> bool:
    """Validate an OpenAI API key.

    :param key: API key to validate
    :return: Whether the key is valid
    """
    cli = get_openai_client(api_key)
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
    thread_id: str,
    assistant_id: int,
    message: list[MessageContentPartParam],
    file_names: dict[str, str] = {},
    metadata: Dict[str, str | int] | None = None,
    file_search_file_ids: list[str] | None = None,
    code_interpreter_file_ids: list[str] | None = None,
):
    try:
        if message:
            if (
                len(
                    set(file_search_file_ids or []).union(
                        set(code_interpreter_file_ids or [])
                    )
                )
                > 10
            ):
                raise ValueError(
                    "You cannot upload more than 10 files in a single message."
                )

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
        handler = BufferedStreamHandler(file_names=file_names)
        async with cli.beta.threads.runs.stream(
            thread_id=thread_id,
            assistant_id=assistant_id,
            event_handler=handler,
        ) as run:
            async for step in run:
                if (
                    isinstance(step, ThreadRunStepCompleted)
                    and isinstance(step.data.step_details, ToolCallsStepDetails)
                    and any(
                        isinstance(tool_call, CodeInterpreterToolCall)
                        for tool_call in step.data.step_details.tool_calls
                    )
                ):
                    data = {
                        "version": 2,
                        "run_id": step.data.run_id,
                        "step_id": step.data.id,
                        "thread_id": step.data.thread_id,
                        "created_at": step.data.created_at,
                    }
                    # Create a new DB session to commit the new CI call
                    await config.authz.driver.init()
                    async with config.db.driver.async_session() as session:
                        await models.CodeInterpreterCall.create(session, data)
                        await session.commit()
                yield handler.flush()
    except openai.APIError as openai_error:
        if openai_error.type == "server_error":
            try:
                logger.warning(f"Server error in thread run: {openai_error}")
                yield (
                    orjson.dumps(
                        {
                            "type": "error",
                            "detail": "OpenAI was unable to process your request. Please refresh the page and try again. If the issue persists, check https://pingpong-hks.statuspage.io/.",
                        }
                    )
                    + b"\n"
                )
            except Exception:
                logger.exception("Error writing to stream: {e}")
                pass
        else:
            try:
                logger.exception("Error adding new thread message")
                yield (
                    orjson.dumps(
                        {
                            "type": "error",
                            "detail": "OpenAI was unable to process your request: "
                            + str(openai_error.message),
                        }
                    )
                    + b"\n"
                )
            except Exception:
                logger.exception("Error writing to stream: {e}")
                pass
    except ValueError as e:
        try:
            logger.warning(f"Error adding new thread message: {e}")
            yield orjson.dumps({"type": "error", "detail": str(e)}) + b"\n"
        except Exception as e:
            logger.exception("Error writing to stream")
            pass
    except Exception as e:
        try:
            logger.exception("Error adding new thread message")
            yield orjson.dumps({"type": "error", "detail": str(e)}) + b"\n"
        except Exception:
            logger.exception("Error writing to stream")
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


async def export_class_threads(
    cli: openai.AsyncClient,
    class_id: str,
    user_id: int,
    nowfn: NowFn = utcnow,
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
        csvwriter.writerow(
            [
                "User ID",
                "Assistant Name",
                "Role",
                "Thread ID",
                "Created At",
                "Content",
            ]
        )

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

            csvwriter.writerow(
                [
                    user_hashes_str,
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

            after = None
            while True:
                messages = await cli.beta.threads.messages.list(
                    thread_id=thread.thread_id,
                    after=after,
                    order="asc",
                )

                for message in messages.data:
                    csvwriter.writerow(
                        [
                            user_hashes_str,
                            assistant_name,
                            message.role,
                            thread.id,
                            datetime.fromtimestamp(message.created_at, tz=timezone.utc)
                            .astimezone(ZoneInfo("America/New_York"))
                            .isoformat(),
                            process_message_content(message.content, file_names),
                        ]
                    )

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


@functools.cache
def get_openai_client(api_key: str) -> openai.AsyncClient:
    return openai.AsyncClient(api_key=api_key)
