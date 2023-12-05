import openai

from .config import ReadOnlyFunctorProxy, config


def get_openai_client() -> openai.AsyncClient:
    return openai.AsyncClient(api_key=config.openai.api_key)


async def run_assistant(cli: openai.AsyncClient, assistant_id: str, thread_id: str):
    return await cli.beta.threads.runs.create(
        thread_id=thread_id,
        assistant_id=assistant_id,
    )


openai_client = ReadOnlyFunctorProxy(get_openai_client)
