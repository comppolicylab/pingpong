import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
import logging
import tempfile
from pathlib import Path
from typing import Any

from fastapi import HTTPException, UploadFile
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

import pingpong.models as models
import pingpong.schemas as schemas
from pingpong import lecture_video_runtime
from pingpong.config import config
from pingpong.files import handle_create_file
from pingpong.lecture_video_service import (
    LECTURE_VIDEO_CHAT_UNAVAILABLE_NOTE,
    lecture_video_chat_metadata,
    lecture_video_chat_context_from_model,
)
from pingpong.video_store import VideoInputSource, VideoStoreError

logger = logging.getLogger(__name__)

# Include a short future transcript window and a slight frame rewind so chat context stays aligned.
LOOKAHEAD_WINDOW_MS = 30_000
FRAME_LOOKBACK_MS = 1_000
TRANSCRIPT_CONTEXT_WINDOW_MS = 120_000


class LectureVideoFrameContextError(Exception):
    """Raised for expected failures while assembling lecture video frame context."""


@dataclass
class LectureChatContextBuildResult:
    text_message_parts: list[models.MessagePart]
    frame_message_parts: list[models.MessagePart]
    current_offset_ms: int
    user_assistant_messages_only: bool = False


@dataclass
class LectureChatTurnPreparation:
    prepended_messages: list[models.Message]
    user_output_index: int
    user_assistant_messages_only: bool = False


def _apply_lecture_video_chat_metadata(thread: models.Thread) -> None:
    thread.lecture_video_chat_available = lecture_video_chat_metadata(
        thread.lecture_video
    )


def _serialize_transcript_words_v3(
    words: list[schemas.LectureVideoManifestWordV3],
) -> list[tuple[int, int, str]]:
    return [(word.start_offset_ms, word.end_offset_ms, word.word) for word in words]


def _interval_overlaps_range(
    start_ms: int,
    end_ms: int,
    range_start_ms: int,
    range_end_ms: int,
) -> bool:
    if range_end_ms < range_start_ms:
        return False
    return end_ms > range_start_ms and start_ms <= range_end_ms


def _join_words(words: list[str]) -> str:
    if not words:
        return ""

    # This is a deliberately small punctuation heuristic; it covers common
    # transcript tokens well enough for now but will miss edge cases such as
    # em dashes or ellipses.
    no_leading_space = {".", ",", "!", "?", ":", ";", ")", "]", "}", "%"}
    no_trailing_space = {"(", "[", "{", "$"}

    parts: list[str] = []
    for word in words:
        if not parts:
            parts.append(word)
            continue
        if word in no_leading_space or parts[-1] in no_trailing_space:
            parts[-1] += word
        else:
            parts.append(word)
    return " ".join(parts)


def _transcript_slice_text(
    transcript_words: list[tuple[int, int, str]],
    range_start_ms: int,
    range_end_ms: int,
) -> str:
    if range_end_ms < range_start_ms:
        return ""

    selected_words = [
        word
        for start_ms, end_ms, word in transcript_words
        if _interval_overlaps_range(start_ms, end_ms, range_start_ms, range_end_ms)
    ]
    return _join_words(selected_words)


def _get_current_question(
    thread: models.Thread,
    state: models.LectureVideoThreadState,
) -> models.LectureVideoQuestion | None:
    if state.current_question is not None:
        return state.current_question
    if not thread.lecture_video:
        return None
    for question in thread.lecture_video.questions:
        if question.id == state.current_question_id:
            return question
    return None


def _get_next_question(
    thread: models.Thread,
    current_question: models.LectureVideoQuestion | None,
) -> models.LectureVideoQuestion | None:
    if not thread.lecture_video or current_question is None:
        return None
    next_position = current_question.position + 1
    for question in thread.lecture_video.questions:
        if question.position == next_position:
            return question
    return None


def _get_next_future_question(
    thread: models.Thread,
    current_offset_ms: int,
) -> models.LectureVideoQuestion | None:
    if not thread.lecture_video:
        return None
    for question in sorted(
        thread.lecture_video.questions, key=lambda item: item.position
    ):
        if question.stop_offset_ms > current_offset_ms:
            return question
    return None


def _knowledge_check_number(question: models.LectureVideoQuestion) -> int:
    return question.position + 1


