from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from pingpong import lecture_video_service, models, schemas
from pingpong.migrations import (
    m08_cleanup_invalid_lecture_video_schema_rows as migration,
)

pytestmark = pytest.mark.asyncio

DEFAULT_VOICE_ID = "voice-test-id"


def lecture_video_manifest() -> schemas.LectureVideoManifestV1:
    return schemas.LectureVideoManifestV1.model_validate(
        {
            "questions": [
                {
                    "type": "single_select",
                    "question_text": "Question 1",
                    "intro_text": "Intro 1",
                    "stop_offset_ms": 1000,
                    "options": [
                        {
                            "option_text": "Option A",
                            "post_answer_text": "Correct",
                            "continue_offset_ms": 1500,
                            "correct": True,
                        },
                        {
                            "option_text": "Option B",
                            "post_answer_text": "Try again",
                            "continue_offset_ms": 1800,
                            "correct": False,
                        },
                    ],
                }
            ]
        }
    )


async def add_lv_credentials(session, class_id: int) -> None:
    await models.ClassCredential.create(
        session,
        class_id,
        schemas.ClassCredentialPurpose.LECTURE_VIDEO_MANIFEST_GENERATION,
        "gemini-key",
        schemas.ClassCredentialProvider.GEMINI,
    )
    await models.ClassCredential.create(
        session,
        class_id,
        schemas.ClassCredentialPurpose.LECTURE_VIDEO_NARRATION_TTS,
        "elevenlabs-key",
        schemas.ClassCredentialProvider.ELEVENLABS,
    )


async def create_lecture_video(
    session,
    *,
    class_id: int,
    uploader_id: int,
    key: str,
    voice_id: str | None = DEFAULT_VOICE_ID,
    status: schemas.LectureVideoStatus = schemas.LectureVideoStatus.READY,
    with_manifest: bool = True,
) -> models.LectureVideo:
    stored_object = models.LectureVideoStoredObject(
        key=key,
        original_filename=key,
        content_type="video/mp4",
        content_length=128,
    )
    lecture_video = models.LectureVideo(
        class_id=class_id,
        stored_object=stored_object,
        status=status,
        uploader_id=uploader_id,
        voice_id=voice_id,
    )
    session.add(lecture_video)
    await session.flush()
    if with_manifest:
        await lecture_video_service.persist_manifest(
            session,
            lecture_video,
            lecture_video_manifest(),
            voice_id=voice_id,
            create_narration_placeholders=False,
        )
    return lecture_video


async def run_migration(session_factory, config):
    await config.authz.driver.init()
    async with (
        session_factory.async_session() as session,
        config.authz.driver.get_client() as authz_client,
    ):
        result = await migration.cleanup_invalid_lecture_video_schema_rows(
            session, authz_client
        )
        await session.commit()
        return result


async def grant_relations(config, grants):
    await config.authz.driver.init()
    async with config.authz.driver.get_client() as authz_client:
        await authz_client.write_safe(grant=grants)


