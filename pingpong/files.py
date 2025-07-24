import asyncio
from datetime import datetime, timezone
from typing import Union
import openai
import logging
from fastapi import HTTPException, UploadFile
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from .ai import get_details_from_api_error
from .authz import AuthzClient, Relation
from .models import File
from .schemas import FileTypeInfo, FileUploadPurpose, GenericStatus, ImageProxy
from .schemas import File as FileSchema
import base64

logger = logging.getLogger(__name__)

OpenAIClientType = Union[openai.AsyncClient, openai.AsyncAzureOpenAI]


def _file_grants(
    file: File,
    class_id: int,
    user_auth: str | None = None,
    anonymous_link_auth: str | None = None,
    anonymous_user_auth: str | None = None,
) -> list[Relation]:
    target_type = "user_file" if file.private else "class_file"
    target = f"{target_type}:{file.id}"

    grants = [
        (f"class:{class_id}", "parent", target),
    ]

    if file.private:
        if user_auth:
            grants.append((user_auth, "owner", target))
        if anonymous_user_auth:
            grants.append((anonymous_user_auth, "owner", target))
        if anonymous_link_auth:
            grants.append((anonymous_link_auth, "can_delete", target))

    else:
        grants.append((f"user:{file.uploader_id}", "owner", target))

    return grants


def _file_grants_revoke(
    file: File,
    class_id: int,
    class_only: bool = False,
) -> list[Relation]:
    target_type = "user_file" if file.private else "class_file"
    target = f"{target_type}:{file.id}"

    grants = [
        (f"class:{class_id}", "parent", target),
    ]

    if class_only:
        return grants

    if file.anonymous_session:
        grants.append(
            (f"anonymous_user:{file.anonymous_session.session_token}", "owner", target)
        )
    if file.anonymous_link:
        grants.append(
            (f"anonymous_link:{file.anonymous_link.id}", "can_delete", target)
        )

    grants.append((f"user:{file.uploader_id}", "owner", target))

    return grants


class FileNotFoundException(Exception):
    pass


