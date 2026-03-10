import importlib
from types import SimpleNamespace
from unittest.mock import AsyncMock

from pingpong import models
import pingpong.schemas as schemas

from .testutil import with_authz, with_user

server_module = importlib.import_module("pingpong.server")


def _make_v2_message(
    message_id: str,
    file_id: str,
    *,
    role: str = "user",
    tool_types: tuple[str, ...] = ("file_search",),
):
    return SimpleNamespace(
        id=message_id,
        role=role,
        attachments=[
            SimpleNamespace(
                file_id=file_id,
                tools=[SimpleNamespace(type=tool_type) for tool_type in tool_types],
            )
        ],
        content=[],
    )


def _make_openai_client(*, retrieve=None):
    if retrieve is None:

        async def retrieve(*_args, **_kwargs):
            return None

    return SimpleNamespace(
        beta=SimpleNamespace(
            threads=SimpleNamespace(
                messages=SimpleNamespace(
                    retrieve=AsyncMock(side_effect=retrieve),
                )
            )
        ),
        vector_stores=SimpleNamespace(
            files=SimpleNamespace(delete=AsyncMock()),
        ),
        files=SimpleNamespace(delete=AsyncMock()),
    )


def _patch_openai_client(monkeypatch, class_id: int, openai_client):
    async def fake_get_openai_client_by_class_id(_session, requested_class_id: int):
        assert requested_class_id == class_id
        return openai_client

    monkeypatch.setattr(
        server_module,
        "get_openai_client_by_class_id",
        fake_get_openai_client_by_class_id,
    )


@with_user(123)
@with_authz(grants=[("user:123", "can_participate", "thread:20")])
async def test_delete_thread_file_v2_file_search_upload_by_current_user_succeeds(
    api, db, valid_user_token, monkeypatch
):
    async with db.async_session() as session:
        session.add(models.Class(id=10, name="Class 10"))
        vector_store = models.VectorStore(
            id=500,
            vector_store_id="vs-thread-20",
            type=schemas.VectorStoreType.THREAD,
            class_id=10,
        )
        file = models.File(
            id=77,
            file_id="file-allowed",
            name="report.csv",
            content_type="text/csv",
            class_id=10,
            private=True,
            uploader_id=123,
        )
        vector_store.files = [file]
        session.add(vector_store)
        session.add(
            models.Thread(
                id=20,
                class_id=10,
                version=2,
                thread_id="oai-thread-20",
                vector_store_id=vector_store.id,
                private=False,
            )
        )
        await session.commit()

    async def fake_retrieve(message_id: str, thread_id: str):
        assert message_id == "msg-target"
        assert thread_id == "oai-thread-20"
        return _make_v2_message(
            "msg-target", "file-allowed", tool_types=("file_search",)
        )

    openai_client = _make_openai_client(retrieve=fake_retrieve)
    _patch_openai_client(monkeypatch, 10, openai_client)

    response = api.delete(
        "/api/v1/class/10/thread/20/message/msg-target/file/file-allowed",
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )

    assert response.status_code == 200
    openai_client.vector_stores.files.delete.assert_awaited_once_with(
        vector_store_id="vs-thread-20",
        file_id="file-allowed",
    )
    openai_client.files.delete.assert_awaited_once_with("file-allowed")

    async with db.async_session() as session:
        assert not await models.Thread.thread_vector_store_contains_file(
            session, 20, 77
        )
        assert await models.File.get_by_file_id(session, "file-allowed") is None


