import logging
from dataclasses import dataclass

from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

import pingpong.models as models
import pingpong.schemas as schemas
from pingpong import lecture_slide_service
from pingpong.ai import GetOpenAIClientException
from pingpong.config import config
from pingpong.video_store import VideoStoreError

logger = logging.getLogger(__name__)

_BATCH_SIZE = 20


@dataclass(frozen=True)
class UploadLectureSlideSourcesToOpenAIResult:
    uploaded: int = 0
    skipped: int = 0
    failed: int = 0
    version_bumped: int = 0


async def _upload_source_to_openai(
    session: AsyncSession,
    source: models.LectureSlideSourceStoredObject,
) -> models.File | None:
    decks = sorted(source.lecture_slide_decks, key=lambda deck: deck.id)
    if not decks:
        logger.warning(
            "Skipping lecture slide source without decks. source_id=%s key=%s",
            source.id,
            source.key,
        )
        return None
    deck = decks[0]
    return await lecture_slide_service.upload_lecture_slide_source_to_openai(
        session,
        source,
        class_id=deck.class_id,
        uploader_id=deck.uploader_id,
    )


async def upload_lecture_slide_sources_to_openai(
    session: AsyncSession,
) -> UploadLectureSlideSourcesToOpenAIResult:
    if config.video_store:
        uploaded, skipped, failed = await _upload_unlinked_sources(session)
    else:
        logger.warning(
            "No video store configured; skipping lecture slide source OpenAI upload."
        )
        uploaded = 0
        skipped = 0
        failed = 0

    version_bumped = await _bump_lecture_slide_decks_for_existing_threads(session)

    return UploadLectureSlideSourcesToOpenAIResult(
        uploaded=uploaded,
        skipped=skipped,
        failed=failed,
        version_bumped=version_bumped,
    )


async def _upload_unlinked_sources(session: AsyncSession) -> tuple[int, int, int]:
    uploaded = 0
    skipped = 0
    failed = 0
    last_processed_id = 0

    while True:
        sources = (
            (
                await session.scalars(
                    select(models.LectureSlideSourceStoredObject)
                    .where(
                        models.LectureSlideSourceStoredObject.openai_file_object_id.is_(
                            None
                        )
                    )
                    .where(models.LectureSlideSourceStoredObject.id > last_processed_id)
                    .options(
                        selectinload(
                            models.LectureSlideSourceStoredObject.lecture_slide_decks
                        )
                    )
                    .order_by(models.LectureSlideSourceStoredObject.id.asc())
                    .limit(_BATCH_SIZE)
                )
            )
            .unique()
            .all()
        )
        if not sources:
            break

        restart_batch = False
        for source in sources:
            source_id = source.id
            source_key = source.key
            last_processed_id = source_id
            try:
                file = await _upload_source_to_openai(session, source)
            except (GetOpenAIClientException, VideoStoreError) as exc:
                failed += 1
                await session.rollback()
                logger.warning(
                    "Failed to upload lecture slide source to OpenAI. "
                    "source_id=%s key=%s error=%s",
                    source_id,
                    source_key,
                    getattr(exc, "detail", None) or str(exc),
                )
                session.expunge_all()
                restart_batch = True
                break
            except Exception:
                failed += 1
                await session.rollback()
                logger.exception(
                    "Unexpected error uploading lecture slide source to OpenAI. "
                    "source_id=%s key=%s",
                    source_id,
                    source_key,
                )
                session.expunge_all()
                restart_batch = True
                break

            if file is None:
                skipped += 1
            else:
                uploaded += 1
                logger.info(
                    "Uploaded lecture slide source to OpenAI. source_id=%s key=%s file_id=%s",
                    source.id,
                    source.key,
                    file.file_id,
                )
            await session.commit()
        session.expunge_all()
        if restart_batch:
            continue

    logger.info(
        "Finished uploading lecture slide sources to OpenAI. uploaded=%s skipped=%s failed=%s",
        uploaded,
        skipped,
        failed,
    )
    return uploaded, skipped, failed


async def _bump_lecture_slide_decks_for_existing_threads(
    session: AsyncSession,
) -> int:
    assistant_deck_rows = (
        await session.execute(
            select(models.Assistant.id, models.Assistant.lecture_slide_deck_id)
            .join(
                models.Thread,
                and_(
                    models.Thread.assistant_id == models.Assistant.id,
                    models.Thread.lecture_slide_deck_id
                    == models.Assistant.lecture_slide_deck_id,
                ),
            )
            .join(models.Message, models.Message.thread_id == models.Thread.id)
            .where(
                models.Assistant.interaction_mode
                == schemas.InteractionMode.LECTURE_SLIDES,
                models.Assistant.lecture_slide_deck_id.is_not(None),
            )
            .distinct()
            .order_by(models.Assistant.id.asc())
        )
    ).all()

    bumped = 0
    for assistant_id, deck_id in assistant_deck_rows:
        if deck_id is None:
            continue
        assistant = await session.get(models.Assistant, assistant_id)
        deck = await models.LectureSlideDeck.get_by_id_with_processing_context(
            session, deck_id
        )
        if assistant is None or deck is None:
            logger.warning(
                "Skipping lecture slide deck version bump with missing row. "
                "assistant_id=%s deck_id=%s",
                assistant_id,
                deck_id,
            )
            continue

        cloned_deck = await lecture_slide_service.clone_lecture_slide_deck_snapshot(
            session,
            deck,
        )
        cloned_deck_id = cloned_deck.id
        assistant.lecture_slide_deck_id = cloned_deck.id
        session.add(assistant)
        await session.commit()
        session.expunge_all()
        bumped += 1
        logger.info(
            "Bumped lecture slide deck for existing threads. assistant_id=%s old_deck_id=%s new_deck_id=%s",
            assistant_id,
            deck_id,
            cloned_deck_id,
        )

    logger.info(
        "Finished bumping lecture slide deck versions for existing threads. version_bumped=%s",
        bumped,
    )
    return bumped