async def handle_delete_file(
    session: AsyncSession,
    authz: AuthzClient,
    oai_client: openai.AsyncClient,
    file_id: int,
    class_id: int,
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
    if not file:
        raise FileNotFoundException()
    remote_file_id = file.file_id

    # 1) Ensure that the file is not in use by any assistants
    nr_of_assistants = await File.assistant_count_using_file(
        session, int_file_id, class_id
    )

    if nr_of_assistants > 0:
        raise HTTPException(
            status_code=403,
            detail=f"{file.name} is in use. Remove it from all assistants before deleting!",
        )

    # 2) Remove the single row from the association table
    await File.remove_file_from_class(session, int_file_id, class_id)
    revoke_class_only_grants = _file_grants_revoke(file, class_id, class_only=True)
    # Revoke all grants for this file in the class
    await authz.write_safe(revoke=revoke_class_only_grants)

    revoke_grants = _file_grants_revoke(
        file,
        class_id,
    )
    try:
        # 3) Count how many classes still refer to this file
        remaining = await File.class_count_using_file(session, int_file_id)

        # 4) If none remain, do the actual delete
        if remaining == 0:
            await File.delete(session, int_file_id)
            await oai_client.files.delete(remote_file_id)
            # 5) Revoke all grants for this file
            await authz.write_safe(revoke=revoke_grants)
    except Exception:
        # If the delete fails, we need to ensure that the grants are restored
        await authz.write_safe(grant=revoke_class_only_grants + revoke_grants)
        raise
    return GenericStatus(status="ok")


async def handle_delete_files(
    session: AsyncSession,
    authz: AuthzClient,
    oai_client: openai.AsyncClient,
    file_ids: list[int],
    class_id: int,
) -> GenericStatus:
    """Handle file deletion for multiple files.

    Args:
        session (AsyncSession): Database session
        authz (AuthzClient): Authorization client
        oai_client (openai.AsyncClient): OpenAI API client
        file_ids (list[int]): File IDs to delete

    Returns:
        GenericStatus: Status of the operation
    """
    if not file_ids:
        return GenericStatus(status="ok")

    files: list[File] = await File.get_all_by_id(session, file_ids)
    file_map = {file.id: file for file in files}
    file_ids_found = list(file_map.keys())
    missing_ids = [file_id for file_id in file_ids if file_id not in file_ids_found]
    if missing_ids:
        logger.warning(
            f"Could not find the following files for deletion: {missing_ids}"
        )

    usage_rows = await File.assistant_count_using_files(
        session, file_ids_found, class_id
    )
    usage_counts = {row[0]: row[1] for row in usage_rows}

    in_use_files = [file for file in files if usage_counts.get(file.id, 0) > 0]
    if in_use_files:
        file_names = ", ".join(file.name for file in in_use_files)
        raise HTTPException(
            status_code=403,
            detail=f"The following files are in use by assistants: {file_names}. "
            "Remove them from all assistants before deleting!",
        )

    await File.remove_files_from_class(session, file_ids_found, class_id)

    revoked_grants_class_only = []
    for file in files:
        revoked_grants_class_only.extend(
            _file_grants_revoke(file, class_id, class_only=True)
        )
    await authz.write_safe(revoke=revoked_grants_class_only)

    revoked_grants = []
    remaining_rows = await File.class_count_using_files(session, file_ids_found)
    remaining_counts = {row[0]: row[1] for row in remaining_rows}
    file_ids_to_delete = [
        file_id for file_id in file_ids_found if remaining_counts.get(file_id, 0) == 0
    ]
    try:
        deleted_files, missing_ids = await File.delete_multiple(
            session, file_ids_to_delete
        )
        for file in files:
            revoked_grants.extend(_file_grants(file, class_id))
        await authz.write_safe(revoke=revoked_grants)

        if missing_ids:
            logger.warning(
                f"Could not find the following files for deletion: {missing_ids}"
            )
    except IntegrityError:
        await authz.write_safe(grant=revoked_grants_class_only)
        raise HTTPException(
            status_code=403,
            detail="One or more files are still in use. Ensure that files aren't used by other assistants before deleting!",
        )

    delete_tasks = [oai_client.files.delete(file.file_id) for file in deleted_files]
    results = await asyncio.gather(*delete_tasks, return_exceptions=True)
    for file, result in zip(deleted_files, results):
        if isinstance(result, openai.NotFoundError):
            logger.warning(f"Could not find file {file.file_id} for deletion, ignored.")
        elif isinstance(result, Exception):
            await authz.write_safe(grant=revoked_grants + revoked_grants_class_only)
            raise result

    return GenericStatus(status="ok")


async def get_base64_encoded_file(upload: UploadFile) -> str:
    """
    Reads the entire content of upload, resets the pointer,
    and returns the base64-encoded string.
    """
    await upload.seek(0)
    return base64.b64encode(await upload.read()).decode("utf-8")


async def handle_create_single_purpose_file(
    session: AsyncSession,
    authz: AuthzClient,
    oai_client: OpenAIClientType,
    upload: UploadFile,
    class_id: int,
    uploader_id: int,
    private: bool,
    purpose: FileUploadPurpose,
    content_type: str,
    is_azure_client: bool,
    use_image_descriptions: bool,
    user_auth: str | None = None,
    anonymous_link_auth: str | None = None,
    anonymous_user_auth: str | None = None,
    anonymous_session_id: int | None = None,
    anonymous_link_id: int | None = None,
) -> "FileSchema":
    """
    Creates a file for a single purpose (assistants or vision)
    (including creating a DB record and granting permissions)
    or returns a dummy file if this is an Azure vision file.
    """

    # ---------------------------------------------------------
    # Client: Azure OpenAI
    # Purpose: Vision
    # ---------------------------------------------------------
    if purpose == "vision" and is_azure_client:
        if not _is_vision_supported(content_type):
            raise HTTPException(
                status_code=403,
                detail="File type not supported for Vision by OpenAI!",
            )
        image_description = None
        if use_image_descriptions:
            base64_image = await get_base64_encoded_file(upload)
            image_description = await generate_image_description(
                oai_client, base64_image, content_type
            )
        return FileSchema(
            id=0,
            name=upload.filename,
            content_type=content_type,
            file_id="",
            vision_obj_id=None,
            class_id=class_id,
            private=None,
            uploader_id=None,
            created=datetime.now(timezone.utc),
            updated=None,
            image_description=image_description,
        )

    # ---------------------------------------------------------
    # Client: OpenAI
    # Purpose: Assistants or Vision
    # ---------------------------------------------------------
    # Client: Azure OpenAI
    # Purpose: Assistants
    # ---------------------------------------------------------
    match purpose:
        case "assistants":
            if not (_is_fs_supported(content_type) or _is_ci_supported(content_type)):
                raise HTTPException(
                    status_code=400,
                    detail="File type not supported as a document by OpenAI!",
                )
        case "vision":
            if not _is_vision_supported(content_type):
                raise HTTPException(
                    status_code=400,
                    detail="File type not supported for Vision by OpenAI!",
                )
        case _:
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported file purpose: {purpose}",
            )

    await upload.seek(0)
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
            detail=get_details_from_api_error(e, "OpenAI rejected this request."),
        )

    data = {
        "file_id": new_f.id,
        "private": private,
        "uploader_id": int(uploader_id),
        "name": upload.filename,
        "content_type": content_type,
        "anonymous_session_id": anonymous_session_id,
        "anonymous_link_id": anonymous_link_id,
    }

    try:
        f = await File.create(session, data, class_id=class_id)
        await authz.write(
            grant=_file_grants(
                f, class_id, user_auth, anonymous_link_auth, anonymous_user_auth
            )
        )

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
            class_id=class_id,
            private=f.private,
            uploader_id=f.uploader_id,
            created=f.created,
            updated=f.updated,
        )
    except Exception as e:
        await oai_client.files.delete(new_f.id)
        await authz.write(
            revoke=_file_grants(
                f, class_id, user_auth, anonymous_link_auth, anonymous_user_auth
            )
        )
        raise e


