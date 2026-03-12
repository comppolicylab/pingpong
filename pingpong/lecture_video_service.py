import logging
from pathlib import Path

import humanize
from fastapi import HTTPException, UploadFile
from sqlalchemy import delete, select, union
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
import uuid_utils as uuid

import pingpong.models as models
import pingpong.schemas as schemas
from .authz import AuthzClient, Relation
from .config import config
from .video_store import VideoStoreError

logger = logging.getLogger(__name__)

LECTURE_VIDEO_ALREADY_ASSIGNED_DETAIL = (
    "This lecture video is already attached to another assistant. "
    "Upload a new lecture video or copy the assistant instead."
)


def get_upload_size(upload: UploadFile) -> int:
    if upload.size is None:
        raise HTTPException(
            status_code=400,
            detail="Lecture video upload size could not be determined.",
        )

    return upload.size


def generate_store_key(content_type: str) -> str:
    suffix = ".mp4" if content_type == "video/mp4" else ".webm"
    return f"lv_{uuid.uuid7()}{suffix}"


def get_original_filename(upload: UploadFile, store_key: str) -> str:
    return Path(upload.filename or store_key).name


def lecture_video_grants(
    lecture_video: models.LectureVideo,
) -> list[Relation]:
    grants = [
        (
            f"class:{lecture_video.class_id}",
            "parent",
            f"lecture_video:{lecture_video.id}",
        )
    ]
    if lecture_video.uploader_id is not None:
        grants.append(
            (
                f"user:{lecture_video.uploader_id}",
                "owner",
                f"lecture_video:{lecture_video.id}",
            )
        )
    return grants


async def grant_lecture_video_permissions_or_cleanup(
    session: AsyncSession,
    authz: AuthzClient,
    lecture_video: models.LectureVideo,
) -> None:
    try:
        await authz.write_safe(grant=lecture_video_grants(lecture_video))
    except Exception:
        logger.exception(
            "Error granting permissions for lecture video. lecture_video_id=%s",
            lecture_video.id,
        )
        try:
            await delete_lecture_video(session, lecture_video.id)
        except Exception:
            logger.exception(
                "Failed to clean up lecture video after permission grant error. lecture_video_id=%s",
                lecture_video.id,
            )
        raise


async def create_lecture_video(
    session: AsyncSession,
    class_id: int,
    uploader_id: int,
    upload: UploadFile,
) -> models.LectureVideo:
    if not config.video_store:
        raise HTTPException(
            status_code=503, detail="Video store not configured or unavailable."
        )

    upload_size = get_upload_size(upload)
    if upload_size > config.upload.lecture_video_max_size:
        raise HTTPException(
            status_code=413,
            detail=(
                "File too large. "
                f"Max size is {humanize.naturalsize(config.upload.lecture_video_max_size)}."
            ),
        )

    content_type = (upload.content_type or "").lower()
    if content_type not in {"video/mp4", "video/webm"}:
        raise HTTPException(
            status_code=400,
            detail="Lecture videos must be uploaded as MP4 or WebM files.",
        )

    store_key = generate_store_key(content_type)
    original_filename = get_original_filename(upload, store_key)

    try:
        upload.file.seek(0)
        await config.video_store.store.put(store_key, upload.file, content_type)
    except VideoStoreError as e:
        raise HTTPException(
            status_code=400,
            detail=f"Error saving lecture video: {e.detail or str(e)}",
        ) from e
    except Exception as e:
        logger.exception("Unexpected error saving lecture video upload")
        raise HTTPException(
            status_code=500,
            detail="An unexpected error occurred while saving the lecture video. Please try again later.",
        ) from e

    try:
        stored_object = await models.LectureVideoStoredObject.create(
            session,
            key=store_key,
            original_filename=original_filename,
            content_type=content_type,
            content_length=upload_size,
        )
        lecture_video = await models.LectureVideo.create(
            session,
            class_id=class_id,
            stored_object_id=stored_object.id,
            user_id=uploader_id,
        )
        lecture_video.stored_object = stored_object
        return lecture_video
    except Exception as e:
        try:
            await config.video_store.store.delete(store_key)
        except Exception:
            logger.exception(
                "Failed to delete uploaded lecture video after database error. key=%s",
                store_key,
            )
        logger.exception(
            "Failed to create lecture video database records after upload. key=%s",
            store_key,
        )
        raise HTTPException(
            status_code=500,
            detail="An unexpected error occurred while saving the lecture video. Please try again later.",
        ) from e


