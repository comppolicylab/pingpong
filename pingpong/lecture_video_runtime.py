from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta, timezone

import uuid_utils as uuid
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

import pingpong.models as models
import pingpong.schemas as schemas
from pingpong.now import NowFn, utcnow

CONTROLLER_SESSION_HEADER = "x-lecture-video-controller-session"
CONTROLLER_LEASE_DURATION = timedelta(seconds=30)
PLAYBACK_PROGRESS_TOLERANCE_MS = 2_000


class LectureVideoRuntimeError(Exception):
    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


class LectureVideoNotFoundError(LectureVideoRuntimeError):
    pass


class LectureVideoValidationError(LectureVideoRuntimeError):
    pass


class LectureVideoConflictError(LectureVideoRuntimeError):
    pass


def has_active_controller(
    state: models.LectureVideoThreadState, now: datetime | None = None
) -> bool:
    current_time = now or utcnow()
    lease_expires_at = state.normalized_controller_lease_expires_at
    return bool(
        state.controller_session_id
        and state.controller_user_id is not None
        and lease_expires_at is not None
        and lease_expires_at > current_time
    )


def lecture_video_matches_assistant(thread: models.Thread | None) -> bool:
    if not thread or not thread.assistant_id or not thread.lecture_video_id:
        return False
    assistant = thread.assistant
    return bool(
        assistant
        and assistant.lecture_video_id is not None
        and assistant.lecture_video_id == thread.lecture_video_id
    )


def _narration_id(
    narration: models.LectureVideoNarration | None,
) -> int | None:
    if (
        narration is None
        or narration.status != schemas.LectureVideoNarrationStatus.READY
        or narration.stored_object is None
    ):
        return None
    return narration.id


def narration_allowed_for_thread_state(
    thread: models.Thread, narration_id: int
) -> bool:
    state = thread.lecture_video_state
    if state is None:
        return False

    current_question = _get_current_question(thread, state)
    if (
        state.state
        in {
            schemas.LectureVideoSessionState.PLAYING,
            schemas.LectureVideoSessionState.AWAITING_ANSWER,
        }
        and current_question is not None
        and current_question.intro_narration_id == narration_id
    ):
        return True

    return bool(
        state.state == schemas.LectureVideoSessionState.AWAITING_POST_ANSWER_RESUME
        and state.active_option is not None
        and state.active_option.post_narration_id == narration_id
    )


def _question_prompt(
    question: models.LectureVideoQuestion,
) -> schemas.LectureVideoQuestionPrompt:
    return schemas.LectureVideoQuestionPrompt(
        id=question.id,
        type=question.question_type,
        question_text=question.question_text,
        intro_text=question.intro_text,
        stop_offset_ms=question.stop_offset_ms,
        intro_narration_id=_narration_id(question.intro_narration),
        options=[
            schemas.LectureVideoOptionPrompt(
                id=option.id,
                option_text=option.option_text,
            )
            for option in sorted(question.options, key=lambda item: item.position)
        ],
    )


def _get_current_question(
    thread: models.Thread, state: models.LectureVideoThreadState
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
    thread: models.Thread, current_question: models.LectureVideoQuestion | None
) -> models.LectureVideoQuestion | None:
    if not thread.lecture_video or current_question is None:
        return None
    next_position = current_question.position + 1
    for question in thread.lecture_video.questions:
        if question.position == next_position:
            return question
    return None


