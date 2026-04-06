from types import SimpleNamespace

import pingpong.schemas as schemas
from pingpong.lecture_video_chat import (
    TRANSCRIPT_CONTEXT_WINDOW_MS,
    _build_context_text,
    _serialize_transcript_words,
)


def _build_manifest_question():
    return schemas.LectureVideoManifestQuestionV1(
        type=schemas.LectureVideoQuestionType.SINGLE_SELECT,
        question_text='What matters here?',
        intro_text='Think about timing.',
        stop_offset_ms=999_999,
        options=[
            schemas.LectureVideoManifestOptionV1(
                option_text='Latency',
                post_answer_text='Correct.',
                continue_offset_ms=1_000_000,
                correct=True,
            ),
            schemas.LectureVideoManifestOptionV1(
                option_text='Color',
                post_answer_text='Incorrect.',
                continue_offset_ms=1_000_000,
                correct=False,
            ),
        ],
    )


def test_serialize_transcript_words_preserves_millisecond_integer_timestamps():
    words = [
        schemas.LectureVideoManifestWordV2(
            id="w1",
            word="Latency",
            start=400,
            end=900,
        ),
        schemas.LectureVideoManifestWordV2(
            id="w2",
            word="matters",
            start=950,
            end=1400,
        ),
    ]

    assert _serialize_transcript_words(words) == [
        (400, 900, "Latency"),
        (950, 1400, "matters"),
    ]


def test_serialize_transcript_words_preserves_second_integer_timestamps():
    words = [
        schemas.LectureVideoManifestWordV2(
            id="w1",
            word="Protocol",
            start=10_800,
            end=10_801,
        ),
        schemas.LectureVideoManifestWordV2(
            id="w2",
            word="switch",
            start=10_801,
            end=10_802,
        ),
    ]

    assert _serialize_transcript_words(words) == [
        (10_800_000, 10_801_000, "Protocol"),
        (10_801_000, 10_802_000, "switch"),
    ]


def test_build_context_text_caps_initial_transcript_context_window():
    thread = SimpleNamespace(lecture_video=SimpleNamespace(questions=[]))
    state = SimpleNamespace(
        last_known_offset_ms=180_000,
        last_chat_context_end_ms=0,
        current_question=None,
        current_question_id=None,
        state=SimpleNamespace(value='active'),
    )
    manifest = schemas.LectureVideoManifestV2(
        version=2,
        word_level_transcription=[
            schemas.LectureVideoManifestWordV2(
                id='w1',
                word='intro',
                start=10,
                end=11,
            ),
            schemas.LectureVideoManifestWordV2(
                id='w2',
                word='recent',
                start=(180_000 - TRANSCRIPT_CONTEXT_WINDOW_MS) / 1000,
                end=((180_000 - TRANSCRIPT_CONTEXT_WINDOW_MS) / 1000) + 1,
            ),
            schemas.LectureVideoManifestWordV2(
                id='w3',
                word='now',
                start=179,
                end=180,
            ),
        ],
        questions=[_build_manifest_question()],
    )

    context_text, current_offset_ms = _build_context_text(thread, state, manifest)

    assert current_offset_ms == 180_000
    assert 'Recent transcript context' in context_text
    assert '(older transcript omitted)' in context_text
    assert 'intro' not in context_text
    assert 'recent now' in context_text


def test_build_context_text_caps_transcript_since_last_chat():
    thread = SimpleNamespace(lecture_video=SimpleNamespace(questions=[]))
    state = SimpleNamespace(
        last_known_offset_ms=300_000,
        last_chat_context_end_ms=30_000,
        current_question=None,
        current_question_id=None,
        state=SimpleNamespace(value='active'),
    )
    manifest = schemas.LectureVideoManifestV2(
        version=2,
        word_level_transcription=[
            schemas.LectureVideoManifestWordV2(
                id='w1',
                word='stale',
                start=40,
                end=41,
            ),
            schemas.LectureVideoManifestWordV2(
                id='w2',
                word='fresh',
                start=(300_000 - TRANSCRIPT_CONTEXT_WINDOW_MS) / 1000,
                end=((300_000 - TRANSCRIPT_CONTEXT_WINDOW_MS) / 1000) + 1,
            ),
            schemas.LectureVideoManifestWordV2(
                id='w3',
                word='context',
                start=299,
                end=300,
            ),
        ],
        questions=[_build_manifest_question()],
    )

    context_text, current_offset_ms = _build_context_text(thread, state, manifest)

    assert current_offset_ms == 300_000
    assert 'Recent transcript since last lecture chat' in context_text
    assert '(older transcript omitted)' in context_text
    assert 'stale' not in context_text
    assert 'fresh context' in context_text
