import asyncio
from datetime import datetime, timezone
from typing import Union
import openai
import logging
from fastapi import HTTPException, UploadFile
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from pathlib import Path
import uuid_utils as uuid

from .ai_error import get_details_from_api_error
from .authz import AuthzClient, Relation
from .config import config
from .log_utils import sanitize_for_log
from .models import File, S3File
from .schemas import FileTypeInfo, FileUploadPurpose, GenericStatus, ImageProxy
from .schemas import File as FileSchema
import base64

logger = logging.getLogger(__name__)
responses_api_transition_logger = logging.getLogger("responses_api_transition")

OpenAIClientType = Union[openai.AsyncClient, openai.AsyncAzureOpenAI]


async def _delete_orphaned_s3_files(
    session: AsyncSession, candidate_s3_file_ids: list[int | None]
) -> None:
    s3_file_ids = list(dict.fromkeys(id_ for id_ in candidate_s3_file_ids if id_))
    if not s3_file_ids or not config.file_store:
        return

    orphaned_s3_files = await S3File.get_orphaned_by_ids(session, s3_file_ids)
    delete_errors: list[Exception] = []
    for s3_file in orphaned_s3_files:
        try:
            await config.file_store.store.delete(s3_file.key)
        except Exception as exc:
            logger.exception(
                "Failed to delete orphaned uploaded file from file store. "
                "s3_file_id=%s key=%s",
                s3_file.id,
                sanitize_for_log(s3_file.key),
            )
            delete_errors.append(exc)
            continue
        await S3File.delete_by_ids(session, [s3_file.id])
    if delete_errors:
        raise RuntimeError("Failed to delete one or more orphaned uploaded files.")


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
            (
                f"anonymous_link:{file.anonymous_link.share_token}",
                "can_delete",
                target,
            )
        )

    grants.append((f"user:{file.uploader_id}", "owner", target))

    return grants


class FileNotFoundException(Exception):
    pass


