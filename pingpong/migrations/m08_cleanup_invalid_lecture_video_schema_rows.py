import logging
from dataclasses import dataclass

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import load_only, selectinload

import pingpong.models as models
import pingpong.schemas as schemas
from pingpong.authz import AuthzClient
from pingpong.lecture_video_service import lecture_video_grants

logger = logging.getLogger(__name__)

_BATCH_SIZE = 100


@dataclass
class CleanupInvalidLectureVideoSchemaRowsResult:
    lecture_video_disabled_classes: int = 0
    invalid_lecture_videos: int = 0
    invalid_assistants: int = 0
    invalid_threads: int = 0
    lecture_videos_deleted: int = 0
    threads_deleted: int = 0
    assistants_deleted: int = 0
    revokes_attempted: int = 0


async def _get_lecture_video_enabled_class_ids(session: AsyncSession) -> set[int]:
    configured_purposes = (
        await session.execute(
            select(
                models.ClassCredential.class_id,
                models.ClassCredential.purpose,
            ).where(
                models.ClassCredential.purpose.in_(
                    [
                        schemas.ClassCredentialPurpose.LECTURE_VIDEO_MANIFEST_GENERATION,
                        schemas.ClassCredentialPurpose.LECTURE_VIDEO_NARRATION_TTS,
                    ]
                )
            )
        )
    ).all()

    purposes_by_class_id: dict[int, set[schemas.ClassCredentialPurpose]] = {}
    for class_id, purpose in configured_purposes:
        purposes_by_class_id.setdefault(class_id, set()).add(purpose)

    return {
        class_id
        for class_id, purposes in purposes_by_class_id.items()
        if schemas.ClassCredentialPurpose.LECTURE_VIDEO_MANIFEST_GENERATION in purposes
        and schemas.ClassCredentialPurpose.LECTURE_VIDEO_NARRATION_TTS in purposes
    }


async def _load_lecture_videos(
    session: AsyncSession, lecture_video_ids: set[int] | None = None
) -> dict[int, models.LectureVideo]:
    if lecture_video_ids is not None and not lecture_video_ids:
        return {}

    stmt = select(models.LectureVideo).options(
        load_only(
            models.LectureVideo.id,
            models.LectureVideo.class_id,
            models.LectureVideo.status,
            models.LectureVideo.voice_id,
            models.LectureVideo.stored_object_id,
        ),
        selectinload(models.LectureVideo.questions)
        .load_only(
            models.LectureVideoQuestion.id,
            models.LectureVideoQuestion.question_type,
            models.LectureVideoQuestion.stop_offset_ms,
        )
        .selectinload(models.LectureVideoQuestion.options)
        .load_only(
            models.LectureVideoQuestionOption.id,
            models.LectureVideoQuestionOption.continue_offset_ms,
        ),
    )
    if lecture_video_ids is not None:
        stmt = stmt.where(models.LectureVideo.id.in_(sorted(lecture_video_ids)))

    result = await session.execute(stmt)
    lecture_videos = result.scalars().all()
    return {lecture_video.id: lecture_video for lecture_video in lecture_videos}


async def _load_referenced_lecture_videos(
    session: AsyncSession, lecture_video_ids: set[int]
) -> dict[int, models.LectureVideo]:
    return await _load_lecture_videos(session, lecture_video_ids)


async def _load_all_lecture_videos(
    session: AsyncSession,
) -> dict[int, models.LectureVideo]:
    return await _load_lecture_videos(session)


async def _get_correct_option_counts(
    session: AsyncSession, question_ids: set[int]
) -> dict[int, int]:
    if not question_ids:
        return {}

    rows = (
        await session.execute(
            select(
                models.lecture_video_question_single_select_correct_option_association.c.question_id,
                func.count(
                    models.lecture_video_question_single_select_correct_option_association.c.option_id
                ),
            )
            .where(
                models.lecture_video_question_single_select_correct_option_association.c.question_id.in_(
                    sorted(question_ids)
                )
            )
            .group_by(
                models.lecture_video_question_single_select_correct_option_association.c.question_id
            )
        )
    ).all()
    return {question_id: int(count) for question_id, count in rows}


def _is_valid_lecture_video(
    lecture_video: models.LectureVideo,
    correct_option_counts: dict[int, int],
) -> bool:
    if lecture_video.status != schemas.LectureVideoStatus.READY:
        return False

    if not (lecture_video.voice_id or "").strip():
        return False

    if not lecture_video.questions:
        return False

    for question in lecture_video.questions:
        if question.question_type != schemas.LectureVideoQuestionType.SINGLE_SELECT:
            return False
        if question.stop_offset_ms < 0:
            return False
        if len(question.options) < 2:
            return False
        if correct_option_counts.get(question.id, 0) != 1:
            return False
        for option in question.options:
            if option.continue_offset_ms < 0:
                return False

    return True


