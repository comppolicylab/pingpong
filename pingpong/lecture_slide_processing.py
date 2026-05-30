import asyncio
import contextlib
import io
import json
import logging
import multiprocessing
import os
import secrets
import shutil
import socket
import tempfile
import time
from collections.abc import Callable, Coroutine, Mapping, Sequence
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path
from typing import Any, Literal, TypeVar, TypedDict, cast

import openai
import fitz
import uuid_utils as uuid
from openai.types.audio import TranscriptionWord
from openai.types.responses.response_input_param import ResponseInputParam
from pydantic import BaseModel, ConfigDict, Field, create_model
from pydub import AudioSegment
from sqlalchemy import and_, delete, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

import pingpong.models as models
import pingpong.schemas as schemas
from pingpong import lecture_video_processing
from pingpong.ai import get_openai_client_by_class_id
from pingpong.class_credential_validation import (
    ClassCredentialValidationSSLError,
    ClassCredentialValidationUnavailableError,
    ClassCredentialVoiceValidationError,
)
from pingpong.config import config
from pingpong.errors import capture_exception_to_sentry, sentry
from pingpong.elevenlabs import synthesize_elevenlabs_speech
from pingpong.lecture_video_manifest_generation import (
    DEFAULT_GENERATION_PROMPT_CONTENT,
    DEFAULT_VIDEO_DESCRIPTION_DURATION_MS,
    _augment_manifest_words_with_segment_text,
    _generation_transcript_source_text,
    _normalize_v4_context_arrays,
    build_generation_prompt,
)
from pingpong.lecture_video_service import (
    TRANSCRIPT_DATA_VERSION,
    lecture_video_words_to_webvtt,
)
from pingpong.now import utcnow
from pingpong.worker_pool import (
    DEFAULT_WORKER_POLL_INTERVAL_SECONDS,
    DEFAULT_WORKER_SHUTDOWN_GRACE_SECONDS,
    RunAssignment,
    WorkerCompleted,
    WorkerJobException,
    WorkerPoolManager,
    WorkerReady,
    WorkerStarted,
    ignore_sigint_in_worker,
)

logger = logging.getLogger(__name__)

_ResponseModelT = TypeVar("_ResponseModelT", bound=BaseModel)
_TranscriptionWordField = Literal["word", "start", "end"]
_TranscriptionWordValue = str | int | float


class SlidePageRange(TypedDict):
    slide_position: int
    start_offset_ms: int | None
    end_offset_ms: int | None


DEFAULT_NARRATION_PROMPT = """You are the instructor giving a lecture from this PDF slide deck.

Critical rules:
- Use the PDF itself as the source of truth.
- Write narration as if you are speaking live to students while each slide is visible.
- Teach the material on the slide; do not merely describe the slide's layout.
- Stay grounded in what appears on the current slide and the necessary connective context from earlier slides.
- Do not invent facts, examples, equations, citations, or course context that are not supported by the deck.
- Do not mention the PDF, the prompt, the model, schemas, extraction, or any implementation details.

For each slide:
1. Explain the slide's main point in a clear instructor voice.
2. Connect it briefly to the previous slide when that helps the lecture flow.
3. Highlight important definitions, steps, diagrams, equations, or contrasts visible on the slide.
4. Use natural spoken language suitable for text-to-speech.
5. Keep the narration focused and proportional to the slide's density: usually 30 to 90 seconds of spoken content, shorter for simple transition slides.

Output requirements:
- Return one narration item per slide.
- Use zero-based slide_position values.
- Keep narration_text as plain spoken prose, with no markdown, bullets, slide labels, or stage directions."""

RUN_LEASE_DURATION = timedelta(minutes=10)
RUN_LEASE_HEARTBEAT_INTERVAL = min(timedelta(minutes=1), RUN_LEASE_DURATION / 2)
UNEXPECTED_WORKER_EXIT_ERROR_MESSAGE = "Lecture slide worker exited unexpectedly."
LECTURE_SLIDE_AUDIO_CONTENT_TYPE = "audio/ogg"
MAX_RUN_CREATE_RETRIES = 3
OPENAI_GENERATION_MAX_ATTEMPTS = 3
OPENAI_GENERATION_RETRY_DELAY_SECONDS = 5.0
SLIDE_MANIFEST_CHUNK_DURATION_MS = 5 * 60 * 1000
SLIDE_MANIFEST_CHUNK_OVERLAP_MS = DEFAULT_VIDEO_DESCRIPTION_DURATION_MS
SLIDE_MANIFEST_CHUNK_MIN_SPLIT_MS = 60 * 1000
_ACTIVE_RUN_STATUSES = (
    schemas.LectureSlideProcessingRunStatus.QUEUED,
    schemas.LectureSlideProcessingRunStatus.RUNNING,
)
_STAGE_SEQUENCE = (
    schemas.LectureSlideProcessingStage.SLIDE_ASSET_EXTRACTION,
    schemas.LectureSlideProcessingStage.NARRATION_TEXT,
    schemas.LectureSlideProcessingStage.NARRATION_AUDIO,
    schemas.LectureSlideProcessingStage.NARRATION_TRANSCRIPTION,
    schemas.LectureSlideProcessingStage.MANIFEST_GENERATION,
    schemas.LectureSlideProcessingStage.COMPOSITE_ARTIFACTS,
)


class GeneratedSlideNarration(BaseModel):
    model_config = ConfigDict(extra="forbid")

    slide_position: int = Field(..., ge=0)
    title: str | None = None
    narration_text: str = Field(..., min_length=1)


class GeneratedSlideNarrationSet(BaseModel):
    model_config = ConfigDict(extra="forbid")

    slides: list[GeneratedSlideNarration] = Field(..., min_length=1)


def _generated_slide_narration_set_model(
    slide_count: int,
) -> type[GeneratedSlideNarrationSet]:
    if slide_count < 1:
        raise ValueError(
            "Lecture slide narration generation requires at least one slide."
        )
    return cast(
        type[GeneratedSlideNarrationSet],
        create_model(
            f"GeneratedSlideNarrationSet{slide_count}Slides",
            __base__=GeneratedSlideNarrationSet,
            slides=(
                list[GeneratedSlideNarration],
                Field(..., min_length=slide_count, max_length=slide_count),
            ),
        ),
    )


class GeneratedSlideChoice(BaseModel):
    model_config = ConfigDict(extra="forbid")

    option_text: str = Field(..., min_length=1)
    post_answer_text: str = ""
    correct: bool
    continue_slide_position: int | None = Field(None, ge=0)
    continue_slide_offset_ms: int | None = Field(None, ge=0)
    continue_offset_ms: int = Field(..., ge=0)


class GeneratedSlideQuestion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    slide_position: int = Field(..., ge=0)
    slide_offset_ms: int = Field(..., ge=0)
    stop_offset_ms: int = Field(..., ge=0)
    question_text: str = Field(..., min_length=1)
    intro_text: str = ""
    options: list[GeneratedSlideChoice] = Field(..., min_length=2)


class GeneratedSlideManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    questions: list[GeneratedSlideQuestion] = Field(default_factory=list)
    summary_checkpoints: list[schemas.LectureVideoManifestSummaryCheckpointV4] = Field(
        ..., min_length=1
    )
    moment_contexts: list[schemas.LectureVideoManifestMomentContextV4] = Field(
        ..., min_length=1
    )


def _build_slide_manifest_generation_instructions(
    content_section: str,
    *,
    total_duration_ms: int | None,
    generation_start_ms: int | None = None,
    generation_end_ms: int | None = None,
    context_start_ms: int | None = None,
    context_end_ms: int | None = None,
) -> str:
    video_instructions = build_generation_prompt(
        content_section,
        video_duration_ms=total_duration_ms,
        generation_start_ms=generation_start_ms,
        generation_end_ms=generation_end_ms,
        context_start_ms=context_start_ms,
        context_end_ms=context_end_ms,
        video_description_window_ms=DEFAULT_VIDEO_DESCRIPTION_DURATION_MS,
    )
    return f"""{video_instructions}

SLIDE LESSON MANIFEST ADAPTATION:
- Treat the attached PDF as the visible lesson media and the word-level transcript
  as the generated narration timeline for the slide lesson.
- Use the PDF, slide timing source data, and transcript together. Do not rely on
  extracted slide text.
- The output schema is GeneratedSlideManifest. Do not emit lecture-video word-ID
  fields such as pause_after_word_id, pause_after_word, resume_at_word_id, or
  resume_at_word.
- Use zero-based slide_position values from the supplied slide timing ranges.
- Use absolute millisecond offsets from the combined narration timeline for
  stop_offset_ms, continue_offset_ms, summary_checkpoints, and moment_contexts.
- Use slide_offset_ms as the offset within the visible slide where the question
  appears.
- Options use option_text, post_answer_text, continue_offset_ms, correct, and
  optional continue_slide_position / continue_slide_offset_ms when the resume
  point is naturally described in slide coordinates.
- Exactly one option must have correct=true for every question.
- If a generation window is provided, create questions only inside that window,
  but use the surrounding context window to avoid boundary artifacts.
"""


def _slide_timing_source_text(page_ranges: list[SlidePageRange]) -> str:
    return (
        "SLIDE TIMING SOURCE DATA:\n"
        "Each range uses zero-based slide_position values and absolute "
        "millisecond offsets in the combined narration timeline.\n\n"
        f"{json.dumps(page_ranges, indent=2)}"
    )


def _slide_generation_final_task_text() -> str:
    return (
        "Based on the PDF, slide timing source data, and word-level transcript "
        "source data above, generate the interactive slide lesson manifest now. "
        "Follow the instructions and return only the schema-valid JSON object."
    )


@dataclass(frozen=True)
class ExtractedSlideAsset:
    position: int
    image_path: str
    width_px: int
    height_px: int
    extracted_text: str | None


