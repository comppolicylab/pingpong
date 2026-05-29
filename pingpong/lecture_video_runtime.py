from datetime import datetime
from typing import Any, cast

from sqlalchemy.ext.asyncio import AsyncSession

import pingpong.interactive_lesson_runtime as interactive_lesson_runtime
import pingpong.models as models
import pingpong.schemas as schemas
from pingpong.now import NowFn

CONTROLLER_SESSION_HEADER = "x-lecture-video-controller-session"
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

LectureVideoRuntimeError = interactive_lesson_runtime.InteractiveLessonRuntimeError
LectureVideoNotFoundError = interactive_lesson_runtime.InteractiveLessonNotFoundError
LectureVideoValidationError = (
    interactive_lesson_runtime.InteractiveLessonValidationError
)
LectureVideoConflictError = interactive_lesson_runtime.InteractiveLessonConflictError

_VIDEO_EVENT_TO_STORAGE = {
    schemas.InteractiveLessonInteractionEventType.SESSION_INITIALIZED: (
        schemas.LectureVideoInteractionEventType.SESSION_INITIALIZED
    ),
    schemas.InteractiveLessonInteractionEventType.QUESTION_PRESENTED: (
        schemas.LectureVideoInteractionEventType.QUESTION_PRESENTED
    ),
    schemas.InteractiveLessonInteractionEventType.ANSWER_SUBMITTED: (
        schemas.LectureVideoInteractionEventType.ANSWER_SUBMITTED
    ),
    schemas.InteractiveLessonInteractionEventType.LESSON_RESUMED: (
        schemas.LectureVideoInteractionEventType.VIDEO_RESUMED
    ),
    schemas.InteractiveLessonInteractionEventType.LESSON_PAUSED: (
        schemas.LectureVideoInteractionEventType.VIDEO_PAUSED
    ),
    schemas.InteractiveLessonInteractionEventType.LESSON_SEEKED: (
        schemas.LectureVideoInteractionEventType.VIDEO_SEEKED
    ),
    schemas.InteractiveLessonInteractionEventType.LESSON_ENDED: (
        schemas.LectureVideoInteractionEventType.VIDEO_ENDED
    ),
    schemas.InteractiveLessonInteractionEventType.SESSION_COMPLETED: (
        schemas.LectureVideoInteractionEventType.SESSION_COMPLETED
    ),
}
_VIDEO_STORAGE_TO_EVENT = {
    storage_event: lesson_event
    for lesson_event, storage_event in _VIDEO_EVENT_TO_STORAGE.items()
}


class LectureVideoAdapter:
    state_model: Any = models.LectureVideoThreadState
    interaction_model: Any = models.LectureVideoInteraction
    state_enum: Any = schemas.LectureVideoSessionState

    async def get_thread_with_context(
        self, session: AsyncSession, thread_id: int
    ) -> models.Thread | None:
        return await models.Thread.get_by_id_with_lecture_video_context(
            session, thread_id
        )

    def get_asset(self, thread: models.Thread) -> models.LectureVideo | None:
        if thread.interaction_mode != schemas.InteractionMode.LECTURE_VIDEO:
            return None
        return thread.lecture_video

    def get_questions(
        self, thread: models.Thread
    ) -> list[interactive_lesson_runtime.LessonQuestion]:
        if thread.lecture_video is None:
            return []
        return cast(
            list[interactive_lesson_runtime.LessonQuestion],
            thread.lecture_video.questions,
        )

    def get_state(
        self, thread: models.Thread
    ) -> interactive_lesson_runtime.LessonState | None:
        return cast(
            interactive_lesson_runtime.LessonState | None, thread.lecture_video_state
        )

    def set_state(
        self, thread: models.Thread, state: interactive_lesson_runtime.LessonState
    ) -> None:
        thread.lecture_video_state = cast(models.LectureVideoThreadState, state)

    def matches_assistant(self, thread: models.Thread) -> bool:
        return lecture_video_matches_assistant(thread)

    def lesson_chat_available(self, asset: object) -> bool:
        lecture_video = cast(models.LectureVideo, asset)
        return lecture_video.lecture_video_chat_available

    def initial_state_fields(self) -> dict[str, Any]:
        return {"last_chat_context_end_ms": 0}

    def to_storage_event(
        self, event_type: schemas.InteractiveLessonInteractionEventType
    ) -> schemas.LectureVideoInteractionEventType:
        return _VIDEO_EVENT_TO_STORAGE[event_type]


_VIDEO_ADAPTER = LectureVideoAdapter()

_VIDEO_REQUEST_TO_INTERACTIVE = {
    schemas.LectureVideoQuestionPresentedRequest: (
        schemas.InteractiveLessonQuestionPresentedRequest,
        "question_presented",
    ),
    schemas.LectureVideoAnswerSubmittedRequest: (
        schemas.InteractiveLessonAnswerSubmittedRequest,
        "answer_submitted",
    ),
    schemas.LectureVideoResumedRequest: (
        schemas.InteractiveLessonResumedRequest,
        "lesson_resumed",
    ),
    schemas.LectureVideoPausedRequest: (
        schemas.InteractiveLessonPausedRequest,
        "lesson_paused",
    ),
    schemas.LectureVideoSeekedRequest: (
        schemas.InteractiveLessonSeekedRequest,
        "lesson_seeked",
    ),
    schemas.LectureVideoEndedRequest: (
        schemas.InteractiveLessonEndedRequest,
        "lesson_ended",
    ),
}