async def handle_multimodal_upload(
    session: AsyncSession,
    authz: AuthzClient,
    oai_client: OpenAIClientType,
    upload: UploadFile,
    class_id: int,
    uploader_id: int,
    private: bool,
    purpose: FileUploadPurpose,
    content_type: str,
    is_azure_client: bool,
    use_image_descriptions: bool,
    user_auth: str | None = None,
    anonymous_link_auth: str | None = None,
    anonymous_user_auth: str | None = None,
    anonymous_session_id: int | None = None,
    anonymous_link_id: int | None = None,
) -> "FileSchema":
    """
    Handles multimodal file creation by creating separate files (e.g. vision and
    assistants files) and combining the results. In some cases a dummy file with an image description is returned.
    """
    new_v_file, new_f_file, image_description = None, None, None

    can_generate_image_description = (
        _is_vision_supported(content_type)
        and is_azure_client
        and use_image_descriptions
    )
    can_upload_as_document = (_is_fs_supported(content_type) and "fs" in purpose) or (
        _is_ci_supported(content_type) and "ci" in purpose
    )

    # There is a case where the file is vision supported
    # but not file search or code interpreter supported
    # image/webp is an example of this case
    if not can_upload_as_document and can_generate_image_description:
        # ----------------------------------------------------------
        # Client: Azure OpenAI
        # Purpose: Vision
        # Returns: Dummy Vision File with Description
        # ----------------------------------------------------------
        return await handle_create_single_purpose_file(
            session,
            authz,
            oai_client,
            upload,
            class_id,
            uploader_id,
            private,
            "vision",
            content_type,
            is_azure_client,
            use_image_descriptions,
            user_auth,
            anonymous_link_auth,
            anonymous_user_auth,
            anonymous_session_id,
            anonymous_link_id,
        )

    if _is_vision_supported(content_type) and not is_azure_client:
        # ----------------------------------------------------------
        # Client: OpenAI
        # Purpose: Vision
        # Sets: new_v_file as regular File
        # ----------------------------------------------------------
        new_v_file = await handle_create_single_purpose_file(
            session,
            authz,
            oai_client,
            upload,
            class_id,
            uploader_id,
            private,
            "vision",
            content_type,
            is_azure_client,
            use_image_descriptions,
            user_auth,
            anonymous_link_auth,
            anonymous_user_auth,
            anonymous_session_id,
            anonymous_link_id,
        )

    if can_upload_as_document:
        try:
            if can_generate_image_description:
                # ----------------------------------------------------------
                # Client: Azure OpenAI
                # Purpose: Vision
                # Sets: image_description with generated description
                # ----------------------------------------------------------
                base64_image = await get_base64_encoded_file(upload)
                description_task = generate_image_description(
                    oai_client, base64_image, content_type
                )

                # ----------------------------------------------------------
                # Client: Azure OpenAI
                # Purpose: Assistants
                # Sets: new_f_file as regular File
                # ----------------------------------------------------------
                new_f_task = handle_create_single_purpose_file(
                    session,
                    authz,
                    oai_client,
                    upload,
                    class_id,
                    uploader_id,
                    private,
                    "assistants",
                    content_type,
                    is_azure_client,
                    use_image_descriptions,
                    user_auth,
                    anonymous_link_auth,
                    anonymous_user_auth,
                    anonymous_session_id,
                    anonymous_link_id,
                )

                # We can run these tasks concurrently,
                # since we're not using the upload object when
                # creating the image description
                image_description, new_f_file = await asyncio.gather(
                    description_task, new_f_task
                )
            else:
                # ----------------------------------------------------------
                # Client: OpenAI
                # Purpose: Assistants
                # Sets: new_f_file as regular File
                # ----------------------------------------------------------
                new_f_file = await handle_create_single_purpose_file(
                    session,
                    authz,
                    oai_client,
                    upload,
                    class_id,
                    uploader_id,
                    private,
                    "assistants",
                    content_type,
                    is_azure_client,
                    use_image_descriptions,
                    user_auth,
                    anonymous_link_auth,
                    anonymous_user_auth,
                    anonymous_session_id,
                    anonymous_link_id,
                )
        except Exception as e:
            if new_v_file:
                await oai_client.files.delete(new_v_file.file_id)
                await authz.write(
                    revoke=_file_grants(
                        new_v_file, class_id, user_auth, anonymous_user_auth
                    )
                )
            if new_f_file:
                await oai_client.files.delete(new_f_file.file_id)
                await authz.write(
                    revoke=_file_grants(
                        new_f_file, class_id, user_auth, anonymous_user_auth
                    )
                )
            raise e

    primary_file = new_f_file or new_v_file
    if not primary_file:
        raise HTTPException(
            status_code=500, detail="File not uploaded, something went wrong!"
        )

    return FileSchema(
        id=primary_file.id,
        name=primary_file.name,
        content_type=primary_file.content_type,
        file_id=primary_file.file_id,
        vision_obj_id=new_v_file.id if (new_v_file and new_f_file) else None,
        file_search_file_id=primary_file.file_id
        if _is_fs_supported(content_type) and "fs" in purpose
        else None,
        code_interpreter_file_id=primary_file.file_id
        if _is_ci_supported(content_type) and "ci" in purpose
        else None,
        vision_file_id=new_v_file.file_id if new_v_file else None,
        class_id=class_id,
        private=primary_file.private,
        uploader_id=primary_file.uploader_id,
        created=primary_file.created,
        updated=primary_file.updated,
        image_description=image_description,
    )


