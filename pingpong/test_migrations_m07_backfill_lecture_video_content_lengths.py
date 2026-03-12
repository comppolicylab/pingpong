import pytest

from pingpong.config import LocalVideoStoreSettings
from pingpong.migrations.m07_backfill_lecture_video_content_lengths import (
    backfill_lecture_video_content_lengths,
)
from pingpong import models

pytestmark = pytest.mark.asyncio


async def test_backfill_lecture_video_content_lengths_updates_zero_length_rows(
    db, config, monkeypatch, tmp_path
):
    monkeypatch.setattr(
        config,
        "video_store",
        LocalVideoStoreSettings(type="local", save_target=str(tmp_path)),
    )
    video_bytes = b"legacy-video-bytes"

    async with db.async_session() as session:
        institution = models.Institution(id=1, name="Test Institution")
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
        )
        session.add_all([institution, class_, lecture_video])
        await session.commit()
        stored_object_id = stored_object.id

    (tmp_path / "legacy-video.mp4").write_bytes(video_bytes)

    async with db.async_session() as session:
        updated = await backfill_lecture_video_content_lengths(session)
        await session.commit()

    assert updated == 1

    async with db.async_session() as session:
        stored_object = await session.get(
            models.LectureVideoStoredObject, stored_object_id
        )

    assert stored_object is not None
    assert stored_object.content_length == len(video_bytes)
