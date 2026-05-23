import pytest

from pingpong import models, schemas
from pingpong.server import _build_run_instructions

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
        thread_instructions=None,
        assistant_instructions="Be helpful.",
        use_latex=True,
    )

    instructions = _build_run_instructions(thread, assistant, user_id=1)

    assert instructions is not None
    assert "Be helpful." in instructions
    assert "---Formatting: Lecture Video Dual Speech/Display Blocks---" in instructions
    assert "---Formatting: LaTeX---" not in instructions
    assert "---Formatting: Lecture Video Follow-ups---" in instructions


async def test_build_run_instructions_for_lecture_video_without_latex_skips_say_contract(
    db,
):
    thread, assistant = await create_thread_and_assistant(
        db,
        interaction_mode=schemas.InteractionMode.LECTURE_VIDEO,
        thread_instructions=None,
        assistant_instructions="Be helpful.",
        use_latex=False,
    )

    instructions = _build_run_instructions(thread, assistant, user_id=1)

    assert instructions is not None
    assert "Be helpful." in instructions
    assert (
        "---Formatting: Lecture Video Dual Speech/Display Blocks---" not in instructions
    )
    assert "---Formatting: LaTeX---" not in instructions


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
