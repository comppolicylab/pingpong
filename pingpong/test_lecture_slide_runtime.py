import importlib
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from sqlalchemy import asc, select

import pingpong.lecture_slide_chat as lecture_slide_chat
import pingpong.lecture_slide_runtime as lecture_slide_runtime
import pingpong.models as models
import pingpong.schemas as schemas
from pingpong.config import config
from pingpong.testutil import with_institution

pytestmark = pytest.mark.asyncio
server_module = importlib.import_module("pingpong.server")


async def test_send_message_allows_first_run_for_lecture_slide_threads():
    thread = SimpleNamespace(interaction_mode=schemas.InteractionMode.LECTURE_SLIDES)

    assert server_module._allows_first_message_without_prior_run(thread)


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
    allow_lesson_timeline_bypass: bool = False,
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
        allow_lesson_timeline_bypass=allow_lesson_timeline_bypass,
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


def _server_request(session, user_id: int = 123, *, headers: dict | None = None):
    def url_for(name: str, **path_params):
        params = "/".join(f"{key}-{value}" for key, value in path_params.items())
        return f"http://testserver/{name}/{params}"

    return SimpleNamespace(
        state={
            "db": session,
            "session": SimpleNamespace(user=SimpleNamespace(id=user_id)),
        },
        app=SimpleNamespace(state={}),
        headers=headers or {},
        url_for=url_for,
    )


def _slide_transcript_data() -> dict:
    return {
        "word_level_transcription": [
            {
                "id": "w1",
                "word": "Hello",
                "start_offset_ms": 0,
                "end_offset_ms": 400,
            },
            {
                "id": "w2",
                "word": "slides",
                "start_offset_ms": 400,
                "end_offset_ms": 900,
            },
        ]
    }


def _slide_context_data_v5() -> dict:
    return {
        "version": 5,
        "deck_summary": "A short lesson about using examples to explain an idea.",
        "slides": [
            {
                "slide_position": 0,
                "title": "Core idea",
                "start_offset_ms": 0,
                "end_offset_ms": 30_000,
                "visible_text": "Core idea",
                "visual_context": "A title slide with a simple definition.",
                "narration_summary": "The narration introduces the core idea.",
                "key_points": ["The idea needs a concrete example."],
                "diagrams": [],
                "equations_or_symbols": [],
            },
            {
                "slide_position": 1,
                "title": "Example",
                "start_offset_ms": 30_000,
                "end_offset_ms": 60_000,
                "visible_text": "Example",
                "visual_context": "A worked example is shown in a callout.",
                "narration_summary": "The narration walks through the example.",
                "key_points": ["Examples make the concept testable."],
                "diagrams": ["A callout box connects the term to the example."],
                "equations_or_symbols": ["x -> y"],
            },
        ],
        "summary_checkpoints": [
            {
                "end_offset_ms": 39_000,
                "end_slide_position": 1,
                "summary": "The lesson has introduced the idea and started the example.",
            }
        ],
        "moment_contexts": [
            {
                "start_offset_ms": 36_000,
                "center_offset_ms": 42_000,
                "end_offset_ms": 48_000,
                "slide_position": 1,
                "before": "The learner has just moved from the definition to the example.",
                "at": "The example is being connected to the visible callout.",
                "after": "The narration will finish the example and prepare to continue.",
            }
        ],
    }


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
async def test_lecture_slide_seek_rejects_forward_jump_without_bypass(db, institution):
    async with db.async_session() as session:
        _, _, _, thread, _ = await _create_slide_runtime_fixture(session, institution)

        (
            controller_session_id,
            slide_session,
        ) = await lecture_slide_runtime.acquire_control(
            session,
            thread.id,
            actor_user_id=123,
        )

        with pytest.raises(lecture_slide_runtime.LectureSlideValidationError) as exc:
            await lecture_slide_runtime.process_interaction(
                session,
                thread.id,
                actor_user_id=123,
                request=schemas.InteractiveLessonSeekedRequest(
                    type="lesson_seeked",
                    controller_session_id=controller_session_id,
                    expected_state_version=slide_session.state_version,
                    idempotency_key="blocked-forward-seek",
                    from_offset_ms=0,
                    to_offset_ms=3_000,
                ),
            )

    assert (
        str(exc.value)
        == "You cannot jump ahead yet. Continue from where the lesson left off."
    )


