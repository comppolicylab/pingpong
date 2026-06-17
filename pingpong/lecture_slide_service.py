import contextlib
import io
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import humanize
import openai
import uuid_utils as uuid
from fastapi import HTTPException, UploadFile
from pypdf import PdfReader
from sqlalchemy import delete, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

import pingpong.models as models
import pingpong.schemas as schemas
from pingpong.ai import get_openai_client_by_class_id
from pingpong.config import config
from pingpong.files import FILE_TYPES
from pingpong.lecture_video_service import get_original_filename, get_upload_size
from pingpong.video_store import VideoStoreError

logger = logging.getLogger(__name__)

LECTURE_SLIDE_DECK_ALREADY_ASSIGNED_DETAIL = (
    "This lecture slide deck is already attached to another assistant. "
    "Upload a new deck or copy the assistant instead."
)
OPENAI_INPUT_FILE_MAX_BYTES = 50 * 1024 * 1024
OPENAI_INPUT_FILE_MIME_TYPES = {
    file_type.mime_type.lower() for file_type in FILE_TYPES if file_type.input_file
}


@dataclass(frozen=True)
class LectureSlidePageUpdateResult:
    notes_changed: bool = False
    narration_changed: bool = False
    narration_changed_positions: frozenset[int] = frozenset()


@dataclass(frozen=True)
class LectureSlideQuestionUpdateResult:
    questions_changed: bool = False
    audio_changed: bool = False
    requires_question_generation: bool = False


def generate_source_store_key() -> str:
    return f"ls_source_{uuid.uuid7()}.pdf"


async def _read_source_pdf_bytes(key: str) -> bytes:
    if not config.video_store:
        raise RuntimeError("Video store not configured.")
    chunks = []
    async for chunk in config.video_store.store.stream_video(key):
        chunks.append(chunk)
    return b"".join(chunks)


def _uploaded_openai_file_id(uploaded_file: object) -> str:
    file_id = getattr(uploaded_file, "id", None)
    if not file_id and isinstance(uploaded_file, dict):
        file_id = uploaded_file.get("id")
    if not file_id:
        raise RuntimeError("OpenAI did not return a file id for lecture slide PDF.")
    return str(file_id)


def lecture_slide_context_file_summary_from_model(
    context_file: models.LectureSlideAdditionalContextFile,
) -> schemas.LectureSlideAdditionalContextFileSummary:
    return schemas.LectureSlideAdditionalContextFileSummary(
        id=context_file.id,
        filename=context_file.original_filename,
        size=context_file.content_length,
        content_type=context_file.content_type,
        file_object_id=context_file.file_object_id,
    )


def _normalize_content_type(content_type: str | None) -> str:
    return (content_type or "").split(";", 1)[0].strip().lower()


def _is_openai_input_file_supported(upload: UploadFile) -> bool:
    return _normalize_content_type(upload.content_type) in OPENAI_INPUT_FILE_MIME_TYPES


def _validate_openai_input_file_upload(upload: UploadFile, upload_size: int) -> None:
    if upload_size >= OPENAI_INPUT_FILE_MAX_BYTES:
        raise HTTPException(
            status_code=413,
            detail=(
                "File too large. "
                f"Each OpenAI input file must be under {humanize.naturalsize(OPENAI_INPUT_FILE_MAX_BYTES)}."
            ),
        )
    if not _is_openai_input_file_supported(upload):
        raise HTTPException(
            status_code=400,
            detail="File type not supported as an OpenAI input file.",
        )


async def upload_lecture_slide_source_to_openai(
    session: AsyncSession,
    source: models.LectureSlideSourceStoredObject,
    *,
    class_id: int,
    uploader_id: int | None,
    source_bytes: bytes | None = None,
) -> models.File:
    if source_bytes is None:
        source_bytes = await _read_source_pdf_bytes(source.key)

    openai_client = await get_openai_client_by_class_id(session, class_id)
    uploaded_file = await openai_client.files.create(
        file=(source.original_filename, source_bytes, source.content_type),
        purpose="user_data",
    )
    file_id = _uploaded_openai_file_id(uploaded_file)

    try:
        file = await models.File.create(
            session,
            {
                "file_id": file_id,
                "private": True,
                "uploader_id": uploader_id,
                "name": source.original_filename,
                "content_type": source.content_type,
            },
            class_id=class_id,
        )
        source.openai_file_object_id = file.id
        session.add(source)
        return file
    except BaseException:
        with contextlib.suppress(Exception):
            await openai_client.files.delete(file_id)
        raise


