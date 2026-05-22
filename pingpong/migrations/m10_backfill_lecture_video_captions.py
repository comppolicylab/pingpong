import asyncio
import logging
import os
import tempfile
from dataclasses import dataclass

from sqlalchemy import distinct, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload, undefer

import pingpong.models as models
import pingpong.schemas as schemas
from pingpong.ai import get_openai_client_by_class_id
from pingpong.config import config
from pingpong.lecture_video_manifest_generation import (
    transcribe_video_words,
    video_suffix_for_content_type,
)
from pingpong.lecture_video_service import (
    TRANSCRIPT_DATA_VERSION,
    persist_caption_artifact_for_lecture_video,
)

logger = logging.getLogger(__name__)

_DEFAULT_RETRANSCRIPTION_BATCH_SIZE = 10
_DEFAULT_CAPTION_BATCH_SIZE = 50


@dataclass(frozen=True)
class LectureVideoWordRetranscriptionResult:
    updated: int = 0
    skipped: int = 0
    failed: int = 0


@dataclass(frozen=True)
class LectureVideoCaptionBackfillResult:
    created: int = 0
    skipped: int = 0
    failed: int = 0


def _has_current_transcript_data(lecture_video: models.LectureVideo) -> bool:
    transcript_data = lecture_video.transcript_data
    if not isinstance(transcript_data, dict):
        return False
    word_level_transcription = transcript_data.get("word_level_transcription")
    return transcript_data.get("version") == TRANSCRIPT_DATA_VERSION and isinstance(
        word_level_transcription, list
    )


async def _write_video_to_temp_path(
    lecture_video: models.LectureVideo,
    temp_dir: str,
) -> str:
    if not config.video_store:
        raise RuntimeError("Video store not configured or unavailable.")
    if lecture_video.stored_object is None:
        raise RuntimeError("Lecture video stored object is not loaded.")

    suffix = video_suffix_for_content_type(lecture_video.stored_object.content_type)
    video_path = os.path.join(temp_dir, f"lecture_video_{lecture_video.id}{suffix}")
    with open(video_path, "wb") as output_file:
        async for chunk in config.video_store.store.stream_video(
            lecture_video.stored_object.key
        ):
            await asyncio.to_thread(output_file.write, chunk)
    return video_path


async def retranscribe_active_lecture_video_words(
    session: AsyncSession,
    *,
    batch_size: int = _DEFAULT_RETRANSCRIPTION_BATCH_SIZE,
    force: bool = False,
) -> LectureVideoWordRetranscriptionResult:
    if batch_size <= 0:
        raise ValueError("batch_size must be greater than 0.")

    if not config.video_store:
        logger.warning(
            "No video store configured; skipping lecture video retranscription."
        )
        return LectureVideoWordRetranscriptionResult()

    updated = 0
    skipped = 0
    failed = 0
    last_processed_id = 0

    while True:
        lecture_video_ids = list(
            (
                await session.scalars(
                    select(distinct(models.LectureVideo.id))
                    .join(
                        models.Assistant,
                        models.Assistant.lecture_video_id == models.LectureVideo.id,
                    )
                    .where(
                        models.Assistant.interaction_mode
                        == schemas.InteractionMode.LECTURE_VIDEO,
                        models.LectureVideo.status == schemas.LectureVideoStatus.READY,
                        models.LectureVideo.id > last_processed_id,
                    )
                    .order_by(models.LectureVideo.id.asc())
                    .limit(batch_size)
                )
            ).all()
        )
        if not lecture_video_ids:
            break

        for lecture_video_id in lecture_video_ids:
            last_processed_id = lecture_video_id
            lecture_video = await session.get(
                models.LectureVideo,
                lecture_video_id,
                options=[
                    undefer(models.LectureVideo.transcript_data),
                    selectinload(models.LectureVideo.stored_object),
                ],
            )
            if lecture_video is None:
                skipped += 1
                logger.warning(
                    "Could not find lecture video for retranscription. lecture_video_id=%s",
                    lecture_video_id,
                )
                continue
            if not force and _has_current_transcript_data(lecture_video):
                skipped += 1
                logger.info(
                    "Skipping lecture video with current transcript data. lecture_video_id=%s",
                    lecture_video_id,
                )
                continue

            try:
                openai_client = await get_openai_client_by_class_id(
                    session, lecture_video.class_id
                )
                with tempfile.TemporaryDirectory(
                    prefix="pingpong_lv_retranscribe_"
                ) as temp_dir:
                    video_path = await _write_video_to_temp_path(
                        lecture_video,
                        temp_dir,
                    )
                    words = await transcribe_video_words(
                        video_path,
                        openai_client,
                        temp_dir=temp_dir,
                    )
                lecture_video.transcript_data = {
                    "version": TRANSCRIPT_DATA_VERSION,
                    "word_level_transcription": [
                        word.model_dump(mode="json") for word in words
                    ],
                }
                session.add(lecture_video)
                await session.commit()
                updated += 1
                logger.info(
                    "Retranscribed lecture video words. lecture_video_id=%s words=%s",
                    lecture_video_id,
                    len(words),
                )
            except Exception:
                await session.rollback()
                failed += 1
                logger.exception(
                    "Unexpected error retranscribing lecture video. lecture_video_id=%s",
                    lecture_video_id,
                )
                continue

        session.expunge_all()

    logger.info(
        "Finished retranscribing lecture video words: updated=%s skipped=%s failed=%s",
        updated,
        skipped,
        failed,
    )
    return LectureVideoWordRetranscriptionResult(
        updated=updated,
        skipped=skipped,
        failed=failed,
    )