_KnowledgeCheckAnswerFormatter = Callable[
    [models.LectureVideoQuestion, models.LectureVideoQuestionOption], str
]


async def _build_answered_knowledge_checks(
    session: AsyncSession,
    thread_id: int,
    format_answer: _KnowledgeCheckAnswerFormatter,
) -> str | None:
    interactions = (
        await models.LectureVideoInteraction.list_question_history_by_thread_id(
            session, thread_id
        )
    )
    answer_lines: list[str] = []
    for interaction in interactions:
        if (
            interaction.event_type
            != schemas.LectureVideoInteractionEventType.ANSWER_SUBMITTED
        ):
            continue
        question = interaction.question
        option = interaction.option
        if question is None or option is None:
            continue
        answer_lines.append(format_answer(question, option))
    return "\n".join(answer_lines) if answer_lines else None


def _knowledge_check_label(question: models.LectureVideoQuestion) -> str:
    return f"Knowledge Check #{_knowledge_check_number(question)}"


async def _build_answered_knowledge_checks_markdown(
    session: AsyncSession, thread_id: int
) -> str | None:
    def format_answer(
        question: models.LectureVideoQuestion,
        option: models.LectureVideoQuestionOption,
    ) -> str:
        question_text = question.question_text.strip() or f"Question {question.id}"
        option_lines = _format_knowledge_check_options(question, selected_option=option)
        indented_option_lines = "\n".join(
            f"  {line}" for line in option_lines.splitlines()
        )
        return (
            f"- At {question.stop_offset_ms}ms, {_knowledge_check_label(question)} "
            f"was asked: {question_text}\n"
            f"  Student selected `{option.option_text}`.\n"
            f"  Options:\n{indented_option_lines}"
        )

    return await _build_answered_knowledge_checks(session, thread_id, format_answer)


def _build_context_text_from_transcript(
    thread: models.Thread,
    state: models.LectureVideoThreadState,
    transcript_words: list[tuple[int, int, str]],
    *,
    answered_knowledge_checks: str | None = None,
) -> tuple[str, int]:
    return _build_context_text_from_parts(
        thread,
        state,
        transcript_words=transcript_words,
        answered_knowledge_checks=answered_knowledge_checks,
    )


def _build_context_text_from_parts(
    thread: models.Thread,
    state: models.LectureVideoThreadState,
    *,
    transcript_words: list[tuple[int, int, str]],
    answered_knowledge_checks: str | None = None,
    video_descriptions: list[schemas.LectureVideoManifestVideoDescriptionV3]
    | None = None,
) -> tuple[str, int]:
    current_offset_ms = max(0, state.last_known_offset_ms)

    transcript_start_ms, uncapped_transcript_start_ms = _transcript_context_window(
        state, current_offset_ms
    )
    transcript_heading = _transcript_context_heading(
        transcript_start_ms, uncapped_transcript_start_ms
    )

    transcript_text = _transcript_slice_text(
        transcript_words,
        transcript_start_ms,
        current_offset_ms,
    )

    next_future_question = _get_next_future_question(thread, current_offset_ms)
    lookahead_end_ms = min(
        next_future_question.stop_offset_ms
        if next_future_question
        else current_offset_ms + LOOKAHEAD_WINDOW_MS,
        current_offset_ms + LOOKAHEAD_WINDOW_MS,
    )
    lookahead_text = _transcript_slice_text(
        transcript_words,
        current_offset_ms,
        lookahead_end_ms,
    )
    descriptions_text = (
        _format_video_descriptions(
            video_descriptions,
            transcript_start_ms,
            lookahead_end_ms,
        )
        if video_descriptions is not None
        else None
    )

    current_question = _get_current_question(thread, state)
    return (
        _build_lecture_context_text(
            state=state,
            current_question=current_question,
            context=_LectureContextSections(
                current_offset_ms=current_offset_ms,
                transcript_heading=transcript_heading,
                transcript_text=transcript_text,
                lookahead_text=lookahead_text,
                upcoming_question=next_future_question,
                answered_knowledge_checks=answered_knowledge_checks,
                video_descriptions_text=descriptions_text,
            ),
        ),
        current_offset_ms,
    )


def _transcript_context_heading(
    transcript_start_ms: int, uncapped_transcript_start_ms: int
) -> str:
    heading = "Recent Transcript"
    if uncapped_transcript_start_ms > 0:
        heading += " Since Last Lecture Chat"
    if transcript_start_ms > uncapped_transcript_start_ms:
        heading += " (older transcript omitted)"
    return heading