@with_institution(11, "Test Institution")
async def test_lecture_slide_timeline_bypass_seek_recomputes_question_queue(
    db, institution
):
    async with db.async_session() as session:
        _, _, _, thread, questions = await _create_slide_runtime_fixture(
            session, institution, allow_lesson_timeline_bypass=True
        )

        (
            controller_session_id,
            slide_session,
        ) = await lecture_slide_runtime.acquire_control(
            session,
            thread.id,
            actor_user_id=123,
        )
        assert slide_session.timeline_bypass_enabled is True

        slide_session = await lecture_slide_runtime.process_interaction(
            session,
            thread.id,
            actor_user_id=123,
            request=schemas.InteractiveLessonSeekedRequest(
                type="lesson_seeked",
                controller_session_id=controller_session_id,
                expected_state_version=slide_session.state_version,
                idempotency_key="skip-first-question",
                from_offset_ms=0,
                to_offset_ms=2_000,
            ),
        )
        assert slide_session.state == schemas.InteractiveLessonSessionState.PLAYING
        assert slide_session.last_known_offset_ms == 2_000
        assert slide_session.furthest_offset_ms == 2_000
        assert slide_session.current_question is not None
        assert slide_session.current_question.id == questions[1].id

        slide_session = await lecture_slide_runtime.process_interaction(
            session,
            thread.id,
            actor_user_id=123,
            request=schemas.InteractiveLessonSeekedRequest(
                type="lesson_seeked",
                controller_session_id=controller_session_id,
                expected_state_version=slide_session.state_version,
                idempotency_key="skip-all-questions",
                from_offset_ms=2_000,
                to_offset_ms=5_000,
            ),
        )
        assert slide_session.current_question is None

        slide_session = await lecture_slide_runtime.process_interaction(
            session,
            thread.id,
            actor_user_id=123,
            request=schemas.InteractiveLessonSeekedRequest(
                type="lesson_seeked",
                controller_session_id=controller_session_id,
                expected_state_version=slide_session.state_version,
                idempotency_key="reactivate-second-question",
                from_offset_ms=5_000,
                to_offset_ms=2_000,
            ),
        )
        assert slide_session.current_question is not None
        assert slide_session.current_question.id == questions[1].id
        assert slide_session.furthest_offset_ms == 5_000

        slide_session = await lecture_slide_runtime.process_interaction(
            session,
            thread.id,
            actor_user_id=123,
            request=schemas.InteractiveLessonSeekedRequest(
                type="lesson_seeked",
                controller_session_id=controller_session_id,
                expected_state_version=slide_session.state_version,
                idempotency_key="reactivate-first-question",
                from_offset_ms=2_000,
                to_offset_ms=500,
            ),
        )
        interactions = await _list_slide_interactions(session, thread.id)

    assert slide_session.current_question is not None
    assert slide_session.current_question.id == questions[0].id
    assert [interaction.event_type for interaction in interactions] == [
        schemas.InteractiveLessonInteractionEventType.SESSION_INITIALIZED,
        schemas.InteractiveLessonInteractionEventType.LESSON_SEEKED,
        schemas.InteractiveLessonInteractionEventType.LESSON_SEEKED,
        schemas.InteractiveLessonInteractionEventType.LESSON_SEEKED,
        schemas.InteractiveLessonInteractionEventType.LESSON_SEEKED,
    ]


@with_institution(11, "Test Institution")
async def test_lecture_slide_timeline_bypass_seek_to_exact_checkpoint_keeps_question(
    db, institution
):
    async with db.async_session() as session:
        _, _, _, thread, questions = await _create_slide_runtime_fixture(
            session, institution, allow_lesson_timeline_bypass=True
        )

        (
            controller_session_id,
            slide_session,
        ) = await lecture_slide_runtime.acquire_control(
            session,
            thread.id,
            actor_user_id=123,
        )

        slide_session = await lecture_slide_runtime.process_interaction(
            session,
            thread.id,
            actor_user_id=123,
            request=schemas.InteractiveLessonSeekedRequest(
                type="lesson_seeked",
                controller_session_id=controller_session_id,
                expected_state_version=slide_session.state_version,
                idempotency_key="seek-to-first-checkpoint",
                from_offset_ms=0,
                to_offset_ms=questions[0].stop_offset_ms,
            ),
        )

    assert slide_session.state == schemas.InteractiveLessonSessionState.PLAYING
    assert slide_session.current_question is not None
    assert slide_session.current_question.id == questions[0].id


@with_institution(11, "Test Institution")
async def test_lecture_slide_timeline_bypass_seek_clears_pending_question(
    db, institution
):
    async with db.async_session() as session:
        _, _, _, thread, questions = await _create_slide_runtime_fixture(
            session, institution, allow_lesson_timeline_bypass=True
        )

        (
            controller_session_id,
            slide_session,
        ) = await lecture_slide_runtime.acquire_control(
            session,
            thread.id,
            actor_user_id=123,
        )

        slide_session = await lecture_slide_runtime.process_interaction(
            session,
            thread.id,
            actor_user_id=123,
            request=schemas.InteractiveLessonQuestionPresentedRequest(
                type="question_presented",
                controller_session_id=controller_session_id,
                expected_state_version=slide_session.state_version,
                idempotency_key="present-first-before-seek",
                question_id=questions[0].id,
                offset_ms=questions[0].stop_offset_ms,
            ),
        )
        assert (
            slide_session.state == schemas.InteractiveLessonSessionState.AWAITING_ANSWER
        )

        slide_session = await lecture_slide_runtime.process_interaction(
            session,
            thread.id,
            actor_user_id=123,
            request=schemas.InteractiveLessonSeekedRequest(
                type="lesson_seeked",
                controller_session_id=controller_session_id,
                expected_state_version=slide_session.state_version,
                idempotency_key="seek-out-of-pending-question",
                from_offset_ms=questions[0].stop_offset_ms,
                to_offset_ms=2_000,
            ),
        )

    assert slide_session.state == schemas.InteractiveLessonSessionState.PLAYING
    assert slide_session.current_question is not None
    assert slide_session.current_question.id == questions[1].id
    assert slide_session.current_continuation is None


