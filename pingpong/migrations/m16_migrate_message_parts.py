import io
import logging
from collections import defaultdict
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
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlalchemy.orm.attributes import flag_modified

import pingpong.models as models
import pingpong.schemas as schemas
from pingpong.ai import get_openai_client_by_class_id
from pingpong.authz.base import AuthzClient, Relation
from pingpong.config import config
from pingpong.files import _file_grants, _is_ci_supported, file_extension_to_mime_type
from pingpong.server import OpenAIClient

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ThreadMessages:
    thread: models.Thread
    messages: list[models.Message]


@dataclass(frozen=True)
class UploaderFields:
    uploader_id: int | None
    anonymous_session_id: int | None
    anonymous_link_id: int | None
    user_auth: str | None
    anonymous_user_auth: str | None
    anonymous_link_auth: str | None


@dataclass
class MessagePartMigrationStats:
    parts_created: int = 0
    annotations_created: int = 0
    files_created: int = 0
    files_reused: int = 0


async def migrate_message_parts(
    session: AsyncSession, authz_client: AuthzClient
) -> None:
    """Backfill MessageParts/Annotations for messages created by m15. This migration
    fetches those same upstream messages (from m15) and stores their parts and
    annotations locally.
    """

    messages_by_class_id: dict[int, list[models.Message]] = defaultdict(list)

    openai_clients_by_class_id: dict[int, OpenAIClient] = {}

    local_messages_to_process = await _fetch_message_fields(session)
    for local_message in local_messages_to_process:
        messages_by_class_id[local_message.thread.class_id].append(local_message)
    logger.info(
        "m16 starting message part migration. classes=%s messages=%s",
        len(messages_by_class_id),
        len(local_messages_to_process),
    )

    for class_id, local_messages in messages_by_class_id.items():
        try:
            openai_client = await get_openai_client_by_class_id(session, class_id)
            openai_clients_by_class_id[class_id] = openai_client
        except Exception:
            logger.exception(
                "Could not get OpenAI client during message part "
                f"backfill. class_id={class_id}",
            )
            continue

        for local_message in local_messages:
            # Authz grants are written separately from DB sessions, so we need to keep
            # track of those writes so we can revoke if the nested session fails
            written_grants: list[Relation] = []
            async with session.begin_nested() as savepoint:
                try:
                    await _migrate_message_parts(
                        session,
                        authz_client,
                        openai_client,
                        local_message,
                        written_grants,
                    )
                    local_message.message_metadata[
                        "assistants_to_responses_api_thread_migration"
                    ]["message_parts"] = "complete"
                    # Notifies SQLAlchemy that `message_metadata` changed (since it's JSON it
                    # wouldn't be detected otherwise)
                    flag_modified(local_message, "message_metadata")
                except Exception:
                    await savepoint.rollback()
                    await authz_client.write_safe(revoke=written_grants)
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
    a MessagePart or whose `message_parts` migration state is already "complete", so
    the backfill is idempotent. The thread (with its anonymous sessions) and run
    are fetched in advance.

    The options for pre-loading threads, anonymous sessions, and runs are necessary
    because SQLAlchemy doesn't lazily load those fields in an async context.
    """

    migration_metadata = models.Message.message_metadata[
        "assistants_to_responses_api_thread_migration"
    ]
    message_state = migration_metadata["message"].as_string()
    message_parts_state = migration_metadata["message_parts"].as_string()

    stmt = (
        select(models.Message)
        .where(
            message_state == "complete",
            models.Message.message_id.is_not(None),
            or_(
                message_parts_state.is_(None),
                message_parts_state != "complete",
            ),
        )
        .options(
            selectinload(models.Message.thread)
            .selectinload(models.Thread.anonymous_sessions)
            .selectinload(models.AnonymousSession.user)
            .selectinload(models.User.anonymous_link),
            selectinload(models.Message.run),
        )
    )
    result = await session.execute(stmt)
    return list(result.scalars())


async def _migrate_message_parts(
    session: AsyncSession,
    authz_client: AuthzClient,
    openai_client: OpenAIClient,
    local_message: models.Message,
    written_grants: list[Relation],
) -> MessagePartMigrationStats:
    stats = MessagePartMigrationStats()
    openai_message = await openai_client.beta.threads.messages.retrieve(
        message_id=local_message.message_id,
        thread_id=local_message.thread.thread_id,
    )
    # Exception is handled by caller so that we can rollback if there's an error. So
    # no try-except
    await _persist_message_parts(
        session,
        authz_client,
        openai_client,
        openai_message,
        local_message,
        written_grants,
        stats,
    )
    await session.flush()
    logger.info(
        "m16 migrated message parts. message_pk=%s openai_message_id=%s "
        "thread_id=%s parts_created=%s annotations_created=%s files_created=%s "
        "files_reused=%s",
        local_message.id,
        local_message.message_id,
        local_message.thread_id,
        stats.parts_created,
        stats.annotations_created,
        stats.files_created,
        stats.files_reused,
    )
    return stats


async def _persist_message_parts(
    session: AsyncSession,
    authz_client: AuthzClient,
    openai_client: OpenAIClient,
    openai_message: OpenAIMessage,
    local_message: models.Message,
    written_grants: list[Relation],
    stats: MessagePartMigrationStats,
) -> None:
    for part_index, content in enumerate(openai_message.content):
        part_data = await _create_message_part_data(
            session,
            authz_client,
            openai_client,
            content,
            local_message,
            part_index,
            written_grants,
            stats,
        )
        if part_data is None:
            logger.warning(
                f"Skipping unsupported message content block. "
                f"message_id={local_message.id} openai_message_id={openai_message.id} "
                f"content_type={content.type}",
            )
            continue

        message_part = await models.MessagePart.create(session, part_data)
        stats.parts_created += 1

        for annotation_index, annotation in enumerate(
            _get_annotations_for_content(content)
        ):
            annotation_data = await _create_annotation_data_and_persist_file(
                session,
                authz_client,
                openai_client,
                annotation,
                local_message.thread,
                local_message,
                message_part.id,
                annotation_index,
                written_grants,
                stats,
            )
            if annotation_data is None:
                logger.warning(
                    f"Skipping unsupported message annotation. "
                    f"message_id={local_message.id} message_part_id={message_part.id} "
                    f"annotation_type={annotation.type}",
                )
                continue

            await models.Annotation.create(session, annotation_data)
            stats.annotations_created += 1


async def _create_message_part_data(
    session: AsyncSession,
    authz_client: AuthzClient,
    openai_client: OpenAIClient,
    openai_message_content: MessageContent,
    local_message: models.Message,
    part_index: int,
    written_grants: list[Relation],
    stats: MessagePartMigrationStats,
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
            authz_client,
            openai_client,
            local_message.thread,
            local_message,
            openai_message_content.image_file.file_id,
            written_grants,
            include_anonymous_context=True,
            source="image_file",
            stats=stats,
        )
        await _backfill_s3_file(session, openai_client, local_file)
        message_part_data["type"] = schemas.MessagePartType.INPUT_IMAGE
        message_part_data["input_image_file_id"] = local_file.file_id
        message_part_data["input_image_file_object_id"] = local_file.id
        return message_part_data

    return None


async def _create_annotation_data_and_persist_file(
    session: AsyncSession,
    authz_client: AuthzClient,
    openai_client: OpenAIClient,
    annotation: OpenAIAnnotation,
    local_thread: models.Thread,
    local_message: models.Message,
    message_part_id: int,
    annotation_index: int,
    written_grants: list[Relation],
    stats: MessagePartMigrationStats,
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
        if local_file is not None:
            stats.files_reused += 1
            logger.info(
                "m16 reused local file. openai_file_id=%s local_file_id=%s "
                "source=file_citation",
                annotation.file_citation.file_id,
                local_file.id,
            )
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
            authz_client,
            openai_client,
            local_thread,
            local_message,
            annotation.file_path.file_id,
            written_grants,
            include_anonymous_context=False,
            source="file_path",
            stats=stats,
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

        if _is_ci_supported(local_file.content_type):
            await models.Thread.add_code_interpreter_files(
                session=session,
                thread_id=local_thread.id,
                file_ids=[local_file.file_id],
            )
            logger.info(
                "m16 added file_path output to thread code interpreter files. "
                "thread_id=%s local_file_id=%s openai_file_id=%s content_type=%s",
                local_thread.id,
                local_file.id,
                local_file.file_id,
                local_file.content_type,
            )

        # The OpenAI file id is already usable by the next Responses request once it
        # is attached to the thread. The S3 backfill keeps a local copy available for
        # providers that cannot reuse OpenAI-hosted assistant output files.
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
    authz_client: AuthzClient,
    openai_client: OpenAIClient,
    local_thread: models.Thread,
    local_message: models.Message,
    openai_file_id: str,
    written_grants: list[Relation],
    *,
    include_anonymous_context: bool,
    source: str,
    stats: MessagePartMigrationStats,
) -> models.File:
    maybe_local_file = await _fetch_local_file(session, openai_file_id)
    if maybe_local_file:
        stats.files_reused += 1
        logger.info(
            "m16 reused local file. openai_file_id=%s local_file_id=%s source=%s",
            openai_file_id,
            maybe_local_file.id,
            source,
        )
        return maybe_local_file

    openai_file = await openai_client.files.retrieve(openai_file_id)
    filename_parts = openai_file.filename.split(".")
    content_type = (
        file_extension_to_mime_type(filename_parts[-1]) if filename_parts else None
    )
    uploader = await _get_anonymous_user_fields(
        session,
        local_thread,
        local_message,
        include_anonymous_context=include_anonymous_context,
    )

    # used for updated too since that's not given by OpenAI
    created_dt = _require_dt(openai_file.created_at)

    local_file = await models.File.create(
        session,
        {
            "file_id": openai_file_id,
            "private": local_thread.private,
            "name": openai_file.filename,
            "content_type": content_type,
            "anonymous_session_id": uploader.anonymous_session_id,
            "anonymous_link_id": uploader.anonymous_link_id,
            "uploader_id": uploader.uploader_id,
            "created": created_dt,
            "updated": created_dt,
        },
        class_id=local_thread.class_id,
    )

    grants = _file_grants(
        local_file,
        local_thread.class_id,
        uploader.user_auth,
        uploader.anonymous_link_auth,
        uploader.anonymous_user_auth,
    )
    await authz_client.write_safe(grant=grants)
    stats.files_created += 1
    logger.info(
        "m16 created local file. openai_file_id=%s local_file_id=%s source=%s "
        "filename=%s content_type=%s uploader_id=%s include_anonymous_context=%s "
        "anonymous_session_id=%s anonymous_link_id=%s",
        openai_file_id,
        local_file.id,
        source,
        openai_file.filename,
        content_type,
        uploader.uploader_id,
        include_anonymous_context,
        uploader.anonymous_session_id,
        uploader.anonymous_link_id,
    )
    logger.info(
        "m16 wrote file grants. local_file_id=%s openai_file_id=%s grant_count=%s "
        "include_anonymous_context=%s",
        local_file.id,
        openai_file_id,
        len(grants),
        include_anonymous_context,
    )
    # Record so the caller can revoke these if the savepoint rolls back (the authz
    # write above is not covered by the DB transaction).
    written_grants.extend(grants)

    return local_file


async def _get_anonymous_user_fields(
    session: AsyncSession,
    local_thread: models.Thread,
    local_message: models.Message,
    *,
    include_anonymous_context: bool,
) -> UploaderFields:
    uploader_id = local_message.user_id

    if uploader_id is None and local_message.run is not None:
        uploader_id = local_message.run.creator_id

    if uploader_id is None:
        return UploaderFields(None, None, None, None, None, None)

    # Replicating auth string in `pingpong.files._file_grants_revoke`
    user_auth = f"user:{uploader_id}"

    anonymous_session_id = None
    anonymous_session_token = None
    anonymous_link_id = None
    anonymous_link_auth = None

    if include_anonymous_context:
        anonymous_session = next(iter(local_thread.anonymous_sessions), None)
        if anonymous_session is not None:
            anonymous_session_id = anonymous_session.id
            anonymous_session_token = anonymous_session.session_token

            anonymous_user = anonymous_session.user
            if anonymous_user is None and anonymous_session.user_id is not None:
                anonymous_user = await _fetch_full_user(
                    session, anonymous_session.user_id
                )

            if anonymous_user is not None:
                anonymous_link_id = anonymous_user.anonymous_link_id
                if anonymous_user.anonymous_link is not None:
                    anonymous_link_auth = (
                        f"anonymous_link:{anonymous_user.anonymous_link.share_token}"
                    )

    # Replicating auth strings in `pingpong.files._file_grants_revoke`
    anonymous_user_auth = (
        f"anonymous_user:{anonymous_session_token}" if anonymous_session_token else None
    )

    return UploaderFields(
        uploader_id=uploader_id,
        anonymous_session_id=anonymous_session_id,
        anonymous_link_id=anonymous_link_id,
        user_auth=user_auth,
        anonymous_user_auth=anonymous_user_auth,
        anonymous_link_auth=anonymous_link_auth,
    )


async def _fetch_full_user(
    session: AsyncSession, uploader_id: int
) -> models.User | None:
    """To get the anonymous fields on User"""
    return await session.scalar(
        select(models.User)
        .where(models.User.id == uploader_id)
        .options(selectinload(models.User.anonymous_link))
    )


async def _backfill_s3_file(
    session: AsyncSession,
    openai_client: OpenAIClient,
    local_file: models.File,
) -> None:
    """
    If anything fails in this function, we let the exception bubble up to the DB
    transaction savepoint so that we can rollback our changes if we're unable to
    fetch the content of the files from OpenAI.
    """
    if local_file.s3_file_id is not None:
        return

    response = await openai_client.files.with_raw_response.retrieve_content(
        local_file.file_id
    )

    if response.status_code != 200:
        raise RuntimeError(
            f"OpenAI returned {response.status_code} while fetching file "
            f"during message part migration (id: {local_file.id})"
        )

    # filename generation taken from `pingpong.files.handle_create_file`
    suffix = Path(local_file.name or "").suffix.lower()
    store_key = f"file_{uuid.uuid4()}{suffix}"
    content_type = local_file.content_type

    await config.file_store.store.put(
        store_key, io.BytesIO(response.content), content_type
    )

    s3_file = await models.S3File.create(
        session,
        key=store_key,
        file_obj_ids=[local_file.id],
        file_ids=[local_file.file_id],
    )
    await session.refresh(local_file)
    logger.info(
        "m16 backfilled file content. local_file_id=%s openai_file_id=%s s3_file_id=%s",
        local_file.id,
        local_file.file_id,
        s3_file.id,
    )


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
