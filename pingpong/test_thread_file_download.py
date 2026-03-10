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
    include_attachment: bool = True,
    annotation_type: str = "file_path",
):
    if annotation_type == "file_path":
        annotations = [
            SimpleNamespace(
                type="file_path",
                file_path=SimpleNamespace(file_id=file_id),
            )
        ]
    elif annotation_type == "file_citation":
        annotations = [
            SimpleNamespace(
                type="file_citation",
                file_citation=SimpleNamespace(file_id=file_id),
            )
        ]
    else:
        annotations = []

    return SimpleNamespace(
        id=message_id,
        attachments=[SimpleNamespace(file_id=file_id)] if include_attachment else [],
        content=[
            SimpleNamespace(
                type="text",
                text=SimpleNamespace(annotations=annotations),
            )
        ],
    )


@with_user(123)
@with_authz(grants=[("user:123", "can_view", "thread:20")])
async def test_download_file_v2_requires_requested_message_reference(
    api, db, valid_user_token, monkeypatch
):
    async with db.async_session() as session:
        session.add(models.Class(id=10, name="Class 10"))
        session.add(
            models.Thread(
                id=20,
                class_id=10,
                version=2,
                thread_id="oai-thread-20",
                private=False,
            )
        )
        await session.commit()

    target_message = _make_v2_message("msg_target", "file-allowed")
    retrieve_content = AsyncMock(
        return_value=SimpleNamespace(
            status_code=200,
            headers={
                "content-type": "text/csv",
                "content-disposition": "attachment; filename=random_emails.csv",
            },
            content=b"email\nuser@example.com\n",
        )
    )

    async def fake_retrieve(message_id: str, thread_id: str):
        assert message_id == "msg_target"
        assert thread_id == "oai-thread-20"
        return target_message

    openai_client = SimpleNamespace(
        beta=SimpleNamespace(
            threads=SimpleNamespace(
                messages=SimpleNamespace(
                    retrieve=AsyncMock(side_effect=fake_retrieve),
                )
            )
        ),
        files=SimpleNamespace(
            with_raw_response=SimpleNamespace(retrieve_content=retrieve_content)
        ),
    )

    async def fake_get_openai_client_by_class_id(_session, class_id: int):
        assert class_id == 10
        return openai_client

    monkeypatch.setattr(
        server_module,
        "get_openai_client_by_class_id",
        fake_get_openai_client_by_class_id,
    )

    response = api.get(
        "/api/v1/class/10/thread/20/message/msg_target/file/file-allowed",
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )

    assert response.status_code == 200
    assert response.content == b"email\nuser@example.com\n"
    assert (
        response.headers["content-disposition"]
        == "attachment; filename=random_emails.csv"
    )


@with_user(123)
@with_authz(grants=[("user:123", "can_view", "thread:21")])
async def test_download_file_v2_rejects_file_from_different_message(
    api, db, valid_user_token, monkeypatch
):
    async with db.async_session() as session:
        session.add(models.Class(id=11, name="Class 11"))
        session.add(
            models.Thread(
                id=21,
                class_id=11,
                version=2,
                thread_id="oai-thread-21",
                private=False,
            )
        )
        await session.commit()

    target_message = _make_v2_message("msg_target", "file-different")
    retrieve_content = AsyncMock()

    async def fake_retrieve(message_id: str, thread_id: str):
        assert message_id == "msg_target"
        assert thread_id == "oai-thread-21"
        return target_message

    openai_client = SimpleNamespace(
        beta=SimpleNamespace(
            threads=SimpleNamespace(
                messages=SimpleNamespace(
                    retrieve=AsyncMock(side_effect=fake_retrieve),
                )
            )
        ),
        files=SimpleNamespace(
            with_raw_response=SimpleNamespace(retrieve_content=retrieve_content)
        ),
    )

    async def fake_get_openai_client_by_class_id(_session, class_id: int):
        assert class_id == 11
        return openai_client

    monkeypatch.setattr(
        server_module,
        "get_openai_client_by_class_id",
        fake_get_openai_client_by_class_id,
    )

    response = api.get(
        "/api/v1/class/11/thread/21/message/msg_target/file/file-allowed",
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )

    assert response.status_code == 404
    retrieve_content.assert_not_awaited()