@with_institution(11, "Test Institution")
async def test_lecture_slide_timeline_bypass_seek_clears_post_answer_continuation(
    db, institution
):
    async with db.async_session() as session:
        _, _, _, thread, questions = await _create_slide_runtime_fixture(
            session, institution, allow_lesson_timeline_bypass=True
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
                idempotency_key="present-before-post-answer-seek",
                question_id=first_question.id,
                offset_ms=first_question.stop_offset_ms,
            ),
        )
        slide_session = await lecture_slide_runtime.process_interaction(
            session,
            thread.id,
            actor_user_id=123,
            request=schemas.InteractiveLessonAnswerSubmittedRequest(
                type="answer_submitted",
                controller_session_id=controller_session_id,
                expected_state_version=slide_session.state_version,
                idempotency_key="answer-before-post-answer-seek",
                question_id=first_question.id,
                option_id=first_option.id,
            ),
        )
        assert (
            slide_session.state
            == schemas.InteractiveLessonSessionState.AWAITING_POST_ANSWER_RESUME
        )
        assert slide_session.current_continuation is not None

        slide_session = await lecture_slide_runtime.process_interaction(
            session,
            thread.id,
            actor_user_id=123,
            request=schemas.InteractiveLessonSeekedRequest(
                type="lesson_seeked",
                controller_session_id=controller_session_id,
                expected_state_version=slide_session.state_version,
                idempotency_key="seek-out-of-post-answer",
                from_offset_ms=first_question.stop_offset_ms,
                to_offset_ms=2_000,
            ),
        )

    assert slide_session.state == schemas.InteractiveLessonSessionState.PLAYING
    assert slide_session.current_continuation is None
    assert slide_session.current_question is not None
    assert slide_session.current_question.id == questions[1].id


@with_institution(11, "Test Institution")
async def test_lecture_slide_timeline_bypass_allows_presenting_question_after_seek(
    db, institution
):
    async with db.async_session() as session:
        _, _, _, thread, questions = await _create_slide_runtime_fixture(
            session, institution, allow_lesson_timeline_bypass=True
        )

        (
            controller_session_id,
            slide_session,
        ) = await lecture_slide_runtime.acquire_control(
            session,
            thread.id,
            actor_user_id=123,
        )

        # Jump past the first question to a spot still ahead of plausible
        # watched progress for the second question's checkpoint.
        slide_session = await lecture_slide_runtime.process_interaction(
            session,
            thread.id,
            actor_user_id=123,
            request=schemas.InteractiveLessonSeekedRequest(
                type="lesson_seeked",
                controller_session_id=controller_session_id,
                expected_state_version=slide_session.state_version,
                idempotency_key="seek-near-second-question",
                from_offset_ms=0,
                to_offset_ms=1_500,
            ),
        )
        assert slide_session.current_question is not None
        assert slide_session.current_question.id == questions[1].id

        slide_session = await lecture_slide_runtime.process_interaction(
            session,
            thread.id,
            actor_user_id=123,
            request=schemas.InteractiveLessonQuestionPresentedRequest(
                type="question_presented",
                controller_session_id=controller_session_id,
                expected_state_version=slide_session.state_version,
                idempotency_key="present-second-after-seek",
                question_id=questions[1].id,
                offset_ms=questions[1].stop_offset_ms,
            ),
        )

    assert slide_session.state == schemas.InteractiveLessonSessionState.AWAITING_ANSWER
    assert slide_session.current_question is not None
    assert slide_session.current_question.id == questions[1].id
    assert slide_session.last_known_offset_ms == questions[1].stop_offset_ms


@with_institution(11, "Test Institution")
async def test_lecture_slide_timeline_bypass_seek_keeps_completed_state(
    db, institution
):
    async with db.async_session() as session:
        _, _, _, thread, _ = await _create_slide_runtime_fixture(
            session,
            institution,
            with_questions=False,
            allow_lesson_timeline_bypass=True,
        )

        (
            controller_session_id,
            slide_session,
        ) = await lecture_slide_runtime.acquire_control(
            session,
            thread.id,
            actor_user_id=123,
        )

        slide_session = await lecture_slide_runtime.process_interaction(
            session,
            thread.id,
            actor_user_id=123,
            request=schemas.InteractiveLessonEndedRequest(
                type="lesson_ended",
                controller_session_id=controller_session_id,
                expected_state_version=slide_session.state_version,
                idempotency_key="complete-lesson",
                offset_ms=10_000,
            ),
        )
        assert slide_session.state == schemas.InteractiveLessonSessionState.COMPLETED

        slide_session = await lecture_slide_runtime.process_interaction(
            session,
            thread.id,
            actor_user_id=123,
            request=schemas.InteractiveLessonSeekedRequest(
                type="lesson_seeked",
                controller_session_id=controller_session_id,
                expected_state_version=slide_session.state_version,
                idempotency_key="seek-back-after-complete",
                from_offset_ms=10_000,
                to_offset_ms=1_000,
            ),
        )

    assert slide_session.state == schemas.InteractiveLessonSessionState.COMPLETED
    assert slide_session.current_question is None
    assert slide_session.last_known_offset_ms == 1_000
    assert slide_session.furthest_offset_ms == 10_000


