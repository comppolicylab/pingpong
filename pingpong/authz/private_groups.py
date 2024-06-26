import logging

from .base import AuthzClient, Relation
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from ..models import Class

logger = logging.getLogger(__name__)

async def add_private_class_migration(db: AsyncSession, authz: AuthzClient) -> None:
    """
    Add permissions for non-private classes to OpenFga.
    Since all current classes are non-private, we can just add
      - all admins as auditors
      - all teachers as moderators

    Args:
        authz (AuthzClient): The OpenFga driver.
    """

    logger.info(" Getting all unmigrated classes ...")
    stmt = select(Class.id, Class.private).where(Class.private.is_(None))
    classes = await db.execute(stmt)
    
    classesToUpdate = list[int]()
    grants = list[Relation]()
    revokes = list[Relation]()
    
    for class_id in classes.scalars():
        logger.info(f" - Adding permissions for class {class_id} ...")
        grants.append(
            (
                f"class:{class_id}#teacher",
                "moderator",
                f"class:{class_id}",
            )
        )
        grants.append(
            (
                f"class:{class_id}#admin",
                "auditor",
                f"class:{class_id}",
            )
        )
        classesToUpdate.append(class_id)
    
    await authz.write_safe(grant=grants, revoke=revokes)
    
    stmt_ = update(Class).values(private = False).where(Class.id.in_(classesToUpdate))
    await db.execute(stmt_)
