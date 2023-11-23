import openai

from .config import ReadOnlyFunctorProxy, config


def get_openai_client() -> openai.AsyncClient:
    return openai.AsyncClient(api_key=config.openai.api_key)


openai_client = ReadOnlyFunctorProxy(get_openai_client)
