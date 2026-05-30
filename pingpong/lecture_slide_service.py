import logging
from pathlib import Path
from typing import Iterable

import humanize
import uuid_utils as uuid
from fastapi import HTTPException, UploadFile
from pypdf import PdfReader
from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

import pingpong.models as models
import pingpong.schemas as schemas
from pingpong.config import config
from pingpong.lecture_video_service import get_original_filename, get_upload_size
from pingpong.video_store import VideoStoreError

logger = logging.getLogger(__name__)

LECTURE_SLIDE_DECK_ALREADY_ASSIGNED_DETAIL = (
    "This lecture slide deck is already attached to another assistant. "
    "Upload a new deck or copy the assistant instead."
)


def generate_source_store_key() -> str:
    return f"ls_source_{uuid.uuid7()}.pdf"


async def lecture_slide_summary_from_model(
    deck: models.LectureSlideDeck | None,
) -> schemas.LectureSlideSummary | None:
    if deck is None:
        return None
    source = deck.source_stored_object
    filename = deck.display_name
    size = 0
    content_type = "application/pdf"
    if source is not None:
        filename = source.original_filename
        size = source.content_length
        content_type = source.content_type
    return schemas.LectureSlideSummary(
        id=deck.id,
        filename=filename,
        size=size,
        content_type=content_type,
        status=schemas.LectureSlideDeckStatus(deck.status),
        error_message=deck.error_message,
        slide_count=deck.slide_count,
    )


async def create_lecture_slide_deck(
    session: AsyncSession,
    class_id: int,
    uploader_id: int,
    upload: UploadFile,
) -> models.LectureSlideDeck:
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
    filename = Path(upload.filename or "").name
    if content_type != "application/pdf" and not filename.lower().endswith(".pdf"):
        raise HTTPException(
            status_code=400,
            detail="Lecture slides must be uploaded as a PDF file.",
        )

    try:
        upload.file.seek(0)
        reader = PdfReader(upload.file)
        slide_count = len(reader.pages)
        upload.file.seek(0)
    except Exception as exc:
        raise HTTPException(
            status_code=400,
            detail="Lecture slides must be a readable PDF file.",
        ) from exc
    if slide_count < 1:
        raise HTTPException(
            status_code=400,
            detail="Lecture slide PDFs must contain at least one page.",
        )

    store_key = generate_source_store_key()
    original_filename = get_original_filename(upload, store_key)

    try:
        await config.video_store.store.put(store_key, upload.file, "application/pdf")
    except VideoStoreError as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Error saving lecture slides: {exc.detail or str(exc)}",
        ) from exc
    except Exception as exc:
        logger.exception("Unexpected error saving lecture slide upload")
        raise HTTPException(
            status_code=500,
            detail="An unexpected error occurred while saving the lecture slides. Please try again later.",
        ) from exc

    try:
        stored_object = await models.LectureSlideSourceStoredObject.create(
            session,
            key=store_key,
            original_filename=original_filename,
            content_type="application/pdf",
            content_length=upload_size,
        )
        deck = await models.LectureSlideDeck.create(
            session,
            class_id=class_id,
            source_stored_object_id=stored_object.id,
            uploader_id=uploader_id,
            display_name=original_filename,
            slide_count=slide_count,
        )
        deck.source_stored_object = stored_object
        return deck
    except Exception as exc:
        try:
            await config.video_store.store.delete(store_key)
        except Exception:
            logger.exception(
                "Failed to delete uploaded lecture slides after database error. key=%s",
                store_key,
            )
        logger.exception(
            "Failed to create lecture slide database records after upload. key=%s",
            store_key,
        )
        raise HTTPException(
            status_code=500,
            detail="An unexpected error occurred while saving the lecture slides. Please try again later.",
        ) from exc


