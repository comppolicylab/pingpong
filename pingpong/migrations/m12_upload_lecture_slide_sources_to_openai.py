import logging
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

import pingpong.models as models
from pingpong.ai import GetOpenAIClientException, get_openai_client_by_class_id
from pingpong.config import config
from pingpong.video_store import VideoStoreError

logger = logging.getLogger(__name__)

_BATCH_SIZE = 20


@dataclass(frozen=True)
class UploadLectureSlideSourcesToOpenAIResult:
    uploaded: int = 0
    skipped: int = 0
    failed: int = 0


async def _read_source_pdf_bytes(key: str) -> bytes:
    if not config.video_store:
        raise RuntimeError("Video store not configured.")
    chunks = []
    async for chunk in config.video_store.store.stream_video(key):
        chunks.append(chunk)
    return b"".join(chunks)


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
    openai_client = await get_openai_client_by_class_id(session, deck.class_id)
    source_bytes = await _read_source_pdf_bytes(source.key)
    uploaded_file = await openai_client.files.create(
        file=(source.original_filename, source_bytes, source.content_type),
        purpose="user_data",
    )
    file_id = getattr(uploaded_file, "id", None)
    if not file_id and isinstance(uploaded_file, dict):
        file_id = uploaded_file.get("id")
    if not file_id:
        raise RuntimeError("OpenAI did not return a file id for lecture slide PDF.")

    file = await models.File.create(
        session,
        {
            "file_id": str(file_id),
            "private": True,
            "uploader_id": deck.uploader_id,
            "name": source.original_filename,
            "content_type": source.content_type,
        },
        class_id=deck.class_id,
    )
    source.openai_file_object_id = file.id
    session.add(source)
    return file


async def upload_lecture_slide_sources_to_openai(
    session: AsyncSession,
) -> UploadLectureSlideSourcesToOpenAIResult:
    if not config.video_store:
        logger.warning(
            "No video store configured; skipping lecture slide source OpenAI upload."
        )
        return UploadLectureSlideSourcesToOpenAIResult()

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
    return UploadLectureSlideSourcesToOpenAIResult(
        uploaded=uploaded,
        skipped=skipped,
        failed=failed,
    )
