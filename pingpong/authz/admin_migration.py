from ..config import config
from ..models import Class
from .base import AuthzClient

import logging

import tqdm
from sqlalchemy import select

logger = logging.getLogger(__name__)


async def swap_class_admin_for_teacher(c: AuthzClient, all_classes: list[int]):
    """Find users who are class admins and swap them to teachers."""
    logger.info("Swapping group admin role for teacher role ...")
    total_migrated = 0
    for class_id in tqdm.tqdm(all_classes):
        # Use `expand` instead of `list-users` since we want to *ignore* everyone
        # who has *inherited* permissions. Expand at level 1 will only return
        # the direct assignments within the class.
        expand_result = await c.expand(f"class:{class_id}", "admin", max_depth=1)
        users_with_admin = [rel.entity for rel in expand_result if not rel.is_group]
        await c.write_safe(
            grant=[(u, "teacher", f"class:{class_id}") for u in users_with_admin],
            revoke=[(u, "admin", f"class:{class_id}") for u in users_with_admin],
        )
        total_migrated += len(users_with_admin)
    logger.info(f"Swapped {total_migrated} user(s) from admin to teacher role.")


async def swap_class_admin_group_for_supervisor_group(
    c: AuthzClient, all_classes: list[int]
):
    """Find groups where admins can manage assistants and grant to supervisors."""
    logger.info("Swapping group admin group for supervisor group ...")
    total_migrated = 0
    for class_id in tqdm.tqdm(all_classes):
        # NOTE that since supervisor is a supserset of admin, this will always be true even
        # after classes are migrated. That's ok, since the update is idempotent.
        checks = await c.check(
            [(f"class:{class_id}#admin", "can_manage_assistants", f"class:{class_id}")]
        )
        if checks[0]:
            await c.write_safe(
                grant=[
                    (
                        f"class:{class_id}#supervisor",
                        "can_manage_assistants",
                        f"class:{class_id}",
                    )
                ],
                revoke=[
                    (
                        f"class:{class_id}#admin",
                        "can_manage_assistants",
                        f"class:{class_id}",
                    )
                ],
            )
            total_migrated += 1
    logger.info(f"Swapped {total_migrated} group(s) from admin to supervisor group.")


async def remove_class_admin_perms():
    """Clean up any `admin` permissions assigned on a class level.

    1) Swap class `admin` for `teacher`
    2) Swap `class:#admin` group for `class:#supervisor` where it is set in `can_manage_assistants`
    """
    logger.info("Updating group admin permissions ...")
    await config.authz.driver.init()
    async with config.db.driver.async_session() as session:
        all_classes = await session.execute(select(Class))
        all_class_ids = [c.id for c in all_classes.scalars()]

    logger.info(f"Found {len(all_class_ids)} groups to migrate.")

    async with config.authz.driver.get_client() as c:
        await swap_class_admin_for_teacher(c, all_class_ids)
        await swap_class_admin_group_for_supervisor_group(c, all_class_ids)

    logger.info("Group admin permissions updated.")
