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
    "Lecture chat is only available for lecture slides with generated context "
    "and word-level transcription."
)

_V3_TRANSCRIPT_ADAPTER = TypeAdapter(list[schemas.LectureVideoManifestWordV3])
_SUMMARY_CHECKPOINTS_ADAPTER = TypeAdapter(
    list[schemas.LectureVideoManifestSummaryCheckpointV4]
)
_MOMENT_CONTEXTS_ADAPTER = TypeAdapter(
    list[schemas.LectureVideoManifestMomentContextV4]
)


@dataclass
class LectureSlideChatContext:
    word_level_transcription: list[schemas.LectureVideoManifestWordV3]
    summary_checkpoints: list[schemas.LectureVideoManifestSummaryCheckpointV4]
    moment_contexts: list[schemas.LectureVideoManifestMomentContextV4]


@dataclass
class LectureSlideChatTurnPreparation:
    prepended_messages: list[models.Message]
    user_output_index: int
    user_assistant_messages_only: bool = True


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
) -> LectureSlideChatContext | None:
    if deck.context_version != 4:
        return None
    transcript = transcript_from_model(deck)
    context_data = deck.context_data if isinstance(deck.context_data, dict) else None
    if transcript is None or context_data is None:
        return None

    summary_checkpoints = _SUMMARY_CHECKPOINTS_ADAPTER.validate_python(
        context_data.get("summary_checkpoints") or []
    )
    moment_contexts = _MOMENT_CONTEXTS_ADAPTER.validate_python(
        context_data.get("moment_contexts") or []
    )
    summary_checkpoints, moment_contexts = (
        schemas.normalize_lecture_video_manifest_v4_context_arrays(
            summary_checkpoints,
            moment_contexts,
        )
    )
    if not summary_checkpoints and not moment_contexts:
        return None
    return LectureSlideChatContext(
        word_level_transcription=transcript,
        summary_checkpoints=summary_checkpoints,
        moment_contexts=moment_contexts,
    )


def transcript_from_model(
    deck: models.LectureSlideDeck,
) -> list[schemas.LectureVideoManifestWordV3] | None:
    return _words_from_transcript_data(deck.transcript_data)


def lecture_slide_chat_available(deck: models.LectureSlideDeck | None) -> bool:
    if deck is None:
        return False
    return deck.context_version == 4 and deck.lecture_slide_chat_available


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
) -> str | None:
    interactions = await session.scalars(
        select(models.LectureSlideInteraction)
        .where(models.LectureSlideInteraction.thread_id == thread_id)
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
        if (
            interaction.event_type
            != schemas.InteractiveLessonInteractionEventType.ANSWER_SUBMITTED
        ):
            continue
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


def _select_summary_checkpoint(
    checkpoints: list[schemas.LectureVideoManifestSummaryCheckpointV4],
    furthest_offset_ms: int,
) -> schemas.LectureVideoManifestSummaryCheckpointV4 | None:
    selected = None
    for checkpoint in checkpoints:
        if checkpoint.end_offset_ms <= furthest_offset_ms:
            selected = checkpoint
        else:
            break
    return selected


def _select_moment_context(
    moments: list[schemas.LectureVideoManifestMomentContextV4],
    playback_position_ms: int,
) -> schemas.LectureVideoManifestMomentContextV4 | None:
    selected = None
    for moment in moments:
        if moment.center_offset_ms <= playback_position_ms:
            selected = moment
        else:
            break
    return selected


def _format_moment_context(
    moment: schemas.LectureVideoManifestMomentContextV4,
) -> str:
    return (
        f"Before this moment ({moment.start_offset_ms}-{moment.center_offset_ms}ms):\n"
        f"{moment.before}\n\n"
        f"At this moment ({moment.center_offset_ms}ms):\n"
        f"{moment.at}\n\n"
        f"After this moment ({moment.center_offset_ms}-{moment.end_offset_ms}ms):\n"
        f"{moment.after}"
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
    chat_context: LectureSlideChatContext,
    *,
    playback_position_ms: int,
    answered_knowledge_checks: str | None,
) -> str:
    current_question = _get_current_question(thread, state)
    furthest_offset_ms = max(state.furthest_offset_ms, playback_position_ms, 0)
    summary_checkpoint = _select_summary_checkpoint(
        chat_context.summary_checkpoints,
        furthest_offset_ms,
    )
    moment_context = _select_moment_context(
        chat_context.moment_contexts,
        playback_position_ms,
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
    ]
    _append_context_section(
        lines,
        "Lecture Summary So Far",
        (
            f"Through {summary_checkpoint.end_offset_ms}ms:\n"
            f"{summary_checkpoint.summary}"
            if summary_checkpoint is not None
            else None
        ),
    )
    _append_context_section(
        lines,
        "Current Moment Context",
        _format_moment_context(moment_context) if moment_context is not None else None,
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
    try:
        chat_context = (
            lecture_slide_chat_context_from_model(deck) if deck is not None else None
        )
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
    if chat_context is None:
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
    answered_knowledge_checks = await _build_answered_knowledge_checks_markdown(
        request.state["db"], slide_thread.id
    )
    context_text = _build_context_text(
        slide_thread,
        slide_state,
        chat_context,
        playback_position_ms=playback_position_ms,
        answered_knowledge_checks=answered_knowledge_checks,
    )

    slide_state.last_chat_context_end_ms = playback_position_ms
    request.state["db"].add(slide_state)

    return LectureSlideChatTurnPreparation(
        prepended_messages=[
            models.Message(
                thread_id=slide_thread.id,
                output_index=prev_output_sequence + 1,
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
        ],
        user_output_index=prev_output_sequence + 2,
        user_assistant_messages_only=True,
    )
