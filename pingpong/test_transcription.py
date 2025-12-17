from openai.types.audio.transcription_diarized import TranscriptionDiarized
from openai.types.beta.threads.message import Message as OpenAIThreadMessage

from pingpong.transcription import (
    format_diarized_transcription_txt,
    infer_speaker_display_names_from_thread_messages,
    _iter_diarized_chunks,
    _normalize_text,
    _similarity,
    _token_set,
)


def _msg(
    *,
    role: str,
    text: str,
    metadata: dict[str, object] | None = None,
    msg_id: str = "msg_1",
    thread_id: str = "thread_1",
) -> OpenAIThreadMessage:
    return OpenAIThreadMessage.model_validate(
        {
            "id": msg_id,
            "object": "thread.message",
            "created_at": 0,
            "thread_id": thread_id,
            "role": role,
            "status": "completed",
            "content": [
                {"type": "text", "text": {"value": text, "annotations": []}},
            ],
            "metadata": metadata or {},
        }
    )


def test_format_diarized_transcription_txt_collapses_consecutive_segments() -> None:
    transcription = TranscriptionDiarized.model_validate(
        {
            "duration": 4.0,
            "task": "transcribe",
            "text": "",
            "segments": [
                {
                    "id": "seg_1",
                    "type": "transcript.text.segment",
                    "speaker": "spk_1",
                    "start": 0.0,
                    "end": 1.0,
                    "text": "Hello",
                },
                {
                    "id": "seg_2",
                    "type": "transcript.text.segment",
                    "speaker": "spk_1",
                    "start": 1.0,
                    "end": 2.0,
                    "text": "there",
                },
                {
                    "id": "seg_3",
                    "type": "transcript.text.segment",
                    "speaker": "spk_2",
                    "start": 2.0,
                    "end": 3.0,
                    "text": "Hi",
                },
                {
                    "id": "seg_4",
                    "type": "transcript.text.segment",
                    "speaker": "spk_1",
                    "start": 3.0,
                    "end": 4.0,
                    "text": "Back",
                },
            ],
        }
    )

    assert (
        format_diarized_transcription_txt(transcription)
        == "Speaker 1 (00:00-00:02)\nHello there\n\n"
        "Speaker 2 (00:02-00:03)\nHi\n\n"
        "Speaker 1 (00:03-00:04)\nBack\n"
    )


def test_infer_speaker_display_names_maps_assistant_and_user() -> None:
    transcription = TranscriptionDiarized.model_validate(
        {
            "duration": 12.0,
            "task": "transcribe",
            "text": "",
            "segments": [
                {
                    "id": "seg_1",
                    "type": "transcript.text.segment",
                    "speaker": "spk_a",
                    "start": 0.0,
                    "end": 4.0,
                    "text": "Sure — here's a quick overview of photosynthesis and why plants do it.",
                },
                {
                    "id": "seg_2",
                    "type": "transcript.text.segment",
                    "speaker": "spk_u",
                    "start": 4.0,
                    "end": 8.0,
                    "text": "Can you explain photosynthesis quickly in simple terms?",
                },
            ],
        }
    )

    thread_messages = [
        _msg(
            role="assistant",
            msg_id="msg_a",
            text="Here's a quick overview of photosynthesis and why plants do it.",
        ),
        _msg(
            role="user",
            msg_id="msg_u",
            metadata={"user_id": "123"},
            text="Can you explain photosynthesis quickly in simple terms?",
        ),
    ]

    mapping = infer_speaker_display_names_from_thread_messages(
        transcription=transcription,
        thread_messages=thread_messages,
        user_id_to_name={123: "Curious Otter"},
    )

    assert mapping == {"spk_a": "Assistant", "spk_u": "Curious Otter"}


def test_infer_speaker_display_names_prefers_assistant_on_vote_tie() -> None:
    transcription = TranscriptionDiarized.model_validate(
        {
            "duration": 20.0,
            "task": "transcribe",
            "text": "",
            "segments": [
                {
                    "id": "seg_1",
                    "type": "transcript.text.segment",
                    "speaker": "spk_mix",
                    "start": 0.0,
                    "end": 4.0,
                    "text": "Let's solve the problem step by step and verify the result.",
                },
                {
                    "id": "seg_2",
                    "type": "transcript.text.segment",
                    "speaker": "spk_other",
                    "start": 4.0,
                    "end": 8.0,
                    "text": "Okay.",
                },
                {
                    "id": "seg_3",
                    "type": "transcript.text.segment",
                    "speaker": "spk_mix",
                    "start": 8.0,
                    "end": 12.0,
                    "text": "Wait, I'm confused — can you repeat that last part?",
                },
            ],
        }
    )

    thread_messages = [
        _msg(
            role="assistant",
            msg_id="msg_a",
            text="Let's solve the problem step by step and verify the result.",
        ),
        _msg(
            role="user",
            msg_id="msg_u",
            metadata={"user_id": "123"},
            text="I'm confused — can you repeat that last part?",
        ),
    ]

    mapping = infer_speaker_display_names_from_thread_messages(
        transcription=transcription,
        thread_messages=thread_messages,
        user_id_to_name={123: "User One"},
    )

    assert mapping.get("spk_mix") == "Assistant"


def test_infer_speaker_display_names_does_not_map_user_without_user_id() -> None:
    transcription = TranscriptionDiarized.model_validate(
        {
            "duration": 8.0,
            "task": "transcribe",
            "text": "",
            "segments": [
                {
                    "id": "seg_1",
                    "type": "transcript.text.segment",
                    "speaker": "spk_u",
                    "start": 0.0,
                    "end": 4.0,
                    "text": "Can you help me with this homework question about fractions?",
                },
            ],
        }
    )

    thread_messages = [
        _msg(
            role="user",
            msg_id="msg_u",
            metadata={},  # no user_id available
            text="Can you help me with this homework question about fractions?",
        )
    ]

    mapping = infer_speaker_display_names_from_thread_messages(
        transcription=transcription,
        thread_messages=thread_messages,
        user_id_to_name={123: "User One"},
    )

    assert mapping == {}


