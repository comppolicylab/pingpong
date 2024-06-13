import json

from openai import AsyncClient
from openai.types.beta import Assistant as OpenAIAssistant
from openai.types.beta import Thread as OpenAIThread
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from .models import Assistant, VectorStore, Thread, File
from .schemas import VectorStoreType

from typing import AsyncGenerator, TypeVar


async def migrate_object(
    openai_client: AsyncClient,
    session: AsyncSession,
    local_obj: Assistant | Thread,
    class_id: int,
):
    openai_obj: OpenAIAssistant | OpenAIThread

    if isinstance(local_obj, Assistant):
        openai_obj = await openai_client.beta.assistants.retrieve(
            local_obj.assistant_id
        )
    elif isinstance(local_obj, Thread):
        openai_obj = await openai_client.beta.threads.retrieve(local_obj.thread_id)

    # Check if the object has file search (retrieval) tool enabled
    if (
        openai_obj.tool_resources
        and openai_obj.tool_resources.file_search
        and openai_obj.tool_resources.file_search.vector_store_ids
    ):
        # Get the vector store files
        vector_store_files = await openai_client.beta.vector_stores.files.list(
            openai_obj.tool_resources.file_search.vector_store_ids[0]
        )

        # Extract the file ids
        vector_store_file_ids = [f.id for f in vector_store_files.data]
        data = {
            "type": VectorStoreType.ASSISTANT
            if isinstance(local_obj, Assistant)
            else VectorStoreType.THREAD,
            "class_id": class_id,
            "expires_at": None,
            "vector_store_id": openai_obj.tool_resources.file_search.vector_store_ids[
                0
            ],
        }

        # Create a new vector store
        vector_store_object_id = await VectorStore.create(
            session,
            data,
            vector_store_file_ids,
        )

        # Associate the vector store with the local object
        local_obj.vector_store_id = vector_store_object_id

    # NOTE: Because we did not differentiate between the two tools in v1,
    # any files in column `files` might only be associated with file search
    # (retrieval), or both file search and code interpreter tools. If code
    # interpreter is disabled, we need to delete the files from the `files`
    # column.

    # Check if the code interpreter tool is enabled
    if (
        openai_obj.tool_resources
        and openai_obj.tool_resources.code_interpreter
        and openai_obj.tool_resources.code_interpreter.file_ids
    ):
        if isinstance(local_obj, Assistant):
            local_obj.code_interpreter_files = local_obj.files
        elif isinstance(local_obj, Thread):
            files = await File.get_all_by_file_id(
                session, openai_obj.tool_resources.code_interpreter.file_ids
            )
            local_obj.code_interpreter_files = files
    else:
        local_obj.code_interpreter_files = []

    # Bump object version
    local_obj.version = 2

    # Update object with available tools
    if isinstance(local_obj, Assistant):
        local_obj.tools = json.dumps([t.model_dump() for t in openai_obj.tools])
    elif isinstance(local_obj, Thread):
        local_obj.tools_available = local_obj.assistant.tools

    session.add(local_obj)
    await session.commit()


T = TypeVar("T", Thread, Assistant)


async def get_by_class_id_and_version(
    session: AsyncSession,
    object_type: type[T],
    class_id: int,
    version: int,
) -> AsyncGenerator["T", None]:
    stmt = (
        select(object_type)
        .where(object_type.class_id == int(class_id))
        .where(object_type.version == version)
    )
    if object_type == Thread:
        stmt = stmt.options(joinedload(Thread.assistant))
    result = await session.execute(stmt)
    if object_type == Thread:
        for row in result:
            yield row.Thread
    else:
        for row in result:
            yield row.Assistant
