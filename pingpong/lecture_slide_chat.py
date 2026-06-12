from dataclasses import dataclass
from datetime import datetime, timezone
import logging
from typing import Any

from fastapi import HTTPException
from pydantic import TypeAdapter, ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

import pingpong.models as models
import pingpong.schemas as schemas
from pingpong import lecture_slide_runtime

logger = logging.getLogger(__name__)

LECTURE_SLIDE_CHAT_UNAVAILABLE_NOTE = (
    "Lecture chat is only available for lecture slides with generated narration "
    "and word-level transcription."
)

_V3_TRANSCRIPT_ADAPTER = TypeAdapter(list[schemas.LectureVideoManifestWordV3])
_V5_CONTEXT_ADAPTER = TypeAdapter(schemas.LectureSlideContextV5)


@dataclass
class LectureSlideChatTurnPreparation:
    prepended_messages: list[models.Message]
    user_output_index: int
    user_assistant_messages_only: bool = True
    include_developer_messages: bool = True


def _words_from_transcript_data(
    transcript_data: dict[str, Any] | list[Any] | None,
) -> list[schemas.LectureVideoManifestWordV3] | None:
    if transcript_data is None:
        return None
    source = (
        transcript_data.get("word_level_transcription")
        if isinstance(transcript_data, dict)
        else transcript_data
    )
    if not source:
        return None
    return _V3_TRANSCRIPT_ADAPTER.validate_python(source)


def lecture_slide_chat_context_from_model(
    deck: models.LectureSlideDeck,
) -> list[schemas.LectureVideoManifestWordV3] | None:
    if deck.context_version != 4:
        return None
    transcript = transcript_from_model(deck)
    return transcript or None


def lecture_slide_context_v5_from_model(
    deck: models.LectureSlideDeck,
) -> schemas.LectureSlideContextV5 | None:
    if deck.context_version != 5 or deck.context_data is None:
        return None
    return _V5_CONTEXT_ADAPTER.validate_python(deck.context_data)


def transcript_from_model(
    deck: models.LectureSlideDeck,
) -> list[schemas.LectureVideoManifestWordV3] | None:
    return _words_from_transcript_data(deck.transcript_data)


def lecture_slide_chat_available(deck: models.LectureSlideDeck | None) -> bool:
    if deck is None:
        return False
    return deck.context_version in {4, 5} and deck.lecture_slide_chat_available


def _get_current_question(
    thread: models.Thread,
    state: models.LectureSlideThreadState,
) -> models.LectureSlideQuestion | None:
    if state.current_question is not None:
        return state.current_question
    if thread.lecture_slide_deck is None:
        return None
    for question in thread.lecture_slide_deck.questions:
        if question.id == state.current_question_id:
            return question
    return None


def _get_next_question(
    thread: models.Thread,
    current_question: models.LectureSlideQuestion | None,
) -> models.LectureSlideQuestion | None:
    if thread.lecture_slide_deck is None or current_question is None:
        return None
    next_position = current_question.position + 1
    for question in thread.lecture_slide_deck.questions:
        if question.position == next_position:
            return question
    return None


def _get_next_future_question(
    thread: models.Thread,
    current_offset_ms: int,
) -> models.LectureSlideQuestion | None:
    if thread.lecture_slide_deck is None:
        return None
    for question in sorted(
        thread.lecture_slide_deck.questions, key=lambda item: item.position
    ):
        if question.stop_offset_ms > current_offset_ms:
            return question
    return None


def _knowledge_check_label(question: models.LectureSlideQuestion) -> str:
    return f"Knowledge Check #{question.position + 1}"


def _format_knowledge_check_options(
    question: models.LectureSlideQuestion,
    *,
    selected_option: models.LectureSlideQuestionOption | None = None,
) -> str:
    correct_option = question.correct_option

    def format_option(option: models.LectureSlideQuestionOption) -> str:
        if correct_option is None:
            correctness = "unknown"
        elif option.id == correct_option.id:
            correctness = "correct"
        else:
            correctness = "incorrect"
        labels = []
        if selected_option is not None and option.id == selected_option.id:
            labels.append("selected")
        labels.append(correctness)
        feedback = (option.post_answer_text or "").strip() or "None"
        return f"- {option.option_text} ({', '.join(labels)}). Feedback: {feedback}"

    return "\n".join(
        format_option(option)
        for option in sorted(question.options, key=lambda item: item.position)
    )