def _transcript_context_window(
    state: models.LectureVideoThreadState, current_offset_ms: int
) -> tuple[int, int]:
    clamped_last_chat_context_end_ms = min(
        max(state.last_chat_context_end_ms, 0), current_offset_ms
    )
    uncapped_transcript_start_ms = (
        clamped_last_chat_context_end_ms
        if state.last_chat_context_end_ms == clamped_last_chat_context_end_ms
        else 0
    )
    transcript_start_ms = max(
        uncapped_transcript_start_ms,
        current_offset_ms - TRANSCRIPT_CONTEXT_WINDOW_MS,
    )
    return transcript_start_ms, uncapped_transcript_start_ms


def _format_knowledge_check_prompt(
    question: models.LectureVideoQuestion,
    *,
    prefix: str | None = None,
) -> str:
    question_text = question.question_text.strip() or f"Question {question.id}"
    question_line = f"{_knowledge_check_label(question)}: {question_text}"
    parts = []
    if prefix is not None:
        parts.extend([prefix, ""])
    option_lines = _format_knowledge_check_options(question)
    parts.extend([question_line, "", f"Options:\n{option_lines}"])
    return "\n".join(parts)


def _format_knowledge_check_options(
    question: models.LectureVideoQuestion,
    *,
    selected_option: models.LectureVideoQuestionOption | None = None,
) -> str:
    correct_option = question.correct_option

    def format_option(option: models.LectureVideoQuestionOption) -> str:
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


def _format_video_descriptions(
    descriptions: list[schemas.LectureVideoManifestVideoDescriptionV3],
    range_start_ms: int,
    range_end_ms: int,
) -> str | None:
    lines = [
        f"- {description.start_offset_ms}-{description.end_offset_ms}ms: "
        f"{description.description}"
        for description in descriptions
        if _interval_overlaps_range(
            description.start_offset_ms,
            description.end_offset_ms,
            range_start_ms,
            range_end_ms,
        )
    ]
    return "\n".join(lines) if lines else None


def _lecture_context_status(
    state: models.LectureVideoThreadState,
    current_question: models.LectureVideoQuestion | None,
) -> str:
    if state.state == schemas.LectureVideoSessionState.COMPLETED:
        return "Finished watching the lecture video"
    if state.state == schemas.LectureVideoSessionState.AWAITING_ANSWER:
        if current_question is not None:
            return f"Answering {_knowledge_check_label(current_question)}"
        logger.warning(
            "Lecture video state is awaiting_answer without a current question.",
            extra={"thread_id": getattr(state, "thread_id", None)},
        )
        return "Answering Knowledge Check (missing question)"
    if state.state == schemas.LectureVideoSessionState.AWAITING_POST_ANSWER_RESUME:
        if current_question is not None:
            return f"Just answered {_knowledge_check_label(current_question)}"
        logger.warning(
            "Lecture video state is awaiting_post_answer_resume without a current question.",
            extra={"thread_id": getattr(state, "thread_id", None)},
        )
        return "Just answered Knowledge Check (missing question)"
    return "Watching the lecture video"


def _append_lecture_context_section(
    lines: list[str],
    heading: str,
    body: str | None,
) -> None:
    if body is None or not body.strip():
        return
    lines.extend(["", f"### {heading}", "", body])


@dataclass
class _LectureContextSections:
    current_offset_ms: int
    transcript_heading: str
    transcript_text: str
    lookahead_text: str
    upcoming_question: models.LectureVideoQuestion | None
    answered_knowledge_checks: str | None = None
    video_descriptions_text: str | None = None