async def create_lecture_slide_additional_context_file(
    session: AsyncSession,
    class_id: int,
    uploader_id: int,
    upload: UploadFile,
) -> models.LectureSlideAdditionalContextFile:
    upload_size = get_upload_size(upload)
    _validate_openai_input_file_upload(upload, upload_size)
    if not config.file_store:
        raise HTTPException(
            status_code=503, detail="File store not configured or unavailable."
        )

    filename = get_original_filename(upload, f"lecture_slide_context_{uuid.uuid7()}")
    content_type = (
        _normalize_content_type(upload.content_type) or "application/octet-stream"
    )
    openai_client = await get_openai_client_by_class_id(session, class_id)
    await upload.seek(0)
    upload_bytes = await upload.read()
    await upload.seek(0)
    try:
        uploaded_file = await openai_client.files.create(
            file=(filename, upload_bytes, content_type),
            purpose="user_data",
        )
    except openai.BadRequestError as exc:
        raise HTTPException(
            status_code=400,
            detail="OpenAI rejected this context file.",
        ) from exc
    file_id = _uploaded_openai_file_id(uploaded_file)
    store_key: str | None = None
    try:
        file = await models.File.create(
            session,
            {
                "file_id": file_id,
                "private": True,
                "uploader_id": uploader_id,
                "name": filename,
                "content_type": content_type,
            },
            class_id=class_id,
        )
        suffix = Path(filename).suffix.lower()
        store_key = f"file_{uuid.uuid4()}{suffix}"
        await config.file_store.store.put(
            store_key, io.BytesIO(upload_bytes), content_type
        )
        await models.S3File.create(session, key=store_key, file_obj_ids=[file.id])
        return await models.LectureSlideAdditionalContextFile.create(
            session,
            lecture_slide_deck_id=None,
            file_object_id=file.id,
            class_id=class_id,
            uploader_id=uploader_id,
            position=0,
            original_filename=filename,
            content_type=content_type,
            content_length=upload_size,
        )
    except BaseException:
        try:
            await openai_client.files.delete(file_id)
        except Exception:
            logger.exception(
                "Failed to rollback OpenAI context file upload. file_id=%s",
                file_id,
            )
        if store_key is not None:
            try:
                await config.file_store.store.delete(store_key)
            except Exception:
                logger.exception(
                    "Failed to rollback stored context file after create failure. key=%s",
                    store_key,
                )
        raise


