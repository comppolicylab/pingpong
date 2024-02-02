import openai
from fastapi import HTTPException, UploadFile
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from .models import File
from .schemas import GenericStatus


async def handle_delete_file(
    session: AsyncSession, oai_client: openai.AsyncClient, file_id: int
) -> GenericStatus:
    """Handle file deletion.

    Args:
        session (AsyncSession): Database session
        oai_client (openai.AsyncClient): OpenAI API client
        file_id (int): File ID to delete

    Returns:
        GenericStatus: Status of the operation
    """
    int_file_id = int(file_id)  # ensure just in case
    file = await File.get_by_id(session, int_file_id)
    remote_file_id = file.file_id

    try:
        await File.delete(session, int_file_id)
    except IntegrityError:
        raise HTTPException(
            status_code=403,
            detail="File is in use. Remove it from all assistants before deleting!",
        )
    await oai_client.files.delete(remote_file_id)
    return GenericStatus(status="ok")


async def handle_create_file(
    session: AsyncSession,
    oai_client: openai.AsyncClient,
    *,
    upload: UploadFile,
    class_id: int,
    uploader_id: int,
    private: bool,
) -> File:
    """Handle file creation.

    Args:
        session (AsyncSession): Database session
        oai_client (openai.AsyncClient): OpenAI API client
        upload (UploadFile): File to upload
        class_id (int): Class ID
        uploader_id (int): Uploader ID
        private (bool): File privacy
    """
    new_f = await oai_client.files.create(
        # NOTE(jnu): the client tries to infer the filename, which doesn't
        # work on this file that exists as bytes in memory. There's an
        # undocumented way to specify name, content, and content_type which
        # we use here to force correctness.
        # https://github.com/stanford-policylab/pingpong/issues/147
        file=(upload.filename, upload.file, upload.content_type),
        purpose="assistants",
    )

    data = {
        "file_id": new_f.id,
        "class_id": int(class_id),
        "private": private,
        "uploader_id": int(uploader_id),
        "name": upload.filename,
        "content_type": upload.content_type,
    }

    try:
        return await File.create(session, data)
    except Exception as e:
        await oai_client.files.delete(new_f.id)
        raise e