async def test_disabled_class_removes_lv_rows_and_revokes_permissions(
    authz, db, config
):
    async with db.async_session() as session:
        institution = models.Institution(id=1, name="Test Institution")
        creator = models.User(id=101, email="creator@example.com")
        member = models.User(id=102, email="member@example.com")
        anonymous_user = models.User(id=103, email="anonymous-user@example.com")
        class_ = models.Class(id=1, name="Disabled LV Class", institution_id=1)
        session.add_all([institution, creator, member, anonymous_user, class_])
        await session.flush()
        lecture_video = await create_lecture_video(
            session,
            class_id=class_.id,
            uploader_id=creator.id,
            key="disabled-class.mp4",
        )
        assistant = models.Assistant(
            id=201,
            name="Lecture Assistant",
            class_id=class_.id,
            creator_id=creator.id,
            interaction_mode=schemas.InteractionMode.LECTURE_VIDEO,
            lecture_video_id=lecture_video.id,
            version=3,
            published=datetime.now(timezone.utc),
        )
        thread = models.Thread(
            id=301,
            name="Lecture Thread",
            class_id=class_.id,
            assistant_id=assistant.id,
            interaction_mode=schemas.InteractionMode.LECTURE_VIDEO,
            lecture_video_id=lecture_video.id,
            version=3,
            private=False,
            tools_available="[]",
            users=[member, anonymous_user],
        )
        anonymous_session = models.AnonymousSession(
            session_token="anon-session-token",
            thread=thread,
            user=anonymous_user,
        )

        session.add_all([assistant, thread, anonymous_session])
        await session.commit()

    await grant_relations(
        config,
        [
            ("class:1", "parent", f"lecture_video:{lecture_video.id}"),
            ("user:101", "owner", f"lecture_video:{lecture_video.id}"),
            ("class:1", "parent", "assistant:201"),
            ("user:101", "owner", "assistant:201"),
            ("class:1#member", "can_view", "assistant:201"),
            ("class:1", "parent", "thread:301"),
            ("user:102", "party", "thread:301"),
            ("user:102", "anonymous_party", "thread:301"),
            ("user:103", "anonymous_party", "thread:301"),
            ("anonymous_user:anon-session-token", "anonymous_party", "thread:301"),
            ("anonymous_user:anon-session-token", "can_upload_user_files", "class:1"),
            ("class:1#member", "can_view", "thread:301"),
        ],
    )

    result = await run_migration(db, config)

    assert result.lecture_video_disabled_classes == 1
    assert result.invalid_assistants == 1
    assert result.invalid_threads == 1
    assert result.lecture_videos_deleted == 1
    assert result.assistants_deleted == 1
    assert result.threads_deleted == 1

    async with db.async_session() as session:
        assert await session.get(models.Assistant, 201) is None
        assert await session.get(models.Thread, 301) is None
        assert await session.get(models.LectureVideo, lecture_video.id) is None

    revokes = {call for call in await authz.get_all_calls() if call[0] == "revoke"}
    assert (
        "revoke",
        "class:1",
        "parent",
        f"lecture_video:{lecture_video.id}",
    ) in revokes
    assert (
        "revoke",
        "user:101",
        "owner",
        f"lecture_video:{lecture_video.id}",
    ) in revokes
    assert ("revoke", "class:1", "parent", "assistant:201") in revokes
    assert ("revoke", "user:101", "owner", "assistant:201") in revokes
    assert ("revoke", "class:1#member", "can_view", "assistant:201") in revokes
    assert ("revoke", "class:1", "parent", "thread:301") in revokes
    assert ("revoke", "user:102", "party", "thread:301") in revokes
    assert ("revoke", "user:102", "anonymous_party", "thread:301") in revokes
    assert (
        "revoke",
        "anonymous_user:anon-session-token",
        "anonymous_party",
        "thread:301",
    ) in revokes
    assert (
        "revoke",
        "anonymous_user:anon-session-token",
        "can_upload_user_files",
        "class:1",
    ) in revokes
    assert ("revoke", "class:1#member", "can_view", "thread:301") in revokes


async def test_mismatch_thread_deleted_but_valid_pair_remains(authz, db, config):
    async with db.async_session() as session:
        institution = models.Institution(id=11, name="Test Institution")
        creator = models.User(id=111, email="creator@example.com")
        class_ = models.Class(id=11, name="Enabled LV Class", institution_id=11)
        session.add_all([institution, creator, class_])
        await session.flush()
        await add_lv_credentials(session, class_.id)

        matching_video = await create_lecture_video(
            session,
            class_id=class_.id,
            uploader_id=creator.id,
            key="matching.mp4",
        )
        thread_video = await create_lecture_video(
            session,
            class_id=class_.id,
            uploader_id=creator.id,
            key="mismatch-thread.mp4",
        )
        valid_video = await create_lecture_video(
            session,
            class_id=class_.id,
            uploader_id=creator.id,
            key="valid.mp4",
        )

        mismatched_assistant = models.Assistant(
            id=211,
            name="Mismatched Assistant",
            class_id=class_.id,
            creator_id=creator.id,
            interaction_mode=schemas.InteractionMode.LECTURE_VIDEO,
            lecture_video_id=matching_video.id,
            version=3,
        )
        valid_assistant = models.Assistant(
            id=212,
            name="Valid Assistant",
            class_id=class_.id,
            creator_id=creator.id,
            interaction_mode=schemas.InteractionMode.LECTURE_VIDEO,
            lecture_video_id=valid_video.id,
            version=3,
        )
        mismatched_thread = models.Thread(
            id=311,
            name="Mismatched Thread",
            class_id=class_.id,
            assistant_id=211,
            interaction_mode=schemas.InteractionMode.LECTURE_VIDEO,
            lecture_video_id=thread_video.id,
            version=3,
            private=True,
            tools_available="[]",
        )
        valid_thread = models.Thread(
            id=312,
            name="Valid Thread",
            class_id=class_.id,
            assistant_id=212,
            interaction_mode=schemas.InteractionMode.LECTURE_VIDEO,
            lecture_video_id=valid_video.id,
            version=3,
            private=True,
            tools_available="[]",
        )
        session.add_all(
            [
                mismatched_assistant,
                valid_assistant,
                mismatched_thread,
                valid_thread,
            ]
        )
        await session.commit()

    await grant_relations(config, [("class:11", "parent", "thread:311")])

    result = await run_migration(db, config)

    assert result.invalid_assistants == 0
    assert result.invalid_threads == 1
    assert result.lecture_videos_deleted == 1
    assert result.threads_deleted == 1
    assert result.assistants_deleted == 0

    async with db.async_session() as session:
        assert await session.get(models.Thread, 311) is None
        assert await session.get(models.Assistant, 211) is not None
        assert await session.get(models.LectureVideo, thread_video.id) is None
        assert await session.get(models.LectureVideo, matching_video.id) is not None
        assert await session.get(models.Thread, 312) is not None
        assert await session.get(models.Assistant, 212) is not None

    revokes = {call for call in await authz.get_all_calls() if call[0] == "revoke"}
    assert ("revoke", "class:11", "parent", "thread:311") in revokes


