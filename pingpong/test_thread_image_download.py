import importlib
from types import SimpleNamespace
from unittest.mock import AsyncMock

from pingpong import models
import pingpong.schemas as schemas

from .testutil import with_authz, with_user

server_module = importlib.import_module("pingpong.server")


def _make_v2_image_message(message_id: str, file_id: str, *, role: str = "user"):
    return SimpleNamespace(
        id=message_id,
        role=role,
        content=[
            SimpleNamespace(
                type="image_file",
                image_file=SimpleNamespace(file_id=file_id),
            )
        ],
    )


def _make_v2_ci_output_message(file_id: str):
    return SimpleNamespace(
        content=[
            SimpleNamespace(
                type="code_output_image_file",
                image_file=SimpleNamespace(file_id=file_id),
            )
        ]
    )


def _make_openai_client(
    *,
    message_retrieve: AsyncMock | None = None,
    retrieve_content: AsyncMock | None = None,
):
    return SimpleNamespace(
        beta=SimpleNamespace(
            threads=SimpleNamespace(
                messages=SimpleNamespace(
                    retrieve=message_retrieve or AsyncMock(),
                )
            )
        ),
        files=SimpleNamespace(
            with_raw_response=SimpleNamespace(
                retrieve_content=retrieve_content or AsyncMock(),
            )
        ),
    )


@with_user(123)
@with_authz(grants=[("user:123", "can_view", "thread:50")])
async def test_get_message_image_v2_requires_requested_message_reference(
    api, db, valid_user_token, monkeypatch
):
    async with db.async_session() as session:
        session.add(models.Class(id=50, name="Class 50"))
        session.add(
            models.Thread(
                id=50,
                class_id=50,
                version=2,
                thread_id="oai-thread-50",
                private=False,
            )
        )
        await session.commit()

    target_message = _make_v2_image_message("msg_target", "file-allowed")
    retrieve_content = AsyncMock(
        return_value=SimpleNamespace(
            status_code=200,
            headers={
                "content-type": "image/png",
                "content-disposition": "inline; filename=chart.png",
            },
            content=b"png-bytes",
        )
    )

    async def fake_retrieve(message_id: str, thread_id: str):
        assert message_id == "msg_target"
        assert thread_id == "oai-thread-50"
        return target_message

    openai_client = _make_openai_client(
        message_retrieve=AsyncMock(side_effect=fake_retrieve),
        retrieve_content=retrieve_content,
    )

    async def fake_get_openai_client_by_class_id(_session, class_id: int):
        assert class_id == 50
        return openai_client

    monkeypatch.setattr(
        server_module,
        "get_openai_client_by_class_id",
        fake_get_openai_client_by_class_id,
    )

    response = api.get(
        "/api/v1/class/50/thread/50/message/msg_target/image/file-allowed",
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )

    assert response.status_code == 200
    assert response.content == b"png-bytes"
    assert response.headers["content-disposition"] == "inline; filename=chart.png"


@with_user(123)
@with_authz(grants=[("user:123", "can_view", "thread:51")])
async def test_get_message_image_v2_rejects_file_from_different_message(
    api, db, valid_user_token, monkeypatch
):
    async with db.async_session() as session:
        session.add(models.Class(id=51, name="Class 51"))
        session.add(
            models.Thread(
                id=51,
                class_id=51,
                version=2,
                thread_id="oai-thread-51",
                private=False,
            )
        )
        await session.commit()

    target_message = _make_v2_image_message("msg_target", "file-different")
    retrieve_content = AsyncMock()
    openai_client = _make_openai_client(
        message_retrieve=AsyncMock(return_value=target_message),
        retrieve_content=retrieve_content,
    )

    async def fake_get_openai_client_by_class_id(_session, class_id: int):
        assert class_id == 51
        return openai_client

    monkeypatch.setattr(
        server_module,
        "get_openai_client_by_class_id",
        fake_get_openai_client_by_class_id,
    )

    response = api.get(
        "/api/v1/class/51/thread/51/message/msg_target/image/file-allowed",
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )

    assert response.status_code == 404
    retrieve_content.assert_not_awaited()


