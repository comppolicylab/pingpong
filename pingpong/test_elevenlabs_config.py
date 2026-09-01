from types import SimpleNamespace

from pingpong import schemas
from pingpong.elevenlabs_config import (
    config_payload,
    legacy_assistant_config,
    pronunciation_cache_key,
    voice_settings_for_profile,
)


def test_new_config_defaults_generation_to_v3_and_live_chat_to_flash():
    config = schemas.ElevenLabsConfig()

    assert config.narration.model == schemas.ElevenLabsTTSModel.V3
    assert config.knowledge_check.model == schemas.ElevenLabsTTSModel.V3
    assert config.live_chat.model == schemas.ElevenLabsTTSModel.FLASH_V2_5


def test_legacy_config_preserves_flash_chat_settings_but_defaults_generation_to_v3():
    assistant = SimpleNamespace(
        elevenlabs_stability=0.9,
        elevenlabs_similarity_boost=0.4,
        elevenlabs_use_speaker_boost=False,
        elevenlabs_style=0.2,
        elevenlabs_speed=1.1,
    )

    config = legacy_assistant_config(assistant)

    assert config.narration.model == schemas.ElevenLabsTTSModel.V3
    assert config.knowledge_check.model == schemas.ElevenLabsTTSModel.V3
    assert config.knowledge_check.stability == 0.5
    assert config.live_chat.model == schemas.ElevenLabsTTSModel.FLASH_V2_5
    assert config.live_chat.stability == 0.9
    assert config.live_chat.use_speaker_boost is False


def test_voice_settings_include_every_setting_for_both_models():
    flash = schemas.ElevenLabsTTSProfile(
        model=schemas.ElevenLabsTTSModel.FLASH_V2_5,
        stability=0.9,
        similarity_boost=0.4,
        use_speaker_boost=False,
        style=0.2,
        speed=1.1,
    )
    v3 = schemas.ElevenLabsTTSProfile(
        model=schemas.ElevenLabsTTSModel.V3,
        stability=0.7,
        similarity_boost=0.3,
        use_speaker_boost=False,
        style=0.4,
        speed=0.8,
    )

    assert voice_settings_for_profile(flash) == {
        "stability": 0.9,
        "similarity_boost": 0.4,
        "use_speaker_boost": False,
        "style": 0.2,
        "speed": 1.1,
    }
    assert voice_settings_for_profile(v3) == {
        "stability": 0.7,
        "similarity_boost": 0.3,
        "use_speaker_boost": False,
        "style": 0.4,
        "speed": 0.8,
    }


def test_pronunciation_cache_key_changes_when_authored_hint_changes():
    first = pronunciation_cache_key(
        language_code="en",
        written="lead",
        authored_spoken="leed",
    )
    second = pronunciation_cache_key(
        language_code="en",
        written="lead",
        authored_spoken="led",
    )

    assert first != second
    payload = config_payload(
        schemas.ElevenLabsConfig(),
        existing_raw={"pronunciation_cache": {first: "liːd"}},
    )
    assert payload["pronunciation_cache"] == {first: "liːd"}