async def test_invalid_manifest_and_blank_voice_remove_assistants_and_threads(
    authz, db, config
):
    async with db.async_session() as session:
        institution = models.Institution(id=21, name="Test Institution")
        creator = models.User(id=121, email="creator@example.com")
        class_ = models.Class(id=21, name="Enabled LV Class", institution_id=21)
        session.add_all([institution, creator, class_])
        await session.flush()
        await add_lv_credentials(session, class_.id)

        invalid_manifest_video = models.LectureVideo(
            class_id=class_.id,
            stored_object=models.LectureVideoStoredObject(
                key="invalid-manifest.mp4",
                original_filename="invalid-manifest.mp4",
                content_type="video/mp4",
                content_length=128,
            ),
            status=schemas.LectureVideoStatus.READY,
            uploader_id=creator.id,
            voice_id=DEFAULT_VOICE_ID,
        )
        blank_voice_video = await create_lecture_video(
            session,
            class_id=class_.id,
            uploader_id=creator.id,
            key="blank-voice.mp4",
            voice_id="   ",
        )
        valid_video = await create_lecture_video(
            session,
            class_id=class_.id,
            uploader_id=creator.id,
            key="valid-stays.mp4",
        )
        session.add(invalid_manifest_video)
        await session.flush()
        question = models.LectureVideoQuestion(
            lecture_video_id=invalid_manifest_video.id,
            position=0,
            question_type=schemas.LectureVideoQuestionType.SINGLE_SELECT,
            question_text="Broken question",
            intro_text="Broken intro",
            stop_offset_ms=1000,
        )
        session.add(question)
        await session.flush()
        session.add(
            models.LectureVideoQuestionOption(
                question_id=question.id,
                position=0,
                option_text="Only option",
                post_answer_text="Nope",
                continue_offset_ms=1500,
            )
        )
        invalid_manifest_assistant = models.Assistant(
            id=221,
            name="Invalid Manifest Assistant",
            class_id=class_.id,
            creator_id=creator.id,
            interaction_mode=schemas.InteractionMode.LECTURE_VIDEO,
            lecture_video_id=invalid_manifest_video.id,
            version=3,
        )
        blank_voice_assistant = models.Assistant(
            id=222,
            name="Blank Voice Assistant",
            class_id=class_.id,
            creator_id=creator.id,
            interaction_mode=schemas.InteractionMode.LECTURE_VIDEO,
            lecture_video_id=blank_voice_video.id,
            version=3,
        )
        valid_assistant = models.Assistant(
            id=223,
            name="Valid Assistant",
            class_id=class_.id,
            creator_id=creator.id,
            interaction_mode=schemas.InteractionMode.LECTURE_VIDEO,
            lecture_video_id=valid_video.id,
            version=3,
        )
        session.add_all(
            [
                invalid_manifest_assistant,
                blank_voice_assistant,
                valid_assistant,
                models.Thread(
                    id=321,
                    name="Invalid Manifest Thread",
                    class_id=class_.id,
                    assistant_id=221,
                    interaction_mode=schemas.InteractionMode.LECTURE_VIDEO,
                    lecture_video_id=invalid_manifest_video.id,
                    version=3,
                    private=True,
                    tools_available="[]",
                ),
                models.Thread(
                    id=322,
                    name="Blank Voice Thread",
                    class_id=class_.id,
                    assistant_id=222,
                    interaction_mode=schemas.InteractionMode.LECTURE_VIDEO,
                    lecture_video_id=blank_voice_video.id,
                    version=3,
                    private=True,
                    tools_available="[]",
                ),
                models.Thread(
                    id=323,
                    name="Valid Thread",
                    class_id=class_.id,
                    assistant_id=223,
                    interaction_mode=schemas.InteractionMode.LECTURE_VIDEO,
                    lecture_video_id=valid_video.id,
                    version=3,
                    private=True,
                    tools_available="[]",
                ),
            ]
        )
        await session.commit()

    result = await run_migration(db, config)

    assert result.invalid_lecture_videos == 2
    assert result.invalid_assistants == 2
    assert result.invalid_threads == 2
    assert result.lecture_videos_deleted == 2
    assert result.assistants_deleted == 2
    assert result.threads_deleted == 2

    async with db.async_session() as session:
        assert await session.get(models.Assistant, 221) is None
        assert await session.get(models.Assistant, 222) is None
        assert await session.get(models.Thread, 321) is None
        assert await session.get(models.Thread, 322) is None
        assert await session.get(models.LectureVideo, invalid_manifest_video.id) is None
        assert await session.get(models.LectureVideo, blank_voice_video.id) is None
        assert await session.get(models.Assistant, 223) is not None
        assert await session.get(models.Thread, 323) is not None


