import importlib
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import asc, select

import pingpong.lecture_slide_runtime as lecture_slide_runtime
import pingpong.models as models
import pingpong.schemas as schemas
from pingpong.testutil import with_institution

pytestmark = pytest.mark.asyncio
server_module = importlib.import_module("pingpong.server")


def _slide_deck(
    class_: models.Class,
    source: models.LectureSlideSourceStoredObject,
    *,
    id: int = 1,
    display_name: str = "Test Slides",
) -> models.LectureSlideDeck:
    return models.LectureSlideDeck(
        id=id,
        class_=class_,
        source_stored_object=source,
        display_name=display_name,
        status=schemas.LectureSlideDeckStatus.READY,
        slide_count=1,
        total_duration_ms=10_000,
    )


async def _create_slide_runtime_fixture(
    session,
    institution: models.Institution,
    *,
    with_questions: bool = True,
) -> tuple[
    models.Class,
    models.LectureSlideDeck,
    models.Assistant,
    models.Thread,
    list[models.LectureSlideQuestion],
]:
    class_ = models.Class(
        id=1,
        name="Test Class",
        institution_id=institution.id,
        api_key="test-key",
    )
    source = models.LectureSlideSourceStoredObject(
        key="test-slides.pdf",
        original_filename="test-slides.pdf",
        content_type="application/pdf",
        content_length=128,
    )
    deck = _slide_deck(class_, source)
    assistant = models.Assistant(
        id=1,
        name="Slide Assistant",
        class_=class_,
        interaction_mode=schemas.InteractionMode.CHAT,
        version=3,
        lecture_slide_deck=deck,
        instructions="You are a slide assistant.",
        model="gpt-4o-mini",
        tools="[]",
        use_latex=False,
        use_image_descriptions=False,
        hide_prompt=False,
    )
    thread = models.Thread(
        id=1,
        name="Slide Lesson",
        version=3,
        thread_id="thread-slide-runtime",
        class_=class_,
        assistant=assistant,
        interaction_mode=schemas.InteractionMode.CHAT,
        lecture_slide_deck=deck,
        private=False,
        display_user_info=False,
        tools_available="[]",
    )
    questions: list[models.LectureSlideQuestion] = []

    if with_questions:
        first_question = models.LectureSlideQuestion(
            lecture_slide_deck=deck,
            position=1,
            slide_position=1,
            slide_offset_ms=0,
            stop_offset_ms=1_000,
            question_type=schemas.LectureSlideQuestionType.SINGLE_SELECT,
            question_text="What is shown on this slide?",
            intro_text="Pick the best description.",
        )
        first_correct_option = models.LectureSlideQuestionOption(
            question=first_question,
            position=1,
            option_text="A clear example",
            post_answer_text="Correct.",
            continue_slide_position=1,
            continue_slide_offset_ms=1_500,
            continue_offset_ms=1_500,
        )
        first_question.correct_option = first_correct_option

        second_question = models.LectureSlideQuestion(
            lecture_slide_deck=deck,
            position=2,
            slide_position=1,
            slide_offset_ms=3_000,
            stop_offset_ms=4_000,
            question_type=schemas.LectureSlideQuestionType.SINGLE_SELECT,
            question_text="What comes next?",
            intro_text="Choose the next step.",
        )
        second_option = models.LectureSlideQuestionOption(
            question=second_question,
            position=1,
            option_text="Continue",
            post_answer_text="Good.",
            continue_slide_position=1,
            continue_slide_offset_ms=5_000,
            continue_offset_ms=5_000,
        )
        second_question.correct_option = second_option
        questions = [first_question, second_question]

    session.add_all([class_, source, deck, assistant, thread, *questions])
    await session.flush()
    return class_, deck, assistant, thread, questions


async def _list_slide_interactions(
    session, thread_id: int
) -> list[models.LectureSlideInteraction]:
    result = await session.scalars(
        select(models.LectureSlideInteraction)
        .where(models.LectureSlideInteraction.thread_id == thread_id)
        .order_by(asc(models.LectureSlideInteraction.event_index))
    )
    return list(result)


def _server_request(session, user_id: int = 123):
    return SimpleNamespace(
        state={
            "db": session,
            "session": SimpleNamespace(user=SimpleNamespace(id=user_id)),
        },
        app=SimpleNamespace(state={}),
    )


