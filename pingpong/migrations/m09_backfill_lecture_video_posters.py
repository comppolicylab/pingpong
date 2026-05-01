import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

import pingpong.models as models
from pingpong.config import config
from pingpong.lecture_video_poster import extract_and_store_poster

logger = logging.getLogger(__name__)

_BATCH_SIZE = 25


async def backfill_lecture_video_posters(session: AsyncSession) -> int:
    if not config.video_store:
        logger.warning(
            "No video store configured; skipping lecture video poster backfill."
        )
        return 0

    extracted = 0
    skipped = 0
    last_processed_id = 0

    while True:
        result = await session.execute(
            select(models.LectureVideo)
            .where(models.LectureVideo.poster_stored_object_id.is_(None))
            .where(models.LectureVideo.id > last_processed_id)
            .order_by(models.LectureVideo.id.asc())
            .options(selectinload(models.LectureVideo.stored_object))
            .limit(_BATCH_SIZE)
        )
        lecture_videos = result.scalars().all()
        if not lecture_videos:
            break

        for lecture_video in lecture_videos:
            last_processed_id = lecture_video.id
            try:
                stored_object = await extract_and_store_poster(session, lecture_video)
            except Exception:
                skipped += 1
                logger.exception(
                    "Unexpected error backfilling lecture video poster. lecture_video_id=%s",
                    lecture_video.id,
                )
                continue

            if stored_object is None:
                skipped += 1
                logger.warning(
                    "Could not generate poster for lecture video. lecture_video_id=%s",
                    lecture_video.id,
                )
                continue

            extracted += 1
            logger.info(
                "Backfilled lecture video poster. lecture_video_id=%s key=%s",
                lecture_video.id,
                stored_object.key,
            )
        await session.commit()
        session.expunge_all()

    logger.info(
        "Finished backfilling lecture video posters: extracted=%s skipped=%s",
        extracted,
        skipped,
    )
    return extracted