async def test_non_lecture_rows_with_lecture_video_id_are_removed(authz, db, config):
    async with db.async_session() as session:
        institution = models.Institution(id=31, name="Test Institution")
        creator = models.User(id=131, email="creator@example.com")
        class_ = models.Class(id=31, name="Enabled LV Class", institution_id=31)
        session.add_all([institution, creator, class_])
        await session.flush()
        await add_lv_credentials(session, class_.id)

        lecture_video = await create_lecture_video(
            session,
            class_id=class_.id,
            uploader_id=creator.id,
            key="stray.mp4",
        )
        assistant = models.Assistant(
            id=231,
            name="Chat Assistant With LV",
            class_id=class_.id,
            creator_id=creator.id,
            interaction_mode=schemas.InteractionMode.CHAT,
            lecture_video_id=lecture_video.id,
            version=3,
        )
        thread = models.Thread(
            id=331,
            name="Chat Thread With LV",
            class_id=class_.id,
            interaction_mode=schemas.InteractionMode.CHAT,
            lecture_video_id=lecture_video.id,
            version=3,
            private=True,
            tools_available="[]",
        )
        session.add_all([assistant, thread])
        await session.commit()

    result = await run_migration(db, config)

    assert result.invalid_assistants == 1
    assert result.invalid_threads == 1
    assert result.lecture_videos_deleted == 1

    async with db.async_session() as session:
        assert await session.get(models.Assistant, 231) is None
        assert await session.get(models.Thread, 331) is None
        assert await session.get(models.LectureVideo, lecture_video.id) is None


async def test_cross_class_lecture_video_links_are_removed(db, config, authz):
    async with db.async_session() as session:
        institution = models.Institution(id=35, name="Test Institution")
        creator = models.User(id=135, email="creator@example.com")
        class_one = models.Class(id=35, name="Enabled LV Class One", institution_id=35)
        class_two = models.Class(id=36, name="Enabled LV Class Two", institution_id=35)
        session.add_all([institution, creator, class_one, class_two])
        await session.flush()
        await add_lv_credentials(session, class_one.id)
        await add_lv_credentials(session, class_two.id)

        class_one_video = await create_lecture_video(
            session,
            class_id=class_one.id,
            uploader_id=creator.id,
            key="class-one.mp4",
        )
        class_two_video = await create_lecture_video(
            session,
            class_id=class_two.id,
            uploader_id=creator.id,
            key="class-two.mp4",
        )

        cross_class_assistant = models.Assistant(
            id=235,
            name="Cross Class Assistant",
            class_id=class_one.id,
            creator_id=creator.id,
            interaction_mode=schemas.InteractionMode.LECTURE_VIDEO,
            lecture_video_id=class_two_video.id,
            version=3,
        )
        cross_class_thread = models.Thread(
            id=335,
            name="Cross Class Thread",
            class_id=class_one.id,
            assistant_id=235,
            interaction_mode=schemas.InteractionMode.LECTURE_VIDEO,
            lecture_video_id=class_two_video.id,
            version=3,
            private=True,
            tools_available="[]",
        )
        valid_assistant = models.Assistant(
            id=236,
            name="Valid Assistant",
            class_id=class_one.id,
            creator_id=creator.id,
            interaction_mode=schemas.InteractionMode.LECTURE_VIDEO,
            lecture_video_id=class_one_video.id,
            version=3,
        )
        valid_thread = models.Thread(
            id=336,
            name="Valid Thread",
            class_id=class_one.id,
            assistant_id=236,
            interaction_mode=schemas.InteractionMode.LECTURE_VIDEO,
            lecture_video_id=class_one_video.id,
            version=3,
            private=True,
            tools_available="[]",
        )

        session.add_all(
            [
                cross_class_assistant,
                cross_class_thread,
                valid_assistant,
                valid_thread,
            ]
        )
        await session.commit()

    result = await run_migration(db, config)

    assert result.invalid_lecture_videos == 0
    assert result.invalid_assistants == 1
    assert result.invalid_threads == 1
    assert result.lecture_videos_deleted == 1
    assert result.assistants_deleted == 1
    assert result.threads_deleted == 1

    async with db.async_session() as session:
        assert await session.get(models.Assistant, 235) is None
        assert await session.get(models.Thread, 335) is None
        assert await session.get(models.LectureVideo, class_two_video.id) is None
        assert await session.get(models.Assistant, 236) is not None
        assert await session.get(models.Thread, 336) is not None
        assert await session.get(models.LectureVideo, class_one_video.id) is not None


