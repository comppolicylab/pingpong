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


class FakeAuthzClient:
    """Records grant/revoke writes so tests can assert the OpenFGA tuples the
    migration emits, without standing up a real authz backend."""

    def __init__(self):
        self.grants: list = []
        self.revokes: list = []

    async def write(self, grant=None, revoke=None):
        if grant:
            self.grants.extend(grant)
        if revoke:
            self.revokes.extend(revoke)

    async def write_safe(self, grant=None, revoke=None):
        await self.write(grant=grant, revoke=revoke)


class FakeMessagesClient:
    def __init__(self, messages_by_thread):
        self.messages_by_thread = messages_by_thread
        self.retrieve_calls = []

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

    async def get(self, name):
        data, _content_type = self.stored_files[name]
        yield data


def _fake_openai_client(messages_by_thread, *, file_responses=None):
    return SimpleNamespace(
        beta=SimpleNamespace(
            threads=SimpleNamespace(
                messages=FakeMessagesClient(messages_by_thread),
            )
        ),
        files=SimpleNamespace(
            with_raw_response=FakeFilesWithRawResponse(file_responses)
        ),
    )


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
    user_id: int | None = None,
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
        user_id=user_id,
    )
    session.add(message)
    await session.flush()
    return message


async def _all(session, model, order_by=None):
    """Fetch all rows of a model, optionally ordered."""
    stmt = select(model)
    if order_by is not None:
        stmt = stmt.order_by(order_by)
    return list((await session.scalars(stmt)).all())


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

    fake_client = _fake_openai_client(
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
        await migration.migrate_message_parts(session, FakeAuthzClient())

    async with db.async_session() as session:
        parts = await _all(session, models.MessagePart, models.MessagePart.message_id)

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
            content_type="text/plain",
            class_id=1,
            s3_file=s3_file,
        )
        session.add(file)
        await session.commit()

    fake_client = _fake_openai_client(
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
        await migration._migrate_message_parts(
            session, FakeAuthzClient(), fake_client, message, []
        )
        await session.commit()

    assert fake_client.beta.threads.messages.retrieve_calls == [
        ("thread-100", "msg-with-file")
    ]
    # The local file (and its S3File) already exist, so neither a new file
    # fetch nor an S3 backfill should be triggered.
    assert fake_client.files.with_raw_response.calls == []

    async with db.async_session() as session:
        parts = await _all(session, models.MessagePart, models.MessagePart.part_index)
        annotations = await _all(
            session, models.Annotation, models.Annotation.annotation_index
        )
        thread = await session.get(models.Thread, 100)
        image_files = await thread.awaitable_attrs.image_files

    # The assistant image content becomes a container-file-citation annotation on
    # the text part (the native v3 shape), not an INPUT_IMAGE part.
    assert [part.type for part in parts] == [
        schemas.MessagePartType.OUTPUT_TEXT,
    ]
    assert [
        (
            annotation.type,
            annotation.file_object_id,
            annotation.vision_file_object_id,
            annotation.filename,
        )
        for annotation in annotations
    ] == [
        (schemas.AnnotationType.FILE_CITATION, 50, None, "shared.txt"),
        (schemas.AnnotationType.CONTAINER_FILE_CITATION, 50, None, "shared.txt"),
        (schemas.AnnotationType.CONTAINER_FILE_CITATION, None, 50, "shared.txt"),
    ]
    assert [image_file.id for image_file in image_files] == [50]


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
    fake_client = _fake_openai_client(
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
        await migration._migrate_message_parts(
            session, FakeAuthzClient(), fake_client, message, []
        )
        await session.commit()

    assert fake_client.files.with_raw_response.calls == ["file-needs-s3"]
    assert list(fake_store.stored_files.values()) == [(b"stored bytes", "text/plain")]

    async with db.async_session() as session:
        parts = await _all(session, models.MessagePart)
        annotations = await _all(session, models.Annotation)
        file = await session.get(models.File, 50)
        assert file is not None
        assert file.s3_file_id is not None
        s3_file = await session.get(models.S3File, file.s3_file_id)
        assert s3_file is not None
        assert s3_file.key in fake_store.stored_files
        thread = await session.get(models.Thread, 100)
        ci_files = await thread.awaitable_attrs.code_interpreter_files
        assert [ci_file.id for ci_file in ci_files] == [50]
        image_files = await thread.awaitable_attrs.image_files
        assert [image_file.id for image_file in image_files] == [50]

    assert len(parts) == 1
    assert len(annotations) == 2


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
    fake_client = _fake_openai_client(
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
        await migration._migrate_message_parts(
            session, FakeAuthzClient(), fake_client, message, []
        )
        await session.commit()

    assert fake_client.files.with_raw_response.calls == []
    assert fake_store.stored_files == {}

    async with db.async_session() as session:
        parts = await _all(session, models.MessagePart)
        thread = await session.get(models.Thread, 100)
        ci_files = await thread.awaitable_attrs.code_interpreter_files
        assert [ci_file.id for ci_file in ci_files] == [50]
    assert len(parts) == 1


async def test_migrate_message_parts_creates_vision_annotation_for_assistant_image(
    db, monkeypatch
):
    """Assistant `image_file` content (a code interpreter output image) becomes a
    container-file-citation annotation with vision fields, an image-thread
    association, and a sniffed image content type — the extensionless UUID
    filename OpenAI assigns provides no type signal."""

    async with db.async_session() as session:
        await _seed_thread(session, class_id=1, assistant_id=10, thread_id=100)
        await _seed_message(
            session,
            id_=1001,
            thread_id=100,
            run_id=100,
            openai_message_id="msg-with-ci-image",
            output_index=0,
            metadata=MIGRATION_METADATA,
        )
        await session.commit()

    fake_store = FakeFileStore()
    monkeypatch.setattr(
        migration.config, "file_store", SimpleNamespace(store=fake_store)
    )
    png_bytes = b"\x89PNG\r\n\x1a\n" + b"fake image data"
    fake_client = _fake_openai_client(
        {
            "thread-100": [
                _openai_message(
                    "msg-with-ci-image",
                    [
                        _image_content("file-ci-image"),
                        _text_content("Here is the plot."),
                    ],
                )
            ],
        },
        file_responses={
            "file-ci-image": SimpleNamespace(status_code=200, content=png_bytes)
        },
    )

    async def fake_retrieve(_file_id):
        return SimpleNamespace(
            filename="484b93a8-fd8d-4e71-8b46-5e95189838de", created_at=0
        )

    fake_client.files.retrieve = fake_retrieve

    async with db.async_session() as session:
        message = await _load_single_message(session)
        await migration._migrate_message_parts(
            session, FakeAuthzClient(), fake_client, message, []
        )
        await session.commit()

    async with db.async_session() as session:
        parts = await _all(session, models.MessagePart, models.MessagePart.part_index)
        annotations = await _all(session, models.Annotation)
        file = await session.scalar(
            select(models.File).where(models.File.file_id == "file-ci-image")
        )
        thread = await session.get(models.Thread, 100)
        image_files = await thread.awaitable_attrs.image_files

    assert [(part.type, part.text) for part in parts] == [
        (schemas.MessagePartType.OUTPUT_TEXT, "Here is the plot."),
    ]
    assert len(annotations) == 1
    annotation = annotations[0]
    assert annotation.type == schemas.AnnotationType.CONTAINER_FILE_CITATION
    assert annotation.message_part_id == parts[0].id
    assert annotation.vision_file_id == "file-ci-image"
    assert annotation.vision_file_object_id == file.id
    assert annotation.file_object_id is None
    assert annotation.container_id is None
    assert file.content_type == "image/png"
    assert [image_file.id for image_file in image_files] == [file.id]


async def test_migrate_message_parts_sniffs_content_type_for_reused_backfilled_file(
    db, monkeypatch
):
    """A file already backfilled to the store (e.g. by an interrupted earlier run)
    but missing a content type gets its type sniffed from the stored bytes, not
    refetched from OpenAI."""

    async with db.async_session() as session:
        await _seed_thread(session, class_id=1, assistant_id=10, thread_id=100)
        await _seed_message(
            session,
            id_=1001,
            thread_id=100,
            run_id=100,
            openai_message_id="msg-with-ci-image",
            output_index=0,
            metadata=MIGRATION_METADATA,
        )
        session.add(
            models.File(
                id=50,
                file_id="file-backed-image",
                name="484b93a8-fd8d-4e71-8b46-5e95189838de",
                class_id=1,
                s3_file=models.S3File(id=500, key="backed/image"),
            )
        )
        await session.commit()

    fake_store = FakeFileStore()
    fake_store.stored_files["backed/image"] = (
        b"\x89PNG\r\n\x1a\n" + b"stored image data",
        None,
    )
    monkeypatch.setattr(
        migration.config, "file_store", SimpleNamespace(store=fake_store)
    )
    fake_client = _fake_openai_client(
        {
            "thread-100": [
                _openai_message(
                    "msg-with-ci-image",
                    [
                        _image_content("file-backed-image"),
                        _text_content("Here is the plot."),
                    ],
                )
            ],
        },
    )

    async with db.async_session() as session:
        message = await _load_single_message(session)
        await migration._migrate_message_parts(
            session, FakeAuthzClient(), fake_client, message, []
        )
        await session.commit()

    # No OpenAI content fetch — the type came from the stored bytes.
    assert fake_client.files.with_raw_response.calls == []

    async with db.async_session() as session:
        file = await session.get(models.File, 50)
        assert file.content_type == "image/png"
        thread = await session.get(models.Thread, 100)
        image_files = await thread.awaitable_attrs.image_files
        assert [image_file.id for image_file in image_files] == [50]


async def test_migrate_message_parts_keeps_input_image_for_user_messages(
    db, monkeypatch
):
    """User-uploaded images stay INPUT_IMAGE parts — only assistant image content
    is converted to container-file-citation annotations."""

    async with db.async_session() as session:
        await _seed_thread(session, class_id=1, assistant_id=10, thread_id=100)
        await _seed_message(
            session,
            id_=1001,
            thread_id=100,
            run_id=100,
            openai_message_id="msg-user-image",
            output_index=0,
            role=schemas.MessageRole.USER,
            metadata=MIGRATION_METADATA,
        )
        await session.commit()

    fake_store = FakeFileStore()
    monkeypatch.setattr(
        migration.config, "file_store", SimpleNamespace(store=fake_store)
    )
    fake_client = _fake_openai_client(
        {
            "thread-100": [
                _openai_message(
                    "msg-user-image",
                    [
                        _image_content("file-user-image"),
                        _text_content("what is this?"),
                    ],
                )
            ],
        },
        file_responses={
            "file-user-image": SimpleNamespace(
                status_code=200, content=b"\x89PNG\r\n\x1a\nuser bytes"
            )
        },
    )

    async def fake_retrieve(_file_id):
        return SimpleNamespace(filename="photo.png", created_at=0)

    fake_client.files.retrieve = fake_retrieve

    async with db.async_session() as session:
        message = await _load_single_message(session)
        await migration._migrate_message_parts(
            session, FakeAuthzClient(), fake_client, message, []
        )
        await session.commit()

    async with db.async_session() as session:
        parts = await _all(session, models.MessagePart, models.MessagePart.part_index)
        annotations = await _all(session, models.Annotation)
        file = await session.scalar(
            select(models.File).where(models.File.file_id == "file-user-image")
        )
        thread = await session.get(models.Thread, 100)
        image_files = await thread.awaitable_attrs.image_files

    assert [part.type for part in parts] == [
        schemas.MessagePartType.INPUT_IMAGE,
        schemas.MessagePartType.INPUT_TEXT,
    ]
    assert parts[0].input_image_file_object_id == file.id
    assert annotations == []
    assert image_files == []


async def test_migrate_message_parts_preserves_anonymous_context_for_image_file(
    db, monkeypatch
):
    async with db.async_session() as session:
        thread, run = await _seed_thread(
            session, class_id=1, assistant_id=10, thread_id=100
        )
        thread.private = True
        run.creator_id = 1
        await _seed_user(session, id_=1)
        link = models.AnonymousLink(id=42, share_token="share-tok")
        session.add(link)
        await session.flush()
        await _seed_user(session, id_=23, anonymous_link_id=42)
        session.add(
            models.AnonymousSession(
                id=7, session_token="sess-tok", thread_id=100, user_id=23
            )
        )
        await _seed_message(
            session,
            id_=1001,
            thread_id=100,
            run_id=100,
            openai_message_id="msg-with-image",
            output_index=0,
            metadata=MIGRATION_METADATA,
        )
        await session.commit()

    fake_store = FakeFileStore()
    monkeypatch.setattr(
        migration.config, "file_store", SimpleNamespace(store=fake_store)
    )
    fake_client = _fake_openai_client(
        {
            "thread-100": [
                _openai_message("msg-with-image", [_image_content("file-image")])
            ],
        },
        file_responses={
            "file-image": SimpleNamespace(status_code=200, content=b"image bytes")
        },
    )

    async def fake_retrieve_image(_file_id):
        return SimpleNamespace(filename="generated.png", created_at=0)

    fake_client.files.retrieve = fake_retrieve_image
    authz = FakeAuthzClient()

    async with db.async_session() as session:
        message = await _load_single_message(session)
        await migration._migrate_message_parts(session, authz, fake_client, message, [])
        await session.commit()

    async with db.async_session() as session:
        file = await session.scalar(
            select(models.File).where(models.File.file_id == "file-image")
        )

    assert file.uploader_id == 1
    assert file.anonymous_session_id == 7
    assert file.anonymous_link_id == 42
    assert sorted(authz.grants) == sorted(
        [
            ("class:1", "parent", f"user_file:{file.id}"),
            ("user:1", "owner", f"user_file:{file.id}"),
            ("anonymous_user:sess-tok", "owner", f"user_file:{file.id}"),
            ("anonymous_link:share-tok", "can_delete", f"user_file:{file.id}"),
        ]
    )


async def test_migrate_message_parts_strips_anonymous_context_for_file_path(
    db, monkeypatch
):
    async with db.async_session() as session:
        thread, run = await _seed_thread(
            session, class_id=1, assistant_id=10, thread_id=100
        )
        thread.private = True
        run.creator_id = 1
        await _seed_user(session, id_=1)
        link = models.AnonymousLink(id=42, share_token="share-tok")
        session.add(link)
        await session.flush()
        await _seed_user(session, id_=23, anonymous_link_id=42)
        session.add(
            models.AnonymousSession(
                id=7, session_token="sess-tok", thread_id=100, user_id=23
            )
        )
        await _seed_message(
            session,
            id_=1001,
            thread_id=100,
            run_id=100,
            openai_message_id="msg-with-file-path",
            output_index=0,
            metadata=MIGRATION_METADATA,
        )
        await session.commit()

    fake_store = FakeFileStore()
    monkeypatch.setattr(
        migration.config, "file_store", SimpleNamespace(store=fake_store)
    )
    fake_client = _fake_openai_client(
        {
            "thread-100": [
                _openai_message(
                    "msg-with-file-path",
                    [_text_content("path", [_file_path("file-output")])],
                )
            ],
        },
        file_responses={
            "file-output": SimpleNamespace(status_code=200, content=b"output bytes")
        },
    )

    async def fake_retrieve_output(_file_id):
        return SimpleNamespace(filename="output.txt", created_at=0)

    fake_client.files.retrieve = fake_retrieve_output
    authz = FakeAuthzClient()

    async with db.async_session() as session:
        message = await _load_single_message(session)
        await migration._migrate_message_parts(session, authz, fake_client, message, [])
        await session.commit()

    async with db.async_session() as session:
        file = await session.scalar(
            select(models.File).where(models.File.file_id == "file-output")
        )

    assert file.uploader_id == 1
    assert file.anonymous_session_id is None
    assert file.anonymous_link_id is None
    assert sorted(authz.grants) == sorted(
        [
            ("class:1", "parent", f"user_file:{file.id}"),
            ("user:1", "owner", f"user_file:{file.id}"),
        ]
    )


async def test_migrate_message_parts_raises_when_s3_backfill_fails(db, monkeypatch):
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
    fake_client = _fake_openai_client(
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
        with pytest.raises(RuntimeError, match="store failure"):
            await migration._migrate_message_parts(
                session, FakeAuthzClient(), fake_client, message, []
            )


async def test_migrate_message_parts_revokes_grants_on_failure(db, monkeypatch):
    """If a message fails after a new File (and its authz grant) is created, the
    savepoint rollback removes the File row, so the grant must be revoked too —
    otherwise it dangles, pointing at a File that no longer exists."""

    async with db.async_session() as session:
        await _seed_thread(session, class_id=1, assistant_id=10, thread_id=100)
        await _seed_message(
            session,
            id_=1001,
            thread_id=100,
            run_id=100,
            openai_message_id="msg-fails-after-grant",
            output_index=0,
            metadata=MIGRATION_METADATA,
        )
        await session.commit()

    # The file_path annotation references a brand-new file (so a grant is
    # written), then the image content — processed after the text parts —
    # references a file whose retrieve raises, failing the message after the
    # grant was written.
    fake_store = FakeFileStore()
    monkeypatch.setattr(
        migration.config, "file_store", SimpleNamespace(store=fake_store)
    )
    fake_client = _fake_openai_client(
        {
            "thread-100": [
                _openai_message(
                    "msg-fails-after-grant",
                    [
                        _text_content("path", [_file_path("file-new")]),
                        _image_content("file-explodes"),
                    ],
                )
            ],
        },
        file_responses={
            "file-new": SimpleNamespace(status_code=200, content=b"new bytes")
        },
    )

    async def fake_retrieve(file_id):
        if file_id == "file-explodes":
            raise RuntimeError("retrieve failure")
        return SimpleNamespace(filename="new.txt", created_at=0)

    fake_client.files.retrieve = fake_retrieve

    async def fake_get_openai_client_by_class_id(_session, class_id):
        return fake_client

    monkeypatch.setattr(
        migration, "get_openai_client_by_class_id", fake_get_openai_client_by_class_id
    )

    authz = FakeAuthzClient()
    async with db.async_session() as session:
        await migration.migrate_message_parts(session, authz)

    # The grant written for the new file must have been revoked on rollback...
    assert authz.grants
    assert sorted(authz.revokes) == sorted(authz.grants)

    # ...and nothing was persisted for the failed message.
    async with db.async_session() as session:
        parts = await _all(session, models.MessagePart)
        files = await _all(session, models.File)
    assert parts == []
    assert files == []


async def _seed_user(session, *, id_: int, anonymous_link_id: int | None = None):
    user = models.User(id=id_, anonymous_link_id=anonymous_link_id)
    session.add(user)
    await session.flush()
    return user


async def test_get_anonymous_user_fields_for_logged_in_user(db):
    async with db.async_session() as session:
        await _seed_thread(session, class_id=1, assistant_id=10, thread_id=100)
        await _seed_user(session, id_=500)
        await _seed_message(
            session,
            id_=1001,
            thread_id=100,
            run_id=100,
            openai_message_id="msg",
            output_index=0,
            metadata=MIGRATION_METADATA,
            user_id=500,
        )
        await session.commit()

    async with db.async_session() as session:
        message = await _load_single_message(session)
        uploader = await migration._get_anonymous_user_fields(
            session, message.thread, message, include_anonymous_context=True
        )

    assert uploader.uploader_id == 500
    assert uploader.user_auth == "user:500"
    assert uploader.anonymous_user_auth is None
    assert uploader.anonymous_link_auth is None


async def test_get_anonymous_user_fields_for_anonymous_session_and_link(db):
    async with db.async_session() as session:
        await _seed_thread(session, class_id=1, assistant_id=10, thread_id=100)
        link = models.AnonymousLink(id=42, share_token="share-tok")
        session.add(link)
        await session.flush()
        await _seed_user(session, id_=500, anonymous_link_id=42)
        session.add(
            models.AnonymousSession(
                id=7,
                session_token="sess-tok",
                thread_id=100,
                user_id=500,
            )
        )
        await _seed_message(
            session,
            id_=1001,
            thread_id=100,
            run_id=100,
            openai_message_id="msg",
            output_index=0,
            metadata=MIGRATION_METADATA,
            user_id=500,
        )
        await session.commit()

    async with db.async_session() as session:
        message = await _load_single_message(session)
        uploader = await migration._get_anonymous_user_fields(
            session, message.thread, message, include_anonymous_context=True
        )

    assert uploader.uploader_id == 500
    assert uploader.anonymous_session_id == 7
    assert uploader.anonymous_link_id == 42
    assert uploader.user_auth == "user:500"
    assert uploader.anonymous_user_auth == "anonymous_user:sess-tok"
    assert uploader.anonymous_link_auth == "anonymous_link:share-tok"


async def test_get_anonymous_user_fields_does_not_infer_from_thread_users(db):
    """Uploader identity comes from m15's message/run rows, not thread parties."""
    async with db.async_session() as session:
        await _seed_thread(session, class_id=1, assistant_id=10, thread_id=100)
        session.add(models.AnonymousLink(id=99, share_token="fallback-share-tok"))
        await session.flush()
        await _seed_user(session, id_=400, anonymous_link_id=99)
        await _seed_user(session, id_=500)
        await session.execute(
            models.user_thread_association.insert(),
            [
                {"user_id": 400, "thread_id": 100},
                {"user_id": 500, "thread_id": 100},
            ],
        )
        await _seed_message(
            session,
            id_=1001,
            thread_id=100,
            run_id=100,
            openai_message_id="msg",
            output_index=0,
            metadata=MIGRATION_METADATA,
        )
        # Leave message.user_id/run.creator_id unset so thread users are ignored.
        await session.commit()

    async with db.async_session() as session:
        message = await _load_single_message(session)
        uploader = await migration._get_anonymous_user_fields(
            session, message.thread, message, include_anonymous_context=True
        )

    assert uploader.uploader_id is None
    assert uploader.user_auth is None


async def test_get_anonymous_user_fields_falls_back_to_run_creator(db):
    """With no message `user_id` and no thread users, the uploader falls back to
    the run's creator."""
    async with db.async_session() as session:
        await _seed_thread(session, class_id=1, assistant_id=10, thread_id=100)
        await _seed_user(session, id_=500)
        run = await session.get(models.Run, 100)
        run.creator_id = 500
        await _seed_message(
            session,
            id_=1001,
            thread_id=100,
            run_id=100,
            openai_message_id="msg",
            output_index=0,
            metadata=MIGRATION_METADATA,
        )
        await session.commit()

    async with db.async_session() as session:
        message = await _load_single_message(session)
        uploader = await migration._get_anonymous_user_fields(
            session, message.thread, message, include_anonymous_context=False
        )

    assert uploader.uploader_id == 500
    assert uploader.user_auth == "user:500"


async def test_get_anonymous_user_fields_tracks_logged_in_anonymous_session(db):
    async with db.async_session() as session:
        await _seed_thread(session, class_id=1, assistant_id=10, thread_id=100)
        await _seed_user(session, id_=1)
        link = models.AnonymousLink(id=42, share_token="share-tok")
        session.add(link)
        await session.flush()
        await _seed_user(session, id_=23, anonymous_link_id=42)
        session.add(
            models.AnonymousSession(
                id=7, session_token="sess-tok", thread_id=100, user_id=23
            )
        )
        run = await session.get(models.Run, 100)
        run.creator_id = 1
        await _seed_message(
            session,
            id_=1001,
            thread_id=100,
            run_id=100,
            openai_message_id="msg",
            output_index=0,
            metadata=MIGRATION_METADATA,
        )
        await session.commit()

    async with db.async_session() as session:
        message = await _load_single_message(session)
        uploader = await migration._get_anonymous_user_fields(
            session, message.thread, message, include_anonymous_context=True
        )

    assert uploader.uploader_id == 1
    assert uploader.anonymous_session_id == 7
    assert uploader.anonymous_link_id == 42
    assert uploader.user_auth == "user:1"
    assert uploader.anonymous_user_auth == "anonymous_user:sess-tok"
    assert uploader.anonymous_link_auth == "anonymous_link:share-tok"


async def test_get_anonymous_user_fields_strips_anonymous_context_when_requested(db):
    async with db.async_session() as session:
        await _seed_thread(session, class_id=1, assistant_id=10, thread_id=100)
        link = models.AnonymousLink(id=42, share_token="share-tok")
        session.add(link)
        await session.flush()
        await _seed_user(session, id_=500, anonymous_link_id=42)
        session.add(
            models.AnonymousSession(
                id=7, session_token="sess-tok", thread_id=100, user_id=500
            )
        )
        await _seed_message(
            session,
            id_=1001,
            thread_id=100,
            run_id=100,
            openai_message_id="msg",
            output_index=0,
            metadata=MIGRATION_METADATA,
            user_id=500,
        )
        await session.commit()

    async with db.async_session() as session:
        message = await _load_single_message(session)
        uploader = await migration._get_anonymous_user_fields(
            session, message.thread, message, include_anonymous_context=False
        )

    assert uploader.uploader_id == 500
    assert uploader.user_auth == "user:500"
    assert uploader.anonymous_session_id is None
    assert uploader.anonymous_link_id is None
    assert uploader.anonymous_user_auth is None
    assert uploader.anonymous_link_auth is None


async def test_get_anonymous_user_fields_grants_match_file_grants(db):
    """The derived auth strings, fed to `_file_grants`, produce the same tuples
    request-driven uploads would for a private file."""
    async with db.async_session() as session:
        await _seed_thread(session, class_id=1, assistant_id=10, thread_id=100)
        link = models.AnonymousLink(id=42, share_token="share-tok")
        session.add(link)
        await session.flush()
        await _seed_user(session, id_=500, anonymous_link_id=42)
        session.add(
            models.AnonymousSession(
                id=7, session_token="sess-tok", thread_id=100, user_id=500
            )
        )
        await _seed_message(
            session,
            id_=1001,
            thread_id=100,
            run_id=100,
            openai_message_id="msg",
            output_index=0,
            metadata=MIGRATION_METADATA,
            user_id=500,
        )
        await session.commit()

    async with db.async_session() as session:
        message = await _load_single_message(session)
        uploader = await migration._get_anonymous_user_fields(
            session, message.thread, message, include_anonymous_context=True
        )

    private_file = SimpleNamespace(id=99, private=True, uploader_id=500)
    grants = migration._file_grants(
        private_file,
        1,
        uploader.user_auth,
        uploader.anonymous_link_auth,
        uploader.anonymous_user_auth,
    )

    assert set(grants) == {
        ("class:1", "parent", "user_file:99"),
        ("user:500", "owner", "user_file:99"),
        ("anonymous_user:sess-tok", "owner", "user_file:99"),
        ("anonymous_link:share-tok", "can_delete", "user_file:99"),
    }
