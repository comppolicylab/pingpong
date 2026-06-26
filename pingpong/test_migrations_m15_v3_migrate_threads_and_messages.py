from datetime import datetime
from types import SimpleNamespace
from typing import Any, Literal

import pytest
from glowplug import DbDriver
from openai.types.beta.threads import Message, Run, RunStatus
from openai.types.beta.threads.run import IncompleteDetails, LastError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pingpong import models, schemas
from pingpong.migrations import m15_v3_migrate_threads_and_messages as migration

pytestmark = pytest.mark.asyncio


def _generate_openai_message(
    msg_id: str,
    *,
    role: Literal["user", "assistant"],
    created_at: int,
    run_id: str | None = None,
    status: Literal["in_progress", "incomplete", "completed"] | None = "completed",
    completed_at: int | None = None,
    user_id: str | int | None = None,
    metadata: dict | None = None,
) -> Message:
    if metadata is None:
        metadata = {}
        if user_id is not None:
            metadata["user_id"] = str(user_id)
    data: dict[str, Any] = {
        "id": msg_id,
        "object": "thread.message",
        "thread_id": "sample_openai_thread_id",
        "role": role,
        "status": status,
        "created_at": created_at,
        "completed_at": completed_at,
        "run_id": run_id,
        "assistant_id": None,
        "attachments": None,
        "content": [],
        "incomplete_at": None,
        "incomplete_details": None,
        "metadata": metadata,
    }
    if status is None:
        return Message.model_construct(**data)
    return Message(**data)


def _generate_openai_run(
    run_id: str,
    *,
    status: RunStatus = "completed",
    created_at: int = 100,
    started_at: int | None = None,
    completed_at: int | None = None,
    failed_at: int | None = None,
    cancelled_at: int | None = None,
    expires_at: int | None = None,
    last_error: LastError | None = None,
    incomplete_details: IncompleteDetails | None = None,
) -> Run:
    return Run(
        id=run_id,
        object="thread.run",
        thread_id="sample_openai_thread_id",
        assistant_id="asst_openai",
        status=status,
        created_at=created_at,
        started_at=started_at,
        completed_at=completed_at,
        failed_at=failed_at,
        cancelled_at=cancelled_at,
        expires_at=expires_at,
        last_error=last_error,
        incomplete_details=incomplete_details,
        instructions="",
        model="gpt-test",
        tools=[],
        parallel_tool_calls=True,
        metadata={},
        required_action=None,
        response_format="auto",
        tool_choice="auto",
        truncation_strategy=None,
        usage=None,
        max_completion_tokens=None,
        max_prompt_tokens=None,
        temperature=None,
        top_p=None,
    )


class _FakeOpenAIMessages:
    def __init__(
        self,
        messages: list[Message],
        pages: list[list[Message]] | None = None,
        fail_thread_ids: set[str] | None = None,
    ) -> None:
        self._messages = messages
        self._pages = pages
        self._fail_thread_ids = fail_thread_ids or set()
        self.calls: list[SimpleNamespace] = []

    async def list(
        self, *, thread_id: str, order: str, after: str | None
    ) -> SimpleNamespace:
        self.calls.append(
            SimpleNamespace(thread_id=thread_id, order=order, after=after)
        )
        if thread_id in self._fail_thread_ids:
            raise RuntimeError(f"failed to fetch messages for thread {thread_id}")
        if self._pages is not None:
            index = len(self.calls) - 1
            return SimpleNamespace(
                data=list(self._pages[index]),
                has_more=index < len(self._pages) - 1,
            )
        return SimpleNamespace(data=list(self._messages), has_more=False)


class _FakeOpenAIRuns:
    def __init__(self, runs: dict[str, Run]) -> None:
        self._runs = runs
        self.retrieved: list[str] = []

    async def retrieve(self, run_id: str, *, thread_id: str) -> Run:
        self.retrieved.append(run_id)
        return self._runs[run_id]