@dataclass(frozen=True)
class SlideAudioArtifact:
    page_id: int
    page_position: int
    content_type: str
    audio: bytes
    duration_ms: int
    store_key: str
    stored_object_id: int


@dataclass(frozen=True)
class SlideManifestGenerationChunk:
    generation_start_ms: int
    generation_end_ms: int
    context_start_ms: int
    context_end_ms: int

    @property
    def generation_duration_ms(self) -> int:
        return self.generation_end_ms - self.generation_start_ms


class LectureSlideWorkerPoolManager(WorkerPoolManager):
    def __init__(
        self,
        *,
        workers: int,
        poll_interval_seconds: float = DEFAULT_WORKER_POLL_INTERVAL_SECONDS,
        shutdown_grace_seconds: float = DEFAULT_WORKER_SHUTDOWN_GRACE_SECONDS,
        process_context: Any | None = None,
        claim_run_fn: Callable[[str], tuple[int, str] | None] | None = None,
        recover_run_fn: Callable[[int, str, str], bool] | None = None,
        sleep_fn: Callable[[float], None] = time.sleep,
        time_fn: Callable[[], float] = time.monotonic,
    ) -> None:
        self.async_runner: asyncio.Runner | None = None
        super().__init__(
            workers=workers,
            worker_target=_worker_process_main,
            process_context=process_context or get_forkserver_context(),
            claim_run_fn=claim_run_fn or self._claim_next_processing_run_sync,
            recover_run_fn=recover_run_fn or self._recover_failed_processing_run_sync,
            build_runner_id_fn=build_runner_id,
            worker_label="lecture processing worker",
            unexpected_exit_error_message=UNEXPECTED_WORKER_EXIT_ERROR_MESSAGE,
            poll_interval_seconds=poll_interval_seconds,
            shutdown_grace_seconds=shutdown_grace_seconds,
            sleep_fn=sleep_fn,
            time_fn=time_fn,
        )

    def _ensure_async_runner(self) -> asyncio.Runner:
        if self.async_runner is None:
            self.async_runner = asyncio.Runner()
        return self.async_runner

    def _claim_next_processing_run_sync(self, runner_id: str) -> tuple[int, str] | None:
        return self._ensure_async_runner().run(
            claim_next_any_processing_run(leased_by=runner_id)
        )

    def _recover_failed_processing_run_sync(
        self,
        run_id: int,
        lease_token: str,
        error_message: str,
    ) -> bool:
        return self._ensure_async_runner().run(
            recover_failed_processing_run(
                run_id,
                lease_token,
                error_message=error_message,
            )
        )

    def _shutdown_resources(self) -> None:
        if self.async_runner is not None:
            self.async_runner.close()
            self.async_runner = None


def build_runner_id(worker_slot: int | None = None, pid: int | None = None) -> str:
    effective_pid = pid if pid is not None else os.getpid()
    if worker_slot is None:
        return f"lecture-processing:{socket.gethostname()}:{effective_pid}"
    return (
        f"lecture-processing:{socket.gethostname()}:{effective_pid}:"
        f"worker-{worker_slot}"
    )


def get_forkserver_context() -> multiprocessing.context.BaseContext:
    if "forkserver" not in multiprocessing.get_all_start_methods():
        raise RuntimeError(
            "The lecture processing worker pool requires the 'forkserver' start method."
        )
    return multiprocessing.get_context("forkserver")


def run_processing_worker_pool(
    *,
    workers: int = 1,
    poll_interval_seconds: float = DEFAULT_WORKER_POLL_INTERVAL_SECONDS,
    shutdown_grace_seconds: float = DEFAULT_WORKER_SHUTDOWN_GRACE_SECONDS,
    process_context: Any | None = None,
    claim_run_fn: Callable[[str], tuple[int, str] | None] | None = None,
    recover_run_fn: Callable[[int, str, str], bool] | None = None,
    sleep_fn: Callable[[float], None] = time.sleep,
    time_fn: Callable[[], float] = time.monotonic,
) -> None:
    manager = LectureSlideWorkerPoolManager(
        workers=workers,
        poll_interval_seconds=poll_interval_seconds,
        shutdown_grace_seconds=shutdown_grace_seconds,
        process_context=process_context,
        claim_run_fn=claim_run_fn,
        recover_run_fn=recover_run_fn,
        sleep_fn=sleep_fn,
        time_fn=time_fn,
    )
    manager.run()


def _worker_process_main(worker_slot: int, assignment_queue, result_queue) -> None:
    with sentry():
        ignore_sigint_in_worker()
        result_queue.put(WorkerReady(worker_slot=worker_slot, pid=os.getpid()))
        with asyncio.Runner() as runner:
            while True:
                assignment = assignment_queue.get()
                if assignment is None:
                    logger.info(
                        "Lecture processing worker shutting down. slot=%s pid=%s",
                        worker_slot,
                        os.getpid(),
                    )
                    return
                if not isinstance(assignment, RunAssignment):
                    raise TypeError(
                        f"Expected RunAssignment, got {type(assignment).__name__}"
                    )

                result_queue.put(
                    WorkerStarted(
                        worker_slot=worker_slot,
                        run_id=assignment.run_id,
                        lease_token=assignment.lease_token,
                    )
                )
                try:
                    runner.run(
                        process_claimed_run(assignment.run_id, assignment.lease_token)
                    )
                except Exception as exc:
                    logger.exception(
                        "Lecture processing worker failed. run_id=%s slot=%s pid=%s",
                        assignment.run_id,
                        worker_slot,
                        os.getpid(),
                    )
                    capture_exception_to_sentry(
                        exc,
                        source="lecture-processing-worker-child",
                        worker_slot=worker_slot,
                        pid=os.getpid(),
                        run_id=assignment.run_id,
                    )
                    result_queue.put(
                        WorkerJobException(
                            worker_slot=worker_slot,
                            run_id=assignment.run_id,
                            lease_token=assignment.lease_token,
                            error_message=str(exc)
                            or UNEXPECTED_WORKER_EXIT_ERROR_MESSAGE,
                        )
                    )
                else:
                    result_queue.put(
                        WorkerCompleted(
                            worker_slot=worker_slot,
                            run_id=assignment.run_id,
                            lease_token=assignment.lease_token,
                        )
                    )


async def queue_lecture_slide_processing_run(
    session: AsyncSession,
    deck: models.LectureSlideDeck,
    *,
    requested_by_assistant_id: int | None = None,
) -> models.LectureSlideProcessingRun | None:
    if deck.status == schemas.LectureSlideDeckStatus.FAILED:
        deck.status = schemas.LectureSlideDeckStatus.PROCESSING
    if deck.status not in {
        schemas.LectureSlideDeckStatus.UPLOADED,
        schemas.LectureSlideDeckStatus.PROCESSING,
    }:
        return None

    existing_run = await models.LectureSlideProcessingRun.get_non_terminal_by_snapshot(
        session,
        deck.id,
    )
    if existing_run is not None:
        return existing_run

    deck.status = schemas.LectureSlideDeckStatus.PROCESSING
    deck.error_message = None
    attempt_number = (
        await models.LectureSlideProcessingRun.get_latest_attempt_number(
            session,
            deck.id,
        )
        + 1
    )
    last_error: IntegrityError | None = None
    for _ in range(MAX_RUN_CREATE_RETRIES):
        async with session.begin_nested() as savepoint:
            try:
                return await models.LectureSlideProcessingRun.create(
                    session,
                    lecture_slide_deck_id=deck.id,
                    lecture_slide_deck_id_snapshot=deck.id,
                    class_id=deck.class_id,
                    assistant_id_at_start=requested_by_assistant_id,
                    stage=schemas.LectureSlideProcessingStage.SLIDE_ASSET_EXTRACTION,
                    attempt_number=attempt_number,
                    status=schemas.LectureSlideProcessingRunStatus.QUEUED,
                )
            except IntegrityError as exc:
                last_error = exc
                await savepoint.rollback()

        existing_run = (
            await models.LectureSlideProcessingRun.get_non_terminal_by_snapshot(
                session,
                deck.id,
            )
        )
        if existing_run is not None:
            return existing_run
        attempt_number = (
            await models.LectureSlideProcessingRun.get_latest_attempt_number(
                session,
                deck.id,
            )
            + 1
        )

    assert last_error is not None
    raise last_error


def _claimable_processing_run_condition(now) -> Any:
    return or_(
        models.LectureSlideProcessingRun.status
        == schemas.LectureSlideProcessingRunStatus.QUEUED,
        and_(
            models.LectureSlideProcessingRun.status
            == schemas.LectureSlideProcessingRunStatus.RUNNING,
            or_(
                models.LectureSlideProcessingRun.lease_expires_at.is_(None),
                models.LectureSlideProcessingRun.lease_expires_at < now,
            ),
        ),
    )


async def claim_next_processing_run(
    *,
    leased_by: str | None = None,
) -> tuple[int, str] | None:
    async with config.db.driver.async_session() as session:
        now = utcnow()
        condition = _claimable_processing_run_condition(now)
        effective_leased_by = leased_by or build_runner_id()
        candidate_ids = list(
            (
                await session.scalars(
                    select(models.LectureSlideProcessingRun.id)
                    .where(condition)
                    .order_by(
                        func.coalesce(
                            models.LectureSlideProcessingRun.created, now
                        ).asc(),
                        models.LectureSlideProcessingRun.id.asc(),
                    )
                    .limit(25)
                )
            ).all()
        )
        for candidate_id in candidate_ids:
            lease_token = secrets.token_urlsafe(24)
            result = await session.execute(
                update(models.LectureSlideProcessingRun)
                .where(models.LectureSlideProcessingRun.id == candidate_id)
                .where(condition)
                .values(
                    status=schemas.LectureSlideProcessingRunStatus.RUNNING,
                    lease_token=lease_token,
                    leased_by=effective_leased_by,
                    lease_expires_at=now + RUN_LEASE_DURATION,
                    started_at=func.coalesce(
                        models.LectureSlideProcessingRun.started_at, now
                    ),
                    cancel_reason=None,
                    finished_at=None,
                )
            )
            if result.rowcount:
                await session.commit()
                return candidate_id, lease_token
    return None


