import logging
import ssl

from elevenlabs.client import AsyncElevenLabs
from elevenlabs.errors import UnauthorizedError as ElevenLabsUnauthorizedError
from google import genai

from pingpong import schemas
from pingpong.log_utils import sanitize_for_log

logger = logging.getLogger(__name__)


_EXPECTED_PROVIDER_BY_PURPOSE = {
    schemas.ClassCredentialPurpose.LECTURE_VIDEO_NARRATION_TTS: schemas.ClassCredentialProvider.ELEVENLABS,
    schemas.ClassCredentialPurpose.LECTURE_VIDEO_MANIFEST_GENERATION: schemas.ClassCredentialProvider.GEMINI,
}


class ClassCredentialValidationUnavailableError(Exception):
    def __init__(
        self,
        provider: schemas.ClassCredentialProvider,
        message: str,
    ) -> None:
        super().__init__(message)
        self.provider = provider


class ClassCredentialValidationSSLError(ClassCredentialValidationUnavailableError):
    pass


def provider_matches_purpose(
    provider: schemas.ClassCredentialProvider,
    purpose: schemas.ClassCredentialPurpose,
) -> bool:
    return _EXPECTED_PROVIDER_BY_PURPOSE[purpose] == provider


def expected_provider_for_purpose(
    purpose: schemas.ClassCredentialPurpose,
) -> schemas.ClassCredentialProvider:
    return _EXPECTED_PROVIDER_BY_PURPOSE[purpose]


async def validate_class_credential(
    api_key: str,
    provider: schemas.ClassCredentialProvider,
) -> bool:
    safe_provider = sanitize_for_log(provider.value)
    if provider == schemas.ClassCredentialProvider.ELEVENLABS:
        client = AsyncElevenLabs(api_key=api_key)
        try:
            await client.voices.settings.get_default()
            return True
        except ElevenLabsUnauthorizedError:
            return False
        except ssl.SSLError as exc:
            logger.warning(
                "SSL error validating %s class credential.",
                safe_provider,
                exc_info=exc,
            )
            raise ClassCredentialValidationSSLError(
                provider=provider,
                message="Unable to validate the ElevenLabs API key due to an SSL error.",
            ) from exc
        except Exception as exc:
            logger.warning(
                "Failed to validate %s class credential due to provider error.",
                safe_provider,
                exc_info=exc,
            )
            raise ClassCredentialValidationUnavailableError(
                provider=provider,
                message="Unable to validate the ElevenLabs API key right now.",
            ) from exc
    elif provider == schemas.ClassCredentialProvider.GEMINI:
        try:
            async with genai.Client(api_key=api_key).aio as aclient:
                await aclient.models.list(config={"page_size": 1})
            return True
        except genai.errors.APIError as exc:
            status_code = getattr(exc, "code", None)
            message = str(exc)
            if status_code in {400, 401, 403} and (
                "API_KEY_INVALID" in message or "API key not valid" in message
            ):
                return False
            logger.warning(
                "Failed to validate %s class credential due to provider API error.",
                safe_provider,
                exc_info=exc,
            )
            raise ClassCredentialValidationUnavailableError(
                provider=provider,
                message="Unable to validate the Gemini API key right now.",
            ) from exc
        except ssl.SSLError as exc:
            logger.warning(
                "SSL error validating %s class credential.",
                safe_provider,
                exc_info=exc,
            )
            raise ClassCredentialValidationSSLError(
                provider=provider,
                message="Unable to validate the Gemini API key due to an SSL error.",
            ) from exc
        except Exception as exc:
            logger.warning(
                "Failed to validate %s class credential due to provider error.",
                safe_provider,
                exc_info=exc,
            )
            raise ClassCredentialValidationUnavailableError(
                provider=provider,
                message="Unable to validate the Gemini API key right now.",
            ) from exc
    raise ValueError(f"Unsupported class credential provider: {provider}")
