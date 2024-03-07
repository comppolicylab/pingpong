import logging

from sqlalchemy import false, select, true
from sqlalchemy.ext.asyncio import AsyncSession

from ..models import Assistant, Class, File, Institution, Thread, User
from ..schemas import Role
from .base import AuthzClient, Relation

logger = logging.getLogger(__name__)


async def sync_db_to_openfga(db: AsyncSession, authz: AuthzClient) -> None:
    """Translate database objects to OpenFga permissions.

    Args:
        db (AsyncSession): The database session.
        authz (AuthzDriver): The OpenFga driver.
    """
    ###########################################################################
    # Super Users
    logger.info("Syncing super users ...")
    stmt = select(User).where(User.super_admin == true())
    super_admins = await db.execute(stmt)
    grants = list[Relation]()
    for user in super_admins.scalars():
        logger.info(f" - Creating root user {user.id} ...")
        grants.append((f"user:{user.id}", "admin", authz.root))
    await authz.write_safe(grant=grants)

    ###########################################################################
    # Institutions
    logger.info("Syncing institutions ...")
    stmt = select(Institution)
    institutions = await db.execute(stmt)
    grants = list[Relation]()
    for institution in institutions.scalars():
        logger.info(f" - Creating institution {institution.id} ...")
        grants.append((authz.root, "parent", f"institution:{institution.id}"))
    await authz.write_safe(grant=grants)

    ###########################################################################
    # Classes
    logger.info("Syncing classes ...")
    stmt = select(Class)
    classes = await db.execute(stmt)
    grants = list[Relation]()
    class_ids = list[int]()
    for class_ in classes.scalars():
        logger.info(f" - Creating class {class_.id} ...")
        class_ids.append(class_.id)
        grants.append(
            (f"institution:{class_.institution_id}", "parent", f"class:{class_.id}")
        )
        if class_.any_can_create_assistant:
            grants.append(
                (
                    f"class:{class_.id}#student",
                    "can_create_assistants",
                    f"class:{class_.id}",
                )
            )
        if class_.any_can_publish_assistant:
            grants.append(
                (
                    f"class:{class_.id}#student",
                    "can_publish_assistants",
                    f"class:{class_.id}",
                )
            )
    await authz.write_safe(grant=grants)

    ###########################################################################
    # Class Users
    logger.info("Syncing class user roles ...")
    grants = list[Relation]()
    for class_id in class_ids:
        members = await Class.get_members(db, class_id)
        for member in members:
            if member.role == Role.ADMIN:
                logger.info(f" - Making {member.user_id} admin of {class_id} ...")
                grants.append((f"user:{member.user_id}", "admin", f"class:{class_id}"))
            elif member.title in {"Course Assistant", "Professor"}:
                logger.info(f" - Making {member.user_id} teacher of {class_id} ...")
                grants.append(
                    (f"user:{member.user_id}", "teacher", f"class:{class_id}")
                )
            elif member.title == "Student":
                logger.info(f" - Making {member.user_id} student of {class_id} ...")
                grants.append(
                    (f"user:{member.user_id}", "student", f"class:{class_id}")
                )
    await authz.write_safe(grant=grants)

    ###########################################################################
    # Threads
    logger.info("Syncing threads ...")
    grants = list[Relation]()
    stmt = select(Thread)
    threads = await db.execute(stmt)
    for thread in threads.scalars():
        logger.info(f" - Creating permissions on thread {thread.id} ...")
        grants.append((f"class:{thread.class_id}", "parent", f"thread:{thread.id}"))
        for user in thread.users:
            grants.append((f"user:{user.id}", "party", f"thread:{thread.id}"))
    await authz.write_safe(grant=grants)

    ###########################################################################
    # Assistants
    logger.info("Syncing assistants ...")
    grants = list[Relation]()
    stmt = select(Assistant)
    assistants = await db.execute(stmt)
    for assistant in assistants.scalars():
        logger.info(f" - Creating permissions on assistant {assistant.id} ...")
        grants.append(
            (f"class:{assistant.class_id}", "parent", f"assistant:{assistant.id}")
        )
        grants.append(
            (f"user:{assistant.creator_id}", "owner", f"assistant:{assistant.id}")
        )
        if assistant.published:
            grants.append(
                (
                    f"class:{assistant.class_id}#member",
                    "can_view",
                    f"assistant:{assistant.id}",
                )
            )
    await authz.write_safe(grant=grants)

    ###########################################################################
    # Class Files
    logger.info("Syncing class files ...")
    stmt = select(File).where(File.private == false())
    class_files = await db.execute(stmt)
    grants = list[Relation]()
    for file in class_files.scalars():
        logger.info(f" - Creating permissions on file {file.id} ...")
        grants.append((f"class:{file.class_id}", "parent", f"class_file:{file.id}"))
        grants.append((f"user:{file.uploader_id}", "owner", f"class_file:{file.id}"))
    await authz.write_safe(grant=grants)

    ###########################################################################
    # User Files
    logger.info("Syncing user files ...")
    stmt = select(File).where(File.private == true())
    user_files = await db.execute(stmt)
    grants = list[Relation]()
    for file in user_files.scalars():
        logger.info(f" - Creating permissions on file {file.id} ...")
        grants.append((f"class:{file.class_id}", "parent", f"user_file:{file.id}"))
        grants.append((f"user:{file.uploader_id}", "owner", f"user_file:{file.id}"))
        # NOTE - not syncing thread id because it's harder to figure out
    await authz.write_safe(grant=grants)
