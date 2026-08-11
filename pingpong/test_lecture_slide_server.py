import importlib
import io
from types import SimpleNamespace

import humanize
import pytest
from fastapi import HTTPException, UploadFile
from pypdf import PdfWriter
from sqlalchemy import func, select

import pingpong.schemas as schemas
from pingpong import lecture_slide_processing, lecture_slide_service, models
from pingpong.models import file_class_association
from pingpong.config import LocalAudioStoreSettings
from pingpong.lecture_video_service import get_upload_size

from .testutil import with_authz, with_institution, with_user


class FakeLectureSlideStore:
    def __init__(self):
        self.stored_files: dict[str, bytes] = {}
        self.deleted_keys: list[str] = []

    async def put(self, key: str, file, content_type: str):
        self.stored_files[key] = file.read()

    async def delete(self, key: str):
        self.deleted_keys.append(key)


class FakeLectureSlideAudioStore:
    def __init__(self):
        self.deleted_keys: list[str] = []

    async def delete_file(self, key: str):
        self.deleted_keys.append(key)


class FakeOpenAIFiles:
    def __init__(self):
        self.created_files = []
        self.deleted_file_ids: list[str] = []

    async def create(self, *, file, purpose: str):
        self.created_files.append((file, purpose))
        return SimpleNamespace(id=f"file-{len(self.created_files)}")

    async def delete(self, file_id: str):
        self.deleted_file_ids.append(file_id)


def _one_page_pdf_upload(filename: str = "slides.pdf") -> tuple[UploadFile, bytes]:
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    pdf = io.BytesIO()
    writer.write(pdf)
    pdf_bytes = pdf.getvalue()
    return (
        UploadFile(file=io.BytesIO(pdf_bytes), filename=filename, size=len(pdf_bytes)),
        pdf_bytes,
    )


def _text_upload(
    filename: str = "notes.md",
    content: bytes = b"# Instructor notes",
    content_type: str = "text/markdown",
) -> UploadFile:
    return UploadFile(
        file=io.BytesIO(content),
        filename=filename,
        size=len(content),
        headers={"content-type": content_type},
    )


def _context_file_input(
    file_id: str = "file-context-1",
    filename: str = "notes.md",
    file_kind: str = schemas.LECTURE_SLIDE_CONTEXT_FILE_KIND_OTHER,
    usage_mode: str = schemas.LECTURE_SLIDE_CONTEXT_FILE_USAGE_GUIDE,
    usage_note: str | None = None,
) -> lecture_slide_processing.AdditionalContextFileInput:
    return lecture_slide_processing.AdditionalContextFileInput(
        file_id=file_id,
        filename=filename,
        file_kind=file_kind,
        usage_mode=usage_mode,
        usage_note=usage_note,
    )


def test_additional_context_generation_payload_is_separate_user_message():
    messages = lecture_slide_processing._append_additional_context_message(
        [
            {
                "role": "user",
                "content": [
                    {"type": "input_file", "file_id": "file-slides"},
                    {"type": "input_text", "text": "Generate narration."},
                ],
            }
        ],
        [
            _context_file_input(
                file_id="file-context-1",
                filename="transcript.txt",
                file_kind=schemas.LECTURE_SLIDE_CONTEXT_FILE_KIND_TRANSCRIPT,
                usage_mode=schemas.LECTURE_SLIDE_CONTEXT_FILE_USAGE_GUIDE,
            ),
            _context_file_input(file_id="file-context-2", filename="notes.md"),
        ],
    )

    assert len(messages) == 2
    assert messages[0]["content"][0] == {
        "type": "input_file",
        "file_id": "file-slides",
    }
    assert messages[1]["role"] == "user"
    preamble, *parts = messages[1]["content"]
    assert preamble["type"] == "input_text"
    assert "additional context" in preamble["text"]
    assert [part["type"] for part in parts] == [
        "input_text",
        "input_file",
        "input_text",
        "input_file",
    ]
    first_label, first_file, second_label, second_file = parts
    assert "[Additional context file 1 of 2]" in first_label["text"]
    assert "Filename: transcript.txt" in first_label["text"]
    assert "Kind: transcript" in first_label["text"]
    assert "Usage mode: guide" in first_label["text"]
    assert first_file == {"type": "input_file", "file_id": "file-context-1"}
    assert "[Additional context file 2 of 2]" in second_label["text"]
    assert "Filename: notes.md" in second_label["text"]
    assert "Kind: other" in second_label["text"]
    assert second_file == {"type": "input_file", "file_id": "file-context-2"}


def test_additional_context_user_message_empty_returns_none():
    assert lecture_slide_processing._additional_context_user_message([]) is None
    assert lecture_slide_processing._append_additional_context_message(
        [{"role": "user", "content": []}], []
    ) == [{"role": "user", "content": []}]


def test_additional_context_user_message_faithful_transcript():
    message = lecture_slide_processing._additional_context_user_message(
        [
            _context_file_input(
                filename="transcript.txt",
                file_kind=schemas.LECTURE_SLIDE_CONTEXT_FILE_KIND_TRANSCRIPT,
                usage_mode=schemas.LECTURE_SLIDE_CONTEXT_FILE_USAGE_FAITHFUL,
            )
        ]
    )

    assert message is not None
    preamble = message["content"][0]["text"]
    assert "marked FAITHFUL" in preamble
    label = message["content"][1]["text"]
    assert "marked FAITHFUL" in label
    assert "reproduce this transcript essentially verbatim" in label
    assert "Instructor instructions:" not in label


def test_additional_context_user_message_guide_transcript():
    message = lecture_slide_processing._additional_context_user_message(
        [
            _context_file_input(
                filename="transcript.txt",
                file_kind=schemas.LECTURE_SLIDE_CONTEXT_FILE_KIND_TRANSCRIPT,
                usage_mode=schemas.LECTURE_SLIDE_CONTEXT_FILE_USAGE_GUIDE,
            )
        ]
    )

    assert message is not None
    preamble = message["content"][0]["text"]
    assert "marked FAITHFUL" not in preamble
    label = message["content"][1]["text"]
    assert "marked GUIDE" in label
    assert "guide content, emphasis, and pacing" in label


def test_additional_context_user_message_transcript_includes_instructions():
    message = lecture_slide_processing._additional_context_user_message(
        [
            _context_file_input(
                filename="transcript.txt",
                file_kind=schemas.LECTURE_SLIDE_CONTEXT_FILE_KIND_TRANSCRIPT,
                usage_mode=schemas.LECTURE_SLIDE_CONTEXT_FILE_USAGE_GUIDE,
                usage_note="Only use the introduction section.",
            )
        ]
    )

    assert message is not None
    label = message["content"][1]["text"]
    assert "Usage mode: guide" in label
    assert "Instructor instructions: Only use the introduction section." in label


def test_additional_context_user_message_other_file_without_note():
    message = lecture_slide_processing._additional_context_user_message(
        [_context_file_input(filename="syllabus.pdf")]
    )

    assert message is not None
    preamble = message["content"][0]["text"]
    assert "marked FAITHFUL" not in preamble
    label = message["content"][1]["text"]
    assert "Instructor instructions:" not in label
    assert "background context" in label


def test_context_file_metadata_must_describe_submitted_files():
    """Tags for files the save does not attach would be silently dropped."""
    schemas.UpdateAssistant(
        lecture_slide_deck_id=1,
        voice_id="voice-1",
        lecture_slide_additional_context_file_ids=[1, 2],
        lecture_slide_additional_context_file_metadata=[
            schemas.LectureSlideAdditionalContextFileMetadataInput(id=2)
        ],
    )

    with pytest.raises(ValueError):
        schemas.UpdateAssistant(
            lecture_slide_deck_id=1,
            voice_id="voice-1",
            lecture_slide_additional_context_file_ids=[1],
            lecture_slide_additional_context_file_metadata=[
                schemas.LectureSlideAdditionalContextFileMetadataInput(id=3)
            ],
        )

    with pytest.raises(ValueError):
        schemas.UpdateAssistant(
            lecture_slide_deck_id=1,
            voice_id="voice-1",
            lecture_slide_additional_context_file_metadata=[
                schemas.LectureSlideAdditionalContextFileMetadataInput(id=1)
            ],
        )


def test_additional_context_user_message_other_file_omits_usage_mode():
    """Usage modes describe how to follow a transcript, so they are dropped."""
    message = lecture_slide_processing._additional_context_user_message(
        [
            _context_file_input(
                filename="syllabus.pdf",
                usage_mode=schemas.LECTURE_SLIDE_CONTEXT_FILE_USAGE_FAITHFUL,
                usage_note="Use this for the grading policy only.",
            )
        ]
    )

    assert message is not None
    label = message["content"][1]["text"]
    assert "Kind: other" in label
    assert "Usage mode:" not in label
    assert "Instructor instructions: Use this for the grading policy only." in label


def test_has_faithful_transcript():
    faithful = _context_file_input(
        file_kind=schemas.LECTURE_SLIDE_CONTEXT_FILE_KIND_TRANSCRIPT,
        usage_mode=schemas.LECTURE_SLIDE_CONTEXT_FILE_USAGE_FAITHFUL,
    )
    guide = _context_file_input(
        file_kind=schemas.LECTURE_SLIDE_CONTEXT_FILE_KIND_TRANSCRIPT,
        usage_mode=schemas.LECTURE_SLIDE_CONTEXT_FILE_USAGE_GUIDE,
    )
    other = _context_file_input()
    faithful_other = _context_file_input(
        usage_mode=schemas.LECTURE_SLIDE_CONTEXT_FILE_USAGE_FAITHFUL
    )
    unknown = _context_file_input(file_kind="summary", usage_mode="faithful-ish")

    assert lecture_slide_processing._has_faithful_transcript([]) is False
    assert lecture_slide_processing._has_faithful_transcript([faithful]) is True
    assert lecture_slide_processing._has_faithful_transcript([guide, other]) is False
    assert lecture_slide_processing._has_faithful_transcript([guide, faithful]) is True
    assert lecture_slide_processing._has_faithful_transcript([faithful_other]) is False
    assert lecture_slide_processing._has_faithful_transcript([unknown]) is False


