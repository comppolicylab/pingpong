from types import SimpleNamespace

import pytest
from sqlalchemy import select

from pingpong import models, schemas
from pingpong.migrations import m16_migrate_message_parts as migration

pytestmark = pytest.mark.asyncio


MIGRATION_METADATA = {
    "assistants_to_responses_api_thread_migration": {"message": "complete"}
}


def _text_content(text: str, annotations=None):
    return SimpleNamespace(
        type="text",
        text=SimpleNamespace(value=text, annotations=annotations or []),
    )


def _image_content(file_id: str):
    return SimpleNamespace(
        type="image_file",
        image_file=SimpleNamespace(file_id=file_id),
    )


def _file_citation(file_id: str):
    return SimpleNamespace(
        type="file_citation",
        start_index=0,
        end_index=4,
        text="file",
        file_citation=SimpleNamespace(file_id=file_id),
    )


def _file_path(file_id: str):
    return SimpleNamespace(
        type="file_path",
        start_index=5,
        end_index=9,
        text="path",
        file_path=SimpleNamespace(file_id=file_id),
    )


def _openai_message(message_id: str, content):
    return SimpleNamespace(id=message_id, content=content)


class FakeMessagesClient:
    def __init__(self, messages_by_thread):
        self.messages_by_thread = messages_by_thread
        self.calls = []
        self.retrieve_calls = []

    async def list(self, *, thread_id, order, after):
        self.calls.append((thread_id, order, after))
        response = self.messages_by_thread[thread_id]
        if isinstance(response, Exception):
            raise response
        return SimpleNamespace(data=response, has_more=False)

    async def retrieve(self, *, thread_id, message_id):
        self.retrieve_calls.append((thread_id, message_id))
        response = self.messages_by_thread[thread_id]
        if isinstance(response, Exception):
            raise response
        for message in response:
            if message.id == message_id:
                return message
        raise KeyError(message_id)


class FakeFilesWithRawResponse:
    def __init__(self, file_responses=None):
        self.file_responses = file_responses or {}
        self.calls = []

    async def retrieve_content(self, file_id):
        self.calls.append(file_id)
        response = self.file_responses[file_id]
        if isinstance(response, Exception):
            raise response
        return response


class FakeFileStore:
    def __init__(self, *, fail: bool = False):
        self.fail = fail
        self.stored_files: dict[str, tuple[bytes, str]] = {}

    async def put(self, key, body, content_type):
        if self.fail:
            raise RuntimeError("store failure")
        body.seek(0)
        self.stored_files[key] = (body.read(), content_type)


def _fake_openai_client(messages_by_thread, *, file_responses=None):
    messages_client = FakeMessagesClient(messages_by_thread)
    files_client = FakeFilesWithRawResponse(file_responses)
    client = SimpleNamespace(
        beta=SimpleNamespace(
            threads=SimpleNamespace(
                messages=messages_client,
            )
        ),
        files=SimpleNamespace(with_raw_response=files_client),
    )
    return client, messages_client


async def _seed_thread(session, *, class_id: int, assistant_id: int, thread_id: int):
    class_ = await session.get(models.Class, class_id)
    if class_ is None:
        session.add(models.Class(id=class_id, name=f"Class {class_id}"))

    assistant = await session.get(models.Assistant, assistant_id)
    if assistant is None:
        session.add(
            models.Assistant(
                id=assistant_id,
                name=f"Assistant {assistant_id}",
                class_id=class_id,
                assistant_id=f"asst-{assistant_id}",
            )
        )
    await session.flush()

    thread = models.Thread(
        id=thread_id,
        thread_id=f"thread-{thread_id}",
        class_id=class_id,
        assistant_id=assistant_id,
    )
    run = models.Run(
        id=thread_id,
        run_id=f"run-{thread_id}",
        status=schemas.RunStatus.COMPLETED,
        thread_id=thread_id,
        assistant_id=assistant_id,
    )
    session.add_all([thread, run])
    await session.flush()
    return thread, run