def _build_lecture_context_text(
    *,
    state: models.LectureVideoThreadState,
    current_question: models.LectureVideoQuestion | None,
    context: _LectureContextSections,
) -> str:
    current_knowledge_check = None
    if (
        state.state == schemas.LectureVideoSessionState.AWAITING_ANSWER
        and current_question is not None
    ):
        current_knowledge_check = _format_knowledge_check_prompt(current_question)

    upcoming_knowledge_check = None
    if context.upcoming_question is not None:
        upcoming_knowledge_check = _format_knowledge_check_prompt(
            context.upcoming_question,
            prefix=(
                f"At {context.upcoming_question.stop_offset_ms}ms, "
                "the learner will be asked:"
            ),
        )

    lines = [
        "## Lecture Context",
        "",
        f"Status: {_lecture_context_status(state, current_question)}",
        f"Current offset: {context.current_offset_ms}ms",
    ]
    _append_lecture_context_section(
        lines, context.transcript_heading, context.transcript_text
    )
    _append_lecture_context_section(
        lines, "Lookahead Transcript", context.lookahead_text
    )
    _append_lecture_context_section(
        lines, "Relevant Video Descriptions", context.video_descriptions_text
    )
    _append_lecture_context_section(
        lines, "Current Knowledge Check", current_knowledge_check
    )
    _append_lecture_context_section(
        lines, "Upcoming Knowledge Check", upcoming_knowledge_check
    )
    _append_lecture_context_section(
        lines, "Knowledge Checks Answered", context.answered_knowledge_checks
    )
    return "\n".join(lines)


def _build_context_text_v3_from_parts(
    thread: models.Thread,
    state: models.LectureVideoThreadState,
    *,
    word_level_transcription: list[schemas.LectureVideoManifestWordV3],
    video_descriptions: list[schemas.LectureVideoManifestVideoDescriptionV3],
    answered_knowledge_checks: str | None,
) -> tuple[str, int]:
    return _build_context_text_from_parts(
        thread,
        state,
        transcript_words=_serialize_transcript_words_v3(word_level_transcription),
        video_descriptions=video_descriptions,
        answered_knowledge_checks=answered_knowledge_checks,
    )


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