@pytest.mark.asyncio
@with_user(123)
@with_institution(11, "Test Institution")
@with_authz(
    grants=[
        ("user:123", "can_create_thread", "class:1"),
        ("user:123", "student", "class:1"),
    ]
)
async def test_translated_thread_requires_ready_variant_and_saves_language(
    api, db, institution, valid_user_token
):
    async with db.async_session() as session:
        class_ = models.Class(
            id=1,
            name="Test Class",
            institution_id=institution.id,
            api_key="test-key",
        )
        source = models.LectureSlideSourceStoredObject(
            key="translated-slides.pdf",
            original_filename="translated-slides.pdf",
            content_type="application/pdf",
            content_length=128,
        )
        deck = models.LectureSlideDeck(
            id=1,
            class_=class_,
            source_stored_object=source,
            display_name="Translated slides",
            status=schemas.LectureSlideDeckStatus.READY,
            slide_count=1,
            total_duration_ms=1_000,
        )
        assistant = models.Assistant(
            id=1,
            name="Translated Slides",
            class_=class_,
            interaction_mode=schemas.InteractionMode.LECTURE_SLIDES,
            version=3,
            lecture_slide_deck=deck,
            instructions="Teach from the slides.",
            model="gpt-4o-mini",
            tools="[]",
            use_latex=False,
            use_image_descriptions=False,
            hide_prompt=False,
        )
        page = models.LectureSlidePage(
            lecture_slide_deck=deck,
            position=0,
            content_kind=schemas.LectureSlideContentKind.SLIDE,
            narration_text="Source narration.",
            start_offset_ms=0,
            end_offset_ms=1_000,
        )
        translation = models.LectureSlideTranslation(
            lecture_slide_deck=deck,
            language_code="es",
            language_name="Spanish",
            openai_model="gpt-4o-mini",
            status=schemas.LectureSlideTranslationStatus.PROCESSING,
            stage=schemas.LectureSlideTranslationStage.NARRATION_AUDIO,
        )
        session.add_all([class_, source, deck, assistant, page, translation])
        await session.commit()
        translation_id = translation.id

    languages = api.get(
        "/api/v1/class/1/assistant/1/lecture-slides/languages",
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )
    assert languages.status_code == 200
    assert languages.json()["can_prepare"] is False
    unsupported_status = api.get(
        "/api/v1/class/1/assistant/1/lecture-slides/translations/not-a-language",
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )
    assert unsupported_status.status_code == 422
    forbidden_prepare = api.post(
        "/api/v1/class/1/assistant/1/lecture-slides/translations",
        json={"language_code": "es"},
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )
    assert forbidden_prepare.status_code == 403

    unavailable = api.post(
        "/api/v1/class/1/thread/lecture",
        json={"assistant_id": 1, "parties": [123], "language_code": "es"},
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )
    assert unavailable.status_code == 409

    async with db.async_session() as session:
        translation = await session.get(models.LectureSlideTranslation, translation_id)
        assert translation is not None
        audio = models.LectureSlideNarrationStoredObject(
            key="translated.webm",
            content_type="audio/webm",
            content_length=100,
            duration_ms=1_200,
        )
        caption = models.LectureSlideCaptionStoredObject(
            key="translated.vtt",
            content_type="text/vtt",
            content_length=50,
        )
        session.add_all([audio, caption])
        await session.flush()
        translation.status = schemas.LectureSlideTranslationStatus.READY
        translation.continuous_narration_stored_object_id = audio.id
        translation.caption_stored_object_id = caption.id
        translation.total_duration_ms = 1_200
        session.add(
            models.LectureSlideTranslationPage(
                translation=translation,
                position=0,
                narration_text="Narración.",
                start_offset_ms=0,
                end_offset_ms=1_200,
            )
        )
        await session.commit()

    ready = api.post(
        "/api/v1/class/1/thread/lecture",
        json={"assistant_id": 1, "parties": [123], "language_code": "es"},
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )

    assert ready.status_code == 200
    assert ready.json()["thread"]["lecture_language_code"] == "es"
    assert ready.json()["thread"]["lecture_language_name"] == "Spanish"
    thread_id = ready.json()["thread"]["id"]
    async with db.async_session() as session:
        thread = await session.get(models.Thread, thread_id)
        assert thread is not None
        assert thread.lecture_slide_translation_id == translation_id


@pytest.mark.asyncio
@with_user(123)
@with_institution(11, "Test Institution")
@with_authz(
    grants=[
        ("user:123", "can_create_thread", "class:1"),
        ("user:123", "can_edit", "assistant:1"),
    ]
)
async def test_lecture_slide_editor_can_prepare_translation(
    api, db, institution, valid_user_token
):
    async with db.async_session() as session:
        class_ = models.Class(
            id=1,
            name="Test Class",
            institution_id=institution.id,
            api_key="test-key",
        )
        source = models.LectureSlideSourceStoredObject(
            key="slides.pdf",
            original_filename="slides.pdf",
            content_type="application/pdf",
            content_length=128,
        )
        deck = models.LectureSlideDeck(
            id=1,
            class_=class_,
            source_stored_object=source,
            display_name="Slides",
            status=schemas.LectureSlideDeckStatus.READY,
            slide_count=1,
        )
        assistant = models.Assistant(
            id=1,
            name="Slides",
            class_=class_,
            interaction_mode=schemas.InteractionMode.LECTURE_SLIDES,
            lecture_slide_deck=deck,
            model="gpt-4o-mini",
        )
        session.add_all([class_, source, deck, assistant])
        await session.commit()

    languages = api.get(
        "/api/v1/class/1/assistant/1/lecture-slides/languages",
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )
    assert languages.status_code == 200
    assert languages.json()["can_prepare"] is True

    prepared = api.post(
        "/api/v1/class/1/assistant/1/lecture-slides/translations",
        json={"language_code": "es"},
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )
    assert prepared.status_code == 200
    assert prepared.json()["status"] == "queued"


@pytest.mark.parametrize(
    ("content_type", "format_names", "video_codec"),
    [
        ("image/png", frozenset({"png_pipe"}), "png"),
        ("image/jpeg", frozenset({"jpeg_pipe"}), "mjpeg"),
        ("image/webp", frozenset({"webp_pipe"}), "webp"),
        ("image/gif", frozenset({"gif"}), "gif"),
        ("video/mp4", frozenset({"mov", "mp4"}), "h264"),
        ("video/webm", frozenset({"matroska", "webm"}), "vp9"),
    ],
)
def test_media_probe_accepts_expected_contents(content_type, format_names, video_codec):
    probe = lecture_slide_service.LectureSlideMediaProbe(
        width_px=1280,
        height_px=720,
        duration_ms=5000,
        has_audio=content_type.startswith("video/"),
        format_names=format_names,
        video_codec=video_codec,
    )

    lecture_slide_service._validate_probed_media_type(content_type, probe)


def test_media_probe_rejects_mime_type_that_does_not_match_contents():
    mp4_probe = lecture_slide_service.LectureSlideMediaProbe(
        width_px=1280,
        height_px=720,
        duration_ms=5000,
        has_audio=True,
        format_names=frozenset({"mov", "mp4"}),
        video_codec="h264",
    )

    with pytest.raises(HTTPException, match="declared file type"):
        lecture_slide_service._validate_probed_media_type("image/png", mp4_probe)


def test_media_probe_reports_missing_ffprobe(monkeypatch):
    monkeypatch.setattr(lecture_slide_service.shutil, "which", lambda _name: None)

    with pytest.raises(HTTPException) as exc_info:
        lecture_slide_service._probe_media_file("ignored.png")

    assert exc_info.value.status_code == 503
    assert "ffprobe is not configured" in str(exc_info.value.detail)


@pytest.mark.asyncio
async def test_visual_media_upload_has_openai_safe_size_cap(db, config, monkeypatch):
    monkeypatch.setattr(
        config,
        "video_store",
        SimpleNamespace(store=FakeLectureSlideStore()),
    )
    upload = UploadFile(
        file=io.BytesIO(),
        filename="too-large.png",
        size=lecture_slide_service.LECTURE_SLIDE_VISUAL_MEDIA_MAX_BYTES + 1,
        headers={"content-type": "image/png"},
    )

    async with db.async_session() as session:
        with pytest.raises(HTTPException) as exc_info:
            await lecture_slide_service.create_lecture_slide_media_upload(
                session,
                class_id=1,
                uploader_id=123,
                upload=upload,
            )

    assert exc_info.value.status_code == 413
    assert humanize.naturalsize(
        lecture_slide_service.LECTURE_SLIDE_VISUAL_MEDIA_MAX_BYTES
    ) in str(exc_info.value.detail)


@pytest.mark.asyncio
@with_institution(11, "Test Institution")
async def test_create_lecture_slide_deck_uploads_source_pdf_to_openai(
    db, config, monkeypatch, institution
):
    store = FakeLectureSlideStore()
    files = FakeOpenAIFiles()
    monkeypatch.setattr(config, "video_store", SimpleNamespace(store=store))
    monkeypatch.setattr(
        lecture_slide_service,
        "generate_source_store_key",
        lambda: "ls_source_test.pdf",
    )

    async def fake_get_openai_client_by_class_id(session, class_id: int):
        assert class_id == 1
        return SimpleNamespace(files=files)

    monkeypatch.setattr(
        lecture_slide_service,
        "get_openai_client_by_class_id",
        fake_get_openai_client_by_class_id,
    )
    upload, pdf_bytes = _one_page_pdf_upload()

    async with db.async_session() as session:
        user = models.User(id=123, email="owner@example.com")
        class_ = models.Class(
            id=1,
            name="Test Class",
            institution_id=institution.id,
            api_key="test-key",
        )
        session.add_all([user, class_])
        await session.flush()

        deck = await lecture_slide_service.create_lecture_slide_deck(
            session,
            class_id=class_.id,
            uploader_id=user.id,
            upload=upload,
        )
        assert deck.source_page_count == 1
        await session.commit()
        source_id = deck.source_stored_object_id

    assert store.stored_files == {"ls_source_test.pdf": pdf_bytes}
    assert files.created_files == [
        (("slides.pdf", pdf_bytes, "application/pdf"), "user_data")
    ]
    assert files.deleted_file_ids == []

    async with db.async_session() as session:
        source = await session.get(models.LectureSlideSourceStoredObject, source_id)
        assert source is not None
        assert source.openai_file_object_id is not None
        file = await session.get(models.File, source.openai_file_object_id)
        assert file is not None
        assert file.file_id == "file-1"
        assert file.name == "slides.pdf"
        assert file.content_type == "application/pdf"
        assert file.private is True
        assert file.uploader_id == 123
        class_ids = (
            await session.execute(
                file_class_association.select().where(
                    file_class_association.c.file_id == file.id
                )
            )
        ).mappings()
        assert [row["class_id"] for row in class_ids] == [1]