async def claim_next_any_processing_run(
    *,
    leased_by: str | None = None,
) -> tuple[int, str] | None:
    async with config.db.driver.async_session() as session:
        now = utcnow()
        slide_result = await session.execute(
            select(
                models.LectureSlideProcessingRun.id,
                models.LectureSlideProcessingRun.created,
            )
            .where(_claimable_processing_run_condition(now))
            .order_by(
                func.coalesce(models.LectureSlideProcessingRun.created, now).asc(),
                models.LectureSlideProcessingRun.id.asc(),
            )
            .limit(1)
        )
        slide_candidate = slide_result.first()
        video_result = await session.execute(
            select(
                models.LectureVideoProcessingRun.id,
                models.LectureVideoProcessingRun.created,
            )
            .where(lecture_video_processing._claimable_processing_run_condition(now))
            .order_by(
                func.coalesce(models.LectureVideoProcessingRun.created, now).asc(),
                models.LectureVideoProcessingRun.id.asc(),
            )
            .limit(1)
        )
        video_candidate = video_result.first()

    try_video_first = False
    if video_candidate is not None and slide_candidate is None:
        try_video_first = True
    elif video_candidate is not None and slide_candidate is not None:
        video_created = video_candidate.created or utcnow()
        slide_created = slide_candidate.created or utcnow()
        try_video_first = (video_created, video_candidate.id) < (
            slide_created,
            slide_candidate.id,
        )

    if try_video_first:
        claimed_video = await lecture_video_processing._claim_next_processing_run(
            leased_by=leased_by
        )
        if claimed_video is not None:
            run_id, lease_token = claimed_video
            return -run_id, lease_token
        return await claim_next_processing_run(leased_by=leased_by)

    claimed_slide = await claim_next_processing_run(leased_by=leased_by)
    if claimed_slide is not None:
        return claimed_slide
    claimed_video = await lecture_video_processing._claim_next_processing_run(
        leased_by=leased_by
    )
    if claimed_video is None:
        return None
    run_id, lease_token = claimed_video
    return -run_id, lease_token


async def recover_failed_processing_run(
    run_id: int,
    lease_token: str,
    *,
    error_message: str = UNEXPECTED_WORKER_EXIT_ERROR_MESSAGE,
) -> bool:
    if run_id < 0:
        return await lecture_video_processing.recover_failed_processing_run(
            -run_id,
            lease_token,
            error_message=error_message,
        )
    async with config.db.driver.async_session() as session:
        run = await models.LectureSlideProcessingRun.get_by_id(session, run_id)
        if run is None:
            return False
        if (
            run.status != schemas.LectureSlideProcessingRunStatus.RUNNING
            or run.lease_token != lease_token
        ):
            return False
        run.status = schemas.LectureSlideProcessingRunStatus.FAILED
        run.error_message = error_message
        run.finished_at = utcnow()
        run.cancel_reason = None
        run.lease_token = None
        run.leased_by = None
        run.lease_expires_at = None
        if run.lecture_slide_deck_id is not None:
            deck = await models.LectureSlideDeck.get_by_id_with_processing_context(
                session, run.lecture_slide_deck_id
            )
            if deck is not None:
                deck.status = schemas.LectureSlideDeckStatus.FAILED
                deck.error_message = error_message
                session.add(deck)
        session.add(run)
        await session.commit()
        return True


async def process_claimed_run(run_id: int, lease_token: str) -> None:
    if run_id < 0:
        await lecture_video_processing._process_claimed_run(-run_id, lease_token)
        return
    await _process_claimed_slide_run(run_id, lease_token)


async def _process_claimed_slide_run(run_id: int, lease_token: str) -> None:
    try:
        async with config.db.driver.async_session() as session:
            run = await models.LectureSlideProcessingRun.get_by_id(session, run_id)
            if run is None:
                return
            if (
                run.status != schemas.LectureSlideProcessingRunStatus.RUNNING
                or run.lease_token != lease_token
                or run.lecture_slide_deck_id is None
            ):
                return
            deck_id = run.lecture_slide_deck_id
            class_id = run.class_id

        openai_client = None
        with tempfile.TemporaryDirectory(prefix="pingpong_ls_") as temp_dir:
            pdf_path = await _download_source_pdf(
                run_id, lease_token, deck_id, temp_dir
            )
            if pdf_path is None:
                return
            await _set_run_stage(
                run_id,
                lease_token,
                schemas.LectureSlideProcessingStage.SLIDE_ASSET_EXTRACTION,
            )
            await _extract_and_store_slide_assets(
                run_id, lease_token, deck_id, pdf_path
            )
            if not await _ensure_run_can_continue(run_id, lease_token):
                return

            async with config.db.driver.async_session() as session:
                openai_client = await get_openai_client_by_class_id(session, class_id)
                responses_model = await _get_responses_model_for_run(
                    session,
                    run_id,
                    deck_id,
                )

            await _set_run_stage(
                run_id,
                lease_token,
                schemas.LectureSlideProcessingStage.NARRATION_TEXT,
            )
            narration_set = await _generate_narration_text(
                run_id,
                lease_token,
                deck_id,
                pdf_path,
                responses_model,
                openai_client,
            )
            if narration_set is None:
                return
            await _persist_narration_text(run_id, lease_token, deck_id, narration_set)
            if not await _ensure_run_can_continue(run_id, lease_token):
                return

            await _set_run_stage(
                run_id,
                lease_token,
                schemas.LectureSlideProcessingStage.NARRATION_AUDIO,
            )
            slide_audio = await _synthesize_slide_audio(run_id, lease_token, deck_id)
            if slide_audio is None:
                return

            await _set_run_stage(
                run_id,
                lease_token,
                schemas.LectureSlideProcessingStage.NARRATION_TRANSCRIPTION,
            )
            transcript = await _transcribe_and_persist_slide_audio(
                run_id,
                lease_token,
                deck_id,
                slide_audio,
                openai_client,
                temp_dir,
            )
            if transcript is None:
                return

            await _set_run_stage(
                run_id,
                lease_token,
                schemas.LectureSlideProcessingStage.MANIFEST_GENERATION,
            )
            manifest = await _generate_slide_manifest(
                run_id,
                lease_token,
                deck_id,
                pdf_path,
                transcript,
                responses_model,
                openai_client,
            )
            if manifest is None:
                return
            await _persist_slide_manifest(
                run_id, lease_token, deck_id, manifest, transcript
            )
            if not await _ensure_run_can_continue(run_id, lease_token):
                return

            await _set_run_stage(
                run_id,
                lease_token,
                schemas.LectureSlideProcessingStage.COMPOSITE_ARTIFACTS,
            )
            await _synthesize_knowledge_check_audio(run_id, lease_token, deck_id)
            await _persist_composite_artifacts(run_id, lease_token, deck_id, transcript)
            await _mark_run_completed(run_id, lease_token)
    except Exception as exc:
        logger.exception("Lecture slide processing failed. run_id=%s", run_id)
        await recover_failed_processing_run(
            run_id,
            lease_token,
            error_message=_user_safe_processing_error_message(exc),
        )


async def _await_with_run_lease_heartbeat(
    run_id: int,
    lease_token: str,
    operation: Coroutine[Any, Any, Any],
) -> Any | None:
    # Callers treat None as cancellation, so wrapped operations must return
    # non-None values.
    task: asyncio.Task[Any] = asyncio.create_task(operation)
    try:
        while True:
            done, _ = await asyncio.wait(
                {task},
                timeout=RUN_LEASE_HEARTBEAT_INTERVAL.total_seconds(),
            )
            if task in done:
                return await task
            if not await _ensure_run_can_continue(run_id, lease_token):
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
                return None
    except Exception:
        if not task.done():
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task
        raise


async def _set_run_stage(
    run_id: int,
    lease_token: str,
    stage: schemas.LectureSlideProcessingStage,
) -> bool:
    async with config.db.driver.async_session() as session:
        run = await models.LectureSlideProcessingRun.get_by_id(session, run_id)
        if run is None:
            return False
        if (
            run.status != schemas.LectureSlideProcessingRunStatus.RUNNING
            or run.lease_token != lease_token
        ):
            return False
        run.stage = stage
        run.lease_expires_at = utcnow() + RUN_LEASE_DURATION
        session.add(run)
        await session.commit()
        return True


async def _ensure_run_can_continue(run_id: int, lease_token: str) -> bool:
    async with config.db.driver.async_session() as session:
        run = await models.LectureSlideProcessingRun.get_by_id(session, run_id)
        if run is None:
            return False
        if (
            run.status != schemas.LectureSlideProcessingRunStatus.RUNNING
            or run.lease_token != lease_token
        ):
            return False
        if run.lecture_slide_deck_id is None:
            await _mark_run_cancelled(
                session,
                run,
                schemas.LectureSlideProcessingCancelReason.LECTURE_SLIDE_DECK_DELETED,
            )
            await session.commit()
            return False
        run.lease_expires_at = utcnow() + RUN_LEASE_DURATION
        session.add(run)
        await session.commit()
        return True


async def _mark_run_cancelled(
    session: AsyncSession,
    run: models.LectureSlideProcessingRun,
    cancel_reason: schemas.LectureSlideProcessingCancelReason,
) -> None:
    run.status = schemas.LectureSlideProcessingRunStatus.CANCELLED
    run.cancel_reason = cancel_reason
    run.finished_at = utcnow()
    run.lease_token = None
    run.leased_by = None
    run.lease_expires_at = None
    session.add(run)
    await session.flush()


