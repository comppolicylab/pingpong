import functools
import hashlib

import openai


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
                    "Summarize the intent of the following message in a couple of words:\n\n"
                    f"{prompt}"
                ),
            }
        ],
        model=model,
    )
    return response.choices[0].message.content


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