@with_user(123)
@with_authz(grants=[("user:123", "can_view", "thread:52")])
async def test_get_message_image_v2_rejects_assistant_message_images(
    api, db, valid_user_token, monkeypatch
):
    async with db.async_session() as session:
        session.add(models.Class(id=52, name="Class 52"))
        session.add(
            models.Thread(
                id=52,
                class_id=52,
                version=2,
                thread_id="oai-thread-52",
                private=False,
            )
        )
        await session.commit()

    target_message = _make_v2_image_message(
        "msg_target", "file-allowed", role="assistant"
    )
    retrieve_content = AsyncMock()
    openai_client = _make_openai_client(
        message_retrieve=AsyncMock(return_value=target_message),
        retrieve_content=retrieve_content,
    )

    async def fake_get_openai_client_by_class_id(_session, class_id: int):
        assert class_id == 52
        return openai_client

    monkeypatch.setattr(
        server_module,
        "get_openai_client_by_class_id",
        fake_get_openai_client_by_class_id,
    )

    response = api.get(
        "/api/v1/class/52/thread/52/message/msg_target/image/file-allowed",
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )

    assert response.status_code == 404
    retrieve_content.assert_not_awaited()


@with_user(123)
@with_authz(grants=[("user:123", "can_view", "thread:53")])
async def test_get_ci_call_image_v2_requires_requested_ci_call_reference(
    api, db, valid_user_token, monkeypatch
):
    async with db.async_session() as session:
        session.add(models.Class(id=53, name="Class 53"))
        session.add(
            models.Thread(
                id=53,
                class_id=53,
                version=2,
                thread_id="oai-thread-53",
                private=False,
            )
        )
        session.add(
            models.CodeInterpreterCall(
                id=91,
                version=2,
                run_id="run-53",
                step_id="step-53",
                thread_id=53,
                created_at=123,
            )
        )
        await session.commit()

    retrieve_content = AsyncMock(
        return_value=SimpleNamespace(
            status_code=200,
            headers={"content-type": "image/png"},
            content=b"ci-image",
        )
    )
    openai_client = _make_openai_client(retrieve_content=retrieve_content)

    async def fake_get_openai_client_by_class_id(_session, class_id: int):
        assert class_id == 53
        return openai_client

    async def fake_get_ci_messages_from_step(
        cli, thread_id: str, run_id: str, step_id: str
    ):
        assert cli is openai_client
        assert thread_id == "oai-thread-53"
        assert run_id == "run-53"
        assert step_id == "step-53"
        return [_make_v2_ci_output_message("file-allowed")]

    monkeypatch.setattr(
        server_module,
        "get_openai_client_by_class_id",
        fake_get_openai_client_by_class_id,
    )
    monkeypatch.setattr(
        server_module, "get_ci_messages_from_step", fake_get_ci_messages_from_step
    )

    response = api.get(
        "/api/v1/class/53/thread/53/ci_call/91/image/file-allowed",
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )

    assert response.status_code == 200
    assert response.content == b"ci-image"


@with_user(123)
@with_authz(grants=[("user:123", "can_view", "thread:54")])
async def test_get_ci_call_image_v2_rejects_image_from_different_ci_call(
    api, db, valid_user_token, monkeypatch
):
    async with db.async_session() as session:
        session.add(models.Class(id=54, name="Class 54"))
        session.add(
            models.Thread(
                id=54,
                class_id=54,
                version=2,
                thread_id="oai-thread-54",
                private=False,
            )
        )
        session.add(
            models.CodeInterpreterCall(
                id=92,
                version=2,
                run_id="run-54",
                step_id="step-54",
                thread_id=54,
                created_at=123,
            )
        )
        await session.commit()

    retrieve_content = AsyncMock()
    openai_client = _make_openai_client(retrieve_content=retrieve_content)

    async def fake_get_openai_client_by_class_id(_session, class_id: int):
        assert class_id == 54
        return openai_client

    async def fake_get_ci_messages_from_step(
        _cli, _thread_id: str, _run_id: str, _step_id: str
    ):
        return [_make_v2_ci_output_message("file-different")]

    monkeypatch.setattr(
        server_module,
        "get_openai_client_by_class_id",
        fake_get_openai_client_by_class_id,
    )
    monkeypatch.setattr(
        server_module, "get_ci_messages_from_step", fake_get_ci_messages_from_step
    )

    response = api.get(
        "/api/v1/class/54/thread/54/ci_call/92/image/file-allowed",
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )

    assert response.status_code == 404
    retrieve_content.assert_not_awaited()