@with_user(123)
@with_authz(grants=[("user:123", "can_participate", "thread:21")])
async def test_delete_thread_file_v2_code_interpreter_upload_by_current_user_succeeds(
    api, db, valid_user_token, monkeypatch
):
    async with db.async_session() as session:
        session.add(models.Class(id=11, name="Class 11"))
        file = models.File(
            id=78,
            file_id="file-ci",
            name="script.py",
            content_type="text/x-python",
            class_id=11,
            private=True,
            uploader_id=123,
        )
        session.add(file)
        session.add(
            models.Thread(
                id=21,
                class_id=11,
                version=2,
                thread_id="oai-thread-21",
                code_interpreter_files=[file],
                private=False,
            )
        )
        await session.commit()

    async def fake_retrieve(message_id: str, thread_id: str):
        assert message_id == "msg-ci"
        assert thread_id == "oai-thread-21"
        return _make_v2_message(
            "msg-ci",
            "file-ci",
            tool_types=("code_interpreter",),
        )

    openai_client = _make_openai_client(retrieve=fake_retrieve)
    _patch_openai_client(monkeypatch, 11, openai_client)

    response = api.delete(
        "/api/v1/class/11/thread/21/message/msg-ci/file/file-ci",
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )

    assert response.status_code == 200
    openai_client.vector_stores.files.delete.assert_not_awaited()
    openai_client.files.delete.assert_awaited_once_with("file-ci")

    async with db.async_session() as session:
        assert not await models.Thread.thread_code_interpreter_contains_file(
            session, 21, 78
        )
        assert await models.File.get_by_file_id(session, "file-ci") is None


@with_user(123)
@with_authz(grants=[("user:123", "can_participate", "thread:22")])
async def test_delete_thread_file_v2_wrong_message_id_returns_404(
    api, db, valid_user_token, monkeypatch
):
    async with db.async_session() as session:
        session.add(models.Class(id=12, name="Class 12"))
        file = models.File(
            id=79,
            file_id="file-missing-message",
            name="report.csv",
            content_type="text/csv",
            class_id=12,
            private=True,
            uploader_id=123,
        )
        session.add(file)
        session.add(
            models.Thread(
                id=22,
                class_id=12,
                version=2,
                thread_id="oai-thread-22",
                code_interpreter_files=[file],
                private=False,
            )
        )
        await session.commit()

    async def fake_retrieve(message_id: str, thread_id: str):
        assert thread_id == "oai-thread-22"
        return None

    openai_client = _make_openai_client(retrieve=fake_retrieve)
    _patch_openai_client(monkeypatch, 12, openai_client)

    response = api.delete(
        "/api/v1/class/12/thread/22/message/msg-wrong/file/file-missing-message",
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )

    assert response.status_code == 404
    openai_client.vector_stores.files.delete.assert_not_awaited()
    openai_client.files.delete.assert_not_awaited()


@with_user(123)
@with_authz(grants=[("user:123", "can_participate", "thread:23")])
async def test_delete_thread_file_v2_assistant_generated_file_is_rejected(
    api, db, valid_user_token, monkeypatch
):
    async with db.async_session() as session:
        session.add(models.Class(id=13, name="Class 13"))
        file = models.File(
            id=80,
            file_id="file-assistant",
            name="assistant.csv",
            content_type="text/csv",
            class_id=13,
            private=True,
            uploader_id=123,
        )
        session.add(file)
        session.add(
            models.Thread(
                id=23,
                class_id=13,
                version=2,
                thread_id="oai-thread-23",
                code_interpreter_files=[file],
                private=False,
            )
        )
        await session.commit()

    async def fake_retrieve(message_id: str, thread_id: str):
        assert thread_id == "oai-thread-23"
        return _make_v2_message(
            "msg-assistant",
            "file-assistant",
            role="assistant",
            tool_types=("code_interpreter",),
        )

    openai_client = _make_openai_client(retrieve=fake_retrieve)
    _patch_openai_client(monkeypatch, 13, openai_client)

    response = api.delete(
        "/api/v1/class/13/thread/23/message/msg-assistant/file/file-assistant",
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )

    assert response.status_code == 404
    openai_client.files.delete.assert_not_awaited()