@with_user(123)
@with_authz(grants=[("user:123", "can_view", "thread:22")])
async def test_download_file_v2_rejects_attachment_without_file_path(
    api, db, valid_user_token, monkeypatch
):
    async with db.async_session() as session:
        session.add(models.Class(id=15, name="Class 15"))
        session.add(
            models.Thread(
                id=22,
                class_id=15,
                version=2,
                thread_id="oai-thread-22",
                private=False,
            )
        )
        await session.commit()

    target_message = _make_v2_message(
        "msg_target",
        "file-allowed",
        annotation_type="none",
    )
    retrieve_content = AsyncMock()

    async def fake_retrieve(message_id: str, thread_id: str):
        assert message_id == "msg_target"
        assert thread_id == "oai-thread-22"
        return target_message

    openai_client = SimpleNamespace(
        beta=SimpleNamespace(
            threads=SimpleNamespace(
                messages=SimpleNamespace(
                    retrieve=AsyncMock(side_effect=fake_retrieve),
                )
            )
        ),
        files=SimpleNamespace(
            with_raw_response=SimpleNamespace(retrieve_content=retrieve_content)
        ),
    )

    async def fake_get_openai_client_by_class_id(_session, class_id: int):
        assert class_id == 15
        return openai_client

    monkeypatch.setattr(
        server_module,
        "get_openai_client_by_class_id",
        fake_get_openai_client_by_class_id,
    )

    response = api.get(
        "/api/v1/class/15/thread/22/message/msg_target/file/file-allowed",
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )

    assert response.status_code == 404
    retrieve_content.assert_not_awaited()


@with_user(123)
@with_authz(grants=[("user:123", "can_view", "thread:23")])
async def test_download_file_v2_rejects_file_citation_without_file_path(
    api, db, valid_user_token, monkeypatch
):
    async with db.async_session() as session:
        session.add(models.Class(id=16, name="Class 16"))
        session.add(
            models.Thread(
                id=23,
                class_id=16,
                version=2,
                thread_id="oai-thread-23",
                private=False,
            )
        )
        await session.commit()

    target_message = _make_v2_message(
        "msg_target",
        "file-allowed",
        include_attachment=False,
        annotation_type="file_citation",
    )
    retrieve_content = AsyncMock()

    async def fake_retrieve(message_id: str, thread_id: str):
        assert message_id == "msg_target"
        assert thread_id == "oai-thread-23"
        return target_message

    openai_client = SimpleNamespace(
        beta=SimpleNamespace(
            threads=SimpleNamespace(
                messages=SimpleNamespace(
                    retrieve=AsyncMock(side_effect=fake_retrieve),
                )
            )
        ),
        files=SimpleNamespace(
            with_raw_response=SimpleNamespace(retrieve_content=retrieve_content)
        ),
    )

    async def fake_get_openai_client_by_class_id(_session, class_id: int):
        assert class_id == 16
        return openai_client

    monkeypatch.setattr(
        server_module,
        "get_openai_client_by_class_id",
        fake_get_openai_client_by_class_id,
    )

    response = api.get(
        "/api/v1/class/16/thread/23/message/msg_target/file/file-allowed",
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )

    assert response.status_code == 404
    retrieve_content.assert_not_awaited()


@with_user(123)
@with_authz(grants=[("user:123", "can_view", "thread:30")])
async def test_download_file_v3_requires_requested_message_reference(
    api, db, valid_user_token, monkeypatch
):
    async with db.async_session() as session:
        session.add(models.Class(id=12, name="Class 12"))
        thread = models.Thread(
            id=30,
            class_id=12,
            version=3,
            thread_id="responses-thread-30",
            private=False,
        )
        session.add(thread)
        run = models.Run(
            id=300,
            status=schemas.RunStatus.COMPLETED,
            thread_id=thread.id,
        )
        session.add(run)
        s3_file = models.S3File(id=700, key="generated/report.csv")
        session.add(s3_file)
        file = models.File(
            id=77,
            file_id="file-generated-77",
            name="report.csv",
            content_type="text/csv",
            class_id=12,
            s3_file=s3_file,
        )
        session.add(file)
        message = models.Message(
            id=40,
            message_status=schemas.MessageStatus.COMPLETED,
            run_id=run.id,
            thread_id=thread.id,
            output_index=0,
            role=schemas.MessageRole.ASSISTANT,
            content=[
                models.MessagePart(
                    type=schemas.MessagePartType.OUTPUT_TEXT,
                    part_index=0,
                    text="Generated report",
                    annotations=[
                        models.Annotation(
                            type=schemas.AnnotationType.CONTAINER_FILE_CITATION,
                            annotation_index=0,
                            file_object_id=file.id,
                            filename=file.name,
                        )
                    ],
                )
            ],
        )
        session.add(message)
        await session.commit()

    async def fake_get_openai_client_by_class_id(_session, class_id: int):
        assert class_id == 12
        return SimpleNamespace()

    monkeypatch.setattr(
        server_module,
        "get_openai_client_by_class_id",
        fake_get_openai_client_by_class_id,
    )
    monkeypatch.setattr(
        server_module.config,
        "file_store",
        SimpleNamespace(
            store=SimpleNamespace(get=lambda name: iter([b"generated report"]))
        ),
    )

    response = api.get(
        "/api/v1/class/12/thread/30/message/40/file/77",
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )

    assert response.status_code == 200
    assert response.content == b"generated report"
    assert response.headers["content-disposition"] == "attachment; filename=report.csv"


