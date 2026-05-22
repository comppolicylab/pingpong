import logging

from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

import pingpong.models as models
from pingpong.schemas import InteractionMode

logger = logging.getLogger(__name__)


async def enable_latex_for_lecture_video_assistants(session: AsyncSession) -> int:
    result = await session.execute(
        update(models.Assistant)
        .where(models.Assistant.interaction_mode == InteractionMode.LECTURE_VIDEO)
        .where(models.Assistant.use_latex.is_not(True))
        .values(use_latex=True)
    )
    updated = result.rowcount or 0
    await session.flush()
    logger.info(
        "Enabled LaTeX for lecture video assistants. updated=%s",
        updated,
    )
    return updated