def _format_knowledge_check_prompt(
    question: models.LectureSlideQuestion,
    *,
    prefix: str | None = None,
) -> str:
    question_text = question.question_text.strip() or f"Question {question.id}"
    parts = []
    if prefix is not None:
        parts.extend([prefix, ""])
    parts.extend(
        [
            f"{_knowledge_check_label(question)}: {question_text}",
            "",
            f"Options:\n{_format_knowledge_check_options(question)}",
        ]
    )
    return "\n".join(parts)


def _format_upcoming_knowledge_check(
    question: models.LectureSlideQuestion | None,
) -> str | None:
    if question is None:
        return None
    return _format_knowledge_check_prompt(
        question,
        prefix=f"At {question.stop_offset_ms}ms, the learner will be asked:",
    )


async def _build_answered_knowledge_checks_markdown(
    session: AsyncSession,
    thread_id: int,
    *,
    since_created: datetime | None = None,
) -> str | None:
    filters = [
        models.LectureSlideInteraction.thread_id == thread_id,
        models.LectureSlideInteraction.event_type
        == schemas.InteractiveLessonInteractionEventType.ANSWER_SUBMITTED,
    ]
    if since_created is not None:
        filters.append(models.LectureSlideInteraction.created > since_created)
    interactions = await session.scalars(
        select(models.LectureSlideInteraction)
        .where(*filters)
        .options(
            selectinload(models.LectureSlideInteraction.question).options(
                selectinload(models.LectureSlideQuestion.options),
                selectinload(models.LectureSlideQuestion.correct_option),
            ),
            selectinload(models.LectureSlideInteraction.option),
        )
        .order_by(models.LectureSlideInteraction.event_index)
    )
    answer_lines: list[str] = []
    for interaction in interactions:
        question = interaction.question
        option = interaction.option
        if question is None or option is None:
            continue
        option_lines = _format_knowledge_check_options(question, selected_option=option)
        indented_option_lines = "\n".join(
            f"  {line}" for line in option_lines.splitlines()
        )
        answer_lines.append(
            f"- At {question.stop_offset_ms}ms, {_knowledge_check_label(question)} "
            f"was asked: {question.question_text}\n"
            f"  Student selected `{option.option_text}`.\n"
            f"  Options:\n{indented_option_lines}"
        )
    return "\n".join(answer_lines) if answer_lines else None


async def _get_latest_lecture_context_created(
    session: AsyncSession,
    thread_id: int,
) -> datetime | None:
    return await session.scalar(
        select(models.Message.created)
        .join(models.MessagePart, models.MessagePart.message_id == models.Message.id)
        .where(
            models.Message.thread_id == thread_id,
            models.Message.role == schemas.MessageRole.DEVELOPER,
            models.MessagePart.type == schemas.MessagePartType.INPUT_TEXT,
            models.MessagePart.text.like("## Lecture Context%"),
        )
        .order_by(models.Message.output_index.desc(), models.Message.created.desc())
        .limit(1)
    )


def _format_slide_narrations(deck: models.LectureSlideDeck) -> str:
    lines = [
        "### Lecture Slide Narrations",
    ]
    for page in sorted(deck.pages, key=lambda item: item.position):
        narration_text = (page.narration_text or "").strip()
        if not narration_text:
            continue
        lines.extend(
            [
                "",
                f"### Slide {page.position + 1}",
                "",
                narration_text,
            ]
        )
    return "\n".join(lines)


def _format_initial_lecture_developer_context(deck: models.LectureSlideDeck) -> str:
    return "\n\n".join(
        [
            "## Lecture Slide Lesson Context",
            _format_slide_narrations(deck),
        ]
    )


async def _thread_has_messages(session: AsyncSession, thread_id: int) -> bool:
    existing_message_id = await session.scalar(
        select(models.Message.id).where(models.Message.thread_id == thread_id).limit(1)
    )
    return existing_message_id is not None