async def cleanup_lecture_slide_additional_context_file_upload(
    session: AsyncSession,
    context_file: models.LectureSlideAdditionalContextFile,
) -> None:
    file = await models.File.get_by_id_with_delete_context(
        session, context_file.file_object_id
    )
    if file is None:
        return

    try:
        openai_client = await get_openai_client_by_class_id(
            session, context_file.class_id
        )
        await openai_client.files.delete(file.file_id)
    except Exception:
        logger.exception(
            "Failed to cleanup OpenAI context file after authz failure. file_object_id=%s openai_file_id=%s",
            file.id,
            file.file_id,
        )

    if config.file_store and file.s3_file is not None:
        try:
            await config.file_store.store.delete(file.s3_file.key)
        except Exception:
            logger.exception(
                "Failed to cleanup stored context file after authz failure. file_object_id=%s key=%s",
                file.id,
                file.s3_file.key,
            )


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
        additional_context_files=[
            lecture_slide_context_file_summary_from_model(context_file)
            for context_file in sorted(
                deck.additional_context_files, key=lambda item: item.position
            )
        ],
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
    if upload_size >= OPENAI_INPUT_FILE_MAX_BYTES:
        raise HTTPException(
            status_code=413,
            detail=(
                "File too large. "
                f"Lecture slide PDFs must be under {humanize.naturalsize(OPENAI_INPUT_FILE_MAX_BYTES)}."
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
        upload.file.seek(0)
        source_bytes = upload.file.read()
        upload.file.seek(0)
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
        await upload_lecture_slide_source_to_openai(
            session,
            stored_object,
            class_id=class_id,
            uploader_id=uploader_id,
            source_bytes=source_bytes,
        )
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


async def apply_lecture_slide_additional_context_files(
    session: AsyncSession,
    deck: models.LectureSlideDeck,
    context_file_ids: Iterable[int],
    *,
    uploader_id: int,
) -> bool:
    requested_ids = list(dict.fromkeys(int(file_id) for file_id in context_file_ids))
    requested_files = (
        await models.LectureSlideAdditionalContextFile.get_all_by_ids_with_file(
            session, requested_ids, for_update=True
        )
    )
    requested_by_id = {
        context_file.id: context_file for context_file in requested_files
    }
    missing_ids = [
        context_file_id
        for context_file_id in requested_ids
        if context_file_id not in requested_by_id
    ]
    if missing_ids:
        raise HTTPException(
            status_code=404,
            detail="Could not find one or more lecture slide context files.",
        )

    for context_file in requested_files:
        if context_file.class_id != deck.class_id:
            raise HTTPException(
                status_code=403,
                detail="Lecture slide context files must belong to the same class as the deck.",
            )
        if (
            context_file.lecture_slide_deck_id is None
            and context_file.uploader_id != uploader_id
        ):
            raise HTTPException(
                status_code=403,
                detail="Only the user who uploaded a lecture slide context file can attach it.",
            )
        if (
            context_file.lecture_slide_deck_id is not None
            and context_file.lecture_slide_deck_id != deck.id
            and context_file.lecture_slide_deck_id
            != deck.source_lecture_slide_deck_id_snapshot
        ):
            raise HTTPException(
                status_code=403,
                detail="Lecture slide context files cannot be reused from another deck.",
            )

    source_size = (
        deck.source_stored_object.content_length if deck.source_stored_object else 0
    )
    total_size = source_size + sum(file.content_length for file in requested_files)
    if total_size >= OPENAI_INPUT_FILE_MAX_BYTES:
        raise HTTPException(
            status_code=413,
            detail=(
                "Lecture slide files are too large. The slide PDF plus all additional "
                f"context files must be under {humanize.naturalsize(OPENAI_INPUT_FILE_MAX_BYTES)}."
            ),
        )

    existing_files = (
        await models.LectureSlideAdditionalContextFile.get_all_by_deck_id_with_file(
            session, deck.id, for_update=True
        )
    )
    existing_by_file_object_id = {
        context_file.file_object_id: context_file for context_file in existing_files
    }
    desired_file_object_ids = [file.file_object_id for file in requested_files]
    desired_file_object_id_set = set(desired_file_object_ids)
    changed = False

    for existing_file in existing_files:
        if existing_file.file_object_id not in desired_file_object_id_set:
            await models.LectureSlideAdditionalContextFile.delete(
                session, existing_file.id
            )
            changed = True

    for position, requested_file in enumerate(requested_files):
        matched_existing_file = existing_by_file_object_id.get(
            requested_file.file_object_id
        )
        if matched_existing_file is not None:
            if matched_existing_file.position != position:
                matched_existing_file.position = position
                session.add(matched_existing_file)
                changed = True
            if requested_file.lecture_slide_deck_id is None:
                await models.LectureSlideAdditionalContextFile.delete(
                    session, requested_file.id
                )
                changed = True
            continue
        if requested_file.lecture_slide_deck_id is None:
            requested_file.lecture_slide_deck_id = deck.id
            requested_file.position = position
            session.add(requested_file)
            changed = True
            continue
        await models.LectureSlideAdditionalContextFile.create(
            session,
            lecture_slide_deck_id=deck.id,
            file_object_id=requested_file.file_object_id,
            class_id=deck.class_id,
            uploader_id=requested_file.uploader_id,
            position=position,
            original_filename=requested_file.original_filename,
            content_type=requested_file.content_type,
            content_length=requested_file.content_length,
        )
        changed = True

    if changed:
        await session.flush()
    return changed


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
) -> LectureSlidePageUpdateResult:
    notes_changed = False
    narration_changed = False
    narration_changed_positions: set[int] = set()
    old_narration_ids: list[int] = []
    notes_by_position = {note.position: note for note in notes}
    pages_by_position = {
        page.position: page
        for page in (
            await session.scalars(
                select(models.LectureSlidePage).where(
                    models.LectureSlidePage.lecture_slide_deck_id == deck.id,
                    models.LectureSlidePage.position.in_(notes_by_position),
                )
            )
        ).all()
    }
    for note in notes_by_position.values():
        if note.position >= deck.slide_count:
            raise HTTPException(
                status_code=400,
                detail=f"Slide note position {note.position} is outside this deck.",
            )
        user_notes = (note.user_notes or "").strip() or None
        narration_text = (note.narration_text or "").strip() or None
        page = pages_by_position.get(note.position)
        if page is None:
            if user_notes is None and narration_text is None:
                continue
            page = models.LectureSlidePage(
                lecture_slide_deck_id=deck.id,
                position=note.position,
                user_notes=user_notes,
                narration_text=narration_text,
            )
            session.add(page)
            notes_changed = notes_changed or user_notes is not None
            narration_changed = narration_changed or narration_text is not None
            if narration_text is not None:
                narration_changed_positions.add(note.position)
            continue
        if page.user_notes != user_notes:
            page.user_notes = user_notes
            session.add(page)
            notes_changed = True
        if page.narration_text != narration_text:
            if page.narration_id is not None:
                old_narration_ids.append(page.narration_id)
            page.narration_text = narration_text
            page.narration_id = None
            page.start_offset_ms = None
            page.end_offset_ms = None
            session.add(page)
            narration_changed = True
            narration_changed_positions.add(note.position)
    if notes_changed or narration_changed:
        await session.flush()
    audio_keys = await _delete_lecture_slide_narrations_if_unused(
        session, old_narration_ids
    )
    await _delete_lecture_slide_audio_keys_quietly(audio_keys)
    return LectureSlidePageUpdateResult(
        notes_changed=notes_changed,
        narration_changed=narration_changed,
        narration_changed_positions=frozenset(narration_changed_positions),
    )


def _text_needs_audio(text: str | None) -> bool:
    return bool((text or "").strip())


def _question_input_payload(
    question: schemas.LectureSlideQuestionInput,
) -> dict[str, object]:
    return {
        "id": question.id,
        "mode": question.mode.value,
        "slide_position": question.slide_position,
        "question_text": question.question_text.strip(),
        "intro_text": question.intro_text.strip(),
        "options": [
            {
                "id": option.id,
                "option_text": option.option_text.strip(),
                "post_answer_text": option.post_answer_text.strip(),
                "correct": option.correct,
            }
            for option in question.options
        ],
    }


def lecture_slide_question_context_payload(
    questions: Iterable[schemas.LectureSlideQuestionInput],
) -> list[dict[str, object]]:
    return [_question_input_payload(question) for question in questions]


def _is_complete_question_input(question: schemas.LectureSlideQuestionInput) -> bool:
    return question.mode == schemas.LectureSlideQuestionDraftMode.COMPLETE


def _question_model_payload(
    question: models.LectureSlideQuestion,
) -> dict[str, object]:
    correct_option_id = question.correct_option.id if question.correct_option else None
    return {
        "id": question.id,
        "mode": schemas.LectureSlideQuestionDraftMode.COMPLETE.value,
        "slide_position": question.slide_position,
        "question_text": question.question_text,
        "intro_text": question.intro_text,
        "options": [
            {
                "id": option.id,
                "option_text": option.option_text,
                "post_answer_text": option.post_answer_text,
                "correct": option.id == correct_option_id,
            }
            for option in sorted(question.options, key=lambda item: item.position)
        ],
    }


def lecture_slide_question_model_context_payload(
    questions: Iterable[models.LectureSlideQuestion],
) -> list[dict[str, object]]:
    return [
        _question_model_payload(question)
        for question in sorted(questions, key=lambda item: item.position)
    ]


async def lecture_slide_deck_question_context_payload(
    session: AsyncSession,
    deck_id: int,
) -> list[dict[str, object]]:
    questions = (
        await session.scalars(
            select(models.LectureSlideQuestion)
            .where(models.LectureSlideQuestion.lecture_slide_deck_id == deck_id)
            .options(selectinload(models.LectureSlideQuestion.options))
            .options(selectinload(models.LectureSlideQuestion.correct_option))
            .order_by(models.LectureSlideQuestion.position)
        )
    ).all()
    return lecture_slide_question_model_context_payload(questions)


async def _reset_narration_for_text(
    session: AsyncSession,
    narration: models.LectureSlideNarration | None,
    text: str,
) -> tuple[
    models.LectureSlideNarration | None,
    bool,
    list[int],
    list[tuple[int, str]],
]:
    if not _text_needs_audio(text):
        return None, narration is not None, [narration.id] if narration else [], []
    if narration is None:
        narration = models.LectureSlideNarration(
            status=schemas.LectureSlideNarrationStatus.PENDING,
        )
        session.add(narration)
        await session.flush()
        return narration, True, [], []
    stored_object_row = (
        [(narration.stored_object_id, narration.stored_object.key)]
        if narration.stored_object_id is not None
        and narration.stored_object is not None
        else []
    )
    narration.stored_object_id = None
    narration.status = schemas.LectureSlideNarrationStatus.PENDING
    narration.error_message = None
    session.add(narration)
    return narration, True, [], stored_object_row


async def _apply_question_option_drafts(
    session: AsyncSession,
    question: models.LectureSlideQuestion,
    options: list[schemas.LectureSlideQuestionOptionInput],
    *,
    question_changed: bool,
) -> tuple[bool, bool, list[int], list[tuple[int, str]]]:
    changed = question_changed
    audio_changed = False
    old_narration_ids: list[int] = []
    old_stored_object_rows: list[tuple[int, str]] = []
    existing_option_rows = list(
        (
            await session.scalars(
                select(models.LectureSlideQuestionOption)
                .where(models.LectureSlideQuestionOption.question_id == question.id)
                .options(
                    selectinload(
                        models.LectureSlideQuestionOption.post_narration
                    ).selectinload(models.LectureSlideNarration.stored_object)
                )
                .order_by(models.LectureSlideQuestionOption.position)
            )
        ).all()
    )
    remaining_options = {option.id: option for option in existing_option_rows}
    existing_options_by_position = {
        option.position: option for option in existing_option_rows
    }
    for temp_position, existing_option in enumerate(existing_option_rows, start=1):
        existing_option.position = -temp_position
        session.add(existing_option)
    if existing_option_rows:
        await session.flush()
    option_input_ids = {option.id for option in options if option.id is not None}
    option_rows: list[tuple[models.LectureSlideQuestionOption, bool]] = []
    for option_position, option in enumerate(options):
        option_text = option.option_text.strip()
        post_answer_text = option.post_answer_text.strip()
        option_row = (
            remaining_options.pop(option.id, None) if option.id is not None else None
        )
        if option_row is None:
            fallback_option = existing_options_by_position.get(option_position)
            if (
                fallback_option is not None
                and fallback_option.id not in option_input_ids
            ):
                option_row = remaining_options.pop(fallback_option.id, None)
        if option_row is None:
            option_row = models.LectureSlideQuestionOption(
                question_id=question.id,
                position=option_position,
                option_text=option_text,
                post_answer_text=post_answer_text,
                continue_slide_position=question.slide_position,
                continue_slide_offset_ms=question.slide_offset_ms,
                continue_offset_ms=question.stop_offset_ms,
            )
            session.add(option_row)
            await session.flush()
            changed = True
            if _text_needs_audio(post_answer_text):
                post_narration = models.LectureSlideNarration(
                    status=schemas.LectureSlideNarrationStatus.PENDING,
                )
                session.add(post_narration)
                await session.flush()
                option_row.post_narration_id = post_narration.id
                audio_changed = True
        else:
            if option_row.position != option_position:
                option_row.position = option_position
                changed = True
            if option_row.option_text != option_text:
                option_row.option_text = option_text
                changed = True
            if option_row.post_answer_text != post_answer_text:
                (
                    narration,
                    narration_changed,
                    deleted_narration_ids,
                    deleted_stored_object_rows,
                ) = await _reset_narration_for_text(
                    session, option_row.post_narration, post_answer_text
                )
                option_row.post_answer_text = post_answer_text
                option_row.post_narration_id = narration.id if narration else None
                old_narration_ids.extend(deleted_narration_ids)
                old_stored_object_rows.extend(deleted_stored_object_rows)
                changed = True
                audio_changed = audio_changed or narration_changed
            if option_row.continue_slide_position != question.slide_position:
                option_row.continue_slide_position = question.slide_position
                changed = True
            if option_row.continue_slide_offset_ms != question.slide_offset_ms:
                option_row.continue_slide_offset_ms = question.slide_offset_ms
                changed = True
            if option_row.continue_offset_ms != question.stop_offset_ms:
                option_row.continue_offset_ms = question.stop_offset_ms
                changed = True
            session.add(option_row)
        option_rows.append((option_row, option.correct))

    for removed_option in remaining_options.values():
        if removed_option.post_narration_id is not None:
            old_narration_ids.append(removed_option.post_narration_id)
        await session.delete(removed_option)
        changed = True
        audio_changed = True

    await session.flush()
    existing_correct_option_id = await session.scalar(
        select(
            models.lecture_slide_question_single_select_correct_option_association.c.option_id
        ).where(
            models.lecture_slide_question_single_select_correct_option_association.c.question_id
            == question.id
        )
    )
    next_correct_option_id = next(
        (option_row.id for option_row, is_correct in option_rows if is_correct),
        None,
    )
    if existing_correct_option_id != next_correct_option_id:
        changed = True
    await session.execute(
        delete(
            models.lecture_slide_question_single_select_correct_option_association
        ).where(
            models.lecture_slide_question_single_select_correct_option_association.c.question_id
            == question.id
        )
    )
    for option_row, is_correct in option_rows:
        if is_correct:
            await session.execute(
                models.lecture_slide_question_single_select_correct_option_association.insert().values(
                    question_id=question.id,
                    option_id=option_row.id,
                )
            )
    return changed, audio_changed, old_narration_ids, old_stored_object_rows


async def apply_lecture_slide_question_drafts(
    session: AsyncSession,
    deck: models.LectureSlideDeck,
    questions: Iterable[schemas.LectureSlideQuestionInput],
) -> LectureSlideQuestionUpdateResult:
    question_inputs = list(questions)
    complete_question_inputs = [
        question_input
        for question_input in question_inputs
        if _is_complete_question_input(question_input)
    ]
    requires_question_generation = len(complete_question_inputs) != len(question_inputs)
    for question_input in question_inputs:
        if question_input.slide_position >= deck.slide_count:
            raise HTTPException(
                status_code=400,
                detail=f"Question slide position {question_input.slide_position} is outside this deck.",
            )

    manual_question_payload = lecture_slide_question_context_payload(question_inputs)
    pages_by_position = (
        {
            page.position: page
            for page in (
                await session.scalars(
                    select(models.LectureSlidePage).where(
                        models.LectureSlidePage.lecture_slide_deck_id == deck.id,
                        models.LectureSlidePage.position.in_(
                            [
                                question_input.slide_position
                                for question_input in question_inputs
                            ]
                        ),
                    )
                )
            ).all()
        }
        if question_inputs
        else {}
    )
    questions_are_timed = all(
        (page := pages_by_position.get(question_input.slide_position)) is not None
        and page.start_offset_ms is not None
        and page.end_offset_ms is not None
        for question_input in question_inputs
    )
    if not questions_are_timed:
        context_data = dict(deck.context_data or {})
        previous_payload = context_data.get(
            schemas.LECTURE_SLIDE_MANUAL_QUESTIONS_CONTEXT_KEY
        )
        if manual_question_payload:
            context_data[schemas.LECTURE_SLIDE_MANUAL_QUESTIONS_CONTEXT_KEY] = (
                manual_question_payload
            )
        else:
            context_data.pop(schemas.LECTURE_SLIDE_MANUAL_QUESTIONS_CONTEXT_KEY, None)
        deck.context_data = context_data
        session.add(deck)
        await session.flush()
        return LectureSlideQuestionUpdateResult(
            questions_changed=previous_payload != manual_question_payload,
            audio_changed=False,
            requires_question_generation=True,
        )

    old_narration_ids: list[int] = []
    old_stored_object_rows: list[tuple[int, str]] = []
    changed = False
    audio_changed = False
    existing_question_rows = list(
        (
            await session.scalars(
                select(models.LectureSlideQuestion)
                .where(models.LectureSlideQuestion.lecture_slide_deck_id == deck.id)
                .options(selectinload(models.LectureSlideQuestion.options))
                .options(selectinload(models.LectureSlideQuestion.correct_option))
                .options(
                    selectinload(
                        models.LectureSlideQuestion.intro_narration
                    ).selectinload(models.LectureSlideNarration.stored_object)
                )
                .options(
                    selectinload(models.LectureSlideQuestion.options)
                    .selectinload(models.LectureSlideQuestionOption.post_narration)
                    .selectinload(models.LectureSlideNarration.stored_object)
                )
                .order_by(models.LectureSlideQuestion.position)
            )
        ).all()
    )
    remaining_questions = {question.id: question for question in existing_question_rows}
    existing_questions_by_position = {
        question.position: question for question in existing_question_rows
    }
    for temp_position, existing_question in enumerate(existing_question_rows, start=1):
        existing_question.position = -temp_position
        session.add(existing_question)
    if existing_question_rows:
        await session.flush()
    question_input_ids = {
        question.id for question in complete_question_inputs if question.id is not None
    }

    for question_position, question_input in enumerate(complete_question_inputs):
        page = pages_by_position[question_input.slide_position]
        slide_offset_ms = (page.end_offset_ms or 0) - (page.start_offset_ms or 0)
        stop_offset_ms = page.end_offset_ms or 0
        question_text = question_input.question_text.strip()
        intro_text = question_input.intro_text.strip()
        question = (
            remaining_questions.pop(question_input.id, None)
            if question_input.id is not None
            else None
        )
        if question is None:
            fallback_question = existing_questions_by_position.get(question_position)
            if (
                fallback_question is not None
                and fallback_question.id not in question_input_ids
            ):
                question = remaining_questions.pop(fallback_question.id, None)
        question_changed = False
        if question is None:
            question = models.LectureSlideQuestion(
                lecture_slide_deck_id=deck.id,
                position=question_position,
                slide_position=question_input.slide_position,
                slide_offset_ms=slide_offset_ms,
                stop_offset_ms=stop_offset_ms,
                question_type=schemas.LectureSlideQuestionType.SINGLE_SELECT,
                question_text=question_text,
                intro_text=intro_text,
            )
            session.add(question)
            await session.flush()
            changed = True
            question_changed = True
            if _text_needs_audio(intro_text):
                intro_narration = models.LectureSlideNarration(
                    status=schemas.LectureSlideNarrationStatus.PENDING,
                )
                session.add(intro_narration)
                await session.flush()
                question.intro_narration_id = intro_narration.id
                audio_changed = True
        else:
            if question.position != question_position:
                question.position = question_position
                question_changed = True
            if question.slide_position != question_input.slide_position:
                question.slide_position = question_input.slide_position
                question_changed = True
            if question.slide_offset_ms != slide_offset_ms:
                question.slide_offset_ms = slide_offset_ms
                question_changed = True
            if question.stop_offset_ms != stop_offset_ms:
                question.stop_offset_ms = stop_offset_ms
                question_changed = True
            if question.question_text != question_text:
                question.question_text = question_text
                question_changed = True
            if question.intro_text != intro_text:
                (
                    narration,
                    narration_changed,
                    deleted_narration_ids,
                    deleted_stored_object_rows,
                ) = await _reset_narration_for_text(
                    session, question.intro_narration, intro_text
                )
                question.intro_text = intro_text
                question.intro_narration_id = narration.id if narration else None
                old_narration_ids.extend(deleted_narration_ids)
                old_stored_object_rows.extend(deleted_stored_object_rows)
                question_changed = True
                audio_changed = audio_changed or narration_changed
            changed = changed or question_changed
            session.add(question)

        (
            options_changed,
            options_audio_changed,
            deleted_narration_ids,
            deleted_stored_object_rows,
        ) = await _apply_question_option_drafts(
            session,
            question,
            question_input.options,
            question_changed=question_changed,
        )
        changed = changed or options_changed
        audio_changed = audio_changed or options_audio_changed
        old_narration_ids.extend(deleted_narration_ids)
        old_stored_object_rows.extend(deleted_stored_object_rows)

    for removed_question in remaining_questions.values():
        if removed_question.intro_narration_id is not None:
            old_narration_ids.append(removed_question.intro_narration_id)
        for option in removed_question.options:
            if option.post_narration_id is not None:
                old_narration_ids.append(option.post_narration_id)
        await session.delete(removed_question)
        changed = True
        audio_changed = True

    context_data = dict(deck.context_data or {})
    if requires_question_generation:
        context_data[schemas.LECTURE_SLIDE_MANUAL_QUESTIONS_CONTEXT_KEY] = (
            manual_question_payload
        )
    else:
        context_data.pop(schemas.LECTURE_SLIDE_MANUAL_QUESTIONS_CONTEXT_KEY, None)
    if context_data != (deck.context_data or {}):
        deck.context_data = context_data
        session.add(deck)
        changed = True

    await session.flush()
    audio_keys = await _delete_lecture_slide_narrations_if_unused(
        session, old_narration_ids
    )
    stored_object_keys = await _delete_lecture_slide_narration_stored_objects_if_unused(
        session,
        old_stored_object_rows,
    )
    await _delete_lecture_slide_audio_keys_quietly([*audio_keys, *stored_object_keys])
    return LectureSlideQuestionUpdateResult(
        questions_changed=changed,
        audio_changed=audio_changed,
        requires_question_generation=requires_question_generation,
    )


async def lecture_slide_deck_has_pages(session: AsyncSession, deck_id: int) -> bool:
    page_id = await session.scalar(
        select(models.LectureSlidePage.id)
        .where(models.LectureSlidePage.lecture_slide_deck_id == deck_id)
        .limit(1)
    )
    return page_id is not None


async def clear_lecture_slide_page_narrations(
    session: AsyncSession, deck_id: int
) -> None:
    narration_ids = list(
        (
            await session.scalars(
                select(models.LectureSlidePage.narration_id).where(
                    models.LectureSlidePage.lecture_slide_deck_id == deck_id,
                    models.LectureSlidePage.narration_id.is_not(None),
                )
            )
        ).all()
    )
    await session.execute(
        update(models.LectureSlidePage)
        .where(models.LectureSlidePage.lecture_slide_deck_id == deck_id)
        .values(narration_id=None, start_offset_ms=None, end_offset_ms=None)
    )
    audio_keys = await _delete_lecture_slide_narrations_if_unused(
        session, narration_ids
    )
    await _delete_lecture_slide_audio_keys_quietly(audio_keys)


async def reset_lecture_slide_question_narrations(
    session: AsyncSession, deck_id: int
) -> None:
    narration_ids = list(
        dict.fromkeys(
            [
                *(
                    await session.scalars(
                        select(models.LectureSlideQuestion.intro_narration_id).where(
                            models.LectureSlideQuestion.lecture_slide_deck_id
                            == deck_id,
                            models.LectureSlideQuestion.intro_narration_id.is_not(None),
                        )
                    )
                ).all(),
                *(
                    await session.scalars(
                        select(models.LectureSlideQuestionOption.post_narration_id)
                        .join(
                            models.LectureSlideQuestion,
                            models.LectureSlideQuestion.id
                            == models.LectureSlideQuestionOption.question_id,
                        )
                        .where(
                            models.LectureSlideQuestion.lecture_slide_deck_id
                            == deck_id,
                            models.LectureSlideQuestionOption.post_narration_id.is_not(
                                None
                            ),
                        )
                    )
                ).all(),
            ]
        )
    )
    if not narration_ids:
        return

    stored_object_rows = list(
        (
            await session.execute(
                select(
                    models.LectureSlideNarration.stored_object_id,
                    models.LectureSlideNarrationStoredObject.key,
                )
                .join(
                    models.LectureSlideNarrationStoredObject,
                    models.LectureSlideNarrationStoredObject.id
                    == models.LectureSlideNarration.stored_object_id,
                )
                .where(models.LectureSlideNarration.id.in_(narration_ids))
            )
        ).all()
    )
    await session.execute(
        update(models.LectureSlideNarration)
        .where(models.LectureSlideNarration.id.in_(narration_ids))
        .values(
            stored_object_id=None,
            status=schemas.LectureSlideNarrationStatus.PENDING,
            error_message=None,
        )
    )
    audio_keys = await _delete_lecture_slide_narration_stored_objects_if_unused(
        session,
        [
            (stored_object_id, key)
            for stored_object_id, key in stored_object_rows
            if stored_object_id is not None
        ],
    )
    await _delete_lecture_slide_audio_keys_quietly(audio_keys)


async def _delete_lecture_slide_narrations_if_unused(
    session: AsyncSession, narration_ids: Iterable[int | None]
) -> list[str]:
    candidate_narration_ids = list(dict.fromkeys(id_ for id_ in narration_ids if id_))
    if not candidate_narration_ids:
        return []

    referenced_narration_ids: set[int] = set()
    for column in (
        models.LectureSlidePage.narration_id,
        models.LectureSlideQuestion.intro_narration_id,
        models.LectureSlideQuestionOption.post_narration_id,
    ):
        referenced_narration_ids.update(
            (
                await session.scalars(
                    select(column).where(column.in_(candidate_narration_ids))
                )
            ).all()
        )

    unused_narration_ids = [
        id_ for id_ in candidate_narration_ids if id_ not in referenced_narration_ids
    ]
    if not unused_narration_ids:
        return []

    stored_object_rows = list(
        (
            await session.execute(
                select(
                    models.LectureSlideNarration.stored_object_id,
                    models.LectureSlideNarrationStoredObject.key,
                )
                .join(
                    models.LectureSlideNarrationStoredObject,
                    models.LectureSlideNarrationStoredObject.id
                    == models.LectureSlideNarration.stored_object_id,
                )
                .where(models.LectureSlideNarration.id.in_(unused_narration_ids))
            )
        ).all()
    )

    await session.execute(
        delete(models.LectureSlideNarration).where(
            models.LectureSlideNarration.id.in_(unused_narration_ids)
        )
    )
    return await _delete_lecture_slide_narration_stored_objects_if_unused(
        session,
        [
            (stored_object_id, key)
            for stored_object_id, key in stored_object_rows
            if stored_object_id is not None
        ],
    )


async def _delete_lecture_slide_narration_stored_objects_if_unused(
    session: AsyncSession, stored_object_rows: Iterable[tuple[int, str]]
) -> list[str]:
    stored_object_keys_by_id = {
        stored_object_id: key for stored_object_id, key in stored_object_rows
    }
    if not stored_object_keys_by_id:
        return []

    stored_object_ids = list(stored_object_keys_by_id)
    referenced_stored_object_ids = set(
        (
            await session.scalars(
                select(models.LectureSlideNarration.stored_object_id).where(
                    models.LectureSlideNarration.stored_object_id.in_(stored_object_ids)
                )
            )
        ).all()
    )
    referenced_stored_object_ids.update(
        (
            await session.scalars(
                select(
                    models.LectureSlideDeck.continuous_narration_stored_object_id
                ).where(
                    models.LectureSlideDeck.continuous_narration_stored_object_id.in_(
                        stored_object_ids
                    )
                )
            )
        ).all()
    )

    unused_stored_object_ids = [
        id_ for id_ in stored_object_ids if id_ not in referenced_stored_object_ids
    ]
    if not unused_stored_object_ids:
        return []

    await session.execute(
        delete(models.LectureSlideNarrationStoredObject).where(
            models.LectureSlideNarrationStoredObject.id.in_(unused_stored_object_ids)
        )
    )
    return [stored_object_keys_by_id[id_] for id_ in unused_stored_object_ids]


async def _delete_lecture_slide_audio_keys_quietly(keys: Iterable[str]) -> None:
    if not config.lecture_video_audio_store:
        return
    for key in keys:
        try:
            await config.lecture_video_audio_store.store.delete_file(key)
        except Exception:
            logger.exception("Failed to clean up lecture slide audio key=%s", key)


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
    for context_file in deck.additional_context_files:
        session.add(
            models.LectureSlideAdditionalContextFile(
                lecture_slide_deck_id=cloned_deck.id,
                file_object_id=context_file.file_object_id,
                class_id=context_file.class_id,
                uploader_id=context_file.uploader_id,
                position=context_file.position,
                original_filename=context_file.original_filename,
                content_type=context_file.content_type,
                content_length=context_file.content_length,
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
) -> list[int]:
    in_use = await session.scalar(
        select(models.Assistant.id)
        .where(models.Assistant.lecture_slide_deck_id == deck_id)
        .limit(1)
    )
    if in_use is not None:
        return []
    thread_in_use = await session.scalar(
        select(models.Thread.id)
        .where(models.Thread.lecture_slide_deck_id == deck_id)
        .limit(1)
    )
    if thread_in_use is not None:
        return []
    additional_context_file_object_ids = (
        await models.LectureSlideAdditionalContextFile.get_file_object_ids_by_deck_id(
            session, deck_id
        )
    )
    await models.LectureSlideAdditionalContextFile.delete_all_by_deck_id(
        session, deck_id
    )
    await session.execute(
        update(models.LectureSlideProcessingRun)
        .where(models.LectureSlideProcessingRun.lecture_slide_deck_id == deck_id)
        .values(lecture_slide_deck_id=None)
    )
    page_narration_ids = list(
        (
            await session.scalars(
                select(models.LectureSlidePage.narration_id).where(
                    models.LectureSlidePage.lecture_slide_deck_id == deck_id,
                    models.LectureSlidePage.narration_id.is_not(None),
                )
            )
        ).all()
    )
    question_narration_ids = list(
        (
            await session.scalars(
                select(models.LectureSlideQuestion.intro_narration_id).where(
                    models.LectureSlideQuestion.lecture_slide_deck_id == deck_id,
                    models.LectureSlideQuestion.intro_narration_id.is_not(None),
                )
            )
        ).all()
    )
    option_narration_ids = list(
        (
            await session.scalars(
                select(models.LectureSlideQuestionOption.post_narration_id)
                .join(
                    models.LectureSlideQuestion,
                    models.LectureSlideQuestion.id
                    == models.LectureSlideQuestionOption.question_id,
                )
                .where(
                    models.LectureSlideQuestion.lecture_slide_deck_id == deck_id,
                    models.LectureSlideQuestionOption.post_narration_id.is_not(None),
                )
            )
        ).all()
    )
    question_ids = list(
        (
            await session.scalars(
                select(models.LectureSlideQuestion.id).where(
                    models.LectureSlideQuestion.lecture_slide_deck_id == deck_id
                )
            )
        ).all()
    )
    if question_ids:
        await session.execute(
            delete(
                models.lecture_slide_question_single_select_correct_option_association
            ).where(
                models.lecture_slide_question_single_select_correct_option_association.c.question_id.in_(
                    question_ids
                )
            )
        )
        await session.execute(
            delete(models.LectureSlideQuestionOption).where(
                models.LectureSlideQuestionOption.question_id.in_(question_ids)
            )
        )
        await session.execute(
            delete(models.LectureSlideQuestion).where(
                models.LectureSlideQuestion.id.in_(question_ids)
            )
        )
    await session.execute(
        delete(models.LectureSlidePage).where(
            models.LectureSlidePage.lecture_slide_deck_id == deck_id
        )
    )
    await session.execute(
        delete(models.LectureSlideDeck).where(models.LectureSlideDeck.id == deck_id)
    )
    audio_keys = await _delete_lecture_slide_narrations_if_unused(
        session,
        [*page_narration_ids, *question_narration_ids, *option_narration_ids],
    )
    await session.flush()
    await _delete_lecture_slide_audio_keys_quietly(audio_keys)
    return additional_context_file_object_ids
