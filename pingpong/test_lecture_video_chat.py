from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

import pingpong.models as models
import pingpong.schemas as schemas
from pingpong.lecture_video_chat import (
    TRANSCRIPT_CONTEXT_WINDOW_MS,
    build_lecture_chat_context_message_parts,
    _build_frame_message_parts,
    _build_context_text,
    _build_context_text_v3,
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


def _build_manifest_v3_dict() -> dict:
    return {
        "word_level_transcription": [
            {
                "id": "w1",
                "word": "Before",
                "start_offset_ms": 0,
                "end_offset_ms": 400,
            },
            {
                "id": "w2",
                "word": "now",
                "start_offset_ms": 4_700,
                "end_offset_ms": 5_000,
            },
            {
                "id": "w3",
                "word": "future",
                "start_offset_ms": 5_100,
                "end_offset_ms": 5_500,
            },
        ],
        "video_descriptions": [
            {
                "start_offset_ms": 4_000,
                "end_offset_ms": 5_500,
                "description": "The slide shows a highlighted formula.",
            }
        ],
        "questions": [
            _build_manifest_question().model_dump(mode="json"),
            schemas.LectureVideoManifestQuestionV1(
                type=schemas.LectureVideoQuestionType.SINGLE_SELECT,
                question_text="What comes next?",
                intro_text="",
                stop_offset_ms=10_000,
                options=[
                    schemas.LectureVideoManifestOptionV1(
                        option_text="A proof",
                        post_answer_text="Correct.",
                        continue_offset_ms=10_500,
                        correct=True,
                    ),
                    schemas.LectureVideoManifestOptionV1(
                        option_text="A joke",
                        post_answer_text="Incorrect.",
                        continue_offset_ms=10_500,
                        correct=False,
                    ),
                ],
            ).model_dump(mode="json"),
        ],
    }


def test_validate_lecture_video_manifest_accepts_omitted_version_v3():
    manifest = schemas.validate_lecture_video_manifest(_build_manifest_v3_dict())

    assert isinstance(manifest, schemas.LectureVideoManifestV3)
    assert manifest.version == 3
    assert manifest.word_level_transcription[0].start_offset_ms == 0
    assert manifest.video_descriptions[0].description == (
        "The slide shows a highlighted formula."
    )


def test_validate_lecture_video_manifest_accepts_explicit_version_v3():
    payload = {"version": 3, **_build_manifest_v3_dict()}

    manifest = schemas.validate_lecture_video_manifest(payload)

    assert isinstance(manifest, schemas.LectureVideoManifestV3)
    assert manifest.version == 3


def test_validate_lecture_video_manifest_infers_versionless_v2_with_partial_v3_word_field():
    payload = {
        "questions": [_build_manifest_question().model_dump(mode="json")],
        "word_level_transcription": [
            {
                "id": "w1",
                "word": "Before",
                "start": 0,
                "end": 400,
                "end_offset_ms": 400,
            }
        ],
    }

    manifest = schemas.validate_lecture_video_manifest(payload)

    assert isinstance(manifest, schemas.LectureVideoManifestV2)
    assert manifest.version == 2


def test_validate_lecture_video_manifest_orders_v3_video_descriptions():
    payload = {
        "version": 3,
        **_build_manifest_v3_dict(),
        "video_descriptions": [
            {
                "start_offset_ms": 8_000,
                "end_offset_ms": 9_000,
                "description": "Later slide.",
            },
            {
                "start_offset_ms": 2_000,
                "end_offset_ms": 3_000,
                "description": "Earlier slide.",
            },
        ],
    }

    manifest = schemas.validate_lecture_video_manifest(payload)

    assert isinstance(manifest, schemas.LectureVideoManifestV3)
    assert [description.description for description in manifest.video_descriptions] == [
        "Earlier slide.",
        "Later slide.",
    ]


@pytest.mark.parametrize(
    "payload_update",
    [
        {
            "word_level_transcription": [
                {
                    "id": "w1",
                    "word": "bad",
                    "start_offset_ms": -1,
                    "end_offset_ms": 100,
                }
            ]
        },
        {
            "word_level_transcription": [
                {
                    "id": "w1",
                    "word": "bad",
                    "start_offset_ms": 200,
                    "end_offset_ms": 100,
                }
            ]
        },
        {
            "video_descriptions": [
                {
                    "start_offset_ms": 300,
                    "end_offset_ms": 200,
                    "description": "Bad range.",
                }
            ]
        },
    ],
)
def test_validate_lecture_video_manifest_rejects_invalid_v3_ranges(payload_update):
    payload = {"version": 3, **_build_manifest_v3_dict(), **payload_update}

    with pytest.raises(ValueError, match="Invalid lecture video manifest"):
        schemas.validate_lecture_video_manifest(payload)


def test_validate_lecture_video_manifest_rejects_empty_v3_video_descriptions():
    payload = {"version": 3, **_build_manifest_v3_dict(), "video_descriptions": []}

    with pytest.raises(ValueError, match="video_descriptions"):
        schemas.validate_lecture_video_manifest(payload)


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


def test_build_context_text_v3_watching_status_and_filters_descriptions():
    thread = SimpleNamespace(lecture_video=SimpleNamespace(questions=[]))
    state = SimpleNamespace(
        last_known_offset_ms=5_000,
        last_chat_context_end_ms=0,
        current_question=None,
        current_question_id=None,
        state=schemas.LectureVideoSessionState.PLAYING,
    )
    manifest = schemas.LectureVideoManifestV3(
        version=3,
        word_level_transcription=[
            schemas.LectureVideoManifestWordV3(
                id="w1",
                word="Current",
                start_offset_ms=4_700,
                end_offset_ms=5_000,
            ),
            schemas.LectureVideoManifestWordV3(
                id="w2",
                word="future",
                start_offset_ms=5_100,
                end_offset_ms=5_500,
            ),
        ],
        video_descriptions=[
            schemas.LectureVideoManifestVideoDescriptionV3(
                start_offset_ms=120_000,
                end_offset_ms=121_000,
                description="A much later slide appears.",
            )
        ],
        questions=[_build_manifest_question()],
    )

    context_text, current_offset_ms = _build_context_text_v3(
        thread,
        state,
        manifest,
        answered_knowledge_checks="None",
    )

    assert current_offset_ms == 5_000
    assert "Status: Watching the lecture video" in context_text
    assert "### Relevant Video Descriptions\n\nNone" in context_text
    assert "A much later slide appears." not in context_text


def test_build_context_text_v3_marks_omitted_transcript_since_last_chat():
    thread = SimpleNamespace(lecture_video=SimpleNamespace(questions=[]))
    state = SimpleNamespace(
        last_known_offset_ms=300_000,
        last_chat_context_end_ms=30_000,
        current_question=None,
        current_question_id=None,
        state=schemas.LectureVideoSessionState.PLAYING,
    )
    manifest = schemas.LectureVideoManifestV3(
        version=3,
        word_level_transcription=[
            schemas.LectureVideoManifestWordV3(
                id="w1",
                word="stale",
                start_offset_ms=40_000,
                end_offset_ms=41_000,
            ),
            schemas.LectureVideoManifestWordV3(
                id="w2",
                word="fresh",
                start_offset_ms=300_000 - TRANSCRIPT_CONTEXT_WINDOW_MS,
                end_offset_ms=300_000 - TRANSCRIPT_CONTEXT_WINDOW_MS + 1_000,
            ),
            schemas.LectureVideoManifestWordV3(
                id="w3",
                word="context",
                start_offset_ms=299_000,
                end_offset_ms=300_000,
            ),
        ],
        video_descriptions=[
            schemas.LectureVideoManifestVideoDescriptionV3(
                start_offset_ms=1_000,
                end_offset_ms=2_000,
                description="The opening title card is visible.",
            )
        ],
        questions=[_build_manifest_question()],
    )

    context_text, current_offset_ms = _build_context_text_v3(
        thread,
        state,
        manifest,
        answered_knowledge_checks="None",
    )

    assert current_offset_ms == 300_000
    assert (
        "### Recent Transcript Since Last Lecture Chat (older transcript omitted)"
        in context_text
    )
    assert "stale" not in context_text
    assert "fresh context" in context_text


@pytest.mark.asyncio
async def test_build_lecture_chat_context_message_parts_v3_markdown_without_images(
    monkeypatch,
):
    manifest = schemas.LectureVideoManifestV3.model_validate(
        {"version": 3, **_build_manifest_v3_dict()}
    )
    option_a = SimpleNamespace(
        id=201,
        position=0,
        option_text="A proof",
        post_answer_text="Correct.",
        continue_offset_ms=10_500,
    )
    option_b = SimpleNamespace(
        id=202,
        position=1,
        option_text="A joke",
        post_answer_text="Incorrect.",
        continue_offset_ms=10_500,
    )
    answered_option = SimpleNamespace(
        id=101,
        position=0,
        option_text="Latency",
        post_answer_text="Correct.",
        continue_offset_ms=1_000_000,
    )
    unanswered_option = SimpleNamespace(
        id=102,
        position=1,
        option_text="Color",
        post_answer_text="Incorrect.",
        continue_offset_ms=1_000_000,
    )
    first_question = SimpleNamespace(
        id=10,
        position=0,
        question_type=schemas.LectureVideoQuestionType.SINGLE_SELECT,
        question_text="What matters here?",
        intro_text="",
        options=[answered_option, unanswered_option],
        correct_option=answered_option,
        stop_offset_ms=4_000,
    )
    next_question = SimpleNamespace(
        id=20,
        position=1,
        question_type=schemas.LectureVideoQuestionType.SINGLE_SELECT,
        question_text="What comes next?",
        intro_text="",
        options=[option_a, option_b],
        correct_option=option_a,
        stop_offset_ms=10_000,
    )
    state = SimpleNamespace(
        last_known_offset_ms=5_000,
        last_chat_context_end_ms=0,
        current_question=first_question,
        current_question_id=first_question.id,
        state=schemas.LectureVideoSessionState.AWAITING_POST_ANSWER_RESUME,
    )
    thread = SimpleNamespace(
        id=123,
        lecture_video=SimpleNamespace(
            id=456,
            manifest_data=manifest.model_dump(mode="json"),
            questions=[first_question, next_question],
        ),
        lecture_video_state=state,
    )
    interaction = SimpleNamespace(
        event_type=schemas.LectureVideoInteractionEventType.ANSWER_SUBMITTED,
        question=first_question,
        option=answered_option,
    )

    async def fake_list_question_history_by_thread_id(cls, session, thread_id):
        return [interaction]

    async def fail_build_frame_message_parts(*_args, **_kwargs):
        raise AssertionError("V3 chat context must not build frame message parts")

    monkeypatch.setattr(
        models.LectureVideoInteraction,
        "list_question_history_by_thread_id",
        classmethod(fake_list_question_history_by_thread_id),
    )
    monkeypatch.setattr(
        "pingpong.lecture_video_chat._build_frame_message_parts",
        fail_build_frame_message_parts,
    )

    result = await build_lecture_chat_context_message_parts(
        SimpleNamespace(),
        SimpleNamespace(),
        SimpleNamespace(),
        thread=thread,
        class_id=1,
        uploader_id=1,
        user_auth=None,
        anonymous_link_auth=None,
        anonymous_user_auth=None,
        anonymous_session_id=None,
        anonymous_link_id=None,
    )

    assert result.frame_message_parts == []
    assert len(result.text_message_parts) == 1
    context_text = result.text_message_parts[0].text
    assert context_text.startswith("## Lecture Context")
    assert "Status: Just answered Knowledge Check #1" in context_text
    assert "Current offset: 5000ms" in context_text
    assert "### Recent Transcript" in context_text
    assert "Before now" in context_text
    assert "### Lookahead Transcript" in context_text
    assert "future" in context_text
    assert "### Relevant Video Descriptions" in context_text
    assert "- 4000-5500ms: The slide shows a highlighted formula." in context_text
    assert "At 10000ms, the learner will be asked:" in context_text
    assert "Options:\n- A proof\n- A joke" in context_text
    assert "- Knowledge Check #1: What matters here?" in context_text
    assert "Selected `Latency`; correct. Feedback: Correct." in context_text


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
