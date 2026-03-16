from collections.abc import Awaitable, Callable

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

_CLASS_CREDENTIAL_VALIDATORS: dict[
    schemas.ClassCredentialProvider, Callable[[str], Awaitable[bool]]
] = {
    schemas.ClassCredentialProvider.ELEVENLABS: validate_elevenlabs_api_key,
    schemas.ClassCredentialProvider.GEMINI: validate_gemini_api_key,
}

_missing_provider_validators = sorted(
    str(provider)
    for provider in set(schemas.ClassCredentialProvider)
    - set(_CLASS_CREDENTIAL_VALIDATORS)
)
if _missing_provider_validators:
    missing = ", ".join(_missing_provider_validators)
    raise ValueError(f"Missing class credential validators for providers: {missing}")


def _get_expected_provider_for_purpose(
    purpose: schemas.ClassCredentialPurpose,
) -> schemas.ClassCredentialProvider:
    expected_provider = _EXPECTED_PROVIDER_BY_PURPOSE.get(purpose)
    if expected_provider is None:
        raise ValueError(f"Unsupported class credential purpose: {purpose}")
    return expected_provider


def provider_matches_purpose(
    provider: schemas.ClassCredentialProvider,
    purpose: schemas.ClassCredentialPurpose,
) -> bool:
    return _get_expected_provider_for_purpose(purpose) == provider


def expected_provider_for_purpose(
    purpose: schemas.ClassCredentialPurpose,
) -> schemas.ClassCredentialProvider:
    return _get_expected_provider_for_purpose(purpose)


def _get_class_credential_validator(
    provider: schemas.ClassCredentialProvider,
) -> Callable[[str], Awaitable[bool]]:
    validator = _CLASS_CREDENTIAL_VALIDATORS.get(provider)
    if validator is None:
        raise ValueError(f"Unsupported class credential provider: {provider}")
    return validator


async def validate_class_credential(
    api_key: str,
    provider: schemas.ClassCredentialProvider,
) -> bool:
    validator = _get_class_credential_validator(provider)
    return await validator(api_key)