@with_institution(11, "Test Institution")
async def test_lecture_slide_timeline_bypass_ended_recomputes_question_queue(
    db, institution
):
    async with db.async_session() as session:
        _, _, _, thread, _ = await _create_slide_runtime_fixture(
            session, institution, allow_lesson_timeline_bypass=True
        )

        (
            controller_session_id,
            slide_session,
        ) = await lecture_slide_runtime.acquire_control(
            session,
            thread.id,
            actor_user_id=123,
        )

        slide_session = await lecture_slide_runtime.process_interaction(
            session,
            thread.id,
            actor_user_id=123,
            request=schemas.InteractiveLessonEndedRequest(
                type="lesson_ended",
                controller_session_id=controller_session_id,
                expected_state_version=slide_session.state_version,
                idempotency_key="complete-after-skip-to-end",
                offset_ms=10_000,
            ),
        )
        interactions = await _list_slide_interactions(session, thread.id)

    assert slide_session.state == schemas.InteractiveLessonSessionState.COMPLETED
    assert slide_session.current_question is None
    assert [interaction.event_type for interaction in interactions] == [
        schemas.InteractiveLessonInteractionEventType.SESSION_INITIALIZED,
        schemas.InteractiveLessonInteractionEventType.LESSON_ENDED,
        schemas.InteractiveLessonInteractionEventType.SESSION_COMPLETED,
    ]


@with_institution(11, "Test Institution")
async def test_initialize_thread_state_plays_when_lecture_slides_have_no_questions(
    db, institution
):
    async with db.async_session() as session:
        _, _, _, thread, _ = await _create_slide_runtime_fixture(
            session, institution, with_questions=False
        )

        state = await lecture_slide_runtime.initialize_thread_state(session, thread.id)
        interactions = await _list_slide_interactions(session, thread.id)

    assert state.state == schemas.InteractiveLessonSessionState.PLAYING
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


@with_institution(11, "Test Institution")
async def test_lecture_slide_chat_context_matches_lecture_video_v4_sections(
    db, institution
):
    async with db.async_session() as session:
        _, deck, _, thread, questions = await _create_slide_runtime_fixture(
            session, institution
        )
        deck.transcript_data = _slide_transcript_data()
        deck.context_data = {}
        deck.context_version = 4
        state = models.LectureSlideThreadState(
            thread=thread,
            state=schemas.InteractiveLessonSessionState.PLAYING,
            current_question=questions[0],
            last_known_offset_ms=2_000,
            furthest_offset_ms=5_000,
            version=1,
        )
        session.add(state)
        await session.flush()

        context = lecture_slide_chat.lecture_slide_chat_context_from_model(deck)
        assert context is not None
        context_text = lecture_slide_chat._build_context_text(
            thread,
            state,
            playback_position_ms=2_000,
            answered_knowledge_checks=None,
        )

    assert "## Lecture Context" in context_text
    assert "Current offset: 2000ms" in context_text
    assert "Furthest watched offset: 5000ms" in context_text
    assert "### Lecture Summary So Far" not in context_text
    assert "### Current Moment Context" not in context_text
    assert "### Upcoming Knowledge Check" in context_text
    assert "### Current Slide" not in context_text
    assert "Extracted text:" not in context_text


@with_institution(11, "Test Institution")
async def test_lecture_slide_deck_view_exposes_pages_narration_and_captions(
    db, institution
):
    async with db.async_session() as session:
        class_, deck, _, thread, _ = await _create_slide_runtime_fixture(
            session, institution
        )
        thread.interaction_mode = schemas.InteractionMode.LECTURE_SLIDES
        narration = models.LectureSlideNarrationStoredObject(
            key="slides/audio.ogg",
            content_type="audio/ogg",
            content_length=10,
            duration_ms=10_000,
        )
        captions = models.LectureSlideCaptionStoredObject(
            key="slides/captions.vtt",
            content_type="text/vtt",
            content_length=12,
        )
        image = models.LectureSlideImageStoredObject(
            key="slides/page-1.png",
            content_type="image/png",
            content_length=5,
            width_px=1280,
            height_px=720,
        )
        page = models.LectureSlidePage(
            lecture_slide_deck=deck,
            position=1,
            title="Terms",
            image_stored_object=image,
            start_offset_ms=0,
            end_offset_ms=10_000,
        )
        deck.continuous_narration_stored_object = narration
        deck.caption_stored_object = captions
        session.add_all([narration, captions, image, page])
        await session.flush()

        loaded_thread = await models.Thread.get_by_id_with_lecture_slide_context(
            session, thread.id
        )
        assert loaded_thread is not None
        view = server_module._lecture_slide_deck_view(
            _server_request(session),
            loaded_thread,
        )

    assert view is not None
    assert view.id == deck.id
    assert view.display_name == "Test Slides"
    assert view.continuous_narration_url is not None
    assert view.captions_url is not None
    assert len(view.pages) == 1
    assert not hasattr(view.pages[0], "title")
    assert view.pages[0].image_stored_object_id == image.id


@with_institution(11, "Test Institution")
async def test_lecture_slide_captions_endpoint_streams_stored_webvtt(
    db, institution, monkeypatch
):
    class FakeVideoStore:
        async def stream_video_range(self, *, key, start=None, end=None):
            assert key == "slides/captions.vtt"
            assert start is None
            assert end is None
            yield b"WEBVTT\n\nHello slides"

    monkeypatch.setattr(config, "video_store", SimpleNamespace(store=FakeVideoStore()))

    async with db.async_session() as session:
        class_, deck, assistant, thread, _ = await _create_slide_runtime_fixture(
            session, institution
        )
        thread.interaction_mode = schemas.InteractionMode.LECTURE_SLIDES
        assistant.interaction_mode = schemas.InteractionMode.LECTURE_SLIDES
        captions = models.LectureSlideCaptionStoredObject(
            key="slides/captions.vtt",
            content_type="text/vtt",
            content_length=20,
        )
        deck.caption_stored_object = captions
        session.add(captions)
        await session.flush()

        response = await server_module.get_thread_lecture_slide_captions(
            str(class_.id),
            str(thread.id),
            _server_request(session),
        )

    assert response.status_code == 200
    assert response.media_type == "text/vtt"
    chunks = [chunk async for chunk in response.body_iterator]
    body = b"".join(chunks).decode("utf-8")
    assert body.startswith("WEBVTT")
    assert "Hello slides" in body