class FakeOpenAIClient:
    def __init__(
        self,
        messages: list[Message],
        runs: dict[str, Run],
        *,
        message_pages: list[list[Message]] | None = None,
        fail_thread_ids: set[str] | None = None,
    ) -> None:
        self.beta = SimpleNamespace(
            threads=SimpleNamespace(
                messages=_FakeOpenAIMessages(
                    messages, pages=message_pages, fail_thread_ids=fail_thread_ids
                ),
                runs=_FakeOpenAIRuns(runs),
            )
        )

    @property
    def retrieved_run_ids(self) -> list[str]:
        return self.beta.threads.runs.retrieved

    @property
    def message_calls(self) -> list[SimpleNamespace]:
        return self.beta.threads.messages.calls


def _patch_client(
    monkeypatch: pytest.MonkeyPatch,
    client: FakeOpenAIClient,
    *,
    fail_class_ids: set[int] | None = None,
) -> None:
    fail_class_ids = fail_class_ids or set()

    async def fake_get_openai_client_by_class_id(
        session: AsyncSession, class_id: int
    ) -> FakeOpenAIClient:
        if class_id in fail_class_ids:
            raise RuntimeError(f"no client for class {class_id}")
        return client

    monkeypatch.setattr(
        migration, "get_openai_client_by_class_id", fake_get_openai_client_by_class_id
    )


async def _generate_local_thread(
    session: AsyncSession,
    *,
    thread_pk: int = 1,
    class_id: int = 1,
    assistant_id: int = 1,
    creator_id: int = 7,
    version: int = 2,
    interaction_mode: schemas.InteractionMode = schemas.InteractionMode.CHAT,
    openai_thread_id: str = "sample_openai_thread_id",
) -> models.Thread:
    class_ = await session.get(models.Class, class_id)
    if class_ is None:
        class_ = models.Class(id=class_id, name="Class", api_key="sk-test")
        session.add(class_)
    if await session.get(models.User, creator_id) is None:
        session.add(models.User(id=creator_id, email=f"u{creator_id}@example.com"))
    await session.flush()

    assistant = await session.get(models.Assistant, assistant_id)
    if assistant is None:
        assistant = models.Assistant(
            id=assistant_id,
            name="Assistant",
            class_id=class_id,
            creator_id=creator_id,
            version=3,
            interaction_mode=schemas.InteractionMode.CHAT,
            instructions="Be helpful.",
            model="gpt-asst",
            temperature=0.5,
            reasoning_effort=2,
            verbosity=1,
            tools="[]",
        )
        session.add(assistant)
        await session.flush()

    thread = models.Thread(
        id=thread_pk,
        thread_id=openai_thread_id,
        class_id=class_id,
        assistant_id=assistant_id,
        version=version,
        interaction_mode=interaction_mode,
        instructions="Thread instructions.",
        tools_available="[]",
    )
    session.add(thread)
    await session.flush()
    return thread


def _naive_dt(timestamp: int) -> datetime:
    # SQLite doesn't store tzinfo (i think?) so we have to do this for comparisons
    return migration._require_dt(timestamp).replace(tzinfo=None)


async def _all_runs(session: AsyncSession, thread_pk: int) -> list[models.Run]:
    result = await session.execute(
        select(models.Run)
        .where(models.Run.thread_id == thread_pk)
        .order_by(models.Run.id)
    )
    return list(result.scalars())


async def _all_messages(session: AsyncSession, thread_pk: int) -> list[models.Message]:
    result = await session.execute(
        select(models.Message)
        .where(models.Message.thread_id == thread_pk)
        .order_by(models.Message.output_index)
    )
    return list(result.scalars())


