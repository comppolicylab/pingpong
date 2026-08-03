import pingpong.elevenlabs as elevenlabs


def test_published_v3_language_list_is_static_and_sorted():
    languages = elevenlabs.ELEVENLABS_V3_LANGUAGES

    assert len(languages) == 74
    assert [language.name for language in languages] == sorted(
        (language.name for language in languages),
        key=str.casefold,
    )
    assert elevenlabs.ElevenLabsLanguage("en", "English") in languages
    assert elevenlabs.ElevenLabsLanguage("es", "Spanish") in languages