async def _mark_run_completed(run_id: int, lease_token: str) -> None:
    async with config.db.driver.async_session() as session:
        run = await models.LectureSlideProcessingRun.get_by_id(session, run_id)
        if run is None:
            return
        if (
            run.status != schemas.LectureSlideProcessingRunStatus.RUNNING
            or run.lease_token != lease_token
        ):
            return
        if run.lecture_slide_deck_id is not None:
            deck = await models.LectureSlideDeck.get_by_id_with_processing_context(
                session, run.lecture_slide_deck_id
            )
            if deck is not None:
                deck.status = schemas.LectureSlideDeckStatus.READY
                deck.error_message = None
                session.add(deck)
        run.status = schemas.LectureSlideProcessingRunStatus.COMPLETED
        run.error_message = None
        run.finished_at = utcnow()
        run.lease_token = None
        run.leased_by = None
        run.lease_expires_at = None
        session.add(run)
        await session.commit()


async def _download_source_pdf(
    run_id: int,
    lease_token: str,
    deck_id: int,
    temp_dir: str,
) -> str | None:
    async with config.db.driver.async_session() as session:
        deck = await models.LectureSlideDeck.get_by_id_with_processing_context(
            session, deck_id
        )
        if deck is None:
            run = await models.LectureSlideProcessingRun.get_by_id(session, run_id)
            if run is not None and run.lease_token == lease_token:
                await _mark_run_cancelled(
                    session,
                    run,
                    schemas.LectureSlideProcessingCancelReason.LECTURE_SLIDE_DECK_DELETED,
                )
                await session.commit()
            return None
        if deck.source_stored_object is None:
            raise RuntimeError("Lecture slide source object is not loaded.")
        if not config.video_store:
            raise RuntimeError("Video store not configured or unavailable.")
        source_key = deck.source_stored_object.key

    pdf_path = os.path.join(temp_dir, f"lecture_slide_deck_{deck_id}.pdf")
    with open(pdf_path, "wb") as output:
        async for chunk in config.video_store.store.stream_video(source_key):
            await asyncio.to_thread(output.write, chunk)
    return pdf_path


async def _get_responses_model_for_run(
    session: AsyncSession,
    run_id: int,
    deck_id: int,
) -> str:
    run = await models.LectureSlideProcessingRun.get_by_id(session, run_id)
    if run is not None and run.assistant_id_at_start is not None:
        model = await session.scalar(
            select(models.Assistant.model).where(
                models.Assistant.id == run.assistant_id_at_start
            )
        )
        if model:
            return str(model)

    model = await session.scalar(
        select(models.Assistant.model)
        .where(models.Assistant.lecture_slide_deck_id == deck_id)
        .order_by(models.Assistant.id.asc())
        .limit(1)
    )
    if model:
        return str(model)

    raise RuntimeError("Lecture slide processing requires an assistant model.")


async def _extract_and_store_slide_assets(
    run_id: int,
    lease_token: str,
    deck_id: int,
    pdf_path: str,
) -> None:
    assets = await _await_with_run_lease_heartbeat(
        run_id,
        lease_token,
        asyncio.to_thread(extract_slide_assets_from_pdf, pdf_path),
    )
    if assets is None:
        return
    try:
        async with config.db.driver.async_session() as session:
            run = await models.LectureSlideProcessingRun.get_by_id(session, run_id)
            deck = await models.LectureSlideDeck.get_by_id_with_processing_context(
                session, deck_id
            )
            if (
                run is None
                or deck is None
                or run.status != schemas.LectureSlideProcessingRunStatus.RUNNING
                or run.lease_token != lease_token
            ):
                return

            await session.execute(
                delete(models.LectureSlidePage).where(
                    models.LectureSlidePage.lecture_slide_deck_id == deck.id
                )
            )
            await session.flush()

            for asset in assets:
                image_bytes = Path(asset.image_path).read_bytes()
                image_key = generate_slide_image_store_key()
                if not config.video_store:
                    raise RuntimeError("Video store not configured or unavailable.")
                await config.video_store.store.put(
                    image_key,
                    io.BytesIO(image_bytes),
                    "image/png",
                )
                image_stored_object = models.LectureSlideImageStoredObject(
                    key=image_key,
                    content_type="image/png",
                    content_length=len(image_bytes),
                    width_px=asset.width_px,
                    height_px=asset.height_px,
                )
                session.add(image_stored_object)
                await session.flush()
                session.add(
                    models.LectureSlidePage(
                        lecture_slide_deck_id=deck.id,
                        position=asset.position,
                        image_stored_object_id=image_stored_object.id,
                        extracted_text=asset.extracted_text,
                    )
                )
            deck.slide_count = len(assets)
            session.add(deck)
            await session.commit()
    finally:
        cleanup_extracted_slide_assets(assets)


def extract_slide_assets_from_pdf(pdf_path: str) -> list[ExtractedSlideAsset]:
    output_dir = tempfile.mkdtemp(prefix="pingpong_ls_extract_")
    try:
        assets: list[ExtractedSlideAsset] = []
        with fitz.open(pdf_path) as document:
            for page_index, page in enumerate(document):
                pixmap = page.get_pixmap(matrix=fitz.Matrix(2, 2), alpha=False)
                image_path = os.path.join(output_dir, f"page-{page_index + 1}.png")
                pixmap.save(image_path)
                text = page.get_text("text").strip()
                assets.append(
                    ExtractedSlideAsset(
                        position=page_index,
                        image_path=image_path,
                        width_px=pixmap.width,
                        height_px=pixmap.height,
                        extracted_text=text or None,
                    )
                )
        return assets
    except Exception:
        shutil.rmtree(output_dir, ignore_errors=True)
        raise


def cleanup_extracted_slide_assets(assets: Sequence[ExtractedSlideAsset]) -> None:
    output_dirs = {Path(asset.image_path).parent for asset in assets}
    for output_dir in output_dirs:
        shutil.rmtree(output_dir, ignore_errors=True)


async def _upload_openai_input_pdf(
    openai_client: openai.AsyncClient | openai.AsyncAzureOpenAI,
    pdf_path: str,
) -> str:
    with open(pdf_path, "rb") as pdf_file:
        uploaded_file = await openai_client.files.create(
            file=pdf_file,
            purpose="user_data",
        )
    file_id = getattr(uploaded_file, "id", None)
    if not file_id and isinstance(uploaded_file, dict):
        file_id = uploaded_file.get("id")
    if not file_id:
        raise RuntimeError("OpenAI did not return a file id for lecture slide PDF.")
    return str(file_id)


async def _delete_openai_file_quietly(
    openai_client: openai.AsyncClient | openai.AsyncAzureOpenAI,
    file_id: str,
) -> None:
    try:
        await openai_client.files.delete(file_id)
    except Exception:
        logger.exception(
            "Failed to delete uploaded lecture slide PDF file_id=%s", file_id
        )


async def _generate_narration_text(
    run_id: int,
    lease_token: str,
    deck_id: int,
    pdf_path: str,
    responses_model: str,
    openai_client: openai.AsyncClient | openai.AsyncAzureOpenAI,
) -> GeneratedSlideNarrationSet | None:
    async with config.db.driver.async_session() as session:
        deck = await models.LectureSlideDeck.get_by_id_with_processing_context(
            session, deck_id
        )
        if deck is None:
            return None
        prompt = deck.narration_prompt or DEFAULT_NARRATION_PROMPT
        slide_count = deck.slide_count
        response_model = _generated_slide_narration_set_model(slide_count)

    file_id = await _await_with_run_lease_heartbeat(
        run_id,
        lease_token,
        _upload_openai_input_pdf(openai_client, pdf_path),
    )
    if file_id is None:
        return None
    try:
        return await _await_with_run_lease_heartbeat(
            run_id,
            lease_token,
            _parse_responses_output(
                openai_client,
                model=responses_model,
                instructions=prompt,
                response_model=response_model,
                input_messages=[
                    {
                        "role": "user",
                        "content": [
                            {"type": "input_file", "file_id": file_id},
                            {
                                "type": "input_text",
                                "text": (
                                    f"Generate narration for exactly {slide_count} "
                                    "slides. Use zero-based "
                                    "slide_position values."
                                ),
                            },
                        ],
                    }
                ],
            ),
        )
    finally:
        await _delete_openai_file_quietly(openai_client, file_id)


async def _persist_narration_text(
    run_id: int,
    lease_token: str,
    deck_id: int,
    narration_set: GeneratedSlideNarrationSet,
) -> None:
    narration_by_position = {item.slide_position: item for item in narration_set.slides}
    async with config.db.driver.async_session() as session:
        run = await models.LectureSlideProcessingRun.get_by_id(session, run_id)
        deck = await models.LectureSlideDeck.get_by_id_with_processing_context(
            session, deck_id
        )
        if (
            run is None
            or deck is None
            or run.status != schemas.LectureSlideProcessingRunStatus.RUNNING
            or run.lease_token != lease_token
        ):
            return
        for page in deck.pages:
            generated = narration_by_position.get(page.position)
            if generated is None:
                raise ValueError(f"Missing narration for slide {page.position}.")
            page.title = generated.title
            page.narration_text = generated.narration_text
            session.add(page)
        await session.commit()