@pytest.mark.asyncio
@with_institution(11, "Test Institution")
async def test_create_lecture_slide_additional_context_file_uploads_as_user_data(
    db, config, monkeypatch, institution
):
    store = FakeLectureSlideStore()
    files = FakeOpenAIFiles()
    monkeypatch.setattr(config, "file_store", SimpleNamespace(store=store))

    async def fake_get_openai_client_by_class_id(session, class_id: int):
        assert class_id == 1
        return SimpleNamespace(files=files)

    monkeypatch.setattr(
        lecture_slide_service,
        "get_openai_client_by_class_id",
        fake_get_openai_client_by_class_id,
    )
    upload = _text_upload()

    async with db.async_session() as session:
        user = models.User(id=123, email="owner@example.com")
        class_ = models.Class(
            id=1,
            name="Test Class",
            institution_id=institution.id,
            api_key="test-key",
        )
        session.add_all([user, class_])
        await session.flush()

        context_file = (
            await lecture_slide_service.create_lecture_slide_additional_context_file(
                session,
                class_id=class_.id,
                uploader_id=user.id,
                upload=upload,
            )
        )
        await session.commit()
        context_file_id = context_file.id

    uploaded_file, purpose = files.created_files[0]
    assert uploaded_file[0] == "notes.md"
    assert uploaded_file[1] == b"# Instructor notes"
    assert uploaded_file[2] == "text/markdown"
    assert purpose == "user_data"
    assert list(store.stored_files.values()) == [b"# Instructor notes"]

    async with db.async_session() as session:
        context_file = await session.get(
            models.LectureSlideAdditionalContextFile, context_file_id
        )
        assert context_file is not None
        assert context_file.lecture_slide_deck_id is None
        assert context_file.original_filename == "notes.md"
        assert context_file.content_length == len(b"# Instructor notes")
        file = await session.get(models.File, context_file.file_object_id)
        assert file is not None
        assert file.file_id == "file-1"
        assert file.private is True
        assert file.s3_file_id is not None
        s3_file = await session.get(models.S3File, file.s3_file_id)
        assert s3_file is not None
        assert s3_file.key in store.stored_files


@pytest.mark.asyncio
@with_institution(11, "Test Institution")
async def test_create_lecture_slide_additional_context_file_stages_default_tags(
    db, config, monkeypatch, institution
):
    store = FakeLectureSlideStore()
    files = FakeOpenAIFiles()
    monkeypatch.setattr(config, "file_store", SimpleNamespace(store=store))

    async def fake_get_openai_client_by_class_id(session, class_id: int):
        return SimpleNamespace(files=files)

    monkeypatch.setattr(
        lecture_slide_service,
        "get_openai_client_by_class_id",
        fake_get_openai_client_by_class_id,
    )

    async with db.async_session() as session:
        user = models.User(id=123, email="owner@example.com")
        class_ = models.Class(
            id=1,
            name="Test Class",
            institution_id=institution.id,
            api_key="test-key",
        )
        session.add_all([user, class_])
        await session.flush()

        staged = (
            await lecture_slide_service.create_lecture_slide_additional_context_file(
                session,
                class_id=class_.id,
                uploader_id=user.id,
                upload=_text_upload(filename="transcript.txt"),
            )
        )

    # Uploading only stages the file; it is tagged when the assistant is saved.
    assert staged.file_kind == schemas.LECTURE_SLIDE_CONTEXT_FILE_KIND_OTHER
    assert staged.usage_mode == schemas.LECTURE_SLIDE_CONTEXT_FILE_USAGE_GUIDE
    assert staged.usage_note is None

    summary = lecture_slide_service.lecture_slide_context_file_summary_from_model(
        staged
    )
    assert summary.file_kind == schemas.LECTURE_SLIDE_CONTEXT_FILE_KIND_OTHER
    assert summary.usage_mode == schemas.LECTURE_SLIDE_CONTEXT_FILE_USAGE_GUIDE
    assert summary.usage_note is None


def test_lecture_slide_additional_context_file_validation_uses_mime_type():
    accepted_mime_with_unknown_extension = _text_upload(
        filename="notes.unknown",
        content_type="text/markdown",
    )
    lecture_slide_service._validate_openai_input_file_upload(
        accepted_mime_with_unknown_extension,
        get_upload_size(accepted_mime_with_unknown_extension),
    )

    unsupported_mime_with_accepted_extension = _text_upload(
        filename="notes.md",
        content_type="application/octet-stream",
    )
    with pytest.raises(HTTPException) as exc_info:
        lecture_slide_service._validate_openai_input_file_upload(
            unsupported_mime_with_accepted_extension,
            get_upload_size(unsupported_mime_with_accepted_extension),
        )
    assert exc_info.value.status_code == 400


@pytest.mark.asyncio
@with_user(123)
@with_institution(11, "Test Institution")
@with_authz(grants=[("user:123", "can_view", "class:1")])
async def test_class_upload_info_marks_openai_input_file_mime_types(
    api, db, institution, valid_user_token, config
):
    async with db.async_session() as session:
        session.add(
            models.Class(
                id=1,
                name="Test Class",
                institution_id=institution.id,
                api_key="test-key",
            )
        )
        await session.commit()

    response = api.get(
        "/api/v1/class/1/upload_info",
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )

    assert response.status_code == 200
    assert (
        response.json()["assistant_avatar_max_size"]
        == config.upload.assistant_avatar_max_size
    )
    types_by_mime = {
        file_type["mime_type"]: file_type for file_type in response.json()["types"]
    }
    assert types_by_mime["application/pdf"]["file_search"] is True
    assert types_by_mime["application/pdf"]["input_file"] is True
    assert types_by_mime["text/x-yaml"]["input_file"] is True
    assert types_by_mime["text/css"]["file_search"] is True
    assert types_by_mime["text/javascript"]["file_search"] is True
    assert types_by_mime["application/typescript"]["file_search"] is True
    assert types_by_mime["application/msword"]["file_search"] is True
    assert types_by_mime["application/msword"]["code_interpreter"] is True
    assert types_by_mime["text/x-csharp"]["file_search"] is True
    assert types_by_mime["text/x-csharp"]["code_interpreter"] is True
    assert types_by_mime["text/x-golang"]["file_search"] is True
    assert types_by_mime["text/x-php"]["file_search"] is True
    assert types_by_mime["text/x-php"]["code_interpreter"] is True
    assert types_by_mime["application/csv"]["code_interpreter"] is True
    assert types_by_mime["application/x-sh"]["file_search"] is True
    assert types_by_mime["application/x-sh"]["code_interpreter"] is True
    assert types_by_mime["application/octet-stream"]["code_interpreter"] is True
    assert types_by_mime["image/webp"]["vision"] is True


@pytest.mark.asyncio
@with_institution(11, "Test Institution")
async def test_apply_additional_context_files_attaches_to_deck_and_validates_size(
    db, institution
):
    async with db.async_session() as session:
        user = models.User(id=123, email="owner@example.com")
        class_ = models.Class(
            id=1,
            name="Test Class",
            institution_id=institution.id,
            api_key="test-key",
        )
        session.add_all([user, class_])
        await session.flush()
        file = await models.File.create(
            session,
            {
                "file_id": "file-context",
                "private": True,
                "uploader_id": user.id,
                "name": "notes.md",
                "content_type": "text/markdown",
            },
            class_id=1,
        )
        source = await models.LectureSlideSourceStoredObject.create(
            session,
            key="slides.pdf",
            original_filename="slides.pdf",
            content_type="application/pdf",
            content_length=1024,
        )
        deck = await models.LectureSlideDeck.create(
            session,
            class_id=class_.id,
            source_stored_object_id=source.id,
            uploader_id=user.id,
            display_name="slides.pdf",
            slide_count=1,
        )
        draft_context = await models.LectureSlideAdditionalContextFile.create(
            session,
            lecture_slide_deck_id=None,
            file_object_id=file.id,
            class_id=class_.id,
            uploader_id=user.id,
            position=0,
            original_filename="notes.md",
            content_type="text/markdown",
            content_length=2048,
        )

        changed = (
            await lecture_slide_service.apply_lecture_slide_additional_context_files(
                session,
                deck,
                [draft_context.id],
                uploader_id=user.id,
            )
        )
        oversized_file = await models.File.create(
            session,
            {
                "file_id": "file-oversized-context",
                "private": True,
                "uploader_id": user.id,
                "name": "large-notes.md",
                "content_type": "text/markdown",
            },
            class_id=1,
        )
        oversized_context = await models.LectureSlideAdditionalContextFile.create(
            session,
            lecture_slide_deck_id=None,
            file_object_id=oversized_file.id,
            class_id=class_.id,
            uploader_id=user.id,
            position=1,
            original_filename="large-notes.md",
            content_type="text/markdown",
            content_length=lecture_slide_service.OPENAI_INPUT_FILE_MAX_BYTES,
        )
        with pytest.raises(HTTPException) as exc_info:
            await lecture_slide_service.apply_lecture_slide_additional_context_files(
                session,
                deck,
                [draft_context.id, oversized_context.id],
                uploader_id=user.id,
            )
        assert exc_info.value.status_code == 413
        await session.commit()
        deck_id = deck.id
        draft_context_id = draft_context.id

    assert changed is True
    async with db.async_session() as session:
        attached_files = (
            await models.LectureSlideAdditionalContextFile.get_all_by_deck_id_with_file(
                session, deck_id
            )
        )
        assert len(attached_files) == 1
        assert attached_files[0].id == draft_context_id
        assert attached_files[0].original_filename == "notes.md"
        assert attached_files[0].lecture_slide_deck_id == deck_id


