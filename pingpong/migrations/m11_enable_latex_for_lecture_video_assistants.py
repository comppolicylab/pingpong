import logging

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from pingpong.ai import format_instructions
import pingpong.models as models
from pingpong.schemas import InteractionMode

logger = logging.getLogger(__name__)


async def enable_latex_for_lecture_video_assistants(session: AsyncSession) -> int:
    thread_rows = (
        await session.execute(
            select(models.Thread, models.Assistant)
            .join(models.Assistant, models.Thread.assistant_id == models.Assistant.id)
            .where(models.Thread.interaction_mode == InteractionMode.LECTURE_VIDEO)
            .where(models.Assistant.interaction_mode == InteractionMode.LECTURE_VIDEO)
        )
    ).all()
    for thread, assistant in thread_rows:
        thread.instructions = format_instructions(
            assistant.instructions,
            use_latex=True,
            use_image_descriptions=assistant.use_image_descriptions,
            disable_prompt_randomization=assistant.disable_prompt_randomization,
            thread_id=str(thread.thread_id or thread.id),
            user_id=None,
            lecture_video_mode=True,
        )

    result = await session.execute(
        update(models.Assistant)
        .where(models.Assistant.interaction_mode == InteractionMode.LECTURE_VIDEO)
        .where(models.Assistant.use_latex.is_not(True))
        .values(use_latex=True)
    )
    updated = result.rowcount or 0
    await session.flush()
    logger.info(
        "Enabled LaTeX for lecture video assistants. updated=%s threads_updated=%s",
        updated,
        len(thread_rows),
    )
    return updated
