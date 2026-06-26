import logging
from collections import defaultdict
from typing import Any

from openai.types.beta.threads import (
    Message as OpenAIMessage,
)
from sqlalchemy import Table, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy.orm.attributes import flag_modified

import pingpong.models as models
from pingpong.ai import get_openai_client_by_class_id
from pingpong.schemas import MessageRole
from pingpong.server import OpenAIClient

logger = logging.getLogger(__name__)


async def migrate_message_attachments(session: AsyncSession) -> None:
    """Backfill `file_search_attachments`/`code_interpreter_attachments` for messages
    created by m15. Assumes m15 and m16 have been run and that local `File` rows exist.
    If a `File` object is missing, we just skip adding it.
    """

    messages_by_class_id: dict[int, list[models.Message]] = defaultdict(list)
    local_messages_to_process = await _fetch_messages(session)
    for local_message in local_messages_to_process:
        messages_by_class_id[local_message.thread.class_id].append(local_message)
    logger.info(
        "m17 starting attachment migration. classes=%s messages=%s",
        len(messages_by_class_id),
        len(local_messages_to_process),
    )

    for class_id, local_messages in messages_by_class_id.items():
        try:
            openai_client = await get_openai_client_by_class_id(session, class_id)
        except Exception:
            logger.exception(
                "Could not get OpenAI client during message attachment "
                f"backfill. class_id={class_id}",
            )
            continue

        for local_message in local_messages:
            async with session.begin_nested() as savepoint:
                try:
                    await _migrate_message_attachments(
                        session, openai_client, local_message
                    )
                    local_message.message_metadata[
                        "assistants_to_responses_api_thread_migration"
                    ]["attachments"] = "complete"
                    # Notifies SQLAlchemy that `message_metadata` changed (since it's
                    # JSON it wouldn't be detected otherwise).
                    flag_modified(local_message, "message_metadata")
                except Exception:
                    await savepoint.rollback()
                    logger.exception(
                        f"Unexpected error backfilling message attachments. "
                        f"thread_id={local_message.thread_id} "
                        f"openai_thread_id={local_message.thread.thread_id}"
                    )

            await session.commit()


async def _fetch_messages(
    session: AsyncSession,
) -> list[models.Message]:
    migration_metadata = models.Message.message_metadata[
        "assistants_to_responses_api_thread_migration"
    ]
    message_parts_state = migration_metadata["message_parts"].as_string()
    attachments_state = migration_metadata["attachments"].as_string()

    stmt = (
        select(models.Message)
        .where(
            message_parts_state == "complete",
            models.Message.message_id.is_not(None),
            or_(
                attachments_state.is_(None),
                attachments_state != "complete",
            ),
            models.Message.role == MessageRole.USER,
        )
        .options(selectinload(models.Message.thread))
    )
    result = await session.execute(stmt)
    return list(result.scalars())


async def _migrate_message_attachments(
    session: AsyncSession,
    openai_client: OpenAIClient,
    local_message: models.Message,
) -> None:
    openai_message = await openai_client.beta.threads.messages.retrieve(
        message_id=local_message.message_id,
        thread_id=local_message.thread.thread_id,
    )
    # Exception is handled by the caller so the savepoint can roll back. No try-except.
    await _persist_message_attachments(session, openai_message, local_message)
    await session.flush()


