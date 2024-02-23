import openai
from fastapi import HTTPException, UploadFile
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from .models import File
from .schemas import FileTypeInfo, GenericStatus


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
    if not _is_supported(upload.content_type.lower()):
        raise HTTPException(
            status_code=403, detail="File type not supported for retrieval by OpenAI!"
        )

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


# Support information comes from:
# https://platform.openai.com/docs/assistants/tools/supported-files
FILE_TYPES = [
    FileTypeInfo(
        mime_type="text/x-c",
        name="C",
        retrieval=True,
        code_interpreter=True,
        extensions=["c"],
    ),
    FileTypeInfo(
        mime_type="text/x-c++",
        name="C++",
        retrieval=True,
        code_interpreter=True,
        extensions=["cpp", "cc", "cxx", "c++"],
    ),
    FileTypeInfo(
        mime_type="text/csv",
        name="CSV",
        retrieval=False,
        code_interpreter=True,
        extensions=["csv"],
    ),
    FileTypeInfo(
        mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        name="Word Doc",
        retrieval=True,
        code_interpreter=True,
        extensions=["docx"],
    ),
    FileTypeInfo(
        mime_type="text/html",
        name="HTML",
        retrieval=True,
        code_interpreter=True,
        extensions=["html", "htm"],
    ),
    FileTypeInfo(
        mime_type="text/x-java",
        name="Java",
        retrieval=True,
        code_interpreter=True,
        extensions=["java"],
    ),
    FileTypeInfo(
        mime_type="application/json",
        name="JSON",
        retrieval=True,
        code_interpreter=True,
        extensions=["json"],
    ),
    FileTypeInfo(
        mime_type="text/markdown",
        name="Markdown",
        retrieval=True,
        code_interpreter=True,
        extensions=["md", "markdown"],
    ),
    FileTypeInfo(
        mime_type="application/pdf",
        name="PDF",
        retrieval=True,
        code_interpreter=True,
        extensions=["pdf"],
    ),
    FileTypeInfo(
        mime_type="text/php",
        name="PHP",
        retrieval=True,
        code_interpreter=True,
        extensions=["php"],
    ),
    FileTypeInfo(
        mime_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
        name="PowerPoint",
        retrieval=True,
        code_interpreter=True,
        extensions=["pptx"],
    ),
    FileTypeInfo(
        mime_type="text/x-python",
        name="Python",
        retrieval=True,
        code_interpreter=True,
        extensions=["py"],
    ),
    FileTypeInfo(
        mime_type="text/x-script.python",
        name="Python",
        retrieval=True,
        code_interpreter=True,
        extensions=["py"],
    ),
    FileTypeInfo(
        mime_type="text/x-ruby",
        name="Ruby",
        retrieval=True,
        code_interpreter=True,
        extensions=["rb"],
    ),
    FileTypeInfo(
        mime_type="text/x-tex",
        name="LaTeX",
        retrieval=True,
        code_interpreter=True,
        extensions=["tex"],
    ),
    FileTypeInfo(
        mime_type="text/plain",
        name="Text",
        retrieval=True,
        code_interpreter=True,
        extensions=["txt"],
    ),
    FileTypeInfo(
        mime_type="text/css",
        name="CSS",
        retrieval=False,
        code_interpreter=True,
        extensions=["css"],
    ),
    FileTypeInfo(
        mime_type="image/jpeg",
        name="JPEG",
        retrieval=False,
        code_interpreter=True,
        extensions=["jpeg", "jpg"],
    ),
    FileTypeInfo(
        mime_type="text/javascript",
        name="JavaScript",
        retrieval=False,
        code_interpreter=True,
        extensions=["js"],
    ),
    FileTypeInfo(
        mime_type="image/gif",
        name="GIF",
        retrieval=False,
        code_interpreter=True,
        extensions=["gif"],
    ),
    FileTypeInfo(
        mime_type="image/png",
        name="PNG",
        retrieval=False,
        code_interpreter=True,
        extensions=["png"],
    ),
    FileTypeInfo(
        mime_type="application/x-tar",
        name="Tarball",
        retrieval=False,
        code_interpreter=True,
        extensions=["tar"],
    ),
    FileTypeInfo(
        mime_type="application/typescript",
        name="TypeScript",
        retrieval=False,
        code_interpreter=True,
        extensions=["ts"],
    ),
    FileTypeInfo(
        mime_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        name="Excel",
        retrieval=False,
        code_interpreter=True,
        extensions=["xlsx"],
    ),
    FileTypeInfo(
        mime_type="application/xml",
        name="XML",
        retrieval=False,
        code_interpreter=True,
        extensions=["xml"],
    ),
    FileTypeInfo(
        mime_type="text/xml",
        name="XML",
        retrieval=False,
        code_interpreter=True,
        extensions=["xml"],
    ),
    FileTypeInfo(
        mime_type="application/zip",
        name="Zip Archive",
        retrieval=False,
        code_interpreter=True,
        extensions=["zip"],
    ),
]

_SUPPORTED_TYPE = {ft.mime_type.lower() for ft in FILE_TYPES}


def _is_supported(content_type: str) -> bool:
    """Check if the content type is supported."""
    return content_type in _SUPPORTED_TYPE