def has_active_controller(
    state: models.LectureVideoThreadState, now: datetime | None = None
) -> bool:
    return interactive_lesson_runtime.has_active_controller(state, now)


def lecture_video_matches_assistant(thread: models.Thread | None) -> bool:
    if not thread or not thread.assistant_id or not thread.lecture_video_id:
        return False
    assistant = thread.assistant
    return bool(
        assistant
        and assistant.lecture_video_id is not None
        and assistant.lecture_video_id == thread.lecture_video_id
    )


def narration_allowed_for_thread_state(
    thread: models.Thread, narration_id: int
) -> bool:
    state = thread.lecture_video_state
    if state is None:
        return False

    current_question = interactive_lesson_runtime.get_current_question(
        thread, state, adapter=_VIDEO_ADAPTER
    )
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


def _to_video_session(
    session: schemas.InteractiveLessonSession,
) -> schemas.LectureVideoSession:
    data = session.model_dump()
    data["lecture_video_chat_available"] = data.pop("lesson_chat_available")
    return schemas.LectureVideoSession.model_validate(data)


def _to_interactive_request(
    request: schemas.LectureVideoInteractionRequest,
) -> schemas.InteractiveLessonInteractionRequest:
    request_mapping = _VIDEO_REQUEST_TO_INTERACTIVE.get(type(request))
    if request_mapping is None:
        raise TypeError(
            f"Unhandled lecture video interaction request type: {type(request).__name__}"
        )
    request_model, generic_type = request_mapping
    data = request.model_dump()
    data["type"] = generic_type
    return request_model(**data)


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
    return _to_video_session(
        interactive_lesson_runtime.build_interactive_lesson_session(
            thread,
            state,
            adapter=_VIDEO_ADAPTER,
            furthest_offset_ms=furthest_offset_ms,
            latest_interaction_at=latest_interaction_at,
            request_controller_session_id=request_controller_session_id,
            request_actor_user_id=request_actor_user_id,
            now=now,
        )
    )


async def get_plausible_playback_offset_ms(
    session: AsyncSession,
    state: models.LectureVideoThreadState,
    *,
    current_time: datetime,
) -> int:
    return await interactive_lesson_runtime.get_plausible_playback_offset_ms(
        session,
        state,
        adapter=_VIDEO_ADAPTER,
        current_time=current_time,
    )


async def get_thread_session(
    session: AsyncSession,
    thread_id: int,
    *,
    request_controller_session_id: str | None = None,
    request_actor_user_id: int | None = None,
    nowfn: NowFn | None = None,
) -> schemas.LectureVideoSession | None:
    lesson_session = await interactive_lesson_runtime.get_thread_session(
        session,
        thread_id,
        adapter=_VIDEO_ADAPTER,
        request_controller_session_id=request_controller_session_id,
        request_actor_user_id=request_actor_user_id,
        nowfn=nowfn,
    )
    if lesson_session is None:
        return None
    return _to_video_session(lesson_session)


async def initialize_thread_state(
    session: AsyncSession, thread_id: int
) -> models.LectureVideoThreadState:
    return cast(
        models.LectureVideoThreadState,
        await interactive_lesson_runtime.initialize_thread_state(
            session, thread_id, adapter=_VIDEO_ADAPTER
        ),
    )


async def get_or_initialize_thread_state(
    session: AsyncSession,
    thread_id: int,
    *,
    for_update: bool = False,
) -> models.LectureVideoThreadState:
    return cast(
        models.LectureVideoThreadState,
        await interactive_lesson_runtime.get_or_initialize_thread_state(
            session, thread_id, adapter=_VIDEO_ADAPTER, for_update=for_update
        ),
    )


async def acquire_control(
    session: AsyncSession,
    thread_id: int,
    actor_user_id: int,
    *,
    nowfn: NowFn | None = None,
) -> tuple[str, schemas.LectureVideoSession]:
    (
        controller_session_id,
        lesson_session,
    ) = await interactive_lesson_runtime.acquire_control(
        session,
        thread_id,
        actor_user_id,
        adapter=_VIDEO_ADAPTER,
        nowfn=nowfn,
    )
    return controller_session_id, _to_video_session(lesson_session)


async def release_control(
    session: AsyncSession,
    thread_id: int,
    actor_user_id: int,
    controller_session_id: str,
    *,
    nowfn: NowFn | None = None,
) -> schemas.LectureVideoSession:
    lesson_session = await interactive_lesson_runtime.release_control(
        session,
        thread_id,
        actor_user_id,
        controller_session_id,
        adapter=_VIDEO_ADAPTER,
        nowfn=nowfn,
    )
    return _to_video_session(lesson_session)


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
        adapter=_VIDEO_ADAPTER,
        nowfn=nowfn,
    )


async def process_interaction(
    session: AsyncSession,
    thread_id: int,
    actor_user_id: int,
    request: schemas.LectureVideoInteractionRequest,
    *,
    nowfn: NowFn | None = None,
) -> schemas.LectureVideoSession:
    lesson_session = await interactive_lesson_runtime.process_interaction(
        session,
        thread_id,
        actor_user_id,
        _to_interactive_request(request),
        adapter=_VIDEO_ADAPTER,
        nowfn=nowfn,
    )
    return _to_video_session(lesson_session)
