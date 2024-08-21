import asyncio
import openai
from fastapi import HTTPException, UploadFile
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from .authz import AuthzClient, Relation
from .models import File
from .schemas import FileTypeInfo, GenericStatus, FileUploadPurpose
from .schemas import File as FileSchema


def _file_grants(file: File) -> list[Relation]:
    target_type = "user_file" if file.private else "class_file"
    target = f"{target_type}:{file.id}"
    return [
        (f"class:{file.class_id}", "parent", target),
        (f"user:{file.uploader_id}", "owner", target),
    ]


async def handle_delete_file(
    session: AsyncSession,
    authz: AuthzClient,
    oai_client: openai.AsyncClient,
    file_id: int,
) -> GenericStatus:
    """Handle file deletion.

    Args:
        session (AsyncSession): Database session
        authz (AuthzClient): Authorization client
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
        await authz.write(revoke=_file_grants(file))
    except IntegrityError:
        raise HTTPException(
            status_code=403,
            detail=f"{file.name} is in use. Remove it from all assistants before deleting!",
        )
    await oai_client.files.delete(remote_file_id)
    return GenericStatus(status="ok")


async def handle_create_file(
    session: AsyncSession,
    authz: AuthzClient,
    oai_client: openai.AsyncClient,
    *,
    upload: UploadFile,
    class_id: int,
    uploader_id: int,
    private: bool,
    purpose: FileUploadPurpose = "assistants",
) -> FileSchema:
    """Handle file creation.

    Args:
        session (AsyncSession): Database session
        authz (AuthzClient): Authorization client
        oai_client (openai.AsyncClient): OpenAI API client
        upload (UploadFile): File to upload
        class_id (int): Class ID
        uploader_id (int): Uploader ID
        private (bool): File privacy
    """
    content_type = upload.content_type.lower()

    if not _is_supported(content_type):
        raise HTTPException(
            status_code=403, detail="File type not supported for File Search by OpenAI!"
        )

    if purpose == "multimodal":
        tasks: list[asyncio.Task[FileSchema]] = []
        if _is_vision_supported(content_type):
            tasks.append(
                asyncio.create_task(
                    handle_create_file(
                        session,
                        authz,
                        oai_client,
                        upload=upload,
                        class_id=class_id,
                        uploader_id=uploader_id,
                        private=private,
                        purpose="vision",
                    ),
                    name="vision_upload",
                )
            )

        # There is a case where the file is vision supported but not file search or code interpreter supported
        # image/webp is an example of this case
        if _is_fs_supported(content_type) or _is_ci_supported(content_type):
            tasks.append(
                asyncio.create_task(
                    handle_create_file(
                        session,
                        authz,
                        oai_client,
                        upload=upload,
                        class_id=class_id,
                        uploader_id=uploader_id,
                        private=private,
                        purpose="assistants",
                    ),
                    name="assistants_upload",
                )
            )

        await asyncio.gather(*tasks)
        new_v_file, new_f_file = (
            next(
                (task.result() for task in tasks if task.get_name() == "vision_upload"),
                None,
            ),
            next(
                (
                    task.result()
                    for task in tasks
                    if task.get_name() == "assistants_upload"
                ),
                None,
            ),
        )

        primary_file = new_f_file if new_f_file else new_v_file

        # Always true, as we have checked _is_supported
        if not primary_file:
            raise HTTPException(
                status_code=500,
                detail="File not uploaded, something went wrong!",
            )

        return FileSchema(
            id=primary_file.id,
            name=primary_file.name,
            content_type=primary_file.content_type,
            file_id=primary_file.file_id,
            vision_obj_id=new_v_file.id if new_v_file and new_f_file else None,
            file_search_file_id=primary_file.file_id
            if _is_fs_supported(content_type)
            else None,
            code_interpreter_file_id=primary_file.file_id
            if _is_ci_supported(content_type)
            else None,
            vision_file_id=new_v_file.file_id if new_v_file else None,
            class_id=primary_file.class_id,
            private=primary_file.private,
            uploader_id=primary_file.uploader_id,
            created=primary_file.created,
            updated=primary_file.updated,
        )

    try:
        new_f = await oai_client.files.create(
            # NOTE(jnu): the client tries to infer the filename, which doesn't
            # work on this file that exists as bytes in memory. There's an
            # undocumented way to specify name, content, and content_type which
            # we use here to force correctness.
            # https://github.com/stanford-policylab/pingpong/issues/147
            file=(upload.filename.lower(), upload.file, upload.content_type),
            purpose=purpose,
        )
    except openai.BadRequestError as e:
        raise HTTPException(
            status_code=400,
            detail=e.response.json()
            .get("error", {})
            .get("message", "OpenAI rejected this request"),
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
        f = await File.create(session, data)
        await authz.write(grant=_file_grants(f))

        return FileSchema(
            id=f.id,
            name=f.name,
            content_type=f.content_type,
            file_id=f.file_id,
            file_search_file_id=f.file_id
            if _is_fs_supported(content_type) and purpose == "assistants"
            else None,
            code_interpreter_file_id=f.file_id
            if _is_ci_supported(content_type) and purpose == "assistants"
            else None,
            vision_file_id=f.file_id
            if _is_vision_supported(content_type) and purpose == "vision"
            else None,
            class_id=f.class_id,
            private=f.private,
            uploader_id=f.uploader_id,
            created=f.created,
            updated=f.updated,
        )
    except Exception as e:
        await oai_client.files.delete(new_f.id)
        raise e


# Support information comes from:
# https://platform.openai.com/docs/assistants/tools/supported-files
FILE_TYPES = [
    FileTypeInfo(
        mime_type="text/x-c",
        name="C",
        file_search=True,
        code_interpreter=True,
        vision=False,
        extensions=["c"],
    ),
    FileTypeInfo(
        mime_type="text/x-c++",
        name="C++",
        file_search=True,
        code_interpreter=True,
        vision=False,
        extensions=["cpp", "cc", "cxx", "c++"],
    ),
    FileTypeInfo(
        mime_type="text/csv",
        name="CSV",
        file_search=False,
        code_interpreter=True,
        vision=False,
        extensions=["csv"],
    ),
    FileTypeInfo(
        mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        name="Word Doc",
        file_search=True,
        code_interpreter=True,
        vision=False,
        extensions=["docx"],
    ),
    FileTypeInfo(
        mime_type="text/html",
        name="HTML",
        file_search=True,
        code_interpreter=True,
        vision=False,
        extensions=["html", "htm"],
    ),
    FileTypeInfo(
        mime_type="text/x-java",
        name="Java",
        file_search=True,
        code_interpreter=True,
        vision=False,
        extensions=["java"],
    ),
    FileTypeInfo(
        mime_type="application/json",
        name="JSON",
        file_search=True,
        code_interpreter=True,
        vision=False,
        extensions=["json"],
    ),
    FileTypeInfo(
        mime_type="text/markdown",
        name="Markdown",
        file_search=True,
        code_interpreter=True,
        vision=False,
        extensions=["md", "markdown"],
    ),
    FileTypeInfo(
        mime_type="application/pdf",
        name="PDF",
        file_search=True,
        code_interpreter=True,
        vision=False,
        extensions=["pdf"],
    ),
    FileTypeInfo(
        mime_type="text/php",
        name="PHP",
        file_search=True,
        code_interpreter=True,
        vision=False,
        extensions=["php"],
    ),
    FileTypeInfo(
        mime_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
        name="PowerPoint",
        file_search=True,
        code_interpreter=True,
        vision=False,
        extensions=["pptx"],
    ),
    FileTypeInfo(
        mime_type="text/x-python",
        name="Python",
        file_search=True,
        code_interpreter=True,
        vision=False,
        extensions=["py"],
    ),
    FileTypeInfo(
        mime_type="text/x-script.python",
        name="Python",
        file_search=True,
        code_interpreter=True,
        vision=False,
        extensions=["py"],
    ),
    FileTypeInfo(
        mime_type="text/x-ruby",
        name="Ruby",
        file_search=True,
        code_interpreter=True,
        vision=False,
        extensions=["rb"],
    ),
    FileTypeInfo(
        mime_type="text/x-tex",
        name="LaTeX",
        file_search=True,
        code_interpreter=True,
        vision=False,
        extensions=["tex"],
    ),
    FileTypeInfo(
        mime_type="text/plain",
        name="Text",
        file_search=True,
        code_interpreter=True,
        vision=False,
        extensions=["txt"],
    ),
    FileTypeInfo(
        mime_type="text/css",
        name="CSS",
        file_search=False,
        code_interpreter=True,
        vision=False,
        extensions=["css"],
    ),
    FileTypeInfo(
        mime_type="image/jpeg",
        name="JPEG",
        file_search=False,
        code_interpreter=True,
        vision=True,
        extensions=["jpeg", "jpg"],
    ),
    FileTypeInfo(
        mime_type="text/javascript",
        name="JavaScript",
        file_search=False,
        code_interpreter=True,
        vision=False,
        extensions=["js"],
    ),
    FileTypeInfo(
        mime_type="image/gif",
        name="GIF",
        file_search=False,
        code_interpreter=True,
        vision=True,
        extensions=["gif"],
    ),
    FileTypeInfo(
        mime_type="image/png",
        name="PNG",
        file_search=False,
        code_interpreter=True,
        vision=True,
        extensions=["png"],
    ),
    FileTypeInfo(
        mime_type="image/webp",
        name="WEBP",
        file_search=False,
        code_interpreter=False,
        vision=True,
        extensions=["webp"],
    ),
    FileTypeInfo(
        mime_type="application/x-tar",
        name="Tarball",
        file_search=False,
        code_interpreter=True,
        vision=False,
        extensions=["tar"],
    ),
    FileTypeInfo(
        mime_type="application/typescript",
        name="TypeScript",
        file_search=False,
        code_interpreter=True,
        vision=False,
        extensions=["ts"],
    ),
    FileTypeInfo(
        mime_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        name="Excel",
        file_search=False,
        code_interpreter=True,
        vision=False,
        extensions=["xlsx"],
    ),
    FileTypeInfo(
        mime_type="application/xml",
        name="XML",
        file_search=False,
        code_interpreter=True,
        vision=False,
        extensions=["xml"],
    ),
    FileTypeInfo(
        mime_type="text/xml",
        name="XML",
        file_search=False,
        code_interpreter=True,
        vision=False,
        extensions=["xml"],
    ),
    FileTypeInfo(
        mime_type="application/zip",
        name="Zip Archive",
        file_search=False,
        code_interpreter=True,
        vision=False,
        extensions=["zip"],
    ),
]

_SUPPORTED_TYPE = {ft.mime_type.lower() for ft in FILE_TYPES}

_IMG_SUPPORTED_TYPE = {ft.mime_type.lower() for ft in FILE_TYPES if ft.vision}

_FS_SUPPORTED_TYPE = {ft.mime_type.lower() for ft in FILE_TYPES if ft.file_search}

_CI_SUPPORTED_TYPE = {ft.mime_type.lower() for ft in FILE_TYPES if ft.code_interpreter}


def _is_supported(content_type: str) -> bool:
    """Check if the content type is supported."""
    return content_type in _SUPPORTED_TYPE


def _is_vision_supported(content_type: str) -> bool:
    """Check if the content type is supported for vision."""
    return content_type in _IMG_SUPPORTED_TYPE


def _is_fs_supported(content_type: str) -> bool:
    """Check if the content type is supported for file search."""
    return content_type in _FS_SUPPORTED_TYPE


def _is_ci_supported(content_type: str) -> bool:
    """Check if the content type is supported for code interpreter."""
    return content_type in _CI_SUPPORTED_TYPE
