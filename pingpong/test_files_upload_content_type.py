import io
from types import SimpleNamespace
from unittest.mock import AsyncMock

from fastapi import UploadFile
import pytest

from pingpong import files as files_module
from pingpong import models, schemas
from pingpong.files import (
    _normalize_upload_content_type,
    handle_create_generated_file,
)


def _upload(filename: str, content_type: str) -> UploadFile:
    return UploadFile(
        file=io.BytesIO(b"content"),
        filename=filename,
        headers={"content-type": content_type},
    )


def test_normalize_upload_content_type_uses_known_extension_for_generic_mime():
    upload = _upload("notes.md", "application/octet-stream")

    assert _normalize_upload_content_type(upload) == "text/markdown"


def test_normalize_upload_content_type_uses_known_extension_for_text_plain_mime():
    upload = _upload("notes.md", "text/plain")

    assert _normalize_upload_content_type(upload) == "text/markdown"


def test_normalize_upload_content_type_uses_leading_dot_filename_extension():
    upload = _upload(".md", "application/x-unknown")

    assert _normalize_upload_content_type(upload) == "text/markdown"


def test_normalize_upload_content_type_keeps_matching_generic_extension():
    upload = _upload("model.pkl", "application/octet-stream")

    assert _normalize_upload_content_type(upload) == "application/octet-stream"


def test_normalize_upload_content_type_keeps_supported_reported_mime():
    upload = _upload("notes.unknown", "text/markdown")

    assert _normalize_upload_content_type(upload) == "text/markdown"


@pytest.mark.asyncio
async def test_handle_create_generated_file_persists_without_tool_input(
    db, monkeypatch
):
    class FakeStore:
        def __init__(self):
            self.files = {}

        async def put(self, name, file, content_type):
            self.files[name] = (file.read(), content_type)

        async def delete(self, name):
            self.files.pop(name, None)

    async with db.async_session() as session:
        session.add_all(
            [
                models.User(
                    id=7101,
                    email="generated-file@test.dev",
                    state=schemas.UserState.VERIFIED,
                ),
                models.Class(id=7102, name="Generated File Class", api_key="sk-test"),
            ]
        )
        await session.commit()

    store = FakeStore()
    monkeypatch.setattr(files_module.config, "file_store", SimpleNamespace(store=store))
    authz = AsyncMock()

    async with db.async_session() as session:
        file = await handle_create_generated_file(
            session=session,
            authz=authz,
            upload=_upload("reminders.ics", "text/calendar"),
            class_id=7102,
            uploader_id=7101,
            private=True,
            source_file_id="cfile-calendar",
            user_auth="user:7101",
        )
        await session.commit()
        saved_file = await models.File.get_by_id_with_download(session, file.id)

    authz.write.assert_awaited_once()
    assert file.file_id == "cfile-calendar"
    assert file.code_interpreter_file_id is None
    assert saved_file.s3_file is not None
    assert store.files[saved_file.s3_file.key] == (b"content", "text/calendar")