async def _seed_message(
    session,
    *,
    id_: int,
    thread_id: int,
    run_id: int,
    openai_message_id: str,
    output_index: int,
    role: schemas.MessageRole = schemas.MessageRole.ASSISTANT,
    metadata=None,
):
    message = models.Message(
        id=id_,
        message_id=openai_message_id,
        message_status=schemas.MessageStatus.COMPLETED,
        run_id=run_id,
        thread_id=thread_id,
        output_index=output_index,
        role=role,
        message_metadata=metadata,
    )
    session.add(message)
    await session.flush()
    return message


async def _load_single_message(session) -> models.Message:
    """Fetch the one message that needs parts, fully loaded the way the
    migration loop loads it (thread, assistant, run, anonymous_sessions)."""
    messages = await migration._fetch_message_fields(session)
    assert len(messages) == 1
    return messages[0]


async def test_fetch_message_fields_returns_only_migrated_messages_needing_parts(db):
    async with db.async_session() as session:
        await _seed_thread(session, class_id=1, assistant_id=10, thread_id=100)
        await _seed_thread(session, class_id=2, assistant_id=20, thread_id=200)
        await _seed_message(
            session,
            id_=1001,
            thread_id=100,
            run_id=100,
            openai_message_id="msg-migrated",
            output_index=0,
            metadata=MIGRATION_METADATA,
        )
        await _seed_message(
            session,
            id_=1002,
            thread_id=100,
            run_id=100,
            openai_message_id="msg-not-migrated",
            output_index=1,
            metadata={},
        )
        message_with_part = await _seed_message(
            session,
            id_=1003,
            thread_id=100,
            run_id=100,
            openai_message_id="msg-has-part",
            output_index=2,
            metadata=MIGRATION_METADATA,
        )
        session.add(
            models.MessagePart(
                message_id=message_with_part.id,
                type=schemas.MessagePartType.OUTPUT_TEXT,
                part_index=0,
                text="already migrated",
            )
        )
        await _seed_message(
            session,
            id_=2001,
            thread_id=200,
            run_id=200,
            openai_message_id="msg-other-class",
            output_index=0,
            metadata=MIGRATION_METADATA,
        )
        await session.commit()

    async with db.async_session() as session:
        messages = await migration._fetch_message_fields(session)

    assert [message.message_id for message in messages] == [
        "msg-migrated",
        "msg-other-class",
    ]
    assert [
        (message.thread.class_id, message.thread.assistant_id, message.thread.thread_id)
        for message in messages
    ] == [
        (1, 10, "thread-100"),
        (2, 20, "thread-200"),
    ]


async def test_migrate_message_parts_continues_after_message_failure(db, monkeypatch):
    async with db.async_session() as session:
        await _seed_thread(session, class_id=1, assistant_id=10, thread_id=100)
        await _seed_thread(session, class_id=1, assistant_id=10, thread_id=200)
        await _seed_message(
            session,
            id_=1001,
            thread_id=100,
            run_id=100,
            openai_message_id="msg-fails",
            output_index=0,
            metadata=MIGRATION_METADATA,
        )
        await _seed_message(
            session,
            id_=2001,
            thread_id=200,
            run_id=200,
            openai_message_id="msg-succeeds",
            output_index=0,
            metadata=MIGRATION_METADATA,
        )
        await session.commit()

    fake_client, _messages_client = _fake_openai_client(
        {
            "thread-100": RuntimeError("upstream failure"),
            "thread-200": [
                _openai_message("msg-succeeds", [_text_content("backfilled")])
            ],
        }
    )

    async def fake_get_openai_client_by_class_id(_session, class_id):
        assert class_id == 1
        return fake_client

    monkeypatch.setattr(
        migration, "get_openai_client_by_class_id", fake_get_openai_client_by_class_id
    )

    async with db.async_session() as session:
        await migration.migrate_message_parts(session)

    async with db.async_session() as session:
        parts = list(
            (
                await session.execute(
                    select(models.MessagePart).order_by(models.MessagePart.message_id)
                )
            ).scalars()
        )

    assert [(part.message_id, part.text) for part in parts] == [(2001, "backfilled")]