async def validate_private_file_delete_permissions(
    session: AsyncSession, class_id: int, file_ids: list[int]
) -> None:
    if not file_ids:
        return

    unique_file_ids = list(set(file_ids))
    files = await File.get_all_by_id(session, unique_file_ids)
    file_map = {file.id: file for file in files}
    class_file_ids = await File.get_file_ids_for_class(
        session, class_id, unique_file_ids
    )

    forbidden_ids = [
        file_id
        for file_id in unique_file_ids
        if file_id not in file_map or file_id not in class_file_ids
    ]
    if forbidden_ids:
        # Keep this generic to avoid leaking file existence across classes.
        logger.warning(
            "Rejected private file deletion request. class_id=%s forbidden_file_ids=%s",
            sanitize_for_log(str(class_id)),
            sanitize_for_log(",".join(str(file_id) for file_id in forbidden_ids)),
        )
        raise HTTPException(
            status_code=403,
            detail="You do not have permission to delete one or more private files.",
        )

    non_private_ids = [
        file_id for file_id in unique_file_ids if not file_map[file_id].private
    ]
    if non_private_ids:
        logger.warning(
            "Rejected non-private file id in deleted_private_files. class_id=%s file_ids=%s",
            sanitize_for_log(str(class_id)),
            sanitize_for_log(",".join(str(file_id) for file_id in non_private_ids)),
        )
        file_id = non_private_ids[0]
        raise HTTPException(
            status_code=400,
            detail=f"File {file_id} is not a private file and cannot be deleted via this field.",
        )


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
    file = await File.get_by_id_with_delete_context(session, int_file_id)
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
    candidate_s3_file_ids = [file.s3_file_id]

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
            await _delete_orphaned_s3_files(session, candidate_s3_file_ids)
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
            "Could not find the following files for deletion: %s",
            sanitize_for_log(",".join(str(file_id) for file_id in missing_ids)),
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
    candidate_s3_file_ids = [
        file.s3_file_id for file in files if file.id in file_ids_to_delete
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
                "Could not find the following files for deletion: %s",
                sanitize_for_log(",".join(str(file_id) for file_id in missing_ids)),
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
    await _delete_orphaned_s3_files(session, candidate_s3_file_ids)

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
        openai_file_purpose = (
            "user_data" if purpose == "assistants" and not is_azure_client else purpose
        )
        new_f = await oai_client.files.create(
            # NOTE(jnu): the client tries to infer the filename, which doesn't
            # work on this file that exists as bytes in memory. There's an
            # undocumented way to specify name, content, and content_type which
            # we use here to force correctness.
            # https://github.com/stanford-policylab/pingpong/issues/147
            file=(upload.filename.lower(), upload.file, upload.content_type),
            purpose=openai_file_purpose,
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

    file = None
    if "multimodal" in purpose:
        file = await handle_multimodal_upload(
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
        file = await handle_create_single_purpose_file(
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

    if not file:
        raise HTTPException(
            status_code=500, detail="File not uploaded, something went wrong!"
        )

    suffix = Path(upload.filename).suffix.lower()
    upload_filename = f"file_{uuid.uuid4()}{suffix}"
    await config.file_store.store.put(upload_filename, upload.file, upload.content_type)

    added_file_ids = list(
        filter(
            None,
            [
                file.file_id,
                file.file_search_file_id,
                file.code_interpreter_file_id,
                file.vision_file_id,
            ],
        )
    )
    added_file_obj_ids = [file.vision_obj_id] if file.vision_obj_id else []

    responses_api_transition_logger.debug(
        f"Creating S3File for file {file.name} with key {upload_filename}, "
        f"file_ids: {added_file_ids}, file_obj_ids: {added_file_obj_ids}"
    )
    s3_file = await S3File.create(
        session,
        key=upload_filename,
        file_obj_ids=added_file_obj_ids,
        file_ids=added_file_ids,
    )

    responses_api_transition_logger.debug(
        f"Created S3File {s3_file.id} with key {s3_file.key} for file {file.name}"
    )

    return file


# FILE_TYPES is the upload capability source of truth.
# input_file support comes from:
# https://developers.openai.com/api/docs/guides/file-inputs#full-list-of-accepted-file-types
# file_search support information comes from:
# https://developers.openai.com/api/docs/guides/tools-file-search#supported-files
# code_interpreter support information comes from:
# https://developers.openai.com/api/docs/guides/tools-code-interpreter#supported-files
# vision support information comes from:
# https://developers.openai.com/api/docs/guides/images-vision#image-input-requirements
FILE_TYPES = [
    FileTypeInfo(
        mime_type="text/x-c",
        name="C",
        file_search=True,
        code_interpreter=True,
        vision=False,
        input_file=True,
        extensions=["c"],
    ),
    FileTypeInfo(
        mime_type="text/x-c++",
        name="C++",
        file_search=True,
        code_interpreter=True,
        vision=False,
        input_file=True,
        extensions=["cpp", "cc", "cxx", "c++"],
    ),
    FileTypeInfo(
        mime_type="text/csv",
        name="CSV",
        file_search=False,
        code_interpreter=True,
        vision=False,
        input_file=True,
        extensions=["csv"],
    ),
    FileTypeInfo(
        mime_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        name="Word Doc",
        file_search=True,
        code_interpreter=True,
        vision=False,
        input_file=True,
        extensions=["docx"],
    ),
    FileTypeInfo(
        mime_type="text/html",
        name="HTML",
        file_search=True,
        code_interpreter=True,
        vision=False,
        input_file=True,
        extensions=["html", "htm"],
    ),
    FileTypeInfo(
        mime_type="text/x-java",
        name="Java",
        file_search=True,
        code_interpreter=True,
        vision=False,
        input_file=True,
        extensions=["java"],
    ),
    FileTypeInfo(
        mime_type="application/json",
        name="JSON",
        file_search=True,
        code_interpreter=True,
        vision=False,
        input_file=True,
        extensions=["json"],
    ),
    FileTypeInfo(
        mime_type="text/markdown",
        name="Markdown",
        file_search=True,
        code_interpreter=True,
        vision=False,
        input_file=True,
        extensions=["md", "markdown"],
    ),
    FileTypeInfo(
        mime_type="application/pdf",
        name="PDF",
        file_search=True,
        code_interpreter=True,
        vision=False,
        input_file=True,
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
        input_file=True,
        extensions=["pptx"],
    ),
    FileTypeInfo(
        mime_type="text/x-python",
        name="Python",
        file_search=True,
        code_interpreter=True,
        vision=False,
        input_file=True,
        extensions=["py"],
    ),
    FileTypeInfo(
        mime_type="text/x-script.python",
        name="Python",
        file_search=True,
        code_interpreter=True,
        vision=False,
        input_file=True,
        extensions=["py"],
    ),
    FileTypeInfo(
        mime_type="text/x-ruby",
        name="Ruby",
        file_search=True,
        code_interpreter=True,
        vision=False,
        input_file=True,
        extensions=["rb"],
    ),
    FileTypeInfo(
        mime_type="text/x-tex",
        name="LaTeX",
        file_search=True,
        code_interpreter=True,
        vision=False,
        input_file=True,
        extensions=["tex"],
    ),
    FileTypeInfo(
        mime_type="text/plain",
        name="Text",
        file_search=True,
        code_interpreter=True,
        vision=False,
        input_file=True,
        extensions=["txt"],
    ),
    FileTypeInfo(
        mime_type="text/css",
        name="CSS",
        file_search=True,
        code_interpreter=True,
        vision=False,
        input_file=True,
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
        file_search=True,
        code_interpreter=True,
        vision=False,
        input_file=True,
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
        file_search=True,
        code_interpreter=True,
        vision=False,
        input_file=True,
        extensions=["ts"],
    ),
    FileTypeInfo(
        mime_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        name="Excel",
        file_search=False,
        code_interpreter=True,
        vision=False,
        input_file=True,
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
        input_file=True,
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
    FileTypeInfo(
        mime_type="application/csv",
        name="CSV",
        file_search=False,
        code_interpreter=True,
        vision=False,
        input_file=True,
        extensions=["csv"],
    ),
    FileTypeInfo(
        mime_type="text/tsv",
        name="TSV",
        file_search=False,
        code_interpreter=False,
        vision=False,
        input_file=True,
        extensions=["tsv"],
    ),
    FileTypeInfo(
        mime_type="text/x-iif",
        name="IIF",
        file_search=False,
        code_interpreter=False,
        vision=False,
        input_file=True,
        extensions=["iif"],
    ),
    FileTypeInfo(
        mime_type="application/x-iif",
        name="IIF",
        file_search=False,
        code_interpreter=False,
        vision=False,
        input_file=True,
        extensions=["iif"],
    ),
    FileTypeInfo(
        mime_type="application/vnd.google-apps.spreadsheet",
        name="Google Sheets",
        file_search=False,
        code_interpreter=False,
        vision=False,
        input_file=True,
        extensions=[],
    ),
    FileTypeInfo(
        mime_type="application/vnd.ms-excel",
        name="Excel",
        file_search=False,
        code_interpreter=False,
        vision=False,
        input_file=True,
        extensions=["xla", "xlb", "xlc", "xlm", "xls", "xlt", "xlw"],
    ),
    FileTypeInfo(
        mime_type="application/msword",
        name="Word Doc",
        file_search=True,
        code_interpreter=True,
        vision=False,
        input_file=True,
        extensions=["doc", "dot"],
    ),
    FileTypeInfo(
        mime_type="application/rtf",
        name="RTF",
        file_search=False,
        code_interpreter=False,
        vision=False,
        input_file=True,
        extensions=["rtf"],
    ),
    FileTypeInfo(
        mime_type="text/rtf",
        name="RTF",
        file_search=False,
        code_interpreter=False,
        vision=False,
        input_file=True,
        extensions=["rtf"],
    ),
    FileTypeInfo(
        mime_type="application/vnd.oasis.opendocument.text",
        name="OpenDocument Text",
        file_search=False,
        code_interpreter=False,
        vision=False,
        input_file=True,
        extensions=["odt"],
    ),
    FileTypeInfo(
        mime_type="application/vnd.apple.pages",
        name="Pages",
        file_search=False,
        code_interpreter=False,
        vision=False,
        input_file=True,
        extensions=["pages"],
    ),
    FileTypeInfo(
        mime_type="application/vnd.google-apps.document",
        name="Google Docs",
        file_search=False,
        code_interpreter=False,
        vision=False,
        input_file=True,
        extensions=[],
    ),
    FileTypeInfo(
        mime_type="application/vnd.apple.iwork",
        name="iWork",
        file_search=False,
        code_interpreter=False,
        vision=False,
        input_file=True,
        extensions=["pages", "key", "numbers"],
    ),
    FileTypeInfo(
        mime_type="application/vnd.ms-powerpoint",
        name="PowerPoint",
        file_search=False,
        code_interpreter=False,
        vision=False,
        input_file=True,
        extensions=["ppt", "pot", "ppa", "pps", "pwz", "wiz"],
    ),
    FileTypeInfo(
        mime_type="application/vnd.apple.keynote",
        name="Keynote",
        file_search=False,
        code_interpreter=False,
        vision=False,
        input_file=True,
        extensions=["key"],
    ),
    FileTypeInfo(
        mime_type="application/vnd.google-apps.presentation",
        name="Google Slides",
        file_search=False,
        code_interpreter=False,
        vision=False,
        input_file=True,
        extensions=[],
    ),
    FileTypeInfo(
        mime_type="application/javascript",
        name="JavaScript",
        file_search=False,
        code_interpreter=False,
        vision=False,
        input_file=True,
        extensions=["js", "mjs"],
    ),
    FileTypeInfo(
        mime_type="text/x-shellscript",
        name="Shell Script",
        file_search=False,
        code_interpreter=False,
        vision=False,
        input_file=True,
        extensions=["bat", "ksh", "sh", "bash", "zsh"],
    ),
    FileTypeInfo(
        mime_type="text/x-rst",
        name="reStructuredText",
        file_search=False,
        code_interpreter=False,
        vision=False,
        input_file=True,
        extensions=["rst"],
    ),
    FileTypeInfo(
        mime_type="text/x-makefile",
        name="Makefile",
        file_search=False,
        code_interpreter=False,
        vision=False,
        input_file=True,
        extensions=["mk"],
    ),
    FileTypeInfo(
        mime_type="text/x-lisp",
        name="Lisp",
        file_search=False,
        code_interpreter=False,
        vision=False,
        input_file=True,
        extensions=["lisp", "lsp"],
    ),
    FileTypeInfo(
        mime_type="text/x-asm",
        name="Assembly",
        file_search=False,
        code_interpreter=False,
        vision=False,
        input_file=True,
        extensions=["asm", "s"],
    ),
    FileTypeInfo(
        mime_type="text/vbscript",
        name="VBScript",
        file_search=False,
        code_interpreter=False,
        vision=False,
        input_file=True,
        extensions=["vbs"],
    ),
    FileTypeInfo(
        mime_type="message/rfc822",
        name="Email",
        file_search=False,
        code_interpreter=False,
        vision=False,
        input_file=True,
        extensions=["eml", "mime", "mht", "mhtml", "nws"],
    ),
    FileTypeInfo(
        mime_type="application/x-sql",
        name="SQL",
        file_search=False,
        code_interpreter=False,
        vision=False,
        input_file=True,
        extensions=["sql"],
    ),
    FileTypeInfo(
        mime_type="application/x-scala",
        name="Scala",
        file_search=False,
        code_interpreter=False,
        vision=False,
        input_file=True,
        extensions=["scala"],
    ),
    FileTypeInfo(
        mime_type="application/x-rust",
        name="Rust",
        file_search=False,
        code_interpreter=False,
        vision=False,
        input_file=True,
        extensions=["rs"],
    ),
    FileTypeInfo(
        mime_type="application/x-powershell",
        name="PowerShell",
        file_search=False,
        code_interpreter=False,
        vision=False,
        input_file=True,
        extensions=["ps1"],
    ),
    FileTypeInfo(
        mime_type="text/x-diff",
        name="Diff",
        file_search=False,
        code_interpreter=False,
        vision=False,
        input_file=True,
        extensions=["diff"],
    ),
    FileTypeInfo(
        mime_type="text/x-patch",
        name="Patch",
        file_search=False,
        code_interpreter=False,
        vision=False,
        input_file=True,
        extensions=["patch"],
    ),
    FileTypeInfo(
        mime_type="application/x-patch",
        name="Patch",
        file_search=False,
        code_interpreter=False,
        vision=False,
        input_file=True,
        extensions=["patch"],
    ),
    FileTypeInfo(
        mime_type="text/x-golang",
        name="Go",
        file_search=True,
        code_interpreter=False,
        vision=False,
        input_file=True,
        extensions=["go"],
    ),
    FileTypeInfo(
        mime_type="text/x-php",
        name="PHP",
        file_search=True,
        code_interpreter=True,
        vision=False,
        input_file=True,
        extensions=["php"],
    ),
    FileTypeInfo(
        mime_type="application/x-php",
        name="PHP",
        file_search=False,
        code_interpreter=False,
        vision=False,
        input_file=True,
        extensions=["php"],
    ),
    FileTypeInfo(
        mime_type="application/x-httpd-php",
        name="PHP",
        file_search=False,
        code_interpreter=False,
        vision=False,
        input_file=True,
        extensions=["php"],
    ),
    FileTypeInfo(
        mime_type="application/x-httpd-php-source",
        name="PHP Source",
        file_search=False,
        code_interpreter=False,
        vision=False,
        input_file=True,
        extensions=["php"],
    ),
    FileTypeInfo(
        mime_type="text/x-sh",
        name="Shell Script",
        file_search=False,
        code_interpreter=False,
        vision=False,
        input_file=True,
        extensions=["sh"],
    ),
    FileTypeInfo(
        mime_type="application/x-sh",
        name="Shell Script",
        file_search=True,
        code_interpreter=True,
        vision=False,
        extensions=["sh"],
    ),
    FileTypeInfo(
        mime_type="text/x-bash",
        name="Bash",
        file_search=False,
        code_interpreter=False,
        vision=False,
        input_file=True,
        extensions=["bash"],
    ),
    FileTypeInfo(
        mime_type="application/x-bash",
        name="Bash",
        file_search=False,
        code_interpreter=False,
        vision=False,
        input_file=True,
        extensions=["bash"],
    ),
    FileTypeInfo(
        mime_type="text/x-zsh",
        name="Zsh",
        file_search=False,
        code_interpreter=False,
        vision=False,
        input_file=True,
        extensions=["zsh"],
    ),
    FileTypeInfo(
        mime_type="text/x-csharp",
        name="C#",
        file_search=True,
        code_interpreter=True,
        vision=False,
        input_file=True,
        extensions=["cs"],
    ),
    FileTypeInfo(
        mime_type="text/x-typescript",
        name="TypeScript",
        file_search=False,
        code_interpreter=False,
        vision=False,
        input_file=True,
        extensions=["ts"],
    ),
    FileTypeInfo(
        mime_type="text/x-go",
        name="Go",
        file_search=False,
        code_interpreter=False,
        vision=False,
        input_file=True,
        extensions=["go"],
    ),
    FileTypeInfo(
        mime_type="text/x-rust",
        name="Rust",
        file_search=False,
        code_interpreter=False,
        vision=False,
        input_file=True,
        extensions=["rs"],
    ),
    FileTypeInfo(
        mime_type="text/x-scala",
        name="Scala",
        file_search=False,
        code_interpreter=False,
        vision=False,
        input_file=True,
        extensions=["scala"],
    ),
    FileTypeInfo(
        mime_type="text/x-kotlin",
        name="Kotlin",
        file_search=False,
        code_interpreter=False,
        vision=False,
        input_file=True,
        extensions=["kt", "kts"],
    ),
    FileTypeInfo(
        mime_type="text/x-swift",
        name="Swift",
        file_search=False,
        code_interpreter=False,
        vision=False,
        input_file=True,
        extensions=["swift"],
    ),
    FileTypeInfo(
        mime_type="text/x-lua",
        name="Lua",
        file_search=False,
        code_interpreter=False,
        vision=False,
        input_file=True,
        extensions=["lua"],
    ),
    FileTypeInfo(
        mime_type="text/x-r",
        name="R",
        file_search=False,
        code_interpreter=False,
        vision=False,
        input_file=True,
        extensions=["r"],
    ),
    FileTypeInfo(
        mime_type="text/x-R",
        name="R",
        file_search=False,
        code_interpreter=False,
        vision=False,
        input_file=True,
        extensions=["R"],
    ),
    FileTypeInfo(
        mime_type="text/x-julia",
        name="Julia",
        file_search=False,
        code_interpreter=False,
        vision=False,
        input_file=True,
        extensions=["jl"],
    ),
    FileTypeInfo(
        mime_type="text/x-perl",
        name="Perl",
        file_search=False,
        code_interpreter=False,
        vision=False,
        input_file=True,
        extensions=["pl", "pm"],
    ),
    FileTypeInfo(
        mime_type="text/x-objectivec",
        name="Objective-C",
        file_search=False,
        code_interpreter=False,
        vision=False,
        input_file=True,
        extensions=["m"],
    ),
    FileTypeInfo(
        mime_type="text/x-objectivec++",
        name="Objective-C++",
        file_search=False,
        code_interpreter=False,
        vision=False,
        input_file=True,
        extensions=["mm"],
    ),
    FileTypeInfo(
        mime_type="text/x-erlang",
        name="Erlang",
        file_search=False,
        code_interpreter=False,
        vision=False,
        input_file=True,
        extensions=["erl", "hrl"],
    ),
    FileTypeInfo(
        mime_type="text/x-elixir",
        name="Elixir",
        file_search=False,
        code_interpreter=False,
        vision=False,
        input_file=True,
        extensions=["ex", "exs"],
    ),
    FileTypeInfo(
        mime_type="text/x-haskell",
        name="Haskell",
        file_search=False,
        code_interpreter=False,
        vision=False,
        input_file=True,
        extensions=["hs"],
    ),
    FileTypeInfo(
        mime_type="text/x-clojure",
        name="Clojure",
        file_search=False,
        code_interpreter=False,
        vision=False,
        input_file=True,
        extensions=["clj", "cljs", "cljc"],
    ),
    FileTypeInfo(
        mime_type="text/x-groovy",
        name="Groovy",
        file_search=False,
        code_interpreter=False,
        vision=False,
        input_file=True,
        extensions=["groovy"],
    ),
    FileTypeInfo(
        mime_type="text/x-dart",
        name="Dart",
        file_search=False,
        code_interpreter=False,
        vision=False,
        input_file=True,
        extensions=["dart"],
    ),
    FileTypeInfo(
        mime_type="text/x-awk",
        name="AWK",
        file_search=False,
        code_interpreter=False,
        vision=False,
        input_file=True,
        extensions=["awk"],
    ),
    FileTypeInfo(
        mime_type="application/x-awk",
        name="AWK",
        file_search=False,
        code_interpreter=False,
        vision=False,
        input_file=True,
        extensions=["awk"],
    ),
    FileTypeInfo(
        mime_type="text/jsx",
        name="JSX",
        file_search=False,
        code_interpreter=False,
        vision=False,
        input_file=True,
        extensions=["jsx"],
    ),
    FileTypeInfo(
        mime_type="text/tsx",
        name="TSX",
        file_search=False,
        code_interpreter=False,
        vision=False,
        input_file=True,
        extensions=["tsx"],
    ),
    FileTypeInfo(
        mime_type="text/x-handlebars",
        name="Handlebars",
        file_search=False,
        code_interpreter=False,
        vision=False,
        input_file=True,
        extensions=["hbs", "handlebars"],
    ),
    FileTypeInfo(
        mime_type="text/x-mustache",
        name="Mustache",
        file_search=False,
        code_interpreter=False,
        vision=False,
        input_file=True,
        extensions=["mustache"],
    ),
    FileTypeInfo(
        mime_type="text/x-ejs",
        name="EJS",
        file_search=False,
        code_interpreter=False,
        vision=False,
        input_file=True,
        extensions=["ejs"],
    ),
    FileTypeInfo(
        mime_type="text/x-jinja2",
        name="Jinja2",
        file_search=False,
        code_interpreter=False,
        vision=False,
        input_file=True,
        extensions=["jinja", "jinja2"],
    ),
    FileTypeInfo(
        mime_type="text/x-liquid",
        name="Liquid",
        file_search=False,
        code_interpreter=False,
        vision=False,
        input_file=True,
        extensions=["liquid"],
    ),
    FileTypeInfo(
        mime_type="text/x-erb",
        name="ERB",
        file_search=False,
        code_interpreter=False,
        vision=False,
        input_file=True,
        extensions=["erb"],
    ),
    FileTypeInfo(
        mime_type="text/x-twig",
        name="Twig",
        file_search=False,
        code_interpreter=False,
        vision=False,
        input_file=True,
        extensions=["twig"],
    ),
    FileTypeInfo(
        mime_type="text/x-pug",
        name="Pug",
        file_search=False,
        code_interpreter=False,
        vision=False,
        input_file=True,
        extensions=["pug"],
    ),
    FileTypeInfo(
        mime_type="text/x-jade",
        name="Jade",
        file_search=False,
        code_interpreter=False,
        vision=False,
        input_file=True,
        extensions=["jade"],
    ),
    FileTypeInfo(
        mime_type="text/x-tmpl",
        name="Template",
        file_search=False,
        code_interpreter=False,
        vision=False,
        input_file=True,
        extensions=["tmpl"],
    ),
    FileTypeInfo(
        mime_type="text/x-cmake",
        name="CMake",
        file_search=False,
        code_interpreter=False,
        vision=False,
        input_file=True,
        extensions=["cmake"],
    ),
    FileTypeInfo(
        mime_type="text/x-dockerfile",
        name="Dockerfile",
        file_search=False,
        code_interpreter=False,
        vision=False,
        input_file=True,
        extensions=["dockerfile"],
    ),
    FileTypeInfo(
        mime_type="text/x-gradle",
        name="Gradle",
        file_search=False,
        code_interpreter=False,
        vision=False,
        input_file=True,
        extensions=["gradle"],
    ),
    FileTypeInfo(
        mime_type="text/x-ini",
        name="INI",
        file_search=False,
        code_interpreter=False,
        vision=False,
        input_file=True,
        extensions=["ini"],
    ),
    FileTypeInfo(
        mime_type="text/x-properties",
        name="Properties",
        file_search=False,
        code_interpreter=False,
        vision=False,
        input_file=True,
        extensions=["properties"],
    ),
    FileTypeInfo(
        mime_type="text/x-protobuf",
        name="Protocol Buffers",
        file_search=False,
        code_interpreter=False,
        vision=False,
        input_file=True,
        extensions=["proto"],
    ),
    FileTypeInfo(
        mime_type="application/x-protobuf",
        name="Protocol Buffers",
        file_search=False,
        code_interpreter=False,
        vision=False,
        input_file=True,
        extensions=["proto"],
    ),
    FileTypeInfo(
        mime_type="text/x-sql",
        name="SQL",
        file_search=False,
        code_interpreter=False,
        vision=False,
        input_file=True,
        extensions=["sql"],
    ),
    FileTypeInfo(
        mime_type="text/x-sass",
        name="Sass",
        file_search=False,
        code_interpreter=False,
        vision=False,
        input_file=True,
        extensions=["sass"],
    ),
    FileTypeInfo(
        mime_type="text/x-scss",
        name="SCSS",
        file_search=False,
        code_interpreter=False,
        vision=False,
        input_file=True,
        extensions=["scss"],
    ),
    FileTypeInfo(
        mime_type="text/x-less",
        name="Less",
        file_search=False,
        code_interpreter=False,
        vision=False,
        input_file=True,
        extensions=["less"],
    ),
    FileTypeInfo(
        mime_type="text/x-hcl",
        name="HCL",
        file_search=False,
        code_interpreter=False,
        vision=False,
        input_file=True,
        extensions=["hcl"],
    ),
    FileTypeInfo(
        mime_type="text/x-terraform",
        name="Terraform",
        file_search=False,
        code_interpreter=False,
        vision=False,
        input_file=True,
        extensions=["tf"],
    ),
    FileTypeInfo(
        mime_type="application/x-terraform",
        name="Terraform",
        file_search=False,
        code_interpreter=False,
        vision=False,
        input_file=True,
        extensions=["tf"],
    ),
    FileTypeInfo(
        mime_type="text/x-toml",
        name="TOML",
        file_search=False,
        code_interpreter=False,
        vision=False,
        input_file=True,
        extensions=["toml"],
    ),
    FileTypeInfo(
        mime_type="application/toml",
        name="TOML",
        file_search=False,
        code_interpreter=False,
        vision=False,
        input_file=True,
        extensions=["toml"],
    ),
    FileTypeInfo(
        mime_type="application/x-toml",
        name="TOML",
        file_search=False,
        code_interpreter=False,
        vision=False,
        input_file=True,
        extensions=["toml"],
    ),
    FileTypeInfo(
        mime_type="application/graphql",
        name="GraphQL",
        file_search=False,
        code_interpreter=False,
        vision=False,
        input_file=True,
        extensions=["graphql", "gql"],
    ),
    FileTypeInfo(
        mime_type="application/x-graphql",
        name="GraphQL",
        file_search=False,
        code_interpreter=False,
        vision=False,
        input_file=True,
        extensions=["graphql", "gql"],
    ),
    FileTypeInfo(
        mime_type="text/x-graphql",
        name="GraphQL",
        file_search=False,
        code_interpreter=False,
        vision=False,
        input_file=True,
        extensions=["graphql", "gql"],
    ),
    FileTypeInfo(
        mime_type="application/x-ndjson",
        name="NDJSON",
        file_search=False,
        code_interpreter=False,
        vision=False,
        input_file=True,
        extensions=["ndjson"],
    ),
    FileTypeInfo(
        mime_type="application/json5",
        name="JSON5",
        file_search=False,
        code_interpreter=False,
        vision=False,
        input_file=True,
        extensions=["json5"],
    ),
    FileTypeInfo(
        mime_type="application/x-json5",
        name="JSON5",
        file_search=False,
        code_interpreter=False,
        vision=False,
        input_file=True,
        extensions=["json5"],
    ),
    FileTypeInfo(
        mime_type="text/x-yaml",
        name="YAML",
        file_search=False,
        code_interpreter=False,
        vision=False,
        input_file=True,
        extensions=["yaml", "yml"],
    ),
    FileTypeInfo(
        mime_type="application/x-yaml",
        name="YAML",
        file_search=False,
        code_interpreter=False,
        vision=False,
        input_file=True,
        extensions=["yaml", "yml"],
    ),
    FileTypeInfo(
        mime_type="application/yaml",
        name="YAML",
        file_search=False,
        code_interpreter=False,
        vision=False,
        input_file=True,
        extensions=["yaml", "yml"],
    ),
    FileTypeInfo(
        mime_type="text/x-astro",
        name="Astro",
        file_search=False,
        code_interpreter=False,
        vision=False,
        input_file=True,
        extensions=["astro"],
    ),
    FileTypeInfo(
        mime_type="text/srt",
        name="SubRip",
        file_search=False,
        code_interpreter=False,
        vision=False,
        input_file=True,
        extensions=["srt"],
    ),
    FileTypeInfo(
        mime_type="application/x-subrip",
        name="SubRip",
        file_search=False,
        code_interpreter=False,
        vision=False,
        input_file=True,
        extensions=["srt"],
    ),
    FileTypeInfo(
        mime_type="text/x-subrip",
        name="SubRip",
        file_search=False,
        code_interpreter=False,
        vision=False,
        input_file=True,
        extensions=["srt"],
    ),
    FileTypeInfo(
        mime_type="text/vtt",
        name="WebVTT",
        file_search=False,
        code_interpreter=False,
        vision=False,
        input_file=True,
        extensions=["vtt"],
    ),
    FileTypeInfo(
        mime_type="text/x-vcard",
        name="vCard",
        file_search=False,
        code_interpreter=False,
        vision=False,
        input_file=True,
        extensions=["vcf"],
    ),
    FileTypeInfo(
        mime_type="text/calendar",
        name="Calendar",
        file_search=False,
        code_interpreter=False,
        vision=False,
        input_file=True,
        extensions=["ics", "ifb"],
    ),
    FileTypeInfo(
        mime_type="application/octet-stream",
        name="Pickle",
        file_search=False,
        code_interpreter=True,
        vision=False,
        extensions=["pkl"],
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


def file_extension_to_mime_type(extension: str) -> str | None:
    """Convert a file extension to its corresponding MIME type."""
    for file_type in FILE_TYPES:
        if extension in file_type.extensions:
            return file_type.mime_type
    return None


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
