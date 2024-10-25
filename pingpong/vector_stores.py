import openai
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from .schemas import VectorStoreDeleteResponse, VectorStoreType

import pingpong.models as models


async def create_vector_store(
    session: AsyncSession,
    openai_client: openai.AsyncClient,
    class_id: str,
    file_search_file_ids: list[str],
    type: VectorStoreType,
    upload_to_oai: bool = True,
) -> tuple[str, int]:
    """
    Creates a new vector store with the give file_search file ids and class id

    Args:
        session (AsyncSession): SQLAlchemy session
        openai_client (openai.AsyncClient): OpenAI client
        class_id (str): class id of the vector store
        file_search_file_ids (list[str]): list of file ids to add to the vector store
        type (VectorStoreType): type of the vector store

    Returns:
        tuple[str, int]: vector store id (used for OpenAI API requests, and vector store object id (DB PK, used for database queries)
    """

    try:
        new_vector_store = await openai_client.beta.vector_stores.create(
            file_ids=file_search_file_ids if upload_to_oai else [],
            metadata={
                "class_id": class_id,
            },
        )

    except openai.BadRequestError as e:
        raise HTTPException(
            400, e.body.get("message") or e.message or "OpenAI rejected this request"
        )

    try:
        data = {
            "type": type,
            "class_id": int(class_id),
            "version": 2,
            "expires_at": None,
            "vector_store_id": new_vector_store.id,
        }
        vector_store_object_id = await models.VectorStore.create(
            session, data, file_search_file_ids
        )
    except Exception as e:
        await openai_client.beta.vector_stores.delete(new_vector_store.id)
        raise e

    return new_vector_store.id, vector_store_object_id


async def append_vector_store_files(
    session: AsyncSession,
    openai_client: openai.AsyncClient,
    vector_store_object_id: int,
    file_search_file_ids: list[str],
) -> str:
    """
    Adds the given file_search file ids to the vector store specified by vector_store_id
    (the OpenAI API vector store id). This is used to add files to a thread's vector store,
    for which we don't need to replace files, but simply add new ones, to save on DB calls.

    Args:
        session (AsyncSession): SQLAlchemy session
        openai_client (openai.AsyncClient): OpenAI client
        vector_store_object_id (int): DB PK of the vector store
        file_search_file_ids (list[str]): list of file ids to add to the vector store

    Returns:
        int: vector store object id (DB PK, used for database queries)
    """
    vector_store_id = await add_vector_store_files_to_db(
        session, vector_store_object_id, file_search_file_ids
    )

    try:
        await openai_client.beta.vector_stores.file_batches.create(
            vector_store_id, file_ids=file_search_file_ids
        )
    except openai.BadRequestError as e:
        raise HTTPException(
            400, e.body.get("message") or e.message or "OpenAI rejected this request"
        )

    return vector_store_id


async def add_vector_store_files_to_db(
    session: AsyncSession,
    vector_store_object_id: int,
    file_search_file_ids: list[str],
) -> str:
    """
    Adds the given file_search file ids to the vector store specified by vector_store_id (the PK).

    Args:
        session (AsyncSession): SQLAlchemy session
        openai_client (openai.AsyncClient): OpenAI client
        vector_store_object_id (int): DB PK of the vector store
        file_search_file_ids (list[str]): list of file ids to add to the vector store

    Returns:
        int: vector store object id (DB PK, used for database queries)
    """
    return await models.VectorStore.add_files_return_id(
        session, vector_store_object_id, file_search_file_ids
    )


