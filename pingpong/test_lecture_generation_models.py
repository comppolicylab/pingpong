import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

from pingpong import models, schemas


pytestmark = pytest.mark.asyncio


async def _create_class(session):
    institution = models.Institution(id=1, name="Test Institution")
    class_ = models.Class(
        id=1,
        name="Test Class",
        institution_id=institution.id,
        api_key="test-key",
    )
    session.add_all([institution, class_])
    await session.flush()
    return class_


async def _create_target_class(session):
    class_ = models.Class(
        id=2,
        name="Target Class",
        institution_id=1,
        api_key="target-key",
    )
    session.add(class_)
    await session.flush()
    return class_


async def test_uploaded_lecture_video_create_requires_stored_object(db):
    async with db.async_session() as session:
        class_ = await _create_class(session)

        with pytest.raises(ValueError, match="stored_object_id"):
            await models.LectureVideo.create(
                session,
                class_id=class_.id,
                user_id=None,
            )


async def test_uploaded_lecture_video_create_uses_stored_object(db):
    async with db.async_session() as session:
        class_ = await _create_class(session)
        stored_object = await models.LectureVideoStoredObject.create(
            session,
            key="lecture-video.mp4",
            original_filename="lecture-video.mp4",
            content_type="video/mp4",
            content_length=123,
        )

        lecture_video = await models.LectureVideo.create(
            session,
            class_id=class_.id,
            stored_object_id=stored_object.id,
            user_id=None,
        )

        assert lecture_video.stored_object_id == stored_object.id
        assert (
            lecture_video.source_kind == schemas.LectureVideoSourceKind.UPLOADED_VIDEO
        )
        assert (
            lecture_video.playback_kind == schemas.LectureVideoPlaybackKind.VIDEO_FILE
        )


async def test_generated_lecture_video_allows_null_stored_object_and_media_roles(db):
    async with db.async_session() as session:
        class_ = await _create_class(session)
        lecture_video = await models.LectureVideo.create(
            session,
            class_id=class_.id,
            stored_object_id=None,
            user_id=None,
            source_kind=schemas.LectureVideoSourceKind.GENERATED_SLIDE_DECK,
            playback_kind=schemas.LectureVideoPlaybackKind.HLS_AUDIO,
            duration_ms=42_000,
            status=schemas.LectureVideoStatus.PROCESSING,
        )
        source_deck_object = await models.LectureVideoMediaStoredObject.create(
            session,
            key="lecture-generation/source.pdf",
            original_filename="source.pdf",
            content_type="application/pdf",
            content_length=1000,
        )
        source_deck = await models.LectureVideoMedia.create(
            session,
            lecture_video_id=lecture_video.id,
            stored_object_id=source_deck_object.id,
            role=schemas.LectureVideoMediaRole.SOURCE_DECK,
        )
        slide_image_object = await models.LectureVideoMediaStoredObject.create(
            session,
            key="lecture-generation/slide-1.png",
            original_filename="slide-1.png",
            content_type="image/png",
            content_length=2000,
        )
        slide_image = await models.LectureVideoMedia.create(
            session,
            lecture_video_id=lecture_video.id,
            stored_object_id=slide_image_object.id,
            role=schemas.LectureVideoMediaRole.SLIDE_IMAGE,
            position=0,
        )
        playlist_object = await models.LectureVideoMediaStoredObject.create(
            session,
            key="lecture-generation/audio.m3u8",
            original_filename=None,
            content_type="application/vnd.apple.mpegurl",
            content_length=3000,
        )
        playlist = await models.LectureVideoMedia.create(
            session,
            lecture_video_id=lecture_video.id,
            stored_object_id=playlist_object.id,
            role=schemas.LectureVideoMediaRole.HLS_PLAYLIST,
        )
        segment_object = await models.LectureVideoMediaStoredObject.create(
            session,
            key="lecture-generation/audio-000.ts",
            original_filename=None,
            content_type="video/mp2t",
            content_length=4000,
        )
        segment = await models.LectureVideoMedia.create(
            session,
            lecture_video_id=lecture_video.id,
            stored_object_id=segment_object.id,
            role=schemas.LectureVideoMediaRole.HLS_SEGMENT,
            position=0,
        )
        lecture_video.source_deck_media_id = source_deck.id
        lecture_video.hls_playlist_media_id = playlist.id
        slide = models.LectureVideoSlide(
            lecture_video_id=lecture_video.id,
            position=0,
            image_media_id=slide_image.id,
            source_page_number=1,
            extracted_text="Slide text",
            speaker_notes="Speaker notes",
            narration_text="Narration text",
            start_offset_ms=0,
            end_offset_ms=42_000,
        )
        session.add(slide)
        await session.commit()

    async with db.async_session() as session:
        loaded = await models.LectureVideo.get_by_id_with_copy_context(
            session, lecture_video.id
        )

        assert loaded is not None
        assert loaded.stored_object_id is None
        assert loaded.source_kind == schemas.LectureVideoSourceKind.GENERATED_SLIDE_DECK
        assert loaded.playback_kind == schemas.LectureVideoPlaybackKind.HLS_AUDIO
        assert loaded.duration_ms == 42_000
        assert {media.role for media in loaded.media_items} == {
            schemas.LectureVideoMediaRole.SOURCE_DECK,
            schemas.LectureVideoMediaRole.SLIDE_IMAGE,
            schemas.LectureVideoMediaRole.HLS_PLAYLIST,
            schemas.LectureVideoMediaRole.HLS_SEGMENT,
        }
        assert loaded.source_deck_media_id == source_deck.id
        assert loaded.hls_playlist_media_id == playlist.id
        assert (
            loaded.source_deck_media.stored_object.key
            == "lecture-generation/source.pdf"
        )
        assert [slide.position for slide in loaded.slides] == [0]
        assert segment.id is not None