@with_institution(11, "Test Institution")
async def test_lecture_slide_continuous_narration_endpoint_streams_audio(
    db, institution, monkeypatch
):
    class FakeAudioStore:
        async def get_file(self, key):
            assert key == "slides/audio.ogg"
            yield b"audio"

    monkeypatch.setattr(
        config,
        "lecture_video_audio_store",
        SimpleNamespace(store=FakeAudioStore()),
    )

    async with db.async_session() as session:
        class_, deck, assistant, thread, _ = await _create_slide_runtime_fixture(
            session, institution
        )
        thread.interaction_mode = schemas.InteractionMode.LECTURE_SLIDES
        assistant.interaction_mode = schemas.InteractionMode.LECTURE_SLIDES
        narration = models.LectureSlideNarrationStoredObject(
            key="slides/audio.ogg",
            content_type="audio/ogg",
            content_length=5,
            duration_ms=10_000,
        )
        deck.continuous_narration_stored_object = narration
        session.add(narration)
        await session.flush()

        response = await server_module.get_thread_lecture_slide_continuous_narration(
            str(class_.id),
            str(thread.id),
            _server_request(session),
        )

    chunks = [chunk async for chunk in response.body_iterator]
    assert response.status_code == 200
    assert response.media_type == "audio/ogg"
    assert b"".join(chunks) == b"audio"


@with_institution(11, "Test Institution")
async def test_lecture_slide_question_narration_endpoint_streams_allowed_audio(
    db, institution, monkeypatch
):
    class FakeAudioStore:
        async def get_file(self, key):
            assert key == "slides/question.ogg"
            yield b"question-audio"

    monkeypatch.setattr(
        config,
        "lecture_video_audio_store",
        SimpleNamespace(store=FakeAudioStore()),
    )

    async with db.async_session() as session:
        (
            class_,
            _deck,
            assistant,
            thread,
            questions,
        ) = await _create_slide_runtime_fixture(session, institution)
        thread.interaction_mode = schemas.InteractionMode.LECTURE_SLIDES
        assistant.interaction_mode = schemas.InteractionMode.LECTURE_SLIDES
        stored_object = models.LectureSlideNarrationStoredObject(
            key="slides/question.ogg",
            content_type="audio/ogg",
            content_length=14,
            duration_ms=1_000,
        )
        narration = models.LectureSlideNarration(
            stored_object=stored_object,
            status=schemas.LectureSlideNarrationStatus.READY,
        )
        questions[0].intro_narration = narration
        state = models.LectureSlideThreadState(
            thread=thread,
            state=schemas.InteractiveLessonSessionState.AWAITING_ANSWER,
            current_question=questions[0],
            last_known_offset_ms=questions[0].stop_offset_ms,
            furthest_offset_ms=questions[0].stop_offset_ms,
            version=1,
        )
        session.add_all([stored_object, narration, state])
        await session.flush()

        response = await server_module.get_thread_lecture_slide_narration(
            str(class_.id),
            str(thread.id),
            narration.id,
            _server_request(session),
        )

    chunks = [chunk async for chunk in response.body_iterator]
    assert response.status_code == 200
    assert response.media_type == "audio/ogg"
    assert b"".join(chunks) == b"question-audio"


@with_institution(11, "Test Institution")
async def test_lecture_slide_page_image_endpoint_streams_from_video_store(
    db, institution, monkeypatch
):
    class FakeVideoStore:
        async def stream_video_range(self, *, key, start=None, end=None):
            assert key == "slides/page-1.png"
            assert start is None
            assert end is None
            yield b"image"

    monkeypatch.setattr(config, "video_store", SimpleNamespace(store=FakeVideoStore()))

    async with db.async_session() as session:
        class_, deck, assistant, thread, _ = await _create_slide_runtime_fixture(
            session, institution
        )
        thread.interaction_mode = schemas.InteractionMode.LECTURE_SLIDES
        assistant.interaction_mode = schemas.InteractionMode.LECTURE_SLIDES
        image = models.LectureSlideImageStoredObject(
            key="slides/page-1.png",
            content_type="image/png",
            content_length=5,
            width_px=1280,
            height_px=720,
        )
        page = models.LectureSlidePage(
            lecture_slide_deck=deck,
            position=1,
            title="Terms",
            image_stored_object=image,
            start_offset_ms=0,
            end_offset_ms=10_000,
        )
        session.add_all([image, page])
        await session.flush()

        response = await server_module.get_thread_lecture_slide_page_image(
            str(class_.id),
            str(thread.id),
            page.id,
            _server_request(session),
        )

    chunks = [chunk async for chunk in response.body_iterator]
    assert response.status_code == 200
    assert response.media_type == "image/png"
    assert b"".join(chunks) == b"image"


