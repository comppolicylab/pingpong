import pingpong.elevenlabs as elevenlabs
from pingpong import schemas
from pingpong.server import _lecture_slide_languages


def test_published_flash_v2_5_language_list_is_static_and_sorted():
    languages = elevenlabs.ELEVENLABS_FLASH_V2_5_LANGUAGES

    assert len(languages) == 32
    assert [language.name for language in languages] == sorted(
        (language.name for language in languages),
        key=str.casefold,
    )
    assert elevenlabs.ElevenLabsLanguage("en", "English") in languages
    assert elevenlabs.ElevenLabsLanguage("es", "Spanish") in languages


def test_published_v3_language_list_is_static_and_broader_than_flash():
    languages = elevenlabs.ELEVENLABS_V3_LANGUAGES

    assert len(languages) == 74
    assert [language.name for language in languages] == sorted(
        (language.name for language in languages),
        key=str.casefold,
    )
    assert set(elevenlabs.ELEVENLABS_FLASH_V2_5_LANGUAGES) < set(languages)


def test_translation_language_response_follows_narration_model():
    flash = _lecture_slide_languages(
        can_prepare=True,
        model=schemas.ElevenLabsTTSModel.FLASH_V2_5,
    )
    v3 = _lecture_slide_languages(
        can_prepare=True,
        model=schemas.ElevenLabsTTSModel.V3,
    )

    assert len(flash.languages) == 33  # original + 32 Flash languages
    assert len(v3.languages) == 75  # original + 74 v3 languages
    assert "cy" not in {language.code for language in flash.languages}
    assert "cy" in {language.code for language in v3.languages}