async def test_lecture_video_slide_position_is_unique_per_lecture_video(db):
    async with db.async_session() as session:
        class_ = await _create_class(session)
        lecture_video = await models.LectureVideo.create(
            session,
            class_id=class_.id,
            stored_object_id=None,
            user_id=None,
            source_kind=schemas.LectureVideoSourceKind.GENERATED_SLIDE_DECK,
            playback_kind=schemas.LectureVideoPlaybackKind.HLS_AUDIO,
        )
        first_image_object = await models.LectureVideoMediaStoredObject.create(
            session,
            key="lecture-generation/unique-slide-1.png",
            original_filename="slide-1.png",
            content_type="image/png",
            content_length=100,
        )
        first_image = await models.LectureVideoMedia.create(
            session,
            lecture_video_id=lecture_video.id,
            stored_object_id=first_image_object.id,
            role=schemas.LectureVideoMediaRole.SLIDE_IMAGE,
            position=0,
        )
        second_image_object = await models.LectureVideoMediaStoredObject.create(
            session,
            key="lecture-generation/unique-slide-2.png",
            original_filename="slide-2.png",
            content_type="image/png",
            content_length=100,
        )
        second_image = await models.LectureVideoMedia.create(
            session,
            lecture_video_id=lecture_video.id,
            stored_object_id=second_image_object.id,
            role=schemas.LectureVideoMediaRole.SLIDE_IMAGE,
            position=1,
        )
        session.add_all(
            [
                models.LectureVideoSlide(
                    lecture_video_id=lecture_video.id,
                    position=0,
                    image_media_id=first_image.id,
                ),
                models.LectureVideoSlide(
                    lecture_video_id=lecture_video.id,
                    position=0,
                    image_media_id=second_image.id,
                ),
            ]
        )

        with pytest.raises(IntegrityError):
            await session.commit()


async def test_generated_media_stored_object_can_be_shared_across_snapshots(db):
    async with db.async_session() as session:
        class_ = await _create_class(session)
        first_video = await models.LectureVideo.create(
            session,
            class_id=class_.id,
            stored_object_id=None,
            user_id=None,
            source_kind=schemas.LectureVideoSourceKind.GENERATED_SLIDE_DECK,
            playback_kind=schemas.LectureVideoPlaybackKind.HLS_AUDIO,
        )
        second_video = await models.LectureVideo.create(
            session,
            class_id=class_.id,
            stored_object_id=None,
            user_id=None,
            source_kind=schemas.LectureVideoSourceKind.GENERATED_SLIDE_DECK,
            playback_kind=schemas.LectureVideoPlaybackKind.HLS_AUDIO,
            source_lecture_video_id_snapshot=first_video.id,
        )
        stored_object = await models.LectureVideoMediaStoredObject.create(
            session,
            key="lecture-generation/shared-slide.png",
            original_filename="shared-slide.png",
            content_type="image/png",
            content_length=100,
        )
        first_media = await models.LectureVideoMedia.create(
            session,
            lecture_video_id=first_video.id,
            stored_object_id=stored_object.id,
            role=schemas.LectureVideoMediaRole.SLIDE_IMAGE,
            position=0,
        )
        second_media = await models.LectureVideoMedia.create(
            session,
            lecture_video_id=second_video.id,
            stored_object_id=stored_object.id,
            role=schemas.LectureVideoMediaRole.SLIDE_IMAGE,
            position=0,
        )
        await session.commit()

    async with db.async_session() as session:
        loaded = await session.scalar(
            select(models.LectureVideoMediaStoredObject)
            .where(models.LectureVideoMediaStoredObject.id == stored_object.id)
            .options(selectinload(models.LectureVideoMediaStoredObject.media_items))
        )

        assert loaded is not None
        assert {media.id for media in loaded.media_items} == {
            first_media.id,
            second_media.id,
        }