def test_infer_speaker_display_names_requires_similarity_match() -> None:
    transcription = TranscriptionDiarized.model_validate(
        {
            "duration": 8.0,
            "task": "transcribe",
            "text": "",
            "segments": [
                {
                    "id": "seg_1",
                    "type": "transcript.text.segment",
                    "speaker": "spk_1",
                    "start": 0.0,
                    "end": 4.0,
                    "text": "Completely unrelated content that should not match anything.",
                },
            ],
        }
    )

    thread_messages = [
        _msg(
            role="assistant",
            msg_id="msg_a",
            text="This is about a different topic entirely and won't overlap.",
        )
    ]

    mapping = infer_speaker_display_names_from_thread_messages(
        transcription=transcription,
        thread_messages=thread_messages,
        user_id_to_name={123: "User One"},
    )

    assert mapping == {}


def test_iter_diarized_chunks_collapses_consecutive_speaker_segments() -> None:
    transcription = TranscriptionDiarized.model_validate(
        {
            "duration": 10.0,
            "task": "transcribe",
            "text": "",
            "segments": [
                {
                    "id": "seg_1",
                    "type": "transcript.text.segment",
                    "speaker": "spk_1",
                    "start": 0.0,
                    "end": 1.0,
                    "text": "Hello",
                },
                {
                    "id": "seg_2",
                    "type": "transcript.text.segment",
                    "speaker": "spk_1",
                    "start": 1.0,
                    "end": 2.5,
                    "text": "there",
                },
                {
                    "id": "seg_3",
                    "type": "transcript.text.segment",
                    "speaker": "spk_2",
                    "start": 2.5,
                    "end": 3.0,
                    "text": "Hi",
                },
                {
                    "id": "seg_4",
                    "type": "transcript.text.segment",
                    "speaker": "spk_1",
                    "start": 3.0,
                    "end": 4.0,
                    "text": "Back",
                },
            ],
        }
    )

    assert _iter_diarized_chunks(transcription) == [
        ("spk_1", 0.0, 2.5, "Hello there"),
        ("spk_2", 2.5, 3.0, "Hi"),
        ("spk_1", 3.0, 4.0, "Back"),
    ]


def test_iter_diarized_chunks_skips_empty_text_parts_and_preserves_boundaries() -> None:
    transcription = TranscriptionDiarized.model_validate(
        {
            "duration": 10.0,
            "task": "transcribe",
            "text": "",
            "segments": [
                {
                    "id": "seg_1",
                    "type": "transcript.text.segment",
                    "speaker": "spk_1",
                    "start": 0.0,
                    "end": 1.0,
                    "text": "First",
                },
                {
                    "id": "seg_2",
                    "type": "transcript.text.segment",
                    "speaker": "spk_1",
                    "start": 1.0,
                    "end": 2.0,
                    "text": "",
                },
                {
                    "id": "seg_3",
                    "type": "transcript.text.segment",
                    "speaker": "spk_1",
                    "start": 2.0,
                    "end": 3.0,
                    "text": "Third",
                },
                {
                    "id": "seg_4",
                    "type": "transcript.text.segment",
                    "speaker": "spk_2",
                    "start": 3.0,
                    "end": 4.0,
                    "text": "Other",
                },
            ],
        }
    )

    assert _iter_diarized_chunks(transcription) == [
        ("spk_1", 0.0, 3.0, "First Third"),
        ("spk_2", 3.0, 4.0, "Other"),
    ]


def test_iter_diarized_chunks_uses_unknown_speaker_when_missing() -> None:
    transcription = TranscriptionDiarized.model_validate(
        {
            "duration": 3.0,
            "task": "transcribe",
            "text": "",
            "segments": [
                {
                    "id": "seg_1",
                    "type": "transcript.text.segment",
                    "speaker": "",
                    "start": 0.0,
                    "end": 1.0,
                    "text": "Hello",
                },
                {
                    "id": "seg_2",
                    "type": "transcript.text.segment",
                    "speaker": "",
                    "start": 1.0,
                    "end": 2.0,
                    "text": "world",
                },
            ],
        }
    )

    assert _iter_diarized_chunks(transcription) == [
        ("unknown", 0.0, 2.0, "Hello world")
    ]


def test_normalize_text_handles_empty_and_whitespace() -> None:
    assert _normalize_text("") == ""
    assert _normalize_text("   \n\t  ") == ""


def test_normalize_text_strips_special_chars_and_collapses_spaces() -> None:
    assert _normalize_text("Hello,   world!!!") == "hello world"
    assert _normalize_text("C++ / Python\t3.11") == "c python 3 11"


def test_token_set_splits_and_dedupes() -> None:
    assert _token_set("") == set()
    assert _token_set("Hello world world") == {"hello", "world"}
    assert _token_set("  hello   ") == {"hello"}


def test_similarity_returns_zero_for_empty_inputs() -> None:
    assert _similarity("", "anything") == 0.0
    assert _similarity("anything", "") == 0.0
    assert _similarity("", "") == 0.0


def test_similarity_handles_partial_overlap() -> None:
    # One token in common out of min(2,2) => 0.5
    assert _similarity("hello world", "hello there") == 0.5
    assert _similarity("alpha beta", "gamma delta") == 0.0


def test_similarity_substring_match_is_strong_signal() -> None:
    a = "this is a sufficiently long phrase to trigger substring matching"
    b = f"prefix {a} suffix"
    assert _similarity(a, b) == 1.0