async def _backfill_lecture_video_content_length_if_missing(
    session: AsyncSession,
    stored_object: models.LectureVideoStoredObject,
) -> None:
    if stored_object.content_length != 0:
        return

    if not config.video_store:
        logger.warning(
            "Lecture video stored object has content_length=0 but no video store is configured. stored_object_id=%s key=%s",
            stored_object.id,
            stored_object.key,
        )
        return

    logger.info(
        "Lecture video stored object has content_length=0; loading metadata from store. stored_object_id=%s key=%s",
        stored_object.id,
        stored_object.key,
    )
    try:
        metadata = await config.video_store.store.get_video_metadata(stored_object.key)
    except VideoStoreError as e:
        logger.warning(
            "Failed to backfill lecture video content length from store. stored_object_id=%s key=%s error=%s",
            stored_object.id,
            stored_object.key,
            e.detail or str(e),
        )
        return
    except Exception:
        logger.exception(
            "Unexpected error backfilling lecture video content length. stored_object_id=%s key=%s",
            stored_object.id,
            stored_object.key,
        )
        return

    if metadata.content_length == 0:
        logger.warning(
            "Video store returned content_length=0 during on-demand lecture video backfill. stored_object_id=%s key=%s",
            stored_object.id,
            stored_object.key,
        )
        return

    stored_object.content_length = metadata.content_length
    await session.flush()
    logger.info(
        "Backfilled lecture video content length from store. stored_object_id=%s key=%s content_length=%s",
        stored_object.id,
        stored_object.key,
        metadata.content_length,
    )


async def lecture_video_summary_from_model(
    session: AsyncSession,
    lecture_video: models.LectureVideo | None,
) -> schemas.LectureVideoSummary | None:
    if lecture_video is None:
        return None
    stored_object = lecture_video.stored_object
    if stored_object is None:
        raise ValueError(
            "Lecture video stored_object must be loaded before serialization."
        )
    await _backfill_lecture_video_content_length_if_missing(session, stored_object)
    return schemas.LectureVideoSummary(
        id=lecture_video.id,
        filename=stored_object.original_filename,
        size=stored_object.content_length,
        content_type=stored_object.content_type,
        status=lecture_video.status,
        error_message=lecture_video.error_message,
    )


async def ensure_lecture_video_is_unassigned(
    session: AsyncSession,
    lecture_video_id: int,
    *,
    exclude_assistant_id: int | None = None,
) -> None:
    # Lock the lecture video row so the unassigned check and the later write/flush()
    # happen in the same transaction window for this lecture_video_id.
    await session.execute(
        select(models.LectureVideo.id)
        .where(models.LectureVideo.id == lecture_video_id)
        .with_for_update()
    )
    existing_assistant = await models.Assistant.get_by_lecture_video_id(
        session, lecture_video_id, exclude_assistant_id=exclude_assistant_id
    )
    if existing_assistant is not None:
        raise HTTPException(
            status_code=400,
            detail=LECTURE_VIDEO_ALREADY_ASSIGNED_DETAIL,
        )


def raise_if_lecture_video_assignment_conflict(exc: IntegrityError) -> None:
    message = " ".join(
        part.lower()
        for part in (
            str(exc),
            str(getattr(exc, "orig", "")),
            str(getattr(exc, "statement", "")),
        )
        if part
    )
    if (
        "lecture_video_id" in message
        and "assistant" in message
        and ("unique" in message or "duplicate" in message)
    ):
        raise HTTPException(
            status_code=400, detail=LECTURE_VIDEO_ALREADY_ASSIGNED_DETAIL
        ) from exc


async def get_lecture_video_assistant_for_class(
    session: AsyncSession, assistant_id: int, class_id: int
) -> models.Assistant:
    assistant = await models.Assistant.get_by_id(session, assistant_id)
    if not assistant or assistant.class_id != class_id:
        raise HTTPException(404, f"Assistant {assistant_id} not found.")

    if assistant.interaction_mode != schemas.InteractionMode.LECTURE_VIDEO:
        raise HTTPException(
            400,
            "This endpoint only supports assistants in Lecture Video mode.",
        )

    return assistant


