import functools
import io
import logging
from datetime import datetime
from typing import Dict, List

import openai
import orjson
from openai.types.beta.threads import ImageFile

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


class BufferedStreamHandler(openai.AsyncAssistantEventHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.__buffer = io.BytesIO()

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
        self.enqueue(
            {
                "type": "message_delta",
                "delta": delta.model_dump(),
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
    message: str | None,
    file_ids: List[str] | None = None,
    metadata: Dict[str, str | int] | None = None,
):
    try:
        if message is not None:
            await cli.beta.threads.messages.create(
                thread_id,
                role="user",
                content=message,
                file_ids=file_ids,
                metadata=metadata,
            )

        handler = BufferedStreamHandler()
        async with cli.beta.threads.runs.create_and_stream(
            thread_id=thread_id,
            assistant_id=assistant_id,
            event_handler=handler,
        ) as run:
            async for _ in run:
                # Consume the stream and
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


@functools.cache
def get_openai_client(api_key: str) -> openai.AsyncClient:
    return openai.AsyncClient(api_key=api_key)