@with_institution(11, "Test Institution")
async def test_lecture_slide_session_uses_stored_chat_available_flag(db, institution):
    async with db.async_session() as session:
        _, deck, _, thread, _ = await _create_slide_runtime_fixture(
            session, institution
        )
        deck.context_version = 4
        deck.lecture_slide_chat_available = True
        lesson_session = await lecture_slide_runtime.get_thread_session(
            session,
            thread.id,
            request_actor_user_id=123,
        )

    assert lesson_session is not None
    assert lesson_session.lesson_chat_available is True


@with_institution(11, "Test Institution")
async def test_lecture_slide_session_accepts_v5_chat_context(db, institution):
    async with db.async_session() as session:
        _, deck, _, thread, _ = await _create_slide_runtime_fixture(
            session, institution
        )
        deck.context_version = 5
        deck.lecture_slide_chat_available = True
        lesson_session = await lecture_slide_runtime.get_thread_session(
            session,
            thread.id,
            request_actor_user_id=123,
        )

    assert lesson_session is not None
    assert lesson_session.lesson_chat_available is True


@with_institution(11, "Test Institution")
async def test_prepare_lecture_slide_chat_turn_uses_video_context_shape(
    db, institution
):
    async with db.async_session() as session:
        (
            class_,
            deck,
            assistant,
            thread,
            questions,
        ) = await _create_slide_runtime_fixture(session, institution)
        thread.interaction_mode = schemas.InteractionMode.LECTURE_SLIDES
        assistant.interaction_mode = schemas.InteractionMode.LECTURE_SLIDES
        deck.transcript_data = _slide_transcript_data()
        deck.context_data = {}
        deck.context_version = 4
        deck.lecture_slide_chat_available = True
        input_file = models.File(
            file_id="pdf-file-id",
            name="test-slides.pdf",
            content_type="application/pdf",
            private=True,
        )
        session.add(input_file)
        await session.flush()
        input_file_id = input_file.id
        assert deck.source_stored_object is not None
        deck.source_stored_object.openai_file_object_id = input_file.id
        page = models.LectureSlidePage(
            lecture_slide_deck=deck,
            position=0,
            narration_text="This slide introduces the core idea.",
            start_offset_ms=0,
            end_offset_ms=1_000,
        )
        state = models.LectureSlideThreadState(
            thread=thread,
            state=schemas.InteractiveLessonSessionState.PLAYING,
            current_question=questions[0],
            last_known_offset_ms=2_000,
            furthest_offset_ms=5_000,
            version=1,
        )
        session.add_all([page, state])
        await session.flush()

        prep = await lecture_slide_chat.prepare_lecture_chat_turn(
            request=_server_request(session),
            class_id=str(class_.id),
            thread=thread,
            user_id=123,
            prev_output_sequence=7,
            lecture_video_playback_position_ms=2_000,
        )
        lesson_context_message = prep.prepended_messages[0]
        file_message = prep.prepended_messages[1]
        context_message = prep.prepended_messages[2]
        lesson_context_text = lesson_context_message.content[0].text
        file_note = file_message.content[1].text
        context_text = context_message.content[0].text

    assert prep.user_output_index == 11
    assert prep.user_assistant_messages_only is True
    assert prep.include_developer_messages is True
    assert prep.user_message_metadata == {
        schemas.MESSAGE_METADATA_LECTURE_PLAYBACK_POSITION_MS_V1: 2_000,
        schemas.MESSAGE_METADATA_LECTURE_SLIDE_NUMBER_V1: 1,
    }
    assert lesson_context_message.is_hidden is True
    assert lesson_context_message.role == schemas.MessageRole.DEVELOPER
    assert "## Lecture Slide Narrations" in lesson_context_text
    assert "This slide introduces the core idea." in lesson_context_text
    assert "## Lecture Knowledge Checks" not in lesson_context_text
    assert "What is shown on this slide?" not in lesson_context_text
    assert "What comes next?" not in lesson_context_text
    assert "A clear example" not in lesson_context_text
    assert file_message.is_hidden is True
    assert file_message.role == schemas.MessageRole.USER
    assert file_message.content[0].type == schemas.MessagePartType.INPUT_FILE
    assert file_message.content[0].input_file_object_id == input_file_id
    assert "visual source of truth" in file_note
    assert context_message.is_hidden is True
    assert "## Lecture Context" in context_text
    assert "Current offset: 2000ms" in context_text
    assert "Furthest watched offset: 5000ms" in context_text
    assert "### Lecture Summary So Far" not in context_text
    assert "### Current Moment Context" not in context_text
    assert "### Upcoming Knowledge Check" in context_text
    assert "### Current Slide" not in context_text
    assert "Extracted text:" not in context_text


