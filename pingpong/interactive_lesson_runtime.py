from collections.abc import Awaitable, Callable, Sequence
from datetime import datetime, timedelta, timezone
from typing import Any, Protocol

import uuid_utils as uuid
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

import pingpong.models as models
import pingpong.schemas as schemas
from pingpong.now import NowFn, utcnow

CONTROLLER_LEASE_DURATION = timedelta(seconds=30)
CONTROLLER_LEASE_DURATION_MS = int(CONTROLLER_LEASE_DURATION.total_seconds() * 1000)
ERROR_CONTROLLER_LEASE_EXPIRED = "controller_lease_expired"
PLAYBACK_PROGRESS_TOLERANCE_MS = 2_000

MSG_STALE_PAGE = "This page was inactive for too long. Refresh the lesson to continue."
MSG_OTHER_CONTROLLER = (
    "Someone else is controlling this video right now. Try again in a moment."
)
MSG_TAB_DISCONNECTED = (
    "This tab is no longer connected to the video. Refresh the lesson to continue."
)
MSG_LESSON_UPDATED = "This video lesson was updated. Start a new lesson to continue."
MSG_QUESTION_NO_LONGER_OPEN = (
    "This question is no longer open. Refresh the lesson to see the latest question."
)
MSG_QUESTION_ALREADY_CLOSED = (
    "This question is already closed. Refresh the lesson to continue."
)
MSG_SKIP_AHEAD_BLOCKED = (
    "You cannot skip ahead yet. Continue from where the lesson left off."
)
MSG_CANNOT_CONTINUE_FROM_HERE = (
    "The video cannot continue from here. Refresh the lesson and try again."
)
MSG_VIDEO_CANNOT_DO_THAT = (
    "The video cannot do that right now. Wait a moment, then try again."
)
MSG_PAUSE_AHEAD_OF_PROGRESS = (
    "The lesson could not save that spot because it is ahead of your current progress."
)
MSG_JUMP_AHEAD_BLOCKED = (
    "You cannot jump ahead yet. Continue from where the lesson left off."
)
MSG_COMPLETE_FROM_SPOT_BLOCKED = "The lesson cannot be marked complete from this spot. Continue from where you left off."
MSG_REFRESH_AND_RETRY = (
    "This lesson changed while you were working. Refresh the lesson and try again."
)


class InteractiveLessonAdapter(Protocol):
    state_model: Any
    interaction_model: Any
    state_enum: "LessonStateEnum"

    async def get_thread_with_context(
        self, session: AsyncSession, thread_id: int
    ) -> models.Thread | None:
        pass

    def get_asset(self, thread: models.Thread) -> object | None:
        pass

    def get_questions(self, thread: models.Thread) -> Sequence["LessonQuestion"]:
        pass

    def get_state(self, thread: models.Thread) -> "LessonState | None":
        pass

    def set_state(self, thread: models.Thread, state: "LessonState") -> None:
        pass

    def matches_assistant(self, thread: models.Thread) -> bool:
        pass

    def lesson_chat_available(self, asset: object) -> bool:
        pass

    def timeline_bypass_enabled(self, thread: models.Thread) -> bool:
        pass

    def initial_state_fields(self) -> dict[str, Any]:
        pass

    def to_storage_event(
        self, event_type: schemas.InteractiveLessonInteractionEventType
    ) -> object:
        pass


class LessonStateValue(Protocol):
    value: str


class LessonStateEnum(Protocol):
    PLAYING: LessonStateValue
    AWAITING_ANSWER: LessonStateValue
    AWAITING_POST_ANSWER_RESUME: LessonStateValue
    COMPLETED: LessonStateValue


class LessonNarrationStatus(Protocol):
    value: str


class LessonNarration(Protocol):
    id: int
    status: LessonNarrationStatus
    stored_object: object | None


class LessonQuestionOption(Protocol):
    id: int
    position: int
    option_text: str
    post_answer_text: str | None
    continue_offset_ms: int
    post_narration_id: int | None
    post_narration: LessonNarration | None


class LessonQuestionType(Protocol):
    value: str


class LessonQuestion(Protocol):
    id: int
    position: int
    question_type: LessonQuestionType | str
    question_text: str
    intro_text: str
    stop_offset_ms: int
    intro_narration_id: int | None
    intro_narration: LessonNarration | None
    correct_option: LessonQuestionOption | None
    options: Sequence[LessonQuestionOption]


class LessonState(Protocol):
    thread_id: int
    thread: models.Thread
    state: LessonStateValue
    current_question_id: int | None
    current_question: LessonQuestion | None
    active_option_id: int | None
    active_option: LessonQuestionOption | None
    last_known_offset_ms: int
    furthest_offset_ms: int
    version: int
    controller_session_id: str | None
    controller_user_id: int | None
    controller_lease_expires_at: datetime | None
    normalized_controller_lease_expires_at: datetime | None