def _assistant_revokes(assistant: models.Assistant) -> list[tuple[str, str, str]]:
    revokes = [
        (f"class:{assistant.class_id}", "parent", f"assistant:{assistant.id}"),
        (f"user:{assistant.creator_id}", "owner", f"assistant:{assistant.id}"),
    ]
    if assistant.published:
        revokes.append(
            (
                f"class:{assistant.class_id}#member",
                "can_view",
                f"assistant:{assistant.id}",
            )
        )
    return revokes


def _thread_revokes(thread: models.Thread) -> list[tuple[str, str, str]]:
    target = f"thread:{thread.id}"
    revokes = [(f"class:{thread.class_id}", "parent", target)]
    revokes.extend((f"user:{user.id}", "party", target) for user in thread.users)
    revokes.extend(
        (f"user:{user.id}", "anonymous_party", target) for user in thread.users
    )
    revokes.extend(
        (
            f"anonymous_user:{anonymous_session.session_token}",
            "anonymous_party",
            target,
        )
        for anonymous_session in thread.anonymous_sessions
    )
    revokes.extend(
        (
            f"anonymous_user:{anonymous_session.session_token}",
            "can_upload_user_files",
            f"class:{thread.class_id}",
        )
        for anonymous_session in thread.anonymous_sessions
    )
    if not thread.private:
        revokes.append((f"class:{thread.class_id}#member", "can_view", target))
    return revokes


async def _delete_thread_db_only(
    session: AsyncSession,
    authz: AuthzClient,
    thread: models.Thread,
) -> int:
    revokes = _thread_revokes(thread)
    await thread.delete(session)
    await authz.write_safe(revoke=revokes)
    return len(revokes)


async def _delete_assistant_db_only(
    session: AsyncSession,
    authz: AuthzClient,
    assistant: models.Assistant,
) -> int:
    await session.execute(
        delete(models.code_interpreter_file_assistant_association).where(
            models.code_interpreter_file_assistant_association.c.assistant_id
            == assistant.id
        )
    )
    await session.execute(
        delete(models.mcp_server_tool_assistant_association).where(
            models.mcp_server_tool_assistant_association.c.assistant_id == assistant.id
        )
    )
    await models.Assistant.delete(session, assistant.id)

    revokes = _assistant_revokes(assistant)
    await authz.write_safe(revoke=revokes)
    return len(revokes)


async def _delete_lecture_video_db_only(
    session: AsyncSession,
    authz: AuthzClient,
    lecture_video: models.LectureVideo,
) -> int:
    question_ids = list(
        (
            await session.scalars(
                select(models.LectureVideoQuestion.id).where(
                    models.LectureVideoQuestion.lecture_video_id == lecture_video.id
                )
            )
        ).all()
    )

    intro_narration_ids = list(
        (
            await session.scalars(
                select(models.LectureVideoQuestion.intro_narration_id).where(
                    models.LectureVideoQuestion.lecture_video_id == lecture_video.id,
                    models.LectureVideoQuestion.intro_narration_id.is_not(None),
                )
            )
        ).all()
    )
    post_narration_ids = list(
        (
            await session.scalars(
                select(models.LectureVideoQuestionOption.post_narration_id)
                .join(
                    models.LectureVideoQuestion,
                    models.LectureVideoQuestion.id
                    == models.LectureVideoQuestionOption.question_id,
                )
                .where(
                    models.LectureVideoQuestion.lecture_video_id == lecture_video.id,
                    models.LectureVideoQuestionOption.post_narration_id.is_not(None),
                )
            )
        ).all()
    )
    narration_ids = intro_narration_ids + post_narration_ids

    narration_stored_object_ids: list[int] = []
    if narration_ids:
        narration_stored_object_ids = list(
            (
                await session.scalars(
                    select(models.LectureVideoNarration.stored_object_id).where(
                        models.LectureVideoNarration.id.in_(narration_ids),
                        models.LectureVideoNarration.stored_object_id.is_not(None),
                    )
                )
            ).all()
        )

    if question_ids:
        await session.execute(
            delete(
                models.lecture_video_question_single_select_correct_option_association
            ).where(
                models.lecture_video_question_single_select_correct_option_association.c.question_id.in_(
                    question_ids
                )
            )
        )
        await session.execute(
            delete(models.LectureVideoQuestionOption).where(
                models.LectureVideoQuestionOption.question_id.in_(question_ids)
            )
        )
        await session.execute(
            delete(models.LectureVideoQuestion).where(
                models.LectureVideoQuestion.id.in_(question_ids)
            )
        )

    if narration_ids:
        await session.execute(
            delete(models.LectureVideoNarration).where(
                models.LectureVideoNarration.id.in_(narration_ids)
            )
        )

    if narration_stored_object_ids:
        orphaned_narration_stored_object_ids: list[int] = []
        for stored_object_id in sorted(set(narration_stored_object_ids)):
            still_used = await session.scalar(
                select(models.LectureVideoNarration.id).where(
                    models.LectureVideoNarration.stored_object_id == stored_object_id
                )
            )
            if still_used is None:
                orphaned_narration_stored_object_ids.append(stored_object_id)
        if orphaned_narration_stored_object_ids:
            await session.execute(
                delete(models.LectureVideoNarrationStoredObject).where(
                    models.LectureVideoNarrationStoredObject.id.in_(
                        orphaned_narration_stored_object_ids
                    )
                )
            )

    stored_object_id = lecture_video.stored_object_id
    await session.execute(
        delete(models.LectureVideo).where(models.LectureVideo.id == lecture_video.id)
    )

    if stored_object_id is not None:
        remaining_lecture_video = await session.scalar(
            select(models.LectureVideo.id).where(
                models.LectureVideo.stored_object_id == stored_object_id
            )
        )
        if remaining_lecture_video is None:
            await session.execute(
                delete(models.LectureVideoStoredObject).where(
                    models.LectureVideoStoredObject.id == stored_object_id
                )
            )

    revokes = lecture_video_grants(lecture_video)
    await authz.write_safe(revoke=revokes)
    return len(revokes)


