import hashlib
import json
import logging
from typing import Any, Literal

from pydantic import ValidationError

from pingpong import schemas
from pingpong.elevenlabs_defaults import (
    DEFAULT_ELEVENLABS_SIMILARITY_BOOST,
    DEFAULT_ELEVENLABS_SPEED,
    DEFAULT_ELEVENLABS_STABILITY,
    DEFAULT_ELEVENLABS_STYLE,
    DEFAULT_ELEVENLABS_USE_SPEAKER_BOOST,
)


logger = logging.getLogger(__name__)

ElevenLabsComponent = Literal["narration", "knowledge_check", "live_chat"]
PRONUNCIATION_CACHE_KEY = "pronunciation_cache"
MAX_PRONUNCIATION_CACHE_ENTRIES = 500


def flash_profile(
    *,
    stability: float = DEFAULT_ELEVENLABS_STABILITY,
    similarity_boost: float = DEFAULT_ELEVENLABS_SIMILARITY_BOOST,
    use_speaker_boost: bool = DEFAULT_ELEVENLABS_USE_SPEAKER_BOOST,
    style: float = DEFAULT_ELEVENLABS_STYLE,
    speed: float = DEFAULT_ELEVENLABS_SPEED,
) -> schemas.ElevenLabsTTSProfile:
    return schemas.ElevenLabsTTSProfile(
        model=schemas.ElevenLabsTTSModel.FLASH_V2_5,
        stability=stability,
        similarity_boost=similarity_boost,
        use_speaker_boost=use_speaker_boost,
        style=style,
        speed=speed,
    )


def legacy_assistant_config(assistant: Any) -> schemas.ElevenLabsConfig:
    live_chat = flash_profile(
        stability=(
            assistant.elevenlabs_stability
            if getattr(assistant, "elevenlabs_stability", None) is not None
            else DEFAULT_ELEVENLABS_STABILITY
        ),
        similarity_boost=(
            assistant.elevenlabs_similarity_boost
            if getattr(assistant, "elevenlabs_similarity_boost", None) is not None
            else DEFAULT_ELEVENLABS_SIMILARITY_BOOST
        ),
        use_speaker_boost=(
            assistant.elevenlabs_use_speaker_boost
            if getattr(assistant, "elevenlabs_use_speaker_boost", None) is not None
            else DEFAULT_ELEVENLABS_USE_SPEAKER_BOOST
        ),
        style=(
            assistant.elevenlabs_style
            if getattr(assistant, "elevenlabs_style", None) is not None
            else DEFAULT_ELEVENLABS_STYLE
        ),
        speed=(
            assistant.elevenlabs_speed
            if getattr(assistant, "elevenlabs_speed", None) is not None
            else DEFAULT_ELEVENLABS_SPEED
        ),
    )
    return schemas.ElevenLabsConfig(
        narration=schemas.ElevenLabsTTSProfile(),
        knowledge_check=schemas.ElevenLabsTTSProfile(),
        live_chat=live_chat,
    )


def config_from_assistant(assistant: Any) -> schemas.ElevenLabsConfig:
    raw = getattr(assistant, "elevenlabs_config", None)
    if raw:
        try:
            return schemas.ElevenLabsConfig.model_validate(raw)
        except ValidationError:
            logger.warning(
                "Ignoring invalid ElevenLabs configuration. assistant_id=%s",
                getattr(assistant, "id", None),
                exc_info=True,
            )
    return legacy_assistant_config(assistant)


def profile_for(
    assistant: Any, component: ElevenLabsComponent
) -> schemas.ElevenLabsTTSProfile:
    return getattr(config_from_assistant(assistant), component)


def voice_settings_for_profile(
    profile: schemas.ElevenLabsTTSProfile,
) -> dict[str, Any]:
    return {
        "stability": profile.stability,
        "similarity_boost": profile.similarity_boost,
        "use_speaker_boost": profile.use_speaker_boost,
        "style": profile.style,
        "speed": profile.speed,
    }


def config_payload(
    config: schemas.ElevenLabsConfig,
    *,
    existing_raw: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = config.model_dump(mode="json")
    cache = pronunciation_cache(existing_raw)
    payload[PRONUNCIATION_CACHE_KEY] = cache
    return payload


def pronunciation_cache(raw: dict[str, Any] | None) -> dict[str, str]:
    if not isinstance(raw, dict):
        return {}
    candidate = raw.get(PRONUNCIATION_CACHE_KEY)
    if not isinstance(candidate, dict):
        return {}
    return {
        str(key): str(value)
        for key, value in candidate.items()
        if isinstance(key, str) and isinstance(value, str)
    }


def pronunciation_cache_key(
    *,
    language_code: str | None,
    written: str,
    authored_spoken: str,
) -> str:
    source = json.dumps(
        {
            "language_code": language_code,
            "written": written,
            "authored_spoken": authored_spoken,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(source.encode()).hexdigest()


def with_pronunciation_cache_entries(
    raw: dict[str, Any] | None,
    *,
    entries: dict[str, str],
) -> dict[str, Any]:
    payload = dict(raw or {})
    cache = pronunciation_cache(raw)
    for key, value in entries.items():
        cache.pop(key, None)
        cache[key] = value
    while len(cache) > MAX_PRONUNCIATION_CACHE_ENTRIES:
        cache.pop(next(iter(cache)))
    payload[PRONUNCIATION_CACHE_KEY] = cache
    return payload


def profile_fingerprint(profile: schemas.ElevenLabsTTSProfile) -> str:
    return json.dumps(
        profile.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
    )