class InteractiveLessonRuntimeError(Exception):
    def __init__(self, detail: str, *, error_code: str | None = None) -> None:
        super().__init__(detail)
        self.detail = detail
        self.error_code = error_code


class InteractiveLessonNotFoundError(InteractiveLessonRuntimeError):
    pass


class InteractiveLessonValidationError(InteractiveLessonRuntimeError):
    pass


class InteractiveLessonConflictError(InteractiveLessonRuntimeError):
    pass


def _state_enum(adapter: InteractiveLessonAdapter) -> LessonStateEnum:
    return adapter.state_enum


def has_active_controller(state: LessonState, now: datetime | None = None) -> bool:
    current_time = now or utcnow()
    lease_expires_at = state.normalized_controller_lease_expires_at
    return bool(
        state.controller_session_id
        and state.controller_user_id is not None
        and lease_expires_at is not None
        and lease_expires_at > current_time
    )


def _narration_id(narration: LessonNarration | None) -> int | None:
    if narration is None or narration.stored_object is None:
        return None
    if narration.status.value != "ready":
        return None
    return narration.id


def _question_type_value(question_type: LessonQuestionType | str) -> str:
    if isinstance(question_type, str):
        return question_type
    return question_type.value


def _question_prompt(
    question: LessonQuestion,
) -> schemas.InteractiveLessonQuestionPrompt:
    return schemas.InteractiveLessonQuestionPrompt(
        id=question.id,
        type=_question_type_value(question.question_type),
        question_text=question.question_text,
        intro_text=question.intro_text,
        stop_offset_ms=question.stop_offset_ms,
        intro_narration_id=_narration_id(question.intro_narration),
        options=[
            schemas.InteractiveLessonOptionPrompt(
                id=option.id,
                option_text=option.option_text,
            )
            for option in sorted(question.options, key=lambda item: item.position)
        ],
    )


def _question_markers(
    thread: models.Thread,
    *,
    adapter: InteractiveLessonAdapter,
) -> list[schemas.InteractiveLessonQuestionMarker]:
    if adapter.get_asset(thread) is None:
        return []
    return [
        schemas.InteractiveLessonQuestionMarker(
            id=question.id,
            stop_offset_ms=question.stop_offset_ms,
        )
        for question in sorted(
            adapter.get_questions(thread), key=lambda item: item.stop_offset_ms
        )
    ]


def _get_current_question(
    thread: models.Thread, state: LessonState, *, adapter: InteractiveLessonAdapter
) -> LessonQuestion | None:
    if state.current_question is not None:
        return state.current_question
    if adapter.get_asset(thread) is None:
        return None
    for question in adapter.get_questions(thread):
        if question.id == state.current_question_id:
            return question
    return None


def _get_next_question(
    thread: models.Thread,
    current_question: LessonQuestion | None,
    *,
    adapter: InteractiveLessonAdapter,
) -> LessonQuestion | None:
    if adapter.get_asset(thread) is None or current_question is None:
        return None
    next_position = current_question.position + 1
    for question in adapter.get_questions(thread):
        if question.position == next_position:
            return question
    return None


def _is_timeline_bypass_enabled(
    thread: models.Thread, *, adapter: InteractiveLessonAdapter
) -> bool:
    return bool(adapter.timeline_bypass_enabled(thread))


async def _get_answered_question_ids(
    session: AsyncSession, state: LessonState, *, adapter: InteractiveLessonAdapter
) -> set[int]:
    return await adapter.interaction_model.get_answered_question_ids_by_thread_id(
        session, state.thread_id
    )


async def _reset_question_queue_for_offset(
    session: AsyncSession,
    state: LessonState,
    offset_ms: int,
    *,
    adapter: InteractiveLessonAdapter,
) -> None:
    answered_question_ids = await _get_answered_question_ids(
        session, state, adapter=adapter
    )
    next_question = next(
        (
            question
            for question in sorted(
                adapter.get_questions(state.thread),
                key=lambda item: item.stop_offset_ms,
            )
            if question.stop_offset_ms > offset_ms
            and question.id not in answered_question_ids
        ),
        None,
    )
    state.active_option_id = None
    state.active_option = None
    state.current_question_id = next_question.id if next_question is not None else None
    state.current_question = next_question


def _build_continuation(
    thread: models.Thread, state: LessonState, *, adapter: InteractiveLessonAdapter
) -> schemas.InteractiveLessonContinuation | None:
    state_enum = _state_enum(adapter)
    if (
        state.state != state_enum.AWAITING_POST_ANSWER_RESUME
        or state.active_option is None
    ):
        return None

    current_question = _get_current_question(thread, state, adapter=adapter)
    next_question = _get_next_question(thread, current_question, adapter=adapter)

    correct_option_id: int | None = None
    if current_question is not None and adapter.get_asset(thread) is not None:
        for question in adapter.get_questions(thread):
            if (
                question.id == current_question.id
                and question.correct_option is not None
            ):
                correct_option_id = question.correct_option.id
                break

    return schemas.InteractiveLessonContinuation(
        option_id=state.active_option.id,
        correct_option_id=correct_option_id,
        post_answer_text=state.active_option.post_answer_text or None,
        post_answer_narration_id=_narration_id(state.active_option.post_narration),
        resume_offset_ms=state.active_option.continue_offset_ms,
        next_question=_question_prompt(next_question)
        if next_question is not None
        else None,
        complete=next_question is None,
    )


