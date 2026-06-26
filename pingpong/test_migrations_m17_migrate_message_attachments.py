from types import SimpleNamespace

import pytest
from sqlalchemy import select

from pingpong import models, schemas
from pingpong.migrations import m17_migrate_message_attachments as migration

pytestmark = pytest.mark.asyncio


MIGRATION_KEY = "assistants_to_responses_api_thread_migration"


def _migration_metadata(*, attachments_complete: bool = False):
    metadata = {MIGRATION_KEY: {"message_parts": "complete"}}
    if attachments_complete:
        metadata[MIGRATION_KEY]["attachments"] = "complete"
    return metadata


def _attachments_migration_state(message):
    return message.message_metadata[MIGRATION_KEY].get("attachments")


def _patch_openai_client(monkeypatch, fake_client, *, expected_class_id=None):
    async def fake_get_openai_client_by_class_id(_session, class_id):
        if expected_class_id is not None:
            assert class_id == expected_class_id
        return fake_client

    monkeypatch.setattr(
        migration, "get_openai_client_by_class_id", fake_get_openai_client_by_class_id
    )


def _tool(tool_type: str):
    return SimpleNamespace(type=tool_type)


def _attachment(file_id, tool_types):
    return SimpleNamespace(
        file_id=file_id,
        tools=[_tool(t) for t in tool_types],
    )


def _openai_message(message_id: str, attachments):
    return SimpleNamespace(id=message_id, attachments=attachments)


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


def _fake_openai_client(messages_by_thread):
    return SimpleNamespace(
        beta=SimpleNamespace(
            threads=SimpleNamespace(
                messages=FakeMessagesClient(messages_by_thread),
            )
        ),
    )


async def _seed_thread(
    session,
    *,
    class_id: int,
    assistant_id: int,
    thread_id: int,
    vector_store_id: int | None = None,
):
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
        vector_store_id=vector_store_id,
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


async def _seed_vector_store(session, *, id_: int, class_id: int):
    vector_store = models.VectorStore(
        id=id_,
        vector_store_id=f"vs-{id_}",
        type=schemas.VectorStoreType.THREAD,
        class_id=class_id,
    )
    session.add(vector_store)
    await session.flush()
    return vector_store


