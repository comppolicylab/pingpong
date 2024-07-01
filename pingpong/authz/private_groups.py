import logging

from .base import AuthzClient, Relation
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from ..models import Class

logger = logging.getLogger(__name__)


async def fetch_classes_to_migrate(session: AsyncSession, limit: int = 10) -> list[int]:
    """
    Fetch classes that need to be migrated to OpenFga.

    Args:
        session (AsyncSession): The database session.
        limit (int, optional): The maximum number of classes to fetch. Defaults to 10.

    Returns:
        list[int]: The list of class IDs.
    """
    stmt = (
        select(Class.id).where(Class.private.is_(None)).with_for_update().limit(limit)
    )
    result = await session.execute(stmt)
    return result.scalars().all()


async def update_objs_in_db(
    session: AsyncSession, classes_to_migrate: list[int]
) -> None:
    """
    Update the classes in the database.

    Args:
        session (AsyncSession): The database session.
        classes (list[int]): The list of class IDs.
    """
    stmt = update(Class).values(private=False).where(Class.id.in_(classes_to_migrate))
    await session.execute(stmt)


async def write_grants_to_openfga(
    authz: AuthzClient, classes_to_migrate: list[int]
) -> None:
    """
    Write the grants to OpenFga.

    Args:
        authz (AuthzClient): The OpenFga driver.
        classes_to_migrate (list[int]): The list of class IDs.

    """
    grants = list[Relation]()

    for class_id in classes_to_migrate:
        logger.info(f" - Adding permissions for class {class_id} ...")
        grants.append(
            (
                f"class:{class_id}#teacher",
                "can_manage_threads",
                f"class:{class_id}",
            )
        )
        grants.append(
            (
                f"class:{class_id}#admin",
                "can_manage_threads",
                f"class:{class_id}",
            )
        )
        grants.append(
            (
                f"class:{class_id}#admin",
                "can_manage_assistants",
                f"class:{class_id}",
            )
        )

    await authz.write_safe(grant=grants)
