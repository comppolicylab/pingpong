import io
from types import SimpleNamespace

from fastapi import UploadFile
from pypdf import PdfWriter
from sqlalchemy import func, select

import pingpong.schemas as schemas
from pingpong import lecture_slide_service, models
from pingpong.models import file_class_association
from pingpong.config import LocalAudioStoreSettings

from .testutil import with_authz, with_institution, with_user


class FakeLectureSlideStore:
    def __init__(self):
        self.stored_files: dict[str, bytes] = {}
        self.deleted_keys: list[str] = []

    async def put(self, key: str, file, content_type: str):
        self.stored_files[key] = file.read()

    async def delete(self, key: str):
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
