import asyncio
import json
from typing import AsyncGenerator
from sqlalchemy import Select, and_, delete, exists, or_, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession
import logging

from pingpong.config import config
from pingpong.authz.base import Relation
from pingpong.authz.openfga import OpenFgaAuthzClient, ReadRequestTupleKey
from pingpong.models import (
    AgreementAcceptance,
    Assistant,
    Class,
    ExternalLogin,
    LTIClass,
    MCPServerTool,
    User,
    UserClassRole,
    UserInstitutionRole,
    _get_upsert_stmt,
    user_thread_association,
    user_merge_association,
    File,
)
from pingpong.schemas import MergedUserTuple

logger = logging.getLogger(__name__)


async def merge(
    session: AsyncSession,
    client: OpenFgaAuthzClient,
    new_user_id: int,
    old_user_id: int,
) -> "User":
    await merge_db_operations(session, new_user_id, old_user_id)
    await merge_permissions(client, new_user_id, old_user_id)
    return await merge_users(session, new_user_id, old_user_id)


async def merge_db_operations(
    session: AsyncSession,
    new_user_id: int,
    old_user_id: int,
):
    await merge_classes(session, new_user_id, old_user_id)
    await merge_institutions(session, new_user_id, old_user_id)
    await merge_assistants(session, new_user_id, old_user_id)
    await merge_threads(session, new_user_id, old_user_id)
    await merge_agreement_acceptances(session, new_user_id, old_user_id)
    await merge_mcp_created_by(session, new_user_id, old_user_id)
    await merge_mcp_updated_by(session, new_user_id, old_user_id)
    await merge_files(session, new_user_id, old_user_id)
    await merge_lms_users(session, new_user_id, old_user_id)
    await merge_lti_users(session, new_user_id, old_user_id)
    await merge_external_logins(session, new_user_id, old_user_id)
    await merge_user_files(session, new_user_id, old_user_id)


async def merge_missing_permissions(
    session: AsyncSession,
    client: OpenFgaAuthzClient,
    stmt: Select,
    obj_type: str,
    rel: str,
    new_user_id: int,
) -> None:
    result = await session.execute(stmt)
    grants: list[Relation] = []
    revokes: list[Relation] = []

    async def process_row(row):
        old_user_ids = await client.list_entities(f"{obj_type}:{row[0]}", rel, "user")

        grants.extend([(f"user:{new_user_id}", rel, f"{obj_type}:{row[0]}")])
        revokes.extend(
            [
                (f"user:{old_id}", rel, f"{obj_type}:{row[0]}")
                for old_id in old_user_ids
                if old_id != new_user_id
            ]
        )

    await asyncio.gather(*(process_row(row) for row in result))
    await client.write_safe(grant=grants, revoke=revokes)


async def merge_classes(
    session: AsyncSession, new_user_id: int, old_user_id: int
) -> None:
    upsert_stmt = text("""
    INSERT INTO users_classes (user_id, class_id, role, title, lms_tenant, lms_type)
    SELECT :new_user_id, class_id, role, title, lms_tenant, lms_type
    FROM users_classes
    WHERE user_id = :old_user_id
    ON CONFLICT (user_id, class_id) DO NOTHING
    """)

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
    upsert_stmt = text("""
    INSERT INTO users_institutions (user_id, institution_id, role, title)
    SELECT :new_user_id, institution_id, role, title
    FROM users_institutions
    WHERE user_id = :old_user_id
    ON CONFLICT (user_id, institution_id) DO NOTHING
    """)

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


async def merge_missing_assistant_permissions(
    client: OpenFgaAuthzClient, session: AsyncSession, new_user_id: int
) -> None:
    stmt = select(Assistant.id).where(Assistant.creator_id == new_user_id)
    await merge_missing_permissions(
        session, client, stmt, "assistant", "owner", new_user_id
    )


async def merge_threads(
    session: AsyncSession, new_user_id: int, old_user_id: int
) -> None:
    stmt = (
        update(user_thread_association)
        .where(user_thread_association.c.user_id == old_user_id)
        .values(user_id=new_user_id)
    )
    await session.execute(stmt)


async def merge_missing_thread_permissions(
    client: OpenFgaAuthzClient, session: AsyncSession, new_user_id: int
) -> None:
    # Working assumption is that only one persion is associated with a thread, as we currently don't have multiparty threads
    stmt = select(user_thread_association.c.thread_id).where(
        user_thread_association.c.user_id == new_user_id
    )
    await merge_missing_permissions(
        session, client, stmt, "thread", "party", new_user_id
    )


async def merge_lms_users(
    session: AsyncSession, new_user_id: int, old_user_id: int
) -> None:
    stmt = (
        update(Class)
        .where(Class.lms_user_id == old_user_id)
        .values(lms_user_id=new_user_id)
    )
    await session.execute(stmt)


async def merge_lti_users(
    session: AsyncSession, new_user_id: int, old_user_id: int
) -> None:
    stmt = (
        update(LTIClass)
        .where(LTIClass.setup_user_id == old_user_id)
        .values(setup_user_id=new_user_id)
    )
    await session.execute(stmt)


