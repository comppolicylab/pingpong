import openai

from .config import ReadOnlyFunctorProxy, config


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


def get_openai_client() -> openai.AsyncClient:
    return openai.AsyncClient(api_key=config.openai.api_key)


openai_client = ReadOnlyFunctorProxy(get_openai_client)