async def test_migrate_message_parts_reuses_existing_local_file(db):
    async with db.async_session() as session:
        await _seed_thread(session, class_id=1, assistant_id=10, thread_id=100)
        await _seed_message(
            session,
            id_=1001,
            thread_id=100,
            run_id=100,
            openai_message_id="msg-with-file",
            output_index=0,
            metadata=MIGRATION_METADATA,
        )
        s3_file = models.S3File(id=500, key="already-backed/shared.txt")
        session.add(s3_file)
        file = models.File(
            id=50,
            file_id="file-same",
            name="shared.txt",
            class_id=1,
            s3_file=s3_file,
        )
        session.add(file)
        await session.commit()

    fake_client, messages_client = _fake_openai_client(
        {
            "thread-100": [
                _openai_message(
                    "msg-with-file",
                    [
                        _image_content("file-same"),
                        _text_content(
                            "file path",
                            [
                                _file_citation("file-same"),
                                _file_path("file-same"),
                            ],
                        ),
                    ],
                ),
            ],
        }
    )

    async with db.async_session() as session:
        message = await _load_single_message(session)
        await migration._migrate_message_parts(session, fake_client, message)
        await session.commit()

    assert messages_client.calls == []
    assert messages_client.retrieve_calls == [("thread-100", "msg-with-file")]
    # The local file (and its S3File) already exist, so neither a new file
    # fetch nor an S3 backfill should be triggered.
    assert fake_client.files.with_raw_response.calls == []

    async with db.async_session() as session:
        parts = list(
            (
                await session.execute(
                    select(models.MessagePart).order_by(models.MessagePart.part_index)
                )
            ).scalars()
        )
        annotations = list(
            (
                await session.execute(
                    select(models.Annotation).order_by(
                        models.Annotation.annotation_index
                    )
                )
            ).scalars()
        )

    assert [part.type for part in parts] == [
        schemas.MessagePartType.INPUT_IMAGE,
        schemas.MessagePartType.OUTPUT_TEXT,
    ]
    assert parts[0].input_image_file_object_id == 50
    assert [
        (annotation.file_object_id, annotation.filename) for annotation in annotations
    ] == [
        (50, "shared.txt"),
        (50, "shared.txt"),
    ]


async def test_migrate_message_parts_backfills_missing_s3_file(db, monkeypatch):
    async with db.async_session() as session:
        await _seed_thread(session, class_id=1, assistant_id=10, thread_id=100)
        await _seed_message(
            session,
            id_=1001,
            thread_id=100,
            run_id=100,
            openai_message_id="msg-with-file",
            output_index=0,
            metadata=MIGRATION_METADATA,
        )
        session.add(
            models.File(
                id=50,
                file_id="file-needs-s3",
                name="shared.txt",
                content_type="text/plain",
                class_id=1,
            )
        )
        await session.commit()

    fake_store = FakeFileStore()
    monkeypatch.setattr(
        migration.config, "file_store", SimpleNamespace(store=fake_store)
    )
    fake_client, _messages_client = _fake_openai_client(
        {
            "thread-100": [
                _openai_message(
                    "msg-with-file",
                    [
                        _image_content("file-needs-s3"),
                        _text_content(
                            "file path",
                            [_file_path("file-needs-s3")],
                        ),
                    ],
                )
            ],
        },
        file_responses={
            "file-needs-s3": SimpleNamespace(
                status_code=200,
                content=b"stored bytes",
            )
        },
    )

    async with db.async_session() as session:
        message = await _load_single_message(session)
        await migration._migrate_message_parts(session, fake_client, message)
        await session.commit()

    assert fake_client.files.with_raw_response.calls == ["file-needs-s3"]
    assert list(fake_store.stored_files.values()) == [(b"stored bytes", "text/plain")]

    async with db.async_session() as session:
        parts = list((await session.execute(select(models.MessagePart))).scalars())
        annotations = list((await session.execute(select(models.Annotation))).scalars())
        file = await session.get(models.File, 50)
        assert file is not None
        assert file.s3_file_id is not None
        s3_file = await session.get(models.S3File, file.s3_file_id)
        assert s3_file is not None
        assert s3_file.key in fake_store.stored_files

    assert len(parts) == 2
    assert len(annotations) == 1


