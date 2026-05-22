import logging

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from pingpong.ai import format_instructions
import pingpong.models as models
from pingpong.schemas import InteractionMode

logger = logging.getLogger(__name__)
LECTURE_VIDEO_LATEX_HEADER = "---Formatting: Lecture Video LaTeX---"


def _lecture_video_latex_instructions() -> str:
    return format_instructions(
        "",
        use_latex=True,
        lecture_video_mode=True,
    ).strip()


def _with_lecture_video_latex_instructions(instructions: str | None) -> str:
    existing = instructions or ""
    if LECTURE_VIDEO_LATEX_HEADER in existing:
        return existing

    formatting_instructions = _lecture_video_latex_instructions()
    return (
        f"{existing}\n\n{formatting_instructions}"
        if existing
        else formatting_instructions
    )


async def enable_latex_for_lecture_video_assistants(session: AsyncSession) -> int:
    thread_rows = (
        (
            await session.execute(
                select(models.Thread).where(
                    models.Thread.interaction_mode == InteractionMode.LECTURE_VIDEO
                )
            )
        )
        .scalars()
        .all()
    )
    for thread in thread_rows:
        thread.instructions = _with_lecture_video_latex_instructions(
            thread.instructions
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
