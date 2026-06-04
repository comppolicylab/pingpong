from types import SimpleNamespace

import pytest

from pingpong import models
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
        migration, "get_openai_client_by_class_id", fake_get_openai_client_by_class_id
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