@with_user(123)
@with_authz(grants=[("user:123", "can_participate", "thread:24")])
async def test_delete_thread_file_v2_image_file_is_rejected(
    api, db, valid_user_token, monkeypatch
):
    async with db.async_session() as session:
        session.add(models.Class(id=14, name="Class 14"))
        file = models.File(
            id=81,
            file_id="file-image",
            name="image.png",
            content_type="image/png",
            class_id=14,
            private=True,
            uploader_id=123,
        )
        session.add(file)
        session.add(
            models.Thread(
                id=24,
                class_id=14,
                version=2,
                thread_id="oai-thread-24",
                code_interpreter_files=[file],
                private=False,
            )
        )
        await session.commit()

    async def fake_retrieve(message_id: str, thread_id: str):
        assert thread_id == "oai-thread-24"
        return _make_v2_message(
            "msg-image",
            "file-image",
            tool_types=("code_interpreter",),
        )

    openai_client = _make_openai_client(retrieve=fake_retrieve)
    _patch_openai_client(monkeypatch, 14, openai_client)

    response = api.delete(
        "/api/v1/class/14/thread/24/message/msg-image/file/file-image",
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )

    assert response.status_code == 404
    openai_client.files.delete.assert_not_awaited()


@with_user(123)
@with_authz(grants=[("user:123", "can_participate", "thread:25")])
async def test_delete_thread_file_v2_other_users_upload_returns_403(
    api, db, valid_user_token, monkeypatch
):
    async with db.async_session() as session:
        session.add(models.User(id=999, email="other@example.com"))
        session.add(models.Class(id=15, name="Class 15"))
        file = models.File(
            id=82,
            file_id="file-other-user",
            name="report.csv",
            content_type="text/csv",
            class_id=15,
            private=True,
            uploader_id=999,
        )
        session.add(file)
        session.add(
            models.Thread(
                id=25,
                class_id=15,
                version=2,
                thread_id="oai-thread-25",
                code_interpreter_files=[file],
                private=False,
            )
        )
        await session.commit()

    async def fake_retrieve(message_id: str, thread_id: str):
        assert thread_id == "oai-thread-25"
        return _make_v2_message(
            "msg-other-user",
            "file-other-user",
            tool_types=("code_interpreter",),
        )

    openai_client = _make_openai_client(retrieve=fake_retrieve)
    _patch_openai_client(monkeypatch, 15, openai_client)

    response = api.delete(
        "/api/v1/class/15/thread/25/message/msg-other-user/file/file-other-user",
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )

    assert response.status_code == 403
    openai_client.files.delete.assert_not_awaited()


@with_user(123)
@with_authz(grants=[("user:123", "can_participate", "thread:30")])
async def test_delete_thread_file_v3_file_search_attachment_removes_message_and_thread_rows(
    api, db, valid_user_token, monkeypatch
):
    async with db.async_session() as session:
        session.add(models.Class(id=16, name="Class 16"))
        vector_store = models.VectorStore(
            id=600,
            vector_store_id="vs-thread-30",
            type=schemas.VectorStoreType.THREAD,
            class_id=16,
        )
        file = models.File(
            id=90,
            file_id="file-v3-fs",
            name="document.pdf",
            content_type="application/pdf",
            class_id=16,
            private=True,
            uploader_id=123,
        )
        vector_store.files = [file]
        session.add(vector_store)
        thread = models.Thread(
            id=30,
            class_id=16,
            version=3,
            thread_id="responses-thread-30",
            vector_store_id=vector_store.id,
            private=False,
        )
        session.add(thread)
        run = models.Run(
            id=300,
            status=schemas.RunStatus.COMPLETED,
            thread_id=thread.id,
        )
        session.add(run)
        session.add(
            models.Message(
                id=40,
                message_status=schemas.MessageStatus.COMPLETED,
                run_id=run.id,
                thread_id=thread.id,
                output_index=0,
                role=schemas.MessageRole.USER,
                file_search_attachments=[file],
                content=[],
            )
        )
        await session.commit()

    openai_client = _make_openai_client()
    _patch_openai_client(monkeypatch, 16, openai_client)

    response = api.delete(
        "/api/v1/class/16/thread/30/message/40/file/90",
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )

    assert response.status_code == 200
    openai_client.vector_stores.files.delete.assert_awaited_once_with(
        vector_store_id="vs-thread-30",
        file_id="file-v3-fs",
    )
    openai_client.files.delete.assert_awaited_once_with("file-v3-fs")

    async with db.async_session() as session:
        assert not await models.Message.contains_file_search_attachment(session, 40, 90)
        assert not await models.Thread.thread_vector_store_contains_file(
            session, 30, 90
        )
        assert await models.File.get_by_id(session, 90) is None


