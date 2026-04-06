from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import pingpong.schemas as schemas
from pingpong.lecture_video_chat import (
    TRANSCRIPT_CONTEXT_WINDOW_MS,
    _build_frame_message_parts,
    _build_context_text,
    _extract_frame,
    _serialize_transcript_words,
)
from pingpong.video_store import VideoInputSource


def _build_manifest_question():
    return schemas.LectureVideoManifestQuestionV1(
        type=schemas.LectureVideoQuestionType.SINGLE_SELECT,
        question_text="What matters here?",
        intro_text="Think about timing.",
        stop_offset_ms=999_999,
        options=[
            schemas.LectureVideoManifestOptionV1(
                option_text="Latency",
                post_answer_text="Correct.",
                continue_offset_ms=1_000_000,
                correct=True,
            ),
            schemas.LectureVideoManifestOptionV1(
                option_text="Color",
                post_answer_text="Incorrect.",
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
        state=SimpleNamespace(value="active"),
    )
    manifest = schemas.LectureVideoManifestV2(
        version=2,
        word_level_transcription=[
            schemas.LectureVideoManifestWordV2(
                id="w1",
                word="intro",
                start=10,
                end=11,
            ),
            schemas.LectureVideoManifestWordV2(
                id="w2",
                word="recent",
                start=(180_000 - TRANSCRIPT_CONTEXT_WINDOW_MS) / 1000,
                end=((180_000 - TRANSCRIPT_CONTEXT_WINDOW_MS) / 1000) + 1,
            ),
            schemas.LectureVideoManifestWordV2(
                id="w3",
                word="now",
                start=179,
                end=180,
            ),
        ],
        questions=[_build_manifest_question()],
    )

    context_text, current_offset_ms = _build_context_text(thread, state, manifest)

    assert current_offset_ms == 180_000
    assert "Recent transcript context" in context_text
    assert "(older transcript omitted)" in context_text
    assert "intro" not in context_text
    assert "recent now" in context_text


def test_build_context_text_caps_transcript_since_last_chat():
    thread = SimpleNamespace(lecture_video=SimpleNamespace(questions=[]))
    state = SimpleNamespace(
        last_known_offset_ms=300_000,
        last_chat_context_end_ms=30_000,
        current_question=None,
        current_question_id=None,
        state=SimpleNamespace(value="active"),
    )
    manifest = schemas.LectureVideoManifestV2(
        version=2,
        word_level_transcription=[
            schemas.LectureVideoManifestWordV2(
                id="w1",
                word="stale",
                start=40,
                end=41,
            ),
            schemas.LectureVideoManifestWordV2(
                id="w2",
                word="fresh",
                start=(300_000 - TRANSCRIPT_CONTEXT_WINDOW_MS) / 1000,
                end=((300_000 - TRANSCRIPT_CONTEXT_WINDOW_MS) / 1000) + 1,
            ),
            schemas.LectureVideoManifestWordV2(
                id="w3",
                word="context",
                start=299,
                end=300,
            ),
        ],
        questions=[_build_manifest_question()],
    )

    context_text, current_offset_ms = _build_context_text(thread, state, manifest)

    assert current_offset_ms == 300_000
    assert "Recent transcript since last lecture chat" in context_text
    assert "(older transcript omitted)" in context_text
    assert "stale" not in context_text
    assert "fresh context" in context_text


def test_build_context_text_clamps_last_chat_context_after_backward_seek():
    thread = SimpleNamespace(lecture_video=SimpleNamespace(questions=[]))
    state = SimpleNamespace(
        last_known_offset_ms=120_000,
        last_chat_context_end_ms=300_000,
        current_question=None,
        current_question_id=None,
        state=SimpleNamespace(value="active"),
    )
    manifest = schemas.LectureVideoManifestV2(
        version=2,
        word_level_transcription=[
            schemas.LectureVideoManifestWordV2(
                id="w1",
                word="earlier",
                start=15,
                end=16,
            ),
            schemas.LectureVideoManifestWordV2(
                id="w2",
                word="context",
                start=119,
                end=120,
            ),
            schemas.LectureVideoManifestWordV2(
                id="w3",
                word="future",
                start=301,
                end=302,
            ),
        ],
        questions=[_build_manifest_question()],
    )

    context_text, current_offset_ms = _build_context_text(thread, state, manifest)

    assert current_offset_ms == 120_000
    assert "Recent transcript context" in context_text
    assert "(older transcript omitted)" not in context_text
    assert "earlier context" in context_text
    assert "future" not in context_text


@pytest.mark.asyncio
async def test_build_frame_message_parts_reraises_unexpected_runtime_error(monkeypatch):
    monkeypatch.setattr(
        "pingpong.lecture_video_chat._get_video_input_source",
        AsyncMock(side_effect=RuntimeError("unexpected bug")),
    )

    with pytest.raises(RuntimeError, match="unexpected bug"):
        await _build_frame_message_parts(
            session=SimpleNamespace(),
            authz=SimpleNamespace(),
            openai_client=SimpleNamespace(),
            thread_id=1,
            lecture_video=SimpleNamespace(
                id=123,
                stored_object=SimpleNamespace(key="video.mp4"),
            ),
            current_offset_ms=5_000,
            class_id=1,
            uploader_id=1,
            user_auth=None,
            anonymous_link_auth=None,
            anonymous_user_auth=None,
            anonymous_session_id=None,
            anonymous_link_id=None,
        )


@pytest.mark.asyncio
async def test_build_frame_message_parts_deduplicates_zero_offsets(monkeypatch):
    extract_calls: list[int] = []
    upload_calls: list[str] = []
    added_image_files: list[str] = []

    async def _fake_extract_frame(_video_url, frame_path, frame_offset_ms):
        extract_calls.append(frame_offset_ms)
        frame_path.write_bytes(b"png")
        return True

    async def _fake_handle_create_file(*_args, upload, **_kwargs):
        upload_calls.append(upload.filename)
        return SimpleNamespace(
            vision_file_id=f"vision-{len(upload_calls)}",
            file_id=f"file-{len(upload_calls)}",
            id=100 + len(upload_calls),
        )

    async def _fake_add_image_files(_session, _thread_id, image_file_ids):
        added_image_files.extend(image_file_ids)

    monkeypatch.setattr(
        "pingpong.lecture_video_chat._get_video_input_source",
        AsyncMock(
            return_value=VideoInputSource(
                url="https://video.test/video.mp4?sig=123",
                ffmpeg_input_args=["-method", "GET"],
            )
        ),
    )
    monkeypatch.setattr(
        "pingpong.lecture_video_chat._extract_frame",
        _fake_extract_frame,
    )
    monkeypatch.setattr(
        "pingpong.lecture_video_chat.handle_create_file",
        _fake_handle_create_file,
    )
    monkeypatch.setattr(
        "pingpong.models.Thread.add_image_files",
        _fake_add_image_files,
    )

    frame_parts = await _build_frame_message_parts(
        session=SimpleNamespace(),
        authz=SimpleNamespace(),
        openai_client=SimpleNamespace(),
        thread_id=1,
        lecture_video=SimpleNamespace(
            id=123,
            stored_object=SimpleNamespace(key="video.mp4"),
        ),
        current_offset_ms=0,
        class_id=1,
        uploader_id=1,
        user_auth=None,
        anonymous_link_auth=None,
        anonymous_user_auth=None,
        anonymous_session_id=None,
        anonymous_link_id=None,
    )

    assert extract_calls == [0]
    assert upload_calls == ["frame-1.png"]
    assert [part.part_index for part in frame_parts] == [1]
    assert added_image_files == ["vision-1"]


@pytest.mark.asyncio
async def test_build_frame_message_parts_skips_failed_uploads(monkeypatch):
    upload_calls: list[str] = []
    added_image_files: list[str] = []

    async def _fake_extract_frame(_video_url, frame_path, _frame_offset_ms):
        frame_path.write_bytes(b"png")
        return True

    async def _fake_handle_create_file(*_args, upload, **_kwargs):
        upload_calls.append(upload.filename)
        if upload.filename == "frame-1.png":
            raise RuntimeError("temporary upload failure")
        return SimpleNamespace(
            vision_file_id="vision-2",
            file_id="file-2",
            id=102,
        )

    async def _fake_add_image_files(_session, _thread_id, image_file_ids):
        added_image_files.extend(image_file_ids)

    monkeypatch.setattr(
        "pingpong.lecture_video_chat._get_video_input_source",
        AsyncMock(
            return_value=VideoInputSource(
                url="https://video.test/video.mp4?sig=123",
                ffmpeg_input_args=["-method", "GET"],
            )
        ),
    )
    monkeypatch.setattr(
        "pingpong.lecture_video_chat._extract_frame", _fake_extract_frame
    )
    monkeypatch.setattr(
        "pingpong.lecture_video_chat.handle_create_file",
        _fake_handle_create_file,
    )
    monkeypatch.setattr("pingpong.models.Thread.add_image_files", _fake_add_image_files)

    frame_parts = await _build_frame_message_parts(
        session=SimpleNamespace(),
        authz=SimpleNamespace(),
        openai_client=SimpleNamespace(),
        thread_id=1,
        lecture_video=SimpleNamespace(
            id=123,
            stored_object=SimpleNamespace(key="video.mp4"),
        ),
        current_offset_ms=5_000,
        class_id=1,
        uploader_id=1,
        user_auth=None,
        anonymous_link_auth=None,
        anonymous_user_auth=None,
        anonymous_session_id=None,
        anonymous_link_id=None,
    )

    assert upload_calls == ["frame-1.png", "frame-2.png"]
    assert [part.part_index for part in frame_parts] == [2]
    assert [part.input_image_file_id for part in frame_parts] == ["vision-2"]
    assert added_image_files == ["vision-2"]


@pytest.mark.asyncio
async def test_build_frame_message_parts_ignores_attach_failures(monkeypatch):
    async def _fake_extract_frame(_video_url, frame_path, _frame_offset_ms):
        frame_path.write_bytes(b"png")
        return True

    async def _fake_handle_create_file(*_args, **_kwargs):
        return SimpleNamespace(
            vision_file_id="vision-1",
            file_id="file-1",
            id=101,
        )

    async def _fake_add_image_files(*_args, **_kwargs):
        raise RuntimeError("temporary attach failure")

    monkeypatch.setattr(
        "pingpong.lecture_video_chat._get_video_input_source",
        AsyncMock(
            return_value=VideoInputSource(
                url="https://video.test/video.mp4?sig=123",
                ffmpeg_input_args=["-method", "GET"],
            )
        ),
    )
    monkeypatch.setattr(
        "pingpong.lecture_video_chat._extract_frame", _fake_extract_frame
    )
    monkeypatch.setattr(
        "pingpong.lecture_video_chat.handle_create_file",
        _fake_handle_create_file,
    )
    monkeypatch.setattr(
        "pingpong.models.Thread.add_image_files",
        _fake_add_image_files,
    )

    frame_parts = await _build_frame_message_parts(
        session=SimpleNamespace(),
        authz=SimpleNamespace(),
        openai_client=SimpleNamespace(),
        thread_id=1,
        lecture_video=SimpleNamespace(
            id=123,
            stored_object=SimpleNamespace(key="video.mp4"),
        ),
        current_offset_ms=0,
        class_id=1,
        uploader_id=1,
        user_auth=None,
        anonymous_link_auth=None,
        anonymous_user_auth=None,
        anonymous_session_id=None,
        anonymous_link_id=None,
    )

    assert [part.part_index for part in frame_parts] == [1]
    assert [part.input_image_file_id for part in frame_parts] == ["vision-1"]


@pytest.mark.asyncio
async def test_extract_frame_passes_ffmpeg_input_args_before_input(
    monkeypatch, tmp_path
):
    captured_args = None

    class _FakeProcess:
        returncode = 0

        async def communicate(self):
            return b"", b""

        def kill(self):
            pass

    async def fake_create_subprocess_exec(*args, **_kwargs):
        nonlocal captured_args
        captured_args = args
        tmp_path.joinpath("frame.png").write_bytes(b"png")
        return _FakeProcess()

    monkeypatch.setattr(
        "pingpong.lecture_video_chat.asyncio.create_subprocess_exec",
        fake_create_subprocess_exec,
    )

    source = VideoInputSource(
        url="https://example.com/video.mp4?sig=123",
        ffmpeg_input_args=[
            "-method",
            "GET",
            "-seekable",
            "1",
            "-multiple_requests",
            "1",
        ],
    )
    output_path = tmp_path / "frame.png"

    assert await _extract_frame(source, output_path, 5_000) is True
    assert captured_args == (
        "ffmpeg",
        "-loglevel",
        "error",
        "-y",
        "-ss",
        "5.000",
        "-method",
        "GET",
        "-seekable",
        "1",
        "-multiple_requests",
        "1",
        "-i",
        "https://example.com/video.mp4?sig=123",
        "-frames:v",
        "1",
        str(output_path),
    )