def build_interactive_lesson_session(
    thread: models.Thread,
    state: LessonState,
    *,
    adapter: InteractiveLessonAdapter,
    furthest_offset_ms: int | None = None,
    latest_interaction_at: datetime | None = None,
    request_controller_session_id: str | None = None,
    request_actor_user_id: int | None = None,
    now: datetime | None = None,
) -> schemas.InteractiveLessonSession:
    current_time = now or utcnow()
    current_question = _get_current_question(thread, state, adapter=adapter)
    state_enum = _state_enum(adapter)
    active_controller = has_active_controller(state, current_time)
    request_has_control = bool(
        active_controller
        and request_controller_session_id
        and request_controller_session_id == state.controller_session_id
        and request_actor_user_id is not None
        and request_actor_user_id == state.controller_user_id
    )
    asset = adapter.get_asset(thread)

    return schemas.InteractiveLessonSession(
        state=schemas.InteractiveLessonSessionState(state.state.value),
        lesson_chat_available=bool(
            asset is not None and adapter.lesson_chat_available(asset)
        ),
        timeline_bypass_enabled=_is_timeline_bypass_enabled(thread, adapter=adapter),
        last_known_offset_ms=state.last_known_offset_ms,
        furthest_offset_ms=furthest_offset_ms,
        latest_interaction_at=latest_interaction_at,
        current_question=(
            _question_prompt(current_question)
            if request_has_control
            and current_question is not None
            and state.state != state_enum.COMPLETED
            else None
        ),
        current_continuation=(
            _build_continuation(thread, state, adapter=adapter)
            if request_has_control
            else None
        ),
        question_markers=_question_markers(thread, adapter=adapter),
        state_version=state.version,
        controller=schemas.InteractiveLessonSessionController(
            has_control=request_has_control,
            has_active_controller=active_controller,
            lease_expires_at=(
                state.normalized_controller_lease_expires_at
                if active_controller
                else None
            ),
            lease_duration_ms=CONTROLLER_LEASE_DURATION_MS
            if active_controller
            else None,
        ),
    )


async def _build_interactive_lesson_session_for_state(
    state: LessonState,
    *,
    adapter: InteractiveLessonAdapter,
    latest_interaction_at: datetime | None = None,
    request_controller_session_id: str | None = None,
    request_actor_user_id: int | None = None,
    now: datetime | None = None,
) -> schemas.InteractiveLessonSession:
    furthest_offset_ms = _get_unlocked_offset_ms(state)
    return build_interactive_lesson_session(
        state.thread,
        state,
        adapter=adapter,
        furthest_offset_ms=furthest_offset_ms,
        latest_interaction_at=latest_interaction_at,
        request_controller_session_id=request_controller_session_id,
        request_actor_user_id=request_actor_user_id,
        now=now,
    )


def get_current_question(
    thread: models.Thread, state: LessonState, *, adapter: InteractiveLessonAdapter
) -> LessonQuestion | None:
    return _get_current_question(thread, state, adapter=adapter)


async def build_interactive_lesson_session_for_state(
    state: LessonState,
    *,
    adapter: InteractiveLessonAdapter,
    latest_interaction_at: datetime | None = None,
    request_controller_session_id: str | None = None,
    request_actor_user_id: int | None = None,
    now: datetime | None = None,
) -> schemas.InteractiveLessonSession:
    return await _build_interactive_lesson_session_for_state(
        state,
        adapter=adapter,
        latest_interaction_at=latest_interaction_at,
        request_controller_session_id=request_controller_session_id,
        request_actor_user_id=request_actor_user_id,
        now=now,
    )


def _get_unlocked_offset_ms(state: LessonState) -> int:
    return max(state.last_known_offset_ms, state.furthest_offset_ms)


def get_unlocked_offset_ms(state: LessonState) -> int:
    return _get_unlocked_offset_ms(state)


def _set_last_known_offset_ms(state: LessonState, offset_ms: int) -> None:
    state.last_known_offset_ms = offset_ms
    state.furthest_offset_ms = max(state.furthest_offset_ms, offset_ms)


def _set_seek_offset_ms(
    state: LessonState,
    *,
    from_offset_ms: int,
    to_offset_ms: int,
    plausible_offset_ms: int,
) -> None:
    state.last_known_offset_ms = to_offset_ms
    state.furthest_offset_ms = max(
        state.furthest_offset_ms,
        to_offset_ms,
        from_offset_ms if from_offset_ms <= plausible_offset_ms else 0,
    )


def _normalize_interaction_time(timestamp: datetime | None) -> datetime | None:
    if timestamp is None:
        return None
    if timestamp.tzinfo is None:
        return timestamp.replace(tzinfo=timezone.utc)
    return timestamp