async def ensure_lecture_slide_deck_is_unassigned(
    session: AsyncSession,
    deck_id: int,
    *,
    exclude_assistant_id: int | None = None,
) -> None:
    await session.execute(
        select(models.LectureSlideDeck.id)
        .where(models.LectureSlideDeck.id == deck_id)
        .with_for_update()
    )
    existing_assistant = await models.Assistant.get_by_lecture_slide_deck_id(
        session, deck_id, exclude_assistant_id=exclude_assistant_id
    )
    if existing_assistant is not None:
        raise HTTPException(
            status_code=400,
            detail=LECTURE_SLIDE_DECK_ALREADY_ASSIGNED_DETAIL,
        )


def raise_if_lecture_slide_assignment_conflict(exc: IntegrityError) -> None:
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
        "lecture_slide_deck_id" in message
        and "assistant" in message
        and ("unique" in message or "duplicate" in message)
    ):
        raise HTTPException(
            status_code=400, detail=LECTURE_SLIDE_DECK_ALREADY_ASSIGNED_DETAIL
        ) from exc


async def get_lecture_slide_assistant_for_class(
    session: AsyncSession, assistant_id: int, class_id: int
) -> models.Assistant:
    assistant = await models.Assistant.get_by_id(session, assistant_id)
    if not assistant or assistant.class_id != class_id:
        raise HTTPException(404, f"Assistant {assistant_id} not found.")

    if assistant.interaction_mode != schemas.InteractionMode.LECTURE_SLIDES:
        raise HTTPException(
            400,
            "This endpoint only supports assistants in Lecture Slides mode.",
        )

    return assistant


def ensure_lecture_slide_deck_uploaded_by_user(
    deck: models.LectureSlideDeck, user_id: int
) -> None:
    if deck.uploader_id != user_id:
        raise HTTPException(
            403,
            "Only the user who uploaded this lecture slide deck can access it.",
        )


async def apply_lecture_slide_page_notes(
    session: AsyncSession,
    deck: models.LectureSlideDeck,
    notes: Iterable[schemas.LectureSlidePageNotes],
) -> bool:
    changed = False
    for note in notes:
        if note.position >= deck.slide_count:
            raise HTTPException(
                status_code=400,
                detail=f"Slide note position {note.position} is outside this deck.",
            )
        value = (note.user_notes or "").strip() or None
        page = next(
            (page for page in deck.pages if page.position == note.position), None
        )
        if page is None:
            page = models.LectureSlidePage(
                lecture_slide_deck_id=deck.id,
                position=note.position,
                user_notes=value,
            )
            deck.pages.append(page)
            session.add(page)
            changed = True
        elif page.user_notes != value:
            page.user_notes = value
            session.add(page)
            changed = True
    if changed:
        await session.flush()
    return changed


