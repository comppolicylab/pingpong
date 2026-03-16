from pingpong import schemas
from pingpong.class_credential_validation import (
    ClassCredentialValidationSSLError,
    ClassCredentialValidationUnavailableError,
    ClassCredentialVoiceValidationError,
)
from pingpong.elevenlabs import (
    validate_elevenlabs_api_key,
)
from pingpong.gemini import validate_gemini_api_key

__all__ = [
    "ClassCredentialValidationSSLError",
    "ClassCredentialValidationUnavailableError",
    "ClassCredentialVoiceValidationError",
    "provider_matches_purpose",
    "expected_provider_for_purpose",
    "validate_class_credential",
]

_EXPECTED_PROVIDER_BY_PURPOSE = {
    schemas.ClassCredentialPurpose.LECTURE_VIDEO_NARRATION_TTS: schemas.ClassCredentialProvider.ELEVENLABS,
    schemas.ClassCredentialPurpose.LECTURE_VIDEO_MANIFEST_GENERATION: schemas.ClassCredentialProvider.GEMINI,
}


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
    if provider == schemas.ClassCredentialProvider.ELEVENLABS:
        return await validate_elevenlabs_api_key(api_key)
    elif provider == schemas.ClassCredentialProvider.GEMINI:
        return await validate_gemini_api_key(api_key)
    raise ValueError(f"Unsupported class credential provider: {provider}")