def _build_lecture_developer_context_message(
    *,
    slide_thread: models.Thread,
    output_index: int,
) -> models.Message | None:
    deck = slide_thread.lecture_slide_deck
    if deck is None:
        return None
    return models.Message(
        thread_id=slide_thread.id,
        output_index=output_index,
        message_status=schemas.MessageStatus.COMPLETED,
        role=schemas.MessageRole.DEVELOPER,
        is_hidden=True,
        content=[
            models.MessagePart(
                part_index=0,
                type=schemas.MessagePartType.INPUT_TEXT,
                text=_format_initial_lecture_developer_context(deck),
            )
        ],
    )


async def _build_initial_lecture_file_message(
    *,
    session: AsyncSession,
    slide_thread: models.Thread,
    user_id: int,
    output_index: int,
) -> models.Message | None:
    deck = slide_thread.lecture_slide_deck
    if deck is None or deck.source_stored_object is None:
        return None
    source = deck.source_stored_object
    if source.openai_file_object_id is None:
        return None
    input_file = await models.File.get_by_id(session, source.openai_file_object_id)
    if input_file is None:
        return None
    return models.Message(
        thread_id=slide_thread.id,
        output_index=output_index,
        message_status=schemas.MessageStatus.COMPLETED,
        role=schemas.MessageRole.USER,
        is_hidden=True,
        user_id=user_id,
        content=[
            models.MessagePart(
                part_index=0,
                type=schemas.MessagePartType.INPUT_FILE,
                input_file_object_id=input_file.id,
                input_file=input_file,
            ),
            models.MessagePart(
                part_index=1,
                type=schemas.MessagePartType.INPUT_TEXT,
                text=(
                    "Use the attached PDF slide deck as the visual source of "
                    "truth for this lecture conversation."
                ),
            ),
        ],
    )


def _append_context_section(
    lines: list[str],
    heading: str,
    body: str | None,
) -> None:
    if body is None or not body.strip():
        return
    lines.extend(["", f"### {heading}", "", body])


def _lecture_context_status(
    state: models.LectureSlideThreadState,
    current_question: models.LectureSlideQuestion | None,
) -> str:
    if state.state == schemas.InteractiveLessonSessionState.COMPLETED:
        return "Finished the lecture slides"
    if state.state == schemas.InteractiveLessonSessionState.AWAITING_ANSWER:
        if current_question is not None:
            return f"Answering {_knowledge_check_label(current_question)}"
        return "Answering Knowledge Check (missing question)"
    if state.state == schemas.InteractiveLessonSessionState.AWAITING_POST_ANSWER_RESUME:
        if current_question is not None:
            return f"Just answered {_knowledge_check_label(current_question)}"
        return "Just answered Knowledge Check (missing question)"
    return "Viewing the lecture slides"


async def _validate_playback_position(
    session: AsyncSession,
    state: models.LectureSlideThreadState,
    lecture_video_playback_position_ms: int | None,
) -> int:
    if lecture_video_playback_position_ms is None:
        raise HTTPException(
            status_code=400,
            detail="lecture_video_playback_position_ms is required for this lecture slide lesson.",
        )
    if lecture_video_playback_position_ms < 0:
        raise HTTPException(
            status_code=400,
            detail="lecture_video_playback_position_ms must be greater than or equal to 0.",
        )
    plausible_offset_ms = await lecture_slide_runtime.get_plausible_playback_offset_ms(
        session,
        state,
        current_time=datetime.now(timezone.utc),
    )
    if lecture_video_playback_position_ms > plausible_offset_ms:
        raise HTTPException(
            status_code=400,
            detail="lecture_video_playback_position_ms is past your unlocked progress in this lecture slide lesson.",
        )
    return lecture_video_playback_position_ms


