import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import pingpong.models as models
from pingpong.config import config
from pingpong.video_store import VideoStoreError

logger = logging.getLogger(__name__)

_BATCH_SIZE = 100


async def backfill_lecture_video_content_lengths(session: AsyncSession) -> int:
    if not config.video_store:
        logger.warning(
            "No video store configured; skipping lecture video content length backfill."
        )
        return 0

    updated = 0
    skipped = 0
    last_processed_id = 0

    while True:
        result = await session.execute(
            select(models.LectureVideoStoredObject)
            .where(models.LectureVideoStoredObject.content_length == 0)
            .where(models.LectureVideoStoredObject.id > last_processed_id)
            .order_by(models.LectureVideoStoredObject.id.asc())
            .limit(_BATCH_SIZE)
        )
        stored_objects = result.scalars().all()
        if not stored_objects:
            break

        for stored_object in stored_objects:
            last_processed_id = stored_object.id
            try:
                metadata = await config.video_store.store.get_video_metadata(
                    stored_object.key
                )
            except VideoStoreError as e:
                skipped += 1
                logger.warning(
                    "Failed to backfill lecture video content length. stored_object_id=%s key=%s error=%s",
                    stored_object.id,
                    stored_object.key,
                    e.detail or str(e),
                )
                continue
            except Exception:
                skipped += 1
                logger.exception(
                    "Unexpected error backfilling lecture video content length. stored_object_id=%s key=%s",
                    stored_object.id,
                    stored_object.key,
                )
                continue

            if metadata.content_length == 0:
                skipped += 1
                logger.warning(
                    "Video store returned content_length=0 during backfill. stored_object_id=%s key=%s",
                    stored_object.id,
                    stored_object.key,
                )
                continue

            stored_object.content_length = metadata.content_length
            session.add(stored_object)
            updated += 1
            logger.info(
                "Backfilled lecture video content length. stored_object_id=%s key=%s content_length=%s",
                stored_object.id,
                stored_object.key,
                metadata.content_length,
            )
        await session.commit()
        session.expunge_all()

    logger.info(
        "Finished backfilling lecture video content lengths: updated=%s skipped=%s",
        updated,
        skipped,
    )
    return updated