async def sync_vector_store_files(
    session: AsyncSession,
    openai_client: openai.AsyncClient,
    vector_store_obj_id: int,
    file_search_file_ids: list[str],
) -> str:
    """
    Synchronizes the vector store associated files to reflect the given file_search file ids. It adds files  This is used when an assistant's files are updated, and we need to update the vector store with the new files.

    Args:
        session (AsyncSession): SQLAlchemy session
        openai_client (openai.AsyncClient): OpenAI client
        vector_store_object_id (int): DB PK of the vector store
        file_search_file_ids (list[str]): final list of file ids the vector store should end up with

    Returns:
        str: OpenAI API vector store id
    """
    (
        vector_store_id,
        file_ids_to_add,
        file_ids_to_remove,
    ) = await models.VectorStore.sync_files(
        session, vector_store_obj_id, file_search_file_ids
    )

    if file_ids_to_add:
        try:
            await openai_client.beta.vector_stores.file_batches.create(
                vector_store_id, file_ids=file_ids_to_add
            )
        except openai.BadRequestError as e:
            raise HTTPException(400, e.message or "OpenAI rejected this request")

    for file_id in file_ids_to_remove:
        try:
            await openai_client.beta.vector_stores.files.delete(
                file_id, vector_store_id=vector_store_id
            )
        # Don't raise an error if the file is already deleted
        except openai.NotFoundError:
            pass
        except openai.BadRequestError as e:
            raise HTTPException(400, e.message or "OpenAI rejected this request")
    return vector_store_id


async def delete_vector_store(
    session: AsyncSession,
    openai_client: openai.AsyncClient,
    vector_store_object_id: int,
) -> None:
    """
    Deletes the vector store with the given vector store object id (DB PK). This is used when an assistant is deleted, and we need to delete the vector store associated with them.

    Args:
        session (AsyncSession): SQLAlchemy session
        openai_client (openai.AsyncClient): OpenAI client
        vector_store_object_id (int): DB PK of the vector store
    """
    vector_store_id = await delete_vector_store_db(session, vector_store_object_id)

    await delete_vector_store_oai(openai_client, vector_store_id)


async def delete_vector_store_db(
    session: AsyncSession,
    vector_store_object_id: int,
) -> str:
    """
    Deletes the vector store from the DB with the given vector store object id (DB PK). This is used when an assistant is deleted, and we need to delete the vector store associated with them.

    Args:
        session (AsyncSession): SQLAlchemy session
        openai_client (openai.AsyncClient): OpenAI client
        vector_store_object_id (int): DB PK of the vector store

    Returns:
        str: vector store object id
    """
    vector_store_id = await models.VectorStore.get_vector_store_id_by_id(
        session, vector_store_object_id
    )

    await models.VectorStore.delete(session, vector_store_object_id)

    return vector_store_id


async def delete_vector_store_db_returning_file_ids(
    session: AsyncSession,
    vector_store_object_id: int,
) -> VectorStoreDeleteResponse:
    """
    Deletes the vector store from the DB with the given vector store object id (DB PK). This is used when an assistant is deleted, and we need to delete the vector store associated with them.

    Args:
        session (AsyncSession): SQLAlchemy session
        openai_client (openai.AsyncClient): OpenAI client
        vector_store_object_id (int): DB PK of the vector store

    Returns:
        str: vector store object id
        file_ids: list of file ids that were in the vector store
    """
    vector_store_id = await models.VectorStore.get_vector_store_id_by_id(
        session, vector_store_object_id
    )

    file_ids = await models.VectorStore.delete_return_file_ids(
        session, vector_store_object_id
    )

    return VectorStoreDeleteResponse(
        vector_store_id=vector_store_id, deleted_file_ids=file_ids
    )


async def delete_vector_store_oai(
    openai_client: openai.AsyncClient,
    vector_store_id: str,
) -> None:
    """
    Deletes the vector store from OpenAI's servers with the given vector store id (OpenAI API vector store id). This is used when an assistant is deleted, and we need to delete the vector store associated with them.

    Args:
        openai_client (openai.AsyncClient): OpenAI client
        vector_store_id (str): OpenAI API vector store id
    """
    try:
        await openai_client.beta.vector_stores.delete(vector_store_id)
    except openai.NotFoundError:
        pass
    except openai.BadRequestError as e:
        raise HTTPException(
            400, e.body.get("message") or e.message or "OpenAI rejected this request"
        )