@with_user(123)
@with_authz(grants=[("user:123", "can_participate", "thread:31")])
async def test_delete_thread_file_v3_code_interpreter_attachment_removes_message_and_thread_rows(
    api, db, valid_user_token, monkeypatch
):
    async with db.async_session() as session:
        session.add(models.Class(id=17, name="Class 17"))
        file = models.File(
            id=91,
            file_id="file-v3-ci",
            name="script.py",
            content_type="text/x-python",
            class_id=17,
            private=True,
            uploader_id=123,
        )
        session.add(file)
        thread = models.Thread(
            id=31,
            class_id=17,
            version=3,
            thread_id="responses-thread-31",
            code_interpreter_files=[file],
            private=False,
        )
        session.add(thread)
        run = models.Run(
            id=301,
            status=schemas.RunStatus.COMPLETED,
            thread_id=thread.id,
        )
        session.add(run)
        session.add(
            models.Message(
                id=41,
                message_status=schemas.MessageStatus.COMPLETED,
                run_id=run.id,
                thread_id=thread.id,
                output_index=0,
                role=schemas.MessageRole.USER,
                code_interpreter_attachments=[file],
                content=[],
            )
        )
        await session.commit()

    openai_client = _make_openai_client()
    _patch_openai_client(monkeypatch, 17, openai_client)

    response = api.delete(
        "/api/v1/class/17/thread/31/message/41/file/91",
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )

    assert response.status_code == 200
    openai_client.vector_stores.files.delete.assert_not_awaited()
    openai_client.files.delete.assert_awaited_once_with("file-v3-ci")

    async with db.async_session() as session:
        assert not await models.Message.contains_code_interpreter_attachment(
            session, 41, 91
        )
        assert not await models.Thread.thread_code_interpreter_contains_file(
            session, 31, 91
        )
        assert await models.File.get_by_id(session, 91) is None


@with_user(123)
@with_authz(grants=[("user:123", "can_participate", "thread:32")])
async def test_delete_thread_file_v3_second_delete_attempt_returns_404(
    api, db, valid_user_token, monkeypatch
):
    async with db.async_session() as session:
        session.add(models.Class(id=18, name="Class 18"))
        file = models.File(
            id=92,
            file_id="file-v3-repeat",
            name="document.pdf",
            content_type="application/pdf",
            class_id=18,
            private=True,
            uploader_id=123,
        )
        session.add(file)
        thread = models.Thread(
            id=32,
            class_id=18,
            version=3,
            thread_id="responses-thread-32",
            code_interpreter_files=[file],
            private=False,
        )
        session.add(thread)
        run = models.Run(
            id=302,
            status=schemas.RunStatus.COMPLETED,
            thread_id=thread.id,
        )
        session.add(run)
        session.add(
            models.Message(
                id=42,
                message_status=schemas.MessageStatus.COMPLETED,
                run_id=run.id,
                thread_id=thread.id,
                output_index=0,
                role=schemas.MessageRole.USER,
                code_interpreter_attachments=[file],
                content=[],
            )
        )
        await session.commit()

    openai_client = _make_openai_client()
    _patch_openai_client(monkeypatch, 18, openai_client)

    first_response = api.delete(
        "/api/v1/class/18/thread/32/message/42/file/92",
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )
    second_response = api.delete(
        "/api/v1/class/18/thread/32/message/42/file/92",
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )

    assert first_response.status_code == 200
    assert second_response.status_code == 404