def ensure_lecture_video_uploaded_by_user(
    lecture_video: models.LectureVideo, user_id: int
) -> None:
    if lecture_video.uploader_id != user_id:
        raise HTTPException(
            403,
            "Only the user who uploaded this lecture video can delete it.",
        )


def text_needs_audio(text: str) -> bool:
    return bool(text.strip())


async def _get_orphaned_narration_stored_objects_for_clear(
    session: AsyncSession, lecture_video_id: int
) -> list[tuple[int, str]]:
    narration_ids = union(
        select(models.LectureVideoQuestion.intro_narration_id.label("id")).where(
            models.LectureVideoQuestion.lecture_video_id == lecture_video_id,
            models.LectureVideoQuestion.intro_narration_id.is_not(None),
        ),
        select(models.LectureVideoQuestionOption.post_narration_id.label("id"))
        .join(
            models.LectureVideoQuestion,
            models.LectureVideoQuestion.id
            == models.LectureVideoQuestionOption.question_id,
        )
        .where(
            models.LectureVideoQuestion.lecture_video_id == lecture_video_id,
            models.LectureVideoQuestionOption.post_narration_id.is_not(None),
        ),
    ).cte("narration_ids")
    other_narrations = models.LectureVideoNarration.__table__.alias("other_narrations")
    remaining_narration_exists = (
        select(other_narrations.c.id)
        .select_from(
            other_narrations.outerjoin(
                narration_ids, narration_ids.c.id == other_narrations.c.id
            )
        )
        .where(
            other_narrations.c.stored_object_id
            == models.LectureVideoNarrationStoredObject.id,
            narration_ids.c.id.is_(None),
        )
        .exists()
    )

    return list(
        (
            await session.execute(
                select(
                    models.LectureVideoNarrationStoredObject.id,
                    models.LectureVideoNarrationStoredObject.key,
                )
                .join(
                    models.LectureVideoNarration,
                    models.LectureVideoNarration.stored_object_id
                    == models.LectureVideoNarrationStoredObject.id,
                )
                .join(
                    narration_ids, narration_ids.c.id == models.LectureVideoNarration.id
                )
                .where(~remaining_narration_exists)
                .distinct()
            )
        ).all()
    )


async def clear_normalized_content(
    session: AsyncSession, lecture_video_id: int
) -> None:
    audio_keys_to_delete = await _clear_normalized_content_rows_and_collect_audio_keys(
        session, lecture_video_id
    )
    if not audio_keys_to_delete or not config.lecture_video_audio_store:
        return

    for key in audio_keys_to_delete:
        await config.lecture_video_audio_store.store.delete_file(key)


async def _clear_normalized_content_rows_and_collect_audio_keys(
    session: AsyncSession, lecture_video_id: int
) -> list[str]:
    orphaned_stored_objects = await _get_orphaned_narration_stored_objects_for_clear(
        session, lecture_video_id
    )
    await models.LectureVideo.clear_normalized_content_rows(session, lecture_video_id)
    if not orphaned_stored_objects:
        return []

    await session.execute(
        delete(models.LectureVideoNarrationStoredObject).where(
            models.LectureVideoNarrationStoredObject.id.in_(
                [stored_object_id for stored_object_id, _ in orphaned_stored_objects]
            )
        )
    )
    return [key for _, key in orphaned_stored_objects]