@with_institution(11, "Test Institution")
async def test_initialize_thread_state_and_acquire_control_for_lecture_slides(
    db, institution
):
    async with db.async_session() as session:
        _, _, _, thread, questions = await _create_slide_runtime_fixture(
            session, institution
        )

        state = await lecture_slide_runtime.initialize_thread_state(session, thread.id)
        interactions = await _list_slide_interactions(session, thread.id)

        assert state.state == schemas.InteractiveLessonSessionState.PLAYING
        assert state.current_question_id == questions[0].id
        assert state.last_known_offset_ms == 0
        assert state.version == 1
        assert [interaction.event_type for interaction in interactions] == [
            schemas.InteractiveLessonInteractionEventType.SESSION_INITIALIZED
        ]

        (
            controller_session_id,
            slide_session,
        ) = await lecture_slide_runtime.acquire_control(
            session,
            thread.id,
            actor_user_id=123,
        )

    assert controller_session_id
    assert slide_session.controller.has_control is True
    assert slide_session.controller.has_active_controller is True
    assert slide_session.current_question is not None
    assert slide_session.current_question.id == questions[0].id
    assert [marker.id for marker in slide_session.question_markers] == [
        question.id for question in questions
    ]


@with_institution(11, "Test Institution")
async def test_acquire_lecture_slide_control_endpoint_uses_generic_lesson_session(
    db, institution
):
    async with db.async_session() as session:
        class_, _, _, thread, questions = await _create_slide_runtime_fixture(
            session, institution
        )
        thread.interaction_mode = schemas.InteractionMode.LECTURE_SLIDES
        await session.flush()

        response = await server_module.acquire_lecture_slide_control(
            str(class_.id),
            str(thread.id),
            _server_request(session),
        )

    assert response["controller_session_id"]
    lesson_session = response["interactive_lesson_session"]
    assert isinstance(lesson_session, schemas.InteractiveLessonSession)
    assert lesson_session.controller.has_control is True
    assert lesson_session.current_question is not None
    assert lesson_session.current_question.id == questions[0].id


@with_institution(11, "Test Institution")
async def test_acquire_lecture_slide_control_endpoint_rejects_non_slide_thread(
    db, institution
):
    async with db.async_session() as session:
        class_, _, _, thread, _ = await _create_slide_runtime_fixture(
            session, institution
        )

        with pytest.raises(HTTPException) as excinfo:
            await server_module.acquire_lecture_slide_control(
                str(class_.id),
                str(thread.id),
                _server_request(session),
            )

    assert excinfo.value.status_code == 404
    assert excinfo.value.detail == "Lecture slide thread not found."


@with_institution(11, "Test Institution")
async def test_process_lecture_slide_question_answer_and_resume(db, institution):
    async with db.async_session() as session:
        _, _, _, thread, questions = await _create_slide_runtime_fixture(
            session, institution
        )

        (
            controller_session_id,
            slide_session,
        ) = await lecture_slide_runtime.acquire_control(
            session,
            thread.id,
            actor_user_id=123,
        )
        first_question = questions[0]
        first_option = first_question.options[0]

        slide_session = await lecture_slide_runtime.process_interaction(
            session,
            thread.id,
            actor_user_id=123,
            request=schemas.InteractiveLessonQuestionPresentedRequest(
                type="question_presented",
                controller_session_id=controller_session_id,
                expected_state_version=slide_session.state_version,
                idempotency_key="present-1",
                question_id=first_question.id,
                offset_ms=first_question.stop_offset_ms,
            ),
        )
        assert (
            slide_session.state == schemas.InteractiveLessonSessionState.AWAITING_ANSWER
        )

        repeated_session = await lecture_slide_runtime.process_interaction(
            session,
            thread.id,
            actor_user_id=123,
            request=schemas.InteractiveLessonQuestionPresentedRequest(
                type="question_presented",
                controller_session_id=controller_session_id,
                expected_state_version=slide_session.state_version - 1,
                idempotency_key="present-1",
                question_id=first_question.id,
                offset_ms=first_question.stop_offset_ms,
            ),
        )
        assert repeated_session.state_version == slide_session.state_version

        slide_session = await lecture_slide_runtime.process_interaction(
            session,
            thread.id,
            actor_user_id=123,
            request=schemas.InteractiveLessonAnswerSubmittedRequest(
                type="answer_submitted",
                controller_session_id=controller_session_id,
                expected_state_version=slide_session.state_version,
                idempotency_key="answer-1",
                question_id=first_question.id,
                option_id=first_option.id,
            ),
        )
        assert (
            slide_session.state
            == schemas.InteractiveLessonSessionState.AWAITING_POST_ANSWER_RESUME
        )
        assert slide_session.current_continuation is not None
        assert slide_session.current_continuation.option_id == first_option.id
        assert slide_session.current_continuation.next_question is not None
        assert slide_session.current_continuation.next_question.id == questions[1].id

        slide_session = await lecture_slide_runtime.process_interaction(
            session,
            thread.id,
            actor_user_id=123,
            request=schemas.InteractiveLessonResumedRequest(
                type="lesson_resumed",
                controller_session_id=controller_session_id,
                expected_state_version=slide_session.state_version,
                idempotency_key="resume-1",
                offset_ms=first_option.continue_offset_ms,
            ),
        )
        interactions = await _list_slide_interactions(session, thread.id)

    assert slide_session.state == schemas.InteractiveLessonSessionState.PLAYING
    assert slide_session.current_question is not None
    assert slide_session.current_question.id == questions[1].id
    assert [interaction.event_type for interaction in interactions] == [
        schemas.InteractiveLessonInteractionEventType.SESSION_INITIALIZED,
        schemas.InteractiveLessonInteractionEventType.QUESTION_PRESENTED,
        schemas.InteractiveLessonInteractionEventType.ANSWER_SUBMITTED,
        schemas.InteractiveLessonInteractionEventType.LESSON_RESUMED,
    ]


