import io
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import TypeGuard

import uuid_utils as uuid
from openai.types.beta.threads import (
    Annotation as OpenAIAnnotation,
)
from openai.types.beta.threads import (
    ImageFileContentBlock,
    TextContentBlock,
)
from openai.types.beta.threads import (
    Message as OpenAIMessage,
)
from openai.types.beta.threads.message_content import MessageContent
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import contains_eager, selectinload

import pingpong.models as models
import pingpong.schemas as schemas
from pingpong.ai import get_openai_client_by_class_id
from pingpong.config import config
from pingpong.files import file_extension_to_mime_type, _is_ci_supported
from pingpong.server import OpenAIClient

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ThreadMessages:
    thread: models.Thread
    messages: list[models.Message]


async def migrate_message_parts(
    session: AsyncSession,
) -> None:
    """Backfill MessageParts/Annotations for messages created by m15. This migration
    fetches those same upstream messages (from m15) and stores their parts and
    annotations locally.
    """

    openai_clients_by_class_id: dict[int, OpenAIClient] = {}
    failed_class_ids: set[int] = set()

    for local_message in await _fetch_message_fields(session):
        class_id = local_message.thread.class_id
        if class_id in failed_class_ids:
            continue

        openai_client = openai_clients_by_class_id.get(class_id)
        if openai_client is None:
            try:
                openai_client = await get_openai_client_by_class_id(session, class_id)
                openai_clients_by_class_id[class_id] = openai_client
            except Exception:
                logger.exception(
                    "Could not get OpenAI client for class during message part "
                    f"backfill. class_id={class_id}",
                )
                failed_class_ids.add(class_id)
                continue

        async with session.begin_nested() as savepoint:
            try:
                await _migrate_message_parts(session, openai_client, local_message)
            except Exception:
                await savepoint.rollback()
                logger.exception(
                    f"Unexpected error backfilling message parts. "
                    f"thread_id={local_message.thread_id} "
                    f"openai_thread_id={local_message.thread.thread_id}"
                )

        await session.commit()


async def _fetch_message_fields(
    session: AsyncSession,
) -> list[models.Message]:
    """
    Selects messages whose metadata marks the m15 migration as "complete" and that
    have an upstream OpenAI message_id, while excluding any message that already has
    a MessagePart, so the backfill is idempotent.
    Messages are ordered by class, thread, and output index to keep related
    messages grouped, and OpenAI clients can be reused per class. The thread (with its
    anonymous sessions) and run are fetched in advance.

    `group_by` combines message rows into one row per group, but we need every
    individual message row to back-fill its parts, so grouping would get rid of the rows
    we're trying to iterate over.

    The options for pre-loading threads, anonymous sessions, and runs are necessary
    because SQLAlchemy doesn't lazily load those fields in an async context.
    """

    stmt = (
        select(models.Message)
        .join(models.Thread, models.Message.thread_id == models.Thread.id)
        .outerjoin(
            models.MessagePart, models.MessagePart.message_id == models.Message.id
        )
        .where(
            models.Message.message_metadata[
                "assistants_to_responses_api_thread_migration"
            ]["message"].as_string()
            == "complete",
            models.Message.message_id.is_not(None),
            models.MessagePart.id.is_(None),
        )
        .order_by(
            models.Thread.class_id.asc(),
            models.Thread.id.asc(),
            models.Message.output_index.asc(),
        )
        .options(
            contains_eager(models.Message.thread).selectinload(
                models.Thread.anonymous_sessions
            ),
            selectinload(models.Message.run),
        )
    )
    result = await session.execute(stmt)
    return list(result.scalars())


async def _migrate_message_parts(
    session: AsyncSession,
    openai_client: OpenAIClient,
    local_message: models.Message,
) -> None:
    openai_message = await openai_client.beta.threads.messages.retrieve(
        message_id=local_message.message_id,
        thread_id=local_message.thread.thread_id,
    )
    # Exception is handled by caller so that we can rollback if there's an error. So
    # no try-catch
    await _persist_message_parts(
        session,
        openai_client,
        openai_message,
        local_message,
    )

    await session.flush()