async def _synthesize_slide_audio(
    run_id: int,
    lease_token: str,
    deck_id: int,
) -> list[SlideAudioArtifact] | None:
    async with config.db.driver.async_session() as session:
        deck = await models.LectureSlideDeck.get_by_id_with_processing_context(
            session, deck_id
        )
        if deck is None:
            return None
        class_id = deck.class_id
        voice_id = deck.voice_id
        pages = [
            (page.id, page.position, page.narration_text or "")
            for page in sorted(deck.pages, key=lambda item: item.position)
            if text_needs_audio(page.narration_text or "")
        ]
    if not pages:
        return []
    if not voice_id:
        raise RuntimeError("Lecture slide deck voice_id is required for narration.")
    api_key = await _get_elevenlabs_api_key(class_id)
    artifacts: list[SlideAudioArtifact] = []
    for page_id, page_position, narration_text in pages:
        synthesis_result = await _await_with_run_lease_heartbeat(
            run_id,
            lease_token,
            synthesize_elevenlabs_speech(api_key, voice_id, narration_text),
        )
        if synthesis_result is None:
            # Existing stored slide audio is retained on mid-run cancellation,
            # matching lecture-video retry behavior.
            return None
        _, audio = synthesis_result
        content_type = LECTURE_SLIDE_AUDIO_CONTENT_TYPE
        duration_ms = audio_duration_ms(audio, content_type)
        store_key, content_length = await _store_audio(
            generate_slide_narration_store_key(),
            content_type,
            audio,
        )
        async with config.db.driver.async_session() as session:
            run = await models.LectureSlideProcessingRun.get_by_id(session, run_id)
            page = await session.get(models.LectureSlidePage, page_id)
            if (
                run is None
                or page is None
                or run.status != schemas.LectureSlideProcessingRunStatus.RUNNING
                or run.lease_token != lease_token
            ):
                await _delete_audio_key_quietly(store_key)
                return None
            stored_object = models.LectureSlideNarrationStoredObject(
                key=store_key,
                content_type=content_type,
                content_length=content_length,
                duration_ms=duration_ms,
            )
            session.add(stored_object)
            await session.flush()
            narration = models.LectureSlideNarration(
                stored_object_id=stored_object.id,
                status=schemas.LectureSlideNarrationStatus.READY,
            )
            session.add(narration)
            await session.flush()
            page.narration_id = narration.id
            page.narration_stored_object_id = stored_object.id
            session.add(page)
            await session.commit()
            artifacts.append(
                SlideAudioArtifact(
                    page_id=page_id,
                    page_position=page_position,
                    content_type=content_type,
                    audio=audio,
                    duration_ms=duration_ms,
                    store_key=store_key,
                    stored_object_id=stored_object.id,
                )
            )
    return artifacts


async def _get_elevenlabs_api_key(class_id: int) -> str:
    async with config.db.driver.async_session() as session:
        credential = await models.ClassCredential.get_by_class_id_and_purpose(
            session,
            class_id,
            schemas.ClassCredentialPurpose.LECTURE_VIDEO_NARRATION_TTS,
        )
        if credential is None or credential.api_key_obj is None:
            raise RuntimeError(
                "An ElevenLabs credential is required before lecture slide narration can be generated."
            )
        return credential.api_key_obj.api_key


async def _store_audio(
    store_key: str,
    content_type: str,
    audio: bytes,
) -> tuple[str, int]:
    if not config.lecture_video_audio_store:
        raise RuntimeError("Lecture video audio store is not configured.")
    upload = await config.lecture_video_audio_store.store.create_upload(
        name=store_key,
        content_type=content_type,
    )
    try:
        await upload.upload_part(io.BytesIO(audio))
        await upload.complete_upload()
    except Exception:
        with contextlib.suppress(Exception):
            await upload.delete_file()
        raise
    return store_key, len(audio)


async def _transcribe_and_persist_slide_audio(
    run_id: int,
    lease_token: str,
    deck_id: int,
    slide_audio: list[SlideAudioArtifact],
    openai_client: openai.AsyncClient | openai.AsyncAzureOpenAI,
    temp_dir: str,
) -> list[schemas.LectureVideoManifestWordV3] | None:
    words: list[schemas.LectureVideoManifestWordV3] = []
    current_offset_ms = 0
    page_timings: dict[int, tuple[int, int]] = {}
    for artifact in sorted(slide_audio, key=lambda item: item.page_position):
        slide_path = os.path.join(temp_dir, f"slide-{artifact.page_position}.audio")
        Path(slide_path).write_bytes(artifact.audio)
        slide_words = await _await_with_run_lease_heartbeat(
            run_id,
            lease_token,
            transcribe_audio_words(slide_path, openai_client),
        )
        if slide_words is None:
            return None
        for word_index, word in enumerate(slide_words):
            words.append(
                schemas.LectureVideoManifestWordV3(
                    id=f"slide-{artifact.page_position}-word-{word_index}",
                    word=word.word,
                    start_offset_ms=word.start_offset_ms + current_offset_ms,
                    end_offset_ms=word.end_offset_ms + current_offset_ms,
                )
            )
        page_timings[artifact.page_id] = (
            current_offset_ms,
            current_offset_ms + artifact.duration_ms,
        )
        current_offset_ms += artifact.duration_ms

    async with config.db.driver.async_session() as session:
        run = await models.LectureSlideProcessingRun.get_by_id(session, run_id)
        deck = await models.LectureSlideDeck.get_by_id_with_processing_context(
            session, deck_id
        )
        if (
            run is None
            or deck is None
            or run.status != schemas.LectureSlideProcessingRunStatus.RUNNING
            or run.lease_token != lease_token
        ):
            return None
        for page in deck.pages:
            start, end = page_timings.get(page.id, (None, None))
            page.start_offset_ms = start
            page.end_offset_ms = end
            session.add(page)
        deck.total_duration_ms = current_offset_ms
        deck.transcript_data = transcript_data_from_words(words)
        session.add(deck)
        await session.commit()
    return words


async def transcribe_audio_words(
    audio_path: str,
    openai_client: openai.AsyncClient | openai.AsyncAzureOpenAI,
) -> list[schemas.LectureVideoManifestWordV3]:
    with open(audio_path, "rb") as audio_file:
        transcription = await openai_client.audio.transcriptions.create(
            file=audio_file,
            model="whisper-1",
            response_format="verbose_json",
            timestamp_granularities=["word", "segment"],
            timeout=60 * 20,
        )
    raw_words = getattr(transcription, "words", None)
    if raw_words is None and isinstance(transcription, dict):
        raw_words = transcription.get("words")
    segments = getattr(transcription, "segments", None)
    if segments is None and isinstance(transcription, dict):
        segments = transcription.get("segments")
    if not raw_words:
        raise ValueError("OpenAI transcription returned no word-level timestamps.")
    manifest_words: list[dict[str, object]] = []
    for index, word in enumerate(raw_words):
        raw_word_value = _get_attr_or_key(word, "word")
        if raw_word_value is None:
            continue
        raw_word = str(raw_word_value).strip()
        if not raw_word:
            continue
        start_value = _get_attr_or_key(word, "start")
        end_value = _get_attr_or_key(word, "end")
        start = _seconds_to_ms(start_value or 0)
        end = _seconds_to_ms(end_value or 0)
        manifest_words.append(
            {
                "id": f"word-{index}",
                "word": raw_word,
                "start_offset_ms": start,
                "end_offset_ms": end,
            }
        )
    if not manifest_words:
        raise ValueError("OpenAI transcription returned no non-empty words.")
    return [
        schemas.LectureVideoManifestWordV3.model_validate(word)
        for word in _augment_manifest_words_with_segment_text(manifest_words, segments)
    ]


def _slide_manifest_total_duration_ms(
    *,
    deck_total_duration_ms: int | None,
    page_ranges: list[SlidePageRange],
    transcript: list[schemas.LectureVideoManifestWordV3],
) -> int | None:
    candidates = [
        value
        for value in [
            deck_total_duration_ms,
            *(page_range["end_offset_ms"] for page_range in page_ranges),
            *(word.end_offset_ms for word in transcript),
        ]
        if value is not None
    ]
    return max(candidates) if candidates else None


def _transcript_for_slide_window(
    transcript: list[schemas.LectureVideoManifestWordV3],
    *,
    start_offset_ms: int,
    end_offset_ms: int,
) -> list[schemas.LectureVideoManifestWordV3]:
    return [
        word
        for word in transcript
        if word.end_offset_ms >= start_offset_ms
        and word.start_offset_ms <= end_offset_ms
    ]


def _page_ranges_for_slide_window(
    page_ranges: list[SlidePageRange],
    *,
    start_offset_ms: int,
    end_offset_ms: int,
) -> list[SlidePageRange]:
    return [
        page_range
        for page_range in page_ranges
        if page_range["end_offset_ms"] is None
        or page_range["start_offset_ms"] is None
        or (
            page_range["end_offset_ms"] >= start_offset_ms
            and page_range["start_offset_ms"] <= end_offset_ms
        )
    ]


def _plan_slide_manifest_generation_chunks(
    total_duration_ms: int,
) -> list[SlideManifestGenerationChunk]:
    if total_duration_ms <= SLIDE_MANIFEST_CHUNK_DURATION_MS:
        return [
            SlideManifestGenerationChunk(
                generation_start_ms=0,
                generation_end_ms=total_duration_ms,
                context_start_ms=0,
                context_end_ms=total_duration_ms,
            )
        ]
    chunks: list[SlideManifestGenerationChunk] = []
    generation_start_ms = 0
    while generation_start_ms < total_duration_ms:
        generation_end_ms = min(
            generation_start_ms + SLIDE_MANIFEST_CHUNK_DURATION_MS,
            total_duration_ms,
        )
        chunks.append(
            SlideManifestGenerationChunk(
                generation_start_ms=generation_start_ms,
                generation_end_ms=generation_end_ms,
                context_start_ms=max(
                    0, generation_start_ms - SLIDE_MANIFEST_CHUNK_OVERLAP_MS
                ),
                context_end_ms=min(
                    total_duration_ms,
                    generation_end_ms + SLIDE_MANIFEST_CHUNK_OVERLAP_MS,
                ),
            )
        )
        generation_start_ms = generation_end_ms
    return chunks


