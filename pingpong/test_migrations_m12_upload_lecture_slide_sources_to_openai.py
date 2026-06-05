from types import SimpleNamespace

import pytest

from pingpong import lecture_slide_service, models, schemas
from pingpong.migrations import m12_upload_lecture_slide_sources_to_openai as migration
from pingpong.models import file_class_association

pytestmark = pytest.mark.asyncio


class FakeVideoStore:
    def __init__(self, payloads: dict[str, bytes]):
        self.payloads = payloads
        self.seen_keys: list[str] = []

    async def stream_video(self, key: str):
        self.seen_keys.append(key)
        payload = self.payloads[key]
        yield payload[:5]
        yield payload[5:]


class FakeOpenAIFiles:
    def __init__(self):
        self.created_files = []

    async def create(self, *, file, purpose: str):
        self.created_files.append((file, purpose))
        return SimpleNamespace(id=f"file-{len(self.created_files)}")


async def test_upload_lecture_slide_sources_to_openai_uploads_unlinked_sources(
    db, config, monkeypatch
):
    video_store = FakeVideoStore({"slides.pdf": b"%PDF slide bytes"})
    files = FakeOpenAIFiles()
    monkeypatch.setattr(config, "video_store", SimpleNamespace(store=video_store))

    async def fake_get_openai_client_by_class_id(session, class_id: int):
        assert class_id == 1
        return SimpleNamespace(files=files)

    monkeypatch.setattr(
        lecture_slide_service,
        "get_openai_client_by_class_id",
        fake_get_openai_client_by_class_id,
    )

    async with db.async_session() as session:
        institution = models.Institution(id=1, name="Test Institution")
        user = models.User(id=123, email="owner@example.com")
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
            content_length=16,
        )
        deck = models.LectureSlideDeck(
            class_=class_,
            source_stored_object=source,
            uploader_id=user.id,
            display_name="slides.pdf",
            status="ready",
            slide_count=1,
        )
        session.add_all([institution, user, class_, source, deck])
        await session.commit()
        source_id = source.id

    async with db.async_session() as session:
        result = await migration.upload_lecture_slide_sources_to_openai(session)

    assert result == migration.UploadLectureSlideSourcesToOpenAIResult(
        uploaded=1,
        skipped=0,
        failed=0,
    )
    assert video_store.seen_keys == ["slides.pdf"]
    assert files.created_files == [
        (("slides.pdf", b"%PDF slide bytes", "application/pdf"), "user_data")
    ]

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


async def test_upload_lecture_slide_sources_to_openai_skips_already_linked_sources(
    db, config, monkeypatch
):
    video_store = FakeVideoStore({"slides.pdf": b"%PDF slide bytes"})
    monkeypatch.setattr(config, "video_store", SimpleNamespace(store=video_store))

    async with db.async_session() as session:
        institution = models.Institution(id=1, name="Test Institution")
        user = models.User(id=123, email="owner@example.com")
        class_ = models.Class(
            id=1,
            name="Test Class",
            institution_id=institution.id,
            api_key="test-key",
        )
        file = models.File(
            file_id="existing-file",
            name="slides.pdf",
            content_type="application/pdf",
            private=True,
            uploader_id=user.id,
        )
        source = models.LectureSlideSourceStoredObject(
            key="slides.pdf",
            original_filename="slides.pdf",
            content_type="application/pdf",
            content_length=16,
            openai_file=file,
        )
        deck = models.LectureSlideDeck(
            class_=class_,
            source_stored_object=source,
            uploader_id=user.id,
            display_name="slides.pdf",
            status="ready",
            slide_count=1,
        )
        session.add_all([institution, user, class_, file, source, deck])
        await session.commit()

    async with db.async_session() as session:
        result = await migration.upload_lecture_slide_sources_to_openai(session)

    assert result == migration.UploadLectureSlideSourcesToOpenAIResult()
    assert video_store.seen_keys == []


async def test_upload_lecture_slide_sources_to_openai_skips_without_video_store(
    db, config, monkeypatch
):
    monkeypatch.setattr(config, "video_store", None)

    async with db.async_session() as session:
        result = await migration.upload_lecture_slide_sources_to_openai(session)

    assert result == migration.UploadLectureSlideSourcesToOpenAIResult()


