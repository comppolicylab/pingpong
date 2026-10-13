from types import SimpleNamespace

import pytest

from pingpong.caption_text import caption_display_length, caption_token_spans
from pingpong.elevenlabs import _timing_words_from_alignment
from pingpong.lecture_slide_processing import _display_word_timings
from pingpong.lecture_video_service import _caption_cues_from_words
from pingpong.schemas import LectureVideoManifestWordV3


def aligned_words(text, step=0.1):
    return _timing_words_from_alignment(
        SimpleNamespace(
            characters=list(text),
            character_start_times_seconds=[i * step for i in range(len(text))],
            character_end_times_seconds=[(i + 1) * step for i in range(len(text))],
        )
    )


def manifest_words(words):
    return [
        LectureVideoManifestWordV3(
            id=str(i),
            word=w.word,
            start_offset_ms=w.start_ms,
            end_offset_ms=w.end_ms,
            join_left=w.join_left,
        )
        for i, w in enumerate(words)
    ]


@pytest.mark.parametrize(
    "text",
    [
        "この講義ではChatGPTと人工知能について説明します。" * 12,
        "人工智能可以帮助我们理解复杂的问题。" * 12,
        "ภาษาไทยไม่มีช่องว่างระหว่างคำ" * 12,
        "日本語の長い文です" * 20,
    ],
)
def test_unspaced_captions_keep_text_and_provider_timestamps(text):
    words = aligned_words(text)
    cues = _caption_cues_from_words(manifest_words(words))
    assert len(cues) > 1
    assert "".join(cue[2] for cue in cues) == text
    assert all(caption_display_length(cue[2]) <= 84 for cue in cues)
    assert all(end - start <= 5000 for start, end, _ in cues)
    assert cues[0][0] == 0
    assert cues[-1][1] == round(len(text) * 100)
    for start, end, _ in cues:
        assert start in {w.start_ms for w in words}
        assert end in {w.end_ms for w in words}


def test_graphemes_and_mixed_script_spaces_are_retained():
    text = "か\u3099くせい ChatGPT 👩🏽\u200d💻。"
    words = aligned_words(text)
    assert words[0].word == "か\u3099"
    assert words[0].end_ms == 200
    assert any(w.word == "👩🏽\u200d💻" for w in words)
    cues = _caption_cues_from_words(manifest_words(words))
    assert cues[0][2] == text


def test_japanese_pronunciation_override_does_not_recombine_passage():
    speech = "この講義ではチャットジーピーティーを説明します。次の文です。"
    display = "この講義ではChatGPTを説明します。次の文です。"
    words = _display_word_timings(
        aligned_words(speech), display_text=display, speech_text=speech
    )
    cues = _caption_cues_from_words(manifest_words(words))
    assert "".join(cue[2] for cue in cues) == display
    assert len(cues) == 2
    assert cues[-1][1] == len(speech) * 100


def test_english_words_and_sentence_breaks_are_unchanged():
    words = aligned_words("Hello world! Next sentence.")
    assert [w.word for w in words] == ["Hello", "world!", "Next", "sentence."]
    cues = _caption_cues_from_words(manifest_words(words))
    assert [cue[2] for cue in cues] == ["Hello world!", "Next sentence."]


def test_question_boundary_clips_caption():
    words = manifest_words(aligned_words("この文の途中で質問します。"))
    cues = _caption_cues_from_words(words, split_offsets_ms=[500])
    assert cues[0][1] == 500
    assert cues[1][0] == 500


def test_long_unspaced_latin_token_keeps_grapheme_boundaries():
    text = "a" * 100
    spans = caption_token_spans(text)
    assert "".join(text[start:end] for start, end in spans) == text
    assert len(spans) == 100
