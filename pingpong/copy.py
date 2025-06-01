import openai
from pingpong import models
from pingpong.authz.openfga import OpenFgaAuthzClient
from pingpong.config import config
from pingpong.schemas import CopyClassRequest, CreateClass
from sqlalchemy.ext.asyncio import AsyncSession


async def create_new_class_object(
    session: AsyncSession, institution_id: int, create: CopyClassRequest
) -> models.Class:
    return await models.Class.create(session, institution_id, create)


async def create_new_class(
    session: AsyncSession,
    client: OpenFgaAuthzClient,
    institution_id: int,
    create: CopyClassRequest,
    user_id: int,
    user_dna_as_create: bool,
) -> models.Class:
    new_class = await create_new_class_object(session, institution_id, create)

    # Create an entry for the creator as the owner
    ucr = models.UserClassRole(
        user_id=user_id,
        class_id=new_class.id,
        subscribed_to_summaries=not user_dna_as_create,
    )
    session.add(ucr)

    grants = [
        (f"institution:{institution_id}", "parent", f"class:{new_class.id}"),
        (f"user:{user_id}", "teacher", f"class:{new_class.id}"),
    ]

    if not new_class.private:
        grants.append(
            (
                f"class:{new_class.id}#supervisor",
                "can_manage_threads",
                f"class:{new_class.id}",
            )
        )
        grants.append(
            (
                f"class:{new_class.id}#supervisor",
                "can_manage_assistants",
                f"class:{new_class.id}",
            )
        )

    if new_class.any_can_create_assistant:
        grants.append(
            (
                f"class:{new_class.id}#student",
                "can_create_assistants",
                f"class:{new_class.id}",
            )
        )

    if new_class.any_can_publish_assistant:
        grants.append(
            (
                f"class:{new_class.id}#student",
                "can_publish_assistants",
                f"class:{new_class.id}",
            )
        )

    if new_class.any_can_publish_thread:
        grants.append(
            (
                f"class:{new_class.id}#student",
                "can_publish_threads",
                f"class:{new_class.id}",
            )
        )

    if new_class.any_can_upload_class_file:
        grants.append(
            (
                f"class:{new_class.id}#student",
                "can_upload_class_files",
                f"class:{new_class.id}",
            )
        )

    await client.write(grant=grants)

    return new_class


async def copy_group(
    copy_options: CopyClassRequest, cli: openai.AsyncClient, class_id: str, user_id: int
):
    async with config.db.driver.async_session() as session:
        async with config.authz.driver.get_client() as c:
            class_ = await models.Class.get_by_id(session, int(class_id))
            if not class_:
                raise ValueError(f"Class with ID {class_id} not found")

            user = await models.User.get_by_id(session, user_id)
            if not user:
                raise ValueError(f"User with ID {user_id} not found")

            new_class_options = CreateClass(
                name=copy_options.name,
                term=copy_options.term,
                api_key_id=class_.api_key_id,
                private=copy_options.private,
                any_can_create_assistant=copy_options.any_can_create_assistant,
                any_can_publish_assistant=copy_options.any_can_publish_assistant,
                any_can_publish_thread=copy_options.any_can_publish_thread,
                any_can_upload_class_file=copy_options.any_can_upload_class_file,
            )

            _ = await create_new_class(
                session,
                c,
                class_.institution_id,
                new_class_options,
                user_id,
                user.dna_as_create,
            )