def _split_slide_manifest_generation_chunk(
    chunk: SlideManifestGenerationChunk,
    *,
    total_duration_ms: int,
) -> list[SlideManifestGenerationChunk]:
    split_ms = chunk.generation_start_ms + chunk.generation_duration_ms // 2
    return [
        SlideManifestGenerationChunk(
            generation_start_ms=chunk.generation_start_ms,
            generation_end_ms=split_ms,
            context_start_ms=chunk.context_start_ms,
            context_end_ms=min(
                total_duration_ms, split_ms + SLIDE_MANIFEST_CHUNK_OVERLAP_MS
            ),
        ),
        SlideManifestGenerationChunk(
            generation_start_ms=split_ms,
            generation_end_ms=chunk.generation_end_ms,
            context_start_ms=max(0, split_ms - SLIDE_MANIFEST_CHUNK_OVERLAP_MS),
            context_end_ms=chunk.context_end_ms,
        ),
    ]


def _filter_slide_questions_for_window(
    questions: list[GeneratedSlideQuestion],
    *,
    start_offset_ms: int,
    end_offset_ms: int,
    is_final_chunk: bool,
) -> list[GeneratedSlideQuestion]:
    return [
        question
        for question in questions
        if start_offset_ms <= question.stop_offset_ms
        and (
            question.stop_offset_ms < end_offset_ms
            or (is_final_chunk and question.stop_offset_ms <= end_offset_ms)
        )
    ]


def _validate_generated_slide_manifest(
    manifest: GeneratedSlideManifest,
    *,
    page_ranges: list[SlidePageRange],
    total_duration_ms: int | None,
) -> GeneratedSlideManifest:
    page_range_by_position = {
        int(page_range["slide_position"]): page_range for page_range in page_ranges
    }
    for question in manifest.questions:
        page_range = page_range_by_position.get(question.slide_position)
        if page_range is None:
            raise ValueError(
                f"Generated slide question references unknown slide_position "
                f"{question.slide_position}."
            )
        page_start_ms = page_range["start_offset_ms"]
        page_end_ms = page_range["end_offset_ms"]
        if page_start_ms is not None and page_end_ms is not None:
            page_duration_ms = max(page_end_ms - page_start_ms, 0)
            if question.slide_offset_ms > page_duration_ms:
                raise ValueError(
                    "Generated slide question has slide_offset_ms outside the "
                    f"slide duration. slide_position={question.slide_position}"
                )
            if not page_start_ms <= question.stop_offset_ms <= page_end_ms:
                raise ValueError(
                    "Generated slide question has stop_offset_ms outside its "
                    f"slide range. slide_position={question.slide_position}"
                )
        if (
            total_duration_ms is not None
            and question.stop_offset_ms > total_duration_ms
        ):
            raise ValueError("Generated slide question pause point exceeds duration.")
        correct_count = sum(1 for option in question.options if option.correct)
        if correct_count != 1:
            raise ValueError(
                "Generated slide question must have exactly one correct option."
            )
        for option in question.options:
            if (
                total_duration_ms is not None
                and option.continue_offset_ms > total_duration_ms
            ):
                raise ValueError(
                    "Generated slide option resume point exceeds duration."
                )
            if option.continue_slide_position is not None:
                continue_page_range = page_range_by_position.get(
                    option.continue_slide_position
                )
                if continue_page_range is None:
                    raise ValueError(
                        "Generated slide option references unknown "
                        f"continue_slide_position {option.continue_slide_position}."
                    )
                if option.continue_slide_offset_ms is not None:
                    continue_start_ms = continue_page_range["start_offset_ms"]
                    continue_end_ms = continue_page_range["end_offset_ms"]
                    if continue_start_ms is not None and continue_end_ms is not None:
                        continue_duration_ms = max(
                            continue_end_ms - continue_start_ms, 0
                        )
                        if option.continue_slide_offset_ms > continue_duration_ms:
                            raise ValueError(
                                "Generated slide option has continue_slide_offset_ms "
                                "outside the slide duration."
                            )
    return manifest


def _normalize_slide_manifest_context(
    manifest: GeneratedSlideManifest,
    *,
    total_duration_ms: int | None,
    generation_start_ms: int | None = None,
    generation_end_ms: int | None = None,
) -> GeneratedSlideManifest:
    summary_checkpoints, moment_contexts = _normalize_v4_context_arrays(
        summary_checkpoints=manifest.summary_checkpoints,
        moment_contexts=manifest.moment_contexts,
        video_duration_ms=total_duration_ms or generation_end_ms,
        generation_start_ms=generation_start_ms,
        generation_end_ms=generation_end_ms,
        video_description_window_ms=DEFAULT_VIDEO_DESCRIPTION_DURATION_MS,
    )
    return manifest.model_copy(
        update={
            "summary_checkpoints": summary_checkpoints,
            "moment_contexts": moment_contexts,
        }
    )


def _is_context_limit_error(exc: Exception) -> bool:
    error_text = str(exc).lower()
    return any(
        marker in error_text
        for marker in (
            "input token count exceeds",
            "context_length_exceeded",
            "maximum context length",
            "too many tokens",
        )
    )


def _is_retryable_openai_generation_error(exc: Exception) -> bool:
    if _is_context_limit_error(exc):
        return False
    error_text = str(exc).lower()
    return any(
        marker in error_text
        for marker in (
            "429",
            "500",
            "502",
            "503",
            "504",
            "rate_limit",
            "timeout",
            "temporarily unavailable",
            "connection error",
        )
    )


async def _generate_slide_manifest(
    run_id: int,
    lease_token: str,
    deck_id: int,
    pdf_path: str,
    transcript: list[schemas.LectureVideoManifestWordV3],
    responses_model: str,
    openai_client: openai.AsyncClient | openai.AsyncAzureOpenAI,
) -> GeneratedSlideManifest | None:
    async with config.db.driver.async_session() as session:
        deck = await models.LectureSlideDeck.get_by_id_with_processing_context(
            session, deck_id
        )
        if deck is None:
            return None
        prompt = deck.generation_prompt or DEFAULT_GENERATION_PROMPT_CONTENT
        total_duration_ms = deck.total_duration_ms
        page_ranges: list[SlidePageRange] = [
            {
                "slide_position": page.position,
                "start_offset_ms": page.start_offset_ms,
                "end_offset_ms": page.end_offset_ms,
            }
            for page in sorted(deck.pages, key=lambda item: item.position)
        ]
    total_duration_ms = _slide_manifest_total_duration_ms(
        deck_total_duration_ms=total_duration_ms,
        page_ranges=page_ranges,
        transcript=transcript,
    )

    file_id = await _await_with_run_lease_heartbeat(
        run_id,
        lease_token,
        _upload_openai_input_pdf(openai_client, pdf_path),
    )
    if file_id is None:
        return None
    try:
        return await _await_with_run_lease_heartbeat(
            run_id,
            lease_token,
            _generate_slide_manifest_with_optional_chunks(
                openai_client=openai_client,
                model=responses_model,
                file_id=file_id,
                generation_prompt=prompt,
                page_ranges=page_ranges,
                transcript=transcript,
                total_duration_ms=total_duration_ms,
            ),
        )
    finally:
        await _delete_openai_file_quietly(openai_client, file_id)


async def _generate_slide_manifest_with_optional_chunks(
    *,
    openai_client: openai.AsyncClient | openai.AsyncAzureOpenAI,
    model: str,
    file_id: str,
    generation_prompt: str,
    page_ranges: list[SlidePageRange],
    transcript: list[schemas.LectureVideoManifestWordV3],
    total_duration_ms: int | None,
) -> GeneratedSlideManifest:
    if total_duration_ms is None:
        return await _generate_slide_manifest_for_window(
            openai_client=openai_client,
            model=model,
            file_id=file_id,
            generation_prompt=generation_prompt,
            page_ranges=page_ranges,
            transcript=transcript,
            total_duration_ms=None,
        )
    chunks = _plan_slide_manifest_generation_chunks(total_duration_ms)
    if len(chunks) == 1:
        try:
            return await _generate_slide_manifest_for_window(
                openai_client=openai_client,
                model=model,
                file_id=file_id,
                generation_prompt=generation_prompt,
                page_ranges=page_ranges,
                transcript=transcript,
                total_duration_ms=total_duration_ms,
            )
        except Exception as exc:
            if (
                not _is_context_limit_error(exc)
                or chunks[0].generation_duration_ms <= SLIDE_MANIFEST_CHUNK_MIN_SPLIT_MS
            ):
                raise
            chunks = _split_slide_manifest_generation_chunk(
                chunks[0], total_duration_ms=total_duration_ms
            )
    if len(chunks) == 1:
        raise RuntimeError("Slide manifest chunk planning did not split.")

    logger.info(
        "Generating lecture slide manifest in chunks. total_duration_ms=%s "
        "chunk_count=%s",
        total_duration_ms,
        len(chunks),
    )
    chunk_manifests: list[GeneratedSlideManifest] = []
    for chunk in chunks:
        chunk_manifests.extend(
            await _generate_slide_manifest_chunks(
                openai_client=openai_client,
                model=model,
                file_id=file_id,
                generation_prompt=generation_prompt,
                page_ranges=page_ranges,
                transcript=transcript,
                total_duration_ms=total_duration_ms,
                chunk=chunk,
            )
        )
    return _merge_slide_chunk_manifests(
        chunk_manifests,
        total_duration_ms=total_duration_ms,
    )