def _build_continuation(
    thread: models.Thread, state: models.LectureVideoThreadState
) -> schemas.LectureVideoContinuation | None:
    if (
        state.state != schemas.LectureVideoSessionState.AWAITING_POST_ANSWER_RESUME
        or state.active_option is None
    ):
        return None

    current_question = _get_current_question(thread, state)
    next_question = _get_next_question(thread, current_question)

    correct_option_id: int | None = None
    if current_question is not None and thread.lecture_video:
        for q in thread.lecture_video.questions:
            if q.id == current_question.id and q.correct_option is not None:
                correct_option_id = q.correct_option.id
                break

    return schemas.LectureVideoContinuation(
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


def build_lecture_video_session(
    thread: models.Thread,
    state: models.LectureVideoThreadState,
    *,
    furthest_offset_ms: int | None = None,
    latest_interaction_at: datetime | None = None,
    request_controller_session_id: str | None = None,
    request_actor_user_id: int | None = None,
    now: datetime | None = None,
) -> schemas.LectureVideoSession:
    current_time = now or utcnow()
    current_question = _get_current_question(thread, state)
    active_controller = has_active_controller(state, current_time)
    request_has_control = bool(
        active_controller
        and request_controller_session_id
        and request_controller_session_id == state.controller_session_id
        and request_actor_user_id is not None
        and request_actor_user_id == state.controller_user_id
    )

    return schemas.LectureVideoSession(
        state=state.state,
        lecture_video_chat_available=bool(
            thread.lecture_video and thread.lecture_video.lecture_video_chat_available
        ),
        last_known_offset_ms=state.last_known_offset_ms,
        furthest_offset_ms=furthest_offset_ms,
        latest_interaction_at=latest_interaction_at,
        current_question=(
            _question_prompt(current_question)
            if request_has_control
            and current_question is not None
            and state.state != schemas.LectureVideoSessionState.COMPLETED
            else None
        ),
        current_continuation=(
            _build_continuation(thread, state) if request_has_control else None
        ),
        state_version=state.version,
        controller=schemas.LectureVideoSessionController(
            has_control=request_has_control,
            has_active_controller=active_controller,
            lease_expires_at=(
                state.normalized_controller_lease_expires_at
                if active_controller
                else None
            ),
        ),
    )


async def _build_lecture_video_session_for_state(
    state: models.LectureVideoThreadState,
    *,
    latest_interaction_at: datetime | None = None,
    request_controller_session_id: str | None = None,
    request_actor_user_id: int | None = None,
    now: datetime | None = None,
) -> schemas.LectureVideoSession:
    furthest_offset_ms = _get_unlocked_offset_ms(state)
    return build_lecture_video_session(
        state.thread,
        state,
        furthest_offset_ms=furthest_offset_ms,
        latest_interaction_at=latest_interaction_at,
        request_controller_session_id=request_controller_session_id,
        request_actor_user_id=request_actor_user_id,
        now=now,
    )


def _get_unlocked_offset_ms(state: models.LectureVideoThreadState) -> int:
    return max(state.last_known_offset_ms, state.furthest_offset_ms)


def _set_last_known_offset_ms(
    state: models.LectureVideoThreadState, offset_ms: int
) -> None:
    state.last_known_offset_ms = offset_ms
    state.furthest_offset_ms = max(state.furthest_offset_ms, offset_ms)


def _set_seek_offset_ms(
    state: models.LectureVideoThreadState, *, from_offset_ms: int, to_offset_ms: int
) -> None:
    state.last_known_offset_ms = to_offset_ms
    state.furthest_offset_ms = max(state.furthest_offset_ms, to_offset_ms)


def _normalize_interaction_time(timestamp: datetime | None) -> datetime | None:
    if timestamp is None:
        return None
    if timestamp.tzinfo is None:
        return timestamp.replace(tzinfo=timezone.utc)
    return timestamp


async def _get_plausible_playback_offset_ms(
    session: AsyncSession,
    state: models.LectureVideoThreadState,
    *,
    current_time: datetime,
) -> int:
    unlocked_offset_ms = _get_unlocked_offset_ms(state)
    if state.state != schemas.LectureVideoSessionState.PLAYING:
        return unlocked_offset_ms

    latest_interaction_at = _normalize_interaction_time(
        await models.LectureVideoInteraction.get_latest_created_by_thread_id(
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
    request_controller_session_id: str | None = None,
    request_actor_user_id: int | None = None,
    nowfn: NowFn | None = None,
) -> schemas.LectureVideoSession | None:
    thread = await models.Thread.get_by_id_with_lecture_video_context(
        session, thread_id
    )
    if (
        not thread
        or thread.interaction_mode != schemas.InteractionMode.LECTURE_VIDEO
        or thread.lecture_video is None
    ):
        return None
    state = thread.lecture_video_state or await get_or_initialize_thread_state(
        session, thread_id
    )
    latest_interaction_at = (
        await models.LectureVideoInteraction.get_latest_created_by_thread_id(
            session, thread.id
        )
    )
    return await _build_lecture_video_session_for_state(
        state,
        latest_interaction_at=latest_interaction_at,
        request_controller_session_id=request_controller_session_id,
        request_actor_user_id=request_actor_user_id,
        now=nowfn() if nowfn is not None else None,
    )


async def initialize_thread_state(
    session: AsyncSession, thread_id: int
) -> models.LectureVideoThreadState:
    thread = await models.Thread.get_by_id_with_lecture_video_context(
        session, thread_id
    )
    if (
        thread is None
        or thread.interaction_mode != schemas.InteractionMode.LECTURE_VIDEO
        or thread.lecture_video is None
    ):
        raise LectureVideoNotFoundError("Lecture video thread not found.")

    first_question = next(
        iter(sorted(thread.lecture_video.questions, key=lambda item: item.position)),
        None,
    )

    state = await models.LectureVideoThreadState.create(
        session,
        {
            "thread_id": thread.id,
            "state": (
                schemas.LectureVideoSessionState.PLAYING
                if first_question is not None
                else schemas.LectureVideoSessionState.COMPLETED
            ),
            "current_question_id": first_question.id
            if first_question is not None
            else None,
            "last_known_offset_ms": 0,
            "furthest_offset_ms": 0,
            "last_chat_context_end_ms": 0,
            "version": 1,
        },
    )
    await models.LectureVideoInteraction.create(
        session,
        {
            "thread_id": thread.id,
            "event_index": 1,
            "event_type": schemas.LectureVideoInteractionEventType.SESSION_INITIALIZED,
            "idempotency_key": (
                models.LectureVideoInteraction.generate_idempotency_key()
            ),
        },
    )
    return state


async def get_or_initialize_thread_state(
    session: AsyncSession,
    thread_id: int,
    *,
    for_update: bool = False,
) -> models.LectureVideoThreadState:
    state = await models.LectureVideoThreadState.get_by_thread_id_with_context(
        session, thread_id, for_update=for_update
    )
    if state is not None:
        state.thread.lecture_video_state = state
        return _require_state(state)

    thread = await models.Thread.get_by_id_with_lecture_video_context(
        session, thread_id
    )
    if (
        thread is None
        or thread.interaction_mode != schemas.InteractionMode.LECTURE_VIDEO
        or thread.lecture_video is None
    ):
        raise LectureVideoNotFoundError("Lecture video thread not found.")

    try:
        async with session.begin_nested():
            await initialize_thread_state(session, thread_id)
    except IntegrityError:
        # Another request created the runtime state first. Re-read it below.
        pass

    state = await models.LectureVideoThreadState.get_by_thread_id_with_context(
        session, thread_id, for_update=for_update
    )
    if state is not None:
        state.thread.lecture_video_state = state
    return _require_state(state)


def _require_state(
    state: models.LectureVideoThreadState | None,
) -> models.LectureVideoThreadState:
    if state is None:
        raise LectureVideoNotFoundError("Lecture video runtime not found.")
    if (
        state.thread.interaction_mode != schemas.InteractionMode.LECTURE_VIDEO
        or state.thread.lecture_video is None
    ):
        raise LectureVideoNotFoundError("Lecture video thread not found.")
    return state


def _conflict(
    *,
    detail: str,
) -> LectureVideoConflictError:
    return LectureVideoConflictError(detail)


def _require_controller(
    state: models.LectureVideoThreadState,
    *,
    actor_user_id: int,
    controller_session_id: str,
    now: datetime | None = None,
) -> None:
    if not has_active_controller(state, now):
        raise _conflict(
            detail="Lecture video control has expired. Acquire control again.",
        )
    if state.controller_user_id != actor_user_id:
        raise _conflict(
            detail="Another participant currently controls this lecture video.",
        )
    if state.controller_session_id != controller_session_id:
        raise _conflict(
            detail="This browser window no longer controls the lecture video.",
        )


async def _append_interaction(
    session: AsyncSession,
    state: models.LectureVideoThreadState,
    *,
    actor_user_id: int | None,
    event_type: schemas.LectureVideoInteractionEventType,
    question_id: int | None = None,
    option_id: int | None = None,
    offset_ms: int | None = None,
    from_offset_ms: int | None = None,
    to_offset_ms: int | None = None,
    idempotency_key: str | None = None,
) -> models.LectureVideoInteraction:
    # get_next_event_index() is a read-then-write sequence. Callers must hold the
    # LectureVideoThreadState row lock acquired via get_or_initialize_thread_state(
    # ..., for_update=True) so concurrent requests for the same thread serialize.
    if not getattr(state, "_locked_for_interaction_append", False):
        raise RuntimeError(
            "LectureVideoThreadState must be loaded with FOR UPDATE before appending "
            "lecture video interactions."
        )
    event_index = await models.LectureVideoInteraction.get_next_event_index(
        session, state.thread_id
    )
    effective_idempotency_key = (
        idempotency_key
        if isinstance(idempotency_key, str) and idempotency_key.strip()
        else models.LectureVideoInteraction.generate_idempotency_key()
    )
    return await models.LectureVideoInteraction.create(
        session,
        {
            "thread_id": state.thread_id,
            "event_index": event_index,
            "actor_user_id": actor_user_id,
            "event_type": event_type,
            "question_id": question_id,
            "option_id": option_id,
            "offset_ms": offset_ms,
            "from_offset_ms": from_offset_ms,
            "to_offset_ms": to_offset_ms,
            "idempotency_key": effective_idempotency_key,
        },
    )


def _renew_controller_lease(
    state: models.LectureVideoThreadState,
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
    nowfn: NowFn | None = None,
) -> tuple[str, schemas.LectureVideoSession]:
    state = await get_or_initialize_thread_state(session, thread_id, for_update=True)
    current_time = nowfn() if nowfn is not None else utcnow()
    if not lecture_video_matches_assistant(state.thread):
        raise LectureVideoConflictError(
            "This thread's lecture video no longer matches the assistant configuration."
        )

    if (
        has_active_controller(state, current_time)
        and state.controller_user_id != actor_user_id
    ):
        raise _conflict(
            detail="Another participant currently controls this lecture video.",
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
        await models.LectureVideoInteraction.get_latest_created_by_thread_id(
            session, state.thread_id
        )
    )

    return (
        controller_session_id,
        await _build_lecture_video_session_for_state(
            state,
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
    nowfn: NowFn | None = None,
) -> schemas.LectureVideoSession:
    state = await get_or_initialize_thread_state(session, thread_id, for_update=True)
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
        await models.LectureVideoInteraction.get_latest_created_by_thread_id(
            session, state.thread_id
        )
    )
    return await _build_lecture_video_session_for_state(
        state,
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
    nowfn: NowFn | None = None,
) -> datetime:
    state = await get_or_initialize_thread_state(session, thread_id, for_update=True)
    current_time = nowfn() if nowfn is not None else utcnow()
    if not lecture_video_matches_assistant(state.thread):
        raise LectureVideoConflictError(
            "This thread's lecture video no longer matches the assistant configuration."
        )

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
    question: models.LectureVideoQuestion, option_id: int
) -> models.LectureVideoQuestionOption | None:
    for option in question.options:
        if option.id == option_id:
            return option
    return None


InteractionHandler = Callable[..., Awaitable[None]]


async def _handle_question_presented(
    session: AsyncSession,
    state: models.LectureVideoThreadState,
    actor_user_id: int,
    request: schemas.LectureVideoQuestionPresentedRequest,
    *,
    event_type: schemas.LectureVideoInteractionEventType,
    current_time: datetime,
) -> None:
    current_question = _get_current_question(state.thread, state)
    if (
        state.state != schemas.LectureVideoSessionState.PLAYING
        or current_question is None
        or current_question.id != request.question_id
    ):
        raise _conflict(
            detail="This question is no longer active.",
        )

    if request.offset_ms != current_question.stop_offset_ms:
        raise LectureVideoValidationError(
            "Question presentation must occur at the configured stop offset."
        )

    plausible_offset_ms = await _get_plausible_playback_offset_ms(
        session, state, current_time=current_time
    )
    if request.offset_ms > plausible_offset_ms:
        raise LectureVideoValidationError(
            "Presenting a question past your unlocked progress is not allowed in this lecture video."
        )

    state.state = schemas.LectureVideoSessionState.AWAITING_ANSWER
    _set_last_known_offset_ms(state, request.offset_ms)
    await _append_interaction(
        session,
        state,
        actor_user_id=actor_user_id,
        event_type=event_type,
        question_id=request.question_id,
        offset_ms=request.offset_ms,
        idempotency_key=request.idempotency_key,
    )


async def _handle_answer_submitted(
    session: AsyncSession,
    state: models.LectureVideoThreadState,
    actor_user_id: int,
    request: schemas.LectureVideoAnswerSubmittedRequest,
    *,
    event_type: schemas.LectureVideoInteractionEventType,
    current_time: datetime,
) -> None:
    current_question = _get_current_question(state.thread, state)
    if (
        state.state != schemas.LectureVideoSessionState.AWAITING_ANSWER
        or current_question is None
        or current_question.id != request.question_id
    ):
        raise _conflict(
            detail="This question is no longer accepting answers.",
        )

    option = _find_option_for_question(current_question, request.option_id)
    if option is None:
        raise LectureVideoValidationError(
            "That option does not belong to this question."
        )

    state.state = schemas.LectureVideoSessionState.AWAITING_POST_ANSWER_RESUME
    state.active_option = option
    await _append_interaction(
        session,
        state,
        actor_user_id=actor_user_id,
        event_type=event_type,
        question_id=request.question_id,
        option_id=option.id,
        idempotency_key=request.idempotency_key,
    )


async def _handle_resumed(
    session: AsyncSession,
    state: models.LectureVideoThreadState,
    actor_user_id: int,
    request: schemas.LectureVideoResumedRequest,
    *,
    event_type: schemas.LectureVideoInteractionEventType,
    current_time: datetime,
) -> None:
    if state.state == schemas.LectureVideoSessionState.PLAYING:
        plausible_offset_ms = await _get_plausible_playback_offset_ms(
            session, state, current_time=current_time
        )
        if request.offset_ms > plausible_offset_ms:
            raise LectureVideoValidationError(
                "Resuming past your unlocked progress is not allowed in this lecture video."
            )
        _set_last_known_offset_ms(state, request.offset_ms)
        await _append_interaction(
            session,
            state,
            actor_user_id=actor_user_id,
            event_type=event_type,
            offset_ms=request.offset_ms,
            idempotency_key=request.idempotency_key,
        )
        return

    current_question = _get_current_question(state.thread, state)
    active_option = state.active_option
    if (
        state.state != schemas.LectureVideoSessionState.AWAITING_POST_ANSWER_RESUME
        or active_option is None
        or request.offset_ms != active_option.continue_offset_ms
    ):
        raise _conflict(
            detail="The lecture video cannot resume from this state.",
        )

    next_question = _get_next_question(state.thread, current_question)
    _set_last_known_offset_ms(state, request.offset_ms)
    state.active_option_id = None
    state.active_option = None
    if next_question is None:
        state.current_question_id = None
        state.current_question = None
    else:
        state.current_question_id = next_question.id
        state.current_question = next_question
    state.state = schemas.LectureVideoSessionState.PLAYING

    await _append_interaction(
        session,
        state,
        actor_user_id=actor_user_id,
        event_type=event_type,
        offset_ms=request.offset_ms,
        idempotency_key=request.idempotency_key,
    )


def _require_playing_state_for_playback_event(
    state: models.LectureVideoThreadState,
) -> None:
    if state.state == schemas.LectureVideoSessionState.COMPLETED:
        raise _conflict(
            detail="Session is already completed.",
        )
    if state.state != schemas.LectureVideoSessionState.PLAYING:
        raise _conflict(
            detail="The lecture video cannot process playback events right now.",
        )


async def _handle_paused(
    session: AsyncSession,
    state: models.LectureVideoThreadState,
    actor_user_id: int,
    request: schemas.LectureVideoPausedRequest,
    *,
    event_type: schemas.LectureVideoInteractionEventType,
    current_time: datetime,
) -> None:
    _require_playing_state_for_playback_event(state)
    plausible_offset_ms = await _get_plausible_playback_offset_ms(
        session, state, current_time=current_time
    )
    if request.offset_ms > plausible_offset_ms:
        raise LectureVideoValidationError(
            "Pausing past your unlocked progress is not allowed in this lecture video."
        )

    _set_last_known_offset_ms(state, request.offset_ms)
    await _append_interaction(
        session,
        state,
        actor_user_id=actor_user_id,
        event_type=event_type,
        offset_ms=request.offset_ms,
        idempotency_key=request.idempotency_key,
    )


async def _handle_seeked(
    session: AsyncSession,
    state: models.LectureVideoThreadState,
    actor_user_id: int,
    request: schemas.LectureVideoSeekedRequest,
    *,
    event_type: schemas.LectureVideoInteractionEventType,
    current_time: datetime,
) -> None:
    _require_playing_state_for_playback_event(state)
    plausible_offset_ms = await _get_plausible_playback_offset_ms(
        session, state, current_time=current_time
    )
    if request.to_offset_ms > plausible_offset_ms:
        raise LectureVideoValidationError(
            "Seeking past your unlocked progress is not allowed in this lecture video."
        )

    _set_seek_offset_ms(
        state,
        from_offset_ms=request.from_offset_ms,
        to_offset_ms=request.to_offset_ms,
    )
    await _append_interaction(
        session,
        state,
        actor_user_id=actor_user_id,
        event_type=event_type,
        from_offset_ms=request.from_offset_ms,
        to_offset_ms=request.to_offset_ms,
        idempotency_key=request.idempotency_key,
    )


async def _handle_ended(
    session: AsyncSession,
    state: models.LectureVideoThreadState,
    actor_user_id: int,
    request: schemas.LectureVideoEndedRequest,
    *,
    event_type: schemas.LectureVideoInteractionEventType,
    current_time: datetime,
) -> None:
    _require_playing_state_for_playback_event(state)
    plausible_offset_ms = await _get_plausible_playback_offset_ms(
        session, state, current_time=current_time
    )
    if request.offset_ms > plausible_offset_ms:
        raise LectureVideoValidationError(
            "Ending past your unlocked progress is not allowed in this lecture video."
        )

    _set_last_known_offset_ms(state, request.offset_ms)
    await _append_interaction(
        session,
        state,
        actor_user_id=actor_user_id,
        event_type=event_type,
        offset_ms=request.offset_ms,
        idempotency_key=request.idempotency_key,
    )

    if state.current_question_id is None:
        state.state = schemas.LectureVideoSessionState.COMPLETED
        await _append_interaction(
            session,
            state,
            actor_user_id=actor_user_id,
            event_type=schemas.LectureVideoInteractionEventType.SESSION_COMPLETED,
        )


_INTERACTION_HANDLERS: dict[
    type[schemas.LectureVideoInteractionRequestBase], InteractionHandler
] = {
    schemas.LectureVideoQuestionPresentedRequest: _handle_question_presented,
    schemas.LectureVideoAnswerSubmittedRequest: _handle_answer_submitted,
    schemas.LectureVideoResumedRequest: _handle_resumed,
    schemas.LectureVideoPausedRequest: _handle_paused,
    schemas.LectureVideoSeekedRequest: _handle_seeked,
    schemas.LectureVideoEndedRequest: _handle_ended,
}


async def process_interaction(
    session: AsyncSession,
    thread_id: int,
    actor_user_id: int,
    request: schemas.LectureVideoInteractionRequest,
    *,
    nowfn: NowFn | None = None,
) -> schemas.LectureVideoSession:
    state = await get_or_initialize_thread_state(session, thread_id, for_update=True)
    current_time = nowfn() if nowfn is not None else utcnow()
    if not lecture_video_matches_assistant(state.thread):
        raise LectureVideoConflictError(
            "This thread's lecture video no longer matches the assistant configuration."
        )

    _require_controller(
        state,
        actor_user_id=actor_user_id,
        controller_session_id=request.controller_session_id,
        now=current_time,
    )

    existing = await models.LectureVideoInteraction.get_by_thread_and_idempotency_key(
        session, thread_id, request.idempotency_key
    )
    if existing is not None:
        latest_interaction_at = (
            await models.LectureVideoInteraction.get_latest_created_by_thread_id(
                session, state.thread_id
            )
        )
        return await _build_lecture_video_session_for_state(
            state,
            latest_interaction_at=latest_interaction_at,
            request_controller_session_id=request.controller_session_id,
            request_actor_user_id=actor_user_id,
            now=current_time,
        )

    if request.expected_state_version != state.version:
        raise _conflict(
            detail="Lecture video state is out of date. Refresh and try again.",
        )

    event_type = schemas.LectureVideoInteractionEventType(request.type)
    handler = _INTERACTION_HANDLERS.get(type(request))
    if handler is None:
        raise TypeError(
            f"Unhandled lecture video interaction request type: {type(request).__name__}"
        )
    await handler(
        session,
        state,
        actor_user_id,
        request,
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
        await models.LectureVideoInteraction.get_latest_created_by_thread_id(
            session, state.thread_id
        )
    )

    return await _build_lecture_video_session_for_state(
        state,
        latest_interaction_at=latest_interaction_at,
        request_controller_session_id=request.controller_session_id,
        request_actor_user_id=actor_user_id,
        now=current_time,
    )