def _build_context_text(
    thread: models.Thread,
    state: models.LectureSlideThreadState,
    *,
    playback_position_ms: int,
    answered_knowledge_checks: str | None,
) -> str:
    current_question = _get_current_question(thread, state)
    furthest_offset_ms = max(state.furthest_offset_ms, playback_position_ms, 0)
    current_knowledge_check = None
    if (
        state.state == schemas.InteractiveLessonSessionState.AWAITING_ANSWER
        and current_question is not None
    ):
        current_knowledge_check = _format_knowledge_check_prompt(current_question)

    upcoming_knowledge_check = None
    if current_knowledge_check is None:
        if (
            state.state
            == schemas.InteractiveLessonSessionState.AWAITING_POST_ANSWER_RESUME
            and current_question is not None
        ):
            upcoming_question = _get_next_question(thread, current_question)
        else:
            upcoming_question = _get_next_future_question(thread, playback_position_ms)
        upcoming_knowledge_check = _format_upcoming_knowledge_check(upcoming_question)

    lines = [
        "## Lecture Context",
        "",
        f"Status: {_lecture_context_status(state, current_question)}",
        f"Current offset: {playback_position_ms}ms",
        f"Furthest watched offset: {furthest_offset_ms}ms",
    ]
    _append_context_section(lines, "Current Knowledge Check", current_knowledge_check)
    _append_context_section(lines, "Upcoming Knowledge Check", upcoming_knowledge_check)
    _append_context_section(
        lines, "Knowledge Checks Answered", answered_knowledge_checks
    )
    return "\n".join(lines)


def _select_summary_checkpoint_v5(
    checkpoints: list[schemas.LectureSlideContextSummaryCheckpointV5],
    furthest_offset_ms: int,
) -> schemas.LectureSlideContextSummaryCheckpointV5 | None:
    selected = None
    for checkpoint in checkpoints:
        if checkpoint.end_offset_ms <= furthest_offset_ms:
            selected = checkpoint
        else:
            break
    return selected


def _select_moment_context_v5(
    moments: list[schemas.LectureSlideContextMomentV5],
    playback_position_ms: int,
) -> schemas.LectureSlideContextMomentV5 | None:
    containing = [
        moment
        for moment in moments
        if moment.start_offset_ms <= playback_position_ms <= moment.end_offset_ms
    ]
    if containing:
        return min(
            containing,
            key=lambda moment: abs(moment.center_offset_ms - playback_position_ms),
        )
    if not moments:
        return None
    return min(
        moments,
        key=lambda moment: abs(moment.center_offset_ms - playback_position_ms),
    )


def _slide_at_offset(
    deck: models.LectureSlideDeck,
    offset_ms: int,
) -> models.LectureSlidePage | None:
    timed_pages = [
        page
        for page in sorted(deck.pages, key=lambda item: item.position)
        if page.start_offset_ms is not None and page.end_offset_ms is not None
    ]
    for page in timed_pages:
        if page.start_offset_ms <= offset_ms <= page.end_offset_ms:
            return page
    past_pages = [page for page in timed_pages if page.end_offset_ms <= offset_ms]
    if past_pages:
        return past_pages[-1]
    return timed_pages[0] if timed_pages else None


def _slide_context_by_position(
    context: schemas.LectureSlideContextV5,
) -> dict[int, schemas.LectureSlideContextSlideV5]:
    return {slide.slide_position: slide for slide in context.slides}


def _format_slide_number(slide_position: int | None) -> str:
    if slide_position is None:
        return "Unknown"
    return f"Slide {slide_position + 1}"


def _format_moment_context_v5(
    moment: schemas.LectureSlideContextMomentV5,
) -> str:
    return (
        f"Before this moment:\n{moment.before}\n\n"
        f"At this moment:\n{moment.at}\n\n"
        f"After this moment:\n{moment.after}"
    )


def _format_current_slide_context_v5(
    slide: schemas.LectureSlideContextSlideV5 | None,
) -> str | None:
    if slide is None:
        return None
    title = slide.title.strip()
    header = _format_slide_number(slide.slide_position)
    if title:
        header = f"{header}: {title}"
    lines = [header]
    if slide.visible_text:
        lines.extend(["", "Visible text:", slide.visible_text])
    if slide.visual_context:
        lines.extend(["", "Visual context:", slide.visual_context])
    if slide.narration_summary:
        lines.extend(["", "Narration summary:", slide.narration_summary])
    if slide.key_points:
        lines.extend(["", "Key points:"])
        lines.extend(f"- {point}" for point in slide.key_points)
    if slide.diagrams:
        lines.extend(["", "Diagrams:"])
        lines.extend(f"- {diagram}" for diagram in slide.diagrams)
    if slide.equations_or_symbols:
        lines.extend(["", "Equations or symbols:"])
        lines.extend(f"- {symbol}" for symbol in slide.equations_or_symbols)
    return "\n".join(lines)


