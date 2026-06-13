import logging
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

import pingpong.models as models
from pingpong import lecture_slide_processing
from pingpong.config import config

logger = logging.getLogger(__name__)

_BATCH_SIZE = 50
_TARGET_CONTENT_TYPE = (
    lecture_slide_processing.LECTURE_SLIDE_CONTINUOUS_AUDIO_CONTENT_TYPE
)


@dataclass(frozen=True)
class RemuxLectureSlideNarrationResult:
    remuxed: int = 0
    skipped: int = 0
    failed: int = 0


async def _read_audio_bytes(key: str) -> bytes:
    buffer = bytearray()
    async for chunk in config.lecture_video_audio_store.store.get_file(key):
        buffer.extend(chunk)
    return bytes(buffer)


async def remux_lecture_slide_narration_to_webm(
    session: AsyncSession,
) -> RemuxLectureSlideNarrationResult:
    if not config.lecture_video_audio_store:
        logger.warning(
            "No lecture video audio store configured; skipping continuous "
            "narration WebM remux."
        )
        return RemuxLectureSlideNarrationResult()

    remuxed = 0
    skipped = 0
    failed = 0
    last_processed_id = 0

    while True:
        result = await session.execute(
            select(models.LectureSlideDeck)
            .where(
                models.LectureSlideDeck.continuous_narration_stored_object_id.isnot(
                    None
                )
            )
            .where(models.LectureSlideDeck.id > last_processed_id)
            .order_by(models.LectureSlideDeck.id.asc())
            .options(
                selectinload(models.LectureSlideDeck.continuous_narration_stored_object)
            )
            .limit(_BATCH_SIZE)
        )
        decks = result.scalars().all()
        if not decks:
            break

        for deck in decks:
            last_processed_id = deck.id
            stored_object = deck.continuous_narration_stored_object
            if (
                stored_object is None
                or stored_object.content_type == _TARGET_CONTENT_TYPE
            ):
                skipped += 1
                continue

            old_key = stored_object.key
            try:
                ogg_audio = await _read_audio_bytes(old_key)
                webm_audio = (
                    await lecture_slide_processing.remux_continuous_narration_to_webm(
                        ogg_audio
                    )
                )
                new_key = lecture_slide_processing.generate_slide_continuous_narration_store_key()
                _, content_length = await lecture_slide_processing._store_audio(
                    new_key, _TARGET_CONTENT_TYPE, webm_audio
                )
            except Exception:
                failed += 1
                logger.exception(
                    "Failed to remux continuous narration to WebM. deck_id=%s key=%s",
                    deck.id,
                    old_key,
                )
                continue

            stored_object.key = new_key
            stored_object.content_type = _TARGET_CONTENT_TYPE
            stored_object.content_length = content_length
            session.add(stored_object)
            await session.commit()
            await lecture_slide_processing._delete_audio_key_quietly(old_key)
            remuxed += 1
            logger.info(
                "Remuxed continuous narration to WebM. deck_id=%s old_key=%s new_key=%s",
                deck.id,
                old_key,
                new_key,
            )

    return RemuxLectureSlideNarrationResult(
        remuxed=remuxed, skipped=skipped, failed=failed
    )