@with_institution(11, "Test Institution")
async def test_prepare_lecture_slide_chat_turn_uses_v5_compact_context(db, institution):
    async with db.async_session() as session:
        (
            class_,
            deck,
            assistant,
            thread,
            questions,
        ) = await _create_slide_runtime_fixture(session, institution)
        thread.interaction_mode = schemas.InteractionMode.LECTURE_SLIDES
        assistant.interaction_mode = schemas.InteractionMode.LECTURE_SLIDES
        deck.transcript_data = _slide_transcript_data()
        deck.context_data = _slide_context_data_v5()
        deck.context_version = 5
        deck.lecture_slide_chat_available = True
        deck.slide_count = 2
        pages = [
            models.LectureSlidePage(
                lecture_slide_deck=deck,
                position=0,
                start_offset_ms=0,
                end_offset_ms=30_000,
            ),
            models.LectureSlidePage(
                lecture_slide_deck=deck,
                position=1,
                start_offset_ms=30_000,
                end_offset_ms=60_000,
            ),
        ]
        state = models.LectureSlideThreadState(
            thread=thread,
            state=schemas.InteractiveLessonSessionState.PLAYING,
            current_question=questions[0],
            last_known_offset_ms=42_000,
            furthest_offset_ms=52_000,
            version=1,
        )
        session.add_all([*pages, state])
        await session.flush()

        prep = await lecture_slide_chat.prepare_lecture_chat_turn(
            request=_server_request(session),
            class_id=str(class_.id),
            thread=thread,
            user_id=123,
            prev_output_sequence=7,
            lecture_video_playback_position_ms=42_000,
        )
        context_message = prep.prepended_messages[0]
        context_text = context_message.content[0].text

    assert prep.user_output_index == 9
    assert prep.include_developer_messages is False
    assert prep.user_message_metadata == {
        schemas.MESSAGE_METADATA_LECTURE_PLAYBACK_POSITION_MS_V1: 42_000,
        schemas.MESSAGE_METADATA_LECTURE_SLIDE_NUMBER_V1: 2,
    }
    assert [message.role for message in prep.prepended_messages] == [
        schemas.MessageRole.DEVELOPER,
    ]
    assert context_message.output_index == 8
    assert context_message.is_hidden is True
    assert context_text.startswith("## Lecture Context")
    assert "## Lecture Slide Lesson Context" not in context_text
    assert "Current offset: 42000ms" in context_text
    assert "Furthest watched offset: 52000ms" in context_text
    assert "Current slide: Slide 2" in context_text
    assert "Furthest reached slide: Slide 2" in context_text
    assert "### Lecture Summary So Far" in context_text
    assert "Through 39000ms / Slide 2:" in context_text
    assert "### Current Moment Context" in context_text
    assert "Before this moment:" in context_text
    assert "At this moment:" in context_text
    assert "After this moment:" in context_text
    assert "### Current Slide" in context_text
    assert "Slide 2: Example" in context_text
    assert "Visible text:\nExample" in context_text
    assert "Visual context:\nA worked example is shown in a callout." in context_text
    assert "Key points:\n- Examples make the concept testable." in context_text
    assert (
        "Diagrams:\n- A callout box connects the term to the example." in context_text
    )
    assert "Equations or symbols:\n- x -> y" in context_text


@with_institution(11, "Test Institution")
async def test_prepare_lecture_slide_chat_turn_accepts_v5_context_without_transcript(
    db, institution
):
    async with db.async_session() as session:
        (
            class_,
            deck,
            assistant,
            thread,
            questions,
        ) = await _create_slide_runtime_fixture(session, institution)
        thread.interaction_mode = schemas.InteractionMode.LECTURE_SLIDES
        assistant.interaction_mode = schemas.InteractionMode.LECTURE_SLIDES
        deck.transcript_data = None
        deck.context_data = _slide_context_data_v5()
        deck.context_version = 5
        deck.lecture_slide_chat_available = True
        pages = [
            models.LectureSlidePage(
                lecture_slide_deck=deck,
                position=0,
                start_offset_ms=0,
                end_offset_ms=30_000,
            ),
            models.LectureSlidePage(
                lecture_slide_deck=deck,
                position=1,
                start_offset_ms=30_000,
                end_offset_ms=60_000,
            ),
        ]
        state = models.LectureSlideThreadState(
            thread=thread,
            state=schemas.InteractiveLessonSessionState.PLAYING,
            current_question=questions[0],
            last_known_offset_ms=42_000,
            furthest_offset_ms=52_000,
            version=1,
        )
        session.add_all([*pages, state])
        await session.flush()

        prep = await lecture_slide_chat.prepare_lecture_chat_turn(
            request=_server_request(session),
            class_id=str(class_.id),
            thread=thread,
            user_id=123,
            prev_output_sequence=7,
            lecture_video_playback_position_ms=42_000,
        )

    assert prep.user_output_index == 9
    assert prep.include_developer_messages is False
    assert [message.role for message in prep.prepended_messages] == [
        schemas.MessageRole.DEVELOPER,
    ]
    assert prep.prepended_messages[0].output_index == 8
    assert "### Current Slide" in prep.prepended_messages[0].content[0].text


@with_institution(11, "Test Institution")
async def test_prepare_lecture_slide_chat_turn_skips_initial_file_message_without_uploaded_file(
    db, institution
):
    async with db.async_session() as session:
        (
            class_,
            deck,
            assistant,
            thread,
            questions,
        ) = await _create_slide_runtime_fixture(session, institution)
        thread.interaction_mode = schemas.InteractionMode.LECTURE_SLIDES
        assistant.interaction_mode = schemas.InteractionMode.LECTURE_SLIDES
        deck.transcript_data = _slide_transcript_data()
        deck.context_data = {}
        deck.context_version = 4
        deck.lecture_slide_chat_available = True
        page = models.LectureSlidePage(
            lecture_slide_deck=deck,
            position=0,
            narration_text="This slide introduces the core idea.",
            start_offset_ms=0,
            end_offset_ms=1_000,
        )
        state = models.LectureSlideThreadState(
            thread=thread,
            state=schemas.InteractiveLessonSessionState.PLAYING,
            current_question=questions[0],
            last_known_offset_ms=2_000,
            furthest_offset_ms=5_000,
            version=1,
        )
        session.add_all([page, state])
        await session.commit()
        class_id = class_.id
        thread_id = thread.id

    async with db.async_session() as session:
        prep = await lecture_slide_chat.prepare_lecture_chat_turn(
            request=_server_request(session),
            class_id=str(class_id),
            thread=SimpleNamespace(id=thread_id),
            user_id=123,
            prev_output_sequence=-1,
            lecture_video_playback_position_ms=2_000,
        )

    assert prep.user_output_index == 2
    assert prep.include_developer_messages is True
    assert [message.role for message in prep.prepended_messages] == [
        schemas.MessageRole.DEVELOPER,
        schemas.MessageRole.DEVELOPER,
    ]
    assert "## Lecture Slide Narrations" in prep.prepended_messages[0].content[0].text
    assert "## Lecture Context" in prep.prepended_messages[1].content[0].text