@pytest.mark.asyncio
@with_institution(11, "Test Institution")
async def test_assistant_file_usage_counts_lecture_slide_context_files(db, institution):
    async with db.async_session() as session:
        user = models.User(id=123, email="owner@example.com")
        class_ = models.Class(
            id=1,
            name="Test Class",
            institution_id=institution.id,
            api_key="test-key",
        )
        session.add_all([user, class_])
        await session.flush()
        file = await models.File.create(
            session,
            {
                "file_id": "file-context",
                "private": True,
                "uploader_id": user.id,
                "name": "notes.md",
                "content_type": "text/markdown",
            },
            class_id=class_.id,
        )
        source = await models.LectureSlideSourceStoredObject.create(
            session,
            key="slides.pdf",
            original_filename="slides.pdf",
            content_type="application/pdf",
            content_length=1024,
        )
        deck = await models.LectureSlideDeck.create(
            session,
            class_id=class_.id,
            source_stored_object_id=source.id,
            uploader_id=user.id,
            display_name="slides.pdf",
            slide_count=1,
        )
        await models.LectureSlideAdditionalContextFile.create(
            session,
            lecture_slide_deck_id=deck.id,
            file_object_id=file.id,
            class_id=class_.id,
            uploader_id=user.id,
            position=0,
            original_filename="notes.md",
            content_type="text/markdown",
            content_length=2048,
        )
        session.add(
            models.Assistant(
                id=1,
                name="Lecture Slides Assistant",
                class_id=class_.id,
                creator_id=user.id,
                interaction_mode=schemas.InteractionMode.LECTURE_SLIDES,
                version=3,
                model="gpt-4o-mini",
                instructions="Teach the lecture.",
                tools="[]",
                lecture_slide_deck_id=deck.id,
            )
        )
        await session.flush()

        usage_rows = await models.File.assistant_count_using_files(
            session, [file.id], class_.id
        )
        usage_count = await models.File.assistant_count_using_file(
            session, file.id, class_.id
        )

    assert dict(usage_rows) == {file.id: 1}
    assert usage_count == 1


@pytest.mark.asyncio
@with_institution(11, "Test Institution")
async def test_apply_additional_context_files_preserves_existing_files_for_other_editor(
    db, institution
):
    async with db.async_session() as session:
        owner = models.User(id=123, email="owner@example.com")
        editor = models.User(id=456, email="editor@example.com")
        class_ = models.Class(
            id=1,
            name="Test Class",
            institution_id=institution.id,
            api_key="test-key",
        )
        session.add_all([owner, editor, class_])
        await session.flush()
        file = await models.File.create(
            session,
            {
                "file_id": "file-context",
                "private": True,
                "uploader_id": owner.id,
                "name": "notes.md",
                "content_type": "text/markdown",
            },
            class_id=class_.id,
        )
        source = await models.LectureSlideSourceStoredObject.create(
            session,
            key="slides.pdf",
            original_filename="slides.pdf",
            content_type="application/pdf",
            content_length=1024,
        )
        deck = await models.LectureSlideDeck.create(
            session,
            class_id=class_.id,
            source_stored_object_id=source.id,
            uploader_id=owner.id,
            display_name="slides.pdf",
            slide_count=1,
        )
        context_file = await models.LectureSlideAdditionalContextFile.create(
            session,
            lecture_slide_deck_id=deck.id,
            file_object_id=file.id,
            class_id=class_.id,
            uploader_id=owner.id,
            position=0,
            original_filename="notes.md",
            content_type="text/markdown",
            content_length=2048,
        )

        changed = (
            await lecture_slide_service.apply_lecture_slide_additional_context_files(
                session,
                deck,
                [context_file.id],
                uploader_id=editor.id,
            )
        )

    assert changed is False


@pytest.mark.asyncio
@with_institution(11, "Test Institution")
async def test_apply_additional_context_files_tags_files_on_save(db, institution):
    async with db.async_session() as session:
        user = models.User(id=123, email="owner@example.com")
        class_ = models.Class(
            id=1,
            name="Test Class",
            institution_id=institution.id,
            api_key="test-key",
        )
        session.add_all([user, class_])
        await session.flush()
        file = await models.File.create(
            session,
            {
                "file_id": "file-context",
                "private": True,
                "uploader_id": user.id,
                "name": "transcript.txt",
                "content_type": "text/plain",
            },
            class_id=class_.id,
        )
        source = await models.LectureSlideSourceStoredObject.create(
            session,
            key="slides.pdf",
            original_filename="slides.pdf",
            content_type="application/pdf",
            content_length=1024,
        )
        deck = await models.LectureSlideDeck.create(
            session,
            class_id=class_.id,
            source_stored_object_id=source.id,
            uploader_id=user.id,
            display_name="slides.pdf",
            slide_count=1,
        )
        staged_context = await models.LectureSlideAdditionalContextFile.create(
            session,
            lecture_slide_deck_id=None,
            file_object_id=file.id,
            class_id=class_.id,
            uploader_id=user.id,
            position=0,
            original_filename="transcript.txt",
            content_type="text/plain",
            content_length=2048,
        )
        staged_context_id = staged_context.id

        attached = (
            await lecture_slide_service.apply_lecture_slide_additional_context_files(
                session,
                deck,
                [staged_context_id],
                uploader_id=user.id,
                metadata=[
                    schemas.LectureSlideAdditionalContextFileMetadataInput(
                        id=staged_context_id,
                        file_kind=" transcript ",
                        usage_mode=" faithful ",
                        usage_note="  Skip the intro.  ",
                    )
                ],
            )
        )
        await session.commit()
        deck_id = deck.id

    assert attached is True
    async with db.async_session() as session:
        attached_files = (
            await models.LectureSlideAdditionalContextFile.get_all_by_deck_id_with_file(
                session, deck_id
            )
        )
        assert len(attached_files) == 1
        assert attached_files[0].file_kind == "transcript"
        assert attached_files[0].usage_mode == "faithful"
        assert attached_files[0].usage_note == "Skip the intro."
        attached_id = attached_files[0].id

    # Retagging an already attached file has to report a change, since stale
    # narration and questions are regenerated from that signal alone.
    async with db.async_session() as session:
        deck = await models.LectureSlideDeck.get_by_id(session, deck_id)
        retagged = (
            await lecture_slide_service.apply_lecture_slide_additional_context_files(
                session,
                deck,
                [attached_id],
                uploader_id=user.id,
                metadata=[
                    schemas.LectureSlideAdditionalContextFileMetadataInput(
                        id=attached_id,
                        file_kind=schemas.LECTURE_SLIDE_CONTEXT_FILE_KIND_TRANSCRIPT,
                        usage_mode=schemas.LECTURE_SLIDE_CONTEXT_FILE_USAGE_GUIDE,
                    )
                ],
            )
        )
        unchanged = (
            await lecture_slide_service.apply_lecture_slide_additional_context_files(
                session,
                deck,
                [attached_id],
                uploader_id=user.id,
                metadata=[
                    schemas.LectureSlideAdditionalContextFileMetadataInput(
                        id=attached_id,
                        file_kind=schemas.LECTURE_SLIDE_CONTEXT_FILE_KIND_TRANSCRIPT,
                        usage_mode=schemas.LECTURE_SLIDE_CONTEXT_FILE_USAGE_GUIDE,
                    )
                ],
            )
        )
        await session.commit()

    assert retagged is True
    assert unchanged is False
    async with db.async_session() as session:
        context_file = await session.get(
            models.LectureSlideAdditionalContextFile, attached_id
        )
        assert context_file is not None
        assert context_file.usage_mode == "guide"
        assert context_file.usage_note is None


@pytest.mark.asyncio
@with_institution(11, "Test Institution")
async def test_apply_additional_context_files_copies_metadata_from_snapshot(
    db, institution
):
    async with db.async_session() as session:
        user = models.User(id=123, email="owner@example.com")
        class_ = models.Class(
            id=1,
            name="Test Class",
            institution_id=institution.id,
            api_key="test-key",
        )
        session.add_all([user, class_])
        await session.flush()
        file = await models.File.create(
            session,
            {
                "file_id": "file-context",
                "private": True,
                "uploader_id": user.id,
                "name": "transcript.txt",
                "content_type": "text/plain",
            },
            class_id=class_.id,
        )
        source = await models.LectureSlideSourceStoredObject.create(
            session,
            key="slides.pdf",
            original_filename="slides.pdf",
            content_type="application/pdf",
            content_length=1024,
        )
        source_deck = await models.LectureSlideDeck.create(
            session,
            class_id=class_.id,
            source_stored_object_id=source.id,
            uploader_id=user.id,
            display_name="slides.pdf",
            slide_count=1,
        )
        snapshot_context = await models.LectureSlideAdditionalContextFile.create(
            session,
            lecture_slide_deck_id=source_deck.id,
            file_object_id=file.id,
            class_id=class_.id,
            uploader_id=user.id,
            position=0,
            original_filename="transcript.txt",
            content_type="text/plain",
            content_length=2048,
            file_kind="transcript",
            usage_mode="faithful",
            usage_note="Skip the intro.",
        )
        cloned_deck = await models.LectureSlideDeck.create(
            session,
            class_id=class_.id,
            source_stored_object_id=source.id,
            uploader_id=user.id,
            display_name="slides.pdf",
            slide_count=1,
            source_lecture_slide_deck_id_snapshot=source_deck.id,
        )

        changed = (
            await lecture_slide_service.apply_lecture_slide_additional_context_files(
                session,
                cloned_deck,
                [snapshot_context.id],
                uploader_id=user.id,
            )
        )
        await session.commit()
        cloned_deck_id = cloned_deck.id

    assert changed is True
    async with db.async_session() as session:
        attached_files = (
            await models.LectureSlideAdditionalContextFile.get_all_by_deck_id_with_file(
                session, cloned_deck_id
            )
        )
        assert len(attached_files) == 1
        assert attached_files[0].file_kind == "transcript"
        assert attached_files[0].usage_mode == "faithful"
        assert attached_files[0].usage_note == "Skip the intro."