async def _persist_message_attachments(
    session: AsyncSession,
    openai_message: OpenAIMessage,
    local_message: models.Message,
) -> None:
    attachments_seen = 0
    attachments_linked = 0
    attachments_skipped = 0
    for attachment in openai_message.attachments or []:
        attachments_seen += 1
        if attachment.file_id is None:
            attachments_skipped += 1
            logger.warning(
                f"Skipping attachment with no file_id. message_id={local_message.id} "
                f"openai_message_id={openai_message.id}",
            )
            continue

        tool_types = {
            tool.type for tool in (attachment.tools or []) if tool.type is not None
        }
        if not tool_types:
            attachments_skipped += 1
            logger.warning(
                f"Skipping attachment with no recognized tools. "
                f"message_id={local_message.id} openai_message_id={openai_message.id} "
                f"file_id={attachment.file_id}",
            )
            continue

        local_file, matched_via = await _fetch_local_file(
            session, local_message, attachment.file_id, tool_types
        )
        if local_file is None:
            attachments_skipped += 1
            # Skip missing file that should've been created by m16
            logger.warning(
                f"Skipping attachment whose local File is missing. "
                f"message_id={local_message.id} openai_message_id={openai_message.id} "
                f"file_id={attachment.file_id} tool_types={sorted(tool_types)} "
                f"thread_id={local_message.thread_id} "
                f"vector_store_id={local_message.thread.vector_store_id}",
            )
            continue

        logger.info(
            "m17 matched attachment file. message_pk=%s openai_file_id=%s "
            "local_file_id=%s tool_types=%s matched_via=%s",
            local_message.id,
            attachment.file_id,
            local_file.id,
            sorted(tool_types),
            matched_via,
        )

        if "file_search" in tool_types:
            await _attach_file(
                session,
                models.file_search_attachment_association,
                local_message.id,
                local_file.id,
            )
            attachments_linked += 1
            logger.info(
                "m17 attached file to message. message_pk=%s local_file_id=%s "
                "relation=file_search",
                local_message.id,
                local_file.id,
            )
        if "code_interpreter" in tool_types:
            await _attach_file(
                session,
                models.code_interpreter_attachment_association,
                local_message.id,
                local_file.id,
            )
            attachments_linked += 1
            logger.info(
                "m17 attached file to message. message_pk=%s local_file_id=%s "
                "relation=code_interpreter",
                local_message.id,
                local_file.id,
            )
    logger.info(
        "m17 migrated message attachments. message_pk=%s openai_message_id=%s "
        "attachments_seen=%s linked=%s skipped=%s",
        local_message.id,
        openai_message.id,
        attachments_seen,
        attachments_linked,
        attachments_skipped,
    )


async def _attach_file(
    session: AsyncSession,
    association_table: Table,
    message_id: int,
    file_object_id: int,
) -> None:
    stmt = (
        models._get_upsert_stmt(session)(association_table)
        .values(message_id=message_id, file_id=file_object_id)
        .on_conflict_do_nothing(index_elements=["message_id", "file_id"])
    )
    await session.execute(stmt)


async def _fetch_local_file(
    session: AsyncSession,
    local_message: models.Message,
    openai_file_id: str,
    tool_types: set[str],
) -> tuple[models.File | None, str | None]:
    file_available_to_thread: list[Any] = []
    if "code_interpreter" in tool_types:
        file_available_to_thread.append(
            models.File.id.in_(
                select(models.code_interpreter_file_thread_association.c.file_id).where(
                    models.code_interpreter_file_thread_association.c.thread_id
                    == local_message.thread_id
                )
            )
        )
    if "file_search" in tool_types and local_message.thread.vector_store_id is not None:
        file_available_to_thread.append(
            models.File.id.in_(
                select(models.file_vector_store_association.c.file_id).where(
                    models.file_vector_store_association.c.vector_store_id
                    == local_message.thread.vector_store_id
                )
            )
        )

    if not file_available_to_thread:
        return None, None

    stmt = select(models.File).where(
        models.File.file_id == openai_file_id, or_(*file_available_to_thread)
    )
    local_file = await session.scalar(stmt)
    if local_file is None:
        return None, None

    match_sources = []
    if "code_interpreter" in tool_types:
        code_interpreter_file_id = await session.scalar(
            select(models.code_interpreter_file_thread_association.c.file_id).where(
                models.code_interpreter_file_thread_association.c.thread_id
                == local_message.thread_id,
                models.code_interpreter_file_thread_association.c.file_id
                == local_file.id,
            )
        )
        if code_interpreter_file_id is not None:
            match_sources.append("code_interpreter_thread")
    if "file_search" in tool_types and local_message.thread.vector_store_id is not None:
        vector_store_file_id = await session.scalar(
            select(models.file_vector_store_association.c.file_id).where(
                models.file_vector_store_association.c.vector_store_id
                == local_message.thread.vector_store_id,
                models.file_vector_store_association.c.file_id == local_file.id,
            )
        )
        if vector_store_file_id is not None:
            match_sources.append("thread_vector_store")

    matched_via = (
        "both"
        if len(match_sources) > 1
        else match_sources[0]
        if match_sources
        else "unknown"
    )
    return local_file, matched_via