async def get_plausible_playback_offset_ms(
    session: AsyncSession,
    state: LessonState,
    *,
    adapter: InteractiveLessonAdapter,
    current_time: datetime,
) -> int:
    state_enum = _state_enum(adapter)
    unlocked_offset_ms = _get_unlocked_offset_ms(state)
    if state.state != state_enum.PLAYING:
        return unlocked_offset_ms

    latest_interaction_at = _normalize_interaction_time(
        await adapter.interaction_model.get_latest_created_by_thread_id(
            session, state.thread_id
        )
    )
    if latest_interaction_at is None:
        return unlocked_offset_ms

    elapsed_ms = max(
        int((current_time - latest_interaction_at).total_seconds() * 1000),
        0,
    )
    return max(
        unlocked_offset_ms,
        state.last_known_offset_ms + elapsed_ms + PLAYBACK_PROGRESS_TOLERANCE_MS,
    )


async def get_thread_session(
    session: AsyncSession,
    thread_id: int,
    *,
    adapter: InteractiveLessonAdapter,
    request_controller_session_id: str | None = None,
    request_actor_user_id: int | None = None,
    nowfn: NowFn | None = None,
) -> schemas.InteractiveLessonSession | None:
    thread = await adapter.get_thread_with_context(session, thread_id)
    if not thread or adapter.get_asset(thread) is None:
        return None
    state = adapter.get_state(thread) or await get_or_initialize_thread_state(
        session, thread_id, adapter=adapter
    )
    latest_interaction_at = (
        await adapter.interaction_model.get_latest_created_by_thread_id(
            session, thread.id
        )
    )
    return await _build_interactive_lesson_session_for_state(
        state,
        adapter=adapter,
        latest_interaction_at=latest_interaction_at,
        request_controller_session_id=request_controller_session_id,
        request_actor_user_id=request_actor_user_id,
        now=nowfn() if nowfn is not None else None,
    )


async def initialize_thread_state(
    session: AsyncSession,
    thread_id: int,
    *,
    adapter: InteractiveLessonAdapter,
) -> LessonState:
    thread = await adapter.get_thread_with_context(session, thread_id)
    if thread is None or adapter.get_asset(thread) is None:
        raise InteractiveLessonNotFoundError("Interactive lesson thread not found.")

    first_question = next(
        iter(sorted(adapter.get_questions(thread), key=lambda item: item.position)),
        None,
    )
    state_enum = _state_enum(adapter)

    state_data = {
        "thread_id": thread.id,
        "state": state_enum.PLAYING,
        "current_question_id": first_question.id
        if first_question is not None
        else None,
        "last_known_offset_ms": 0,
        "furthest_offset_ms": 0,
        "version": 1,
    }
    state_data.update(adapter.initial_state_fields())
    state = await adapter.state_model.create(session, state_data)
    await adapter.interaction_model.create(
        session,
        {
            "thread_id": thread.id,
            "event_index": 1,
            "event_type": adapter.to_storage_event(
                schemas.InteractiveLessonInteractionEventType.SESSION_INITIALIZED
            ),
            "idempotency_key": adapter.interaction_model.generate_idempotency_key(),
        },
    )
    return state


async def get_or_initialize_thread_state(
    session: AsyncSession,
    thread_id: int,
    *,
    adapter: InteractiveLessonAdapter,
    for_update: bool = False,
) -> LessonState:
    if for_update:
        # Keep runtime writes in the same lock order as message sends: threads
        # first, then lesson state. Interaction inserts take a FK lock on
        # threads, so taking the state lock first can deadlock with a concurrent
        # message send that already holds the thread row lock and then updates
        # lesson chat context on the state row.
        thread = await models.Thread.get_by_id(session, thread_id, for_update=True)
        if thread is None:
            raise InteractiveLessonNotFoundError("Interactive lesson thread not found.")

    state = await adapter.state_model.get_by_thread_id_with_context(
        session, thread_id, for_update=for_update
    )
    if state is not None:
        adapter.set_state(state.thread, state)
        return _require_state(state, adapter=adapter)

    try:
        async with session.begin_nested():
            await initialize_thread_state(session, thread_id, adapter=adapter)
    except IntegrityError:
        # Another request created the runtime state first. Re-read it below.
        pass

    state = await adapter.state_model.get_by_thread_id_with_context(
        session, thread_id, for_update=for_update
    )
    if state is not None:
        adapter.set_state(state.thread, state)
    return _require_state(state, adapter=adapter)


def _require_state(
    state: LessonState | None, *, adapter: InteractiveLessonAdapter
) -> LessonState:
    if state is None:
        raise InteractiveLessonNotFoundError("Interactive lesson runtime not found.")
    if adapter.get_asset(state.thread) is None:
        raise InteractiveLessonNotFoundError("Interactive lesson thread not found.")
    return state