async def _generate_slide_manifest_chunks(
    *,
    openai_client: openai.AsyncClient | openai.AsyncAzureOpenAI,
    model: str,
    file_id: str,
    generation_prompt: str,
    page_ranges: list[SlidePageRange],
    transcript: list[schemas.LectureVideoManifestWordV3],
    total_duration_ms: int,
    chunk: SlideManifestGenerationChunk,
) -> list[GeneratedSlideManifest]:
    try:
        manifest = await _generate_slide_manifest_for_window(
            openai_client=openai_client,
            model=model,
            file_id=file_id,
            generation_prompt=generation_prompt,
            page_ranges=page_ranges,
            transcript=transcript,
            total_duration_ms=total_duration_ms,
            chunk=chunk,
        )
        return [manifest]
    except Exception as exc:
        if (
            not _is_context_limit_error(exc)
            or chunk.generation_duration_ms <= SLIDE_MANIFEST_CHUNK_MIN_SPLIT_MS
        ):
            raise
        child_chunks = _split_slide_manifest_generation_chunk(
            chunk, total_duration_ms=total_duration_ms
        )
        logger.info(
            "Splitting lecture slide manifest chunk after context limit. "
            "generation_start_ms=%s generation_end_ms=%s split_ms=%s",
            chunk.generation_start_ms,
            chunk.generation_end_ms,
            child_chunks[0].generation_end_ms,
        )
        manifests: list[GeneratedSlideManifest] = []
        for child_chunk in child_chunks:
            manifests.extend(
                await _generate_slide_manifest_chunks(
                    openai_client=openai_client,
                    model=model,
                    file_id=file_id,
                    generation_prompt=generation_prompt,
                    page_ranges=page_ranges,
                    transcript=transcript,
                    total_duration_ms=total_duration_ms,
                    chunk=child_chunk,
                )
            )
        return manifests


async def _generate_slide_manifest_for_window(
    *,
    openai_client: openai.AsyncClient | openai.AsyncAzureOpenAI,
    model: str,
    file_id: str,
    generation_prompt: str,
    page_ranges: list[SlidePageRange],
    transcript: list[schemas.LectureVideoManifestWordV3],
    total_duration_ms: int | None,
    chunk: SlideManifestGenerationChunk | None = None,
) -> GeneratedSlideManifest:
    chunk_transcript = transcript
    chunk_page_ranges = page_ranges
    generation_start_ms = None
    generation_end_ms = None
    context_start_ms = None
    context_end_ms = None
    if chunk is not None:
        generation_start_ms = chunk.generation_start_ms
        generation_end_ms = chunk.generation_end_ms
        context_start_ms = chunk.context_start_ms
        context_end_ms = chunk.context_end_ms
        chunk_transcript = _transcript_for_slide_window(
            transcript,
            start_offset_ms=chunk.context_start_ms,
            end_offset_ms=chunk.context_end_ms,
        )
        chunk_page_ranges = _page_ranges_for_slide_window(
            page_ranges,
            start_offset_ms=chunk.context_start_ms,
            end_offset_ms=chunk.context_end_ms,
        )
    manifest = await _parse_responses_output(
        openai_client,
        model=model,
        instructions=_build_slide_manifest_generation_instructions(
            generation_prompt,
            total_duration_ms=total_duration_ms,
            generation_start_ms=generation_start_ms,
            generation_end_ms=generation_end_ms,
            context_start_ms=context_start_ms,
            context_end_ms=context_end_ms,
        ),
        response_model=GeneratedSlideManifest,
        input_messages=[
            {
                "role": "user",
                "content": [
                    {"type": "input_file", "file_id": file_id},
                    {
                        "type": "input_text",
                        "text": _slide_timing_source_text(chunk_page_ranges),
                    },
                    {
                        "type": "input_text",
                        "text": _generation_transcript_source_text(
                            chunk_transcript,
                            compact=False,
                        ),
                    },
                    {
                        "type": "input_text",
                        "text": _slide_generation_final_task_text(),
                    },
                ],
            }
        ],
    )
    if chunk is not None:
        manifest = manifest.model_copy(
            update={
                "questions": _filter_slide_questions_for_window(
                    manifest.questions,
                    start_offset_ms=chunk.generation_start_ms,
                    end_offset_ms=chunk.generation_end_ms,
                    is_final_chunk=chunk.generation_end_ms == total_duration_ms,
                )
            }
        )
    manifest = _normalize_slide_manifest_context(
        manifest,
        total_duration_ms=total_duration_ms,
        generation_start_ms=generation_start_ms,
        generation_end_ms=generation_end_ms,
    )
    return _validate_generated_slide_manifest(
        manifest,
        page_ranges=page_ranges,
        total_duration_ms=total_duration_ms,
    )


def _merge_slide_chunk_manifests(
    chunk_manifests: list[GeneratedSlideManifest],
    *,
    total_duration_ms: int,
) -> GeneratedSlideManifest:
    summary_checkpoints, moment_contexts = _normalize_v4_context_arrays(
        summary_checkpoints=[
            checkpoint
            for manifest in chunk_manifests
            for checkpoint in manifest.summary_checkpoints
        ],
        moment_contexts=[
            moment
            for manifest in chunk_manifests
            for moment in manifest.moment_contexts
        ],
        video_duration_ms=total_duration_ms,
        video_description_window_ms=DEFAULT_VIDEO_DESCRIPTION_DURATION_MS,
    )
    return GeneratedSlideManifest(
        questions=[
            question for manifest in chunk_manifests for question in manifest.questions
        ],
        summary_checkpoints=summary_checkpoints,
        moment_contexts=moment_contexts,
    )


async def _persist_slide_manifest(
    run_id: int,
    lease_token: str,
    deck_id: int,
    manifest: GeneratedSlideManifest,
    transcript: list[schemas.LectureVideoManifestWordV3],
) -> None:
    async with config.db.driver.async_session() as session:
        run = await models.LectureSlideProcessingRun.get_by_id(session, run_id)
        deck = await models.LectureSlideDeck.get_by_id_with_processing_context(
            session, deck_id
        )
        if (
            run is None
            or deck is None
            or run.status != schemas.LectureSlideProcessingRunStatus.RUNNING
            or run.lease_token != lease_token
        ):
            return

        await session.execute(
            delete(
                models.lecture_slide_question_single_select_correct_option_association
            ).where(
                models.lecture_slide_question_single_select_correct_option_association.c.question_id.in_(
                    select(models.LectureSlideQuestion.id).where(
                        models.LectureSlideQuestion.lecture_slide_deck_id == deck.id
                    )
                )
            )
        )
        await session.execute(
            delete(models.LectureSlideQuestionOption).where(
                models.LectureSlideQuestionOption.question_id.in_(
                    select(models.LectureSlideQuestion.id).where(
                        models.LectureSlideQuestion.lecture_slide_deck_id == deck.id
                    )
                )
            )
        )
        await session.execute(
            delete(models.LectureSlideQuestion).where(
                models.LectureSlideQuestion.lecture_slide_deck_id == deck.id
            )
        )
        await session.flush()

        for question_position, question in enumerate(manifest.questions):
            question_row = models.LectureSlideQuestion(
                lecture_slide_deck_id=deck.id,
                position=question_position,
                slide_position=question.slide_position,
                slide_offset_ms=question.slide_offset_ms,
                stop_offset_ms=question.stop_offset_ms,
                question_type=schemas.LectureSlideQuestionType.SINGLE_SELECT,
                question_text=question.question_text,
                intro_text=question.intro_text,
            )
            session.add(question_row)
            await session.flush()
            if text_needs_audio(question.intro_text):
                intro_narration = models.LectureSlideNarration(
                    status=schemas.LectureSlideNarrationStatus.PENDING,
                )
                session.add(intro_narration)
                await session.flush()
                question_row.intro_narration_id = intro_narration.id

            option_rows: list[
                tuple[GeneratedSlideChoice, models.LectureSlideQuestionOption]
            ] = []
            for option_position, option in enumerate(question.options):
                option_row = models.LectureSlideQuestionOption(
                    question_id=question_row.id,
                    position=option_position,
                    option_text=option.option_text,
                    post_answer_text=option.post_answer_text,
                    continue_slide_position=option.continue_slide_position,
                    continue_slide_offset_ms=option.continue_slide_offset_ms,
                    continue_offset_ms=option.continue_offset_ms,
                )
                session.add(option_row)
                option_rows.append((option, option_row))
            await session.flush()
            for option, option_row in option_rows:
                if option.correct:
                    await session.execute(
                        models.lecture_slide_question_single_select_correct_option_association.insert().values(
                            question_id=question_row.id,
                            option_id=option_row.id,
                        )
                    )
                if text_needs_audio(option.post_answer_text):
                    post_narration = models.LectureSlideNarration(
                        status=schemas.LectureSlideNarrationStatus.PENDING,
                    )
                    session.add(post_narration)
                    await session.flush()
                    option_row.post_narration_id = post_narration.id

        v4_context = schemas.LectureVideoManifestV4(
            version=4,
            questions=[
                schemas.LectureVideoManifestQuestionV1(
                    type=schemas.LectureVideoQuestionType.SINGLE_SELECT,
                    question_text=question.question_text,
                    intro_text=question.intro_text,
                    stop_offset_ms=question.stop_offset_ms,
                    options=[
                        schemas.LectureVideoManifestOptionV1(
                            option_text=option.option_text,
                            post_answer_text=option.post_answer_text,
                            continue_offset_ms=option.continue_offset_ms,
                            correct=option.correct,
                        )
                        for option in question.options
                    ],
                )
                for question in manifest.questions
            ],
            word_level_transcription=transcript,
            summary_checkpoints=manifest.summary_checkpoints,
            moment_contexts=manifest.moment_contexts,
        )
        deck.context_data = _stored_context_extras(v4_context)
        deck.context_version = 4
        deck.lecture_slide_chat_available = bool(transcript)
        deck.transcript_data = transcript_data_from_words(transcript)
        session.add(deck)
        await session.commit()