async def test_clone_generated_lecture_video_reuses_blobs_with_new_media_rows(db):
    async with db.async_session() as session:
        class_ = await _create_class(session)
        target_class = await _create_target_class(session)
        lecture_video = await models.LectureVideo.create(
            session,
            class_id=class_.id,
            stored_object_id=None,
            user_id=None,
            source_kind=schemas.LectureVideoSourceKind.GENERATED_SLIDE_DECK,
            playback_kind=schemas.LectureVideoPlaybackKind.HLS_AUDIO,
            duration_ms=42_000,
        )
        source_deck_object = await models.LectureVideoMediaStoredObject.create(
            session,
            key="lecture-generation/clone-source.pdf",
            original_filename="source.pdf",
            content_type="application/pdf",
            content_length=1000,
        )
        source_deck = await models.LectureVideoMedia.create(
            session,
            lecture_video_id=lecture_video.id,
            stored_object_id=source_deck_object.id,
            role=schemas.LectureVideoMediaRole.SOURCE_DECK,
        )
        slide_image_object = await models.LectureVideoMediaStoredObject.create(
            session,
            key="lecture-generation/clone-slide-1.png",
            original_filename="slide-1.png",
            content_type="image/png",
            content_length=2000,
        )
        slide_image = await models.LectureVideoMedia.create(
            session,
            lecture_video_id=lecture_video.id,
            stored_object_id=slide_image_object.id,
            role=schemas.LectureVideoMediaRole.SLIDE_IMAGE,
            position=0,
        )
        playlist_object = await models.LectureVideoMediaStoredObject.create(
            session,
            key="lecture-generation/clone-audio.m3u8",
            original_filename=None,
            content_type="application/vnd.apple.mpegurl",
            content_length=3000,
        )
        playlist = await models.LectureVideoMedia.create(
            session,
            lecture_video_id=lecture_video.id,
            stored_object_id=playlist_object.id,
            role=schemas.LectureVideoMediaRole.HLS_PLAYLIST,
        )
        lecture_video.source_deck_media_id = source_deck.id
        lecture_video.hls_playlist_media_id = playlist.id
        session.add(
            models.LectureVideoSlide(
                lecture_video_id=lecture_video.id,
                position=0,
                image_media_id=slide_image.id,
                source_page_number=1,
                extracted_text="Slide text",
                speaker_notes="Speaker notes",
                narration_text="Narration text",
                start_offset_ms=0,
                end_offset_ms=42_000,
            )
        )
        source_lecture_video_id = lecture_video.id
        target_class_id = target_class.id
        source_deck_id = source_deck.id
        slide_image_id = slide_image.id
        playlist_id = playlist.id
        source_deck_object_id = source_deck_object.id
        slide_image_object_id = slide_image_object.id
        playlist_object_id = playlist_object.id
        await session.commit()

    async with db.async_session() as session:
        source_lecture_video = await models.LectureVideo.get_by_id_with_copy_context(
            session, source_lecture_video_id
        )
        cloned = await models.LectureVideo.clone_for_class(
            session, source_lecture_video, target_class_id
        )
        cloned_id = cloned.id
        await session.commit()

    async with db.async_session() as session:
        cloned = await models.LectureVideo.get_by_id_with_copy_context(
            session, cloned_id
        )

        assert cloned is not None
        assert cloned.source_lecture_video_id_snapshot == source_lecture_video_id
        assert cloned.source_deck_media_id != source_deck_id
        assert cloned.hls_playlist_media_id != playlist_id
        assert cloned.source_deck_media.stored_object_id == source_deck_object_id
        assert cloned.hls_playlist_media.stored_object_id == playlist_object_id
        assert cloned.slides[0].image_media_id != slide_image_id
        assert cloned.slides[0].image_media.stored_object_id == slide_image_object_id