def _conflict(
    *,
    detail: str,
    error_code: str | None = None,
) -> InteractiveLessonConflictError:
    return InteractiveLessonConflictError(detail, error_code=error_code)


def _require_controller(
    state: LessonState,
    *,
    actor_user_id: int,
    controller_session_id: str,
    now: datetime | None = None,
) -> None:
    if not has_active_controller(state, now):
        raise _conflict(
            detail=MSG_STALE_PAGE,
            error_code=ERROR_CONTROLLER_LEASE_EXPIRED,
        )
    if state.controller_user_id != actor_user_id:
        raise _conflict(
            detail=MSG_OTHER_CONTROLLER,
        )
    if state.controller_session_id != controller_session_id:
        raise _conflict(
            detail=MSG_TAB_DISCONNECTED,
        )


async def _append_interaction(
    session: AsyncSession,
    state: LessonState,
    *,
    adapter: InteractiveLessonAdapter,
    actor_user_id: int | None,
    event_type: schemas.InteractiveLessonInteractionEventType,
    question_id: int | None = None,
    option_id: int | None = None,
    offset_ms: int | None = None,
    from_offset_ms: int | None = None,
    to_offset_ms: int | None = None,
    idempotency_key: str | None = None,
) -> object:
    # get_next_event_index() is a read-then-write sequence. Callers must hold the
    # lesson state row lock acquired via get_or_initialize_thread_state(
    # ..., for_update=True) so concurrent requests for the same thread serialize.
    if not getattr(state, "_locked_for_interaction_append", False):
        raise RuntimeError(
            "Interactive lesson state must be loaded with FOR UPDATE before appending "
            "interactions."
        )
    event_index = await adapter.interaction_model.get_next_event_index(
        session, state.thread_id
    )
    effective_idempotency_key = (
        idempotency_key
        if isinstance(idempotency_key, str) and idempotency_key.strip()
        else adapter.interaction_model.generate_idempotency_key()
    )
    return await adapter.interaction_model.create(
        session,
        {
            "thread_id": state.thread_id,
            "event_index": event_index,
            "actor_user_id": actor_user_id,
            "event_type": adapter.to_storage_event(event_type),
            "question_id": question_id,
            "option_id": option_id,
            "offset_ms": offset_ms,
            "from_offset_ms": from_offset_ms,
            "to_offset_ms": to_offset_ms,
            "idempotency_key": effective_idempotency_key,
        },
    )


async def append_interaction(
    session: AsyncSession,
    state: LessonState,
    *,
    adapter: InteractiveLessonAdapter,
    actor_user_id: int | None,
    event_type: schemas.InteractiveLessonInteractionEventType,
    question_id: int | None = None,
    option_id: int | None = None,
    offset_ms: int | None = None,
    from_offset_ms: int | None = None,
    to_offset_ms: int | None = None,
    idempotency_key: str | None = None,
) -> object:
    return await _append_interaction(
        session,
        state,
        adapter=adapter,
        actor_user_id=actor_user_id,
        event_type=event_type,
        question_id=question_id,
        option_id=option_id,
        offset_ms=offset_ms,
        from_offset_ms=from_offset_ms,
        to_offset_ms=to_offset_ms,
        idempotency_key=idempotency_key,
    )


def _renew_controller_lease(
    state: LessonState,
    actor_user_id: int,
    controller_session_id: str,
    *,
    now: datetime | None = None,
) -> None:
    state.controller_user_id = actor_user_id
    state.controller_session_id = controller_session_id
    state.controller_lease_expires_at = (now or utcnow()) + CONTROLLER_LEASE_DURATION


async def acquire_control(
    session: AsyncSession,
    thread_id: int,
    actor_user_id: int,
    *,
    adapter: InteractiveLessonAdapter,
    nowfn: NowFn | None = None,
) -> tuple[str, schemas.InteractiveLessonSession]:
    state = await get_or_initialize_thread_state(
        session, thread_id, adapter=adapter, for_update=True
    )
    current_time = nowfn() if nowfn is not None else utcnow()
    if not adapter.matches_assistant(state.thread):
        raise InteractiveLessonConflictError(MSG_LESSON_UPDATED)

    if (
        has_active_controller(state, current_time)
        and state.controller_user_id != actor_user_id
    ):
        raise _conflict(
            detail=MSG_OTHER_CONTROLLER,
        )

    controller_session_id = str(uuid.uuid7())
    state.version += 1
    _renew_controller_lease(
        state,
        actor_user_id,
        controller_session_id,
        now=current_time,
    )
    await session.flush()
    latest_interaction_at = (
        await adapter.interaction_model.get_latest_created_by_thread_id(
            session, state.thread_id
        )
    )

    return (
        controller_session_id,
        await _build_interactive_lesson_session_for_state(
            state,
            adapter=adapter,
            latest_interaction_at=latest_interaction_at,
            request_controller_session_id=controller_session_id,
            request_actor_user_id=actor_user_id,
            now=current_time,
        ),
    )


