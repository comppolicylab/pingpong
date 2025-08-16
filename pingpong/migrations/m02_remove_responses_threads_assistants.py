from sqlalchemy import update, delete
import openai
from pingpong.config import config
from pingpong.ai import get_details_from_api_error, get_openai_client_by_class_id
from pingpong.authz.openfga import OpenFgaAuthzClient
from pingpong.vector_stores import (
    delete_vector_store_db,
    delete_vector_store_db_returning_file_ids,
    delete_vector_store_oai,
)
import pingpong.models as models
from sqlalchemy.ext.asyncio import AsyncSession

import logging

logger = logging.getLogger(__name__)


async def delete_thread(
    session: AsyncSession, auth: OpenFgaAuthzClient, thread_id: int
) -> None:
    thread = await models.Thread.get_by_id(session, thread_id)
    # Detach the vector store from the thread and delete it
    vector_store_obj_id = None
    file_ids_to_delete = []
    if thread.vector_store_id:
        vector_store_id = thread.vector_store_id
        thread.vector_store_id = None
        # Keep the OAI vector store ID for deletion
        result_vector = await delete_vector_store_db_returning_file_ids(
            session, vector_store_id
        )
        vector_store_obj_id = result_vector.vector_store_id
        file_ids_to_delete.extend(result_vector.deleted_file_ids)

    # Remove any CI files associations with the thread
    stmt = (
        delete(models.code_interpreter_file_thread_association)
        .where(
            models.code_interpreter_file_thread_association.c.thread_id
            == int(thread.id)
        )
        .returning(models.code_interpreter_file_thread_association.c.file_id)
    )
    result_ci = await session.execute(stmt)
    file_ids_to_delete.extend([row[0] for row in result_ci.fetchall()])

    # Remove any image files associations with the thread
    stmt = (
        delete(models.image_file_thread_association)
        .where(models.image_file_thread_association.c.thread_id == int(thread.id))
        .returning(models.image_file_thread_association.c.file_id)
    )
    result_image = await session.execute(stmt)
    file_ids_to_delete.extend([row[0] for row in result_image.fetchall()])

    revokes = [(f"class:{thread.class_id}", "parent", f"thread:{thread.id}")] + [
        (f"user:{u.id}", "party", f"thread:{thread.id}") for u in thread.users
    ]

    if not thread.private:
        revokes.append(
            (f"class:{thread.class_id}#member", "can_view", f"thread:{thread.id}"),
        )

    if thread.voice_mode_recording:
        try:
            await config.audio_store.store.delete_file(
                key=thread.voice_mode_recording.recording_id
            )
            await models.VoiceModeRecording.delete(
                session, thread.voice_mode_recording.id
            )
        except Exception as e:
            logger.exception(
                "Error deleting voice mode recording for thread %s: %s",
                thread.id,
                e,
            )

    # Keep the OAI thread ID for deletion
    await thread.delete(session)

    openai_client = await get_openai_client_by_class_id(session, thread.class_id)

    # Delete vector store as late as possible to avoid orphaned thread
    if vector_store_obj_id:
        await delete_vector_store_oai(openai_client, vector_store_obj_id)

    if thread.thread_id:
        try:
            await openai_client.beta.threads.delete(thread.thread_id)
        except openai.NotFoundError:
            pass
        except openai.BadRequestError as e:
            logger.warning(
                "OpenAI rejected request to delete thread %s: %s",
                thread.id,
                e,
            )

    # clean up grants
    await auth.write_safe(revoke=revokes)


async def delete_assistant(
    session: AsyncSession, auth: OpenFgaAuthzClient, assistant_id: int
) -> None:
    asst = await models.Assistant.get_by_id(session, int(assistant_id))

    # Detach the vector store from the assistant and delete it
    vector_store_obj_id = None
    if asst.vector_store_id:
        vector_store_id = asst.vector_store_id
        asst.vector_store_id = None
        # Keep the OAI vector store ID for deletion
        vector_store_obj_id = await delete_vector_store_db(session, vector_store_id)

    # Remove any CI files associations with the assistant
    stmt = delete(models.code_interpreter_file_assistant_association).where(
        models.code_interpreter_file_assistant_association.c.assistant_id
        == int(asst.id)
    )
    await session.execute(stmt)

    revokes = [
        (f"class:{asst.class_id}", "parent", f"assistant:{asst.id}"),
        (f"user:{asst.creator_id}", "owner", f"assistant:{asst.id}"),
    ]

    if asst.published:
        revokes.append(
            (f"class:{asst.class_id}#member", "can_view", f"assistant:{asst.id}"),
        )

    _stmt = (
        update(models.Thread)
        .where(models.Thread.assistant_id == int(asst.id))
        .values(assistant_id=None)
    )
    await session.execute(_stmt)

    # Keep the OAI assistant ID for deletion
    assistant_id = asst.assistant_id
    await models.Assistant.delete(session, asst.id)

    openai_client = await get_openai_client_by_class_id(session, asst.class_id)
    # Delete vector store as late as possible to avoid orphaned assistant
    if vector_store_obj_id:
        await delete_vector_store_oai(openai_client, vector_store_obj_id)

    if assistant_id:
        try:
            await openai_client.beta.assistants.delete(assistant_id)
        except openai.NotFoundError:
            pass
        except openai.BadRequestError as e:
            logger.warning(
                "OpenAI rejected request to delete assistant %s: %s",
                assistant_id,
                get_details_from_api_error(e, "OpenAI rejected this request"),
            )

    # clean up grants
    await auth.write_safe(revoke=revokes)


async def remove_responses_threads_assistants(
    session: AsyncSession, auth: OpenFgaAuthzClient
) -> None:
    async for assistant in models.Assistant.get_all_assistants_by_version(session, 3):
        assistant_id = assistant.id
        await delete_assistant(session, auth, assistant_id)
    async for thread in models.Thread.get_all_threads_by_version(session, 3):
        thread_id = thread.id
        await delete_thread(session, auth, thread_id)

    await session.commit()