async def _synthesize_knowledge_check_audio(
    run_id: int,
    lease_token: str,
    deck_id: int,
) -> None:
    async with config.db.driver.async_session() as session:
        deck = await models.LectureSlideDeck.get_by_id_with_processing_context(
            session, deck_id
        )
        if deck is None:
            return
        voice_id = deck.voice_id
        class_id = deck.class_id
        narration_items: list[tuple[int, str]] = []
        for question in deck.questions:
            if question.intro_narration and text_needs_audio(question.intro_text):
                narration_items.append(
                    (question.intro_narration.id, question.intro_text)
                )
            for option in question.options:
                if option.post_narration and text_needs_audio(option.post_answer_text):
                    narration_items.append(
                        (option.post_narration.id, option.post_answer_text)
                    )
    if not narration_items:
        return
    if not voice_id:
        raise RuntimeError("Lecture slide deck voice_id is required for narration.")
    api_key = await _get_elevenlabs_api_key(class_id)
    for narration_id, text in narration_items:
        synthesis_result = await _await_with_run_lease_heartbeat(
            run_id,
            lease_token,
            synthesize_elevenlabs_speech(api_key, voice_id, text),
        )
        if synthesis_result is None:
            return
        _, audio = synthesis_result
        content_type = LECTURE_SLIDE_AUDIO_CONTENT_TYPE
        store_key, content_length = await _store_audio(
            generate_slide_narration_store_key(),
            content_type,
            audio,
        )
        duration_ms = audio_duration_ms(audio, content_type)
        async with config.db.driver.async_session() as session:
            run = await models.LectureSlideProcessingRun.get_by_id(session, run_id)
            narration = await models.LectureSlideNarration.get_by_id(
                session, narration_id
            )
            if (
                run is None
                or narration is None
                or run.status != schemas.LectureSlideProcessingRunStatus.RUNNING
                or run.lease_token != lease_token
            ):
                await _delete_audio_key_quietly(store_key)
                return
            stored_object = models.LectureSlideNarrationStoredObject(
                key=store_key,
                content_type=content_type,
                content_length=content_length,
                duration_ms=duration_ms,
            )
            session.add(stored_object)
            await session.flush()
            narration.stored_object_id = stored_object.id
            narration.status = schemas.LectureSlideNarrationStatus.READY
            narration.error_message = None
            session.add(narration)
            await session.commit()


async def _persist_composite_artifacts(
    run_id: int,
    lease_token: str,
    deck_id: int,
    transcript: list[schemas.LectureVideoManifestWordV3],
) -> None:
    async with config.db.driver.async_session() as session:
        deck = await models.LectureSlideDeck.get_by_id_with_processing_context(
            session, deck_id
        )
        if deck is None:
            return
        stored_objects = [
            page.narration_stored_object
            for page in sorted(deck.pages, key=lambda item: item.position)
            if page.narration_stored_object is not None
        ]
    combined_audio = await _combine_audio_objects(stored_objects)
    content_type = LECTURE_SLIDE_AUDIO_CONTENT_TYPE
    audio_key, audio_length = await _store_audio(
        generate_slide_continuous_narration_store_key(),
        content_type,
        combined_audio,
    )
    caption_text = lecture_video_words_to_webvtt(transcript)
    caption_bytes = caption_text.encode("utf-8")
    caption_key = generate_slide_caption_store_key()
    if not config.video_store:
        raise RuntimeError("Video store not configured or unavailable.")
    await config.video_store.store.put(
        caption_key, io.BytesIO(caption_bytes), "text/vtt"
    )

    async with config.db.driver.async_session() as session:
        run = await models.LectureSlideProcessingRun.get_by_id(session, run_id)
        deck = await models.LectureSlideDeck.get_by_id_with_processing_context(
            session, deck_id
        )
        if (
            run is None
            or deck is None
            or run.status != schemas.LectureSlideProcessingRunStatus.RUNNING
            or run.lease_token != lease_token
        ):
            await _delete_audio_key_quietly(audio_key)
            if config.video_store:
                with contextlib.suppress(Exception):
                    await config.video_store.store.delete(caption_key)
            return
        duration_ms = audio_duration_ms(combined_audio, content_type)
        audio_stored_object = models.LectureSlideNarrationStoredObject(
            key=audio_key,
            content_type=content_type,
            content_length=audio_length,
            duration_ms=duration_ms,
        )
        caption_stored_object = models.LectureSlideCaptionStoredObject(
            key=caption_key,
            content_type="text/vtt",
            content_length=len(caption_bytes),
        )
        session.add_all([audio_stored_object, caption_stored_object])
        await session.flush()
        deck.continuous_narration_stored_object_id = audio_stored_object.id
        deck.caption_stored_object_id = caption_stored_object.id
        session.add(deck)
        await session.commit()


async def _combine_audio_objects(
    stored_objects: Sequence[models.LectureSlideNarrationStoredObject],
) -> bytes:
    if not stored_objects:
        return b""
    chunks: list[bytes] = []
    if not config.lecture_video_audio_store:
        raise RuntimeError("Lecture video audio store is not configured.")
    for stored_object in stored_objects:
        data = bytearray()
        async for chunk in config.lecture_video_audio_store.store.get_file(
            stored_object.key
        ):
            data.extend(chunk)
        chunks.append(bytes(data))
    try:
        combined = AudioSegment.empty()
        for audio_data in chunks:
            combined += AudioSegment.from_file(io.BytesIO(audio_data))
        output = io.BytesIO()
        combined.export(output, format="ogg")
        return output.getvalue()
    except Exception:
        logger.warning(
            "Falling back to byte concatenation for slide audio.", exc_info=True
        )
        return b"".join(chunks)


async def _parse_responses_output(
    openai_client: openai.AsyncClient | openai.AsyncAzureOpenAI,
    *,
    model: str,
    instructions: str,
    response_model: type[_ResponseModelT],
    input_messages: ResponseInputParam,
) -> _ResponseModelT:
    for attempt in range(1, OPENAI_GENERATION_MAX_ATTEMPTS + 1):
        try:
            response = await openai_client.responses.parse(
                model=model,
                instructions=instructions,
                input=input_messages,
                text_format=response_model,
            )
            if response.output_parsed is None:
                raise RuntimeError("OpenAI Responses parse returned no parsed output.")
            return cast(_ResponseModelT, response.output_parsed)
        except Exception as exc:
            if (
                attempt >= OPENAI_GENERATION_MAX_ATTEMPTS
                or not _is_retryable_openai_generation_error(exc)
            ):
                raise
            delay_seconds = OPENAI_GENERATION_RETRY_DELAY_SECONDS * attempt
            logger.warning(
                "Retrying OpenAI Responses generation after transient failure. "
                "attempt=%s max_attempts=%s delay_seconds=%.1f error=%s",
                attempt,
                OPENAI_GENERATION_MAX_ATTEMPTS,
                delay_seconds,
                exc,
            )
            await asyncio.sleep(delay_seconds)
    raise RuntimeError("OpenAI Responses retry loop exited unexpectedly.")


def transcript_data_from_words(
    words: list[schemas.LectureVideoManifestWordV3],
) -> dict[str, Any]:
    return {
        "version": TRANSCRIPT_DATA_VERSION,
        "word_level_transcription": [word.model_dump() for word in words],
    }


def _stored_context_extras(manifest: schemas.LectureVideoManifestV4) -> dict[str, Any]:
    return {
        "version": manifest.version,
        "summary_checkpoints": [
            checkpoint.model_dump() for checkpoint in manifest.summary_checkpoints
        ],
        "moment_contexts": [moment.model_dump() for moment in manifest.moment_contexts],
    }


def text_needs_audio(text: str) -> bool:
    return bool(text.strip())


def audio_duration_ms(audio: bytes, content_type: str | None = None) -> int:
    try:
        segment = AudioSegment.from_file(io.BytesIO(audio))
        return int(len(segment))
    except Exception:
        logger.warning(
            "Unable to determine lecture slide audio duration from content_type=%s; using 0.",
            content_type,
            exc_info=True,
        )
        return 0


def _seconds_to_ms(value: _TranscriptionWordValue) -> int:
    return max(0, int(round(float(value) * 1000)))


def _get_attr_or_key(
    value: TranscriptionWord | Mapping[str, object],
    key: _TranscriptionWordField,
) -> _TranscriptionWordValue | None:
    raw_value = value.get(key) if isinstance(value, Mapping) else getattr(value, key)
    if isinstance(raw_value, str | int | float):
        return raw_value
    return None


def generate_slide_image_store_key() -> str:
    return f"ls_page_{uuid.uuid7()}.png"


def generate_slide_narration_store_key() -> str:
    return f"ls_narration_{uuid.uuid7()}.ogg"


def generate_slide_continuous_narration_store_key() -> str:
    return f"ls_continuous_narration_{uuid.uuid7()}.ogg"


def generate_slide_caption_store_key() -> str:
    return f"ls_caption_{uuid.uuid7()}.vtt"


async def _delete_audio_key_quietly(key: str) -> None:
    if not config.lecture_video_audio_store:
        return
    try:
        await config.lecture_video_audio_store.store.delete_file(key)
    except Exception:
        logger.exception("Failed to clean up lecture slide audio key=%s", key)


def _user_safe_processing_error_message(exc: Exception) -> str:
    if isinstance(
        exc,
        (
            ClassCredentialValidationSSLError,
            ClassCredentialValidationUnavailableError,
            ClassCredentialVoiceValidationError,
        ),
    ):
        return "Unable to synthesize lecture slide narration audio right now. Please retry."
    return "Unable to process the lecture slide deck right now. Please retry."