def _batch_ids(ids: set[int]) -> list[list[int]]:
    ordered_ids = sorted(ids)
    return [
        ordered_ids[i : i + _BATCH_SIZE]
        for i in range(0, len(ordered_ids), _BATCH_SIZE)
    ]


async def cleanup_invalid_lecture_video_schema_rows(
    session: AsyncSession,
    authz: AuthzClient,
) -> CleanupInvalidLectureVideoSchemaRowsResult:
    result = CleanupInvalidLectureVideoSchemaRowsResult()

    enabled_class_ids = await _get_lecture_video_enabled_class_ids(session)

    assistant_rows = (
        (
            await session.execute(
                select(models.Assistant).options(
                    load_only(
                        models.Assistant.id,
                        models.Assistant.class_id,
                        models.Assistant.interaction_mode,
                        models.Assistant.lecture_video_id,
                        models.Assistant.creator_id,
                        models.Assistant.published,
                    )
                )
            )
        )
        .scalars()
        .all()
    )
    thread_rows = (
        (
            await session.execute(
                select(models.Thread).options(
                    load_only(
                        models.Thread.id,
                        models.Thread.class_id,
                        models.Thread.assistant_id,
                        models.Thread.interaction_mode,
                        models.Thread.lecture_video_id,
                        models.Thread.private,
                    )
                )
            )
        )
        .scalars()
        .all()
    )

    lecture_videos_by_id = await _load_all_lecture_videos(session)
    question_ids = {
        question.id
        for lecture_video in lecture_videos_by_id.values()
        for question in lecture_video.questions
    }
    correct_option_counts = await _get_correct_option_counts(session, question_ids)

    assistants_by_id = {assistant.id: assistant for assistant in assistant_rows}
    disabled_class_ids = {
        class_id
        for class_id in (
            [
                assistant.class_id
                for assistant in assistant_rows
                if assistant.interaction_mode == schemas.InteractionMode.LECTURE_VIDEO
            ]
            + [
                thread.class_id
                for thread in thread_rows
                if thread.interaction_mode == schemas.InteractionMode.LECTURE_VIDEO
            ]
        )
        if class_id not in enabled_class_ids
    }
    invalid_lecture_video_ids = {
        lecture_video.id
        for lecture_video in lecture_videos_by_id.values()
        if (
            lecture_video.class_id in disabled_class_ids
            or not _is_valid_lecture_video(lecture_video, correct_option_counts)
        )
    }
    valid_lecture_video_ids = set(lecture_videos_by_id) - invalid_lecture_video_ids

    invalid_assistant_ids: set[int] = set()
    for assistant in assistant_rows:
        if assistant.interaction_mode == schemas.InteractionMode.LECTURE_VIDEO:
            if (
                assistant.class_id in disabled_class_ids
                or assistant.lecture_video_id is None
                or assistant.lecture_video_id not in valid_lecture_video_ids
            ):
                invalid_assistant_ids.add(assistant.id)
        elif assistant.lecture_video_id is not None:
            invalid_assistant_ids.add(assistant.id)

    invalid_thread_ids: set[int] = set()
    for thread in thread_rows:
        if thread.interaction_mode == schemas.InteractionMode.LECTURE_VIDEO:
            assistant = (
                assistants_by_id.get(thread.assistant_id)
                if thread.assistant_id is not None
                else None
            )
            if (
                thread.class_id in disabled_class_ids
                or assistant is None
                or assistant.interaction_mode != schemas.InteractionMode.LECTURE_VIDEO
                or thread.lecture_video_id is None
                or assistant.lecture_video_id is None
                or thread.lecture_video_id != assistant.lecture_video_id
                or thread.lecture_video_id not in valid_lecture_video_ids
            ):
                invalid_thread_ids.add(thread.id)
        elif thread.lecture_video_id is not None:
            invalid_thread_ids.add(thread.id)

    invalid_thread_ids.update(
        thread.id
        for thread in thread_rows
        if thread.assistant_id is not None
        and thread.assistant_id in invalid_assistant_ids
    )
    lecture_video_ids_to_delete: set[int] = set(invalid_lecture_video_ids)
    lecture_video_ids_to_delete.update(
        assistant.lecture_video_id
        for assistant in assistant_rows
        if assistant.id in invalid_assistant_ids
        and assistant.lecture_video_id is not None
    )
    lecture_video_ids_to_delete.update(
        thread.lecture_video_id
        for thread in thread_rows
        if thread.id in invalid_thread_ids and thread.lecture_video_id is not None
    )

    result.lecture_video_disabled_classes = len(disabled_class_ids)
    result.invalid_lecture_videos = len(invalid_lecture_video_ids)
    result.invalid_assistants = len(invalid_assistant_ids)
    result.invalid_threads = len(invalid_thread_ids)

    logger.info(
        "Found invalid lecture-video schema rows: disabled_classes=%s invalid_lecture_videos=%s invalid_assistants=%s invalid_threads=%s",
        result.lecture_video_disabled_classes,
        result.invalid_lecture_videos,
        result.invalid_assistants,
        result.invalid_threads,
    )

    for batch_ids in _batch_ids(invalid_thread_ids):
        batch_threads = (
            (
                await session.execute(
                    select(models.Thread)
                    .where(models.Thread.id.in_(batch_ids))
                    .options(
                        selectinload(models.Thread.users).load_only(models.User.id),
                        selectinload(models.Thread.anonymous_sessions).load_only(
                            models.AnonymousSession.session_token
                        ),
                        load_only(
                            models.Thread.id,
                            models.Thread.class_id,
                            models.Thread.private,
                        ),
                    )
                    .order_by(models.Thread.id.asc())
                )
            )
            .scalars()
            .all()
        )
        for thread in batch_threads:
            result.revokes_attempted += await _delete_thread_db_only(
                session, authz, thread
            )
            result.threads_deleted += 1
        await session.commit()
        session.expunge_all()

    for batch_ids in _batch_ids(invalid_assistant_ids):
        batch_assistants = (
            (
                await session.execute(
                    select(models.Assistant)
                    .where(models.Assistant.id.in_(batch_ids))
                    .options(
                        load_only(
                            models.Assistant.id,
                            models.Assistant.class_id,
                            models.Assistant.creator_id,
                            models.Assistant.published,
                        )
                    )
                    .order_by(models.Assistant.id.asc())
                )
            )
            .scalars()
            .all()
        )
        for assistant in batch_assistants:
            result.revokes_attempted += await _delete_assistant_db_only(
                session, authz, assistant
            )
            result.assistants_deleted += 1
        await session.commit()
        session.expunge_all()

    final_lecture_video_ids_to_delete: set[int] = set()
    for lecture_video_id in lecture_video_ids_to_delete:
        remaining_assistant = await session.scalar(
            select(models.Assistant.id).where(
                models.Assistant.lecture_video_id == lecture_video_id
            )
        )
        remaining_thread = await session.scalar(
            select(models.Thread.id).where(
                models.Thread.lecture_video_id == lecture_video_id
            )
        )
        if remaining_assistant is None and remaining_thread is None:
            final_lecture_video_ids_to_delete.add(lecture_video_id)

    for batch_ids in _batch_ids(final_lecture_video_ids_to_delete):
        batch_lecture_videos = (
            (
                await session.execute(
                    select(models.LectureVideo)
                    .where(models.LectureVideo.id.in_(batch_ids))
                    .options(
                        load_only(
                            models.LectureVideo.id,
                            models.LectureVideo.class_id,
                            models.LectureVideo.uploader_id,
                            models.LectureVideo.stored_object_id,
                        )
                    )
                    .order_by(models.LectureVideo.id.asc())
                )
            )
            .scalars()
            .all()
        )
        for lecture_video in batch_lecture_videos:
            result.revokes_attempted += await _delete_lecture_video_db_only(
                session, authz, lecture_video
            )
            result.lecture_videos_deleted += 1
        await session.commit()
        session.expunge_all()

    logger.info(
        "Finished cleaning invalid lecture-video schema rows: lecture_videos_deleted=%s threads_deleted=%s assistants_deleted=%s revokes_attempted=%s",
        result.lecture_videos_deleted,
        result.threads_deleted,
        result.assistants_deleted,
        result.revokes_attempted,
    )
    return result
