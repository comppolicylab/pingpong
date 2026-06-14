import logging
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload, undefer

import pingpong.models as models
import pingpong.schemas as schemas
from pingpong import lecture_slide_processing, lecture_slide_service
from pingpong.ai import get_openai_client_by_class_id
from pingpong.config import config

logger = logging.getLogger(__name__)

_BATCH_SIZE = 10


@dataclass(frozen=True)
class MigrateLectureSlideV4ContextToV5Result:
    updated: int = 0
    skipped: int = 0
    failed: int = 0


def _transcript_words_from_deck(
    deck: models.LectureSlideDeck,
) -> list[schemas.LectureVideoManifestWordV3] | None:
    transcript_data = deck.transcript_data
    if not isinstance(transcript_data, dict):
        return None
    words = transcript_data.get("word_level_transcription")
    if not isinstance(words, list) or not words:
        return None
    return [schemas.LectureVideoManifestWordV3.model_validate(word) for word in words]


def _page_ranges_from_deck(
    deck: models.LectureSlideDeck,
) -> list[lecture_slide_processing.SlidePageRange]:
    return [
        {
            "slide_position": page.position,
            "start_offset_ms": page.start_offset_ms,
            "end_offset_ms": page.end_offset_ms,
        }
        for page in sorted(deck.pages, key=lambda item: item.position)
    ]


async def _read_source_bytes(source: models.LectureSlideSourceStoredObject) -> bytes:
    if not config.video_store:
        raise RuntimeError("Video store not configured or unavailable.")
    buffer = bytearray()
    async for chunk in config.video_store.store.stream_video(source.key):
        buffer.extend(chunk)
    return bytes(buffer)


async def _get_or_upload_source_file_id(
    session: AsyncSession,
    deck: models.LectureSlideDeck,
) -> str:
    source = deck.source_stored_object
    if source is None:
        raise RuntimeError("Lecture slide source object is not loaded.")
    if source.openai_file is not None and source.openai_file.file_id:
        return str(source.openai_file.file_id)

    source_bytes = await _read_source_bytes(source)
    file = await lecture_slide_service.upload_lecture_slide_source_to_openai(
        session,
        source,
        class_id=deck.class_id,
        uploader_id=deck.uploader_id,
        source_bytes=source_bytes,
    )
    await session.commit()
    return str(file.file_id)


async def _get_responses_model_for_deck(
    session: AsyncSession,
    deck: models.LectureSlideDeck,
) -> str | None:
    model = await session.scalar(
        select(models.Assistant.model)
        .where(models.Assistant.lecture_slide_deck_id == deck.id)
        .where(models.Assistant.model.is_not(None))
        .order_by(models.Assistant.id.asc())
        .limit(1)
    )
    return str(model) if model else None


async def migrate_lecture_slide_v4_context_to_v5(
    session: AsyncSession,
    *,
    batch_size: int = _BATCH_SIZE,
    limit: int | None = None,
) -> MigrateLectureSlideV4ContextToV5Result:
    updated = 0
    skipped = 0
    failed = 0
    seen = 0
    last_processed_id = 0

    while True:
        if limit is not None and seen >= limit:
            break
        page_size = batch_size
        if limit is not None:
            page_size = min(page_size, limit - seen)

        result = await session.execute(
            select(models.LectureSlideDeck)
            .where(models.LectureSlideDeck.context_version == 4)
            .where(models.LectureSlideDeck.lecture_slide_chat_available.is_(True))
            .where(models.LectureSlideDeck.id > last_processed_id)
            .order_by(models.LectureSlideDeck.id.asc())
            .options(undefer(models.LectureSlideDeck.generation_prompt))
            .options(undefer(models.LectureSlideDeck.transcript_data))
            .options(undefer(models.LectureSlideDeck.context_data))
            .options(
                selectinload(models.LectureSlideDeck.source_stored_object).selectinload(
                    models.LectureSlideSourceStoredObject.openai_file
                )
            )
            .options(selectinload(models.LectureSlideDeck.pages))
            .limit(page_size)
        )
        decks = result.scalars().unique().all()
        if not decks:
            break

        for deck in decks:
            last_processed_id = deck.id
            seen += 1
            if limit is not None and seen > limit:
                break

            deck_id = deck.id
            try:
                class_id = deck.class_id
                generation_prompt = deck.generation_prompt
                total_duration_ms = deck.total_duration_ms
                transcript = _transcript_words_from_deck(deck)
                page_ranges = _page_ranges_from_deck(deck)
                if transcript is None or not page_ranges:
                    skipped += 1
                    logger.info(
                        "Skipping lecture slide v4 context migration without "
                        "transcript/pages. deck_id=%s",
                        deck_id,
                    )
                    continue

                responses_model = await _get_responses_model_for_deck(session, deck)
                if responses_model is None:
                    skipped += 1
                    logger.info(
                        "Skipping lecture slide v4 context migration without "
                        "assistant model. deck_id=%s",
                        deck_id,
                    )
                    continue

                file_id = await _get_or_upload_source_file_id(session, deck)
                openai_client = await get_openai_client_by_class_id(session, class_id)
                context = await lecture_slide_processing.generate_slide_context_v5(
                    openai_client=openai_client,
                    model=responses_model,
                    file_id=file_id,
                    generation_prompt=generation_prompt,
                    page_ranges=page_ranges,
                    transcript=transcript,
                    total_duration_ms=total_duration_ms,
                )
                deck.context_data = context.model_dump()
                deck.context_version = 5
                deck.lecture_slide_chat_available = True
                session.add(deck)
                await session.commit()
                updated += 1
                logger.info(
                    "Migrated lecture slide v4 context to v5. deck_id=%s", deck_id
                )
            except Exception:
                failed += 1
                await session.rollback()
                logger.exception(
                    "Failed to migrate lecture slide v4 context to v5. deck_id=%s",
                    deck_id,
                )

    return MigrateLectureSlideV4ContextToV5Result(
        updated=updated,
        skipped=skipped,
        failed=failed,
    )
