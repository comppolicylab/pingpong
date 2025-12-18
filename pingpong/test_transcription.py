import os
import pytest
import pingpong.transcription as transcription_module

from openai.types.audio.transcription_diarized import TranscriptionDiarized
from openai.types.beta.threads.message import Message as OpenAIThreadMessage


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
        transcription_module.format_diarized_transcription_txt(transcription)
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

    mapping = transcription_module.infer_speaker_display_names_from_thread_messages(
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

    mapping = transcription_module.infer_speaker_display_names_from_thread_messages(
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

    mapping = transcription_module.infer_speaker_display_names_from_thread_messages(
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

    mapping = transcription_module.infer_speaker_display_names_from_thread_messages(
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

    assert transcription_module._iter_diarized_chunks(transcription) == [
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

    assert transcription_module._iter_diarized_chunks(transcription) == [
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

    assert transcription_module._iter_diarized_chunks(transcription) == [
        ("unknown", 0.0, 2.0, "Hello world")
    ]


def test_normalize_text_handles_empty_and_whitespace() -> None:
    assert transcription_module._normalize_text("") == ""
    assert transcription_module._normalize_text("   \n\t  ") == ""


def test_normalize_text_strips_special_chars_and_collapses_spaces() -> None:
    assert transcription_module._normalize_text("Hello,   world!!!") == "hello world"
    assert transcription_module._normalize_text("C++ / Python\t3.11") == "c python 3 11"


def test_token_set_splits_and_dedupes() -> None:
    assert transcription_module._token_set("") == set()
    assert transcription_module._token_set("Hello world world") == {"hello", "world"}
    assert transcription_module._token_set("  hello   ") == {"hello"}
    assert transcription_module._token_set_from_normalized("hello world world") == {
        "hello",
        "world",
    }


def test_similarity_returns_zero_for_empty_inputs() -> None:
    assert transcription_module._similarity("", "anything") == 0.0
    assert transcription_module._similarity("anything", "") == 0.0
    assert transcription_module._similarity("", "") == 0.0


def test_similarity_handles_partial_overlap() -> None:
    # One token in common out of min(2,2) => 0.5
    assert transcription_module._similarity("hello world", "hello there") == 0.5
    assert transcription_module._similarity("alpha beta", "gamma delta") == 0.0


def test_similarity_substring_match_is_strong_signal() -> None:
    a = "this is a sufficiently long phrase to trigger substring matching"
    b = f"prefix {a} suffix"
    assert transcription_module._similarity(a, b) == 1.0


def test_rescale_diarized_transcription_timestamps_scales_duration_and_segments() -> (
    None
):
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
                    "start": 1.0,
                    "end": 2.0,
                    "text": "Hello",
                },
                {
                    "id": "seg_2",
                    "type": "transcript.text.segment",
                    "speaker": "spk_1",
                    "start": 2.0,
                    "end": 4.0,
                    "text": "world",
                },
            ],
        }
    )

    transcription_module._rescale_diarized_transcription_timestamps(
        transcription, factor=1.25
    )

    assert transcription.duration == 12.5
    assert transcription.segments[0].start == 1.25
    assert transcription.segments[0].end == 2.5
    assert transcription.segments[1].start == 2.5
    assert transcription.segments[1].end == 5.0


def test_rescale_diarized_transcription_timestamps_handles_missing_or_none_values() -> (
    None
):
    class SegmentWithOptionalTimestamps:
        def __init__(self, start, end):
            self.start = start
            self.end = end

    class SegmentWithoutTimestamps:
        pass

    class TranscriptionLike:
        def __init__(self, segments):
            self.segments = segments

    seg_none_start = SegmentWithOptionalTimestamps(start=None, end=2.0)
    seg_missing_fields = SegmentWithoutTimestamps()
    transcription = TranscriptionLike(segments=[seg_none_start, seg_missing_fields])

    transcription_module._rescale_diarized_transcription_timestamps(
        transcription, factor=1.5
    )

    assert seg_none_start.start is None
    assert seg_none_start.end == 3.0


def test_prepare_audio_file_for_transcription_returns_original_path_when_under_target(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeAudio:
        def __len__(self) -> int:
            return 99_000  # 99 seconds

        def set_frame_rate(self, _rate: int):
            return self

        def set_channels(self, _channels: int):
            return self

        def set_sample_width(self, _width: int):
            return self

    monkeypatch.setattr(transcription_module, "_TRANSCRIPTION_TARGET_SECONDS", 100.0)
    monkeypatch.setattr(
        transcription_module.AudioSegment, "from_file", lambda _p: FakeAudio()
    )
    monkeypatch.setattr(
        transcription_module,
        "speedup",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("speedup() should not be called")
        ),
    )
    monkeypatch.setattr(
        transcription_module.tempfile,
        "NamedTemporaryFile",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("NamedTemporaryFile() should not be called")
        ),
    )

    input_path = "/tmp/in.webm"
    path_to_send, factor, cleanup_path = (
        transcription_module._prepare_audio_file_for_transcription(
            input_path=input_path
        )
    )
    assert path_to_send == input_path
    assert factor == 1.0
    assert cleanup_path is None


def test_prepare_audio_file_for_transcription_speeds_up_and_returns_actual_factor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeAudio:
        def __init__(self, duration_ms: int):
            self.duration_ms = duration_ms

        def __len__(self) -> int:
            return self.duration_ms

        def set_frame_rate(self, _rate: int):
            return self

        def set_channels(self, _channels: int):
            return self

        def set_sample_width(self, _width: int):
            return self

    class FakeSped(FakeAudio):
        def export(
            self, path: str, format: str, codec: str, parameters: list[str]
        ) -> None:
            assert format == "webm"
            assert codec == "libopus"
            assert "-application" in parameters and "voip" in parameters
            assert "-ac" in parameters and "1" in parameters
            assert "-ar" in parameters and "24000" in parameters
            # Touch the file to emulate export output.
            with open(path, "ab"):
                pass

    monkeypatch.setattr(transcription_module, "_TRANSCRIPTION_TARGET_SECONDS", 100.0)
    monkeypatch.setattr(
        transcription_module.AudioSegment, "from_file", lambda _p: FakeAudio(200_000)
    )

    def fake_speedup(audio: FakeAudio, *, playback_speed: float) -> FakeSped:
        assert playback_speed == 2.0  # 200s / 100s target
        return FakeSped(120_000)  # 120 seconds after speedup

    monkeypatch.setattr(transcription_module, "speedup", fake_speedup)

    path_to_send, factor, cleanup_path = (
        transcription_module._prepare_audio_file_for_transcription(
            input_path="/tmp/in.webm"
        )
    )
    try:
        assert cleanup_path == path_to_send
        assert isinstance(path_to_send, str) and path_to_send.endswith(".webm")
        assert os.path.exists(path_to_send)
        assert abs(factor - (200.0 / 120.0)) < 1e-9
    finally:
        if cleanup_path and os.path.exists(cleanup_path):
            os.remove(cleanup_path)


def test_prepare_audio_file_for_transcription_export_failure_removes_tempfile(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    class FakeAudio:
        def __len__(self) -> int:
            return 200_000  # 200 seconds

        def set_frame_rate(self, _rate: int):
            return self

        def set_channels(self, _channels: int):
            return self

        def set_sample_width(self, _width: int):
            return self

    class FakeSped:
        def __len__(self) -> int:
            return 100_000  # 100 seconds

        def export(
            self, _path: str, format: str, codec: str, parameters: list[str]
        ) -> None:
            raise RuntimeError("export failed")

    class _Tmp:
        def __init__(self, name: str):
            self.name = name

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb) -> None:
            return None

    out_path = tmp_path / "out.webm"

    def fake_named_tempfile(*_args, **_kwargs):
        out_path.write_bytes(b"")
        return _Tmp(str(out_path))

    monkeypatch.setattr(transcription_module, "_TRANSCRIPTION_TARGET_SECONDS", 100.0)
    monkeypatch.setattr(
        transcription_module.AudioSegment, "from_file", lambda _p: FakeAudio()
    )
    monkeypatch.setattr(transcription_module, "speedup", lambda *_a, **_k: FakeSped())
    monkeypatch.setattr(
        transcription_module.tempfile, "NamedTemporaryFile", fake_named_tempfile
    )

    with pytest.raises(RuntimeError, match="export failed"):
        transcription_module._prepare_audio_file_for_transcription(
            input_path="/tmp/in.webm"
        )

    assert not out_path.exists()


def test_prepare_audio_file_for_transcription_sped_duration_zero_uses_requested_factor(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    class FakeAudio:
        def __len__(self) -> int:
            return 200_000  # 200 seconds

        def set_frame_rate(self, _rate: int):
            return self

        def set_channels(self, _channels: int):
            return self

        def set_sample_width(self, _width: int):
            return self

    class FakeSped:
        def __len__(self) -> int:
            return 0

        def export(
            self, path: str, format: str, codec: str, parameters: list[str]
        ) -> None:
            (tmp_path / "exported").write_text("ok")
            with open(path, "ab"):
                pass

    class _Tmp:
        def __init__(self, name: str):
            self.name = name

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb) -> None:
            return None

    out_path = tmp_path / "out.webm"

    def fake_named_tempfile(*_args, **_kwargs):
        out_path.write_bytes(b"")
        return _Tmp(str(out_path))

    monkeypatch.setattr(transcription_module, "_TRANSCRIPTION_TARGET_SECONDS", 100.0)
    monkeypatch.setattr(
        transcription_module.AudioSegment, "from_file", lambda _p: FakeAudio()
    )
    monkeypatch.setattr(transcription_module, "speedup", lambda *_a, **_k: FakeSped())
    monkeypatch.setattr(
        transcription_module.tempfile, "NamedTemporaryFile", fake_named_tempfile
    )

    path_to_send, factor, cleanup_path = (
        transcription_module._prepare_audio_file_for_transcription(
            input_path="/tmp/in.webm"
        )
    )
    try:
        assert path_to_send == str(out_path)
        assert cleanup_path == str(out_path)
        assert factor == 2.0  # requested_factor, because sped_duration_seconds == 0
    finally:
        if cleanup_path and os.path.exists(cleanup_path):
            os.remove(cleanup_path)