async def merge_agreement_acceptances(
    session: AsyncSession, new_user_id: int, old_user_id: int
) -> None:
    upsert_stmt = text("""
    INSERT INTO agreement_acceptances (user_id, agreement_id, policy_id, accepted_at)
    SELECT :new_user_id, agreement_id, policy_id, accepted_at
    FROM agreement_acceptances
    WHERE user_id = :old_user_id
    ON CONFLICT (user_id, agreement_id) DO NOTHING
    """)

    await session.execute(
        upsert_stmt, {"new_user_id": new_user_id, "old_user_id": old_user_id}
    )

    stmt_delete_old_user = delete(AgreementAcceptance).where(
        AgreementAcceptance.user_id == old_user_id
    )
    await session.execute(stmt_delete_old_user)


async def merge_files(
    session: AsyncSession, new_user_id: int, old_user_id: int
) -> None:
    stmt = (
        update(File)
        .where(File.uploader_id == old_user_id)
        .values(uploader_id=new_user_id)
    )
    await session.execute(stmt)


async def merge_mcp_created_by(
    session: AsyncSession, new_user_id: int, old_user_id: int
) -> None:
    stmt = (
        update(MCPServerTool)
        .where(MCPServerTool.created_by_user_id == old_user_id)
        .values(created_by_user_id=new_user_id)
    )
    await session.execute(stmt)


async def merge_mcp_updated_by(
    session: AsyncSession, new_user_id: int, old_user_id: int
) -> None:
    stmt = (
        update(MCPServerTool)
        .where(MCPServerTool.updated_by_user_id == old_user_id)
        .values(updated_by_user_id=new_user_id)
    )
    await session.execute(stmt)


async def merge_external_logins(
    session: AsyncSession, new_user_id: int, old_user_id: int
) -> None:
    existing_login = ExternalLogin.__table__.alias("existing_login")

    conflicting_login_exists = exists(
        select(1)
        .select_from(existing_login)
        .where(
            and_(
                existing_login.c.user_id == new_user_id,
                ExternalLogin.provider != "email",
                or_(
                    existing_login.c.provider == ExternalLogin.provider,
                    and_(
                        ExternalLogin.provider_id.is_not(None),
                        existing_login.c.provider_id == ExternalLogin.provider_id,
                    ),
                ),
            )
        )
    )

    move_stmt = (
        update(ExternalLogin)
        .where(
            and_(
                ExternalLogin.user_id == old_user_id,
                ~conflicting_login_exists,
            )
        )
        .values(user_id=new_user_id)
    )
    await session.execute(move_stmt)

    # Remove old-user logins that conflict with already-present new-user logins.
    delete_conflicting_stmt = delete(ExternalLogin).where(
        ExternalLogin.user_id == old_user_id
    )
    await session.execute(delete_conflicting_stmt)


async def merge_user_files(
    session: AsyncSession, new_user_id: int, old_user_id: int
) -> None:
    stmt = (
        update(File)
        .where(File.uploader_id == old_user_id)
        .values(uploader_id=new_user_id)
    )
    await session.execute(stmt)


async def merge_missing_user_file_permissions(
    client: OpenFgaAuthzClient, session: AsyncSession, new_user_id: int
) -> None:
    stmt = select(File.id).where(
        and_(File.uploader_id == new_user_id, File.private.is_(True))
    )
    await merge_missing_permissions(
        session, client, stmt, "user_file", "owner", new_user_id
    )


async def merge_missing_class_file_permissions(
    client: OpenFgaAuthzClient, session: AsyncSession, new_user_id: int
) -> None:
    stmt = select(File.id).where(
        and_(File.uploader_id == new_user_id, File.private.is_(False))
    )
    await merge_missing_permissions(
        session, client, stmt, "class_file", "owner", new_user_id
    )


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
        (client_tuple.user, client_tuple.relation, client_tuple.object)
        for tuple_set in all_tuple_sets
        for client_tuple in tuple_set
    ]

    return all_relations


async def get_merged_user_tuples(
    session: AsyncSession,
) -> AsyncGenerator[MergedUserTuple, None]:
    stmt = select(
        user_merge_association.c.user_id, user_merge_association.c.merged_user_id
    )
    result = await session.execute(stmt)
    for row in result:
        yield MergedUserTuple(current_user_id=row[0], merged_user_id=row[1])


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
    if not new_user:
        raise ValueError(f"New user {new_user_id} not found.")
    if not old_user:
        logging.warning(
            f"Old user {old_user_id} not found, continuing with adding the merge tuple only."
        )
    if old_user:
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
        update_merged_account_tuple_stmt = (
            update(user_merge_association)
            .where(user_merge_association.c.user_id == old_user_id)
            .values(user_id=new_user_id)
        )
        await session.execute(update_merged_account_tuple_stmt)
        delete_old_user_stmt = delete(User).where(User.id == old_user_id)
        await session.execute(delete_old_user_stmt)
    add_new_merge_tuple_stmt = (
        _get_upsert_stmt(session)(user_merge_association)
        .values(user_id=new_user_id, merged_user_id=old_user_id)
        .on_conflict_do_nothing(
            index_elements=["user_id", "merged_user_id"],
        )
    )
    await session.execute(add_new_merge_tuple_stmt)
    session.add(new_user)
    await session.flush()
    await session.refresh(new_user)
    return new_user