async def release_control(
    session: AsyncSession,
    thread_id: int,
    actor_user_id: int,
    controller_session_id: str,
    *,
    adapter: InteractiveLessonAdapter,
    nowfn: NowFn | None = None,
) -> schemas.InteractiveLessonSession:
    state = await get_or_initialize_thread_state(
        session, thread_id, adapter=adapter, for_update=True
    )
    current_time = nowfn() if nowfn is not None else utcnow()
    _require_controller(
        state,
        actor_user_id=actor_user_id,
        controller_session_id=controller_session_id,
        now=current_time,
    )
    state.version += 1
    state.controller_session_id = None
    state.controller_user_id = None
    state.controller_lease_expires_at = None
    await session.flush()
    latest_interaction_at = (
        await adapter.interaction_model.get_latest_created_by_thread_id(
            session, state.thread_id
        )
    )
    return await _build_interactive_lesson_session_for_state(
        state,
        adapter=adapter,
        latest_interaction_at=latest_interaction_at,
        request_actor_user_id=actor_user_id,
        now=current_time,
    )


async def renew_control(
    session: AsyncSession,
    thread_id: int,
    actor_user_id: int,
    controller_session_id: str,
    *,
    adapter: InteractiveLessonAdapter,
    nowfn: NowFn | None = None,
) -> datetime:
    state = await get_or_initialize_thread_state(
        session, thread_id, adapter=adapter, for_update=True
    )
    current_time = nowfn() if nowfn is not None else utcnow()
    if not adapter.matches_assistant(state.thread):
        raise InteractiveLessonConflictError(MSG_LESSON_UPDATED)

    _require_controller(
        state,
        actor_user_id=actor_user_id,
        controller_session_id=controller_session_id,
        now=current_time,
    )
    _renew_controller_lease(
        state,
        actor_user_id,
        controller_session_id,
        now=current_time,
    )
    await session.flush()
    lease_expires_at = state.normalized_controller_lease_expires_at
    assert lease_expires_at is not None
    return lease_expires_at


def _find_option_for_question(
    question: LessonQuestion, option_id: int
) -> LessonQuestionOption | None:
    for option in question.options:
        if option.id == option_id:
            return option
    return None


InteractionHandler = Callable[..., Awaitable[None]]


async def _handle_question_presented(
    session: AsyncSession,
    state: LessonState,
    actor_user_id: int,
    request: schemas.InteractiveLessonQuestionPresentedRequest,
    *,
    adapter: InteractiveLessonAdapter,
    event_type: schemas.InteractiveLessonInteractionEventType,
    current_time: datetime,
) -> None:
    current_question = _get_current_question(state.thread, state, adapter=adapter)
    state_enum = _state_enum(adapter)
    if (
        state.state != state_enum.PLAYING
        or current_question is None
        or current_question.id != request.question_id
    ):
        raise _conflict(
            detail=MSG_QUESTION_NO_LONGER_OPEN,
        )

    if request.offset_ms != current_question.stop_offset_ms:
        raise InteractiveLessonValidationError(
            "Question presentation must occur at the configured stop offset."
        )

    # With timeline bypass the participant may legitimately reach a checkpoint
    # right after seeking near it, so plausible watched progress is no gate.
    if not _is_timeline_bypass_enabled(state.thread, adapter=adapter):
        plausible_offset_ms = await get_plausible_playback_offset_ms(
            session, state, adapter=adapter, current_time=current_time
        )
        if request.offset_ms > plausible_offset_ms:
            raise InteractiveLessonValidationError(
                "Presenting a question past your unlocked progress is not allowed in this lecture video."
            )

    state.state = state_enum.AWAITING_ANSWER
    _set_last_known_offset_ms(state, request.offset_ms)
    await _append_interaction(
        session,
        state,
        adapter=adapter,
        actor_user_id=actor_user_id,
        event_type=event_type,
        question_id=request.question_id,
        offset_ms=request.offset_ms,
        idempotency_key=request.idempotency_key,
    )


async def _handle_answer_submitted(
    session: AsyncSession,
    state: LessonState,
    actor_user_id: int,
    request: schemas.InteractiveLessonAnswerSubmittedRequest,
    *,
    adapter: InteractiveLessonAdapter,
    event_type: schemas.InteractiveLessonInteractionEventType,
    current_time: datetime,
) -> None:
    current_question = _get_current_question(state.thread, state, adapter=adapter)
    state_enum = _state_enum(adapter)
    if (
        state.state != state_enum.AWAITING_ANSWER
        or current_question is None
        or current_question.id != request.question_id
    ):
        raise _conflict(
            detail=MSG_QUESTION_ALREADY_CLOSED,
        )

    option = _find_option_for_question(current_question, request.option_id)
    if option is None:
        raise InteractiveLessonValidationError(
            "That option does not belong to this question."
        )

    state.state = state_enum.AWAITING_POST_ANSWER_RESUME
    state.active_option = option
    await _append_interaction(
        session,
        state,
        adapter=adapter,
        actor_user_id=actor_user_id,
        event_type=event_type,
        question_id=request.question_id,
        option_id=option.id,
        idempotency_key=request.idempotency_key,
    )