async def test_single_turn_creates_run_and_messages(
    db: DbDriver, monkeypatch: pytest.MonkeyPatch
) -> None:
    messages = [
        _generate_openai_message("msg_user", role="user", created_at=100, user_id=7),
        _generate_openai_message(
            "msg_asst", role="assistant", created_at=110, run_id="run_1"
        ),
    ]
    runs = {
        "run_1": _generate_openai_run(
            "run_1", status="completed", started_at=105, completed_at=120
        )
    }
    client = FakeOpenAIClient(messages, runs)
    _patch_client(monkeypatch, client)

    async with db.async_session() as session:
        await _generate_local_thread(session)
        await session.commit()

    async with db.async_session() as session:
        await migration.migrate_threads_and_messages_to_v3(session)

    async with db.async_session() as session:
        runs_local = await _all_runs(session, 1)
        msgs_local = await _all_messages(session, 1)

        assert len(runs_local) == 1
        run = runs_local[0]
        assert run.run_id == "run_1"
        assert run.status == schemas.RunStatus.COMPLETED

        assert run.created == _naive_dt(100)
        assert run.completed == _naive_dt(120)

        assert run.assistant_id == 1
        assert run.creator_id == 7
        assert run.model == "gpt-asst"
        assert run.instructions == "Thread instructions."

        assert [m.message_id for m in msgs_local] == ["msg_user", "msg_asst"]
        assert [m.output_index for m in msgs_local] == [0, 1]
        user_msg, asst_msg = msgs_local
        assert user_msg.role == schemas.MessageRole.USER
        assert user_msg.user_id == 7
        assert user_msg.assistant_id is None
        assert asst_msg.role == schemas.MessageRole.ASSISTANT
        assert asst_msg.assistant_id == 1
        assert asst_msg.user_id is None
        expected_metadata = {
            "assistants_to_responses_api_thread_migration": {"message": "complete"}
        }
        assert user_msg.message_metadata == expected_metadata
        assert asst_msg.message_metadata == expected_metadata
        assert user_msg.run_id == run.id and asst_msg.run_id == run.id


async def test_orphan_user_message_gets_placeholder_run(
    db: DbDriver, monkeypatch: pytest.MonkeyPatch
) -> None:
    messages = [
        _generate_openai_message("msg_user", role="user", created_at=100, user_id=7)
    ]
    client = FakeOpenAIClient(messages, {})
    _patch_client(monkeypatch, client)

    async with db.async_session() as session:
        await _generate_local_thread(session)
        await session.commit()

    async with db.async_session() as session:
        await migration.migrate_threads_and_messages_to_v3(session)

    async with db.async_session() as session:
        runs_local = await _all_runs(session, 1)
        msgs_local = await _all_messages(session, 1)

        assert len(runs_local) == 1
        assert runs_local[0].run_id is None
        assert runs_local[0].status == schemas.RunStatus.INCOMPLETE
        assert runs_local[0].created == _naive_dt(100)
        assert runs_local[0].completed is None

        assert len(msgs_local) == 1
        assert msgs_local[0].message_id == "msg_user"
        assert msgs_local[0].run_id == runs_local[0].id


async def test_consecutive_user_messages_split_orphan_and_owned_turns(
    db: DbDriver, monkeypatch: pytest.MonkeyPatch
) -> None:
    messages = [
        _generate_openai_message("msg_u1", role="user", created_at=100, user_id=7),
        _generate_openai_message("msg_u2", role="user", created_at=110, user_id=7),
        _generate_openai_message(
            "msg_asst", role="assistant", created_at=120, run_id="run_1"
        ),
    ]
    runs = {
        "run_1": _generate_openai_run(
            "run_1", status="completed", started_at=115, completed_at=130
        )
    }
    client = FakeOpenAIClient(messages, runs)
    _patch_client(monkeypatch, client)

    async with db.async_session() as session:
        await _generate_local_thread(session)
        await session.commit()

    async with db.async_session() as session:
        await migration.migrate_threads_and_messages_to_v3(session)

    async with db.async_session() as session:
        runs_local = await _all_runs(session, 1)
        msgs_local = await _all_messages(session, 1)

        assert len(runs_local) == 2
        orphan_run, owned_run = runs_local
        assert orphan_run.run_id is None
        assert orphan_run.created == _naive_dt(100)
        assert owned_run.run_id == "run_1"
        assert owned_run.created == _naive_dt(110)

        assert [m.message_id for m in msgs_local] == ["msg_u1", "msg_u2", "msg_asst"]
        assert [m.output_index for m in msgs_local] == [0, 1, 2]
        assert msgs_local[0].run_id == orphan_run.id
        assert {m.run_id for m in msgs_local[1:]} == {owned_run.id}