def _build_context_text_v5(
    thread: models.Thread,
    state: models.LectureSlideThreadState,
    context: schemas.LectureSlideContextV5,
    *,
    playback_position_ms: int,
    answered_knowledge_checks: str | None,
) -> str:
    deck = thread.lecture_slide_deck
    current_question = _get_current_question(thread, state)
    furthest_offset_ms = max(state.furthest_offset_ms, playback_position_ms, 0)
    summary_checkpoint = _select_summary_checkpoint_v5(
        context.summary_checkpoints,
        furthest_offset_ms,
    )
    moment_context = _select_moment_context_v5(
        context.moment_contexts,
        playback_position_ms,
    )
    current_slide_position = None
    furthest_slide_position = None
    if deck is not None:
        current_slide = _slide_at_offset(deck, playback_position_ms)
        furthest_slide = _slide_at_offset(deck, furthest_offset_ms)
        current_slide_position = (
            current_slide.position if current_slide is not None else None
        )
        furthest_slide_position = (
            furthest_slide.position if furthest_slide is not None else None
        )
    if current_slide_position is None and moment_context is not None:
        current_slide_position = moment_context.slide_position
    if furthest_slide_position is None and summary_checkpoint is not None:
        furthest_slide_position = summary_checkpoint.end_slide_position

    slides_by_position = _slide_context_by_position(context)
    current_slide_context = (
        slides_by_position.get(current_slide_position)
        if current_slide_position is not None
        else None
    )

    current_knowledge_check = None
    if (
        state.state == schemas.InteractiveLessonSessionState.AWAITING_ANSWER
        and current_question is not None
    ):
        current_knowledge_check = _format_knowledge_check_prompt(current_question)

    upcoming_knowledge_check = None
    if current_knowledge_check is None:
        if (
            state.state
            == schemas.InteractiveLessonSessionState.AWAITING_POST_ANSWER_RESUME
            and current_question is not None
        ):
            upcoming_question = _get_next_question(thread, current_question)
        else:
            upcoming_question = _get_next_future_question(thread, playback_position_ms)
        upcoming_knowledge_check = _format_upcoming_knowledge_check(upcoming_question)

    lines = [
        "## Lecture Context",
        "",
        f"Status: {_lecture_context_status(state, current_question)}",
        f"Current offset: {playback_position_ms}ms",
        f"Furthest watched offset: {furthest_offset_ms}ms",
        f"Current slide: {_format_slide_number(current_slide_position)}",
        f"Furthest reached slide: {_format_slide_number(furthest_slide_position)}",
    ]
    _append_context_section(
        lines,
        "Lecture Summary So Far",
        (
            f"Through {summary_checkpoint.end_offset_ms}ms / "
            f"{_format_slide_number(summary_checkpoint.end_slide_position)}:\n"
            f"{summary_checkpoint.summary}"
            if summary_checkpoint is not None
            else None
        ),
    )
    _append_context_section(
        lines,
        "Current Moment Context",
        _format_moment_context_v5(moment_context)
        if moment_context is not None
        else None,
    )
    _append_context_section(
        lines,
        "Current Slide",
        _format_current_slide_context_v5(current_slide_context),
    )
    _append_context_section(lines, "Current Knowledge Check", current_knowledge_check)
    _append_context_section(lines, "Upcoming Knowledge Check", upcoming_knowledge_check)
    _append_context_section(
        lines, "Knowledge Checks Answered", answered_knowledge_checks
    )
    return "\n".join(lines)


