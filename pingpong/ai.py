import functools
import hashlib
import logging
from typing import IO, Dict, List

import openai

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
    response = await cli.chat.completions.create(
        messages=[
            {
                "role": "user",
                "content": (
                    "Summarize what the user is seeking help with in a couple of words:\n\n"
                    f"{prompt}"
                ),
            }
        ],
        model=model,
    )
    return response.choices[0].message.content


class StreamHandler(openai.AsyncAssistantEventHandler):
    def __init__(self, *args, io: IO, **kwargs):
        super().__init__(*args, **kwargs)
        self.io = io

    async def on_text_delta(self, delta, snapshot) -> None:
        self.io.write(delta.value)
        self.io.flush()

    async def on_text_created(self, text) -> None:
        self.io.write("::$asst$::")
        self.io.flush()


async def add_new_thread_message(
    cli: openai.AsyncClient,
    *,
    thread_id: str,
    assistant_id: int,
    message: str,
    file_ids: List[str] | None = None,
    metadata: Dict[str, str | int] | None = None,
    stream: IO,
):
    try:
        await cli.beta.threads.messages.create(
            thread_id,
            role="user",
            content=message,
            file_ids=file_ids,
            metadata=metadata,
        )

        async with cli.beta.threads.runs.create_and_stream(
            thread_id=thread_id,
            assistant_id=assistant_id,
            event_handler=StreamHandler(io=stream),
        ) as run:
            await run.until_done()
    except Exception as e:
        try:
            logger.exception("Error adding new thread message")
            stream.write(f"::$err$::{e}\n")
            stream.flush()
        except Exception:
            logger.exception("Error writing to stream")
            pass
    finally:
        stream.close()


def hash_thread(messages, runs) -> str:
    """Come up with a unique ID representing the thread state."""
    rpart = ""
    if runs:
        last_run = runs[0]
        rpart = f"{last_run.id}-{last_run.status}"

    mpart = ""
    if messages:
        mpart = f"{messages.first_id}-{messages.last_id}"

    return hashlib.md5(f"{mpart}-{rpart}".encode("utf-8")).hexdigest()


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
    return instructions


@functools.cache
def get_openai_client(api_key: str) -> openai.AsyncClient:
    return openai.AsyncClient(api_key=api_key)
