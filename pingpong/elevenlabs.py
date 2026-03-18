import logging
import ssl
from typing import Any

import httpx
from elevenlabs.client import AsyncElevenLabs
from elevenlabs.core.api_error import ApiError as ElevenLabsApiError
from elevenlabs.core.request_options import RequestOptions
from elevenlabs.errors import (
    UnauthorizedError as ElevenLabsUnauthorizedError,
)

from pingpong import schemas
from pingpong.class_credential_validation import (
    ClassCredentialValidationSSLError,
    ClassCredentialValidationUnavailableError,
    ClassCredentialVoiceValidationError,
)
from pingpong.log_utils import sanitize_for_log

logger = logging.getLogger(__name__)

ELEVENLABS_VOICE_VALIDATION_SAMPLE_TEXT = (
    "Here is a sample of the voice PingPong will use for lecture video mode."
)
ELEVENLABS_VOICE_VALIDATION_OUTPUT_FORMAT = "opus_48000_32"
ELEVENLABS_VOICE_VALIDATION_CONTENT_TYPE = "audio/ogg"
ELEVENLABS_VOICE_SAMPLE_TEXT_HEADER = "X-PingPong-Voice-Sample-Text"


def get_elevenlabs_client(api_key: str) -> AsyncElevenLabs:
    if not api_key:
        raise ValueError("API key is required")
    return AsyncElevenLabs(api_key=api_key)


async def _collect_audio_chunks(audio_stream) -> bytes:
    chunks: list[bytes] = []
    async for chunk in audio_stream:
        if chunk:
            chunks.append(chunk)
    return b"".join(chunks)


def _normalize_elevenlabs_error_body(body: Any) -> dict[str, Any] | None:
    if hasattr(body, "model_dump"):
        body = body.model_dump()
    elif hasattr(body, "dict"):
        body = body.dict()

    return body if isinstance(body, dict) else None


def _is_invalid_elevenlabs_voice_error(exc: ElevenLabsApiError) -> bool:
    body = _normalize_elevenlabs_error_body(exc.body)
    if body is None:
        return False

    detail = body.get("detail", body)
    if not isinstance(detail, dict):
        return False

    identifier = str(
        detail.get("code") or detail.get("status") or detail.get("type") or ""
    ).lower()
    param = str(detail.get("param") or "").lower()
    message = str(detail.get("message") or detail.get("error") or "").lower()

    if identifier in {"voice_not_found", "invalid_voice_id"}:
        return True

    if param == "voice_id":
        return True

    return (
        exc.status_code in {400, 404, 422}
        and "voice" in message
        and ("not found" in message or "invalid" in message)
    )


async def synthesize_elevenlabs_voice_sample(
    api_key: str,
    voice_id: str,
) -> tuple[str, str, bytes]:
    try:
        content_type, audio = await synthesize_elevenlabs_speech(
            api_key,
            voice_id,
            ELEVENLABS_VOICE_VALIDATION_SAMPLE_TEXT,
            timeout_seconds=15,
        )
    except ClassCredentialValidationSSLError as exc:
        raise ClassCredentialValidationSSLError(
            provider=schemas.ClassCredentialProvider.ELEVENLABS,
            message="Unable to validate the ElevenLabs voice due to an SSL error.",
        ) from exc
    except ClassCredentialValidationUnavailableError as exc:
        raise ClassCredentialValidationUnavailableError(
            provider=schemas.ClassCredentialProvider.ELEVENLABS,
            message="Unable to validate the ElevenLabs voice right now.",
        ) from exc
    return (
        ELEVENLABS_VOICE_VALIDATION_SAMPLE_TEXT,
        content_type,
        audio,
    )


