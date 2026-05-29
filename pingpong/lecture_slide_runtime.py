from datetime import datetime
from typing import Any, cast

from sqlalchemy.ext.asyncio import AsyncSession

import pingpong.interactive_lesson_runtime as interactive_lesson_runtime
import pingpong.models as models
import pingpong.schemas as schemas
from pingpong.now import NowFn

CONTROLLER_SESSION_HEADER = "x-lecture-slide-controller-session"
CONTROLLER_LEASE_DURATION_MS = interactive_lesson_runtime.CONTROLLER_LEASE_DURATION_MS
ERROR_CONTROLLER_LEASE_EXPIRED = (
    interactive_lesson_runtime.ERROR_CONTROLLER_LEASE_EXPIRED
)
PLAYBACK_PROGRESS_TOLERANCE_MS = (
    interactive_lesson_runtime.PLAYBACK_PROGRESS_TOLERANCE_MS
)

MSG_STALE_PAGE = interactive_lesson_runtime.MSG_STALE_PAGE
MSG_TAB_DISCONNECTED = interactive_lesson_runtime.MSG_TAB_DISCONNECTED
MSG_LESSON_UPDATED = interactive_lesson_runtime.MSG_LESSON_UPDATED
MSG_QUESTION_ALREADY_CLOSED = interactive_lesson_runtime.MSG_QUESTION_ALREADY_CLOSED
MSG_REFRESH_AND_RETRY = interactive_lesson_runtime.MSG_REFRESH_AND_RETRY

LectureSlideRuntimeError = interactive_lesson_runtime.InteractiveLessonRuntimeError
LectureSlideNotFoundError = interactive_lesson_runtime.InteractiveLessonNotFoundError
LectureSlideValidationError = (
    interactive_lesson_runtime.InteractiveLessonValidationError
)
LectureSlideConflictError = interactive_lesson_runtime.InteractiveLessonConflictError


class LectureSlideAdapter:
    state_model: Any = models.LectureSlideThreadState
    interaction_model: Any = models.LectureSlideInteraction

    async def get_thread_with_context(
        self, session: AsyncSession, thread_id: int
    ) -> models.Thread | None:
        return await models.Thread.get_by_id_with_lecture_slide_context(
            session, thread_id
        )

    def get_asset(self, thread: models.Thread) -> models.LectureSlideDeck | None:
        return thread.lecture_slide_deck

    def get_questions(
        self, thread: models.Thread
    ) -> list[interactive_lesson_runtime.LessonQuestion]:
        if thread.lecture_slide_deck is None:
            return []
        return cast(
            list[interactive_lesson_runtime.LessonQuestion],
            thread.lecture_slide_deck.questions,
        )

    def get_state(
        self, thread: models.Thread
    ) -> interactive_lesson_runtime.LessonState | None:
        return cast(
            interactive_lesson_runtime.LessonState | None, thread.lecture_slide_state
        )

    def set_state(
        self, thread: models.Thread, state: interactive_lesson_runtime.LessonState
    ) -> None:
        thread.lecture_slide_state = cast(models.LectureSlideThreadState, state)

    def matches_assistant(self, thread: models.Thread) -> bool:
        return lecture_slide_matches_assistant(thread)

    def to_storage_event(
        self, event_type: schemas.InteractiveLessonInteractionEventType
    ) -> schemas.InteractiveLessonInteractionEventType:
        return event_type


_SLIDE_ADAPTER = LectureSlideAdapter()


def has_active_controller(
    state: models.LectureSlideThreadState, now: datetime | None = None
) -> bool:
    return interactive_lesson_runtime.has_active_controller(state, now)


def lecture_slide_matches_assistant(thread: models.Thread | None) -> bool:
    if not thread or not thread.assistant_id or not thread.lecture_slide_deck_id:
        return False
    assistant = thread.assistant
    return bool(
        assistant
        and assistant.lecture_slide_deck_id is not None
        and assistant.lecture_slide_deck_id == thread.lecture_slide_deck_id
    )


def narration_allowed_for_thread_state(
    thread: models.Thread, narration_id: int
) -> bool:
    state = thread.lecture_slide_state
    if state is None:
        return False

    current_question = interactive_lesson_runtime._get_current_question(
        thread, state, adapter=_SLIDE_ADAPTER
    )
    if (
        state.state
        in {
            schemas.InteractiveLessonSessionState.PLAYING,
            schemas.InteractiveLessonSessionState.AWAITING_ANSWER,
        }
        and current_question is not None
        and current_question.intro_narration_id == narration_id
    ):
        return True

    return bool(
        state.state == schemas.InteractiveLessonSessionState.AWAITING_POST_ANSWER_RESUME
        and state.active_option is not None
        and state.active_option.post_narration_id == narration_id
    )


def build_lecture_slide_session(
    thread: models.Thread,
    state: models.LectureSlideThreadState,
    *,
    furthest_offset_ms: int | None = None,
    latest_interaction_at: datetime | None = None,
    request_controller_session_id: str | None = None,
    request_actor_user_id: int | None = None,
    now: datetime | None = None,
) -> schemas.InteractiveLessonSession:
    return interactive_lesson_runtime.build_interactive_lesson_session(
        thread,
        state,
        adapter=_SLIDE_ADAPTER,
        furthest_offset_ms=furthest_offset_ms,
        latest_interaction_at=latest_interaction_at,
        request_controller_session_id=request_controller_session_id,
        request_actor_user_id=request_actor_user_id,
        now=now,
    )