@pytest.mark.asyncio
@with_institution(11, "Test Institution")
async def test_delete_lecture_slide_deck_if_unused_removes_context_rows_explicitly(
    db, institution, config, monkeypatch
):
    audio_store = FakeLectureSlideAudioStore()
    caption_store = FakeLectureSlideStore()
    monkeypatch.setattr(
        config,
        "lecture_video_audio_store",
        SimpleNamespace(store=audio_store),
    )
    monkeypatch.setattr(
        config,
        "video_store",
        SimpleNamespace(store=caption_store),
    )
    async with db.async_session() as session:
        user = models.User(id=123, email="owner@example.com")
        class_ = models.Class(
            id=1,
            name="Test Class",
            institution_id=institution.id,
            api_key="test-key",
        )
        session.add_all([user, class_])
        await session.flush()
        file = await models.File.create(
            session,
            {
                "file_id": "file-context",
                "private": True,
                "uploader_id": user.id,
                "name": "notes.md",
                "content_type": "text/markdown",
            },
            class_id=class_.id,
        )
        source = await models.LectureSlideSourceStoredObject.create(
            session,
            key="slides.pdf",
            original_filename="slides.pdf",
            content_type="application/pdf",
            content_length=1024,
        )
        deck = await models.LectureSlideDeck.create(
            session,
            class_id=class_.id,
            source_stored_object_id=source.id,
            uploader_id=user.id,
            display_name="slides.pdf",
            slide_count=1,
        )
        context_file = await models.LectureSlideAdditionalContextFile.create(
            session,
            lecture_slide_deck_id=deck.id,
            file_object_id=file.id,
            class_id=class_.id,
            uploader_id=user.id,
            position=0,
            original_filename="notes.md",
            content_type="text/markdown",
            content_length=2048,
        )
        translation = models.LectureSlideTranslation(
            lecture_slide_deck=deck,
            language_code="es",
            language_name="Spanish",
            openai_model="gpt-4o-mini",
            status=schemas.LectureSlideTranslationStatus.QUEUED,
            stage=schemas.LectureSlideTranslationStage.TRANSLATION_TEXT,
        )
        page_audio = models.LectureSlideNarrationStoredObject(
            key="translated-page.webm",
            content_type="audio/webm",
            content_length=100,
            duration_ms=500,
        )
        continuous_audio = models.LectureSlideNarrationStoredObject(
            key="translated-continuous.webm",
            content_type="audio/webm",
            content_length=100,
            duration_ms=500,
        )
        caption = models.LectureSlideCaptionStoredObject(
            key="translated.vtt",
            content_type="text/vtt",
            content_length=50,
        )
        translation.continuous_narration_stored_object = continuous_audio
        translation.caption_stored_object = caption
        translation_page = models.LectureSlideTranslationPage(
            translation=translation,
            position=0,
            narration_text="Narración",
            narration_stored_object=page_audio,
        )
        session.add_all(
            [translation, translation_page, page_audio, continuous_audio, caption]
        )
        await session.flush()
        page_audio_id = page_audio.id
        continuous_audio_id = continuous_audio.id
        caption_id = caption.id
        translation_run = models.LectureSlideTranslationRun(
            translation=translation,
            translation_id_snapshot=translation.id,
            stage=schemas.LectureSlideTranslationStage.TRANSLATION_TEXT,
            attempt_number=1,
            status=schemas.LectureSlideTranslationRunStatus.QUEUED,
        )
        session.add(translation_run)
        await session.flush()
        translation_run_id = translation_run.id

        file_object_ids = (
            await lecture_slide_service.delete_lecture_slide_deck_if_unused(
                session, deck.id
            )
        )
        await session.commit()

    async with db.async_session() as session:
        remaining_context = await session.get(
            models.LectureSlideAdditionalContextFile, context_file.id
        )
        remaining_translation_run = await session.get(
            models.LectureSlideTranslationRun, translation_run_id
        )
        remaining_page_audio = await session.get(
            models.LectureSlideNarrationStoredObject, page_audio_id
        )
        remaining_continuous_audio = await session.get(
            models.LectureSlideNarrationStoredObject, continuous_audio_id
        )
        remaining_caption = await session.get(
            models.LectureSlideCaptionStoredObject, caption_id
        )

    assert file_object_ids == [file.id]
    assert remaining_context is None
    assert remaining_translation_run is not None
    assert (
        remaining_translation_run.status
        == schemas.LectureSlideTranslationRunStatus.CANCELLED
    )
    assert remaining_translation_run.translation_id is None
    assert remaining_page_audio is None
    assert remaining_continuous_audio is None
    assert remaining_caption is None
    assert set(audio_store.deleted_keys) == {
        "translated-page.webm",
        "translated-continuous.webm",
    }
    assert caption_store.deleted_keys == ["translated.vtt"]