async def _handle_resumed(
    session: AsyncSession,
    state: LessonState,
    actor_user_id: int,
    request: schemas.InteractiveLessonResumedRequest,
    *,
    adapter: InteractiveLessonAdapter,
    event_type: schemas.InteractiveLessonInteractionEventType,
    current_time: datetime,
) -> None:
    state_enum = _state_enum(adapter)
    if state.state in {
        state_enum.PLAYING,
        state_enum.COMPLETED,
    }:
        plausible_offset_ms = await get_plausible_playback_offset_ms(
            session, state, adapter=adapter, current_time=current_time
        )
        timeline_bypass_enabled = _is_timeline_bypass_enabled(
            state.thread, adapter=adapter
        )
        if request.offset_ms > plausible_offset_ms and not timeline_bypass_enabled:
            raise InteractiveLessonValidationError(MSG_SKIP_AHEAD_BLOCKED)
        _set_last_known_offset_ms(state, request.offset_ms)
        await _append_interaction(
            session,
            state,
            adapter=adapter,
            actor_user_id=actor_user_id,
            event_type=event_type,
            offset_ms=request.offset_ms,
            idempotency_key=request.idempotency_key,
        )
        return

    current_question = _get_current_question(state.thread, state, adapter=adapter)
    active_option = state.active_option
    if (
        state.state != state_enum.AWAITING_POST_ANSWER_RESUME
        or active_option is None
        or request.offset_ms != active_option.continue_offset_ms
    ):
        raise _conflict(
            detail=MSG_CANNOT_CONTINUE_FROM_HERE,
        )

    next_question = _get_next_question(state.thread, current_question, adapter=adapter)
    _set_last_known_offset_ms(state, request.offset_ms)
    state.active_option_id = None
    state.active_option = None
    if next_question is None:
        state.current_question_id = None
        state.current_question = None
    else:
        state.current_question_id = next_question.id
        state.current_question = next_question
    state.state = state_enum.PLAYING

    await _append_interaction(
        session,
        state,
        adapter=adapter,
        actor_user_id=actor_user_id,
        event_type=event_type,
        offset_ms=request.offset_ms,
        idempotency_key=request.idempotency_key,
    )


def _require_playing_state_for_playback_event(
    state: LessonState, *, adapter: InteractiveLessonAdapter
) -> None:
    state_enum = _state_enum(adapter)
    if state.state not in {
        state_enum.PLAYING,
        state_enum.COMPLETED,
    }:
        raise _conflict(
            detail=MSG_VIDEO_CANNOT_DO_THAT,
        )


async def _handle_paused(
    session: AsyncSession,
    state: LessonState,
    actor_user_id: int,
    request: schemas.InteractiveLessonPausedRequest,
    *,
    adapter: InteractiveLessonAdapter,
    event_type: schemas.InteractiveLessonInteractionEventType,
    current_time: datetime,
) -> None:
    _require_playing_state_for_playback_event(state, adapter=adapter)
    plausible_offset_ms = await get_plausible_playback_offset_ms(
        session, state, adapter=adapter, current_time=current_time
    )
    timeline_bypass_enabled = _is_timeline_bypass_enabled(state.thread, adapter=adapter)
    if request.offset_ms > plausible_offset_ms and not timeline_bypass_enabled:
        raise InteractiveLessonValidationError(MSG_PAUSE_AHEAD_OF_PROGRESS)

    _set_last_known_offset_ms(state, request.offset_ms)
    await _append_interaction(
        session,
        state,
        adapter=adapter,
        actor_user_id=actor_user_id,
        event_type=event_type,
        offset_ms=request.offset_ms,
        idempotency_key=request.idempotency_key,
    )


async def _handle_seeked(
    session: AsyncSession,
    state: LessonState,
    actor_user_id: int,
    request: schemas.InteractiveLessonSeekedRequest,
    *,
    adapter: InteractiveLessonAdapter,
    event_type: schemas.InteractiveLessonInteractionEventType,
    current_time: datetime,
) -> None:
    timeline_bypass_enabled = _is_timeline_bypass_enabled(state.thread, adapter=adapter)
    if not timeline_bypass_enabled:
        _require_playing_state_for_playback_event(state, adapter=adapter)
    plausible_offset_ms = await get_plausible_playback_offset_ms(
        session, state, adapter=adapter, current_time=current_time
    )
    if request.to_offset_ms > plausible_offset_ms and not timeline_bypass_enabled:
        raise InteractiveLessonValidationError(MSG_JUMP_AHEAD_BLOCKED)

    _set_seek_offset_ms(
        state,
        from_offset_ms=request.from_offset_ms,
        to_offset_ms=request.to_offset_ms,
        plausible_offset_ms=plausible_offset_ms,
    )
    state_enum = _state_enum(adapter)
    if timeline_bypass_enabled and state.state != state_enum.COMPLETED:
        await _reset_question_queue_for_offset(
            session, state, request.to_offset_ms, adapter=adapter
        )
        state.state = state_enum.PLAYING
    await _append_interaction(
        session,
        state,
        adapter=adapter,
        actor_user_id=actor_user_id,
        event_type=event_type,
        from_offset_ms=request.from_offset_ms,
        to_offset_ms=request.to_offset_ms,
        idempotency_key=request.idempotency_key,
    )