@with_user(123)
@with_authz(grants=[("user:123", "can_participate", "thread:33")])
async def test_delete_thread_file_v3_shared_file_keeps_underlying_row_when_still_referenced(
    api, db, valid_user_token, monkeypatch
):
    async with db.async_session() as session:
        session.add(models.Class(id=19, name="Class 19"))
        vector_store = models.VectorStore(
            id=601,
            vector_store_id="vs-thread-33",
            type=schemas.VectorStoreType.THREAD,
            class_id=19,
        )
        file = models.File(
            id=93,
            file_id="file-shared",
            name="shared.pdf",
            content_type="application/pdf",
            class_id=19,
            private=True,
            uploader_id=123,
        )
        vector_store.files = [file]
        session.add(vector_store)

        thread = models.Thread(
            id=33,
            class_id=19,
            version=3,
            thread_id="responses-thread-33",
            vector_store_id=vector_store.id,
            private=False,
        )
        other_thread = models.Thread(
            id=34,
            class_id=19,
            version=3,
            thread_id="responses-thread-34",
            code_interpreter_files=[file],
            private=False,
        )
        session.add(thread)
        session.add(other_thread)

        run = models.Run(
            id=303,
            status=schemas.RunStatus.COMPLETED,
            thread_id=thread.id,
        )
        other_run = models.Run(
            id=304,
            status=schemas.RunStatus.COMPLETED,
            thread_id=other_thread.id,
        )
        session.add(run)
        session.add(other_run)

        session.add(
            models.Message(
                id=43,
                message_status=schemas.MessageStatus.COMPLETED,
                run_id=run.id,
                thread_id=thread.id,
                output_index=0,
                role=schemas.MessageRole.USER,
                file_search_attachments=[file],
                content=[],
            )
        )
        session.add(
            models.Message(
                id=44,
                message_status=schemas.MessageStatus.COMPLETED,
                run_id=other_run.id,
                thread_id=other_thread.id,
                output_index=0,
                role=schemas.MessageRole.USER,
                code_interpreter_attachments=[file],
                content=[],
            )
        )
        await session.commit()

    openai_client = _make_openai_client()
    _patch_openai_client(monkeypatch, 19, openai_client)

    response = api.delete(
        "/api/v1/class/19/thread/33/message/43/file/93",
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )

    assert response.status_code == 200
    openai_client.vector_stores.files.delete.assert_awaited_once_with(
        vector_store_id="vs-thread-33",
        file_id="file-shared",
    )
    openai_client.files.delete.assert_not_awaited()

    async with db.async_session() as session:
        assert not await models.Message.contains_file_search_attachment(session, 43, 93)
        assert not await models.Thread.thread_vector_store_contains_file(
            session, 33, 93
        )
        assert await models.Thread.thread_code_interpreter_contains_file(
            session, 34, 93
        )
        assert await models.File.get_by_id(session, 93) is not None