@pytest.mark.asyncio
@with_user(123)
@with_institution(11, "Test Institution")
@with_authz(grants=[("user:123", "can_edit", "assistant:1")])
async def test_upload_assistant_lecture_slide_additional_context_allows_editor(
    api, db, config, monkeypatch, institution, valid_user_token
):
    store = FakeLectureSlideStore()
    files = FakeOpenAIFiles()
    monkeypatch.setattr(config, "file_store", SimpleNamespace(store=store))

    async def fake_get_openai_client_by_class_id(session, class_id: int):
        assert class_id == 1
        return SimpleNamespace(files=files)

    monkeypatch.setattr(
        lecture_slide_service,
        "get_openai_client_by_class_id",
        fake_get_openai_client_by_class_id,
    )

    async with db.async_session() as session:
        class_ = models.Class(
            id=1,
            name="Test Class",
            institution_id=institution.id,
            api_key="test-key",
        )
        session.add(class_)
        await session.flush()
        session.add(
            models.Assistant(
                id=1,
                name="Lecture Slides Assistant",
                class_id=class_.id,
                creator_id=123,
                interaction_mode=schemas.InteractionMode.LECTURE_SLIDES,
                version=3,
                model="gpt-4o-mini",
                instructions="Teach the lecture.",
                tools="[]",
            )
        )
        await session.commit()

    response = api.post(
        "/api/v1/class/1/assistant/1/lecture-slides/additional-context/upload",
        files={"upload": ("notes.md", b"# Instructor notes", "text/markdown")},
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["filename"] == "notes.md"
    assert body["size"] == len(b"# Instructor notes")
    assert body["content_type"] == "text/markdown"
    assert body["file_object_id"]
    assert body["file_kind"] == "other"
    assert body["usage_mode"] == "guide"
    assert body["usage_note"] is None
    assert files.created_files == [
        (("notes.md", b"# Instructor notes", "text/markdown"), "user_data")
    ]
    assert list(store.stored_files.values()) == [b"# Instructor notes"]


@pytest.mark.asyncio
@with_user(123)
@with_institution(11, "Test Institution")
@with_authz(
    grants=[
        ("user:123", "admin", "class:1"),
        ("user:123", "can_create_assistants", "class:1"),
        ("user:123", "can_edit", "assistant:1"),
    ]
)
async def test_retry_lecture_slide_endpoint_queues_processing_after_failure(
    api, db, institution, valid_user_token
):
    async with db.async_session() as session:
        class_ = await session.get(models.Class, 1)
        if class_ is None:
            class_ = models.Class(
                id=1,
                name="Test Class",
                institution_id=institution.id,
                api_key="test-key",
            )
            session.add(class_)
        await session.flush()
        source = await models.LectureSlideSourceStoredObject.create(
            session,
            key="lecture04.pdf",
            original_filename="lecture04.pdf",
            content_type="application/pdf",
            content_length=128,
        )
        deck = await models.LectureSlideDeck.create(
            session,
            class_id=class_.id,
            source_stored_object_id=source.id,
            uploader_id=123,
            display_name="lecture04.pdf",
            slide_count=18,
            voice_id="voice-test-id",
            status=schemas.LectureSlideDeckStatus.FAILED,
            error_message="Unable to process the lecture slide deck right now. Please retry.",
        )
        assistant = models.Assistant(
            id=1,
            name="Physics Slides",
            class_id=class_.id,
            interaction_mode=schemas.InteractionMode.LECTURE_SLIDES,
            version=3,
            lecture_slide_deck_id=deck.id,
            instructions="You are a lecture assistant.",
            model="gpt-4o-mini",
            tools="[]",
            use_latex=False,
            use_image_descriptions=False,
            hide_prompt=False,
        )
        session.add(assistant)
        await models.LectureSlideProcessingRun.create(
            session,
            lecture_slide_deck_id=deck.id,
            lecture_slide_deck_id_snapshot=deck.id,
            class_id=class_.id,
            assistant_id_at_start=assistant.id,
            stage=schemas.LectureSlideProcessingStage.NARRATION_TRANSCRIPTION,
            attempt_number=1,
            status=schemas.LectureSlideProcessingRunStatus.FAILED,
        )
        await session.commit()
        deck_id = deck.id

    response = api.post(
        "/api/v1/class/1/assistant/1/lecture-slides/retry",
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == schemas.LectureSlideDeckStatus.PROCESSING.value
    assert response.json()["error_message"] is None

    async with db.async_session() as session:
        refreshed_deck = await models.LectureSlideDeck.get_by_id(session, deck_id)
        runs = list(
            (
                await session.scalars(
                    select(models.LectureSlideProcessingRun)
                    .where(
                        models.LectureSlideProcessingRun.lecture_slide_deck_id_snapshot
                        == deck_id
                    )
                    .order_by(models.LectureSlideProcessingRun.attempt_number.asc())
                )
            ).all()
        )

    assert refreshed_deck is not None
    assert refreshed_deck.status == schemas.LectureSlideDeckStatus.PROCESSING
    assert refreshed_deck.error_message is None
    assert len(runs) == 2
    assert runs[0].status == schemas.LectureSlideProcessingRunStatus.FAILED
    assert runs[1].status == schemas.LectureSlideProcessingRunStatus.QUEUED
    assert runs[1].stage == schemas.LectureSlideProcessingStage.NARRATION_AUDIO
    assert runs[1].attempt_number == 2


@pytest.mark.asyncio
@with_user(123)
@with_institution(11, "Test Institution")
@with_authz(
    grants=[
        ("user:123", "admin", "class:1"),
        ("user:123", "can_create_assistants", "class:1"),
        ("user:123", "can_edit", "assistant:1"),
    ]
)
async def test_lecture_slide_config_returns_pending_question_drafts(
    api, db, institution, valid_user_token
):
    async with db.async_session() as session:
        class_ = models.Class(
            id=1,
            name="Test Class",
            institution_id=institution.id,
            api_key="test-key",
        )
        session.add(class_)
        await session.flush()
        source = await models.LectureSlideSourceStoredObject.create(
            session,
            key="lecture04.pdf",
            original_filename="lecture04.pdf",
            content_type="application/pdf",
            content_length=128,
        )
        deck = await models.LectureSlideDeck.create(
            session,
            class_id=class_.id,
            source_stored_object_id=source.id,
            uploader_id=123,
            display_name="lecture04.pdf",
            slide_count=2,
            voice_id="voice-test-id",
            context_data={
                schemas.LECTURE_SLIDE_MANUAL_QUESTIONS_CONTEXT_KEY: [
                    {
                        "mode": schemas.LectureSlideQuestionDraftMode.PARTIAL.value,
                        "slide_position": 0,
                        "question_text": "Use this prompt.",
                        "intro_text": "",
                        "options": [],
                    },
                    {
                        "mode": schemas.LectureSlideQuestionDraftMode.MARKER.value,
                        "slide_position": 1,
                        "question_text": "",
                        "intro_text": "",
                        "options": [],
                    },
                ]
            },
        )
        session.add(
            models.Assistant(
                id=1,
                name="Physics Slides",
                class_id=class_.id,
                interaction_mode=schemas.InteractionMode.LECTURE_SLIDES,
                version=3,
                lecture_slide_deck_id=deck.id,
                instructions="You are a lecture assistant.",
                model="gpt-4o-mini",
                tools="[]",
                use_latex=False,
                use_image_descriptions=False,
                hide_prompt=False,
            )
        )
        session.add(
            models.LectureSlidePage(
                lecture_slide_deck_id=deck.id,
                position=0,
                title="Random assignment",
                extracted_text="Treatment group and control group",
                image_description="A diagram splitting participants into two groups.",
            )
        )
        await session.commit()

    response = api.get(
        "/api/v1/class/1/assistant/1/lecture-slides/config",
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["questions"] == []
    assert body["pages"][0]["title"] == "Random assignment"
    assert body["pages"][0]["extracted_text"] == "Treatment group and control group"
    assert body["pages"][0]["image_description"] == (
        "A diagram splitting participants into two groups."
    )
    assert [
        (question["mode"], question["slide_position"], question["question_text"])
        for question in body["question_drafts"]
    ] == [
        ("partial", 0, "Use this prompt."),
        ("marker", 1, ""),
    ]


@pytest.mark.asyncio
@with_institution(11, "Test Institution")
async def test_apply_lecture_slide_page_notes_handles_unloaded_pages(db, institution):
    async with db.async_session() as session:
        class_ = models.Class(
            id=1,
            name="Test Class",
            institution_id=institution.id,
            api_key="test-key",
        )
        session.add(class_)
        await session.flush()
        source = await models.LectureSlideSourceStoredObject.create(
            session,
            key="lecture04.pdf",
            original_filename="lecture04.pdf",
            content_type="application/pdf",
            content_length=128,
        )
        deck = await models.LectureSlideDeck.create(
            session,
            class_id=class_.id,
            source_stored_object_id=source.id,
            uploader_id=123,
            display_name="lecture04.pdf",
            slide_count=2,
            voice_id="voice-test-id",
        )
        session.add(
            models.LectureSlidePage(
                lecture_slide_deck_id=deck.id,
                position=0,
                user_notes="Old notes",
            )
        )
        await session.commit()
        deck_id = deck.id

    async with db.async_session() as session:
        deck = await models.LectureSlideDeck.get_by_id(session, deck_id)
        assert deck is not None
        assert "pages" not in deck.__dict__

        result = await lecture_slide_service.apply_lecture_slide_page_notes(
            session,
            deck,
            [
                schemas.LectureSlidePageNotes(
                    position=0,
                    user_notes="New notes",
                    narration_text="Narrate this.",
                )
            ],
        )
        await session.commit()

    assert result.notes_changed is True
    assert result.narration_changed is True

    async with db.async_session() as session:
        page = await session.scalar(
            select(models.LectureSlidePage).where(
                models.LectureSlidePage.lecture_slide_deck_id == deck_id,
                models.LectureSlidePage.position == 0,
            )
        )

    assert page is not None
    assert page.user_notes == "New notes"
    assert page.narration_text == "Narrate this."


@pytest.mark.asyncio
@with_institution(11, "Test Institution")
async def test_apply_lecture_slide_content_items_inserts_and_reorders_media(
    db, institution
):
    async with db.async_session() as session:
        class_ = models.Class(
            id=1,
            name="Test Class",
            institution_id=institution.id,
            api_key="test-key",
        )
        session.add(class_)
        await session.flush()
        source = await models.LectureSlideSourceStoredObject.create(
            session,
            key="mixed.pdf",
            original_filename="mixed.pdf",
            content_type="application/pdf",
            content_length=128,
        )
        deck = await models.LectureSlideDeck.create(
            session,
            class_id=class_.id,
            source_stored_object_id=source.id,
            uploader_id=123,
            display_name="mixed.pdf",
            slide_count=2,
            source_page_count=2,
            voice_id="voice-test-id",
        )
        session.add_all(
            [
                models.LectureSlidePage(
                    lecture_slide_deck_id=deck.id,
                    position=0,
                    source_page_number=0,
                ),
                models.LectureSlidePage(
                    lecture_slide_deck_id=deck.id,
                    position=1,
                    source_page_number=1,
                ),
            ]
        )
        image = await models.LectureSlideMediaStoredObject.create(
            session,
            class_id=class_.id,
            uploader_id=123,
            key="insert.png",
            original_filename="insert.png",
            content_type="image/png",
            content_length=100,
            content_kind=schemas.LectureSlideContentKind.IMAGE,
            duration_ms=None,
            width_px=640,
            height_px=480,
        )
        video = await models.LectureSlideMediaStoredObject.create(
            session,
            class_id=class_.id,
            uploader_id=123,
            key="insert.mp4",
            original_filename="insert.mp4",
            content_type="video/mp4",
            content_length=1000,
            content_kind=schemas.LectureSlideContentKind.VIDEO,
            duration_ms=5000,
            width_px=1280,
            height_px=720,
        )
        await session.commit()

        result = await lecture_slide_service.apply_lecture_slide_content_items(
            session,
            deck,
            [
                schemas.LectureSlideContentItemInput(
                    content_kind="image", media_stored_object_id=image.id
                ),
                schemas.LectureSlideContentItemInput(
                    content_kind="slide", source_page_number=0
                ),
                schemas.LectureSlideContentItemInput(
                    content_kind="video", media_stored_object_id=video.id
                ),
                schemas.LectureSlideContentItemInput(
                    content_kind="slide", source_page_number=1
                ),
            ],
            uploader_id=123,
        )
        await session.commit()
        deck_id = deck.id
        image_id = image.id
        video_id = video.id

    assert result.structure_changed is True
    assert result.requires_narration_generation is True
    async with db.async_session() as session:
        deck = await models.LectureSlideDeck.get_by_id_with_processing_context(
            session, deck_id
        )
        assert deck is not None
        assert deck.slide_count == 4
        assert [page.content_kind.value for page in deck.pages] == [
            "image",
            "slide",
            "video",
            "slide",
        ]
        assert [page.source_page_number for page in deck.pages] == [None, 0, None, 1]
        assert [page.media_stored_object_id for page in deck.pages] == [
            image_id,
            None,
            video_id,
            None,
        ]

        removal_result = await lecture_slide_service.apply_lecture_slide_content_items(
            session,
            deck,
            [
                schemas.LectureSlideContentItemInput(
                    content_kind="slide", source_page_number=0
                ),
                schemas.LectureSlideContentItemInput(
                    content_kind="video", media_stored_object_id=video_id
                ),
                schemas.LectureSlideContentItemInput(
                    content_kind="slide", source_page_number=1
                ),
            ],
            uploader_id=123,
        )
        await session.commit()
        removed_image = await session.get(
            models.LectureSlideMediaStoredObject, image_id
        )
        retained_video = await session.get(
            models.LectureSlideMediaStoredObject, video_id
        )

    assert removal_result.structure_changed is True
    assert removed_image is None
    assert retained_video is not None


@pytest.mark.asyncio
@with_institution(11, "Test Institution")
async def test_video_transcript_and_audio_survive_editor_payloads(db, institution):
    async with db.async_session() as session:
        class_ = models.Class(
            id=1,
            name="Test Class",
            institution_id=institution.id,
            api_key="test-key",
        )
        session.add(class_)
        await session.flush()
        source = await models.LectureSlideSourceStoredObject.create(
            session,
            key="mixed.pdf",
            original_filename="mixed.pdf",
            content_type="application/pdf",
            content_length=128,
        )
        deck = await models.LectureSlideDeck.create(
            session,
            class_id=class_.id,
            source_stored_object_id=source.id,
            uploader_id=123,
            display_name="mixed.pdf",
            slide_count=2,
            source_page_count=1,
            voice_id="voice-test-id",
        )
        media = await models.LectureSlideMediaStoredObject.create(
            session,
            class_id=class_.id,
            uploader_id=123,
            key="insert.mp4",
            original_filename="insert.mp4",
            content_type="video/mp4",
            content_length=1000,
            content_kind=schemas.LectureSlideContentKind.VIDEO,
            duration_ms=5000,
            width_px=1280,
            height_px=720,
        )
        stored_object = models.LectureSlideNarrationStoredObject(
            key="insert.webm",
            content_type="audio/webm",
            content_length=500,
            duration_ms=5000,
        )
        session.add(stored_object)
        await session.flush()
        narration = models.LectureSlideNarration(
            stored_object_id=stored_object.id,
            status=schemas.LectureSlideNarrationStatus.READY,
        )
        session.add(narration)
        await session.flush()
        session.add_all(
            [
                models.LectureSlidePage(
                    lecture_slide_deck_id=deck.id,
                    position=0,
                    content_kind=schemas.LectureSlideContentKind.SLIDE,
                    source_page_number=0,
                ),
                models.LectureSlidePage(
                    lecture_slide_deck_id=deck.id,
                    position=1,
                    content_kind=schemas.LectureSlideContentKind.VIDEO,
                    media_stored_object_id=media.id,
                    narration_text="Original clip transcript.",
                    narration_id=narration.id,
                    start_offset_ms=1000,
                    end_offset_ms=6000,
                ),
            ]
        )
        await session.commit()

        content_result = await lecture_slide_service.apply_lecture_slide_content_items(
            session,
            deck,
            [
                schemas.LectureSlideContentItemInput(
                    content_kind="slide", source_page_number=0
                ),
                schemas.LectureSlideContentItemInput(
                    content_kind="video", media_stored_object_id=media.id
                ),
            ],
            uploader_id=123,
        )
        notes_result = await lecture_slide_service.apply_lecture_slide_page_notes(
            session,
            deck,
            [schemas.LectureSlidePageNotes(position=1, narration_text=None)],
        )
        await session.commit()
        video_page = await session.scalar(
            select(models.LectureSlidePage).where(
                models.LectureSlidePage.lecture_slide_deck_id == deck.id,
                models.LectureSlidePage.position == 1,
            )
        )

    assert content_result.narration_changed is False
    assert notes_result.narration_changed is False
    assert video_page is not None
    assert video_page.narration_text == "Original clip transcript."
    assert video_page.narration_id == narration.id
    assert video_page.start_offset_ms == 1000
    assert video_page.end_offset_ms == 6000


def test_ready_lecture_slide_media_update_starts_at_narration_text():
    server_module = importlib.import_module("pingpong.server")
    stage = server_module._lecture_slide_update_processing_stage(
        needs_full_processing=False,
        needs_narration_text=True,
        needs_audio=True,
        needs_questions=True,
    )

    assert stage == schemas.LectureSlideProcessingStage.NARRATION_TEXT


@pytest.mark.asyncio
async def test_lecture_slide_media_stream_supports_byte_ranges(config, monkeypatch):
    requested_ranges: list[tuple[int | None, int | None]] = []

    class Store:
        async def stream_video_range(self, *, key, start=None, end=None):
            assert key == "clip.mp4"
            requested_ranges.append((start, end))
            content = b"0123456789"
            yield content[start : end + 1]

    monkeypatch.setattr(config, "video_store", SimpleNamespace(store=Store()))
    server_module = importlib.import_module("pingpong.server")

    response = await server_module._stream_video_store_response(
        key="clip.mp4",
        content_length=10,
        content_type="video/mp4",
        range_header="bytes=2-5",
        retrieval_error_detail="Could not stream clip.",
    )
    body = b"".join([chunk async for chunk in response.body_iterator])

    assert requested_ranges == [(2, 5)]
    assert response.status_code == 206
    assert response.headers["accept-ranges"] == "bytes"
    assert response.headers["content-range"] == "bytes 2-5/10"
    assert response.headers["content-length"] == "4"
    assert body == b"2345"


def test_lecture_slide_video_content_rejects_generated_narration():
    with pytest.raises(ValueError, match="original audio"):
        schemas.LectureSlideContentItemInput(
            content_kind="video",
            media_stored_object_id=7,
            narration_text="Generated voice-over",
        )


@pytest.mark.asyncio
@with_institution(11, "Test Institution")
async def test_apply_lecture_slide_page_notes_deletes_replaced_narration_audio(
    db, institution, config, monkeypatch, tmp_path
):
    narration_dir = tmp_path / "narrations"
    monkeypatch.setattr(
        config,
        "lecture_video_audio_store",
        LocalAudioStoreSettings(save_target=str(narration_dir)),
    )

    async with db.async_session() as session:
        class_ = models.Class(
            id=1,
            name="Test Class",
            institution_id=institution.id,
            api_key="test-key",
        )
        session.add(class_)
        await session.flush()
        source = await models.LectureSlideSourceStoredObject.create(
            session,
            key="lecture04.pdf",
            original_filename="lecture04.pdf",
            content_type="application/pdf",
            content_length=128,
        )
        deck = await models.LectureSlideDeck.create(
            session,
            class_id=class_.id,
            source_stored_object_id=source.id,
            uploader_id=123,
            display_name="lecture04.pdf",
            slide_count=1,
            voice_id="voice-test-id",
        )
        stored_object = models.LectureSlideNarrationStoredObject(
            key="edited-slide.ogg",
            content_type="audio/ogg",
            content_length=100,
        )
        session.add(stored_object)
        await session.flush()
        narration_dir.mkdir(parents=True, exist_ok=True)
        (narration_dir / stored_object.key).write_bytes(b"slide-audio")
        narration = models.LectureSlideNarration(
            stored_object_id=stored_object.id,
            status=schemas.LectureSlideNarrationStatus.READY,
        )
        session.add(narration)
        await session.flush()
        page = models.LectureSlidePage(
            lecture_slide_deck_id=deck.id,
            position=0,
            narration_text="Old narration.",
            narration_id=narration.id,
            start_offset_ms=0,
            end_offset_ms=100,
        )
        session.add(page)
        await session.commit()
        deck_id = deck.id

    async with db.async_session() as session:
        deck = await models.LectureSlideDeck.get_by_id(session, deck_id)
        assert deck is not None
        result = await lecture_slide_service.apply_lecture_slide_page_notes(
            session,
            deck,
            [
                schemas.LectureSlidePageNotes(
                    position=0,
                    narration_text="New narration.",
                )
            ],
        )
        await session.commit()
        page_after_edit = await session.scalar(
            select(models.LectureSlidePage).where(
                models.LectureSlidePage.lecture_slide_deck_id == deck_id,
                models.LectureSlidePage.position == 0,
            )
        )
        narration_count = await session.scalar(
            select(func.count()).select_from(models.LectureSlideNarration)
        )
        stored_object_count = await session.scalar(
            select(func.count()).select_from(models.LectureSlideNarrationStoredObject)
        )

    assert result.narration_changed is True
    assert page_after_edit is not None
    assert page_after_edit.narration_id is None
    assert page_after_edit.start_offset_ms is None
    assert page_after_edit.end_offset_ms is None
    assert narration_count == 0
    assert stored_object_count == 0
    assert not (narration_dir / "edited-slide.ogg").exists()


@pytest.mark.asyncio
@with_institution(11, "Test Institution")
async def test_apply_lecture_slide_question_drafts_uses_model_loaded_context_data(
    db, institution
):
    async with db.async_session() as session:
        class_ = models.Class(
            id=1,
            name="Test Class",
            institution_id=institution.id,
            api_key="test-key",
        )
        session.add(class_)
        await session.flush()
        source = await models.LectureSlideSourceStoredObject.create(
            session,
            key="lecture04.pdf",
            original_filename="lecture04.pdf",
            content_type="application/pdf",
            content_length=128,
        )
        deck = await models.LectureSlideDeck.create(
            session,
            class_id=class_.id,
            source_stored_object_id=source.id,
            uploader_id=123,
            display_name="lecture04.pdf",
            slide_count=1,
            voice_id="voice-test-id",
        )
        session.add(models.LectureSlidePage(lecture_slide_deck_id=deck.id, position=0))
        await session.commit()
        deck_id = deck.id
        class_id = class_.id

    async with db.async_session() as session:
        deck = await models.LectureSlideDeck.get_by_id(session, deck_id)
        assert deck is not None
        assert "context_data" in deck.__dict__

        result = await lecture_slide_service.apply_lecture_slide_question_drafts(
            session,
            deck,
            [
                schemas.LectureSlideQuestionInput(
                    mode=schemas.LectureSlideQuestionDraftMode.PARTIAL,
                    slide_position=0,
                    question_text="Ask about the main point.",
                    options=[],
                )
            ],
        )
        await session.commit()

    async with db.async_session() as session:
        refreshed_deck = await models.LectureSlideDeck.get_by_id_for_class(
            session, deck_id, class_id
        )

    assert result.requires_question_generation is True
    assert result.questions_changed is True
    assert refreshed_deck is not None
    assert refreshed_deck.context_data == {
        schemas.LECTURE_SLIDE_MANUAL_QUESTIONS_CONTEXT_KEY: [
            {
                "id": None,
                "mode": schemas.LectureSlideQuestionDraftMode.PARTIAL.value,
                "slide_position": 0,
                "question_text": "Ask about the main point.",
                "intro_text": "",
                "options": [],
            }
        ]
    }


@pytest.mark.asyncio
@with_institution(11, "Test Institution")
async def test_clone_lecture_slide_deck_snapshot_returns_loaded_context_data(
    db, institution
):
    async with db.async_session() as session:
        class_ = models.Class(
            id=1,
            name="Test Class",
            institution_id=institution.id,
            api_key="test-key",
        )
        session.add(class_)
        await session.flush()
        source = await models.LectureSlideSourceStoredObject.create(
            session,
            key="lecture04.pdf",
            original_filename="lecture04.pdf",
            content_type="application/pdf",
            content_length=128,
        )
        deck = await models.LectureSlideDeck.create(
            session,
            class_id=class_.id,
            source_stored_object_id=source.id,
            uploader_id=123,
            display_name="lecture04.pdf",
            slide_count=3,
            source_page_count=1,
            voice_id="voice-test-id",
            context_data={"manual_questions": []},
        )
        file = await models.File.create(
            session,
            {
                "file_id": "file-context",
                "private": True,
                "uploader_id": 123,
                "name": "transcript.txt",
                "content_type": "text/plain",
            },
            class_id=class_.id,
        )
        await models.LectureSlideAdditionalContextFile.create(
            session,
            lecture_slide_deck_id=deck.id,
            file_object_id=file.id,
            class_id=class_.id,
            uploader_id=123,
            position=0,
            original_filename="transcript.txt",
            content_type="text/plain",
            content_length=2048,
            file_kind="transcript",
            usage_mode="guide",
            usage_note="Use for pacing.",
        )
        loaded_deck = await models.LectureSlideDeck.get_by_id_with_processing_context(
            session, deck.id
        )
        assert loaded_deck is not None

        cloned_deck = await lecture_slide_service.clone_lecture_slide_deck_snapshot(
            session, loaded_deck
        )
        await session.flush()
        cloned_context_files = (
            await models.LectureSlideAdditionalContextFile.get_all_by_deck_id_with_file(
                session, cloned_deck.id
            )
        )

    assert "context_data" in cloned_deck.__dict__
    assert cloned_deck.context_data == {"manual_questions": []}
    assert cloned_deck.slide_count == 3
    assert cloned_deck.source_page_count == 1
    assert len(cloned_context_files) == 1
    assert cloned_context_files[0].file_kind == "transcript"
    assert cloned_context_files[0].usage_mode == "guide"
    assert cloned_context_files[0].usage_note == "Use for pacing."


@pytest.mark.asyncio
@with_institution(11, "Test Institution")
async def test_clear_lecture_slide_page_narrations_deletes_unused_audio(
    db, institution, config, monkeypatch, tmp_path
):
    narration_dir = tmp_path / "narrations"
    monkeypatch.setattr(
        config,
        "lecture_video_audio_store",
        LocalAudioStoreSettings(save_target=str(narration_dir)),
    )

    async with db.async_session() as session:
        class_ = models.Class(
            id=1,
            name="Test Class",
            institution_id=institution.id,
            api_key="test-key",
        )
        session.add(class_)
        await session.flush()
        source = await models.LectureSlideSourceStoredObject.create(
            session,
            key="lecture04.pdf",
            original_filename="lecture04.pdf",
            content_type="application/pdf",
            content_length=128,
        )
        deck = await models.LectureSlideDeck.create(
            session,
            class_id=class_.id,
            source_stored_object_id=source.id,
            uploader_id=123,
            display_name="lecture04.pdf",
            slide_count=1,
            voice_id="voice-test-id",
        )
        stored_object = models.LectureSlideNarrationStoredObject(
            key="slide-1.ogg",
            content_type="audio/ogg",
            content_length=100,
        )
        session.add(stored_object)
        await session.flush()
        narration_dir.mkdir(parents=True, exist_ok=True)
        (narration_dir / stored_object.key).write_bytes(b"slide-audio")
        narration = models.LectureSlideNarration(
            stored_object_id=stored_object.id,
            status=schemas.LectureSlideNarrationStatus.READY,
        )
        session.add(narration)
        await session.flush()
        page = models.LectureSlidePage(
            lecture_slide_deck_id=deck.id,
            position=0,
            narration_id=narration.id,
            start_offset_ms=0,
            end_offset_ms=100,
        )
        session.add(page)
        await session.commit()

        await lecture_slide_service.clear_lecture_slide_page_narrations(
            session, deck.id
        )
        await session.commit()

        page_after_clear = await session.get(models.LectureSlidePage, page.id)
        page_after_clear_narration_id = (
            page_after_clear.narration_id if page_after_clear else None
        )
        page_after_clear_start_offset_ms = (
            page_after_clear.start_offset_ms if page_after_clear else None
        )
        page_after_clear_end_offset_ms = (
            page_after_clear.end_offset_ms if page_after_clear else None
        )
        narration_count = await session.scalar(
            select(func.count()).select_from(models.LectureSlideNarration)
        )
        stored_object_count = await session.scalar(
            select(func.count()).select_from(models.LectureSlideNarrationStoredObject)
        )

    assert page_after_clear is not None
    assert page_after_clear_narration_id is None
    assert page_after_clear_start_offset_ms is None
    assert page_after_clear_end_offset_ms is None
    assert narration_count == 0
    assert stored_object_count == 0
    assert not (narration_dir / "slide-1.ogg").exists()


@pytest.mark.asyncio
@with_institution(11, "Test Institution")
async def test_clear_lecture_slide_page_narrations_preserves_shared_audio(
    db, institution, config, monkeypatch, tmp_path
):
    narration_dir = tmp_path / "narrations"
    monkeypatch.setattr(
        config,
        "lecture_video_audio_store",
        LocalAudioStoreSettings(save_target=str(narration_dir)),
    )

    async with db.async_session() as session:
        class_ = models.Class(
            id=1,
            name="Test Class",
            institution_id=institution.id,
            api_key="test-key",
        )
        session.add(class_)
        await session.flush()
        source = await models.LectureSlideSourceStoredObject.create(
            session,
            key="lecture04.pdf",
            original_filename="lecture04.pdf",
            content_type="application/pdf",
            content_length=128,
        )
        first_deck = await models.LectureSlideDeck.create(
            session,
            class_id=class_.id,
            source_stored_object_id=source.id,
            uploader_id=123,
            display_name="lecture04.pdf",
            slide_count=1,
            voice_id="voice-test-id",
        )
        second_deck = await models.LectureSlideDeck.create(
            session,
            class_id=class_.id,
            source_stored_object_id=source.id,
            uploader_id=123,
            display_name="lecture04-copy.pdf",
            slide_count=1,
            voice_id="voice-test-id",
        )
        stored_object = models.LectureSlideNarrationStoredObject(
            key="shared-slide.ogg",
            content_type="audio/ogg",
            content_length=100,
        )
        session.add(stored_object)
        await session.flush()
        narration_dir.mkdir(parents=True, exist_ok=True)
        (narration_dir / stored_object.key).write_bytes(b"shared-audio")
        first_narration = models.LectureSlideNarration(
            stored_object_id=stored_object.id,
            status=schemas.LectureSlideNarrationStatus.READY,
        )
        second_narration = models.LectureSlideNarration(
            stored_object_id=stored_object.id,
            status=schemas.LectureSlideNarrationStatus.READY,
        )
        session.add_all([first_narration, second_narration])
        await session.flush()
        second_narration_id = second_narration.id
        session.add_all(
            [
                models.LectureSlidePage(
                    lecture_slide_deck_id=first_deck.id,
                    position=0,
                    narration_id=first_narration.id,
                ),
                models.LectureSlidePage(
                    lecture_slide_deck_id=second_deck.id,
                    position=0,
                    narration_id=second_narration.id,
                ),
            ]
        )
        await session.commit()

        await lecture_slide_service.clear_lecture_slide_page_narrations(
            session, first_deck.id
        )
        await session.commit()

        remaining_narration_count = await session.scalar(
            select(func.count()).select_from(models.LectureSlideNarration)
        )
        remaining_stored_object_count = await session.scalar(
            select(func.count()).select_from(models.LectureSlideNarrationStoredObject)
        )
        second_page = await session.scalar(
            select(models.LectureSlidePage).where(
                models.LectureSlidePage.lecture_slide_deck_id == second_deck.id
            )
        )
        second_page_narration_id = second_page.narration_id if second_page else None

    assert remaining_narration_count == 1
    assert remaining_stored_object_count == 1
    assert second_page is not None
    assert second_page_narration_id == second_narration_id
    assert (narration_dir / "shared-slide.ogg").exists()


@pytest.mark.asyncio
@with_institution(11, "Test Institution")
async def test_delete_unused_lecture_slide_deck_deletes_page_narration_audio(
    db, institution, config, monkeypatch, tmp_path
):
    narration_dir = tmp_path / "narrations"
    monkeypatch.setattr(
        config,
        "lecture_video_audio_store",
        LocalAudioStoreSettings(save_target=str(narration_dir)),
    )

    async with db.async_session() as session:
        class_ = models.Class(
            id=1,
            name="Test Class",
            institution_id=institution.id,
            api_key="test-key",
        )
        session.add(class_)
        await session.flush()
        source = await models.LectureSlideSourceStoredObject.create(
            session,
            key="lecture04.pdf",
            original_filename="lecture04.pdf",
            content_type="application/pdf",
            content_length=128,
        )
        deck = await models.LectureSlideDeck.create(
            session,
            class_id=class_.id,
            source_stored_object_id=source.id,
            uploader_id=123,
            display_name="lecture04.pdf",
            slide_count=1,
            voice_id="voice-test-id",
        )
        stored_object = models.LectureSlideNarrationStoredObject(
            key="deleted-deck-slide.ogg",
            content_type="audio/ogg",
            content_length=100,
        )
        session.add(stored_object)
        await session.flush()
        narration_dir.mkdir(parents=True, exist_ok=True)
        (narration_dir / stored_object.key).write_bytes(b"slide-audio")
        narration = models.LectureSlideNarration(
            stored_object_id=stored_object.id,
            status=schemas.LectureSlideNarrationStatus.READY,
        )
        session.add(narration)
        await session.flush()
        session.add(
            models.LectureSlidePage(
                lecture_slide_deck_id=deck.id,
                position=0,
                narration_id=narration.id,
            )
        )
        await session.commit()

        await lecture_slide_service.delete_lecture_slide_deck_if_unused(
            session, deck.id
        )
        await session.commit()

        remaining_deck_count = await session.scalar(
            select(func.count()).select_from(models.LectureSlideDeck)
        )
        remaining_narration_count = await session.scalar(
            select(func.count()).select_from(models.LectureSlideNarration)
        )
        remaining_stored_object_count = await session.scalar(
            select(func.count()).select_from(models.LectureSlideNarrationStoredObject)
        )

    assert remaining_deck_count == 0
    assert remaining_narration_count == 0
    assert remaining_stored_object_count == 0
    assert not (narration_dir / "deleted-deck-slide.ogg").exists()