async def test_consecutive_assistant_messages_collapse_into_one_run(
    db: DbDriver, monkeypatch: pytest.MonkeyPatch
) -> None:
    messages = [
        _generate_openai_message("msg_user", role="user", created_at=100, user_id=7),
        _generate_openai_message(
            "msg_a1", role="assistant", created_at=110, run_id="run_1"
        ),
        _generate_openai_message(
            "msg_a2", role="assistant", created_at=120, run_id="run_2"
        ),
    ]
    runs = {
        "run_1": _generate_openai_run(
            "run_1", status="completed", started_at=105, completed_at=115
        ),
        "run_2": _generate_openai_run(
            "run_2", status="completed", started_at=116, completed_at=125
        ),
    }
    client = FakeOpenAIClient(messages, runs)
    _patch_client(monkeypatch, client)

    async with db.async_session() as session:
        await _generate_local_thread(session)
        await session.commit()

    async with db.async_session() as session:
        await migration.migrate_threads_and_messages_to_v3(session)

    async with db.async_session() as session:
        runs_local = await _all_runs(session, 1)
        msgs_local = await _all_messages(session, 1)

        assert len(runs_local) == 1
        assert runs_local[0].run_id == "run_2"

        assert runs_local[0].created == _naive_dt(100)
        assert runs_local[0].completed == _naive_dt(125)

        assert [m.message_id for m in msgs_local] == ["msg_user", "msg_a1", "msg_a2"]
        assert [m.output_index for m in msgs_local] == [0, 1, 2]
        assert {m.run_id for m in msgs_local} == {runs_local[0].id}


async def test_existing_placeholder_run_is_upgraded_when_reply_arrives(
    db: DbDriver, monkeypatch: pytest.MonkeyPatch
) -> None:
    first_client = FakeOpenAIClient(
        [_generate_openai_message("msg_user", role="user", created_at=100, user_id=7)],
        {},
    )
    _patch_client(monkeypatch, first_client)

    async with db.async_session() as session:
        await _generate_local_thread(session)
        await session.commit()

    async with db.async_session() as session:
        await migration.migrate_threads_and_messages_to_v3(session)

    async with db.async_session() as session:
        placeholder_run = (await _all_runs(session, 1))[0]
        placeholder_run_id = placeholder_run.id
        assert placeholder_run.run_id is None

    messages = [
        _generate_openai_message("msg_user", role="user", created_at=100, user_id=7),
        _generate_openai_message(
            "msg_asst", role="assistant", created_at=110, run_id="run_1"
        ),
    ]
    second_client = FakeOpenAIClient(
        messages,
        {"run_1": _generate_openai_run("run_1", status="completed", completed_at=120)},
    )
    _patch_client(monkeypatch, second_client)

    async with db.async_session() as session:
        await migration.migrate_threads_and_messages_to_v3(session)

    async with db.async_session() as session:
        runs_local = await _all_runs(session, 1)
        msgs_local = await _all_messages(session, 1)

        assert len(runs_local) == 1
        assert runs_local[0].id == placeholder_run_id
        assert runs_local[0].run_id == "run_1"
        assert runs_local[0].status == schemas.RunStatus.COMPLETED
        assert [m.message_id for m in msgs_local] == ["msg_user", "msg_asst"]
        assert {m.run_id for m in msgs_local} == {placeholder_run_id}


