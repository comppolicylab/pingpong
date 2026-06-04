import pytest

import pingpong.models as models
import pingpong.schemas as schemas
from pingpong.migrations import (
    m11_move_lecture_slide_questions_to_slide_ends as migration,
)

pytestmark = pytest.mark.asyncio


async def test_move_lecture_slide_questions_to_slide_ends(db):
    async with db.async_session() as session:
        class_ = models.Class(id=1, name="Slide Class", api_key="sk-test")
        source = models.LectureSlideSourceStoredObject(
            key="slides.pdf",
            original_filename="slides.pdf",
            content_type="application/pdf",
            content_length=100,
        )
        deck = models.LectureSlideDeck(
            id=1,
            class_id=1,
            source_stored_object=source,
            display_name="Slides",
            status=schemas.LectureSlideDeckStatus.READY,
            slide_count=2,
        )
        pages = [
            models.LectureSlidePage(
                lecture_slide_deck_id=1,
                position=0,
                start_offset_ms=0,
                end_offset_ms=1000,
            ),
            models.LectureSlidePage(
                lecture_slide_deck_id=1,
                position=1,
                start_offset_ms=1000,
                end_offset_ms=2500,
            ),
        ]
        question = models.LectureSlideQuestion(
            lecture_slide_deck_id=1,
            position=0,
            slide_position=1,
            slide_offset_ms=300,
            stop_offset_ms=1300,
            question_type=schemas.LectureSlideQuestionType.SINGLE_SELECT,
            question_text="Question?",
            intro_text="",
            options=[
                models.LectureSlideQuestionOption(
                    position=0,
                    option_text="Correct",
                    post_answer_text="",
                    continue_slide_position=1,
                    continue_slide_offset_ms=300,
                    continue_offset_ms=1300,
                ),
                models.LectureSlideQuestionOption(
                    position=1,
                    option_text="Incorrect",
                    post_answer_text="",
                    continue_slide_position=1,
                    continue_slide_offset_ms=300,
                    continue_offset_ms=1300,
                ),
            ],
        )
        session.add_all([class_, deck, *pages, question])
        await session.commit()

        result = await migration.move_lecture_slide_questions_to_slide_ends(session)
        await session.commit()

    async with db.async_session() as session:
        deck = await models.LectureSlideDeck.get_by_id_with_processing_context(
            session, 1
        )
        assert deck is not None
        assert result.updated == 1
        assert result.skipped == 0
        assert result.skipped_question_ids == ()
        assert len(deck.questions) == 1
        question = deck.questions[0]
        assert question.slide_position == 1
        assert question.slide_offset_ms == 1500
        assert question.stop_offset_ms == 2500
        assert [option.continue_slide_position for option in question.options] == [
            1,
            1,
        ]
        assert [option.continue_slide_offset_ms for option in question.options] == [
            1500,
            1500,
        ]
        assert [option.continue_offset_ms for option in question.options] == [
            2500,
            2500,
        ]


async def test_move_lecture_slide_questions_to_slide_ends_is_idempotent(db):
    async with db.async_session() as session:
        class_ = models.Class(id=1, name="Slide Class", api_key="sk-test")
        source = models.LectureSlideSourceStoredObject(
            key="slides.pdf",
            original_filename="slides.pdf",
            content_type="application/pdf",
            content_length=100,
        )
        deck = models.LectureSlideDeck(
            id=1,
            class_id=1,
            source_stored_object=source,
            display_name="Slides",
            status=schemas.LectureSlideDeckStatus.READY,
            slide_count=1,
        )
        page = models.LectureSlidePage(
            lecture_slide_deck_id=1,
            position=0,
            start_offset_ms=0,
            end_offset_ms=1000,
        )
        question = models.LectureSlideQuestion(
            lecture_slide_deck_id=1,
            position=0,
            slide_position=0,
            slide_offset_ms=1000,
            stop_offset_ms=1000,
            question_type=schemas.LectureSlideQuestionType.SINGLE_SELECT,
            question_text="Question?",
            intro_text="",
            options=[
                models.LectureSlideQuestionOption(
                    position=0,
                    option_text="Correct",
                    post_answer_text="",
                    continue_slide_position=0,
                    continue_slide_offset_ms=1000,
                    continue_offset_ms=1000,
                ),
            ],
        )
        session.add_all([class_, deck, page, question])
        await session.commit()

        result = await migration.move_lecture_slide_questions_to_slide_ends(session)

    assert result.updated == 0
    assert result.skipped == 0
    assert result.skipped_question_ids == ()


async def test_move_lecture_slide_questions_to_slide_ends_reports_skipped_questions(db):
    async with db.async_session() as session:
        class_ = models.Class(id=1, name="Slide Class", api_key="sk-test")
        source = models.LectureSlideSourceStoredObject(
            key="slides.pdf",
            original_filename="slides.pdf",
            content_type="application/pdf",
            content_length=100,
        )
        deck = models.LectureSlideDeck(
            id=1,
            class_id=1,
            source_stored_object=source,
            display_name="Slides",
            status=schemas.LectureSlideDeckStatus.READY,
            slide_count=1,
        )
        page = models.LectureSlidePage(
            lecture_slide_deck_id=1,
            position=0,
            start_offset_ms=None,
            end_offset_ms=None,
        )
        question = models.LectureSlideQuestion(
            lecture_slide_deck_id=1,
            position=0,
            slide_position=0,
            slide_offset_ms=200,
            stop_offset_ms=200,
            question_type=schemas.LectureSlideQuestionType.SINGLE_SELECT,
            question_text="Question?",
            intro_text="",
            options=[
                models.LectureSlideQuestionOption(
                    position=0,
                    option_text="Correct",
                    post_answer_text="",
                    continue_slide_position=0,
                    continue_slide_offset_ms=200,
                    continue_offset_ms=200,
                ),
            ],
        )
        session.add_all([class_, deck, page, question])
        await session.commit()
        question_id = question.id

        result = await migration.move_lecture_slide_questions_to_slide_ends(session)
        await session.commit()

    async with db.async_session() as session:
        deck = await models.LectureSlideDeck.get_by_id_with_processing_context(
            session, 1
        )
        assert deck is not None
        assert result.updated == 0
        assert result.skipped == 1
        assert result.skipped_question_ids == (question_id,)
        assert len(deck.questions) == 1
        question = deck.questions[0]
        assert question.slide_offset_ms == 200
        assert question.stop_offset_ms == 200
        assert question.options[0].continue_offset_ms == 200
