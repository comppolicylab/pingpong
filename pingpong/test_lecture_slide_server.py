from sqlalchemy import select

import pingpong.schemas as schemas
from pingpong import lecture_slide_service, models

from .testutil import with_authz, with_institution, with_user


@with_user(123)
@with_institution(11, "Test Institution")
@with_authz(
    grants=[
        ("user:123", "admin", "class:1"),
        ("user:123", "can_create_assistants", "class:1"),
        ("user:123", "can_edit", "assistant:1"),
    ]
)
async def test_retry_lecture_slide_endpoint_queues_processing_after_failure(
    api, db, institution, valid_user_token
):
    async with db.async_session() as session:
        class_ = models.Class(
            id=1,
            name="Test Class",
            institution_id=institution.id,
            api_key="test-key",
        )
        session.add(class_)
        await session.flush()
        source = await models.LectureSlideSourceStoredObject.create(
            session,
            key="lecture04.pdf",
            original_filename="lecture04.pdf",
            content_type="application/pdf",
            content_length=128,
        )
        deck = await models.LectureSlideDeck.create(
            session,
            class_id=class_.id,
            source_stored_object_id=source.id,
            uploader_id=123,
            display_name="lecture04.pdf",
            slide_count=18,
            voice_id="voice-test-id",
            status=schemas.LectureSlideDeckStatus.FAILED,
            error_message="Unable to process the lecture slide deck right now. Please retry.",
        )
        assistant = models.Assistant(
            id=1,
            name="Physics Slides",
            class_id=class_.id,
            interaction_mode=schemas.InteractionMode.LECTURE_SLIDES,
            version=3,
            lecture_slide_deck_id=deck.id,
            instructions="You are a lecture assistant.",
            model="gpt-4o-mini",
            tools="[]",
            use_latex=False,
            use_image_descriptions=False,
            hide_prompt=False,
        )
        session.add(assistant)
        await models.LectureSlideProcessingRun.create(
            session,
            lecture_slide_deck_id=deck.id,
            lecture_slide_deck_id_snapshot=deck.id,
            class_id=class_.id,
            assistant_id_at_start=assistant.id,
            stage=schemas.LectureSlideProcessingStage.NARRATION_TRANSCRIPTION,
            attempt_number=1,
            status=schemas.LectureSlideProcessingRunStatus.FAILED,
        )
        await session.commit()
        deck_id = deck.id

    response = api.post(
        "/api/v1/class/1/assistant/1/lecture-slides/retry",
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == schemas.LectureSlideDeckStatus.PROCESSING.value
    assert response.json()["error_message"] is None

    async with db.async_session() as session:
        refreshed_deck = await models.LectureSlideDeck.get_by_id(session, deck_id)
        runs = list(
            (
                await session.scalars(
                    select(models.LectureSlideProcessingRun)
                    .where(
                        models.LectureSlideProcessingRun.lecture_slide_deck_id_snapshot
                        == deck_id
                    )
                    .order_by(models.LectureSlideProcessingRun.attempt_number.asc())
                )
            ).all()
        )

    assert refreshed_deck is not None
    assert refreshed_deck.status == schemas.LectureSlideDeckStatus.PROCESSING
    assert refreshed_deck.error_message is None
    assert len(runs) == 2
    assert runs[0].status == schemas.LectureSlideProcessingRunStatus.FAILED
    assert runs[1].status == schemas.LectureSlideProcessingRunStatus.QUEUED
    assert runs[1].stage == schemas.LectureSlideProcessingStage.NARRATION_AUDIO
    assert runs[1].attempt_number == 2


@with_institution(11, "Test Institution")
async def test_apply_lecture_slide_page_notes_handles_unloaded_pages(db, institution):
    async with db.async_session() as session:
        class_ = models.Class(
            id=1,
            name="Test Class",
            institution_id=institution.id,
            api_key="test-key",
        )
        session.add(class_)
        await session.flush()
        source = await models.LectureSlideSourceStoredObject.create(
            session,
            key="lecture04.pdf",
            original_filename="lecture04.pdf",
            content_type="application/pdf",
            content_length=128,
        )
        deck = await models.LectureSlideDeck.create(
            session,
            class_id=class_.id,
            source_stored_object_id=source.id,
            uploader_id=123,
            display_name="lecture04.pdf",
            slide_count=2,
            voice_id="voice-test-id",
        )
        session.add(
            models.LectureSlidePage(
                lecture_slide_deck_id=deck.id,
                position=0,
                user_notes="Old notes",
            )
        )
        await session.commit()
        deck_id = deck.id

    async with db.async_session() as session:
        deck = await models.LectureSlideDeck.get_by_id(session, deck_id)
        assert deck is not None
        assert "pages" not in deck.__dict__

        result = await lecture_slide_service.apply_lecture_slide_page_notes(
            session,
            deck,
            [
                schemas.LectureSlidePageNotes(
                    position=0,
                    user_notes="New notes",
                    narration_text="Narrate this.",
                )
            ],
        )
        await session.commit()

    assert result.notes_changed is True
    assert result.narration_changed is True

    async with db.async_session() as session:
        page = await session.scalar(
            select(models.LectureSlidePage).where(
                models.LectureSlidePage.lecture_slide_deck_id == deck_id,
                models.LectureSlidePage.position == 0,
            )
        )

    assert page is not None
    assert page.user_notes == "New notes"
    assert page.narration_text == "Narrate this."
