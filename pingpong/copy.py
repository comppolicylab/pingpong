import json
import logging
import openai
from openai.types.beta.assistant_create_params import ToolResources
from pingpong import models
from pingpong.ai import (
    format_instructions,
    get_azure_model_deployment_name_equivalent,
)
from pingpong.ai_models import get_reasoning_effort_map
from pingpong.auth import generate_auth_link
from pingpong.authz.base import Relation
from pingpong.authz.openfga import OpenFgaAuthzClient
from pingpong.config import config
from pingpong.files import _file_grants
from pingpong.invite import send_clone_group_failed, send_clone_group_notification
from pingpong.schemas import (
    ClonedGroupNotification,
    CopyClassRequest,
    CreateClass,
    VectorStoreType,
    InteractionMode,
)
from pingpong.vector_stores import create_vector_store
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


async def create_new_class_object(
    session: AsyncSession, institution_id: int, create: CreateClass
) -> models.Class:
    return await models.Class.create(session, institution_id, create)


async def create_new_class(
    session: AsyncSession,
    client: OpenFgaAuthzClient,
    institution_id: int,
    create: CreateClass,
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

        if new_class.any_can_share_assistant:
            grants.append(
                (
                    f"class:{new_class.id}#student",
                    "can_share_assistants",
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


async def copy_shared_files(
    session: AsyncSession,
    client: OpenFgaAuthzClient,
    source_class_id: int,
    target_class_id: int,
):
    shared_file_ids = await client.list(
        f"class:{source_class_id}",
        "parent",
        "class_file",
    )

    files = await models.File.get_all_by_ids_if_exist(session, shared_file_ids)

    await models.File.add_files_to_class(
        session, target_class_id, [f.id for f in files]
    )

    new_grants = []
    for file in files:
        new_grants.extend(_file_grants(file, target_class_id))

    await client.write_safe(grant=new_grants)


async def copy_supervisors(
    session: AsyncSession,
    client: OpenFgaAuthzClient,
    source_class_id: int,
    target_class_id: int,
):
    supervisor_ids = await client.list_entities(
        f"class:{source_class_id}",
        "supervisor",
        "user",
    )
    supervisors = await models.User.get_all_by_id_if_in_class(
        session, supervisor_ids, source_class_id
    )

    batch = list[Relation]()
    for supervisor in supervisors:
        for role in ["teacher", "student"]:
            batch.append((f"user:{supervisor.id}", role, f"class:{source_class_id}"))

    results = await client.check(batch)
    new_grants = []
    for i, supervisor in enumerate(supervisors):
        await models.UserClassRole.create(
            session,
            user_id=supervisor.id,
            class_id=target_class_id,
            subscribed_to_summaries=not supervisor.dna_as_create,
        )
        if results[i * 2]:
            new_grants.append(
                (f"user:{supervisor.id}", "teacher", f"class:{target_class_id}")
            )
        if results[i * 2 + 1]:
            new_grants.append(
                (f"user:{supervisor.id}", "student", f"class:{target_class_id}")
            )
    await client.write_safe(grant=new_grants)


async def copy_all_users(
    session: AsyncSession,
    client: OpenFgaAuthzClient,
    source_class_id: int,
    target_class_id: int,
):
    total_users = await models.Class.get_member_count(session, source_class_id)

    if total_users == 0:
        return

    offset = 0
    limit = 10

    new_grants: list[Relation] = []

    while offset < total_users:
        users = list[models.UserClassRole]()

        batch = list[Relation]()
        async for user in models.Class.get_members(
            session, source_class_id, offset=offset, limit=limit
        ):
            users.append(user)
            for role in ["teacher", "student"]:
                batch.append((f"user:{user.user_id}", role, f"class:{source_class_id}"))

        if not users:
            break

        results = await client.check(batch)
        for i, u in enumerate(users):
            await models.UserClassRole.create(
                session,
                user_id=u.user_id,
                class_id=target_class_id,
                subscribed_to_summaries=u.subscribed_to_summaries,
            )

            if results[i * 2]:
                new_grants.append(
                    (f"user:{u.user_id}", "teacher", f"class:{target_class_id}")
                )
            if results[i * 2 + 1]:
                new_grants.append(
                    (f"user:{u.user_id}", "student", f"class:{target_class_id}")
                )

        offset += len(users)

    await client.write_safe(grant=new_grants)


async def copy_vector_store(
    session: AsyncSession,
    client: OpenFgaAuthzClient,
    cli: openai.AsyncClient,
    target_class_id: int,
    old_vector_store_id: int,
) -> tuple[str, int]:
    files = await models.VectorStore.get_files_by_id(session, old_vector_store_id)
    vector_store_obj_id, vector_store_id = await create_vector_store(
        session,
        cli,
        str(target_class_id),
        [f.file_id for f in files],
        type=VectorStoreType.ASSISTANT,
    )

    await models.File.add_files_to_class(
        session, target_class_id, [f.id for f in files]
    )

    new_grants: list[Relation] = []

    for f in files:
        new_grants.extend(_file_grants(f, target_class_id))

    await client.write_safe(grant=new_grants)

    return vector_store_obj_id, vector_store_id


async def copy_assistant(
    session: AsyncSession,
    client: OpenFgaAuthzClient,
    cli: openai.AsyncClient,
    target_class_id: int,
    assistant: models.Assistant,
    *,
    new_name: str | None = None,
    require_published: bool = True,
    force_private: bool = False,
) -> models.Assistant | None:
    """
    Copy an assistant to the target class.

    Returns the new assistant on success, or None if require_published is True
    and the source assistant is not published.
    """
    if require_published and not assistant.published:
        return None

    new_vector_store_id, new_vector_store_obj_id = None, None
    if assistant.vector_store_id:
        new_vector_store_obj_id, new_vector_store_id = await copy_vector_store(
            session, client, cli, target_class_id, assistant.vector_store_id
        )

    if assistant.version <= 2:
        tool_resources: ToolResources = {}
        if new_vector_store_obj_id:
            tool_resources["file_search"] = {
                "vector_store_ids": [new_vector_store_obj_id]
            }

    new_assistant = models.Assistant(
        name=new_name or assistant.name,
        version=assistant.version,
        instructions=assistant.instructions,
        interaction_mode=assistant.interaction_mode,
        description=assistant.description,
        assistant_id="",
        use_latex=assistant.use_latex,
        use_image_descriptions=assistant.use_image_descriptions,
        hide_prompt=assistant.hide_prompt,
        locked=assistant.locked,
        tools=assistant.tools,
        model=assistant.model,
        temperature=assistant.temperature,
        reasoning_effort=assistant.reasoning_effort,
        verbosity=assistant.verbosity,
        assistant_should_message_first=assistant.assistant_should_message_first,
        class_id=target_class_id,
        vector_store_id=new_vector_store_id,
        creator_id=assistant.creator_id,
        published=None if force_private else assistant.published,
        should_record_user_information=assistant.should_record_user_information,
        allow_user_file_uploads=assistant.allow_user_file_uploads,
        allow_user_image_uploads=assistant.allow_user_image_uploads,
        hide_reasoning_summaries=assistant.hide_reasoning_summaries,
        hide_file_search_result_quotes=assistant.hide_file_search_result_quotes,
        hide_file_search_document_names=assistant.hide_file_search_document_names,
        hide_file_search_queries=assistant.hide_file_search_queries,
        hide_web_search_sources=assistant.hide_web_search_sources,
        hide_web_search_actions=assistant.hide_web_search_actions,
        hide_mcp_server_call_details=assistant.hide_mcp_server_call_details,
    )

    session.add(new_assistant)
    await session.flush()
    await session.refresh(new_assistant)

    if assistant.code_interpreter_files:
        await models.Assistant.copy_code_interpreter_files(
            session,
            assistant.id,
            new_assistant.id,
        )

        ci_file_ids = [f.id for f in assistant.code_interpreter_files]
        await models.File.add_files_to_class(session, target_class_id, ci_file_ids)
        ci_grants: list[Relation] = []
        for f in assistant.code_interpreter_files:
            ci_grants.extend(_file_grants(f, target_class_id))
        await client.write_safe(grant=ci_grants)

    if assistant.mcp_server_tools:
        new_mcp_servers = []
        for mcp_tool in assistant.mcp_server_tools:
            new_tool = await models.MCPServerTool.create(
                session,
                {
                    "display_name": mcp_tool.display_name,
                    "server_url": mcp_tool.server_url,
                    "headers": mcp_tool.headers,
                    "authorization_token": mcp_tool.authorization_token,
                    "description": mcp_tool.description,
                    "enabled": mcp_tool.enabled,
                    "created_by_user_id": mcp_tool.created_by_user_id,
                },
            )
            new_mcp_servers.append(new_tool)
        await models.Assistant.synchronize_assistant_mcp_server_tools(
            session, new_assistant.id, [s.id for s in new_mcp_servers], skip_delete=True
        )

    if assistant.version <= 2:
        code_interpreter_file_obj_ids = (
            await models.Assistant.get_code_interpreter_file_obj_ids_by_assistant_id(
                session, assistant.id
            )
        )

        if code_interpreter_file_obj_ids:
            tool_resources["code_interpreter"] = {
                "file_ids": code_interpreter_file_obj_ids
            }

        if new_assistant.interaction_mode == InteractionMode.VOICE:
            _model = "gpt-4o"
        else:
            _model = (
                get_azure_model_deployment_name_equivalent(assistant.model)
                if isinstance(cli, openai.AsyncAzureOpenAI)
                else assistant.model
            )

        reasoning_map = get_reasoning_effort_map(assistant.model)
        reasoning_effort = (
            reasoning_map.get(assistant.reasoning_effort)
            if assistant.reasoning_effort is not None
            else None
        )
        reasoning_extra_body = (
            {"reasoning_effort": reasoning_effort}
            if reasoning_effort is not None
            else {}
        )

        openai_assistant = await cli.beta.assistants.create(
            instructions=format_instructions(
                assistant.instructions,
                use_latex=assistant.use_latex,
                use_image_descriptions=assistant.use_image_descriptions,
            ),
            model=_model,
            tools=json.loads(assistant.tools) if assistant.tools else None,
            temperature=assistant.temperature,
            metadata={
                "class_id": str(target_class_id),
                "creator_id": str(assistant.creator_id),
            },
            tool_resources=tool_resources,
            extra_body=reasoning_extra_body,
        )

        new_assistant.assistant_id = openai_assistant.id
        await session.flush()
        await session.refresh(new_assistant)

    grants = [
        (f"class:{target_class_id}", "parent", f"assistant:{new_assistant.id}"),
        (f"user:{assistant.creator_id}", "owner", f"assistant:{new_assistant.id}"),
    ]

    if assistant.published and not force_private:
        grants.append(
            (
                f"class:{target_class_id}#member",
                "can_view",
                f"assistant:{new_assistant.id}",
            ),
        )

    await client.write_safe(grant=grants)
    return new_assistant


async def copy_moderator_published_assistants(
    session: AsyncSession,
    client: OpenFgaAuthzClient,
    cli: openai.AsyncClient,
    source_class_id: int,
    target_class_id: int,
):
    supervisor_ids = await client.list_entities(
        f"class:{source_class_id}",
        "supervisor",
        "user",
    )

    async for assistant in models.Assistant.async_get_published(
        session, source_class_id, supervisor_ids
    ):
        await copy_assistant(
            session,
            client,
            cli,
            target_class_id,
            assistant,
        )


async def copy_all_published_assistants(
    session: AsyncSession,
    client: OpenFgaAuthzClient,
    cli: openai.AsyncClient,
    source_class_id: int,
    target_class_id: int,
):
    async for assistant in models.Assistant.async_get_published(
        session, source_class_id
    ):
        await copy_assistant(
            session,
            client,
            cli,
            target_class_id,
            assistant,
        )


async def copy_group(
    copy_options: CopyClassRequest, cli: openai.AsyncClient, class_id: str, user_id: int
):
    async with config.db.driver.async_session() as session:
        async with config.authz.driver.get_client() as c:
            try:
                class_ = await models.Class.get_by_id(session, int(class_id))
                if not class_:
                    raise ValueError(f"Class with ID {class_id} not found")

                user = await models.User.get_by_id(session, user_id)
                if not user:
                    raise ValueError(f"User with ID {user_id} not found")

                target_institution_id = (
                    copy_options.institution_id or class_.institution_id
                )

                new_class_options = CreateClass(
                    name=copy_options.name,
                    term=copy_options.term,
                    api_key_id=class_.api_key_id,
                    private=copy_options.private,
                    any_can_create_assistant=copy_options.any_can_create_assistant,
                    any_can_share_assistant=copy_options.any_can_share_assistant,
                    any_can_publish_assistant=copy_options.any_can_publish_assistant,
                    any_can_publish_thread=copy_options.any_can_publish_thread,
                    any_can_upload_class_file=copy_options.any_can_upload_class_file,
                )

                new_class = await create_new_class(
                    session,
                    c,
                    target_institution_id,
                    new_class_options,
                    user_id,
                    user.dna_as_create,
                )

                await copy_shared_files(
                    session,
                    c,
                    class_.id,
                    new_class.id,
                )

                if copy_options.copy_users == "moderators":
                    await copy_supervisors(
                        session,
                        c,
                        class_.id,
                        new_class.id,
                    )
                elif copy_options.copy_users == "all":
                    await copy_all_users(
                        session,
                        c,
                        class_.id,
                        new_class.id,
                    )

                if copy_options.copy_assistants == "moderators":
                    await copy_moderator_published_assistants(
                        session,
                        c,
                        cli,
                        class_.id,
                        new_class.id,
                    )
                elif copy_options.copy_assistants == "all":
                    await copy_all_published_assistants(
                        session,
                        c,
                        cli,
                        class_.id,
                        new_class.id,
                    )

                magic_link = generate_auth_link(
                    user.id,
                    expiry=86_400,
                    redirect=f"/group/{new_class.id}",
                )

                await send_clone_group_notification(
                    config.email.sender,
                    ClonedGroupNotification(
                        email=user.email,
                        class_name=new_class.name,
                        link=magic_link,
                    ),
                    expires=86_400,
                )
                await session.commit()
            except Exception as e:
                try:
                    if user and user.email:
                        await send_clone_group_failed(
                            config.email.sender,
                            ClonedGroupNotification(
                                email=user.email,
                                class_name=class_.name
                                if class_
                                else "your existing group",
                                link=config.url(f"/group/{class_id}"),
                            ),
                        )
                except Exception as e2:
                    logger.exception(f"Failed to send clone group failed email: {e2}")
                await session.rollback()
                raise e