def _format_v4_moment_context(
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


def _build_context_text_v4_from_parts(
    thread: models.Thread,
    state: models.LectureVideoThreadState,
    *,
    summary_checkpoints: list[schemas.LectureVideoManifestSummaryCheckpointV4],
    moment_contexts: list[schemas.LectureVideoManifestMomentContextV4],
    lecture_video_playback_position_ms: int,
    answered_knowledge_checks: str | None,
) -> tuple[str, int]:
    playback_position_ms = max(0, lecture_video_playback_position_ms)
    furthest_offset_ms = max(state.furthest_offset_ms, playback_position_ms, 0)
    summary_checkpoint = _select_summary_checkpoint(
        summary_checkpoints,
        furthest_offset_ms,
    )
    moment_context = _select_moment_context(moment_contexts, playback_position_ms)
    current_question = _get_current_question(thread, state)

    current_knowledge_check = None
    if (
        state.state == schemas.LectureVideoSessionState.AWAITING_ANSWER
        and current_question is not None
    ):
        current_knowledge_check = _format_knowledge_check_prompt(current_question)
    upcoming_knowledge_check = None
    if current_knowledge_check is None:
        upcoming_question = _get_next_future_question(thread, playback_position_ms)
        if upcoming_question is not None:
            upcoming_knowledge_check = _format_knowledge_check_prompt(
                upcoming_question,
                prefix=(
                    f"At {upcoming_question.stop_offset_ms}ms, "
                    "the learner will be asked:"
                ),
            )

    lines = [
        "## Lecture Context",
        "",
        f"Status: {_lecture_context_status(state, current_question)}",
        f"Current offset: {playback_position_ms}ms",
        f"Furthest watched offset: {furthest_offset_ms}ms",
    ]
    _append_lecture_context_section(
        lines,
        "Lecture Summary So Far",
        (
            f"Through {summary_checkpoint.end_offset_ms}ms:\n"
            f"{summary_checkpoint.summary}"
            if summary_checkpoint is not None
            else None
        ),
    )
    _append_lecture_context_section(
        lines,
        "Current Moment Context",
        _format_v4_moment_context(moment_context)
        if moment_context is not None
        else None,
    )
    _append_lecture_context_section(
        lines, "Current Knowledge Check", current_knowledge_check
    )
    _append_lecture_context_section(
        lines, "Upcoming Knowledge Check", upcoming_knowledge_check
    )
    _append_lecture_context_section(
        lines, "Knowledge Checks Answered", answered_knowledge_checks
    )
    return "\n".join(lines), playback_position_ms


async def _validate_v4_playback_position(
    session: AsyncSession,
    state: models.LectureVideoThreadState,
    lecture_video_playback_position_ms: int | None,
) -> int:
    if lecture_video_playback_position_ms is None:
        raise HTTPException(
            status_code=400,
            detail="lecture_video_playback_position_ms is required for this lecture video.",
        )
    if lecture_video_playback_position_ms < 0:
        raise HTTPException(
            status_code=400,
            detail="lecture_video_playback_position_ms must be greater than or equal to 0.",
        )
    plausible_offset_ms = await lecture_video_runtime.get_plausible_playback_offset_ms(
        session,
        state,
        current_time=datetime.now(timezone.utc),
    )
    if lecture_video_playback_position_ms > plausible_offset_ms:
        raise HTTPException(
            status_code=400,
            detail="lecture_video_playback_position_ms is past your unlocked progress in this lecture video.",
        )
    return lecture_video_playback_position_ms


async def _get_video_input_source(
    lecture_video: models.LectureVideo,
) -> VideoInputSource:
    if not config.video_store:
        raise LectureVideoFrameContextError("Video store not configured.")
    if lecture_video.stored_object is None:
        raise LectureVideoFrameContextError("Lecture video stored object not loaded.")

    try:
        return await config.video_store.store.get_ffmpeg_input_source(
            lecture_video.stored_object.key
        )
    except VideoStoreError as e:
        raise LectureVideoFrameContextError(
            e.detail or "Unable to open lecture video input source."
        ) from e


async def _extract_frame(
    video_source: VideoInputSource, output_path: Path, offset_ms: int
) -> bool:
    try:
        process = await asyncio.create_subprocess_exec(
            "ffmpeg",
            "-loglevel",
            "error",
            "-y",
            "-ss",
            f"{offset_ms / 1000:.3f}",
            *video_source.ffmpeg_input_args,
            "-i",
            video_source.url,
            "-frames:v",
            "1",
            str(output_path),
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
    except FileNotFoundError:
        logger.warning("ffmpeg is unavailable; skipping lecture video frame extraction")
        return False

    try:
        _, stderr = await asyncio.wait_for(process.communicate(), timeout=30)
    except asyncio.TimeoutError:
        process.kill()
        _, stderr = await process.communicate()
        logger.warning(
            "Timed out extracting lecture video frame. offset_ms=%s stderr=%s",
            offset_ms,
            stderr.decode("utf-8", errors="ignore").strip(),
        )
        return False

    if process.returncode != 0 or not output_path.exists():
        logger.warning(
            "Failed to extract lecture video frame. offset_ms=%s stderr=%s",
            offset_ms,
            stderr.decode("utf-8", errors="ignore").strip(),
        )
        return False
    return True


async def _build_frame_message_parts(
    session: AsyncSession,
    authz,
    openai_client,
    *,
    thread_id: int,
    lecture_video: models.LectureVideo,
    current_offset_ms: int,
    class_id: int,
    uploader_id: int,
    user_auth: str | None,
    anonymous_link_auth: str | None,
    anonymous_user_auth: str | None,
    anonymous_session_id: int | None,
    anonymous_link_id: int | None,
) -> list[models.MessagePart]:
    if lecture_video.stored_object is None:
        return []

    frame_parts: list[models.MessagePart] = []
    created_thread_image_file_ids: list[str] = []
    try:
        with tempfile.TemporaryDirectory(prefix="lecture-chat-frames-") as tmp_dir:
            tmp_path = Path(tmp_dir)
            video_source = await _get_video_input_source(lecture_video)
            frame_offsets = list(
                dict.fromkeys(
                    [
                        max(current_offset_ms, 0),
                        max(current_offset_ms - FRAME_LOOKBACK_MS, 0),
                    ]
                )
            )
            for part_index, frame_offset_ms in enumerate(frame_offsets, start=1):
                frame_path = tmp_path / f"frame-{part_index}.png"
                if not await _extract_frame(video_source, frame_path, frame_offset_ms):
                    continue

                with frame_path.open("rb") as frame_file:
                    upload = UploadFile(
                        file=frame_file,
                        filename=frame_path.name,
                        headers={"content-type": "image/png"},
                    )
                    try:
                        created_file = await handle_create_file(
                            session,
                            authz,
                            openai_client,
                            upload=upload,
                            class_id=class_id,
                            uploader_id=uploader_id,
                            private=True,
                            purpose="vision",
                            user_auth=user_auth,
                            anonymous_link_auth=anonymous_link_auth,
                            anonymous_user_auth=anonymous_user_auth,
                            anonymous_session_id=anonymous_session_id,
                            anonymous_link_id=anonymous_link_id,
                        )
                    except Exception:
                        logger.warning(
                            "Failed to upload lecture video frame context. lecture_video_id=%s frame_offset_ms=%s",
                            lecture_video.id,
                            frame_offset_ms,
                            exc_info=True,
                        )
                        continue

                created_thread_image_file_id = (
                    created_file.vision_file_id or created_file.file_id
                )
                created_thread_image_file_ids.append(created_thread_image_file_id)
                frame_parts.append(
                    models.MessagePart(
                        part_index=part_index,
                        type=schemas.MessagePartType.INPUT_IMAGE,
                        input_image_file_id=created_thread_image_file_id,
                        input_image_file_object_id=created_file.id,
                    )
                )
        if created_thread_image_file_ids:
            try:
                await models.Thread.add_image_files(
                    session, thread_id, created_thread_image_file_ids
                )
            except Exception:
                logger.warning(
                    "Failed to attach lecture video frame context files to thread. lecture_video_id=%s thread_id=%s",
                    lecture_video.id,
                    thread_id,
                    exc_info=True,
                )
    except (OSError, LectureVideoFrameContextError):
        logger.error(
            "Failed to build lecture video frame context. lecture_video_id=%s",
            lecture_video.id,
            exc_info=True,
        )
        return []

    return frame_parts


async def build_lecture_chat_context_message_parts(
    session: AsyncSession,
    authz,
    openai_client,
    *,
    thread: models.Thread,
    class_id: int,
    uploader_id: int,
    user_auth: str | None,
    anonymous_link_auth: str | None,
    anonymous_user_auth: str | None,
    anonymous_session_id: int | None,
    anonymous_link_id: int | None,
    lecture_video_playback_position_ms: int | None = None,
) -> LectureChatContextBuildResult:
    lecture_video = thread.lecture_video
    state = thread.lecture_video_state
    if lecture_video is None or state is None:
        raise ValueError(
            "Lecture video thread context must be loaded before building chat context."
        )

    try:
        chat_context = lecture_video_chat_context_from_model(lecture_video)
    except (ValidationError, ValueError) as exc:
        logger.warning(
            "Stored lecture video chat manifest is invalid. lecture_video_id=%s",
            lecture_video.id,
            exc_info=True,
        )
        raise HTTPException(
            status_code=409,
            detail=LECTURE_VIDEO_CHAT_UNAVAILABLE_NOTE,
        ) from exc
    if chat_context is None:
        raise HTTPException(
            status_code=409,
            detail=LECTURE_VIDEO_CHAT_UNAVAILABLE_NOTE,
        )

    if chat_context.version == 3:
        answered_knowledge_checks = await _build_answered_knowledge_checks_markdown(
            session, thread.id
        )
        context_text, current_offset_ms = _build_context_text_v3_from_parts(
            thread,
            state,
            word_level_transcription=chat_context.word_level_transcription,
            video_descriptions=chat_context.video_descriptions,
            answered_knowledge_checks=answered_knowledge_checks,
        )
        text_part = models.MessagePart(
            part_index=0,
            type=schemas.MessagePartType.INPUT_TEXT,
            text=context_text,
        )
        return LectureChatContextBuildResult(
            text_message_parts=[text_part],
            frame_message_parts=[],
            current_offset_ms=current_offset_ms,
        )

    if chat_context.version == 4:
        playback_position_ms = await _validate_v4_playback_position(
            session,
            state,
            lecture_video_playback_position_ms,
        )
        answered_knowledge_checks = await _build_answered_knowledge_checks_markdown(
            session, thread.id
        )
        context_text, current_offset_ms = _build_context_text_v4_from_parts(
            thread,
            state,
            summary_checkpoints=chat_context.summary_checkpoints,
            moment_contexts=chat_context.moment_contexts,
            lecture_video_playback_position_ms=playback_position_ms,
            answered_knowledge_checks=answered_knowledge_checks,
        )
        text_part = models.MessagePart(
            part_index=0,
            type=schemas.MessagePartType.INPUT_TEXT,
            text=context_text,
        )
        return LectureChatContextBuildResult(
            text_message_parts=[text_part],
            frame_message_parts=[],
            current_offset_ms=current_offset_ms,
            user_assistant_messages_only=True,
        )

    answered_knowledge_checks = await _build_answered_knowledge_checks_markdown(
        session, thread.id
    )
    context_text, current_offset_ms = _build_context_text_from_transcript(
        thread,
        state,
        _serialize_transcript_words_v3(chat_context.word_level_transcription),
        answered_knowledge_checks=answered_knowledge_checks,
    )
    text_part = models.MessagePart(
        part_index=0,
        type=schemas.MessagePartType.INPUT_TEXT,
        text=context_text,
    )
    frame_parts = await _build_frame_message_parts(
        session,
        authz,
        openai_client,
        thread_id=thread.id,
        lecture_video=lecture_video,
        current_offset_ms=current_offset_ms,
        class_id=class_id,
        uploader_id=uploader_id,
        user_auth=user_auth,
        anonymous_link_auth=anonymous_link_auth,
        anonymous_user_auth=anonymous_user_auth,
        anonymous_session_id=anonymous_session_id,
        anonymous_link_id=anonymous_link_id,
    )
    return LectureChatContextBuildResult(
        text_message_parts=[text_part],
        frame_message_parts=frame_parts,
        current_offset_ms=current_offset_ms,
    )


async def prepare_lecture_chat_turn(
    *,
    request: Any,
    openai_client: Any,
    class_id: str,
    thread: models.Thread,
    user_id: int,
    prev_output_sequence: int,
    lecture_video_playback_position_ms: int | None = None,
) -> LectureChatTurnPreparation:
    lecture_thread = await models.Thread.get_by_id_for_class_with_lecture_video_context(
        request.state["db"], int(class_id), thread.id
    )
    if lecture_thread is None or lecture_thread.lecture_video_state is None:
        raise HTTPException(status_code=404, detail="Lecture video thread not found.")

    _apply_lecture_video_chat_metadata(lecture_thread)
    if not lecture_thread.lecture_video_chat_available:
        raise HTTPException(
            status_code=409,
            detail=LECTURE_VIDEO_CHAT_UNAVAILABLE_NOTE,
        )

    lecture_state = lecture_thread.lecture_video_state
    if lecture_state.state not in {
        schemas.LectureVideoSessionState.PLAYING,
        schemas.LectureVideoSessionState.AWAITING_ANSWER,
        schemas.LectureVideoSessionState.AWAITING_POST_ANSWER_RESUME,
        schemas.LectureVideoSessionState.COMPLETED,
    }:
        raise HTTPException(
            status_code=409,
            detail="Lecture chat is unavailable in the current lecture state.",
        )

    context_result = await build_lecture_chat_context_message_parts(
        request.state["db"],
        request.state["authz"],
        openai_client,
        thread=lecture_thread,
        class_id=int(class_id),
        uploader_id=user_id,
        user_auth=request.state["auth_user"],
        anonymous_link_auth=request.state["anonymous_share_token_auth"],
        anonymous_user_auth=request.state["anonymous_session_token_auth"],
        anonymous_session_id=request.state["anonymous_session_id"],
        anonymous_link_id=request.state["anonymous_link_id"],
        lecture_video_playback_position_ms=lecture_video_playback_position_ms,
    )

    lecture_state.last_chat_context_end_ms = context_result.current_offset_ms
    request.state["db"].add(lecture_state)

    prepended_messages = [
        models.Message(
            thread_id=lecture_thread.id,
            output_index=prev_output_sequence + 1,
            message_status=schemas.MessageStatus.COMPLETED,
            role=schemas.MessageRole.DEVELOPER,
            is_hidden=True,
            content=context_result.text_message_parts,
        )
    ]

    next_output_index = prev_output_sequence + 2
    if context_result.frame_message_parts:
        prepended_messages.append(
            models.Message(
                thread_id=lecture_thread.id,
                output_index=next_output_index,
                message_status=schemas.MessageStatus.COMPLETED,
                role=schemas.MessageRole.USER,
                is_hidden=True,
                content=context_result.frame_message_parts,
            )
        )
        next_output_index += 1

    return LectureChatTurnPreparation(
        prepended_messages=prepended_messages,
        user_output_index=next_output_index,
        user_assistant_messages_only=context_result.user_assistant_messages_only,
    )