async def test_rerun_is_idempotent(
    db: DbDriver, monkeypatch: pytest.MonkeyPatch
) -> None:
    messages = [
        _generate_openai_message("msg_user", role="user", created_at=100, user_id=7),
        _generate_openai_message(
            "msg_asst", role="assistant", created_at=110, run_id="run_1"
        ),
    ]
    runs = {
        "run_1": _generate_openai_run(
            "run_1", status="completed", started_at=105, completed_at=120
        )
    }
    client = FakeOpenAIClient(messages, runs)
    _patch_client(monkeypatch, client)

    async with db.async_session() as session:
        await _generate_local_thread(session)
        await session.commit()

    for _ in range(2):
        async with db.async_session() as session:
            await migration.migrate_threads_and_messages_to_v3(session)
            await session.commit()

    async with db.async_session() as session:
        runs_local = await _all_runs(session, 1)
        msgs_local = await _all_messages(session, 1)
        assert len(runs_local) == 1
        assert [m.message_id for m in msgs_local] == ["msg_user", "msg_asst"]
        assert [m.output_index for m in msgs_local] == [0, 1]


async def test_existing_rows_are_updated_on_rerun(
    db: DbDriver, monkeypatch: pytest.MonkeyPatch
) -> None:
    messages = [
        _generate_openai_message(
            "msg_user", role="user", created_at=100, user_id=7, status="in_progress"
        ),
        _generate_openai_message(
            "msg_asst",
            role="assistant",
            created_at=110,
            run_id="run_1",
            status="in_progress",
        ),
    ]
    client = FakeOpenAIClient(
        messages,
        {"run_1": _generate_openai_run("run_1", status="queued", started_at=105)},
    )
    _patch_client(monkeypatch, client)

    async with db.async_session() as session:
        await _generate_local_thread(session)
        await session.commit()

    async with db.async_session() as session:
        await migration.migrate_threads_and_messages_to_v3(session)

    updated_messages = [
        _generate_openai_message(
            "msg_user",
            role="user",
            created_at=100,
            completed_at=101,
            user_id=7,
            status="completed",
        ),
        _generate_openai_message(
            "msg_asst",
            role="assistant",
            created_at=110,
            completed_at=111,
            run_id="run_1",
            status="completed",
        ),
    ]
    updated_client = FakeOpenAIClient(
        updated_messages,
        {"run_1": _generate_openai_run("run_1", status="completed", completed_at=120)},
    )
    _patch_client(monkeypatch, updated_client)

    async with db.async_session() as session:
        await migration.migrate_threads_and_messages_to_v3(session)

    async with db.async_session() as session:
        runs_local = await _all_runs(session, 1)
        msgs_local = await _all_messages(session, 1)

        assert len(runs_local) == 1
        assert runs_local[0].status == schemas.RunStatus.COMPLETED
        assert runs_local[0].completed == _naive_dt(120)
        assert len(msgs_local) == 2
        assert {m.message_status for m in msgs_local} == {
            schemas.MessageStatus.COMPLETED
        }
        assert [m.completed for m in msgs_local] == [_naive_dt(101), _naive_dt(111)]


async def test_none_message_status_defaults_to_completed(
    db: DbDriver, monkeypatch: pytest.MonkeyPatch
) -> None:
    messages = [
        _generate_openai_message(
            "msg_user", role="user", created_at=100, status=None, user_id=7
        ),
        _generate_openai_message(
            "msg_asst",
            role="assistant",
            created_at=110,
            run_id="run_1",
            status=None,
        ),
    ]
    client = FakeOpenAIClient(
        messages,
        {"run_1": _generate_openai_run("run_1", status="completed", completed_at=120)},
    )
    _patch_client(monkeypatch, client)

    async with db.async_session() as session:
        await _generate_local_thread(session)
        await session.commit()

    async with db.async_session() as session:
        await migration.migrate_threads_and_messages_to_v3(session)

    async with db.async_session() as session:
        msgs_local = await _all_messages(session, 1)
        assert [m.message_status for m in msgs_local] == [
            schemas.MessageStatus.COMPLETED,
            schemas.MessageStatus.COMPLETED,
        ]