async def synthesize_elevenlabs_speech(
    api_key: str,
    voice_id: str,
    text: str,
    *,
    timeout_seconds: int | None = None,
) -> tuple[str, bytes]:
    safe_voice_id = sanitize_for_log(voice_id)
    try:
        client = get_elevenlabs_client(api_key)
        request_options = (
            RequestOptions(timeout_in_seconds=timeout_seconds)
            if timeout_seconds is not None
            else None
        )
        audio = await _collect_audio_chunks(
            client.text_to_speech.convert(
                voice_id=voice_id,
                text=text,
                output_format=ELEVENLABS_VOICE_VALIDATION_OUTPUT_FORMAT,
                request_options=request_options,
            ),
        )
    except ElevenLabsUnauthorizedError as exc:
        logger.warning(
            "ElevenLabs speech synthesis failed due to credential error. voice_id=%s",
            safe_voice_id,
            exc_info=exc,
        )
        raise ClassCredentialValidationUnavailableError(
            provider=schemas.ClassCredentialProvider.ELEVENLABS,
            message="Unable to generate the ElevenLabs audio right now.",
        ) from exc
    except (httpx.TimeoutException, TimeoutError) as exc:
        logger.warning(
            "Timed out generating ElevenLabs audio for voice_id=%s.",
            safe_voice_id,
            exc_info=exc,
        )
        raise ClassCredentialValidationUnavailableError(
            provider=schemas.ClassCredentialProvider.ELEVENLABS,
            message="Unable to generate the ElevenLabs audio right now.",
        ) from exc
    except ssl.SSLError as exc:
        logger.warning(
            "SSL error generating ElevenLabs audio for voice_id=%s.",
            safe_voice_id,
            exc_info=exc,
        )
        raise ClassCredentialValidationSSLError(
            provider=schemas.ClassCredentialProvider.ELEVENLABS,
            message="Unable to generate the ElevenLabs audio due to an SSL error.",
        ) from exc
    except ElevenLabsApiError as exc:
        if _is_invalid_elevenlabs_voice_error(exc):
            logger.info(
                "ElevenLabs speech synthesis rejected voice_id=%s",
                safe_voice_id,
                exc_info=exc,
            )
            raise ClassCredentialVoiceValidationError(
                "Invalid voice ID provided. Please choose a different voice."
            ) from exc
        logger.warning(
            "Failed to generate ElevenLabs audio for voice_id=%s due to provider API error.",
            safe_voice_id,
            exc_info=exc,
        )
        raise ClassCredentialValidationUnavailableError(
            provider=schemas.ClassCredentialProvider.ELEVENLABS,
            message="Unable to generate the ElevenLabs audio right now.",
        ) from exc
    except ValueError as exc:
        logger.warning(
            "ElevenLabs speech synthesis failed due to credential error. voice_id=%s",
            safe_voice_id,
            exc_info=exc,
        )
        raise ClassCredentialValidationUnavailableError(
            provider=schemas.ClassCredentialProvider.ELEVENLABS,
            message="Unable to generate the ElevenLabs audio right now.",
        ) from exc
    except Exception as exc:
        logger.warning(
            "Failed to generate ElevenLabs audio for voice_id=%s due to provider error.",
            safe_voice_id,
            exc_info=exc,
        )
        raise ClassCredentialValidationUnavailableError(
            provider=schemas.ClassCredentialProvider.ELEVENLABS,
            message="Unable to generate the ElevenLabs audio right now.",
        ) from exc

    if not audio:
        logger.warning(
            "ElevenLabs speech synthesis returned empty audio. voice_id=%s",
            safe_voice_id,
        )
        raise ClassCredentialValidationUnavailableError(
            provider=schemas.ClassCredentialProvider.ELEVENLABS,
            message="Unable to generate the ElevenLabs audio right now.",
        )

    return (ELEVENLABS_VOICE_VALIDATION_CONTENT_TYPE, audio)


async def validate_elevenlabs_api_key(api_key: str) -> bool:
    safe_provider = sanitize_for_log(schemas.ClassCredentialProvider.ELEVENLABS.value)
    try:
        client = get_elevenlabs_client(api_key)
        await client.voices.settings.get_default(
            request_options=RequestOptions(timeout_in_seconds=10)
        )
        return True
    except ValueError:
        return False
    except ElevenLabsUnauthorizedError:
        return False
    except (httpx.TimeoutException, TimeoutError) as exc:
        logger.warning(
            "Timed out validating %s class credential.",
            safe_provider,
            exc_info=exc,
        )
        raise ClassCredentialValidationUnavailableError(
            provider=schemas.ClassCredentialProvider.ELEVENLABS,
            message="Unable to validate the ElevenLabs API key right now.",
        ) from exc
    except ssl.SSLError as exc:
        logger.warning(
            "SSL error validating %s class credential.",
            safe_provider,
            exc_info=exc,
        )
        raise ClassCredentialValidationSSLError(
            provider=schemas.ClassCredentialProvider.ELEVENLABS,
            message="Unable to validate the ElevenLabs API key due to an SSL error.",
        ) from exc
    except Exception as exc:
        logger.warning(
            "Failed to validate %s class credential due to provider error.",
            safe_provider,
            exc_info=exc,
        )
        raise ClassCredentialValidationUnavailableError(
            provider=schemas.ClassCredentialProvider.ELEVENLABS,
            message="Unable to validate the ElevenLabs API key right now.",
        ) from exc