async def clone_lecture_slide_deck_snapshot(
    session: AsyncSession,
    deck: models.LectureSlideDeck,
) -> models.LectureSlideDeck:
    cloned_deck = await models.LectureSlideDeck.create(
        session,
        class_id=deck.class_id,
        source_stored_object_id=deck.source_stored_object_id,
        uploader_id=deck.uploader_id,
        display_name=deck.display_name,
        voice_id=deck.voice_id,
        generation_prompt=deck.generation_prompt,
        narration_prompt=deck.narration_prompt,
        transcript_data=deck.transcript_data,
        context_data=deck.context_data,
        context_version=deck.context_version,
        lecture_slide_chat_available=deck.lecture_slide_chat_available,
        status=deck.status,
        error_message=deck.error_message,
        source_lecture_slide_deck_id_snapshot=deck.id,
        slide_count=deck.slide_count,
        total_duration_ms=deck.total_duration_ms,
        continuous_narration_stored_object_id=deck.continuous_narration_stored_object_id,
        caption_stored_object_id=deck.caption_stored_object_id,
    )
    cloned_deck.source_stored_object = deck.source_stored_object
    narration_id_map: dict[int, int] = {}

    async def clone_narration_id(
        narration: models.LectureSlideNarration | None,
    ) -> int | None:
        if narration is None:
            return None
        if narration.id in narration_id_map:
            return narration_id_map[narration.id]
        cloned_narration = models.LectureSlideNarration(
            stored_object_id=narration.stored_object_id,
            status=narration.status,
            error_message=narration.error_message,
        )
        session.add(cloned_narration)
        await session.flush()
        narration_id_map[narration.id] = cloned_narration.id
        return cloned_narration.id

    for page in deck.pages:
        session.add(
            models.LectureSlidePage(
                lecture_slide_deck_id=cloned_deck.id,
                position=page.position,
                image_stored_object_id=page.image_stored_object_id,
                title=page.title,
                extracted_text=page.extracted_text,
                user_notes=page.user_notes,
                narration_text=page.narration_text,
                image_description=page.image_description,
                narration_id=await clone_narration_id(page.narration),
                start_offset_ms=page.start_offset_ms,
                end_offset_ms=page.end_offset_ms,
            )
        )
    for question in deck.questions:
        question_row = models.LectureSlideQuestion(
            lecture_slide_deck_id=cloned_deck.id,
            position=question.position,
            slide_position=question.slide_position,
            slide_offset_ms=question.slide_offset_ms,
            stop_offset_ms=question.stop_offset_ms,
            question_type=question.question_type,
            question_text=question.question_text,
            intro_text=question.intro_text,
            intro_narration_id=await clone_narration_id(question.intro_narration),
        )
        session.add(question_row)
        await session.flush()
        option_pairs: list[tuple[models.LectureSlideQuestionOption, bool]] = []
        for option in question.options:
            option_row = models.LectureSlideQuestionOption(
                question_id=question_row.id,
                position=option.position,
                option_text=option.option_text,
                post_answer_text=option.post_answer_text,
                post_narration_id=await clone_narration_id(option.post_narration),
                continue_slide_position=option.continue_slide_position,
                continue_slide_offset_ms=option.continue_slide_offset_ms,
                continue_offset_ms=option.continue_offset_ms,
            )
            session.add(option_row)
            option_pairs.append(
                (
                    option_row,
                    question.correct_option is not None
                    and question.correct_option.id == option.id,
                )
            )
        await session.flush()
        for option_row, is_correct in option_pairs:
            if is_correct:
                await session.execute(
                    models.lecture_slide_question_single_select_correct_option_association.insert().values(
                        question_id=question_row.id,
                        option_id=option_row.id,
                    )
                )
    await session.flush()
    return cloned_deck


async def latest_processing_run_summary(
    session: AsyncSession,
    deck_id: int,
) -> schemas.LectureVideoProcessingRunSummary | None:
    run = await session.scalar(
        select(models.LectureSlideProcessingRun)
        .where(
            models.LectureSlideProcessingRun.lecture_slide_deck_id_snapshot == deck_id
        )
        .order_by(
            models.LectureSlideProcessingRun.created.desc().nulls_last(),
            models.LectureSlideProcessingRun.id.desc(),
        )
        .limit(1)
    )
    if run is None:
        return None
    return schemas.LectureVideoProcessingRunSummary(
        state=schemas.LectureVideoProcessingRunStatus(run.status),
        error_message=run.error_message,
        started_at=run.started_at,
        finished_at=run.finished_at,
    )


async def delete_lecture_slide_deck_if_unused(
    session: AsyncSession,
    deck_id: int,
) -> None:
    in_use = await session.scalar(
        select(models.Assistant.id)
        .where(models.Assistant.lecture_slide_deck_id == deck_id)
        .limit(1)
    )
    if in_use is not None:
        return
    thread_in_use = await session.scalar(
        select(models.Thread.id)
        .where(models.Thread.lecture_slide_deck_id == deck_id)
        .limit(1)
    )
    if thread_in_use is not None:
        return
    await session.execute(
        update(models.LectureSlideProcessingRun)
        .where(models.LectureSlideProcessingRun.lecture_slide_deck_id == deck_id)
        .values(lecture_slide_deck_id=None)
    )
    await session.execute(
        delete(models.LectureSlideDeck).where(models.LectureSlideDeck.id == deck_id)
    )
    await session.flush()