@with_user(123)
@with_authz(grants=[("user:123", "can_view", "thread:33")])
async def test_download_file_v3_allows_vision_annotation_by_object_id(
    api, db, valid_user_token, monkeypatch
):
    async with db.async_session() as session:
        session.add(models.Class(id=17, name="Class 17"))
        thread = models.Thread(
            id=33,
            class_id=17,
            version=3,
            thread_id="responses-thread-33",
            private=False,
        )
        session.add(thread)
        run = models.Run(
            id=303,
            status=schemas.RunStatus.COMPLETED,
            thread_id=thread.id,
        )
        session.add(run)
        s3_file = models.S3File(id=702, key="generated/chart.png")
        session.add(s3_file)
        file = models.File(
            id=79,
            file_id="file-generated-79",
            name="chart.png",
            content_type="image/png",
            class_id=17,
            s3_file=s3_file,
        )
        session.add(file)
        session.add(
            models.Message(
                id=43,
                message_status=schemas.MessageStatus.COMPLETED,
                run_id=run.id,
                thread_id=thread.id,
                output_index=0,
                role=schemas.MessageRole.ASSISTANT,
                content=[
                    models.MessagePart(
                        type=schemas.MessagePartType.OUTPUT_TEXT,
                        part_index=0,
                        text="Generated image",
                        annotations=[
                            models.Annotation(
                                type=schemas.AnnotationType.CONTAINER_FILE_CITATION,
                                annotation_index=0,
                                vision_file_id=file.file_id,
                                vision_file_object_id=file.id,
                                filename=file.name,
                            )
                        ],
                    )
                ],
            )
        )
        await session.commit()

    async def fake_get_openai_client_by_class_id(_session, class_id: int):
        assert class_id == 17
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
        "/api/v1/class/17/thread/33/message/43/file/79",
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )

    assert response.status_code == 200
    assert response.content == b"image-bytes"
    assert response.headers["content-disposition"] == "attachment; filename=chart.png"


@with_user(123)
@with_authz(grants=[("user:123", "can_view", "thread:31")])
async def test_download_file_v3_rejects_attachment_without_direct_annotation(
    api, db, valid_user_token, monkeypatch
):
    async with db.async_session() as session:
        session.add(models.Class(id=13, name="Class 13"))
        thread = models.Thread(
            id=31,
            class_id=13,
            version=3,
            thread_id="responses-thread-31",
            private=False,
        )
        session.add(thread)
        run = models.Run(
            id=301,
            status=schemas.RunStatus.COMPLETED,
            thread_id=thread.id,
        )
        session.add(run)
        file = models.File(
            id=78,
            file_id="file-generated-78",
            name="requested.csv",
            content_type="text/csv",
            class_id=13,
            s3_file=models.S3File(id=701, key="generated/requested.csv"),
        )
        session.add(file)
        session.add(
            models.Message(
                id=41,
                message_status=schemas.MessageStatus.COMPLETED,
                run_id=run.id,
                thread_id=thread.id,
                output_index=0,
                role=schemas.MessageRole.ASSISTANT,
                code_interpreter_attachments=[file],
                content=[
                    models.MessagePart(
                        type=schemas.MessagePartType.OUTPUT_TEXT,
                        part_index=0,
                        text="Attached but not annotated",
                        annotations=[],
                    )
                ],
            )
        )
        await session.commit()

    async def fake_get_openai_client_by_class_id(_session, class_id: int):
        assert class_id == 13
        return SimpleNamespace()

    monkeypatch.setattr(
        server_module,
        "get_openai_client_by_class_id",
        fake_get_openai_client_by_class_id,
    )
    get_file = AsyncMock()
    monkeypatch.setattr(
        server_module.config,
        "file_store",
        SimpleNamespace(store=SimpleNamespace(get=get_file)),
    )

    response = api.get(
        "/api/v1/class/13/thread/31/message/41/file/78",
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )

    assert response.status_code == 404
    get_file.assert_not_called()


