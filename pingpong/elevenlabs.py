import asyncio
import logging
import ssl

from elevenlabs.client import AsyncElevenLabs
from elevenlabs.core.api_error import ApiError as ElevenLabsApiError
from elevenlabs.errors import (
    BadRequestError as ElevenLabsBadRequestError,
    NotFoundError as ElevenLabsNotFoundError,
    UnauthorizedError as ElevenLabsUnauthorizedError,
    UnprocessableEntityError as ElevenLabsUnprocessableEntityError,
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


def _is_invalid_elevenlabs_voice_error(exc: ElevenLabsApiError) -> bool:
    detail = exc.body.get("detail") if isinstance(exc.body, dict) else None
    if not isinstance(detail, dict):
        return False

    identifier = str(
        detail.get("code") or detail.get("status") or detail.get("type") or ""
    ).lower()
    message = str(detail.get("message") or "").lower()

    if identifier == "voice_not_found":
        return True

    return exc.status_code in {400, 404, 422} and "voice" in message


async def synthesize_elevenlabs_voice_sample(
    api_key: str,
    voice_id: str,
) -> tuple[str, str, bytes]:
    safe_voice_id = sanitize_for_log(voice_id)
    try:
        client = get_elevenlabs_client(api_key)
        audio = await asyncio.wait_for(
            _collect_audio_chunks(
                client.text_to_speech.convert(
                    voice_id=voice_id,
                    text=ELEVENLABS_VOICE_VALIDATION_SAMPLE_TEXT,
                    output_format=ELEVENLABS_VOICE_VALIDATION_OUTPUT_FORMAT,
                )
            ),
            15,
        )
        if not audio:
            logger.warning(
                "ElevenLabs voice validation returned empty audio. voice_id=%s",
                safe_voice_id,
            )
            raise ClassCredentialValidationUnavailableError(
                provider=schemas.ClassCredentialProvider.ELEVENLABS,
                message="Unable to validate the ElevenLabs voice right now.",
            )
        return (
            ELEVENLABS_VOICE_VALIDATION_SAMPLE_TEXT,
            ELEVENLABS_VOICE_VALIDATION_CONTENT_TYPE,
            audio,
        )
    except (
        ElevenLabsBadRequestError,
        ElevenLabsNotFoundError,
        ElevenLabsUnprocessableEntityError,
    ) as exc:
        logger.info(
            "ElevenLabs voice validation rejected voice_id=%s",
            safe_voice_id,
            exc_info=exc,
        )
        raise ClassCredentialVoiceValidationError(
            "Invalid voice ID provided. Please choose a different voice."
        ) from exc
    except ElevenLabsUnauthorizedError as exc:
        logger.warning(
            "ElevenLabs voice validation failed due to credential error. voice_id=%s",
            safe_voice_id,
            exc_info=exc,
        )
        raise ClassCredentialValidationUnavailableError(
            provider=schemas.ClassCredentialProvider.ELEVENLABS,
            message="Unable to validate the ElevenLabs voice right now.",
        ) from exc
    except asyncio.TimeoutError as exc:
        logger.warning(
            "Timed out validating ElevenLabs voice_id=%s.",
            safe_voice_id,
            exc_info=exc,
        )
        raise ClassCredentialValidationUnavailableError(
            provider=schemas.ClassCredentialProvider.ELEVENLABS,
            message="Unable to validate the ElevenLabs voice right now.",
        ) from exc
    except ssl.SSLError as exc:
        logger.warning(
            "SSL error validating ElevenLabs voice_id=%s.",
            safe_voice_id,
            exc_info=exc,
        )
        raise ClassCredentialValidationSSLError(
            provider=schemas.ClassCredentialProvider.ELEVENLABS,
            message="Unable to validate the ElevenLabs voice due to an SSL error.",
        ) from exc
    except ElevenLabsApiError as exc:
        if _is_invalid_elevenlabs_voice_error(exc):
            logger.info(
                "ElevenLabs voice validation rejected voice_id=%s",
                safe_voice_id,
                exc_info=exc,
            )
            raise ClassCredentialVoiceValidationError(
                "Invalid voice ID provided. Please choose a different voice."
            ) from exc
        logger.warning(
            "Failed to validate ElevenLabs voice_id=%s due to provider API error.",
            safe_voice_id,
            exc_info=exc,
        )
        raise ClassCredentialValidationUnavailableError(
            provider=schemas.ClassCredentialProvider.ELEVENLABS,
            message="Unable to validate the ElevenLabs voice right now.",
        ) from exc
    except ValueError as exc:
        logger.warning(
            "ElevenLabs voice validation failed due to credential error. voice_id=%s",
            safe_voice_id,
            exc_info=exc,
        )
        raise ClassCredentialValidationUnavailableError(
            provider=schemas.ClassCredentialProvider.ELEVENLABS,
            message="Unable to validate the ElevenLabs voice right now.",
        ) from exc
    except ClassCredentialValidationUnavailableError:
        # Preserve the original unavailable error instead of wrapping it again below.
        raise
    except Exception as exc:
        logger.warning(
            "Failed to validate ElevenLabs voice_id=%s due to provider error.",
            safe_voice_id,
            exc_info=exc,
        )
        raise ClassCredentialValidationUnavailableError(
            provider=schemas.ClassCredentialProvider.ELEVENLABS,
            message="Unable to validate the ElevenLabs voice right now.",
        ) from exc


async def validate_elevenlabs_api_key(api_key: str) -> bool:
    try:
        client = get_elevenlabs_client(api_key)
        safe_provider = sanitize_for_log(
            schemas.ClassCredentialProvider.ELEVENLABS.value
        )
        await asyncio.wait_for(client.voices.settings.get_default(), 10)
        return True
    except ValueError:
        return False
    except ElevenLabsUnauthorizedError:
        return False
    except asyncio.TimeoutError as exc:
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
