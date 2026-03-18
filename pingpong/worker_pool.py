import logging
import queue as queue_module
import signal
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from pingpong.errors import capture_exception_to_sentry

logger = logging.getLogger(__name__)

DEFAULT_WORKER_POLL_INTERVAL_SECONDS = 5.0
DEFAULT_WORKER_SHUTDOWN_GRACE_SECONDS = 5.0


def _sentence_case(value: str) -> str:
    if not value:
        return value
    return f"{value[0].upper()}{value[1:]}"


def ignore_sigint_in_worker() -> None:
    signal.signal(signal.SIGINT, signal.SIG_IGN)


@dataclass(frozen=True)
class RunAssignment:
    run_id: int
    lease_token: str


@dataclass(frozen=True)
class WorkerReady:
    worker_slot: int
    pid: int


@dataclass(frozen=True)
class WorkerStarted:
    worker_slot: int
    run_id: int
    lease_token: str


@dataclass(frozen=True)
class WorkerCompleted:
    worker_slot: int
    run_id: int
    lease_token: str


@dataclass(frozen=True)
class WorkerJobException:
    worker_slot: int
    run_id: int
    lease_token: str
    error_message: str


@dataclass
class WorkerSlotState:
    worker_slot: int
    process: Any
    assignment_queue: Any
    runner_id: str
    pid: int | None
    idle: bool = True
    run_id: int | None = None
    lease_token: str | None = None