@with_user(123)
@with_authz(grants=[("user:123", "can_participate", "thread:35")])
async def test_delete_thread_file_v3_same_thread_file_search_reference_keeps_thread_vector_store_membership(
    api, db, valid_user_token, monkeypatch
):
    async with db.async_session() as session:
        session.add(models.Class(id=20, name="Class 20"))
        vector_store = models.VectorStore(
            id=602,
            vector_store_id="vs-thread-35",
            type=schemas.VectorStoreType.THREAD,
            class_id=20,
        )
        file = models.File(
            id=94,
            file_id="file-same-thread-fs",
            name="shared.pdf",
            content_type="application/pdf",
            class_id=20,
            private=True,
            uploader_id=123,
        )
        vector_store.files = [file]
        session.add(vector_store)

        thread = models.Thread(
            id=35,
            class_id=20,
            version=3,
            thread_id="responses-thread-35",
            vector_store_id=vector_store.id,
            private=False,
        )
        session.add(thread)

        run = models.Run(
            id=305,
            status=schemas.RunStatus.COMPLETED,
            thread_id=thread.id,
        )
        other_run = models.Run(
            id=306,
            status=schemas.RunStatus.COMPLETED,
            thread_id=thread.id,
        )
        session.add(run)
        session.add(other_run)

        session.add(
            models.Message(
                id=45,
                message_status=schemas.MessageStatus.COMPLETED,
                run_id=run.id,
                thread_id=thread.id,
                output_index=0,
                role=schemas.MessageRole.USER,
                file_search_attachments=[file],
                content=[],
            )
        )
        session.add(
            models.Message(
                id=46,
                message_status=schemas.MessageStatus.COMPLETED,
                run_id=other_run.id,
                thread_id=thread.id,
                output_index=1,
                role=schemas.MessageRole.USER,
                file_search_attachments=[file],
                content=[],
            )
        )
        await session.commit()

    openai_client = _make_openai_client()
    _patch_openai_client(monkeypatch, 20, openai_client)

    response = api.delete(
        "/api/v1/class/20/thread/35/message/45/file/94",
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )

    assert response.status_code == 200
    openai_client.vector_stores.files.delete.assert_not_awaited()
    openai_client.files.delete.assert_not_awaited()

    async with db.async_session() as session:
        assert not await models.Message.contains_file_search_attachment(session, 45, 94)
        assert await models.Message.contains_file_search_attachment(session, 46, 94)
        assert await models.Thread.thread_vector_store_contains_file(session, 35, 94)
        assert await models.File.get_by_id(session, 94) is not None


@with_user(123)
@with_authz(grants=[("user:123", "can_participate", "thread:36")])
async def test_delete_thread_file_v3_same_thread_code_interpreter_reference_keeps_thread_membership(
    api, db, valid_user_token, monkeypatch
):
    async with db.async_session() as session:
        session.add(models.Class(id=21, name="Class 21"))
        file = models.File(
            id=95,
            file_id="file-same-thread-ci",
            name="shared.py",
            content_type="text/x-python",
            class_id=21,
            private=True,
            uploader_id=123,
        )
        session.add(file)
        thread = models.Thread(
            id=36,
            class_id=21,
            version=3,
            thread_id="responses-thread-36",
            code_interpreter_files=[file],
            private=False,
        )
        session.add(thread)

        run = models.Run(
            id=307,
            status=schemas.RunStatus.COMPLETED,
            thread_id=thread.id,
        )
        other_run = models.Run(
            id=308,
            status=schemas.RunStatus.COMPLETED,
            thread_id=thread.id,
        )
        session.add(run)
        session.add(other_run)

        session.add(
            models.Message(
                id=47,
                message_status=schemas.MessageStatus.COMPLETED,
                run_id=run.id,
                thread_id=thread.id,
                output_index=0,
                role=schemas.MessageRole.USER,
                code_interpreter_attachments=[file],
                content=[],
            )
        )
        session.add(
            models.Message(
                id=48,
                message_status=schemas.MessageStatus.COMPLETED,
                run_id=other_run.id,
                thread_id=thread.id,
                output_index=1,
                role=schemas.MessageRole.USER,
                code_interpreter_attachments=[file],
                content=[],
            )
        )
        await session.commit()

    openai_client = _make_openai_client()
    _patch_openai_client(monkeypatch, 21, openai_client)

    response = api.delete(
        "/api/v1/class/21/thread/36/message/47/file/95",
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )

    assert response.status_code == 200
    openai_client.vector_stores.files.delete.assert_not_awaited()
    openai_client.files.delete.assert_not_awaited()

    async with db.async_session() as session:
        assert not await models.Message.contains_code_interpreter_attachment(
            session, 47, 95
        )
        assert await models.Message.contains_code_interpreter_attachment(
            session, 48, 95
        )
        assert await models.Thread.thread_code_interpreter_contains_file(
            session, 36, 95
        )
        assert await models.File.get_by_id(session, 95) is not None
