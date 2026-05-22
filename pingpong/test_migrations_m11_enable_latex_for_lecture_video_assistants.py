import pytest

from pingpong import models, schemas
from pingpong.migrations import m11_enable_latex_for_lecture_video_assistants as m11

pytestmark = pytest.mark.asyncio


async def test_enable_latex_for_lecture_video_assistants_backfills_thread_instructions(
    db,
):
    async with db.async_session() as session:
        class_ = models.Class(id=1, name="Test Class")
        assistant = models.Assistant(
            id=1,
            name="Lecture Assistant",
            class_id=class_.id,
            instructions="Be helpful.",
            interaction_mode=schemas.InteractionMode.LECTURE_VIDEO,
            use_latex=False,
            use_image_descriptions=False,
            disable_prompt_randomization=True,
        )
        thread = models.Thread(
            id=1,
            name="Lecture Thread",
            class_id=class_.id,
            assistant_id=assistant.id,
            interaction_mode=schemas.InteractionMode.LECTURE_VIDEO,
            instructions="Old instructions",
            private=False,
        )
        session.add_all([class_, assistant, thread])
        await session.commit()

    async with db.async_session() as session:
        updated = await m11.enable_latex_for_lecture_video_assistants(session)
        await session.commit()

    assert updated == 1

    async with db.async_session() as session:
        assistant = await session.get(models.Assistant, 1)
        thread = await session.get(models.Thread, 1)

    assert assistant is not None
    assert assistant.use_latex is True
    assert thread is not None
    assert "---Formatting: LaTeX---" in thread.instructions
    assert "---Lecture Video: Spoken and Written Output---" in thread.instructions