async def handle_create_file(
    session: AsyncSession,
    authz: AuthzClient,
    oai_client: OpenAIClientType,
    *,
    upload: UploadFile,
    class_id: int,
    uploader_id: int,
    private: bool,
    purpose: FileUploadPurpose = "assistants",
    use_image_descriptions: bool = False,
    user_auth: str | None = None,
    anonymous_link_auth: str | None = None,
    anonymous_user_auth: str | None = None,
    anonymous_session_id: int | None = None,
    anonymous_link_id: int | None = None,
) -> "FileSchema":
    """
    Main entry point for file creation.

    - Checks if the file type is supported.
    - If the purpose contains “multimodal”, then delegates to handle_multimodal_upload.
    - Otherwise, creates a file using handle_create_single_purpose_file.
    """
    content_type = upload.content_type.lower()
    if not _is_supported(content_type):
        raise HTTPException(
            status_code=403, detail="File type not supported by OpenAI!"
        )

    is_azure_client = isinstance(oai_client, openai.AsyncAzureOpenAI)

    if "multimodal" in purpose:
        return await handle_multimodal_upload(
            session,
            authz,
            oai_client,
            upload,
            class_id,
            uploader_id,
            private,
            purpose,
            content_type,
            is_azure_client,
            use_image_descriptions,
            user_auth,
            anonymous_link_auth if purpose != "assistants" else None,
            anonymous_user_auth if purpose != "assistants" else None,
            anonymous_session_id if purpose != "assistants" else None,
            anonymous_link_id if purpose != "assistants" else None,
        )
    else:
        return await handle_create_single_purpose_file(
            session,
            authz,
            oai_client,
            upload,
            class_id,
            uploader_id,
            private,
            purpose,
            content_type,
            is_azure_client,
            use_image_descriptions,
            user_auth,
            anonymous_link_auth if purpose != "assistants" else None,
            anonymous_user_auth if purpose != "assistants" else None,
            anonymous_session_id if purpose != "assistants" else None,
            anonymous_link_id if purpose != "assistants" else None,
        )


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