@with_user(123)
@with_authz(grants=[("user:123", "can_view", "thread:55")])
async def test_get_ci_messages_v2_includes_ci_call_id_metadata(
    api, db, valid_user_token, monkeypatch
):
    async with db.async_session() as session:
        session.add(models.Class(id=55, name="Class 55"))
        session.add(
            models.Thread(
                id=55,
                class_id=55,
                version=2,
                thread_id="oai-thread-55",
                private=False,
            )
        )
        session.add(
            models.CodeInterpreterCall(
                id=93,
                version=2,
                run_id="run-55",
                step_id="step-55",
                thread_id=55,
                created_at=123,
            )
        )
        await session.commit()

    openai_client = _make_openai_client()

    async def fake_get_openai_client_by_class_id(_session, class_id: int):
        assert class_id == 55
        return openai_client

    async def fake_get_ci_messages_from_step(
        _cli, _thread_id: str, _run_id: str, _step_id: str
    ):
        return [
            schemas.CodeInterpreterMessage.model_validate(
                {
                    "id": "tool-call-55",
                    "assistant_id": "assistant-55",
                    "created_at": 123.0,
                    "content": [
                        {
                            "image_file": {"file_id": "file-allowed"},
                            "type": "code_output_image_file",
                        }
                    ],
                    "metadata": {},
                    "object": "thread.message",
                    "role": "assistant",
                    "run_id": "run-55",
                    "thread_id": "oai-thread-55",
                    "message_type": "code_interpreter_call",
                }
            )
        ]

    monkeypatch.setattr(
        server_module,
        "get_openai_client_by_class_id",
        fake_get_openai_client_by_class_id,
    )
    monkeypatch.setattr(
        server_module, "get_ci_messages_from_step", fake_get_ci_messages_from_step
    )

    response = api.get(
        "/api/v1/class/55/thread/55/ci_messages?run_id=run-55&step_id=step-55",
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )

    assert response.status_code == 200
    assert response.json()["ci_messages"][0]["metadata"]["ci_call_id"] == "93"


@with_user(123)
@with_authz(grants=[("user:123", "can_view", "thread:57")])
async def test_get_ci_messages_rejects_thread_from_different_class(
    api, db, valid_user_token, monkeypatch
):
    async with db.async_session() as session:
        session.add(models.Class(id=57, name="Class 57"))
        session.add(models.Class(id=58, name="Class 58"))
        session.add(
            models.Thread(
                id=57,
                class_id=58,
                version=2,
                thread_id="oai-thread-57",
                private=False,
            )
        )
        await session.commit()

    openai_client = _make_openai_client()
    get_ci_messages_from_step = AsyncMock()

    async def fake_get_openai_client_by_class_id(_session, class_id: int):
        assert class_id == 57
        return openai_client

    monkeypatch.setattr(
        server_module,
        "get_openai_client_by_class_id",
        fake_get_openai_client_by_class_id,
    )
    monkeypatch.setattr(
        server_module, "get_ci_messages_from_step", get_ci_messages_from_step
    )

    response = api.get(
        "/api/v1/class/57/thread/57/ci_messages?run_id=run-57&step_id=step-57",
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )

    assert response.status_code == 404
    get_ci_messages_from_step.assert_not_awaited()


@with_user(123)
@with_authz(grants=[("user:123", "can_view", "thread:56")])
async def test_get_image_v2_generic_route_is_not_available(
    api, db, valid_user_token, monkeypatch
):
    async with db.async_session() as session:
        session.add(models.Class(id=56, name="Class 56"))
        session.add(
            models.Thread(
                id=56,
                class_id=56,
                version=2,
                thread_id="oai-thread-56",
                private=False,
            )
        )
        await session.commit()

    retrieve_content = AsyncMock()
    openai_client = _make_openai_client(retrieve_content=retrieve_content)

    async def fake_get_openai_client_by_class_id(_session, class_id: int):
        assert class_id == 56
        return openai_client

    monkeypatch.setattr(
        server_module,
        "get_openai_client_by_class_id",
        fake_get_openai_client_by_class_id,
    )

    response = api.get(
        "/api/v1/class/56/thread/56/image/file-allowed",
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )

    assert response.status_code == 404
    retrieve_content.assert_not_awaited()