class WorkerPoolManager:
    def __init__(
        self,
        *,
        workers: int,
        worker_target: Callable[[int, Any, Any], None],
        process_context: Any,
        claim_run_fn: Callable[[str], tuple[int, str] | None],
        recover_run_fn: Callable[[int, str, str], bool],
        build_runner_id_fn: Callable[[int, int | None], str],
        worker_label: str,
        unexpected_exit_error_message: str,
        poll_interval_seconds: float = DEFAULT_WORKER_POLL_INTERVAL_SECONDS,
        shutdown_grace_seconds: float = DEFAULT_WORKER_SHUTDOWN_GRACE_SECONDS,
        sleep_fn: Callable[[float], None] = time.sleep,
        time_fn: Callable[[], float] = time.monotonic,
    ) -> None:
        if workers <= 0:
            raise ValueError("workers must be greater than 0.")
        if poll_interval_seconds <= 0:
            raise ValueError("poll_interval_seconds must be greater than 0.")
        if shutdown_grace_seconds <= 0:
            raise ValueError("shutdown_grace_seconds must be greater than 0.")

        self.workers = workers
        self.worker_target = worker_target
        self.process_context = process_context
        self.claim_run_fn = claim_run_fn
        self.recover_run_fn = recover_run_fn
        self.build_runner_id_fn = build_runner_id_fn
        self.worker_label = worker_label
        self.worker_label_display = _sentence_case(worker_label)
        self.worker_pool_label = f"{worker_label} pool"
        self.worker_pool_label_display = _sentence_case(self.worker_pool_label)
        self.unexpected_exit_error_message = unexpected_exit_error_message
        self.poll_interval_seconds = poll_interval_seconds
        self.shutdown_grace_seconds = shutdown_grace_seconds
        self.sleep_fn = sleep_fn
        self.time_fn = time_fn
        self.results_queue = self.process_context.Queue()
        self.stop_requested = False
        self.worker_slots: dict[int, WorkerSlotState] = {}

    def request_stop(self) -> None:
        logger.info("%s stop requested.", self.worker_pool_label_display)
        self.stop_requested = True

    def start(self) -> None:
        for worker_slot in range(self.workers):
            self._spawn_worker(worker_slot)

    def run(self) -> None:
        previous_sigint_handler: Any | None = None
        previous_sigterm_handler: Any | None = None

        def _handle_stop_signal(_signum, _frame) -> None:
            self.request_stop()

        try:
            self.start()
            previous_sigint_handler = signal.getsignal(signal.SIGINT)
            previous_sigterm_handler = signal.getsignal(signal.SIGTERM)
            signal.signal(signal.SIGINT, _handle_stop_signal)
            signal.signal(signal.SIGTERM, _handle_stop_signal)
            while not self.stop_requested:
                progress = self.run_one_iteration()
                if self.stop_requested:
                    break
                if not progress:
                    self.sleep_fn(self.poll_interval_seconds)
        except KeyboardInterrupt:
            self.request_stop()
        except Exception as exc:
            logger.exception("%s manager failed.", self.worker_pool_label_display)
            capture_exception_to_sentry(
                exc,
                source=self._manager_exception_source(),
                workers=self.workers,
            )
            raise
        finally:
            try:
                if previous_sigint_handler is not None:
                    signal.signal(signal.SIGINT, previous_sigint_handler)
            finally:
                try:
                    if previous_sigterm_handler is not None:
                        signal.signal(signal.SIGTERM, previous_sigterm_handler)
                finally:
                    self.shutdown()

    def run_one_iteration(self) -> bool:
        progress = False
        progress |= self._drain_results_queue()
        progress |= self._handle_dead_workers()
        if not self.stop_requested:
            progress |= self._assign_runs_to_idle_workers()
        return progress

    def shutdown(self) -> None:
        deadline = self.time_fn() + self.shutdown_grace_seconds

        for slot in self.worker_slots.values():
            process = slot.process
            if getattr(process, "exitcode", None) is None:
                slot.assignment_queue.put(None)

        for slot in self.worker_slots.values():
            process = slot.process
            remaining = max(0.0, deadline - self.time_fn())
            if hasattr(process, "join"):
                process.join(timeout=remaining)

        self._drain_results_queue()

        for slot in self.worker_slots.values():
            if slot.run_id is not None and slot.lease_token is not None:
                self._recover_slot_assignment(
                    slot,
                    error_message=self.unexpected_exit_error_message,
                )

        for slot in self.worker_slots.values():
            process = slot.process
            if getattr(process, "exitcode", None) is None and hasattr(
                process, "terminate"
            ):
                process.terminate()
                if hasattr(process, "join"):
                    process.join(timeout=0.1)

        for slot in self.worker_slots.values():
            self._close_queue(slot.assignment_queue)
        self._close_queue(self.results_queue)
        self._shutdown_resources()

    def _spawn_worker(self, worker_slot: int) -> WorkerSlotState:
        assignment_queue = self.process_context.Queue()
        process = self.process_context.Process(
            target=self.worker_target,
            args=(worker_slot, assignment_queue, self.results_queue),
            daemon=True,
        )
        process.start()
        runner_id = self.build_runner_id_fn(worker_slot, process.pid)
        logger.info(
            "Started %s process. slot=%s pid=%s runner_id=%s",
            self.worker_label,
            worker_slot,
            process.pid,
            runner_id,
        )
        slot = WorkerSlotState(
            worker_slot=worker_slot,
            process=process,
            assignment_queue=assignment_queue,
            runner_id=runner_id,
            pid=process.pid,
        )
        self.worker_slots[worker_slot] = slot
        return slot

    def _drain_results_queue(self) -> bool:
        progress = False
        while True:
            try:
                event = self.results_queue.get_nowait()
            except queue_module.Empty:
                return progress

            progress = True
            if isinstance(event, WorkerReady):
                self._handle_worker_ready(event)
            elif isinstance(event, WorkerStarted):
                self._handle_worker_started(event)
            elif isinstance(event, WorkerCompleted):
                self._handle_worker_completed(event)
            elif isinstance(event, WorkerJobException):
                self._handle_worker_job_exception(event)

    def _handle_worker_ready(self, event: WorkerReady) -> None:
        slot = self.worker_slots.get(event.worker_slot)
        if slot is None:
            return
        slot.pid = event.pid
        slot.runner_id = self.build_runner_id_fn(event.worker_slot, event.pid)
        logger.info(
            "%s ready. slot=%s pid=%s runner_id=%s",
            self.worker_label_display,
            event.worker_slot,
            event.pid,
            slot.runner_id,
        )

    def _handle_worker_started(self, event: WorkerStarted) -> None:
        slot = self.worker_slots.get(event.worker_slot)
        if slot is None:
            return
        logger.info(
            "%s acknowledged run. slot=%s pid=%s run_id=%s",
            self.worker_label_display,
            event.worker_slot,
            slot.pid,
            event.run_id,
        )

    def _handle_worker_completed(self, event: WorkerCompleted) -> None:
        slot = self.worker_slots.get(event.worker_slot)
        if slot is None:
            return
        if slot.run_id != event.run_id or slot.lease_token != event.lease_token:
            return
        logger.info(
            "%s finished assigned run. slot=%s pid=%s run_id=%s",
            self.worker_label_display,
            event.worker_slot,
            slot.pid,
            event.run_id,
        )
        self._clear_assignment(slot)

    def _handle_worker_job_exception(self, event: WorkerJobException) -> None:
        slot = self.worker_slots.get(event.worker_slot)
        if slot is None:
            return
        if slot.run_id != event.run_id or slot.lease_token != event.lease_token:
            return
        error_message = event.error_message or self.unexpected_exit_error_message
        logger.error(
            "%s reported job exception. slot=%s pid=%s run_id=%s error=%s",
            self.worker_label_display,
            event.worker_slot,
            slot.pid,
            event.run_id,
            error_message,
        )
        self._recover_assignment(
            slot,
            run_id=event.run_id,
            lease_token=event.lease_token,
            error_message=error_message,
        )

    def _handle_dead_workers(self) -> bool:
        progress = False
        for worker_slot, slot in list(self.worker_slots.items()):
            process = slot.process
            if getattr(process, "exitcode", None) is None:
                continue

            progress = True
            logger.warning(
                "%s exited unexpectedly. slot=%s pid=%s exitcode=%s run_id=%s",
                self.worker_label_display,
                worker_slot,
                slot.pid,
                process.exitcode,
                slot.run_id,
            )
            self._recover_slot_assignment(
                slot,
                error_message=self.unexpected_exit_error_message,
            )
            self._close_queue(slot.assignment_queue)
            if hasattr(process, "join"):
                process.join(timeout=0)
            if self.stop_requested:
                continue
            self._spawn_worker(worker_slot)
        return progress

    def _assign_runs_to_idle_workers(self) -> bool:
        progress = False
        for worker_slot in sorted(self.worker_slots):
            slot = self.worker_slots[worker_slot]
            if not slot.idle or getattr(slot.process, "exitcode", None) is not None:
                continue

            claim = self.claim_run_fn(slot.runner_id)
            if claim is None:
                # claim_run_fn is expected to claim from a shared global queue.
                # Once one idle worker sees no claimable work, later idle workers
                # in this pass should see the same empty queue as well.
                break

            run_id, lease_token = claim
            logger.info(
                "Assigning run to %s. slot=%s pid=%s runner_id=%s run_id=%s",
                self.worker_label,
                worker_slot,
                slot.pid,
                slot.runner_id,
                run_id,
            )
            slot.run_id = run_id
            slot.lease_token = lease_token
            slot.idle = False
            slot.assignment_queue.put(
                RunAssignment(run_id=run_id, lease_token=lease_token)
            )
            progress = True

        return progress

    def _recover_slot_assignment(
        self,
        slot: WorkerSlotState,
        *,
        error_message: str,
    ) -> None:
        if slot.run_id is None or slot.lease_token is None:
            return
        self._recover_assignment(
            slot,
            run_id=slot.run_id,
            lease_token=slot.lease_token,
            error_message=error_message,
        )

    def _recover_assignment(
        self,
        slot: WorkerSlotState,
        *,
        run_id: int,
        lease_token: str,
        error_message: str,
    ) -> None:
        try:
            self.recover_run_fn(run_id, lease_token, error_message)
        finally:
            if slot.run_id == run_id and slot.lease_token == lease_token:
                self._clear_assignment(slot)

    def _clear_assignment(self, slot: WorkerSlotState) -> None:
        slot.idle = True
        slot.run_id = None
        slot.lease_token = None

    def _shutdown_resources(self) -> None:
        return

    def _manager_exception_source(self) -> str:
        return f"{self.worker_label.replace(' ', '-')}-parent"

    def _close_queue(self, queue_obj: object) -> None:
        close_fn = getattr(queue_obj, "close", None)
        if callable(close_fn):
            close_fn()
        join_thread_fn = getattr(queue_obj, "join_thread", None)
        if callable(join_thread_fn):
            join_thread_fn()