@with_institution(11, "Test Institution")
async def test_initialize_thread_state_completes_when_lecture_slides_have_no_questions(
    db, institution
):
    async with db.async_session() as session:
        _, _, _, thread, _ = await _create_slide_runtime_fixture(
            session, institution, with_questions=False
        )

        state = await lecture_slide_runtime.initialize_thread_state(session, thread.id)
        interactions = await _list_slide_interactions(session, thread.id)

    assert state.state == schemas.InteractiveLessonSessionState.COMPLETED
    assert state.current_question_id is None
    assert state.last_known_offset_ms == 0
    assert state.version == 1
    assert [interaction.event_type for interaction in interactions] == [
        schemas.InteractiveLessonInteractionEventType.SESSION_INITIALIZED
    ]


@pytest.mark.parametrize(
    ("session_state", "expected_offset_ms"),
    [
        (
            schemas.InteractiveLessonSessionState.PLAYING,
            1_000 + 120_000 + lecture_slide_runtime.PLAYBACK_PROGRESS_TOLERANCE_MS,
        ),
        (schemas.InteractiveLessonSessionState.AWAITING_ANSWER, 1_000),
        (
            schemas.InteractiveLessonSessionState.AWAITING_POST_ANSWER_RESUME,
            1_000,
        ),
    ],
)
@with_institution(11, "Test Institution")
async def test_get_plausible_playback_offset_ms_only_advances_while_slide_is_playing(
    db, institution, session_state, expected_offset_ms
):
    base_time = datetime(2024, 1, 1, tzinfo=timezone.utc)
    current_time = base_time + timedelta(minutes=2)

    async with db.async_session() as session:
        _, _, _, thread, _ = await _create_slide_runtime_fixture(session, institution)
        state = models.LectureSlideThreadState(
            thread_id=thread.id,
            state=session_state,
            last_known_offset_ms=1_000,
            furthest_offset_ms=1_000,
            version=1,
        )
        session.add(state)
        session.add(
            models.LectureSlideInteraction(
                thread_id=thread.id,
                event_index=1,
                event_type=schemas.InteractiveLessonInteractionEventType.LESSON_PAUSED,
                offset_ms=1_000,
                created=base_time,
            )
        )
        await session.flush()

        plausible_offset_ms = (
            await lecture_slide_runtime.get_plausible_playback_offset_ms(
                session,
                state,
                current_time=current_time,
            )
        )

    assert plausible_offset_ms == expected_offset_ms


@with_institution(11, "Test Institution")
async def test_acquire_control_rejects_thread_when_slide_deck_no_longer_matches_assistant(
    db, institution
):
    async with db.async_session() as session:
        class_, deck, assistant, thread, _ = await _create_slide_runtime_fixture(
            session, institution
        )
        replacement_source = models.LectureSlideSourceStoredObject(
            key="replacement-slides.pdf",
            original_filename="replacement-slides.pdf",
            content_type="application/pdf",
            content_length=128,
        )
        replacement_deck = _slide_deck(
            class_,
            replacement_source,
            id=2,
            display_name="Replacement Slides",
        )
        session.add_all([replacement_source, replacement_deck])
        await session.flush()

        assistant.lecture_slide_deck = replacement_deck
        thread.lecture_slide_deck = deck
        await session.flush()

        with pytest.raises(
            lecture_slide_runtime.LectureSlideConflictError,
            match=lecture_slide_runtime.MSG_LESSON_UPDATED,
        ):
            await lecture_slide_runtime.acquire_control(
                session,
                thread.id,
                actor_user_id=123,
            )


@with_institution(11, "Test Institution")
async def test_append_interaction_requires_for_update_locked_slide_state(
    db, institution
):
    async with db.async_session() as session:
        _, _, _, thread, _ = await _create_slide_runtime_fixture(session, institution)
        await lecture_slide_runtime.initialize_thread_state(session, thread.id)
        unlocked_state = await lecture_slide_runtime.get_or_initialize_thread_state(
            session,
            thread.id,
        )

        with pytest.raises(RuntimeError, match="FOR UPDATE before appending"):
            await lecture_slide_runtime._append_interaction(
                session,
                unlocked_state,
                actor_user_id=None,
                event_type=schemas.InteractiveLessonInteractionEventType.LESSON_PAUSED,
                offset_ms=500,
            )