async def test_migration_is_db_only_and_does_not_delete_store_objects(
    authz, db, config, monkeypatch
):
    video_delete = AsyncMock()
    audio_delete = AsyncMock()
    monkeypatch.setattr(
        config,
        "video_store",
        SimpleNamespace(store=SimpleNamespace(delete=video_delete)),
    )
    monkeypatch.setattr(
        config,
        "lecture_video_audio_store",
        SimpleNamespace(store=SimpleNamespace(delete_file=audio_delete)),
    )

    async with db.async_session() as session:
        institution = models.Institution(id=41, name="Test Institution")
        creator = models.User(id=141, email="creator@example.com")
        class_ = models.Class(id=41, name="Disabled LV Class", institution_id=41)
        session.add_all([institution, creator, class_])
        await session.flush()
        lecture_video = await create_lecture_video(
            session,
            class_id=class_.id,
            uploader_id=creator.id,
            key="db-only.mp4",
        )
        assistant = models.Assistant(
            id=241,
            name="Lecture Assistant",
            class_id=class_.id,
            creator_id=creator.id,
            interaction_mode=schemas.InteractionMode.LECTURE_VIDEO,
            lecture_video_id=lecture_video.id,
            version=3,
        )
        thread = models.Thread(
            id=341,
            name="Lecture Thread",
            class_id=class_.id,
            assistant_id=assistant.id,
            interaction_mode=schemas.InteractionMode.LECTURE_VIDEO,
            lecture_video_id=lecture_video.id,
            version=3,
            private=True,
            tools_available="[]",
        )
        session.add_all([assistant, thread])
        await session.commit()

    await run_migration(db, config)

    video_delete.assert_not_awaited()
    audio_delete.assert_not_awaited()


async def test_unattached_invalid_lecture_video_is_deleted(db, config, authz):
    async with db.async_session() as session:
        institution = models.Institution(id=51, name="Test Institution")
        creator = models.User(id=151, email="creator@example.com")
        class_ = models.Class(id=51, name="Enabled LV Class", institution_id=51)
        session.add_all([institution, creator, class_])
        await session.flush()
        await add_lv_credentials(session, class_.id)

        orphaned_invalid_lecture_video = await create_lecture_video(
            session,
            class_id=class_.id,
            uploader_id=creator.id,
            key="orphan-invalid.mp4",
            status=schemas.LectureVideoStatus.UPLOADED,
            with_manifest=False,
        )
        await session.commit()

    await grant_relations(
        config,
        [
            (
                f"class:{class_.id}",
                "parent",
                f"lecture_video:{orphaned_invalid_lecture_video.id}",
            ),
            (
                f"user:{creator.id}",
                "owner",
                f"lecture_video:{orphaned_invalid_lecture_video.id}",
            ),
        ],
    )

    result = await run_migration(db, config)

    assert result.invalid_lecture_videos == 1
    assert result.lecture_videos_deleted == 1

    async with db.async_session() as session:
        assert (
            await session.get(models.LectureVideo, orphaned_invalid_lecture_video.id)
            is None
        )

    revokes = {call for call in await authz.get_all_calls() if call[0] == "revoke"}
    assert (
        "revoke",
        f"class:{class_.id}",
        "parent",
        f"lecture_video:{orphaned_invalid_lecture_video.id}",
    ) in revokes
    assert (
        "revoke",
        f"user:{creator.id}",
        "owner",
        f"lecture_video:{orphaned_invalid_lecture_video.id}",
    ) in revokes
