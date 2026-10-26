"""Class and parent binding for API resources, independent of permission policy."""

from collections.abc import Awaitable, Callable, Iterable
from typing import Any, TypeVar

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from pingpong import models

T = TypeVar("T", models.Thread, models.Assistant)


def require_resource_in_class(
    resource: T | None, class_id: int | str, *, detail: str
) -> T:
    if resource is None or resource.class_id != int(class_id):
        raise HTTPException(404, detail)
    return resource


async def get_thread_for_class(
    db: AsyncSession,
    class_id: int | str,
    thread_id: int | str,
    *,
    loader: Callable[..., Awaitable[models.Thread | None]] | None = None,
    detail: str = "Thread not found",
    **loader_options: Any,
) -> models.Thread:
    return require_resource_in_class(
        await (loader or models.Thread.get_by_id)(db, int(thread_id), **loader_options),
        class_id,
        detail=detail,
    )


async def get_assistant_for_class(
    db: AsyncSession,
    class_id: int | str,
    assistant_id: int | str,
    *,
    loader: Callable[..., Awaitable[models.Assistant | None]] | None = None,
    detail: str = "Assistant not found.",
    **loader_options: Any,
) -> models.Assistant:
    return require_resource_in_class(
        await (loader or models.Assistant.get_by_id)(
            db, int(assistant_id), **loader_options
        ),
        class_id,
        detail=detail,
    )


async def get_assistant_share_for_class(
    db: AsyncSession,
    class_id: int | str,
    assistant_id: int | str,
    share_id: int | str,
    *,
    wrong_parent_status: int = 404,
) -> models.AnonymousLink:
    assistant = await get_assistant_for_class(db, class_id, assistant_id)
    share = await models.AnonymousLink.get_by_id_with_assistant(db, int(share_id))
    if share is None:
        raise HTTPException(404, "Share link not found.")
    if share.assistant is None or share.assistant.id != assistant.id:
        raise HTTPException(
            wrong_parent_status,
            "This share link does not belong to the specified assistant.",
        )
    return share


async def require_files_in_class(
    db: AsyncSession, class_id: int | str, files: Iterable[models.File]
) -> None:
    """Use associations: copied files may legitimately belong to several classes."""
    ids = {file.id for file in files}
    if ids != await models.File.get_file_ids_for_class(db, int(class_id), list(ids)):
        raise HTTPException(404, "File not found")


async def get_attachment_files_for_class(
    db: AsyncSession, class_id: int | str, file_ids: Iterable[str]
) -> list[models.File]:
    ids = set(file_ids)
    if not ids:
        return []
    files = await models.File.get_all_by_file_id(db, list(ids), class_id=int(class_id))
    if {file.file_id for file in files} != ids:
        raise HTTPException(404, "File not found")
    return files