async def _build_lecture_slide_session_for_state(
    state: models.LectureSlideThreadState,
    *,
    latest_interaction_at: datetime | None = None,
    request_controller_session_id: str | None = None,
    request_actor_user_id: int | None = None,
    now: datetime | None = None,
) -> schemas.InteractiveLessonSession:
    return await interactive_lesson_runtime._build_interactive_lesson_session_for_state(
        state,
        adapter=_SLIDE_ADAPTER,
        latest_interaction_at=latest_interaction_at,
        request_controller_session_id=request_controller_session_id,
        request_actor_user_id=request_actor_user_id,
        now=now,
    )


def _get_unlocked_offset_ms(state: models.LectureSlideThreadState) -> int:
    return interactive_lesson_runtime._get_unlocked_offset_ms(state)


async def get_plausible_playback_offset_ms(
    session: AsyncSession,
    state: models.LectureSlideThreadState,
    *,
    current_time: datetime,
) -> int:
    return await interactive_lesson_runtime.get_plausible_playback_offset_ms(
        session,
        state,
        adapter=_SLIDE_ADAPTER,
        current_time=current_time,
    )


async def get_thread_session(
    session: AsyncSession,
    thread_id: int,
    *,
    request_controller_session_id: str | None = None,
    request_actor_user_id: int | None = None,
    nowfn: NowFn | None = None,
) -> schemas.InteractiveLessonSession | None:
    return await interactive_lesson_runtime.get_thread_session(
        session,
        thread_id,
        adapter=_SLIDE_ADAPTER,
        request_controller_session_id=request_controller_session_id,
        request_actor_user_id=request_actor_user_id,
        nowfn=nowfn,
    )


async def initialize_thread_state(
    session: AsyncSession, thread_id: int
) -> models.LectureSlideThreadState:
    return cast(
        models.LectureSlideThreadState,
        await interactive_lesson_runtime.initialize_thread_state(
            session, thread_id, adapter=_SLIDE_ADAPTER
        ),
    )


async def get_or_initialize_thread_state(
    session: AsyncSession,
    thread_id: int,
    *,
    for_update: bool = False,
) -> models.LectureSlideThreadState:
    return cast(
        models.LectureSlideThreadState,
        await interactive_lesson_runtime.get_or_initialize_thread_state(
            session, thread_id, adapter=_SLIDE_ADAPTER, for_update=for_update
        ),
    )


async def _append_interaction(
    session: AsyncSession,
    state: models.LectureSlideThreadState,
    *,
    actor_user_id: int | None,
    event_type: schemas.InteractiveLessonInteractionEventType,
    question_id: int | None = None,
    option_id: int | None = None,
    offset_ms: int | None = None,
    from_offset_ms: int | None = None,
    to_offset_ms: int | None = None,
    idempotency_key: str | None = None,
) -> models.LectureSlideInteraction:
    return cast(
        models.LectureSlideInteraction,
        await interactive_lesson_runtime._append_interaction(
            session,
            state,
            adapter=_SLIDE_ADAPTER,
            actor_user_id=actor_user_id,
            event_type=event_type,
            question_id=question_id,
            option_id=option_id,
            offset_ms=offset_ms,
            from_offset_ms=from_offset_ms,
            to_offset_ms=to_offset_ms,
            idempotency_key=idempotency_key,
        ),
    )


async def acquire_control(
    session: AsyncSession,
    thread_id: int,
    actor_user_id: int,
    *,
    nowfn: NowFn | None = None,
) -> tuple[str, schemas.InteractiveLessonSession]:
    return await interactive_lesson_runtime.acquire_control(
        session,
        thread_id,
        actor_user_id,
        adapter=_SLIDE_ADAPTER,
        nowfn=nowfn,
    )


async def release_control(
    session: AsyncSession,
    thread_id: int,
    actor_user_id: int,
    controller_session_id: str,
    *,
    nowfn: NowFn | None = None,
) -> schemas.InteractiveLessonSession:
    return await interactive_lesson_runtime.release_control(
        session,
        thread_id,
        actor_user_id,
        controller_session_id,
        adapter=_SLIDE_ADAPTER,
        nowfn=nowfn,
    )


async def renew_control(
    session: AsyncSession,
    thread_id: int,
    actor_user_id: int,
    controller_session_id: str,
    *,
    nowfn: NowFn | None = None,
) -> datetime:
    return await interactive_lesson_runtime.renew_control(
        session,
        thread_id,
        actor_user_id,
        controller_session_id,
        adapter=_SLIDE_ADAPTER,
        nowfn=nowfn,
    )


async def process_interaction(
    session: AsyncSession,
    thread_id: int,
    actor_user_id: int,
    request: schemas.InteractiveLessonInteractionRequest,
    *,
    nowfn: NowFn | None = None,
) -> schemas.InteractiveLessonSession:
    return await interactive_lesson_runtime.process_interaction(
        session,
        thread_id,
        actor_user_id,
        request,
        adapter=_SLIDE_ADAPTER,
        nowfn=nowfn,
    )
