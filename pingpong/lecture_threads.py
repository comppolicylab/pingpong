import json
from dataclasses import dataclass

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import func

import pingpong.models as models
import pingpong.schemas as schemas
from pingpong import lecture_slide_processing, lecture_slide_runtime
from pingpong import lecture_video_runtime


@dataclass
class LectureThreadTarget:
    is_slide_lesson: bool
    lecture_slide_translation_id: int | None
    lecture_language_code: str | None
    lecture_language_name: str | None


async def translation_is_playable(
    db: AsyncSession,
    deck: models.LectureSlideDeck,
    translation: models.LectureSlideTranslation,
) -> bool:
    return not (
        await lecture_slide_processing.translation_needs_feedback(db, translation)
        or translation.status != schemas.LectureSlideTranslationStatus.READY
        or translation.continuous_narration_stored_object_id is None
        or translation.caption_stored_object_id is None
        or not translation.has_complete_timeline_for_deck(deck)
    )


async def resolve_lecture_thread_target(
    db: AsyncSession, assistant: models.Assistant, language_code: str
) -> LectureThreadTarget:
    is_slide_lesson = (
        assistant.interaction_mode == schemas.InteractionMode.LECTURE_SLIDES
    )
    if is_slide_lesson:
        if not assistant.lecture_slide_deck:
            raise HTTPException(
                status_code=400,
                detail="This assistant does not have lecture slides attached. Unable to create Lecture Lesson",
            )
        if assistant.lecture_slide_deck.status != schemas.LectureSlideDeckStatus.READY:
            if (
                assistant.lecture_slide_deck.status
                == schemas.LectureSlideDeckStatus.FAILED
            ):
                raise HTTPException(
                    status_code=409,
                    detail=(
                        "This assistant's lecture slide processing failed. "
                        "Edit the assistant and retry."
                    ),
                )
            raise HTTPException(
                status_code=409,
                detail="This assistant's lecture slides are not ready yet.",
            )
    elif not assistant.lecture_video:
        raise HTTPException(
            status_code=400,
            detail="This assistant does not have a lecture video attached. Unable to create Lecture Lesson",
        )
    elif assistant.lecture_video.status != schemas.LectureVideoStatus.READY:
        if assistant.lecture_video.status == schemas.LectureVideoStatus.FAILED:
            raise HTTPException(
                status_code=409,
                detail=(
                    "This assistant's lecture video narration processing failed. "
                    "Edit the assistant and retry."
                ),
            )
        raise HTTPException(
            status_code=409,
            detail="This assistant's lecture video is not ready yet.",
        )

    target = LectureThreadTarget(is_slide_lesson, None, None, None)
    requested_language_code = language_code.strip().lower()
    if is_slide_lesson:
        if requested_language_code == "original":
            target.lecture_language_code = "original"
            target.lecture_language_name = "Original"
        else:
            translation = await models.LectureSlideTranslation.get_by_deck_and_language(
                db,
                assistant.lecture_slide_deck_id,
                requested_language_code,
            )
            if translation is None or not await translation_is_playable(
                db, assistant.lecture_slide_deck, translation
            ):
                raise HTTPException(
                    status_code=409,
                    detail=(
                        "This lecture slide translation is not ready. "
                        "Prepare it from the lesson landing page first."
                    ),
                )
            target.lecture_slide_translation_id = translation.id
            target.lecture_language_code = translation.language_code
            target.lecture_language_name = translation.language_name
    elif requested_language_code != "original":
        raise HTTPException(
            status_code=400,
            detail="Language selection is only available for lecture slides.",
        )

    if assistant.version != 3:
        raise HTTPException(
            status_code=400,
            detail="Lecture presentation can only be created using v3 assistants.",
        )
    return target


async def create_lecture_thread(
    db: AsyncSession,
    *,
    assistant: models.Assistant,
    class_: models.Class,
    target: LectureThreadTarget,
    users: list[models.User],
    anonymous_session: models.AnonymousSession | None,
    timezone: str | None,
    conversation_id: str | None,
    external_principal_id: int | None = None,
) -> models.Thread:
    new_thread = {
        "name": "Lecture Lesson",
        "input_moderation_enabled": bool(assistant.input_moderation_enabled),
        "class_id": class_.id,
        "private": True if users else False,
        "interaction_mode": (
            schemas.InteractionMode.LECTURE_SLIDES
            if target.is_slide_lesson
            else schemas.InteractionMode.LECTURE_VIDEO
        ),
        "users": users,
        "thread_id": None,
        "anonymous_sessions": [anonymous_session] if anonymous_session else [],
        "conversation_id": conversation_id,
        "assistant_id": assistant.id,
        "vector_store_id": None,
        "code_interpreter_file_ids": [],
        "image_file_ids": [],
        "tools_available": json.dumps(
            [{"type": "web_search"}]
            if assistant.tools and {"type": "web_search"} in json.loads(assistant.tools)
            else []
        ),
        "version": assistant.version,
        "last_activity": func.now(),
        "instructions": assistant.instructions,
        "timezone": timezone,
        "lecture_video_id": None
        if target.is_slide_lesson
        else assistant.lecture_video_id,
        "lecture_slide_deck_id": assistant.lecture_slide_deck_id
        if target.is_slide_lesson
        else None,
        "lecture_slide_translation_id": target.lecture_slide_translation_id,
        "lecture_language_code": target.lecture_language_code,
        "lecture_language_name": target.lecture_language_name,
        "display_user_info": assistant.should_record_user_information
        and not class_.private,
        "prevent_user_thread_deletion": (
            assistant.prevent_user_thread_deletion
            and assistant.should_record_user_information
            and not class_.private
        ),
        "external_principal_id": external_principal_id,
    }

    thread = await models.Thread.create(db, new_thread)
    db.add(thread)
    await db.flush()
    if target.is_slide_lesson:
        await lecture_slide_runtime.initialize_thread_state(db, thread.id)
    else:
        await lecture_video_runtime.initialize_thread_state(db, thread.id)
    await db.refresh(thread)
    return thread
