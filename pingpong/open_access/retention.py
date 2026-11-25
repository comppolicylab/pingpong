import logging
from datetime import datetime, timedelta

from sqlalchemy import delete, exists, select

import pingpong.models as models
from ..config import config
from ..now import utcnow
from .threads import delete_thread

logger = logging.getLogger(__name__)

INACTIVITY = timedelta(days=30)
BATCH_SIZE = 100


async def purge_inactive(now: datetime | None = None) -> tuple[int, int]:
    cutoff = (now or utcnow()) - INACTIVITY
    threads_deleted = 0
    await config.authz.driver.init()
    async with config.authz.driver.get_client() as authz:
        while True:
            async with config.db.driver.async_session() as session:
                threads = (
                    await session.scalars(
                        select(models.Thread)
                        .where(
                            models.Thread.external_principal_id.is_not(None),
                            models.Thread.last_activity < cutoff,
                        )
                        .limit(BATCH_SIZE)
                        .with_for_update(skip_locked=True)
                    )
                ).all()
                revokes = []
                for thread in threads:
                    revokes += await delete_thread(session, thread)
                    logger.info(
                        "Open Access retention deleted thread %s (principal %s, "
                        "class %s, last activity %s)",
                        thread.id,
                        thread.external_principal_id,
                        thread.class_id,
                        thread.last_activity.isoformat(),
                    )
                await session.commit()
            await authz.write_safe(revoke=revokes)
            threads_deleted += len(threads)
            if len(threads) < BATCH_SIZE:
                break
    async with config.db.driver.async_session() as session:
        principal_ids = (
            await session.scalars(
                delete(models.ExternalPrincipal)
                .where(
                    ~exists().where(
                        models.Thread.external_principal_id
                        == models.ExternalPrincipal.id
                    )
                )
                .returning(models.ExternalPrincipal.id)
            )
        ).all()
        await session.commit()
    for principal_id in principal_ids:
        logger.info("Open Access retention deleted principal %s", principal_id)
    principals_deleted = len(principal_ids)
    logger.info(
        "Open Access retention deleted %s threads and %s principals",
        threads_deleted,
        principals_deleted,
    )
    return threads_deleted, principals_deleted
