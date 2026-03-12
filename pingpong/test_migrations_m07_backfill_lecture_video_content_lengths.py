from types import SimpleNamespace

import pytest

from pingpong import models
from pingpong.config import LocalVideoStoreSettings
from pingpong.migrations import m07_backfill_lecture_video_content_lengths as migration
from pingpong.schemas import VideoMetadata

pytestmark = pytest.mark.asyncio


async def test_backfill_lecture_video_content_lengths_updates_zero_length_rows(
    authz, db, config, monkeypatch, tmp_path
):
    monkeypatch.setattr(
        config,
        "video_store",
        LocalVideoStoreSettings(type="local", save_target=str(tmp_path)),
    )
    video_bytes = b"legacy-video-bytes"

    async with db.async_session() as session:
        institution = models.Institution(id=1, name="Test Institution")
        user = models.User(id=123, email="lecture-owner@example.com")
        class_ = models.Class(
            id=1,
            name="Test Class",
            institution_id=institution.id,
            api_key="test-key",
        )
        stored_object = models.LectureVideoStoredObject(
            key="legacy-video.mp4",
            original_filename="legacy-video.mp4",
            content_type="video/mp4",
            content_length=0,
        )
        lecture_video = models.LectureVideo(
            class_id=class_.id,
            stored_object=stored_object,
            status="uploaded",
            uploader_id=user.id,
        )
        session.add_all([institution, user, class_, lecture_video])
        await session.commit()
        stored_object_id = stored_object.id

    (tmp_path / "legacy-video.mp4").write_bytes(video_bytes)

    await config.authz.driver.init()
    async with db.async_session() as session:
        async with config.authz.driver.get_client() as authz_client:
            updated = await migration.backfill_lecture_video_content_lengths(
                session, authz_client
            )
            await session.commit()

    assert updated == 1

    async with db.async_session() as session:
        stored_object = await session.get(
            models.LectureVideoStoredObject, stored_object_id
        )

    assert stored_object is not None
    assert stored_object.content_length == len(video_bytes)
    assert await authz.get_all_calls() == [
        ("grant", "class:1", "parent", "lecture_video:1"),
        ("grant", "user:123", "owner", "lecture_video:1"),
    ]


async def test_backfill_lecture_video_content_lengths_batches_and_checkpoints(
    db, config, monkeypatch
):
    monkeypatch.setattr(migration, "_BATCH_SIZE", 2)

    seen_keys = []
    content_lengths = {
        "batch-1.mp4": 101,
        "batch-2.mp4": 0,
        "batch-3.mp4": 103,
        "batch-4.mp4": 104,
        "batch-5.mp4": 105,
    }

    class FakeVideoStore:
        async def get_video_metadata(self, key: str) -> VideoMetadata:
            seen_keys.append(key)
            return VideoMetadata(
                content_length=content_lengths[key],
                content_type="video/mp4",
            )

    monkeypatch.setattr(config, "video_store", SimpleNamespace(store=FakeVideoStore()))

    async with db.async_session() as session:
        institution = models.Institution(id=1, name="Test Institution")
        class_ = models.Class(
            id=1,
            name="Test Class",
            institution_id=institution.id,
            api_key="test-key",
        )
        lecture_videos = []
        for i in range(1, 6):
            lecture_videos.append(
                models.LectureVideo(
                    class_id=class_.id,
                    stored_object=models.LectureVideoStoredObject(
                        key=f"batch-{i}.mp4",
                        original_filename=f"batch-{i}.mp4",
                        content_type="video/mp4",
                        content_length=0,
                    ),
                    status="uploaded",
                )
            )
        session.add_all([institution, class_, *lecture_videos])
        await session.commit()

    async with db.async_session() as session:
        commit_calls = 0
        original_commit = session.commit

        async def counted_commit() -> None:
            nonlocal commit_calls
            commit_calls += 1
            await original_commit()

        monkeypatch.setattr(session, "commit", counted_commit)
        updated = await migration.backfill_lecture_video_content_lengths(session)

    assert updated == 4
    assert commit_calls == 3
    assert seen_keys == [
        "batch-1.mp4",
        "batch-2.mp4",
        "batch-3.mp4",
        "batch-4.mp4",
        "batch-5.mp4",
    ]

    async with db.async_session() as session:
        stored_objects = (
            (
                await session.execute(
                    models.LectureVideoStoredObject.__table__.select().order_by(
                        models.LectureVideoStoredObject.id.asc()
                    )
                )
            )
            .mappings()
            .all()
        )

    assert [stored_object["content_length"] for stored_object in stored_objects] == [
        101,
        0,
        103,
        104,
        105,
    ]