@with_user(123)
@with_authz(grants=[("user:123", "can_view", "thread:57")])
async def test_get_image_v3_requires_thread_image_file_membership(
    api, db, valid_user_token, monkeypatch
):
    async with db.async_session() as session:
        session.add(models.Class(id=57, name="Class 57"))
        image_file = models.File(
            id=570,
            file_id="file-image-57",
            name="chart.png",
            content_type="image/png",
            class_id=57,
            s3_file=models.S3File(id=5700, key="generated/chart.png"),
        )
        thread = models.Thread(
            id=57,
            class_id=57,
            version=3,
            thread_id="responses-thread-57",
            private=False,
            image_files=[image_file],
        )
        session.add(thread)
        await session.commit()

    async def fake_get_openai_client_by_class_id(_session, class_id: int):
        assert class_id == 57
        return SimpleNamespace()

    monkeypatch.setattr(
        server_module,
        "get_openai_client_by_class_id",
        fake_get_openai_client_by_class_id,
    )
    monkeypatch.setattr(
        server_module.config,
        "file_store",
        SimpleNamespace(store=SimpleNamespace(get=lambda name: iter([b"image-bytes"]))),
    )

    response = api.get(
        "/api/v1/class/57/thread/57/image/file-image-57",
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )

    assert response.status_code == 200
    assert response.content == b"image-bytes"
    assert response.headers["content-type"] == "image/png"
    assert response.headers["content-disposition"] == "inline; filename=chart.png"


@with_user(123)
@with_authz(grants=[("user:123", "can_view", "thread:58")])
async def test_get_image_v3_rejects_files_not_in_thread_image_files(
    api, db, valid_user_token, monkeypatch
):
    async with db.async_session() as session:
        session.add(models.Class(id=58, name="Class 58"))
        session.add(
            models.Thread(
                id=58,
                class_id=58,
                version=3,
                thread_id="responses-thread-58",
                private=False,
            )
        )
        session.add(
            models.File(
                id=580,
                file_id="file-image-58",
                name="chart.png",
                content_type="image/png",
                class_id=58,
                s3_file=models.S3File(id=5800, key="generated/chart.png"),
            )
        )
        await session.commit()

    async def fake_get_openai_client_by_class_id(_session, class_id: int):
        assert class_id == 58
        return SimpleNamespace()

    get_file = AsyncMock()
    monkeypatch.setattr(
        server_module,
        "get_openai_client_by_class_id",
        fake_get_openai_client_by_class_id,
    )
    monkeypatch.setattr(
        server_module.config,
        "file_store",
        SimpleNamespace(store=SimpleNamespace(get=get_file)),
    )

    response = api.get(
        "/api/v1/class/58/thread/58/image/file-image-58",
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )

    assert response.status_code == 404
    get_file.assert_not_called()


@with_user(123)
@with_authz(grants=[("user:123", "can_view", "thread:59")])
async def test_get_image_v3_rejects_non_image_files_even_if_associated(
    api, db, valid_user_token, monkeypatch
):
    async with db.async_session() as session:
        session.add(models.Class(id=59, name="Class 59"))
        document_file = models.File(
            id=590,
            file_id="file-document-59",
            name="notes.txt",
            content_type="text/plain",
            class_id=59,
            s3_file=models.S3File(id=5900, key="generated/notes.txt"),
        )
        thread = models.Thread(
            id=59,
            class_id=59,
            version=3,
            thread_id="responses-thread-59",
            private=False,
            image_files=[document_file],
        )
        session.add(thread)
        await session.commit()

    async def fake_get_openai_client_by_class_id(_session, class_id: int):
        assert class_id == 59
        return SimpleNamespace()

    get_file = AsyncMock()
    monkeypatch.setattr(
        server_module,
        "get_openai_client_by_class_id",
        fake_get_openai_client_by_class_id,
    )
    monkeypatch.setattr(
        server_module.config,
        "file_store",
        SimpleNamespace(store=SimpleNamespace(get=get_file)),
    )

    response = api.get(
        "/api/v1/class/59/thread/59/image/file-document-59",
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )

    assert response.status_code == 404
    get_file.assert_not_called()
