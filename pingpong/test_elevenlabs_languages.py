import pingpong.elevenlabs as elevenlabs


def test_published_flash_v2_5_language_list_is_static_and_sorted():
    languages = elevenlabs.ELEVENLABS_FLASH_V2_5_LANGUAGES

    assert len(languages) == 32
    assert [language.name for language in languages] == sorted(
        (language.name for language in languages),
        key=str.casefold,
    )
    assert elevenlabs.ElevenLabsLanguage("en", "English") in languages
    assert elevenlabs.ElevenLabsLanguage("es", "Spanish") in languages