async def prepare_lecture_chat_turn(
    *,
    request: Any,
    class_id: str,
    thread: models.Thread,
    user_id: int,
    prev_output_sequence: int,
    lecture_video_playback_position_ms: int | None = None,
) -> LectureSlideChatTurnPreparation:
    slide_thread = await models.Thread.get_by_id_with_lecture_slide_context(
        request.state["db"], thread.id
    )
    if slide_thread is None or slide_thread.lecture_slide_state is None:
        raise HTTPException(status_code=404, detail="Lecture slide thread not found.")
    if not lecture_slide_runtime.lecture_slide_matches_assistant(slide_thread):
        raise HTTPException(
            status_code=409,
            detail=lecture_slide_runtime.MSG_LESSON_UPDATED,
        )

    deck = slide_thread.lecture_slide_deck
    if not lecture_slide_chat_available(deck):
        raise HTTPException(
            status_code=409,
            detail=LECTURE_SLIDE_CHAT_UNAVAILABLE_NOTE,
        )
    transcript = None
    context_v5 = None
    try:
        if deck is not None and deck.context_version == 5:
            context_v5 = lecture_slide_context_v5_from_model(deck)
            transcript = transcript_from_model(deck)
        elif deck is not None:
            transcript = lecture_slide_chat_context_from_model(deck)
    except (ValidationError, ValueError) as exc:
        logger.warning(
            "Stored lecture slide chat context is invalid. lecture_slide_deck_id=%s",
            getattr(deck, "id", None),
            exc_info=True,
        )
        raise HTTPException(
            status_code=409,
            detail=LECTURE_SLIDE_CHAT_UNAVAILABLE_NOTE,
        ) from exc
    if transcript is None or (
        deck is not None and deck.context_version == 5 and context_v5 is None
    ):
        raise HTTPException(
            status_code=409,
            detail=LECTURE_SLIDE_CHAT_UNAVAILABLE_NOTE,
        )

    slide_state = slide_thread.lecture_slide_state
    playback_position_ms = await _validate_playback_position(
        request.state["db"],
        slide_state,
        lecture_video_playback_position_ms,
    )
    previous_context_created = await _get_latest_lecture_context_created(
        request.state["db"], slide_thread.id
    )
    answered_knowledge_checks = await _build_answered_knowledge_checks_markdown(
        request.state["db"],
        slide_thread.id,
        since_created=previous_context_created,
    )
    prepended_messages = []
    if (
        deck is not None
        and deck.context_version == 4
        and not await _thread_has_messages(request.state["db"], slide_thread.id)
    ):
        developer_context_message = _build_lecture_developer_context_message(
            slide_thread=slide_thread,
            output_index=0,
        )
        if developer_context_message is not None:
            prepended_messages.append(developer_context_message)
        initial_file_message = await _build_initial_lecture_file_message(
            session=request.state["db"],
            slide_thread=slide_thread,
            user_id=user_id,
            output_index=1,
        )
        if initial_file_message is not None:
            prepended_messages.append(initial_file_message)

    if context_v5 is not None:
        context_text = _build_context_text_v5(
            slide_thread,
            slide_state,
            context_v5,
            playback_position_ms=playback_position_ms,
            answered_knowledge_checks=answered_knowledge_checks,
        )
    else:
        context_text = _build_context_text(
            slide_thread,
            slide_state,
            playback_position_ms=playback_position_ms,
            answered_knowledge_checks=answered_knowledge_checks,
        )
    if context_text.strip():
        prepended_messages.append(
            models.Message(
                thread_id=slide_thread.id,
                output_index=prev_output_sequence + 1 + len(prepended_messages),
                message_status=schemas.MessageStatus.COMPLETED,
                role=schemas.MessageRole.DEVELOPER,
                is_hidden=True,
                content=[
                    models.MessagePart(
                        part_index=0,
                        type=schemas.MessagePartType.INPUT_TEXT,
                        text=context_text,
                    )
                ],
            )
        )

    slide_state.last_chat_context_end_ms = playback_position_ms
    request.state["db"].add(slide_state)

    return LectureSlideChatTurnPreparation(
        prepended_messages=prepended_messages,
        user_output_index=prev_output_sequence + 1 + len(prepended_messages),
        user_assistant_messages_only=True,
        include_developer_messages=True,
    )