async def backfill_lecture_video_captions(
    session: AsyncSession,
    *,
    batch_size: int = _DEFAULT_CAPTION_BATCH_SIZE,
) -> LectureVideoCaptionBackfillResult:
    if batch_size <= 0:
        raise ValueError("batch_size must be greater than 0.")

    if not config.video_store:
        logger.warning(
            "No video store configured; skipping lecture video captions backfill."
        )
        return LectureVideoCaptionBackfillResult()

    created = 0
    skipped = 0
    failed = 0
    last_processed_id = 0

    while True:
        lecture_video_ids = list(
            (
                await session.scalars(
                    select(distinct(models.LectureVideo.id))
                    .join(
                        models.Assistant,
                        models.Assistant.lecture_video_id == models.LectureVideo.id,
                    )
                    .where(
                        models.Assistant.interaction_mode
                        == schemas.InteractionMode.LECTURE_VIDEO,
                        models.LectureVideo.caption_stored_object_id.is_(None),
                        models.LectureVideo.status == schemas.LectureVideoStatus.READY,
                        models.LectureVideo.id > last_processed_id,
                    )
                    .order_by(models.LectureVideo.id.asc())
                    .limit(batch_size)
                )
            ).all()
        )
        if not lecture_video_ids:
            break

        for lecture_video_id in lecture_video_ids:
            last_processed_id = lecture_video_id
            caption_key: str | None = None
            lecture_video = await session.get(
                models.LectureVideo,
                lecture_video_id,
                options=[
                    undefer(models.LectureVideo.manifest_data),
                    undefer(models.LectureVideo.transcript_data),
                    selectinload(models.LectureVideo.questions),
                ],
            )
            if lecture_video is None:
                skipped += 1
                logger.warning(
                    "Could not find lecture video for captions backfill. lecture_video_id=%s",
                    lecture_video_id,
                )
                continue

            try:
                caption = await persist_caption_artifact_for_lecture_video(
                    session, lecture_video
                )
                if caption is None:
                    await session.rollback()
                    skipped += 1
                    logger.warning(
                        "Could not generate captions for lecture video. lecture_video_id=%s",
                        lecture_video_id,
                    )
                    continue
                caption_key = caption.key
                await session.commit()
                created += 1
                logger.info(
                    "Backfilled lecture video captions. lecture_video_id=%s key=%s",
                    lecture_video_id,
                    caption_key,
                )
            except Exception:
                await session.rollback()
                # _persist_caption_artifact cleans up failures before flush; this
                # handles commit failures after the caption row was created.
                if caption_key:
                    try:
                        await config.video_store.store.delete(caption_key)
                    except Exception:
                        logger.exception(
                            "Failed to clean up uploaded caption after captions backfill error. key=%s",
                            caption_key,
                        )
                failed += 1
                logger.exception(
                    "Unexpected error backfilling lecture video captions. lecture_video_id=%s",
                    lecture_video_id,
                )
                continue

        # Keep long-running backfills from retaining every processed ORM object.
        session.expunge_all()

    logger.info(
        "Finished backfilling lecture video captions: created=%s skipped=%s failed=%s",
        created,
        skipped,
        failed,
    )
    return LectureVideoCaptionBackfillResult(
        created=created,
        skipped=skipped,
        failed=failed,
    )