async def delete_lecture_video(
    session: AsyncSession,
    lecture_video_id: int,
    authz: AuthzClient | None = None,
) -> None:
    lecture_video = await models.LectureVideo.get_by_id(session, lecture_video_id)
    if lecture_video is None:
        return

    revoke_grants = lecture_video_grants(lecture_video)
    stored_object_id = lecture_video.stored_object_id
    store_key = lecture_video.stored_object.key if lecture_video.stored_object else None
    is_orphaned_after_delete = not bool(
        await session.scalar(
            select(models.LectureVideo.id).where(
                models.LectureVideo.stored_object_id == stored_object_id,
                models.LectureVideo.id != lecture_video_id,
            )
        )
    )

    audio_keys_to_delete = await _clear_normalized_content_rows_and_collect_audio_keys(
        session, lecture_video_id
    )
    await session.execute(
        delete(models.LectureVideo).where(models.LectureVideo.id == lecture_video_id)
    )

    if is_orphaned_after_delete and stored_object_id is not None:
        await session.execute(
            delete(models.LectureVideoStoredObject).where(
                models.LectureVideoStoredObject.id == stored_object_id
            )
        )

    if audio_keys_to_delete and config.lecture_video_audio_store:
        for key in audio_keys_to_delete:
            await config.lecture_video_audio_store.store.delete_file(key)

    if is_orphaned_after_delete and store_key and config.video_store:
        await config.video_store.store.delete(store_key)

    if authz is not None:
        await authz.write_safe(revoke=revoke_grants)


async def ensure_lecture_video_is_unused(
    session: AsyncSession,
    lecture_video_id: int,
    *,
    exclude_assistant_id: int | None = None,
) -> None:
    await session.scalar(
        select(models.LectureVideo.id)
        .where(models.LectureVideo.id == lecture_video_id)
        .with_for_update()
    )

    assistant_id = await session.scalar(
        select(models.Assistant.id).where(
            models.Assistant.lecture_video_id == lecture_video_id
        )
    )
    if assistant_id is not None and assistant_id != exclude_assistant_id:
        raise HTTPException(
            status_code=409,
            detail="This lecture video is attached to an assistant and cannot be deleted.",
        )

    thread_id = await session.scalar(
        select(models.Thread.id).where(
            models.Thread.lecture_video_id == lecture_video_id
        )
    )
    if thread_id is not None:
        raise HTTPException(
            status_code=409,
            detail="This lecture video is used by a thread and cannot be deleted.",
        )


async def delete_lecture_video_if_unused(
    session: AsyncSession,
    lecture_video_id: int | None,
    authz: AuthzClient | None = None,
) -> bool:
    if lecture_video_id is None:
        return False

    try:
        await ensure_lecture_video_is_unused(session, lecture_video_id)
    except HTTPException:
        return False

    await delete_lecture_video(session, lecture_video_id, authz=authz)
    return True


async def persist_manifest(
    session: AsyncSession,
    lecture_video: models.LectureVideo,
    lecture_video_manifest: schemas.LectureVideoManifestV1,
) -> None:
    await clear_normalized_content(session, lecture_video.id)

    for question_position, question in enumerate(lecture_video_manifest.questions):
        question_row = models.LectureVideoQuestion(
            lecture_video_id=lecture_video.id,
            position=question_position,
            question_type=question.type,
            question_text=question.question_text,
            intro_text=question.intro_text,
            stop_offset_ms=question.stop_offset_ms,
        )
        session.add(question_row)
        await session.flush()

        if text_needs_audio(question.intro_text):
            intro_narration = models.LectureVideoNarration(
                status=schemas.LectureVideoNarrationStatus.PENDING,
            )
            session.add(intro_narration)
            await session.flush()
            question_row.intro_narration_id = intro_narration.id

        option_rows: list[
            tuple[
                schemas.LectureVideoManifestOptionV1,
                models.LectureVideoQuestionOption,
            ]
        ] = []
        for option_position, option in enumerate(question.options):
            option_row = models.LectureVideoQuestionOption(
                question_id=question_row.id,
                position=option_position,
                option_text=option.option_text,
                post_answer_text=option.post_answer_text,
                continue_offset_ms=option.continue_offset_ms,
            )
            session.add(option_row)
            option_rows.append((option, option_row))

        await session.flush()

        for option, option_row in option_rows:
            if option.correct:
                await session.execute(
                    models.lecture_video_question_single_select_correct_option_association.insert().values(
                        question_id=question_row.id,
                        option_id=option_row.id,
                    )
                )
            if text_needs_audio(option.post_answer_text):
                post_narration = models.LectureVideoNarration(
                    status=schemas.LectureVideoNarrationStatus.PENDING,
                )
                session.add(post_narration)
                await session.flush()
                option_row.post_narration_id = post_narration.id

    lecture_video.status = schemas.LectureVideoStatus.READY
    lecture_video.error_message = None
    await session.flush()