async def test_stale_local_message_is_deleted(
    db: DbDriver, monkeypatch: pytest.MonkeyPatch
) -> None:
    messages = [
        _generate_openai_message("msg_user", role="user", created_at=100, user_id=7)
    ]
    client = FakeOpenAIClient(messages, {})
    _patch_client(monkeypatch, client)

    async with db.async_session() as session:
        thread = await _generate_local_thread(session)
        stale_run = models.Run(
            thread_id=thread.id,
            assistant_id=1,
            status=schemas.RunStatus.COMPLETED,
        )
        session.add(stale_run)
        await session.flush()
        session.add(
            models.Message(
                message_id="msg_gone",
                thread_id=thread.id,
                run_id=stale_run.id,
                role=schemas.MessageRole.ASSISTANT,
                message_status=schemas.MessageStatus.COMPLETED,
                output_index=0,
            )
        )
        await session.commit()

    async with db.async_session() as session:
        await migration.migrate_threads_and_messages_to_v3(session)

    async with db.async_session() as session:
        msgs_local = await _all_messages(session, 1)
        assert [m.message_id for m in msgs_local] == ["msg_user"]


async def test_empty_openai_fetch_deletes_all_local_messages_and_runs(
    db: DbDriver, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = FakeOpenAIClient([], {})
    _patch_client(monkeypatch, client)

    async with db.async_session() as session:
        thread = await _generate_local_thread(session)
        local_run = models.Run(
            thread_id=thread.id,
            assistant_id=1,
            status=schemas.RunStatus.COMPLETED,
        )
        session.add(local_run)
        await session.flush()
        session.add(
            models.Message(
                message_id="msg_gone",
                thread_id=thread.id,
                run_id=local_run.id,
                role=schemas.MessageRole.ASSISTANT,
                message_status=schemas.MessageStatus.COMPLETED,
                output_index=0,
            )
        )
        await session.commit()

    async with db.async_session() as session:
        await migration.migrate_threads_and_messages_to_v3(session)

    async with db.async_session() as session:
        assert await _all_messages(session, 1) == []
        assert await _all_runs(session, 1) == []


async def test_orphan_run_is_pruned(
    db: DbDriver, monkeypatch: pytest.MonkeyPatch
) -> None:
    # A local run that no surviving message points to should be deleted.
    messages = [
        _generate_openai_message("msg_user", role="user", created_at=100, user_id=7),
        _generate_openai_message(
            "msg_asst", role="assistant", created_at=110, run_id="run_1"
        ),
    ]
    runs = {
        "run_1": _generate_openai_run("run_1", status="completed", completed_at=120)
    }
    client = FakeOpenAIClient(messages, runs)
    _patch_client(monkeypatch, client)

    async with db.async_session() as session:
        thread = await _generate_local_thread(session)
        orphan_run = models.Run(
            thread_id=thread.id,
            assistant_id=1,
            status=schemas.RunStatus.INCOMPLETE,
        )
        session.add(orphan_run)
        await session.commit()
        orphan_run_id = orphan_run.id

    async with db.async_session() as session:
        await migration.migrate_threads_and_messages_to_v3(session)

    async with db.async_session() as session:
        assert await session.get(models.Run, orphan_run_id) is None
        # The real run survives.
        runs_local = await _all_runs(session, 1)
        assert [r.run_id for r in runs_local] == ["run_1"]


async def test_paginated_openai_messages_are_all_migrated(
    db: DbDriver, monkeypatch: pytest.MonkeyPatch
) -> None:
    page_1 = [
        _generate_openai_message("msg_u1", role="user", created_at=100, user_id=7),
        _generate_openai_message(
            "msg_a1", role="assistant", created_at=110, run_id="run_1"
        ),
    ]
    page_2 = [
        _generate_openai_message("msg_u2", role="user", created_at=120, user_id=7),
        _generate_openai_message(
            "msg_a2", role="assistant", created_at=130, run_id="run_2"
        ),
    ]
    runs = {
        "run_1": _generate_openai_run("run_1", status="completed", completed_at=115),
        "run_2": _generate_openai_run("run_2", status="completed", completed_at=135),
    }
    client = FakeOpenAIClient([], runs, message_pages=[page_1, page_2])
    _patch_client(monkeypatch, client)

    async with db.async_session() as session:
        await _generate_local_thread(session)
        await session.commit()

    async with db.async_session() as session:
        await migration.migrate_threads_and_messages_to_v3(session)

    async with db.async_session() as session:
        runs_local = await _all_runs(session, 1)
        msgs_local = await _all_messages(session, 1)

        assert len(client.message_calls) == 2
        assert client.message_calls[1].after == "msg_a1"
        assert [r.run_id for r in runs_local] == ["run_1", "run_2"]
        assert [m.message_id for m in msgs_local] == [
            "msg_u1",
            "msg_a1",
            "msg_u2",
            "msg_a2",
        ]
        assert [m.output_index for m in msgs_local] == [0, 1, 2, 3]


async def test_failed_run_records_error_fields(
    db: DbDriver, monkeypatch: pytest.MonkeyPatch
) -> None:
    messages = [
        _generate_openai_message("msg_user", role="user", created_at=100, user_id=7),
        _generate_openai_message(
            "msg_asst", role="assistant", created_at=110, run_id="run_1"
        ),
    ]
    failed_run = _generate_openai_run(
        "run_1",
        status="failed",
        started_at=105,
        failed_at=118,
        last_error=LastError(code="rate_limit_exceeded", message="slow down"),
    )
    client = FakeOpenAIClient(messages, {"run_1": failed_run})
    _patch_client(monkeypatch, client)

    async with db.async_session() as session:
        await _generate_local_thread(session)
        await session.commit()

    async with db.async_session() as session:
        await migration.migrate_threads_and_messages_to_v3(session)

    async with db.async_session() as session:
        runs_local = await _all_runs(session, 1)
        assert len(runs_local) == 1
        run = runs_local[0]
        assert run.status == schemas.RunStatus.FAILED
        assert run.error_code == "rate_limit_exceeded"
        assert run.error_message == "slow down"
        # falls back to failed_at for completed timestamp.
        assert run.completed == _naive_dt(118)


async def test_cancelled_run_status_maps_to_incomplete(
    db: DbDriver, monkeypatch: pytest.MonkeyPatch
) -> None:
    # "cancelled" has no RunStatus member; it must be mapped, not written raw.
    messages = [
        _generate_openai_message("msg_user", role="user", created_at=100, user_id=7),
        _generate_openai_message(
            "msg_asst", role="assistant", created_at=110, run_id="run_1"
        ),
    ]
    cancelled_run = _generate_openai_run("run_1", status="cancelled", cancelled_at=118)
    client = FakeOpenAIClient(messages, {"run_1": cancelled_run})
    _patch_client(monkeypatch, client)

    async with db.async_session() as session:
        await _generate_local_thread(session)
        await session.commit()

    async with db.async_session() as session:
        await migration.migrate_threads_and_messages_to_v3(session)

    async with db.async_session() as session:
        runs_local = await _all_runs(session, 1)
        assert len(runs_local) == 1
        assert runs_local[0].status == schemas.RunStatus.INCOMPLETE
        # cancelled_at supplies the terminal completed timestamp.
        assert runs_local[0].completed == _naive_dt(118)


async def test_non_chat_and_v1_threads_are_skipped(
    db: DbDriver, monkeypatch: pytest.MonkeyPatch
) -> None:
    messages = [
        _generate_openai_message("msg_user", role="user", created_at=100, user_id=7)
    ]
    client = FakeOpenAIClient(messages, {})
    _patch_client(monkeypatch, client)

    async with db.async_session() as session:
        # v1 chat thread and a v2 voice thread: neither should be migrated.
        await _generate_local_thread(
            session, thread_pk=1, version=1, openai_thread_id="th_v1"
        )
        await _generate_local_thread(
            session,
            thread_pk=2,
            version=2,
            interaction_mode=schemas.InteractionMode.VOICE,
            openai_thread_id="th_voice",
        )
        await session.commit()

    async with db.async_session() as session:
        await migration.migrate_threads_and_messages_to_v3(session)

    async with db.async_session() as session:
        assert await _all_messages(session, 1) == []
        assert await _all_messages(session, 2) == []
        # No OpenAI fetch happened at all (no eligible assistants).
        assert client.message_calls == []
        assert client.retrieved_run_ids == []


async def test_class_without_openai_client_is_skipped(
    db: DbDriver, monkeypatch: pytest.MonkeyPatch
) -> None:
    messages = [
        _generate_openai_message("msg_user", role="user", created_at=100, user_id=7),
        _generate_openai_message(
            "msg_asst", role="assistant", created_at=110, run_id="run_1"
        ),
    ]
    runs = {"run_1": _generate_openai_run("run_1", completed_at=120)}
    client = FakeOpenAIClient(messages, runs)
    _patch_client(monkeypatch, client, fail_class_ids={1})

    async with db.async_session() as session:
        await _generate_local_thread(session)
        await session.commit()

    async with db.async_session() as session:
        # Should not raise; the class is skipped on client-resolution failure.
        await migration.migrate_threads_and_messages_to_v3(session)

    async with db.async_session() as session:
        assert await _all_messages(session, 1) == []
        assert await _all_runs(session, 1) == []


async def test_failed_thread_rolls_back_and_successful_threads_commit(
    db: DbDriver, monkeypatch: pytest.MonkeyPatch
) -> None:
    messages = [
        _generate_openai_message("msg_user", role="user", created_at=100, user_id=7),
        _generate_openai_message(
            "msg_asst", role="assistant", created_at=110, run_id="run_1"
        ),
    ]
    runs = {"run_1": _generate_openai_run("run_1", completed_at=120)}
    client = FakeOpenAIClient(messages, runs, fail_thread_ids={"thread_fail"})
    _patch_client(monkeypatch, client)

    async with db.async_session() as session:
        await _generate_local_thread(session, thread_pk=1, openai_thread_id="thread_ok")
        await _generate_local_thread(
            session, thread_pk=2, openai_thread_id="thread_fail"
        )
        await session.commit()

    async with db.async_session() as session:
        with pytest.raises(RuntimeError, match="Failed to migrate 1 thread"):
            await migration.migrate_threads_and_messages_to_v3(session)

    async with db.async_session() as session:
        assert [m.message_id for m in await _all_messages(session, 1)] == [
            "msg_user",
            "msg_asst",
        ]
        assert len(await _all_runs(session, 1)) == 1
        assert await _all_messages(session, 2) == []
        assert await _all_runs(session, 2) == []


@pytest.mark.parametrize(
    "openai_status, expected",
    [
        # Pass-through: shares the RunStatus name.
        ("queued", schemas.RunStatus.QUEUED),
        ("pending", schemas.RunStatus.PENDING),
        ("in_progress", schemas.RunStatus.IN_PROGRESS),
        ("completed", schemas.RunStatus.COMPLETED),
        ("failed", schemas.RunStatus.FAILED),
        ("incomplete", schemas.RunStatus.INCOMPLETE),
        # Overrides: no direct RunStatus member.
        ("requires_action", schemas.RunStatus.IN_PROGRESS),
        ("cancelling", schemas.RunStatus.INCOMPLETE),
        ("cancelled", schemas.RunStatus.INCOMPLETE),
        ("expired", schemas.RunStatus.INCOMPLETE),
    ],
)
async def test_map_run_status(openai_status: str, expected: schemas.RunStatus) -> None:
    assert migration._map_run_status(openai_status) == expected


async def test_maybe_extract_user_id_valid() -> None:
    msg = _generate_openai_message("m", role="user", created_at=1, user_id=42)
    assert migration._maybe_extract_user_id(msg) == 42


async def test_maybe_extract_user_id_non_user_role() -> None:
    msg = _generate_openai_message("m", role="assistant", created_at=1, run_id="r")
    assert migration._maybe_extract_user_id(msg) is None


async def test_maybe_extract_user_id_missing_metadata() -> None:
    msg = _generate_openai_message("m", role="user", created_at=1, metadata={})
    assert migration._maybe_extract_user_id(msg) is None


async def test_maybe_extract_user_id_non_int() -> None:
    msg = _generate_openai_message(
        "m", role="user", created_at=1, metadata={"user_id": "not-a-number"}
    )
    assert migration._maybe_extract_user_id(msg) is None
