import asyncio
import logging
import ssl
from typing import TypeVar

from google import genai
from google.genai import types
from pydantic import BaseModel

from pingpong import schemas
from pingpong.class_credential_validation import (
    ClassCredentialValidationSSLError,
    ClassCredentialValidationUnavailableError,
)
from pingpong.log_utils import sanitize_for_log

logger = logging.getLogger(__name__)

_ResponseModelT = TypeVar("_ResponseModelT", bound=BaseModel)


async def generate_manifest_quiz(
    api_key: str,
    *,
    model: str,
    prompt: str,
    contents: types.ContentListUnion,
    response_model: type[_ResponseModelT],
) -> _ResponseModelT:
    async with genai.Client(api_key=api_key).aio as aclient:
        response = await aclient.models.generate_content(
            model=model,
            config=types.GenerateContentConfig(
                system_instruction=prompt,
                response_mime_type="application/json",
                response_json_schema=response_model.model_json_schema(),
                media_resolution=types.MediaResolution.MEDIA_RESOLUTION_HIGH,
            ),
            contents=contents,
        )
    if not response.text:
        raise ValueError("Gemini returned an empty response.")
    return response_model.model_validate_json(response.text)


async def delete_file(api_key: str, name: str) -> None:
    async with genai.Client(api_key=api_key).aio as aclient:
        await aclient.files.delete(name=name)


async def validate_gemini_api_key(api_key: str) -> bool:
    safe_provider = sanitize_for_log(schemas.ClassCredentialProvider.GEMINI.value)
    try:
        # The google-genai SDK documents `Client().aio` as an async context
        # manager and supports the one-shot form used here:
        # https://github.com/googleapis/python-genai/blob/main/README.md#client-context-managers
        async with genai.Client(api_key=api_key).aio as aclient:
            await asyncio.wait_for(aclient.models.list(config={"page_size": 1}), 10)
        return True
    except genai.errors.ClientError as exc:
        if exc.code in {401, 403}:
            return False
        logger.warning(
            "Failed to validate %s class credential due to provider client error.",
            safe_provider,
            exc_info=exc,
        )
        raise ClassCredentialValidationUnavailableError(
            provider=schemas.ClassCredentialProvider.GEMINI,
            message="Unable to validate the Gemini API key right now.",
        ) from exc
    except TimeoutError as exc:
        logger.warning(
            "Timed out validating %s class credential.",
            safe_provider,
            exc_info=exc,
        )
        raise ClassCredentialValidationUnavailableError(
            provider=schemas.ClassCredentialProvider.GEMINI,
            message="Unable to validate the Gemini API key right now.",
        ) from exc
    except genai.errors.APIError as exc:
        logger.warning(
            "Failed to validate %s class credential due to provider API error.",
            safe_provider,
            exc_info=exc,
        )
        raise ClassCredentialValidationUnavailableError(
            provider=schemas.ClassCredentialProvider.GEMINI,
            message="Unable to validate the Gemini API key right now.",
        ) from exc
    except ssl.SSLError as exc:
        logger.warning(
            "SSL error validating %s class credential.",
            safe_provider,
            exc_info=exc,
        )
        raise ClassCredentialValidationSSLError(
            provider=schemas.ClassCredentialProvider.GEMINI,
            message="Unable to validate the Gemini API key due to an SSL error.",
        ) from exc
    except Exception as exc:
        logger.warning(
            "Failed to validate %s class credential due to provider error.",
            safe_provider,
            exc_info=exc,
        )
        raise ClassCredentialValidationUnavailableError(
            provider=schemas.ClassCredentialProvider.GEMINI,
            message="Unable to validate the Gemini API key right now.",
        ) from exc