async def _persist_message_parts(
    session: AsyncSession,
    openai_client: OpenAIClient,
    openai_message: OpenAIMessage,
    local_message: models.Message,
) -> None:
    for part_index, content in enumerate(openai_message.content):
        part_data = await _create_message_part_data(
            session, openai_client, content, local_message, part_index
        )
        if part_data is None:
            logger.warning(
                f"Skipping unsupported message content block. "
                f"message_id={local_message.id} openai_message_id={openai_message.id} "
                f"content_type={content.type}",
            )
            continue

        message_part = await models.MessagePart.create(session, part_data)

        for annotation_index, annotation in enumerate(
            _get_annotations_for_content(content)
        ):
            annotation_data = await _create_annotation_data_and_persist_file(
                session,
                openai_client,
                annotation,
                local_message.thread,
                local_message,
                message_part.id,
                annotation_index,
            )
            if annotation_data is None:
                logger.warning(
                    f"Skipping unsupported message annotation. "
                    f"message_id={local_message.id} message_part_id={message_part.id} "
                    f"annotation_type={annotation.type}",
                )
                continue

            await models.Annotation.create(session, annotation_data)


async def _create_message_part_data(
    session: AsyncSession,
    openai_client: OpenAIClient,
    openai_message_content: MessageContent,
    local_message: models.Message,
    part_index: int,
) -> dict[str, object] | None:
    message_part_data: dict[str, object] = {
        "message_id": local_message.id,
        "part_index": part_index,
    }

    if _is_text_content(openai_message_content):
        message_part_data["type"] = (
            schemas.MessagePartType.INPUT_TEXT
            if local_message.role == schemas.MessageRole.USER
            else schemas.MessagePartType.OUTPUT_TEXT
        )
        message_part_data["text"] = openai_message_content.text.value
        return message_part_data

    if _is_image_file_content(openai_message_content):
        local_file = await _fetch_or_create_local_file(
            session,
            openai_client,
            local_message.thread,
            local_message,
            openai_message_content.image_file.file_id,
        )
        if local_message.role == schemas.MessageRole.USER:
            await _backfill_s3_file(session, openai_client, local_file)
        message_part_data["type"] = schemas.MessagePartType.INPUT_IMAGE
        message_part_data["input_image_file_id"] = local_file.file_id
        message_part_data["input_image_file_object_id"] = local_file.id
        return message_part_data

    return None


async def _create_annotation_data_and_persist_file(
    session: AsyncSession,
    openai_client: OpenAIClient,
    annotation: OpenAIAnnotation,
    local_thread: models.Thread,
    local_message: models.Message,
    message_part_id: int,
    annotation_index: int,
) -> dict[str, object] | None:
    data: dict[str, object] = {
        "message_part_id": message_part_id,
        "annotation_index": annotation_index,
        "start_index": annotation.start_index,
        "end_index": annotation.end_index,
        "text": annotation.text,
    }

    if annotation.type == schemas.AnnotationType.FILE_CITATION:
        local_file = await _fetch_local_file(session, annotation.file_citation.file_id)
        data.update(
            {
                "type": schemas.AnnotationType.FILE_CITATION,
                "file_id": annotation.file_citation.file_id,
                "file_object_id": local_file.id if local_file else None,
                "filename": local_file.name if local_file else None,
            }
        )
        return data

    if annotation.type == schemas.AnnotationType.FILE_PATH:
        local_file = await _fetch_or_create_local_file(
            session,
            openai_client,
            local_thread,
            local_message,
            annotation.file_path.file_id,
        )
        await _backfill_s3_file(session, openai_client, local_file)
        data.update(
            {
                "type": schemas.AnnotationType.FILE_PATH,
                "file_id": local_file.file_id,
                "file_object_id": local_file.id if local_file else None,
                "filename": local_file.name if local_file else None,
            }
        )
        # NOTE: ideally we'd also upload the file to OpenAI so it can access it, but
        # that would incur a lot of extra complexity since we'd have to trace the
        # context (i.e., tool call, container, etc.) in which it was created. If the
        # user needs it they can ask for it to be re-generated.
        return data

    return None


async def _fetch_local_file(
    session: AsyncSession,
    openai_file_id: str,
) -> models.File | None:
    stmt = select(models.File).where(models.File.file_id == openai_file_id)
    return await session.scalar(stmt)


