import base64
import boto3
import csv
import functools
import hashlib
import io
import logging
import openai
import orjson
from pingpong.invite import send_export_download
import pingpong.models as models

from datetime import datetime, timedelta, timezone
from openai.types.beta.assistant_stream_event import ThreadRunStepCompleted
from openai.types.beta.threads import ImageFile, MessageContentPartParam
from openai.types.beta.threads.annotation import FileCitationAnnotation
from openai.types.beta.threads.runs import ToolCallsStepDetails, CodeInterpreterToolCall
from openai.types.beta.threads.text_content_block import TextContentBlock
from pingpong.schemas import CodeInterpreterMessage, DownloadExport
from pingpong.config import config
from sqlalchemy.ext.asyncio import AsyncSession
from typing import Dict
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)


async def generate_name(
    cli: openai.AsyncClient, prompt: str, model: str = "gpt-3.5-turbo"
) -> str:
    """Generate a name for a prompt using the given model.

    :param cli: OpenAI client
    :param prompt: Prompt to generate a name for
    :param model: Model to use
    :return: Generated name
    """
    content = (
        "Summarize what the user is seeking help with in a couple of words:\n\n"
        f"{prompt}"
    )

    # The GPT-3.5-turbo model has a 16k token context window. Realistically,
    # the result probably won't change much if we use a much smaller snippet
    # of the prompt. It will also be much cheaper and faster if we don't submit
    # huge prompts to the API. So we'll just use the first 764 words (which is
    # approximately 1,024 tokens, assuming ~1.3 tokens per word).
    content = " ".join(content.split()[:764])

    response = await cli.chat.completions.create(
        messages=[
            {
                "role": "user",
                "content": content,
            }
        ],
        model=model,
    )
    return response.choices[0].message.content


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
                    if annotation["type"] == "file_citation":
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
):
    try:
        if message:
            await cli.beta.threads.messages.create(
                thread_id,
                role="user",
                content=message,
                metadata=metadata,
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


def generate_user_hash(id: int, created: datetime) -> str:
    combined_input = f"{id}{created.isoformat()}"
    hash_object = hashlib.sha256()
    hash_object.update(combined_input.encode("utf-8"))

    binary_hash = hash_object.digest()
    alphanumeric_hash = base64.urlsafe_b64encode(binary_hash).decode("utf-8")
    return alphanumeric_hash.rstrip("=")


async def export_class_threads(
    cli: openai.AsyncClient,
    session: AsyncSession,
    class_id: str,
    user_id: int,
) -> None:
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
            "Message ID",
            "Created At",
            "Content",
        ]
    )

    async for thread in models.Thread.get_thread_by_class_id(
        session, class_id=int(class_id)
    ):
        assistant, file_names = await models.Thread.get_file_search_files_assistant(
            session, thread.id
        )
        assistant_name = assistant.name if assistant else "Deleted Assistant"

        user_hashes = (
            list(
                map(
                    lambda user: generate_user_hash(user.id, user.created), thread.users
                )
            )
            if thread.users
            else ["Unknown User"]
        )
        user_hashes_str = ", ".join(user_hashes)

        csvwriter.writerow(
            [
                user_hashes_str,
                assistant_name,
                "system_prompt",
                thread.id,
                "N/A",
                thread.created.astimezone(ZoneInfo("America/New_York")).strftime(
                    "%Y-%m-%d %H:%M:%S %Z"
                ),
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
                        message.id,
                        datetime.fromtimestamp(message.created_at, tz=timezone.utc)
                        .astimezone(ZoneInfo("America/New_York"))
                        .strftime("%Y-%m-%d %H:%M:%S %Z"),
                        process_message_content(message.content, file_names),
                    ]
                )

            if len(messages.data) == 0:
                break
            after = messages.data[-1].id

    csv_buffer.seek(0)

    s3_key = f"thread_export_{class_id}_{user_id}_{datetime.now().isoformat()}.csv"
    s3_client = boto3.client(
        "s3",
    )
    s3_client.put_object(
        Bucket="pp-stage-artifacts",
        Key=s3_key,
        Body=csv_buffer.getvalue(),
        ContentType="text/csv",
        Expires=datetime.now()
        + timedelta(seconds=config.s3.presigned_url_expiration)
        + timedelta(hours=1),
    )

    csv_buffer.close()

    download_link = s3_client.generate_presigned_url(
        "get_object",
        Params={
            "Bucket": "pp-stage-artifacts",
            "Key": s3_key,
            "ResponseContentDisposition": f"attachment; filename={s3_key}",
        },
        ExpiresIn=config.s3.presigned_url_expiration,
    )
    export_opts = DownloadExport(
        class_name=class_.name,
        email=user.email,
        link=download_link,
    )
    await send_export_download(
        config.email.sender, export_opts, expires=config.s3.presigned_url_expiration
    )


def process_message_content(
    content: list[MessageContentPartParam], file_names: dict[str, str]
) -> str:
    """Process message content for CSV export. The end result is a single string with all the content combined.
    Images are replaced with their file names, and text is extracted from the content parts.
    File citations are replaced with their file names inside the text
    """
    processed_content = []
    for part in content:
        if isinstance(part, TextContentBlock):
            processed_content.append(
                replace_annotations_in_text(text=part, file_names=file_names)
            )
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