@with_user(123)
@with_authz(grants=[("user:123", "can_view", "thread:32")])
async def test_download_file_v3_rejects_annotation_with_file_id_only(
    api, db, valid_user_token, monkeypatch
):
    async with db.async_session() as session:
        session.add(models.Class(id=14, name="Class 14"))
        thread = models.Thread(
            id=32,
            class_id=14,
            version=3,
            thread_id="responses-thread-32",
            private=False,
        )
        session.add(thread)
        run = models.Run(
            id=302,
            status=schemas.RunStatus.COMPLETED,
            thread_id=thread.id,
        )
        session.add(run)
        file = models.File(
            id=78,
            file_id="file-generated-78",
            name="requested.csv",
            content_type="text/csv",
            class_id=14,
            s3_file=models.S3File(id=701, key="generated/requested.csv"),
        )
        session.add(file)
        session.add(
            models.Message(
                id=42,
                message_status=schemas.MessageStatus.COMPLETED,
                run_id=run.id,
                thread_id=thread.id,
                output_index=0,
                role=schemas.MessageRole.ASSISTANT,
                content=[
                    models.MessagePart(
                        type=schemas.MessagePartType.OUTPUT_TEXT,
                        part_index=0,
                        text="Annotated with file_id only",
                        annotations=[
                            models.Annotation(
                                type=schemas.AnnotationType.CONTAINER_FILE_CITATION,
                                annotation_index=0,
                                file_id=file.file_id,
                                filename=file.name,
                            )
                        ],
                    )
                ],
            )
        )
        await session.commit()

    async def fake_get_openai_client_by_class_id(_session, class_id: int):
        assert class_id == 14
        return SimpleNamespace()

    monkeypatch.setattr(
        server_module,
        "get_openai_client_by_class_id",
        fake_get_openai_client_by_class_id,
    )
    get_file = AsyncMock()
    monkeypatch.setattr(
        server_module.config,
        "file_store",
        SimpleNamespace(store=SimpleNamespace(get=get_file)),
    )

    response = api.get(
        "/api/v1/class/14/thread/32/message/42/file/78",
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )

    assert response.status_code == 404
    get_file.assert_not_called()


@with_user(123)
@with_authz(grants=[("user:123", "can_view", "thread:33")])
async def test_download_file_v3_rejects_file_from_different_message(
    api, db, valid_user_token, monkeypatch
):
    async with db.async_session() as session:
        session.add(models.Class(id=17, name="Class 17"))
        thread = models.Thread(
            id=33,
            class_id=17,
            version=3,
            thread_id="responses-thread-33",
            private=False,
        )
        session.add(thread)
        run = models.Run(
            id=303,
            status=schemas.RunStatus.COMPLETED,
            thread_id=thread.id,
        )
        session.add(run)

        requested_file = models.File(
            id=78,
            file_id="file-generated-78",
            name="requested.csv",
            content_type="text/csv",
            class_id=17,
            s3_file=models.S3File(id=701, key="generated/requested.csv"),
        )
        other_file = models.File(
            id=79,
            file_id="file-generated-79",
            name="other.csv",
            content_type="text/csv",
            class_id=17,
            s3_file=models.S3File(id=702, key="generated/other.csv"),
        )
        session.add(requested_file)
        session.add(other_file)

        session.add(
            models.Message(
                id=41,
                message_status=schemas.MessageStatus.COMPLETED,
                run_id=run.id,
                thread_id=thread.id,
                output_index=0,
                role=schemas.MessageRole.ASSISTANT,
                content=[
                    models.MessagePart(
                        type=schemas.MessagePartType.OUTPUT_TEXT,
                        part_index=0,
                        text="Requested file lives here",
                        annotations=[
                            models.Annotation(
                                type=schemas.AnnotationType.CONTAINER_FILE_CITATION,
                                annotation_index=0,
                                file_object_id=requested_file.id,
                                filename=requested_file.name,
                            )
                        ],
                    )
                ],
            )
        )
        session.add(
            models.Message(
                id=42,
                message_status=schemas.MessageStatus.COMPLETED,
                run_id=run.id,
                thread_id=thread.id,
                output_index=1,
                role=schemas.MessageRole.ASSISTANT,
                content=[
                    models.MessagePart(
                        type=schemas.MessagePartType.OUTPUT_TEXT,
                        part_index=0,
                        text="Different file lives here",
                        annotations=[
                            models.Annotation(
                                type=schemas.AnnotationType.CONTAINER_FILE_CITATION,
                                annotation_index=0,
                                file_object_id=other_file.id,
                                filename=other_file.name,
                            )
                        ],
                    )
                ],
            )
        )
        await session.commit()

    async def fake_get_openai_client_by_class_id(_session, class_id: int):
        assert class_id == 17
        return SimpleNamespace()

    monkeypatch.setattr(
        server_module,
        "get_openai_client_by_class_id",
        fake_get_openai_client_by_class_id,
    )
    get_file = AsyncMock()
    monkeypatch.setattr(
        server_module.config,
        "file_store",
        SimpleNamespace(store=SimpleNamespace(get=get_file)),
    )

    response = api.get(
        "/api/v1/class/17/thread/33/message/42/file/78",
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )

    assert response.status_code == 404
    get_file.assert_not_called()