async def _fetch_or_create_local_file(
    session: AsyncSession,
    openai_client: OpenAIClient,
    local_thread: models.Thread,
    local_message: models.Message,
    openai_file_id: str,
) -> models.File:
    maybe_local_file = await _fetch_local_file(session, openai_file_id)
    if maybe_local_file:
        return maybe_local_file

    openai_file = await openai_client.files.retrieve(openai_file_id)
    content_type = file_extension_to_mime_type(openai_file.filename.split(".")[-1])
    (
        uploader_id,
        anonymous_session_id,
        anonymous_link_id,
    ) = await _get_anonymous_user_fields(session, local_thread, local_message)

    # used for updated too since that's not given by OpenAI
    created_dt = _require_dt(openai_file.created_at)

    local_file = await models.File.create(
        session,
        {
            "file_id": openai_file_id,
            "private": local_thread.private,
            "name": openai_file.filename,
            "content_type": content_type,
            "anonymous_session_id": anonymous_session_id,
            "anonymous_link_id": anonymous_link_id,
            "uploader_id": uploader_id,
            "created": created_dt,
            "updated": created_dt,
        },
        class_id=local_thread.class_id,
    )

    if _is_ci_supported(local_file.content_type):
        await models.Thread.add_code_interpreter_files(
            session=session,
            thread_id=local_thread.thread_id,
            file_ids=[openai_file_id],
        )

    return local_file


async def _get_anonymous_user_fields(
    session: AsyncSession,
    local_thread: models.Thread,
    local_message: models.Message,
) -> tuple[int | None, int | None, int | None]:
    uploader_id = local_message.user_id

    if uploader_id is None and len(local_thread.users) > 0:
        for user in local_thread.users:
            if user.anonymous_link_id is None:
                uploader_id = user.id

    if uploader_id is None and local_message.run is not None:
        uploader_id = local_message.run.creator_id

    if uploader_id is None:
        return None, None, None

    user = await models.User.get_by_id(session, uploader_id)
    if user is None:
        return uploader_id, None, None

    anonymous_session_id = None
    for anonymous_session in local_thread.anonymous_sessions:
        if anonymous_session.user_id == uploader_id:
            anonymous_session_id = anonymous_session.id
            break

    if anonymous_session_id is None:
        stmt = select(models.AnonymousSession.id).where(
            models.AnonymousSession.thread_id == local_thread.id,
            models.AnonymousSession.user_id == uploader_id,
        )
        anonymous_session_id = await session.scalar(stmt)

    return uploader_id, anonymous_session_id, user.anonymous_link_id


async def _backfill_s3_file(
    session: AsyncSession,
    openai_client: OpenAIClient,
    local_file: models.File,
) -> None:
    if local_file.s3_file_id is not None:
        return

    try:
        response = await openai_client.files.with_raw_response.retrieve_content(
            local_file.file_id
        )
        if response.status_code != 200:
            logger.exception(
                f"OpenAI returned {response.status_code} while fetching file "
                f"(id: {local_file.id})"
            )
            return
    except Exception:
        logger.exception(
            "Could not fetch file from OpenAI during message part migration. "
            f"file_id={local_file.file_id} file_object_id={local_file.id}",
        )
        return

    # filename generation taken from `pingpong.files.handle_create_file`
    suffix = Path(local_file.name or "").suffix.lower()
    store_key = f"file_{uuid.uuid4()}{suffix}"
    content_type = local_file.content_type

    try:
        await config.file_store.store.put(
            store_key, io.BytesIO(response.content), content_type
        )
    except Exception:
        logger.exception(
            "Could not store file in S3 during message part migration. "
            f"file_id={local_file.file_id} file_object_id={local_file.id}",
        )
        return

    await models.S3File.create(
        session,
        key=store_key,
        file_obj_ids=[local_file.id],
        file_ids=[local_file.file_id],
    )
    await session.refresh(local_file)


def _get_annotations_for_content(content: MessageContent) -> list[OpenAIAnnotation]:
    if not _is_text_content(content):
        return []
    return list(content.text.annotations or [])


def _is_image_file_content(
    content: MessageContent,
) -> TypeGuard[ImageFileContentBlock]:
    return content.type == "image_file"


def _is_text_content(
    content: MessageContent,
) -> TypeGuard[TextContentBlock]:
    return content.type == "text"


def _require_dt(timestamp: int) -> datetime:
    return datetime.fromtimestamp(timestamp, tz=timezone.utc)
