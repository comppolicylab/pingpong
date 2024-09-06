import asyncio
import json
from sqlalchemy import delete, update
from sqlalchemy.ext.asyncio import AsyncSession

from pingpong.config import config
from pingpong.authz.base import Relation
from pingpong.authz.openfga import OpenFgaAuthzClient, ReadRequestTupleKey
from pingpong.models import (
    Assistant,
    Class,
    ExternalLogin,
    User,
    UserClassRole,
    UserInstitutionRole,
    user_thread_association,
    File,
)


async def merge(
    session: AsyncSession,
    client: OpenFgaAuthzClient,
    new_user_id: int,
    old_user_id: int,
) -> "User":
    await asyncio.gather(
        merge_classes(session, new_user_id, old_user_id),
        merge_institutions(session, new_user_id, old_user_id),
        merge_assistants(session, new_user_id, old_user_id),
        merge_threads(session, new_user_id, old_user_id),
        merge_lms_users(session, new_user_id, old_user_id),
        merge_external_logins(session, new_user_id, old_user_id),
        merge_user_files(session, new_user_id, old_user_id),
        merge_permissions(client, new_user_id, old_user_id),
    )
    return await merge_users(session, new_user_id, old_user_id)


async def merge_classes(
    session: AsyncSession, new_user_id: int, old_user_id: int
) -> None:
    upsert_stmt = """
    INSERT INTO users_classes (user_id, class_id, role, title, lms_tenant, lms_type)
    SELECT :new_user_id, class_id, role, title, lms_tenant, lms_type
    FROM users_classes
    WHERE user_id = :old_user_id
    ON CONFLICT (user_id, class_id) DO NOTHING
    """

    await session.execute(
        upsert_stmt, {"new_user_id": new_user_id, "old_user_id": old_user_id}
    )

    stmt_delete_old_user = delete(UserClassRole).where(
        UserClassRole.user_id == old_user_id
    )
    await session.execute(stmt_delete_old_user)


async def merge_institutions(
    session: AsyncSession, new_user_id: int, old_user_id: int
) -> None:
    upsert_stmt = """
    INSERT INTO users_institutions (user_id, institution_id, role, title)
    SELECT :new_user_id, institution_id, role, title
    FROM users_institutions
    WHERE user_id = :old_user_id
    ON CONFLICT (user_id, institution_id) DO NOTHING
    """

    await session.execute(
        upsert_stmt, {"new_user_id": new_user_id, "old_user_id": old_user_id}
    )

    # Remove the old user from all institutions
    delete_stmt = delete(UserInstitutionRole).where(
        UserInstitutionRole.user_id == old_user_id
    )
    await session.execute(delete_stmt)


async def merge_assistants(
    session: AsyncSession, new_user_id: int, old_user_id: int
) -> None:
    stmt = (
        update(Assistant)
        .where(Assistant.creator_id == old_user_id)
        .values(creator_id=new_user_id)
    )
    await session.execute(stmt)


async def merge_threads(
    session: AsyncSession, new_user_id: int, old_user_id: int
) -> None:
    stmt = (
        update(user_thread_association)
        .where(user_thread_association.c.user_id == old_user_id)
        .values(user_id=new_user_id)
    )
    await session.execute(stmt)


async def merge_lms_users(
    session: AsyncSession, new_user_id: int, old_user_id: int
) -> None:
    stmt = (
        update(Class)
        .where(Class.lms_user_id == old_user_id)
        .values(lms_user_id=new_user_id)
    )
    await session.execute(stmt)


async def merge_external_logins(
    session: AsyncSession, new_user_id: int, old_user_id: int
) -> None:
    upsert_stmt = """
    INSERT INTO external_logins (user_id, provider, identifier)
    SELECT :new_user_id, provider, identifier
    FROM external_logins
    WHERE user_id = :old_user_id
    ON CONFLICT (user_id, provider) DO NOTHING
    """

    await session.execute(
        upsert_stmt, {"new_user_id": new_user_id, "old_user_id": old_user_id}
    )

    # Remove the old user from all external logins
    delete_stmt = delete(ExternalLogin).where(ExternalLogin.user_id == old_user_id)
    await session.execute(delete_stmt)


async def merge_user_files(
    session: AsyncSession, new_user_id: int, old_user_id: int
) -> None:
    stmt = (
        update(File)
        .where(File.uploader_id == old_user_id)
        .values(uploader_id=new_user_id)
    )
    await session.execute(stmt)


def get_types() -> list[str]:
    """Get a list of object types used in the authz model."""
    with open(config.authz.driver.model_config) as f:
        model = json.load(f)
    return [t["type"] for t in model["type_definitions"]]


async def list_all_permissions(
    client: OpenFgaAuthzClient, user_id: int
) -> list[Relation]:
    """List all relationships a user has in the authz store."""
    user_key = f"user:{user_id}"
    all_tuple_sets = await asyncio.gather(
        *[
            client.read(
                ReadRequestTupleKey(
                    user=user_key,
                    object=f"{t}:",
                )
            )
            for t in get_types()
        ]
    )
    all_relations = [
        (tuple_set.user, tuple_set.relation, tuple_set.object)
        for tuple_set in all_tuple_sets
    ]

    return all_relations


async def merge_permissions(
    client: OpenFgaAuthzClient, new_user_id: int, old_user_id: int
) -> None:
    old_permissions = await list_all_permissions(client, old_user_id)
    new_permissions = [(f"user:{new_user_id}", r, o) for _, r, o in old_permissions]

    await client.write_safe(grant=new_permissions, revoke=old_permissions)


async def merge_users(
    session: AsyncSession, new_user_id: int, old_user_id: int
) -> "User":
    old_user = await User.get_by_id(session, old_user_id)
    new_user = await User.get_by_id(session, new_user_id)

    match old_user.state:
        case "verified":
            new_user.state = (
                "verified" if new_user.state != "banned" else new_user.state
            )
        case "banned":
            new_user.state = "banned"
        case _:
            pass

    new_user.super_admin = new_user.super_admin or old_user.super_admin
    stmt = delete(User).where(User.id == old_user_id)
    await session.execute(stmt)
    session.add(new_user)
    await session.flush()
    await session.refresh(new_user)
    return new_user