async def test_migrate_message_parts_skips_existing_s3_file_backfill(db, monkeypatch):
    async with db.async_session() as session:
        await _seed_thread(session, class_id=1, assistant_id=10, thread_id=100)
        await _seed_message(
            session,
            id_=1001,
            thread_id=100,
            run_id=100,
            openai_message_id="msg-with-file",
            output_index=0,
            metadata=MIGRATION_METADATA,
        )
        session.add(
            models.File(
                id=50,
                file_id="file-backed",
                name="shared.txt",
                content_type="text/plain",
                class_id=1,
                s3_file=models.S3File(id=500, key="already-backed/shared.txt"),
            )
        )
        await session.commit()

    fake_store = FakeFileStore()
    monkeypatch.setattr(
        migration.config, "file_store", SimpleNamespace(store=fake_store)
    )
    fake_client, _messages_client = _fake_openai_client(
        {
            "thread-100": [
                _openai_message(
                    "msg-with-file",
                    [_text_content("file path", [_file_path("file-backed")])],
                )
            ],
        },
        file_responses={
            "file-backed": SimpleNamespace(status_code=200, content=b"unused")
        },
    )

    async with db.async_session() as session:
        message = await _load_single_message(session)
        await migration._migrate_message_parts(session, fake_client, message)
        await session.commit()

    assert fake_client.files.with_raw_response.calls == []
    assert fake_store.stored_files == {}

    async with db.async_session() as session:
        parts = list((await session.execute(select(models.MessagePart))).scalars())
    assert len(parts) == 1


async def test_migrate_message_parts_continues_when_s3_backfill_fails(db, monkeypatch):
    async with db.async_session() as session:
        await _seed_thread(session, class_id=1, assistant_id=10, thread_id=100)
        await _seed_message(
            session,
            id_=1001,
            thread_id=100,
            run_id=100,
            openai_message_id="msg-with-file",
            output_index=0,
            metadata=MIGRATION_METADATA,
        )
        session.add(
            models.File(
                id=50,
                file_id="file-store-fails",
                name="shared.txt",
                content_type="text/plain",
                class_id=1,
            )
        )
        await session.commit()

    monkeypatch.setattr(
        migration.config,
        "file_store",
        SimpleNamespace(store=FakeFileStore(fail=True)),
    )
    fake_client, _messages_client = _fake_openai_client(
        {
            "thread-100": [
                _openai_message(
                    "msg-with-file",
                    [_text_content("file path", [_file_path("file-store-fails")])],
                )
            ],
        },
        file_responses={
            "file-store-fails": SimpleNamespace(
                status_code=200,
                content=b"stored bytes",
            )
        },
    )

    async with db.async_session() as session:
        message = await _load_single_message(session)
        await migration._migrate_message_parts(session, fake_client, message)
        await session.commit()

    async with db.async_session() as session:
        parts = list((await session.execute(select(models.MessagePart))).scalars())
        file = await session.get(models.File, 50)
        assert file is not None
        assert file.s3_file_id is None
        annotation = await session.scalar(select(models.Annotation))
        assert annotation is not None
        assert annotation.file_object_id == 50

    assert len(parts) == 1
