import pytest

from pingpong import models, schemas
from pingpong.server import (
    _build_run_instructions,
    _lecture_lesson_dual_text_enabled,
    _lecture_lesson_followups_enabled,
)

pytestmark = pytest.mark.asyncio


async def create_thread_and_assistant(
    db,
    *,
    interaction_mode: schemas.InteractionMode,
    thread_instructions: str | None,
    assistant_instructions: str,
    use_latex: bool,
) -> tuple[models.Thread, models.Assistant]:
    async with db.async_session() as session:
        class_ = models.Class(id=1, name="Test Class")
        session.add(class_)
        await session.flush()
        assistant = models.Assistant(
            name="Test Assistant",
            class_id=class_.id,
            instructions=assistant_instructions,
            interaction_mode=interaction_mode,
            model="gpt-4o-mini",
            tools="[]",
            use_latex=use_latex,
            use_image_descriptions=False,
            disable_prompt_randomization=True,
            version=3,
        )
        session.add(assistant)
        await session.flush()
        thread = models.Thread(
            name="Test Thread",
            class_id=class_.id,
            assistant_id=assistant.id,
            interaction_mode=interaction_mode,
            instructions=thread_instructions,
            private=False,
            tools_available="[]",
            version=3,
            thread_id=f"thread-{assistant.id}",
        )
        session.add(thread)
        await session.commit()
        return thread, assistant


async def test_build_run_instructions_for_lecture_video_with_latex_includes_say_and_followups(
    db,
):
    thread, assistant = await create_thread_and_assistant(
        db,
        interaction_mode=schemas.InteractionMode.LECTURE_VIDEO,
        thread_instructions="Stored lecture snapshot.",
        assistant_instructions="Updated assistant instructions.",
        use_latex=True,
    )

    instructions = _build_run_instructions(thread, assistant, user_id=1)

    assert instructions is not None
    assert "Stored lecture snapshot." in instructions
    assert "Updated assistant instructions." not in instructions
    assert "---Formatting: Lecture Dual Speech/Display Blocks---" in instructions
    assert "---Formatting: LaTeX---" not in instructions
    assert "---Formatting: Lecture Follow-ups---" in instructions


async def test_build_run_instructions_for_lecture_video_forces_latex_and_say_contract(
    db,
):
    thread, assistant = await create_thread_and_assistant(
        db,
        interaction_mode=schemas.InteractionMode.LECTURE_VIDEO,
        thread_instructions="Stored lecture snapshot.",
        assistant_instructions="Updated assistant instructions.",
        use_latex=False,
    )

    instructions = _build_run_instructions(thread, assistant, user_id=1)

    assert instructions is not None
    assert "Stored lecture snapshot." in instructions
    assert "Updated assistant instructions." not in instructions
    assert "---Formatting: Lecture Dual Speech/Display Blocks---" in instructions
    assert "---Formatting: LaTeX---" not in instructions
    assert "---Formatting: Lecture Follow-ups---" in instructions


async def test_build_run_instructions_for_lecture_video_normalizes_missing_thread_snapshot(
    db,
):
    thread, assistant = await create_thread_and_assistant(
        db,
        interaction_mode=schemas.InteractionMode.LECTURE_VIDEO,
        thread_instructions=None,
        assistant_instructions="Assistant fallback instructions.",
        use_latex=True,
    )

    instructions = _build_run_instructions(thread, assistant, user_id=1)

    assert instructions is not None
    assert "Assistant fallback instructions." in instructions
    assert "---Formatting: Lecture Dual Speech/Display Blocks---" in instructions
    assert "---Formatting: Lecture Follow-ups---" in instructions


async def test_build_run_instructions_for_lecture_slides_uses_lecture_formatting(
    db,
):
    thread, assistant = await create_thread_and_assistant(
        db,
        interaction_mode=schemas.InteractionMode.LECTURE_SLIDES,
        thread_instructions="Stored slide snapshot.",
        assistant_instructions="Updated assistant instructions.",
        use_latex=False,
    )

    instructions = _build_run_instructions(thread, assistant, user_id=1)

    assert instructions is not None
    assert "Stored slide snapshot." in instructions
    assert "Updated assistant instructions." not in instructions
    assert "---Formatting: Lecture Dual Speech/Display Blocks---" in instructions
    assert "---Formatting: Lecture Follow-ups---" in instructions


async def test_lecture_slides_enable_dual_text_and_followups():
    thread = models.Thread(interaction_mode=schemas.InteractionMode.LECTURE_SLIDES)

    assert _lecture_lesson_dual_text_enabled(thread)
    assert _lecture_lesson_followups_enabled(thread)


async def test_build_run_instructions_for_non_lecture_video_uses_stored_instructions(
    db,
):
    thread, assistant = await create_thread_and_assistant(
        db,
        interaction_mode=schemas.InteractionMode.CHAT,
        thread_instructions="Stored chat instructions.",
        assistant_instructions="Different assistant instructions.",
        use_latex=True,
    )

    instructions = _build_run_instructions(thread, assistant, user_id=1)

    assert instructions == "Stored chat instructions."
