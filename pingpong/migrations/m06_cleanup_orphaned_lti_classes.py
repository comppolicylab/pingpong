import logging

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

import pingpong.models as models
from pingpong.schemas import LTIStatus

logger = logging.getLogger(__name__)


async def cleanup_orphaned_lti_classes(
    session: AsyncSession, dry_run: bool = False
) -> int:
    """Delete LTIClass rows that cannot be linked to a PingPong class.

    These are rows where class_id is NULL but status indicates a linked/error
    class. Pending rows are intentionally excluded because class_id can be NULL
    during setup.
    """

    orphan_filter = (
        models.LTIClass.class_id.is_(None),
        models.LTIClass.lti_status.in_([LTIStatus.LINKED, LTIStatus.ERROR]),
    )

    count_stmt = select(func.count()).where(*orphan_filter).select_from(models.LTIClass)
    count_result = await session.execute(count_stmt)
    orphaned_count = int(count_result.scalar() or 0)
    logger.info("Found %s orphaned LTIClass rows", orphaned_count)

    if orphaned_count == 0 or dry_run:
        return orphaned_count

    delete_stmt = delete(models.LTIClass).where(*orphan_filter)
    await session.execute(delete_stmt)
    await session.flush()
    logger.info("Deleted %s orphaned LTIClass rows", orphaned_count)
    return orphaned_count