IMAGE_DESCRIPTION_PROMPT = """
You are assisting a model without vision capabilities by providing detailed descriptions of images to enable it to answer any questions users might have about the image. DO NOT ATTEMPT TO SOLVE, ANSWER, OR RESPOND TO THE IMAGE.

Examine the image provided carefully, noting all relevant details, features, and contexts that might be meaningful or actionable. Your task is to translate the visual content into a comprehensive textual description that encapsulates everything the model would need to know to effectively simulate an understanding of the image.

# Steps

1. **Observe the Image**: Look closely at the image to identify key elements, such as objects, people, activities, colors, and background.

2. **Identify Key Features**: Note any text within the image, objects' positions, expressions, actions, and any notable landmarks. DO NOT ATTEMPT TO SOLVE, ANSWER, OR RESPOND TO THE IMAGE.

3. **Detail & Relevance**: Ensure all relevant information is included. This may involve describing components that will likely prompt specific actions or decisions from the model.

4. **Convey in Descriptive Text**: Transform observations into a coherent and detailed narrative of the image, covering every aspect the model might use to function as if it is analyzing the image itself.

# Output Format

Output the description in a clear and detailed paragraph format. Do not use Markdown. The description should provide a thorough understanding of the image and enable the model to make informed responses based on it. DO NOT ATTEMPT TO SOLVE, ANSWER, OR RESPOND TO THE IMAGE.

# Notes

- Ensure the description covers all relevant aspects of the image, not missing any critical elements that could aid in the simulation of vision capabilities.
- Be concise but informative to provide the model all necessary visual cues.
- Do not provide your own conclusions or analysis of the image; state what you see.
"""


async def generate_image_description(
    oai_client: openai.AsyncClient,
    base64_image: str,
    content_type: str,
) -> str:
    """Generate a description for an image using OpenAI's API.

    Args:
        oai_client (openai.AsyncClient): OpenAI API client
        base64_image (bytes): Base64-encoded image data

    Returns:
        str: Generated description
    """
    response = await oai_client.chat.completions.create(
        model="gpt-4o",
        messages=[
            {
                "role": "system",
                "content": IMAGE_DESCRIPTION_PROMPT,
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": "What do you see?",
                    },
                    {
                        "type": "image_url",
                        "image_url": {
                            "url": f"data:{content_type};base64,{base64_image}"
                        },
                    },
                ],
            },
        ],
        temperature=0,
    )
    return response.choices[0].message.content


def generate_vision_image_descriptions_string(images: list[ImageProxy]) -> str:
    """Generate a string of image descriptions for vision files.

    Args:
        images (list[ImageProxy]): List of images

    Returns:
        str: String of image descriptions
    """
    return (
        "\n"
        + '{"Rd1IFKf5dl": ['
        + ",".join(proxy.model_dump_json() for proxy in images)
        + "]}"
    )