async def _seed_message(
    session,
    *,
    id_: int,
    thread_id: int,
    run_id: int,
    openai_message_id: str,
    output_index: int,
    role: schemas.MessageRole = schemas.MessageRole.USER,
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


async def _seed_file(session, *, id_: int, file_id: str, class_id: int | None = None):
    file = models.File(
        id=id_, file_id=file_id, name=f"{file_id}.txt", class_id=class_id
    )
    session.add(file)
    await session.flush()
    return file


async def _add_code_interpreter_file_to_thread(
    session, *, file_object_id: int, thread_id: int
):
    await session.execute(
        models.code_interpreter_file_thread_association.insert().values(
            file_id=file_object_id,
            thread_id=thread_id,
        )
    )


async def _add_file_to_vector_store(
    session, *, file_object_id: int, vector_store_id: int
):
    await session.execute(
        models.file_vector_store_association.insert().values(
            file_id=file_object_id,
            vector_store_id=vector_store_id,
        )
    )


async def _all(session, model, order_by=None):
    """Fetch all rows of a model, optionally ordered."""
    stmt = select(model)
    if order_by is not None:
        stmt = stmt.order_by(order_by)
    return list((await session.scalars(stmt)).all())


async def _attachment_pairs(session, association_table):
    """Return (message_id, file_id) pairs from an attachment association table."""
    rows = await session.execute(
        select(association_table.c.message_id, association_table.c.file_id).order_by(
            association_table.c.file_id
        )
    )
    return [tuple(row) for row in rows]


async def test_fetch_messages_returns_only_migrated_messages_needing_attachments(db):
    async with db.async_session() as session:
        await _seed_thread(session, class_id=1, assistant_id=10, thread_id=100)
        await _seed_thread(session, class_id=2, assistant_id=20, thread_id=200)
        # Migrated by m15, not yet attachment-migrated -> included.
        await _seed_message(
            session,
            id_=1001,
            thread_id=100,
            run_id=100,
            openai_message_id="msg-migrated",
            output_index=0,
            metadata=_migration_metadata(),
        )
        # Not migrated by m15 -> excluded.
        await _seed_message(
            session,
            id_=1002,
            thread_id=100,
            run_id=100,
            openai_message_id="msg-not-migrated",
            output_index=1,
            metadata={},
        )
        # Already attachment-migrated -> excluded.
        await _seed_message(
            session,
            id_=1003,
            thread_id=100,
            run_id=100,
            openai_message_id="msg-already-done",
            output_index=2,
            metadata=_migration_metadata(attachments_complete=True),
        )
        # Migrated, different class -> included.
        await _seed_message(
            session,
            id_=2001,
            thread_id=200,
            run_id=200,
            openai_message_id="msg-other-class",
            output_index=0,
            metadata=_migration_metadata(),
        )
        await session.commit()

    async with db.async_session() as session:
        messages = await migration._fetch_messages(session)

    assert sorted(message.message_id for message in messages) == [
        "msg-migrated",
        "msg-other-class",
    ]
    assert {
        (message.thread.class_id, message.thread.thread_id) for message in messages
    } == {
        (1, "thread-100"),
        (2, "thread-200"),
    }


async def test_migrate_attaches_files_by_tool_type(db, monkeypatch):
    """A single attachment can carry both tools; each maps to its own association."""
    async with db.async_session() as session:
        await _seed_vector_store(session, id_=500, class_id=1)
        await _seed_thread(
            session,
            class_id=1,
            assistant_id=10,
            thread_id=100,
            vector_store_id=500,
        )
        await _seed_message(
            session,
            id_=1001,
            thread_id=100,
            run_id=100,
            openai_message_id="msg-with-attachments",
            output_index=0,
            metadata=_migration_metadata(),
        )
        await _seed_file(session, id_=50, file_id="file-search")
        await _seed_file(session, id_=51, file_id="file-both")
        await _add_file_to_vector_store(session, file_object_id=50, vector_store_id=500)
        await _add_file_to_vector_store(session, file_object_id=51, vector_store_id=500)
        await _add_code_interpreter_file_to_thread(
            session, file_object_id=51, thread_id=100
        )
        await session.commit()

    fake_client = _fake_openai_client(
        {
            "thread-100": [
                _openai_message(
                    "msg-with-attachments",
                    [
                        _attachment("file-search", ["file_search"]),
                        _attachment("file-both", ["file_search", "code_interpreter"]),
                    ],
                )
            ],
        }
    )

    _patch_openai_client(monkeypatch, fake_client, expected_class_id=1)

    async with db.async_session() as session:
        await migration.migrate_message_attachments(session)

    async with db.async_session() as session:
        file_search = await _attachment_pairs(
            session, migration.models.file_search_attachment_association
        )
        code_interpreter = await _attachment_pairs(
            session, migration.models.code_interpreter_attachment_association
        )
        message = await session.get(models.Message, 1001)

    assert file_search == [(1001, 50), (1001, 51)]
    assert code_interpreter == [(1001, 51)]
    assert _attachments_migration_state(message) == "complete"


async def test_migrate_skips_attachment_when_local_file_missing(db, monkeypatch):
    """A referenced File that doesn't exist locally is skipped (not created), and the
    message is still marked complete."""
    async with db.async_session() as session:
        await _seed_vector_store(session, id_=500, class_id=1)
        await _seed_thread(
            session,
            class_id=1,
            assistant_id=10,
            thread_id=100,
            vector_store_id=500,
        )
        await _seed_message(
            session,
            id_=1001,
            thread_id=100,
            run_id=100,
            openai_message_id="msg-missing-file",
            output_index=0,
            metadata=_migration_metadata(),
        )
        # Only one of the two referenced files exists locally.
        await _seed_file(session, id_=50, file_id="file-present")
        await _add_file_to_vector_store(session, file_object_id=50, vector_store_id=500)
        await session.commit()

    fake_client = _fake_openai_client(
        {
            "thread-100": [
                _openai_message(
                    "msg-missing-file",
                    [
                        _attachment("file-present", ["file_search"]),
                        _attachment("file-absent", ["code_interpreter"]),
                    ],
                )
            ],
        }
    )

    _patch_openai_client(monkeypatch, fake_client)

    async with db.async_session() as session:
        await migration.migrate_message_attachments(session)

    async with db.async_session() as session:
        file_search = await _attachment_pairs(
            session, migration.models.file_search_attachment_association
        )
        code_interpreter = await _attachment_pairs(
            session, migration.models.code_interpreter_attachment_association
        )
        files = await _all(session, models.File)
        message = await session.get(models.Message, 1001)

    # Only the present file got attached; the missing one was skipped, and no new
    # File was created for it.
    assert file_search == [(1001, 50)]
    assert code_interpreter == []
    assert [file.file_id for file in files] == ["file-present"]
    assert _attachments_migration_state(message) == "complete"


async def test_migrate_skips_file_not_available_to_thread_tool(db, monkeypatch):
    async with db.async_session() as session:
        await _seed_vector_store(session, id_=500, class_id=1)
        await _seed_thread(
            session,
            class_id=1,
            assistant_id=10,
            thread_id=100,
            vector_store_id=500,
        )
        await _seed_message(
            session,
            id_=1001,
            thread_id=100,
            run_id=100,
            openai_message_id="msg-unavailable-file",
            output_index=0,
            metadata=_migration_metadata(),
        )
        await _seed_file(session, id_=50, file_id="file-search", class_id=1)
        await _seed_file(session, id_=51, file_id="file-ci", class_id=1)
        await session.commit()

    fake_client = _fake_openai_client(
        {
            "thread-100": [
                _openai_message(
                    "msg-unavailable-file",
                    [
                        _attachment("file-search", ["file_search"]),
                        _attachment("file-ci", ["code_interpreter"]),
                    ],
                )
            ],
        }
    )

    _patch_openai_client(monkeypatch, fake_client)

    async with db.async_session() as session:
        await migration.migrate_message_attachments(session)

    async with db.async_session() as session:
        file_search = await _attachment_pairs(
            session, migration.models.file_search_attachment_association
        )
        code_interpreter = await _attachment_pairs(
            session, migration.models.code_interpreter_attachment_association
        )
        message = await session.get(models.Message, 1001)

    assert file_search == []
    assert code_interpreter == []
    assert _attachments_migration_state(message) == "complete"


async def test_migrate_message_attachments_continues_after_message_failure(
    db, monkeypatch
):
    async with db.async_session() as session:
        await _seed_thread(session, class_id=1, assistant_id=10, thread_id=100)
        await _seed_vector_store(session, id_=500, class_id=1)
        await _seed_thread(
            session,
            class_id=1,
            assistant_id=10,
            thread_id=200,
            vector_store_id=500,
        )
        await _seed_message(
            session,
            id_=1001,
            thread_id=100,
            run_id=100,
            openai_message_id="msg-fails",
            output_index=0,
            metadata=_migration_metadata(),
        )
        await _seed_message(
            session,
            id_=2001,
            thread_id=200,
            run_id=200,
            openai_message_id="msg-succeeds",
            output_index=0,
            metadata=_migration_metadata(),
        )
        await _seed_file(session, id_=50, file_id="file-ok")
        await _add_file_to_vector_store(session, file_object_id=50, vector_store_id=500)
        await session.commit()

    fake_client = _fake_openai_client(
        {
            "thread-100": RuntimeError("upstream failure"),
            "thread-200": [
                _openai_message(
                    "msg-succeeds",
                    [_attachment("file-ok", ["file_search"])],
                )
            ],
        }
    )

    _patch_openai_client(monkeypatch, fake_client, expected_class_id=1)

    async with db.async_session() as session:
        await migration.migrate_message_attachments(session)

    async with db.async_session() as session:
        file_search = await _attachment_pairs(
            session, migration.models.file_search_attachment_association
        )
        failed_message = await session.get(models.Message, 1001)
        ok_message = await session.get(models.Message, 2001)

    # Only the successful message got an attachment and a completion flag.
    assert file_search == [(2001, 50)]
    assert _attachments_migration_state(failed_message) is None
    assert _attachments_migration_state(ok_message) == "complete"


async def test_migrate_is_idempotent(db, monkeypatch):
    async with db.async_session() as session:
        await _seed_vector_store(session, id_=500, class_id=1)
        await _seed_thread(
            session,
            class_id=1,
            assistant_id=10,
            thread_id=100,
            vector_store_id=500,
        )
        await _seed_message(
            session,
            id_=1001,
            thread_id=100,
            run_id=100,
            openai_message_id="msg-with-attachments",
            output_index=0,
            metadata=_migration_metadata(),
        )
        await _seed_file(session, id_=50, file_id="file-search")
        await _add_file_to_vector_store(session, file_object_id=50, vector_store_id=500)
        await session.commit()

    fake_client = _fake_openai_client(
        {
            "thread-100": [
                _openai_message(
                    "msg-with-attachments",
                    [_attachment("file-search", ["file_search"])],
                )
            ],
        }
    )

    _patch_openai_client(monkeypatch, fake_client)

    async with db.async_session() as session:
        await migration.migrate_message_attachments(session)

    # The second run should pick up no work (metadata flag set) and not duplicate
    # the association row.
    async with db.async_session() as session:
        remaining = await migration._fetch_messages(session)
    assert remaining == []

    async with db.async_session() as session:
        await migration.migrate_message_attachments(session)

    async with db.async_session() as session:
        file_search = await _attachment_pairs(
            session, migration.models.file_search_attachment_association
        )
    assert file_search == [(1001, 50)]


async def test_migrate_skips_attachment_without_tools(db, monkeypatch):
    async with db.async_session() as session:
        await _seed_thread(session, class_id=1, assistant_id=10, thread_id=100)
        await _seed_message(
            session,
            id_=1001,
            thread_id=100,
            run_id=100,
            openai_message_id="msg-no-tools",
            output_index=0,
            metadata=_migration_metadata(),
        )
        await _seed_file(session, id_=50, file_id="file-no-tools", class_id=1)
        await session.commit()

    fake_client = _fake_openai_client(
        {
            "thread-100": [
                _openai_message(
                    "msg-no-tools",
                    [_attachment("file-no-tools", [])],
                )
            ],
        }
    )

    _patch_openai_client(monkeypatch, fake_client)

    async with db.async_session() as session:
        await migration.migrate_message_attachments(session)

    async with db.async_session() as session:
        file_search = await _attachment_pairs(
            session, migration.models.file_search_attachment_association
        )
        code_interpreter = await _attachment_pairs(
            session, migration.models.code_interpreter_attachment_association
        )
        message = await session.get(models.Message, 1001)

    assert file_search == []
    assert code_interpreter == []
    # The attachment was skipped, but the message is still marked complete so the
    # migration doesn't keep reprocessing it.
    assert _attachments_migration_state(message) == "complete"
