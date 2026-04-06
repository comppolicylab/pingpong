import pytest
from sqlalchemy import inspect, select

from pingpong import models, schemas
import pingpong.merge as merge_module

pytestmark = pytest.mark.asyncio


async def _create_user(session, user_id: int, email: str) -> models.User:
    user = models.User(id=user_id, email=email, state=schemas.UserState.VERIFIED)
    session.add(user)
    await session.flush()
    return user


async def test_merge_preserves_lecture_video_user_references(db):
    async with db.async_session() as session:
        old_user = await _create_user(session, 3101, "old-lv@example.com")
        new_user = await _create_user(session, 3102, "new-lv@example.com")

        class_ = models.Class(id=901, name="Lecture Video Class", private=False)
        session.add(class_)
        await session.flush()

        stored_object = await models.LectureVideoStoredObject.create(
            session,
            key="merge-lv.mp4",
            original_filename="merge-lv.mp4",
            content_type="video/mp4",
            content_length=123,
        )
        lecture_video = await models.LectureVideo.create(
            session,
            class_id=class_.id,
            stored_object_id=stored_object.id,
            user_id=old_user.id,
            display_name="Merge LV",
        )

        thread = models.Thread(
            id=902,
            class_id=class_.id,
            thread_id="merge-lv-thread",
            version=3,
            interaction_mode=schemas.InteractionMode.LECTURE_VIDEO,
            lecture_video_id=lecture_video.id,
            private=False,
        )
        session.add(thread)
        await session.flush()

        session.add(
            models.LectureVideoThreadState(
                thread_id=thread.id,
                state=schemas.LectureVideoSessionState.PLAYING,
                last_known_offset_ms=4567,
                furthest_offset_ms=4567,
                version=2,
                controller_session_id="controller-session",
                controller_user_id=old_user.id,
            )
        )
        session.add(
            models.LectureVideoInteraction(
                thread_id=thread.id,
                event_index=1,
                actor_user_id=old_user.id,
                event_type=schemas.LectureVideoInteractionEventType.SESSION_INITIALIZED,
            )
        )
        await session.flush()

        await merge_module.merge_db_operations(session, new_user.id, old_user.id)
        await session.flush()

        lecture_video = await models.LectureVideo.get_by_id(session, lecture_video.id)
        assert lecture_video is not None
        assert lecture_video.uploader_id == new_user.id

        thread_state = (
            await models.LectureVideoThreadState.get_by_thread_id_with_context(
                session, thread.id
            )
        )
        assert thread_state is not None
        assert thread_state.controller_user_id == new_user.id

        interaction = await session.scalar(
            select(models.LectureVideoInteraction).where(
                models.LectureVideoInteraction.thread_id == thread.id,
                models.LectureVideoInteraction.event_index == 1,
            )
        )
        assert interaction is not None
        assert interaction.actor_user_id == new_user.id


async def test_lecture_video_manifest_is_deferred_for_generic_loads(db):
    async with db.async_session() as session:
        class_ = models.Class(name="Deferred Lecture Video Class", private=False)
        session.add(class_)
        await session.flush()

        stored_object = await models.LectureVideoStoredObject.create(
            session,
            key="deferred-lv.mp4",
            original_filename="deferred-lv.mp4",
            content_type="video/mp4",
            content_length=321,
        )
        lecture_video = await models.LectureVideo.create(
            session,
            class_id=class_.id,
            stored_object_id=stored_object.id,
            user_id=None,
            manifest_data={"version": 2, "word_level_transcription": [{"word": "hi"}]},
            manifest_version=2,
            lecture_video_chat_available=True,
        )
        lecture_video_id = lecture_video.id
        await session.commit()

    async with db.async_session() as session:
        generic_loaded = await models.LectureVideo.get_by_id(session, lecture_video_id)
        assert generic_loaded is not None
        assert "manifest_data" in inspect(generic_loaded).unloaded

        copy_context_loaded = await models.LectureVideo.get_by_id_with_copy_context(
            session, lecture_video_id
        )
        assert copy_context_loaded is not None
        assert "manifest_data" not in inspect(copy_context_loaded).unloaded
        assert copy_context_loaded.manifest_data is not None


async def test_thread_lecture_video_context_preloads_manifest_data(db):
    async with db.async_session() as session:
        class_ = models.Class(name="Thread Lecture Video Class", private=False)
        session.add(class_)
        await session.flush()

        stored_object = await models.LectureVideoStoredObject.create(
            session,
            key="thread-lv.mp4",
            original_filename="thread-lv.mp4",
            content_type="video/mp4",
            content_length=654,
        )
        lecture_video = await models.LectureVideo.create(
            session,
            class_id=class_.id,
            stored_object_id=stored_object.id,
            user_id=None,
            manifest_data={"version": 2, "word_level_transcription": [{"word": "hi"}]},
            manifest_version=2,
            lecture_video_chat_available=True,
        )
        thread = models.Thread(
            class_id=class_.id,
            thread_id="thread_with_manifest_context",
            version=3,
            interaction_mode=schemas.InteractionMode.LECTURE_VIDEO,
            lecture_video_id=lecture_video.id,
            private=False,
        )
        session.add(thread)
        await session.commit()
        thread_id = thread.id
        class_id = class_.id

    async with db.async_session() as session:
        loaded_thread = (
            await models.Thread.get_by_id_for_class_with_lecture_video_context(
                session, class_id, thread_id
            )
        )
        assert loaded_thread is not None
        assert loaded_thread.lecture_video is not None
        assert "manifest_data" not in inspect(loaded_thread.lecture_video).unloaded
        assert loaded_thread.lecture_video.manifest_data is not None