async def _handle_ended(
    session: AsyncSession,
    state: LessonState,
    actor_user_id: int,
    request: schemas.InteractiveLessonEndedRequest,
    *,
    adapter: InteractiveLessonAdapter,
    event_type: schemas.InteractiveLessonInteractionEventType,
    current_time: datetime,
) -> None:
    _require_playing_state_for_playback_event(state, adapter=adapter)
    plausible_offset_ms = await get_plausible_playback_offset_ms(
        session, state, adapter=adapter, current_time=current_time
    )
    timeline_bypass_enabled = _is_timeline_bypass_enabled(state.thread, adapter=adapter)
    if request.offset_ms > plausible_offset_ms and not timeline_bypass_enabled:
        raise InteractiveLessonValidationError(MSG_COMPLETE_FROM_SPOT_BLOCKED)

    _set_last_known_offset_ms(state, request.offset_ms)
    await _append_interaction(
        session,
        state,
        adapter=adapter,
        actor_user_id=actor_user_id,
        event_type=event_type,
        offset_ms=request.offset_ms,
        idempotency_key=request.idempotency_key,
    )

    state_enum = _state_enum(adapter)
    if state.state == state_enum.COMPLETED:
        return

    if state.current_question_id is None:
        state.state = state_enum.COMPLETED
        await _append_interaction(
            session,
            state,
            adapter=adapter,
            actor_user_id=actor_user_id,
            event_type=schemas.InteractiveLessonInteractionEventType.SESSION_COMPLETED,
        )


_INTERACTION_HANDLERS: dict[
    type[schemas.InteractiveLessonInteractionRequestBase], InteractionHandler
] = {
    schemas.InteractiveLessonQuestionPresentedRequest: _handle_question_presented,
    schemas.InteractiveLessonAnswerSubmittedRequest: _handle_answer_submitted,
    schemas.InteractiveLessonResumedRequest: _handle_resumed,
    schemas.InteractiveLessonPausedRequest: _handle_paused,
    schemas.InteractiveLessonSeekedRequest: _handle_seeked,
    schemas.InteractiveLessonEndedRequest: _handle_ended,
}


async def process_interaction(
    session: AsyncSession,
    thread_id: int,
    actor_user_id: int,
    request: schemas.InteractiveLessonInteractionRequest,
    *,
    adapter: InteractiveLessonAdapter,
    nowfn: NowFn | None = None,
) -> schemas.InteractiveLessonSession:
    state = await get_or_initialize_thread_state(
        session, thread_id, adapter=adapter, for_update=True
    )
    current_time = nowfn() if nowfn is not None else utcnow()
    if not adapter.matches_assistant(state.thread):
        raise InteractiveLessonConflictError(MSG_LESSON_UPDATED)

    _require_controller(
        state,
        actor_user_id=actor_user_id,
        controller_session_id=request.controller_session_id,
        now=current_time,
    )

    existing = await adapter.interaction_model.get_by_thread_and_idempotency_key(
        session, thread_id, request.idempotency_key
    )
    if existing is not None:
        latest_interaction_at = (
            await adapter.interaction_model.get_latest_created_by_thread_id(
                session, state.thread_id
            )
        )
        return await _build_interactive_lesson_session_for_state(
            state,
            adapter=adapter,
            latest_interaction_at=latest_interaction_at,
            request_controller_session_id=request.controller_session_id,
            request_actor_user_id=actor_user_id,
            now=current_time,
        )

    if request.expected_state_version != state.version:
        raise _conflict(
            detail=MSG_REFRESH_AND_RETRY,
        )

    event_type = schemas.InteractiveLessonInteractionEventType(request.type)
    handler = _INTERACTION_HANDLERS.get(type(request))
    if handler is None:
        raise TypeError(
            f"Unhandled interactive lesson interaction request type: {type(request).__name__}"
        )
    await handler(
        session,
        state,
        actor_user_id,
        request,
        adapter=adapter,
        event_type=event_type,
        current_time=current_time,
    )

    state.version += 1
    _renew_controller_lease(
        state,
        actor_user_id,
        request.controller_session_id,
        now=current_time,
    )
    await session.flush()
    latest_interaction_at = (
        await adapter.interaction_model.get_latest_created_by_thread_id(
            session, state.thread_id
        )
    )

    return await _build_interactive_lesson_session_for_state(
        state,
        adapter=adapter,
        latest_interaction_at=latest_interaction_at,
        request_controller_session_id=request.controller_session_id,
        request_actor_user_id=actor_user_id,
        now=current_time,
    )