async def test_upload_lecture_slide_sources_to_openai_does_not_bump_without_upload(
    db, config, monkeypatch
):
    monkeypatch.setattr(config, "video_store", None)

    async with db.async_session() as session:
        institution = models.Institution(id=1, name="Test Institution")
        user = models.User(id=123, email="owner@example.com")
        class_ = models.Class(
            id=1,
            name="Test Class",
            institution_id=institution.id,
            api_key="test-key",
        )
        file = models.File(
            file_id="existing-openai-file",
            name="slides.pdf",
            content_type="application/pdf",
            private=True,
            uploader_id=user.id,
        )
        source = models.LectureSlideSourceStoredObject(
            key="slides.pdf",
            original_filename="slides.pdf",
            content_type="application/pdf",
            content_length=16,
            openai_file=file,
        )
        deck = models.LectureSlideDeck(
            class_=class_,
            source_stored_object=source,
            uploader_id=user.id,
            display_name="slides.pdf",
            status="ready",
            slide_count=1,
            context_version=4,
            lecture_slide_chat_available=True,
        )
        page = models.LectureSlidePage(
            lecture_slide_deck=deck,
            position=1,
            narration_text="Opening narration.",
        )
        assistant = models.Assistant(
            id=1,
            name="Slide Assistant",
            class_=class_,
            interaction_mode="LECTURE_SLIDES",
            version=3,
            lecture_slide_deck=deck,
            instructions="You are a slide assistant.",
            model="gpt-4o-mini",
            tools="[]",
            use_latex=False,
            use_image_descriptions=False,
            hide_prompt=False,
        )
        thread = models.Thread(
            id=1,
            name="Started Slide Lesson",
            version=3,
            thread_id="thread-started-slide",
            class_=class_,
            assistant=assistant,
            interaction_mode="LECTURE_SLIDES",
            lecture_slide_deck=deck,
            private=False,
            display_user_info=False,
            tools_available="[]",
        )
        run = models.Run(
            thread=thread,
            status=schemas.RunStatus.COMPLETED,
            tools_available="[]",
        )
        message = models.Message(
            thread=thread,
            run=run,
            output_index=1,
            role=schemas.MessageRole.USER,
            message_status=schemas.MessageStatus.COMPLETED,
        )
        session.add_all(
            [
                institution,
                user,
                class_,
                file,
                source,
                deck,
                page,
                assistant,
                thread,
                run,
                message,
            ]
        )
        await session.commit()
        old_deck_id = deck.id
        thread_id = thread.id
        assistant_id = assistant.id
        file_object_id = file.id

    async with db.async_session() as session:
        result = await migration.upload_lecture_slide_sources_to_openai(session)

    assert result == migration.UploadLectureSlideSourcesToOpenAIResult()

    async with db.async_session() as session:
        assistant = await session.get(models.Assistant, assistant_id)
        thread = await session.get(models.Thread, thread_id)
        assert assistant is not None
        assert thread is not None
        assert assistant.lecture_slide_deck_id == old_deck_id
        assert thread.lecture_slide_deck_id == old_deck_id


async def test_upload_lecture_slide_sources_to_openai_bumps_started_slide_lessons(
    db, config, monkeypatch
):
    video_store = FakeVideoStore({"slides.pdf": b"%PDF slide bytes"})
    files = FakeOpenAIFiles()
    monkeypatch.setattr(config, "video_store", SimpleNamespace(store=video_store))

    async def fake_get_openai_client_by_class_id(session, class_id: int):
        assert class_id == 1
        return SimpleNamespace(files=files)

    monkeypatch.setattr(
        lecture_slide_service,
        "get_openai_client_by_class_id",
        fake_get_openai_client_by_class_id,
    )

    async with db.async_session() as session:
        institution = models.Institution(id=1, name="Test Institution")
        user = models.User(id=123, email="owner@example.com")
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
            content_length=16,
        )
        deck = models.LectureSlideDeck(
            class_=class_,
            source_stored_object=source,
            uploader_id=user.id,
            display_name="slides.pdf",
            status="ready",
            slide_count=1,
            context_version=4,
            lecture_slide_chat_available=True,
        )
        page = models.LectureSlidePage(
            lecture_slide_deck=deck,
            position=1,
            narration_text="Opening narration.",
        )
        assistant = models.Assistant(
            id=1,
            name="Slide Assistant",
            class_=class_,
            interaction_mode="LECTURE_SLIDES",
            version=3,
            lecture_slide_deck=deck,
            instructions="You are a slide assistant.",
            model="gpt-4o-mini",
            tools="[]",
            use_latex=False,
            use_image_descriptions=False,
            hide_prompt=False,
        )
        thread = models.Thread(
            id=1,
            name="Started Slide Lesson",
            version=3,
            thread_id="thread-started-slide",
            class_=class_,
            assistant=assistant,
            interaction_mode="LECTURE_SLIDES",
            lecture_slide_deck=deck,
            private=False,
            display_user_info=False,
            tools_available="[]",
        )
        run = models.Run(
            thread=thread,
            status=schemas.RunStatus.COMPLETED,
            tools_available="[]",
        )
        message = models.Message(
            thread=thread,
            run=run,
            output_index=1,
            role=schemas.MessageRole.USER,
            message_status=schemas.MessageStatus.COMPLETED,
        )
        session.add_all(
            [
                institution,
                user,
                class_,
                source,
                deck,
                page,
                assistant,
                thread,
                run,
                message,
            ]
        )
        await session.commit()
        old_deck_id = deck.id
        source_id = source.id
        thread_id = thread.id
        assistant_id = assistant.id

    async with db.async_session() as session:
        result = await migration.upload_lecture_slide_sources_to_openai(session)

    assert result == migration.UploadLectureSlideSourcesToOpenAIResult(
        uploaded=1,
        version_bumped=1,
    )
    assert video_store.seen_keys == ["slides.pdf"]

    async with db.async_session() as session:
        source = await session.get(models.LectureSlideSourceStoredObject, source_id)
        assert source is not None
        assert source.openai_file_object_id is not None
        file_object_id = source.openai_file_object_id
        assistant = await session.get(models.Assistant, assistant_id)
        thread = await session.get(models.Thread, thread_id)
        assert assistant is not None
        assert thread is not None
        assert assistant.lecture_slide_deck_id != old_deck_id
        assert thread.lecture_slide_deck_id == old_deck_id

        cloned_deck = await models.LectureSlideDeck.get_by_id_with_processing_context(
            session,
            assistant.lecture_slide_deck_id,
        )
        assert cloned_deck is not None
        assert cloned_deck.source_lecture_slide_deck_id_snapshot == old_deck_id
        assert cloned_deck.source_stored_object is not None
        assert cloned_deck.source_stored_object.openai_file_object_id == file_object_id
        assert cloned_deck.context_version == 4
        assert cloned_deck.lecture_slide_chat_available is True
        assert [page.narration_text for page in cloned_deck.pages] == [
            "Opening narration."
        ]
