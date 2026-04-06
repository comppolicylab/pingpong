import asyncio
from dataclasses import dataclass
import logging
import tempfile
from pathlib import Path
from typing import Any

from fastapi import HTTPException, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

import pingpong.models as models
import pingpong.schemas as schemas
from pingpong.config import config
from pingpong.files import handle_create_file
from pingpong.lecture_video_service import (
    LECTURE_VIDEO_CHAT_UNAVAILABLE_NOTE,
    lecture_video_chat_metadata,
    lecture_video_manifest_from_model,
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


@dataclass
class LectureChatTurnPreparation:
    prepended_messages: list[models.Message]
    user_output_index: int


def _apply_lecture_video_chat_metadata(thread: models.Thread) -> None:
    thread.lecture_video_chat_available = lecture_video_chat_metadata(
        thread.lecture_video
    )


def _transcript_timestamp_scale(
    words: list[schemas.LectureVideoManifestWordV2],
) -> int:
    numeric_bounds = [(float(word.start), float(word.end)) for word in words]
    if any(
        not start.is_integer() or not end.is_integer() for start, end in numeric_bounds
    ):
        return 1000

    positive_deltas = [end - start for start, end in numeric_bounds if end > start] + [
        next_start - start
        for (start, _), (next_start, _) in zip(numeric_bounds, numeric_bounds[1:])
        if next_start > start
    ]

    # Decide the unit once for the whole transcript. Whole-second manifests tend
    # to have very small positive deltas between words; millisecond manifests do
    # not. This avoids mixing units based on the magnitude of individual values.
    smallest_positive_delta = min(positive_deltas, default=None)
    if smallest_positive_delta is not None and smallest_positive_delta <= 10:
        return 1000

    return 1


def _normalize_timestamp_ms(value: int | float, *, scale: int) -> int:
    return max(0, int(round(float(value) * scale)))


def _serialize_transcript_words(
    words: list[schemas.LectureVideoManifestWordV2],
) -> list[tuple[int, int, str]]:
    scale = _transcript_timestamp_scale(words)
    return [
        (
            _normalize_timestamp_ms(word.start, scale=scale),
            _normalize_timestamp_ms(word.end, scale=scale),
            word.word,
        )
        for word in words
    ]


def _word_in_range(
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
        if _word_in_range(start_ms, end_ms, range_start_ms, range_end_ms)
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


async def _build_answered_knowledge_checks_text(
    session: AsyncSession, thread_id: int
) -> str:
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
        correct_option = question.correct_option
        correctness = (
            "correct"
            if correct_option is not None and correct_option.id == option.id
            else "incorrect"
        )
        feedback = (option.post_answer_text or "").strip() or "None"
        question_label = question.question_text.strip() or f"Question {question.id}"
        answer_lines.append(
            f"- {question_label}: selected {option.option_text}, {correctness}, feedback: {feedback}"
        )
    return "\n".join(answer_lines) if answer_lines else "None"


def _build_context_text(
    thread: models.Thread,
    state: models.LectureVideoThreadState,
    manifest: schemas.LectureVideoManifestV2,
) -> tuple[str, int]:
    current_offset_ms = max(0, state.last_known_offset_ms)
    transcript_words = _serialize_transcript_words(manifest.word_level_transcription)

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
    transcript_label = "Recent transcript context"
    if uncapped_transcript_start_ms > 0:
        transcript_label = "Recent transcript since last lecture chat"
    if transcript_start_ms > uncapped_transcript_start_ms:
        transcript_label += " (older transcript omitted)"

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

    current_question = _get_current_question(thread, state)
    next_question = _get_next_question(thread, current_question)

    current_question_line = (
        f"Current question id: {current_question.id}"
        if current_question is not None
        else "Current question id: None"
    )
    next_question_line = (
        f"Next question id: {next_question.id}"
        if next_question is not None
        else "Next question id: None"
    )

    context_lines = [
        "Lecture chat context",
        f"Current offset: {current_offset_ms}ms",
        f"Session state: {state.state.value}",
        current_question_line,
        next_question_line,
        f"{transcript_label}: {transcript_text or 'None'}",
        f"Lookahead: {lookahead_text or 'None'}",
    ]

    return "\n".join(context_lines), current_offset_ms


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
) -> LectureChatContextBuildResult:
    lecture_video = thread.lecture_video
    state = thread.lecture_video_state
    if lecture_video is None or state is None:
        raise ValueError(
            "Lecture video thread context must be loaded before building chat context."
        )

    manifest = lecture_video_manifest_from_model(lecture_video)
    if not isinstance(manifest, schemas.LectureVideoManifestV2):
        raise ValueError("Lecture chat requires a version 2 lecture video manifest.")

    context_text, current_offset_ms = _build_context_text(thread, state, manifest)
    answered_knowledge_checks = await _build_answered_knowledge_checks_text(
        session, thread.id
    )
    text_part = models.MessagePart(
        part_index=0,
        type=schemas.MessagePartType.INPUT_TEXT,
        text=f"{context_text}\nKnowledge checks answered:\n{answered_knowledge_checks}",
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
    if lecture_state.state == schemas.LectureVideoSessionState.AWAITING_ANSWER:
        raise HTTPException(
            status_code=409,
            detail="Lecture chat is unavailable while you are answering a knowledge check.",
        )
    if lecture_state.state == schemas.LectureVideoSessionState.COMPLETED:
        raise HTTPException(
            status_code=409,
            detail="Lecture chat is unavailable after the lecture is completed.",
        )

    if lecture_state.state not in {
        schemas.LectureVideoSessionState.PLAYING,
        schemas.LectureVideoSessionState.AWAITING_POST_ANSWER_RESUME,
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
    )
