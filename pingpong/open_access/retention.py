import logging
from datetime import datetime, timedelta

from sqlalchemy import delete, exists, select

import pingpong.models as models
from ..authz.base import AuthzClient
from ..config import config
from ..now import utcnow

logger = logging.getLogger(__name__)

INACTIVITY = timedelta(days=30)
BATCH_SIZE = 100


async def _purge_thread(session, authz: AuthzClient, thread: models.Thread) -> None:
    tokens = (
        await session.scalars(
            select(models.AnonymousSession.session_token).where(
                models.AnonymousSession.thread_id == thread.id
            )
        )
    ).all()
    await thread.delete(session)
    logger.info(
        "Open Access retention deleted thread %s (principal %s, class %s, "
        "last activity %s)",
        thread.id,
        thread.external_principal_id,
        thread.class_id,
        thread.last_activity.isoformat(),
    )
    await authz.write_safe(
        revoke=[
            (f"class:{thread.class_id}", "parent", f"thread:{thread.id}"),
            *(
                tuple_
                for token in tokens
                for tuple_ in (
                    (
                        f"anonymous_user:{token}",
                        "anonymous_party",
                        f"thread:{thread.id}",
                    ),
                    (
                        f"anonymous_user:{token}",
                        "can_view",
                        f"assistant:{thread.assistant_id}",
                    ),
                )
            ),
        ]
    )


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
                    )
                ).all()
                for thread in threads:
                    await _purge_thread(session, authz, thread)
                await session.commit()
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
