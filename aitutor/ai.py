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
                    "Come up with a short (few word) title for a chat thread "
                    f"that begins with the following message:\n{prompt}"
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


@functools.cache
def get_openai_client(api_key: str) -> openai.AsyncClient:
    return openai.AsyncClient(api_key=api_key)