@with_institution(11, "Test Institution")
async def test_prepare_lecture_slide_chat_turn_adds_dynamic_context_without_recreating_initial_messages(
    db, institution
):
    async with db.async_session() as session:
        (
            class_,
            deck,
            assistant,
            thread,
            questions,
        ) = await _create_slide_runtime_fixture(session, institution)
        thread.interaction_mode = schemas.InteractionMode.LECTURE_SLIDES
        assistant.interaction_mode = schemas.InteractionMode.LECTURE_SLIDES
        deck.transcript_data = _slide_transcript_data()
        deck.context_data = {}
        deck.context_version = 4
        deck.lecture_slide_chat_available = True
        deck.slide_count = 2
        pages = [
            models.LectureSlidePage(
                lecture_slide_deck=deck,
                position=0,
                narration_text="The first slide introduces the core idea.",
                start_offset_ms=0,
                end_offset_ms=1_000,
            ),
            models.LectureSlidePage(
                lecture_slide_deck=deck,
                position=1,
                narration_text="The second slide shows how to apply it.",
                start_offset_ms=1_000,
                end_offset_ms=2_000,
            ),
        ]
        state = models.LectureSlideThreadState(
            thread=thread,
            state=schemas.InteractiveLessonSessionState.PLAYING,
            current_question=questions[0],
            last_known_offset_ms=2_000,
            furthest_offset_ms=5_000,
            version=1,
        )
        existing_run = models.Run(
            thread=thread,
            status=schemas.RunStatus.COMPLETED,
        )
        previous_context_time = datetime(2026, 1, 1, tzinfo=timezone.utc)
        previous_context_message = models.Message(
            thread=thread,
            run=existing_run,
            output_index=19,
            message_status=schemas.MessageStatus.COMPLETED,
            role=schemas.MessageRole.DEVELOPER,
            is_hidden=True,
            created=previous_context_time,
            content=[
                models.MessagePart(
                    part_index=0,
                    type=schemas.MessagePartType.INPUT_TEXT,
                    text=(
                        "## Lecture Context\n\n"
                        "Status: Viewing the lecture slides\n"
                        "Current offset: 1000ms\n"
                        "Furthest watched offset: 5000ms"
                    ),
                )
            ],
        )
        existing_message = models.Message(
            thread=thread,
            run=existing_run,
            output_index=20,
            message_status=schemas.MessageStatus.COMPLETED,
            role=schemas.MessageRole.USER,
            user_id=123,
            content=[
                models.MessagePart(
                    part_index=0,
                    type=schemas.MessagePartType.INPUT_TEXT,
                    text="I already started this lesson.",
                )
            ],
        )
        older_answered_interaction = models.LectureSlideInteraction(
            thread=thread,
            event_index=1,
            event_type=schemas.InteractiveLessonInteractionEventType.ANSWER_SUBMITTED,
            question=questions[1],
            option=questions[1].correct_option,
            offset_ms=1_000,
            created=previous_context_time - timedelta(seconds=1),
        )
        answered_interaction = models.LectureSlideInteraction(
            thread=thread,
            event_index=2,
            event_type=schemas.InteractiveLessonInteractionEventType.ANSWER_SUBMITTED,
            question=questions[0],
            option=questions[0].correct_option,
            offset_ms=1_000,
            created=previous_context_time + timedelta(seconds=1),
        )
        session.add_all(
            [
                *pages,
                state,
                existing_run,
                previous_context_message,
                existing_message,
                older_answered_interaction,
                answered_interaction,
            ]
        )
        await session.flush()

        prep = await lecture_slide_chat.prepare_lecture_chat_turn(
            request=_server_request(session),
            class_id=str(class_.id),
            thread=thread,
            user_id=123,
            prev_output_sequence=20,
            lecture_video_playback_position_ms=2_000,
        )
        context_message = prep.prepended_messages[0]
        context_text = context_message.content[0].text

    assert prep.user_output_index == 22
    assert prep.include_developer_messages is True
    assert [message.role for message in prep.prepended_messages] == [
        schemas.MessageRole.DEVELOPER,
    ]
    assert context_message.output_index == 21
    assert "## Lecture Context" in context_text
    assert "Status: Viewing the lecture slides" in context_text
    assert "Current offset: 2000ms" in context_text
    assert "Furthest watched offset: 5000ms" in context_text
    assert "### Knowledge Checks Answered" in context_text
    assert "What is shown on this slide?" in context_text
    assert "Student selected `A clear example`." in context_text
    assert "Student selected `Continue`." not in context_text
