import asyncio
import io
import logging
import multiprocessing
import os
import secrets
import socket
import time
from collections.abc import Callable, Coroutine
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

import uuid_utils as uuid
from sqlalchemy import and_, delete, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

import pingpong.models as models
import pingpong.schemas as schemas
from pingpong.audio_store import AudioStoreError
from pingpong.class_credential_validation import (
    ClassCredentialValidationSSLError,
    ClassCredentialValidationUnavailableError,
    ClassCredentialVoiceValidationError,
)
from pingpong.config import config
from pingpong.errors import capture_exception_to_sentry, sentry
from pingpong.elevenlabs import (
    synthesize_elevenlabs_speech,
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

NARRATION_STAGE = schemas.LectureVideoProcessingStage.NARRATION
RUN_LEASE_DURATION = timedelta(minutes=10)
RUN_LEASE_HEARTBEAT_INTERVAL = min(timedelta(minutes=1), RUN_LEASE_DURATION / 2)
_ACTIVE_RUN_STATUSES = (
    schemas.LectureVideoProcessingRunStatus.QUEUED,
    schemas.LectureVideoProcessingRunStatus.RUNNING,
)
UNEXPECTED_WORKER_EXIT_ERROR_MESSAGE = "Lecture video worker exited unexpectedly."
MAX_RUN_CREATE_RETRIES = 3


@dataclass(frozen=True)
class NarrationWorkItem:
    class_id: int
    lecture_video_id: int
    voice_id: str
    narration_id: int
    text: str


class NarrationWorkerPoolManager(WorkerPoolManager):
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
            claim_run_fn=claim_run_fn or self._claim_next_narration_run_sync,
            recover_run_fn=recover_run_fn or self._recover_failed_narration_run_sync,
            build_runner_id_fn=build_runner_id,
            worker_label="lecture video worker",
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

    def _claim_next_narration_run_sync(self, runner_id: str) -> tuple[int, str] | None:
        return self._ensure_async_runner().run(
            _claim_next_narration_run(leased_by=runner_id)
        )

    def _recover_failed_narration_run_sync(
        self,
        run_id: int,
        lease_token: str,
        error_message: str,
    ) -> bool:
        return self._ensure_async_runner().run(
            recover_failed_narration_run(
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
        return f"lecture-video:{socket.gethostname()}:{effective_pid}"
    return f"lecture-video:{socket.gethostname()}:{effective_pid}:worker-{worker_slot}"


def get_forkserver_context() -> multiprocessing.context.BaseContext:
    if "forkserver" not in multiprocessing.get_all_start_methods():
        raise RuntimeError(
            "The lecture video worker pool requires the 'forkserver' start method."
        )
    return multiprocessing.get_context("forkserver")


def _worker_process_main(
    worker_slot: int,
    assignment_queue,
    result_queue,
) -> None:
    with sentry():
        ignore_sigint_in_worker()
        result_queue.put(WorkerReady(worker_slot=worker_slot, pid=os.getpid()))
        with asyncio.Runner() as runner:
            while True:
                assignment = assignment_queue.get()
                if assignment is None:
                    logger.info(
                        "Lecture video worker shutting down. slot=%s pid=%s",
                        worker_slot,
                        os.getpid(),
                    )
                    return

                if not isinstance(assignment, RunAssignment):
                    raise TypeError(
                        f"Expected RunAssignment, got {type(assignment).__name__}"
                    )
                logger.info(
                    "Lecture video worker picked up run. slot=%s pid=%s run_id=%s",
                    worker_slot,
                    os.getpid(),
                    assignment.run_id,
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
                        _process_claimed_narration_run(
                            assignment.run_id,
                            assignment.lease_token,
                        )
                    )
                except Exception as exc:
                    logger.exception(
                        "Lecture video worker process failed while handling run_id=%s. slot=%s pid=%s",
                        assignment.run_id,
                        worker_slot,
                        os.getpid(),
                    )
                    capture_exception_to_sentry(
                        exc,
                        source="lecture-video-worker-child",
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
                    logger.info(
                        "Lecture video worker completed run. slot=%s pid=%s run_id=%s",
                        worker_slot,
                        os.getpid(),
                        assignment.run_id,
                    )
                    result_queue.put(
                        WorkerCompleted(
                            worker_slot=worker_slot,
                            run_id=assignment.run_id,
                            lease_token=assignment.lease_token,
                        )
                    )


def run_narration_processing_worker_pool(
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
    manager = NarrationWorkerPoolManager(
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


def generate_narration_store_key() -> str:
    return f"lv_narration_{uuid.uuid7()}.ogg"


async def queue_narration_processing_run(
    session: AsyncSession,
    lecture_video: models.LectureVideo,
    *,
    assistant_id_at_start: int,
) -> models.LectureVideoProcessingRun | None:
    if lecture_video.status != schemas.LectureVideoStatus.PROCESSING:
        return None

    attached_assistant = await models.Assistant.get_by_lecture_video_id(
        session, lecture_video.id
    )
    if attached_assistant is None:
        return None
    if attached_assistant.id != assistant_id_at_start:
        return None

    existing_run = (
        await models.LectureVideoProcessingRun.get_non_terminal_by_snapshot_stage(
            session,
            lecture_video.id,
            NARRATION_STAGE,
        )
    )
    if existing_run is not None:
        return existing_run

    lecture_video_id = lecture_video.id
    class_id = lecture_video.class_id
    attempt_number = (
        await models.LectureVideoProcessingRun.get_latest_attempt_number(
            session,
            lecture_video_id,
            NARRATION_STAGE,
        )
        + 1
    )
    last_error: IntegrityError | None = None
    for _ in range(MAX_RUN_CREATE_RETRIES):
        async with session.begin_nested() as savepoint:
            try:
                return await models.LectureVideoProcessingRun.create(
                    session,
                    lecture_video_id=lecture_video_id,
                    lecture_video_id_snapshot=lecture_video_id,
                    class_id=class_id,
                    assistant_id_at_start=assistant_id_at_start,
                    stage=NARRATION_STAGE,
                    attempt_number=attempt_number,
                    status=schemas.LectureVideoProcessingRunStatus.QUEUED,
                )
            except IntegrityError as exc:
                last_error = exc
                await savepoint.rollback()

        existing_run = (
            await models.LectureVideoProcessingRun.get_non_terminal_by_snapshot_stage(
                session,
                lecture_video_id,
                NARRATION_STAGE,
            )
        )
        if existing_run is not None:
            return existing_run

        attempt_number = (
            await models.LectureVideoProcessingRun.get_latest_attempt_number(
                session,
                lecture_video_id,
                NARRATION_STAGE,
            )
            + 1
        )

    assert last_error is not None
    raise last_error


async def cancel_narration_processing_runs(
    session: AsyncSession,
    lecture_video_id_snapshot: int,
    cancel_reason: schemas.LectureVideoProcessingCancelReason,
) -> bool:
    now = utcnow()
    result = await session.execute(
        update(models.LectureVideoProcessingRun)
        .where(
            models.LectureVideoProcessingRun.lecture_video_id_snapshot
            == lecture_video_id_snapshot,
            models.LectureVideoProcessingRun.stage == NARRATION_STAGE,
            models.LectureVideoProcessingRun.status.in_(_ACTIVE_RUN_STATUSES),
        )
        .values(
            status=schemas.LectureVideoProcessingRunStatus.CANCELLED,
            cancel_reason=cancel_reason,
            finished_at=now,
            lease_token=None,
            leased_by=None,
            lease_expires_at=None,
        )
    )
    await session.flush()
    return bool(result.rowcount)


async def reset_failed_narrations_for_retry(
    session: AsyncSession,
    lecture_video_id: int,
) -> list[str]:
    lecture_video = await models.LectureVideo.get_by_id_with_copy_context(
        session, lecture_video_id
    )
    if lecture_video is None:
        raise ValueError(f"Lecture video {lecture_video_id} not found.")

    audio_keys_to_delete: list[str] = []
    stored_object_ids_to_delete: list[int] = []
    narrations_to_reset: list[models.LectureVideoNarration] = []

    for question in sorted(lecture_video.questions, key=lambda item: item.position):
        if (
            question.intro_narration is not None
            and question.intro_narration.status
            != schemas.LectureVideoNarrationStatus.READY
        ):
            narrations_to_reset.append(question.intro_narration)
        for option in sorted(question.options, key=lambda item: item.position):
            if (
                option.post_narration is not None
                and option.post_narration.status
                != schemas.LectureVideoNarrationStatus.READY
            ):
                narrations_to_reset.append(option.post_narration)

    for narration in narrations_to_reset:
        if narration.stored_object is not None:
            stored_object_ids_to_delete.append(narration.stored_object.id)
            audio_keys_to_delete.append(narration.stored_object.key)
        narration.stored_object_id = None
        narration.stored_object = None
        narration.status = schemas.LectureVideoNarrationStatus.PENDING
        narration.error_message = None
        session.add(narration)

    await session.flush()

    if stored_object_ids_to_delete:
        await session.execute(
            delete(models.LectureVideoNarrationStoredObject).where(
                models.LectureVideoNarrationStoredObject.id.in_(
                    stored_object_ids_to_delete
                )
            )
        )

    return audio_keys_to_delete


async def claim_failed_lecture_video_for_retry(
    session: AsyncSession,
    lecture_video_id: int,
) -> bool:
    result = await session.execute(
        update(models.LectureVideo)
        .where(models.LectureVideo.id == lecture_video_id)
        .where(models.LectureVideo.status == schemas.LectureVideoStatus.FAILED)
        .values(
            status=schemas.LectureVideoStatus.PROCESSING,
            error_message=None,
        )
    )
    await session.flush()
    return bool(result.rowcount)


async def _await_with_run_lease_heartbeat(
    run_id: int,
    lease_token: str,
    operation: Coroutine[Any, Any, Any],
) -> Any | None:
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
                try:
                    await task
                except asyncio.CancelledError:
                    # Task was just cancelled via task.cancel(); ignore the expected
                    # CancelledError from awaiting it so the outer logic can proceed.
                    pass
                return None
    except Exception:
        if not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                # Task was cancelled as part of cleanup; suppress the expected CancelledError.
                pass
        raise


async def _process_claimed_narration_run(run_id: int, lease_token: str) -> None:
    while True:
        state, payload = await _prepare_next_work_item(run_id, lease_token)
        if state in {"cancelled", "missing"}:
            return
        if state == "completed":
            await _mark_run_completed(run_id, lease_token)
            return
        if state == "failed":
            assert isinstance(payload, tuple)
            narration_id, error_message = payload
            await _mark_run_failed(run_id, lease_token, narration_id, error_message)
            return

        work_item = payload
        if not isinstance(work_item, NarrationWorkItem):
            raise TypeError(
                f"Expected NarrationWorkItem, got {type(work_item).__name__}"
            )

        try:
            synthesis_result = await _await_with_run_lease_heartbeat(
                run_id,
                lease_token,
                synthesize_elevenlabs_speech(
                    await _get_elevenlabs_api_key(work_item.class_id),
                    work_item.voice_id,
                    work_item.text,
                ),
            )
        except Exception as exc:
            await _mark_run_failed(
                run_id,
                lease_token,
                work_item.narration_id,
                _user_safe_processing_error_message(exc),
            )
            return

        if synthesis_result is None:
            return
        content_type, audio = synthesis_result

        if not await _ensure_run_can_continue(run_id, lease_token):
            return

        try:
            store_result = await _await_with_run_lease_heartbeat(
                run_id,
                lease_token,
                _store_narration_audio(
                    content_type,
                    audio,
                ),
            )
        except Exception as exc:
            await _mark_run_failed(
                run_id,
                lease_token,
                work_item.narration_id,
                _user_safe_processing_error_message(exc),
            )
            return

        if store_result is None:
            return
        store_key, content_length = store_result

        try:
            attached = await _attach_stored_audio_to_narration(
                run_id,
                lease_token,
                work_item.narration_id,
                content_type,
                content_length,
                store_key,
            )
        except Exception:
            await _delete_audio_key_quietly(store_key)
            raise

        if not attached:
            await _delete_audio_key_quietly(store_key)
            return


async def _get_elevenlabs_api_key(class_id: int) -> str:
    async with config.db.driver.async_session() as session:
        credential = await models.ClassCredential.get_by_class_id_and_purpose(
            session,
            class_id,
            schemas.ClassCredentialPurpose.LECTURE_VIDEO_NARRATION_TTS,
        )
        if credential is None or credential.api_key_obj is None:
            raise RuntimeError(
                "An ElevenLabs credential is required before lecture video narration can be generated."
            )
        return credential.api_key_obj.api_key


def _claimable_narration_run_condition(now) -> Any:
    return or_(
        models.LectureVideoProcessingRun.status
        == schemas.LectureVideoProcessingRunStatus.QUEUED,
        and_(
            models.LectureVideoProcessingRun.status
            == schemas.LectureVideoProcessingRunStatus.RUNNING,
            or_(
                models.LectureVideoProcessingRun.lease_expires_at.is_(None),
                models.LectureVideoProcessingRun.lease_expires_at < now,
            ),
        ),
    )


async def _claim_next_narration_run(
    *,
    leased_by: str | None = None,
) -> tuple[int, str] | None:
    async with config.db.driver.async_session() as session:
        now = utcnow()
        claimable_run_condition = _claimable_narration_run_condition(now)
        effective_leased_by = leased_by or build_runner_id()
        candidate_ids = list(
            (
                await session.scalars(
                    select(models.LectureVideoProcessingRun.id)
                    .where(models.LectureVideoProcessingRun.stage == NARRATION_STAGE)
                    .where(claimable_run_condition)
                    .order_by(
                        models.LectureVideoProcessingRun.created.asc(),
                        models.LectureVideoProcessingRun.id.asc(),
                    )
                    .limit(25)
                )
            ).all()
        )
        for candidate_id in candidate_ids:
            lease_token = secrets.token_urlsafe(24)
            result = await session.execute(
                update(models.LectureVideoProcessingRun)
                .where(models.LectureVideoProcessingRun.id == candidate_id)
                .where(models.LectureVideoProcessingRun.stage == NARRATION_STAGE)
                .where(claimable_run_condition)
                .values(
                    status=schemas.LectureVideoProcessingRunStatus.RUNNING,
                    lease_token=lease_token,
                    leased_by=effective_leased_by,
                    lease_expires_at=now + RUN_LEASE_DURATION,
                    started_at=func.coalesce(
                        models.LectureVideoProcessingRun.started_at, now
                    ),
                    cancel_reason=None,
                    finished_at=None,
                )
            )
            if result.rowcount:
                await session.commit()
                return candidate_id, lease_token
    return None


async def recover_failed_narration_run(
    run_id: int,
    lease_token: str,
    *,
    error_message: str = UNEXPECTED_WORKER_EXIT_ERROR_MESSAGE,
) -> bool:
    async with config.db.driver.async_session() as session:
        run = await models.LectureVideoProcessingRun.get_by_id(session, run_id)
        if run is None:
            return False
        if (
            run.status != schemas.LectureVideoProcessingRunStatus.RUNNING
            or run.lease_token != lease_token
        ):
            return False

        lecture_video = None
        if run.lecture_video_id is not None:
            lecture_video = await models.LectureVideo.get_by_id_with_copy_context(
                session, run.lecture_video_id
            )
            if lecture_video is not None:
                if _first_pending_narration_work(lecture_video) is None:
                    lecture_video.status = schemas.LectureVideoStatus.READY
                    lecture_video.error_message = None
                    run.status = schemas.LectureVideoProcessingRunStatus.COMPLETED
                    run.error_message = None
                else:
                    lecture_video.status = schemas.LectureVideoStatus.FAILED
                    lecture_video.error_message = error_message
                    run.status = schemas.LectureVideoProcessingRunStatus.FAILED
                    run.error_message = error_message
                    _mark_processing_narrations_failed_for_video(
                        lecture_video,
                        error_message=error_message,
                    )
                session.add(lecture_video)
            else:
                run.status = schemas.LectureVideoProcessingRunStatus.FAILED
                run.error_message = error_message
        else:
            run.status = schemas.LectureVideoProcessingRunStatus.FAILED
            run.error_message = error_message

        run.finished_at = utcnow()
        run.cancel_reason = None
        run.lease_token = None
        run.leased_by = None
        run.lease_expires_at = None
        session.add(run)
        await session.commit()
        return True


async def _prepare_next_work_item(
    run_id: int,
    lease_token: str,
) -> tuple[
    str,
    NarrationWorkItem | tuple[int | None, str] | None,
]:
    async with config.db.driver.async_session() as session:
        run = await models.LectureVideoProcessingRun.get_by_id(session, run_id)
        if run is None:
            return "missing", None

        if (
            run.status != schemas.LectureVideoProcessingRunStatus.RUNNING
            or run.lease_token != lease_token
        ):
            return "cancelled", None

        if run.lecture_video_id is None:
            await _mark_run_cancelled(
                session,
                run,
                run.cancel_reason
                or schemas.LectureVideoProcessingCancelReason.LECTURE_VIDEO_DELETED,
            )
            await session.commit()
            return "cancelled", None

        lecture_video = await models.LectureVideo.get_by_id_with_copy_context(
            session, run.lecture_video_id
        )
        if lecture_video is None:
            await _mark_run_cancelled(
                session,
                run,
                run.cancel_reason
                or schemas.LectureVideoProcessingCancelReason.LECTURE_VIDEO_DELETED,
            )
            await session.commit()
            return "cancelled", None

        if not await _lecture_video_has_attached_assistant(session, lecture_video.id):
            await _mark_run_cancelled(
                session,
                run,
                run.cancel_reason
                or schemas.LectureVideoProcessingCancelReason.ASSISTANT_DETACHED,
            )
            await session.commit()
            return "cancelled", None

        voice_id = (lecture_video.voice_id or "").strip()
        if not voice_id:
            return "failed", (None, "Lecture video voice configuration is missing.")

        work_item = _first_pending_narration_work(lecture_video)
        if work_item is None:
            return "completed", None

        narration = await models.LectureVideoNarration.get_by_id(
            session, work_item.narration_id
        )
        if narration is None:
            await _mark_run_cancelled(
                session,
                run,
                schemas.LectureVideoProcessingCancelReason.LECTURE_VIDEO_DELETED,
            )
            await session.commit()
            return "cancelled", None

        narration.status = schemas.LectureVideoNarrationStatus.PROCESSING
        narration.error_message = None
        run.lease_expires_at = utcnow() + RUN_LEASE_DURATION
        session.add(narration)
        session.add(run)
        await session.commit()
        return "work", work_item


def _first_pending_narration_work(
    lecture_video: models.LectureVideo,
) -> NarrationWorkItem | None:
    voice_id = (lecture_video.voice_id or "").strip()
    for question in sorted(lecture_video.questions, key=lambda item: item.position):
        # Any non-READY narration still needs audio. This intentionally includes
        # PROCESSING so a reclaimed run can resume work after a stale lease.
        if (
            question.intro_narration is not None
            and question.intro_narration.status
            != schemas.LectureVideoNarrationStatus.READY
            and question.intro_text.strip()
        ):
            return NarrationWorkItem(
                class_id=lecture_video.class_id,
                lecture_video_id=lecture_video.id,
                voice_id=voice_id,
                narration_id=question.intro_narration.id,
                text=question.intro_text,
            )

        for option in sorted(question.options, key=lambda item: item.position):
            # Treat all non-READY states as unfinished work for the same lease
            # recovery reason as intro narrations.
            if (
                option.post_narration is not None
                and option.post_narration.status
                != schemas.LectureVideoNarrationStatus.READY
                and option.post_answer_text.strip()
            ):
                return NarrationWorkItem(
                    class_id=lecture_video.class_id,
                    lecture_video_id=lecture_video.id,
                    voice_id=voice_id,
                    narration_id=option.post_narration.id,
                    text=option.post_answer_text,
                )
    return None


async def _ensure_run_can_continue(run_id: int, lease_token: str) -> bool:
    async with config.db.driver.async_session() as session:
        run = await models.LectureVideoProcessingRun.get_by_id(session, run_id)
        if run is None:
            return False
        if (
            run.status != schemas.LectureVideoProcessingRunStatus.RUNNING
            or run.lease_token != lease_token
        ):
            return False

        if run.lecture_video_id is None:
            await _mark_run_cancelled(
                session,
                run,
                run.cancel_reason
                or schemas.LectureVideoProcessingCancelReason.LECTURE_VIDEO_DELETED,
            )
            await session.commit()
            return False

        lecture_video_exists = (
            await session.scalar(
                select(models.LectureVideo.id).where(
                    models.LectureVideo.id == run.lecture_video_id
                )
            )
            is not None
        )
        if not lecture_video_exists:
            await _mark_run_cancelled(
                session,
                run,
                run.cancel_reason
                or schemas.LectureVideoProcessingCancelReason.LECTURE_VIDEO_DELETED,
            )
            await session.commit()
            return False

        if not await _lecture_video_has_attached_assistant(
            session, run.lecture_video_id
        ):
            await _mark_run_cancelled(
                session,
                run,
                run.cancel_reason
                or schemas.LectureVideoProcessingCancelReason.ASSISTANT_DETACHED,
            )
            await session.commit()
            return False

        run.lease_expires_at = utcnow() + RUN_LEASE_DURATION
        session.add(run)
        await session.commit()
        return True


async def _store_narration_audio(
    content_type: str,
    audio: bytes,
) -> tuple[str, int]:
    if not config.lecture_video_audio_store:
        raise RuntimeError("Lecture video audio store is not configured.")

    store_key = generate_narration_store_key()
    upload = await config.lecture_video_audio_store.store.create_upload(
        name=store_key,
        content_type=content_type,
    )
    try:
        await upload.upload_part(io.BytesIO(audio))
        await upload.complete_upload()
    except Exception:
        try:
            await upload.delete_file()
        except Exception:
            logger.exception(
                "Failed to clean up lecture video narration upload after error. key=%s",
                store_key,
            )
        raise
    return store_key, len(audio)


async def _attach_stored_audio_to_narration(
    run_id: int,
    lease_token: str,
    narration_id: int,
    content_type: str,
    content_length: int,
    store_key: str,
) -> bool:
    async with config.db.driver.async_session() as session:
        run = await models.LectureVideoProcessingRun.get_by_id(session, run_id)
        if run is None:
            return False
        if (
            run.status != schemas.LectureVideoProcessingRunStatus.RUNNING
            or run.lease_token != lease_token
        ):
            return False
        if run.lecture_video_id is None:
            await _mark_run_cancelled(
                session,
                run,
                run.cancel_reason
                or schemas.LectureVideoProcessingCancelReason.LECTURE_VIDEO_DELETED,
            )
            await session.commit()
            return False
        if not await _lecture_video_has_attached_assistant(
            session, run.lecture_video_id
        ):
            await _mark_run_cancelled(
                session,
                run,
                run.cancel_reason
                or schemas.LectureVideoProcessingCancelReason.ASSISTANT_DETACHED,
            )
            await session.commit()
            return False

        narration = await models.LectureVideoNarration.get_by_id(session, narration_id)
        if narration is None:
            return False

        stored_object = models.LectureVideoNarrationStoredObject(
            key=store_key,
            content_type=content_type,
            content_length=content_length,
        )
        session.add(stored_object)
        await session.flush()

        narration.stored_object_id = stored_object.id
        narration.stored_object = stored_object
        narration.status = schemas.LectureVideoNarrationStatus.READY
        narration.error_message = None
        run.lease_expires_at = utcnow() + RUN_LEASE_DURATION
        session.add(narration)
        session.add(run)
        await session.commit()
        return True


async def _mark_run_completed(run_id: int, lease_token: str) -> None:
    async with config.db.driver.async_session() as session:
        run = await models.LectureVideoProcessingRun.get_by_id(session, run_id)
        if run is None:
            return
        if (
            run.status != schemas.LectureVideoProcessingRunStatus.RUNNING
            or run.lease_token != lease_token
        ):
            return
        if run.lecture_video_id is None:
            await _mark_run_cancelled(
                session,
                run,
                run.cancel_reason
                or schemas.LectureVideoProcessingCancelReason.LECTURE_VIDEO_DELETED,
            )
            await session.commit()
            return
        if not await _lecture_video_has_attached_assistant(
            session, run.lecture_video_id
        ):
            await _mark_run_cancelled(
                session,
                run,
                run.cancel_reason
                or schemas.LectureVideoProcessingCancelReason.ASSISTANT_DETACHED,
            )
            await session.commit()
            return

        lecture_video = await models.LectureVideo.get_by_id(
            session, run.lecture_video_id
        )
        if lecture_video is None:
            await _mark_run_cancelled(
                session,
                run,
                run.cancel_reason
                or schemas.LectureVideoProcessingCancelReason.LECTURE_VIDEO_DELETED,
            )
            await session.commit()
            return

        lecture_video.status = schemas.LectureVideoStatus.READY
        lecture_video.error_message = None
        run.status = schemas.LectureVideoProcessingRunStatus.COMPLETED
        run.finished_at = utcnow()
        run.error_message = None
        run.lease_token = None
        run.leased_by = None
        run.lease_expires_at = None
        session.add(lecture_video)
        session.add(run)
        await session.commit()


async def _mark_run_failed(
    run_id: int,
    lease_token: str,
    narration_id: int | None,
    error_message: str,
) -> None:
    async with config.db.driver.async_session() as session:
        run = await models.LectureVideoProcessingRun.get_by_id(session, run_id)
        if run is None:
            return
        if (
            run.status != schemas.LectureVideoProcessingRunStatus.RUNNING
            or run.lease_token != lease_token
        ):
            return

        narration = (
            await models.LectureVideoNarration.get_by_id(session, narration_id)
            if narration_id is not None
            else None
        )
        if narration is not None:
            narration.status = schemas.LectureVideoNarrationStatus.FAILED
            narration.error_message = error_message
            session.add(narration)

        run.status = schemas.LectureVideoProcessingRunStatus.FAILED
        run.error_message = error_message
        run.finished_at = utcnow()
        run.lease_token = None
        run.leased_by = None
        run.lease_expires_at = None
        session.add(run)

        if run.lecture_video_id is not None:
            lecture_video = await models.LectureVideo.get_by_id(
                session, run.lecture_video_id
            )
            if lecture_video is not None:
                lecture_video.status = schemas.LectureVideoStatus.FAILED
                lecture_video.error_message = error_message
                session.add(lecture_video)

        await session.commit()


async def _mark_run_cancelled(
    session: AsyncSession,
    run: models.LectureVideoProcessingRun,
    cancel_reason: schemas.LectureVideoProcessingCancelReason,
) -> None:
    run.status = schemas.LectureVideoProcessingRunStatus.CANCELLED
    run.cancel_reason = cancel_reason
    run.finished_at = utcnow()
    run.lease_token = None
    run.leased_by = None
    run.lease_expires_at = None
    session.add(run)
    await session.flush()


async def _lecture_video_has_attached_assistant(
    session: AsyncSession, lecture_video_id: int
) -> bool:
    return (
        await session.scalar(
            select(models.Assistant.id).where(
                models.Assistant.lecture_video_id == lecture_video_id
            )
        )
        is not None
    )


def _mark_processing_narrations_failed_for_video(
    lecture_video: models.LectureVideo,
    *,
    error_message: str,
) -> None:
    for question in sorted(lecture_video.questions, key=lambda item: item.position):
        if (
            question.intro_narration is not None
            and question.intro_narration.status
            == schemas.LectureVideoNarrationStatus.PROCESSING
        ):
            question.intro_narration.status = schemas.LectureVideoNarrationStatus.FAILED
            question.intro_narration.error_message = error_message
        for option in sorted(question.options, key=lambda item: item.position):
            if (
                option.post_narration is not None
                and option.post_narration.status
                == schemas.LectureVideoNarrationStatus.PROCESSING
            ):
                option.post_narration.status = (
                    schemas.LectureVideoNarrationStatus.FAILED
                )
                option.post_narration.error_message = error_message


def _user_safe_processing_error_message(exc: Exception) -> str:
    if isinstance(exc, ClassCredentialVoiceValidationError):
        return str(exc)
    if isinstance(exc, ClassCredentialValidationSSLError):
        return (
            "Unable to generate the lecture video narration right now because ElevenLabs "
            "is unavailable due to an SSL error. Please retry."
        )
    if isinstance(exc, ClassCredentialValidationUnavailableError):
        return str(exc)
    if isinstance(exc, AudioStoreError):
        return "Unable to save lecture video narration audio right now. Please retry."
    if isinstance(exc, RuntimeError):
        return str(exc)
    logger.exception(
        "Unexpected lecture video narration processing failure", exc_info=exc
    )
    return "Unable to generate the lecture video narration right now. Please retry."


async def _delete_audio_key_quietly(store_key: str) -> None:
    if not config.lecture_video_audio_store:
        return
    try:
        await config.lecture_video_audio_store.store.delete_file(store_key)
    except Exception:
        logger.exception(
            "Failed to delete lecture video narration audio during cleanup. key=%s",
            store_key,
        )
