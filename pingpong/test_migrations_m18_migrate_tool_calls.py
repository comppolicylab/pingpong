import base64
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from pingpong import models, schemas
from pingpong.migrations import m18_migrate_tool_calls as migration

pytestmark = pytest.mark.asyncio


MIGRATION_KEY = "assistants_to_responses_api_thread_migration"


def _migration_metadata(*, tool_calls_complete: bool = False):
    metadata = {MIGRATION_KEY: {"message_parts": "complete", "attachments": "complete"}}
    if tool_calls_complete:
        metadata[MIGRATION_KEY]["tool_calls"] = "complete"
    return metadata


def _tool_calls_migration_state(message):
    return message.message_metadata[MIGRATION_KEY].get("tool_calls")


def _ci_logs(logs):
    return SimpleNamespace(type="logs", logs=logs)


def _ci_image(file_id):
    return SimpleNamespace(type="image", image=SimpleNamespace(file_id=file_id))


def _ci_tool_call(id_, code, outputs):
    from openai.types.beta.threads.runs import CodeInterpreterToolCall

    return CodeInterpreterToolCall.construct(
        id=id_,
        type="code_interpreter",
        code_interpreter=SimpleNamespace(input=code, outputs=outputs),
    )


def _fs_content(text):
    return SimpleNamespace(type="text", text=text)


def _fs_result(file_id, file_name, score, content=None):
    return SimpleNamespace(
        file_id=file_id, file_name=file_name, score=score, content=content
    )


def _fs_tool_call(id_, results):
    from openai.types.beta.threads.runs import FileSearchToolCall

    return FileSearchToolCall.construct(
        id=id_,
        type="file_search",
        file_search=SimpleNamespace(results=results, ranking_options=None),
    )


def _function_tool_call(id_):
    from openai.types.beta.threads.runs import FunctionToolCall

    return FunctionToolCall.construct(
        id=id_,
        type="function",
        function=SimpleNamespace(name="f", arguments="{}", output=None),
    )


def _tool_calls_step(
    step_id,
    tool_calls,
    *,
    status="completed",
    created_at=1_000,
    completed_at=2_000,
):
    from openai.types.beta.threads.runs import RunStep, ToolCallsStepDetails

    return RunStep.construct(
        id=step_id,
        type="tool_calls",
        status=status,
        created_at=created_at,
        completed_at=completed_at,
        failed_at=None,
        cancelled_at=None,
        expired_at=None,
        step_details=ToolCallsStepDetails.construct(
            type="tool_calls", tool_calls=tool_calls
        ),
    )


def _message_creation_step(step_id):
    from openai.types.beta.threads.runs import (
        MessageCreationStepDetails,
        RunStep,
    )

    return RunStep.construct(
        id=step_id,
        type="message_creation",
        status="completed",
        created_at=1_000,
        completed_at=2_000,
        failed_at=None,
        cancelled_at=None,
        expired_at=None,
        step_details=MessageCreationStepDetails.construct(
            type="message_creation",
            message_creation=SimpleNamespace(message_id="msg-x"),
        ),
    )


def _openai_message(message_id, role, run_id, *, created_at=1_000):
    return SimpleNamespace(
        id=message_id,
        role=role,
        run_id=run_id,
        created_at=created_at,
        completed_at=created_at,
        status="completed",
        metadata={},
    )


def _openai_run(run_id, *, created_at=900):
    return SimpleNamespace(
        id=run_id,
        status="completed",
        created_at=created_at,
        started_at=created_at,
        completed_at=created_at + 100,
        failed_at=None,
        cancelled_at=None,
        expires_at=None,
        last_error=None,
        incomplete_details=None,
    )


class _FakeMessages:
    def __init__(self, messages_by_thread):
        self.messages_by_thread = messages_by_thread

    async def list(self, *, thread_id, order, after):
        response = self.messages_by_thread.get(thread_id, [])
        if isinstance(response, Exception):
            raise response
        return SimpleNamespace(data=list(response), has_more=False)


class _FakeRuns:
    def __init__(self, runs_by_id, steps):
        self.runs_by_id = runs_by_id
        self.steps = steps

    async def retrieve(self, run_id, *, thread_id):
        return self.runs_by_id[run_id]


class _FakeSteps:
    def __init__(self, steps_by_run):
        self.steps_by_run = steps_by_run
        self.list_calls = []

    async def list(self, run_id, *, thread_id, order, after, include):
        self.list_calls.append((thread_id, run_id, tuple(include)))
        response = self.steps_by_run.get(run_id, [])
        if isinstance(response, Exception):
            raise response
        return SimpleNamespace(data=list(response), has_more=False)


class _FakeRawResponses:
    def __init__(self, content_by_file, status_by_file):
        self.content_by_file = content_by_file
        self.status_by_file = status_by_file

    async def retrieve_content(self, file_id):
        return SimpleNamespace(
            status_code=self.status_by_file.get(file_id, 200),
            content=self.content_by_file.get(file_id, b""),
        )


class _FakeFiles:
    def __init__(self, content_by_file, status_by_file, filename_by_file):
        self.with_raw_response = _FakeRawResponses(content_by_file, status_by_file)
        self.filename_by_file = filename_by_file

    async def retrieve(self, file_id):
        return SimpleNamespace(
            filename=self.filename_by_file.get(file_id, f"{file_id}.png")
        )


def _fake_openai_client(
    *,
    messages_by_thread=None,
    runs_by_id=None,
    steps_by_run=None,
    file_content=None,
    file_status=None,
    file_names=None,
):
    steps = _FakeSteps(steps_by_run or {})
    return SimpleNamespace(
        beta=SimpleNamespace(
            threads=SimpleNamespace(
                messages=_FakeMessages(messages_by_thread or {}),
                runs=SimpleNamespace(
                    retrieve=_FakeRuns(runs_by_id or {}, steps).retrieve,
                    steps=steps,
                ),
            )
        ),
        files=_FakeFiles(file_content or {}, file_status or {}, file_names or {}),
    )


def _patch_openai_client(monkeypatch, fake_client, *, expected_class_id=None):
    async def fake_get_openai_client_by_class_id(_session, class_id):
        if expected_class_id is not None:
            assert class_id == expected_class_id
        return fake_client

    monkeypatch.setattr(
        migration, "get_openai_client_by_class_id", fake_get_openai_client_by_class_id
    )


async def _seed_thread(
    session, *, class_id, assistant_id, thread_id, run_pk, openai_run_id=None
):
    if openai_run_id is None:
        openai_run_id = f"run-{run_pk}"
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
        id=run_pk,
        run_id=openai_run_id,
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
    id_,
    thread_id,
    run_id,
    openai_message_id,
    output_index=0,
    role=schemas.MessageRole.ASSISTANT,
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


async def _seed_file(session, *, id_, file_id, class_id=None):
    file = models.File(
        id=id_, file_id=file_id, name=f"{file_id}.txt", class_id=class_id
    )
    session.add(file)
    await session.flush()
    return file


async def _all(session, model, order_by=None):
    stmt = select(model)
    if order_by is not None:
        stmt = stmt.order_by(order_by)
    return list((await session.scalars(stmt)).all())


async def test_fetch_messages_returns_only_gated_messages(db):
    async with db.async_session() as session:
        await _seed_thread(
            session, class_id=1, assistant_id=10, thread_id=100, run_pk=100
        )
        await _seed_thread(
            session, class_id=2, assistant_id=20, thread_id=200, run_pk=200
        )
        await _seed_message(
            session,
            id_=1001,
            thread_id=100,
            run_id=100,
            openai_message_id="msg-gated",
            metadata=_migration_metadata(),
        )
        await _seed_message(
            session,
            id_=1002,
            thread_id=100,
            run_id=100,
            openai_message_id="msg-not-ready",
            output_index=1,
            metadata={MIGRATION_KEY: {}},
        )
        await _seed_message(
            session,
            id_=1003,
            thread_id=100,
            run_id=100,
            openai_message_id="msg-done",
            output_index=2,
            metadata=_migration_metadata(tool_calls_complete=True),
        )
        await _seed_message(
            session,
            id_=2001,
            thread_id=200,
            run_id=200,
            openai_message_id="msg-other-class",
            metadata=_migration_metadata(),
        )
        await session.commit()

    async with db.async_session() as session:
        messages = await migration._fetch_messages(session)

    assert sorted(m.message_id for m in messages) == ["msg-gated", "msg-other-class"]


async def test_code_interpreter_logs_output(db, monkeypatch):
    async with db.async_session() as session:
        await _seed_thread(
            session,
            class_id=1,
            assistant_id=10,
            thread_id=100,
            run_pk=100,
            openai_run_id="run-A",
        )
        await _seed_message(
            session,
            id_=1001,
            thread_id=100,
            run_id=100,
            openai_message_id="msg-1",
            metadata=_migration_metadata(),
        )
        await session.commit()

    fake_client = _fake_openai_client(
        messages_by_thread={
            "thread-100": [_openai_message("msg-1", "assistant", "run-A")]
        },
        runs_by_id={"run-A": _openai_run("run-A")},
        steps_by_run={
            "run-A": [
                _tool_calls_step(
                    "step-1",
                    [_ci_tool_call("tc-1", "print(1)", [_ci_logs("1\n")])],
                )
            ]
        },
    )
    _patch_openai_client(monkeypatch, fake_client, expected_class_id=1)

    async with db.async_session() as session:
        await migration.migrate_tool_calls(session)

    async with db.async_session() as session:
        tool_calls = await _all(session, models.ToolCall)
        outputs = await _all(session, models.CodeInterpreterCallOutput)
        message = await session.get(models.Message, 1001)

    assert len(tool_calls) == 1
    tc = tool_calls[0]
    assert tc.run_id == 100
    assert tc.thread_id == 100
    assert tc.tool_call_id == "tc-1"
    assert tc.type == schemas.ToolCallType.CODE_INTERPRETER
    assert tc.status == schemas.ToolCallStatus.COMPLETED
    assert tc.code == "print(1)"
    assert tc.container_id is None
    assert tc.output_index == 0
    assert len(outputs) == 1
    assert outputs[0].tool_call_id == tc.id
    assert outputs[0].output_type == schemas.CodeInterpreterOutputType.LOGS
    assert outputs[0].logs == "1\n"
    assert _tool_calls_migration_state(message) == "complete"


async def test_code_interpreter_image_output_data_url(db, monkeypatch):
    async with db.async_session() as session:
        await _seed_thread(
            session,
            class_id=1,
            assistant_id=10,
            thread_id=100,
            run_pk=100,
            openai_run_id="run-A",
        )
        await _seed_message(
            session,
            id_=1001,
            thread_id=100,
            run_id=100,
            openai_message_id="msg-1",
            metadata=_migration_metadata(),
        )
        await session.commit()

    fake_client = _fake_openai_client(
        messages_by_thread={
            "thread-100": [_openai_message("msg-1", "assistant", "run-A")]
        },
        runs_by_id={"run-A": _openai_run("run-A")},
        steps_by_run={
            "run-A": [
                _tool_calls_step(
                    "step-1",
                    [_ci_tool_call("tc-1", "plot()", [_ci_image("file-img")])],
                )
            ]
        },
        file_content={"file-img": b"PNGDATA"},
        file_names={"file-img": "plot.png"},
    )
    _patch_openai_client(monkeypatch, fake_client)

    async with db.async_session() as session:
        await migration.migrate_tool_calls(session)

    async with db.async_session() as session:
        outputs = await _all(session, models.CodeInterpreterCallOutput)

    assert len(outputs) == 1
    expected = "data:image/png;base64," + base64.b64encode(b"PNGDATA").decode("utf-8")
    assert outputs[0].output_type == schemas.CodeInterpreterOutputType.IMAGE
    assert outputs[0].url == expected


async def test_file_search_results(db, monkeypatch):
    async with db.async_session() as session:
        await _seed_thread(
            session,
            class_id=1,
            assistant_id=10,
            thread_id=100,
            run_pk=100,
            openai_run_id="run-A",
        )
        await _seed_message(
            session,
            id_=1001,
            thread_id=100,
            run_id=100,
            openai_message_id="msg-1",
            metadata=_migration_metadata(),
        )
        await _seed_file(session, id_=50, file_id="file-present", class_id=1)
        await session.commit()

    fake_client = _fake_openai_client(
        messages_by_thread={
            "thread-100": [_openai_message("msg-1", "assistant", "run-A")]
        },
        runs_by_id={"run-A": _openai_run("run-A")},
        steps_by_run={
            "run-A": [
                _tool_calls_step(
                    "step-1",
                    [
                        _fs_tool_call(
                            "tc-1",
                            [
                                _fs_result(
                                    "file-present",
                                    "present.pdf",
                                    0.9,
                                    [_fs_content("a"), _fs_content("b")],
                                ),
                                _fs_result("file-absent", "absent.pdf", 0.5, None),
                            ],
                        )
                    ],
                )
            ]
        },
    )
    _patch_openai_client(monkeypatch, fake_client)

    async with db.async_session() as session:
        await migration.migrate_tool_calls(session)

    async with db.async_session() as session:
        tool_calls = await _all(session, models.ToolCall)
        results = await _all(
            session, models.FileSearchCallResult, models.FileSearchCallResult.file_id
        )

    assert len(tool_calls) == 1
    assert tool_calls[0].type == schemas.ToolCallType.FILE_SEARCH
    assert tool_calls[0].queries == ""
    assert len(results) == 2
    absent, present = sorted(results, key=lambda r: r.file_id)
    assert absent.file_id == "file-absent"
    assert absent.file_object_id is None
    assert absent.filename == "absent.pdf"
    assert absent.text == ""
    assert present.file_id == "file-present"
    assert present.file_object_id == 50
    assert present.filename == "present.pdf"
    assert present.score == 0.9
    assert present.text == "a\n\nb"
    assert all(r.attributes is None for r in results)


async def test_multi_run_turn_collects_all_tool_calls(db, monkeypatch):
    """A turn that collapsed two OpenAI runs: m15 stored only the last run id on the
    local Run, but m18 re-derives both and attaches all tool calls to the one Run with
    a monotonic output_index."""
    async with db.async_session() as session:
        await _seed_thread(
            session,
            class_id=1,
            assistant_id=10,
            thread_id=100,
            run_pk=100,
            openai_run_id="run-B",
        )
        await _seed_message(
            session,
            id_=1001,
            thread_id=100,
            run_id=100,
            openai_message_id="msg-1",
            metadata=_migration_metadata(),
        )
        await session.commit()

    fake_client = _fake_openai_client(
        messages_by_thread={
            "thread-100": [
                _openai_message("msg-1", "assistant", "run-A"),
                _openai_message("msg-2", "assistant", "run-B"),
            ]
        },
        runs_by_id={"run-A": _openai_run("run-A"), "run-B": _openai_run("run-B")},
        steps_by_run={
            "run-A": [
                _tool_calls_step(
                    "step-A", [_ci_tool_call("tc-A", "a()", [_ci_logs("a")])]
                )
            ],
            "run-B": [
                _tool_calls_step(
                    "step-B", [_ci_tool_call("tc-B", "b()", [_ci_logs("b")])]
                )
            ],
        },
    )
    _patch_openai_client(monkeypatch, fake_client)

    async with db.async_session() as session:
        await migration.migrate_tool_calls(session)

    async with db.async_session() as session:
        tool_calls = await _all(session, models.ToolCall, models.ToolCall.output_index)

    assert [tc.tool_call_id for tc in tool_calls] == ["tc-A", "tc-B"]
    assert [tc.output_index for tc in tool_calls] == [0, 1]
    assert all(tc.run_id == 100 for tc in tool_calls)


async def test_multi_run_turn_preserves_tool_call_order(db, monkeypatch):
    async with db.async_session() as session:
        await _seed_thread(
            session,
            class_id=1,
            assistant_id=10,
            thread_id=100,
            run_pk=100,
            openai_run_id="run-B",
        )
        await _seed_message(
            session,
            id_=1001,
            thread_id=100,
            run_id=100,
            openai_message_id="msg-1",
            metadata=_migration_metadata(),
        )
        await session.commit()

    fake_client = _fake_openai_client(
        messages_by_thread={
            "thread-100": [
                _openai_message("msg-1", "assistant", "run-A"),
                _openai_message("msg-2", "assistant", "run-B"),
            ]
        },
        runs_by_id={"run-A": _openai_run("run-A"), "run-B": _openai_run("run-B")},
        steps_by_run={
            "run-A": [
                _tool_calls_step(
                    "step-A",
                    [
                        _ci_tool_call("tc-A1", "a1()", [_ci_logs("a1")]),
                        _ci_tool_call("tc-A2", "a2()", [_ci_logs("a2")]),
                    ],
                )
            ],
            "run-B": [
                _tool_calls_step(
                    "step-B",
                    [
                        _ci_tool_call("tc-B1", "b1()", [_ci_logs("b1")]),
                        _ci_tool_call("tc-B2", "b2()", [_ci_logs("b2")]),
                        _ci_tool_call("tc-B3", "b3()", [_ci_logs("b3")]),
                    ],
                )
            ],
        },
    )
    _patch_openai_client(monkeypatch, fake_client)

    async with db.async_session() as session:
        await migration.migrate_tool_calls(session)

    async with db.async_session() as session:
        tool_calls = await _all(session, models.ToolCall, models.ToolCall.output_index)

    assert [tc.tool_call_id for tc in tool_calls] == [
        "tc-A1",
        "tc-A2",
        "tc-B1",
        "tc-B2",
        "tc-B3",
    ]
    assert [tc.output_index for tc in tool_calls] == [0, 1, 2, 3, 4]
    assert all(tc.run_id == 100 for tc in tool_calls)


async def test_tool_calls_inserted_before_assistant_message(db, monkeypatch):
    """m15 numbered the turn's messages consecutively (user=0, assistant=1) with no gap.
    m18 must insert the tool calls between them and push the assistant message (and the
    rest of the thread) up, preserving Responses-style order rather than colliding with
    the existing message output_index values."""
    async with db.async_session() as session:
        await _seed_thread(
            session,
            class_id=1,
            assistant_id=10,
            thread_id=100,
            run_pk=100,
            openai_run_id="run-A",
        )
        await _seed_message(
            session,
            id_=1001,
            thread_id=100,
            run_id=100,
            openai_message_id="msg-user",
            output_index=0,
            role=schemas.MessageRole.USER,
            metadata=_migration_metadata(),
        )
        await _seed_message(
            session,
            id_=1002,
            thread_id=100,
            run_id=100,
            openai_message_id="msg-assistant",
            output_index=1,
            metadata=_migration_metadata(),
        )
        await _seed_message(
            session,
            id_=1003,
            thread_id=100,
            run_id=100,
            openai_message_id="msg-later",
            output_index=2,
            role=schemas.MessageRole.USER,
            metadata=_migration_metadata(),
        )
        await session.commit()

    fake_client = _fake_openai_client(
        messages_by_thread={
            "thread-100": [_openai_message("msg-assistant", "assistant", "run-A")]
        },
        runs_by_id={"run-A": _openai_run("run-A")},
        steps_by_run={
            "run-A": [
                _tool_calls_step(
                    "step-1",
                    [
                        _ci_tool_call("tc-1", "a()", [_ci_logs("a")]),
                        _ci_tool_call("tc-2", "b()", [_ci_logs("b")]),
                    ],
                )
            ]
        },
    )
    _patch_openai_client(monkeypatch, fake_client)

    async with db.async_session() as session:
        await migration.migrate_tool_calls(session)

    async with db.async_session() as session:
        tool_calls = await _all(session, models.ToolCall, models.ToolCall.output_index)
        user = await session.get(models.Message, 1001)
        assistant = await session.get(models.Message, 1002)
        later = await session.get(models.Message, 1003)

    assert user.output_index == 0
    assert [tc.tool_call_id for tc in tool_calls] == ["tc-1", "tc-2"]
    assert [tc.output_index for tc in tool_calls] == [1, 2]
    assert assistant.output_index == 3
    assert later.output_index == 4


async def test_function_and_message_creation_steps_skipped(db, monkeypatch):
    async with db.async_session() as session:
        await _seed_thread(
            session,
            class_id=1,
            assistant_id=10,
            thread_id=100,
            run_pk=100,
            openai_run_id="run-A",
        )
        await _seed_message(
            session,
            id_=1001,
            thread_id=100,
            run_id=100,
            openai_message_id="msg-1",
            metadata=_migration_metadata(),
        )
        await session.commit()

    fake_client = _fake_openai_client(
        messages_by_thread={
            "thread-100": [_openai_message("msg-1", "assistant", "run-A")]
        },
        runs_by_id={"run-A": _openai_run("run-A")},
        steps_by_run={
            "run-A": [
                _message_creation_step("step-mc"),
                _tool_calls_step(
                    "step-fn",
                    [
                        _function_tool_call("tc-fn"),
                        _ci_tool_call("tc-ci", "x()", [_ci_logs("x")]),
                    ],
                ),
            ]
        },
    )
    _patch_openai_client(monkeypatch, fake_client)

    async with db.async_session() as session:
        await migration.migrate_tool_calls(session)

    async with db.async_session() as session:
        tool_calls = await _all(session, models.ToolCall)
        message = await session.get(models.Message, 1001)

    assert [tc.tool_call_id for tc in tool_calls] == ["tc-ci"]
    assert tool_calls[0].output_index == 0
    assert _tool_calls_migration_state(message) == "complete"


async def test_placeholder_run_skipped(db, monkeypatch):
    async with db.async_session() as session:
        await _seed_thread(
            session,
            class_id=1,
            assistant_id=10,
            thread_id=100,
            run_pk=100,
            openai_run_id="run-A",
        )
        run = await session.get(models.Run, 100)
        run.run_id = None
        await _seed_message(
            session,
            id_=1001,
            thread_id=100,
            run_id=100,
            openai_message_id="msg-1",
            metadata=_migration_metadata(),
        )
        await session.commit()

    fake_client = _fake_openai_client()
    _patch_openai_client(monkeypatch, fake_client)

    async with db.async_session() as session:
        await migration.migrate_tool_calls(session)

    async with db.async_session() as session:
        tool_calls = await _all(session, models.ToolCall)
        message = await session.get(models.Message, 1001)

    assert tool_calls == []
    assert _tool_calls_migration_state(message) == "complete"


async def test_idempotent_rerun(db, monkeypatch):
    async with db.async_session() as session:
        await _seed_thread(
            session,
            class_id=1,
            assistant_id=10,
            thread_id=100,
            run_pk=100,
            openai_run_id="run-A",
        )
        await _seed_message(
            session,
            id_=1001,
            thread_id=100,
            run_id=100,
            openai_message_id="msg-1",
            metadata=_migration_metadata(),
        )
        await session.commit()

    def _build_client():
        return _fake_openai_client(
            messages_by_thread={
                "thread-100": [_openai_message("msg-1", "assistant", "run-A")]
            },
            runs_by_id={"run-A": _openai_run("run-A")},
            steps_by_run={
                "run-A": [
                    _tool_calls_step(
                        "step-1",
                        [_ci_tool_call("tc-1", "print(1)", [_ci_logs("1")])],
                    )
                ]
            },
        )

    _patch_openai_client(monkeypatch, _build_client())
    async with db.async_session() as session:
        await migration.migrate_tool_calls(session)

    async with db.async_session() as session:
        assert await migration._fetch_messages(session) == []

    async with db.async_session() as session:
        message = await session.get(models.Message, 1001)
        message.message_metadata = _migration_metadata()
        from sqlalchemy.orm.attributes import flag_modified

        flag_modified(message, "message_metadata")
        await session.commit()

    _patch_openai_client(monkeypatch, _build_client())
    async with db.async_session() as session:
        await migration.migrate_tool_calls(session)

    async with db.async_session() as session:
        tool_calls = await _all(session, models.ToolCall)
        outputs = await _all(session, models.CodeInterpreterCallOutput)

    assert len(tool_calls) == 1
    assert len(outputs) == 1


async def test_run_dedup_within_invocation(db, monkeypatch):
    """A run referenced by two messages is listed once; both messages get flagged."""
    async with db.async_session() as session:
        await _seed_thread(
            session,
            class_id=1,
            assistant_id=10,
            thread_id=100,
            run_pk=100,
            openai_run_id="run-A",
        )
        await _seed_message(
            session,
            id_=1001,
            thread_id=100,
            run_id=100,
            openai_message_id="msg-user",
            output_index=0,
            role=schemas.MessageRole.USER,
            metadata=_migration_metadata(),
        )
        await _seed_message(
            session,
            id_=1002,
            thread_id=100,
            run_id=100,
            openai_message_id="msg-assistant",
            output_index=1,
            metadata=_migration_metadata(),
        )
        await session.commit()

    fake_client = _fake_openai_client(
        messages_by_thread={
            "thread-100": [_openai_message("msg-assistant", "assistant", "run-A")]
        },
        runs_by_id={"run-A": _openai_run("run-A")},
        steps_by_run={
            "run-A": [
                _tool_calls_step(
                    "step-1", [_ci_tool_call("tc-1", "x()", [_ci_logs("x")])]
                )
            ]
        },
    )
    _patch_openai_client(monkeypatch, fake_client)

    async with db.async_session() as session:
        await migration.migrate_tool_calls(session)

    async with db.async_session() as session:
        tool_calls = await _all(session, models.ToolCall)
        m_user = await session.get(models.Message, 1001)
        m_assistant = await session.get(models.Message, 1002)

    assert len(tool_calls) == 1
    assert len(fake_client.beta.threads.runs.steps.list_calls) == 1
    assert _tool_calls_migration_state(m_user) == "complete"
    assert _tool_calls_migration_state(m_assistant) == "complete"


async def test_continues_after_image_fetch_failure(db, monkeypatch):
    async with db.async_session() as session:
        await _seed_thread(
            session,
            class_id=1,
            assistant_id=10,
            thread_id=100,
            run_pk=100,
            openai_run_id="run-A",
        )
        await _seed_thread(
            session,
            class_id=1,
            assistant_id=10,
            thread_id=200,
            run_pk=200,
            openai_run_id="run-B",
        )
        await _seed_message(
            session,
            id_=1001,
            thread_id=100,
            run_id=100,
            openai_message_id="msg-fails",
            metadata=_migration_metadata(),
        )
        await _seed_message(
            session,
            id_=2001,
            thread_id=200,
            run_id=200,
            openai_message_id="msg-ok",
            metadata=_migration_metadata(),
        )
        await session.commit()

    fake_client = _fake_openai_client(
        messages_by_thread={
            "thread-100": [_openai_message("msg-fails", "assistant", "run-A")],
            "thread-200": [_openai_message("msg-ok", "assistant", "run-B")],
        },
        runs_by_id={"run-A": _openai_run("run-A"), "run-B": _openai_run("run-B")},
        steps_by_run={
            "run-A": [
                _tool_calls_step(
                    "step-A", [_ci_tool_call("tc-A", "p()", [_ci_image("bad-img")])]
                )
            ],
            "run-B": [
                _tool_calls_step(
                    "step-B", [_ci_tool_call("tc-B", "ok()", [_ci_logs("ok")])]
                )
            ],
        },
        file_status={"bad-img": 500},
        file_content={"bad-img": b"x"},
    )
    _patch_openai_client(monkeypatch, fake_client, expected_class_id=1)

    async with db.async_session() as session:
        await migration.migrate_tool_calls(session)

    async with db.async_session() as session:
        tool_calls = await _all(session, models.ToolCall)
        failed_message = await session.get(models.Message, 1001)
        ok_message = await session.get(models.Message, 2001)

    assert [tc.tool_call_id for tc in tool_calls] == ["tc-B"]
    assert _tool_calls_migration_state(failed_message) is None
    assert _tool_calls_migration_state(ok_message) == "complete"


async def test_multi_run_turn_inserts_each_run_before_its_own_message(db, monkeypatch):
    async with db.async_session() as session:
        await _seed_thread(
            session,
            class_id=1,
            assistant_id=10,
            thread_id=100,
            run_pk=100,
            openai_run_id="run-B",
        )
        await _seed_message(
            session,
            id_=1001,
            thread_id=100,
            run_id=100,
            openai_message_id="msg-user",
            output_index=0,
            role=schemas.MessageRole.USER,
            metadata=_migration_metadata(),
        )
        await _seed_message(
            session,
            id_=1002,
            thread_id=100,
            run_id=100,
            openai_message_id="msg-A",
            output_index=1,
            metadata=_migration_metadata(),
        )
        await _seed_message(
            session,
            id_=1003,
            thread_id=100,
            run_id=100,
            openai_message_id="msg-B",
            output_index=2,
            metadata=_migration_metadata(),
        )
        await session.commit()

    fake_client = _fake_openai_client(
        messages_by_thread={
            "thread-100": [
                _openai_message("msg-A", "assistant", "run-A"),
                _openai_message("msg-B", "assistant", "run-B"),
            ]
        },
        runs_by_id={"run-A": _openai_run("run-A"), "run-B": _openai_run("run-B")},
        steps_by_run={
            "run-A": [
                _tool_calls_step(
                    "step-A", [_ci_tool_call("tc-A", "a()", [_ci_logs("a")])]
                )
            ],
            "run-B": [
                _tool_calls_step(
                    "step-B", [_ci_tool_call("tc-B", "b()", [_ci_logs("b")])]
                )
            ],
        },
    )
    _patch_openai_client(monkeypatch, fake_client)

    async with db.async_session() as session:
        await migration.migrate_tool_calls(session)

    async with db.async_session() as session:
        tool_calls = await _all(session, models.ToolCall, models.ToolCall.output_index)
        user = await session.get(models.Message, 1001)
        asst_a = await session.get(models.Message, 1002)
        asst_b = await session.get(models.Message, 1003)

    assert user.output_index == 0
    assert {tc.tool_call_id: tc.output_index for tc in tool_calls} == {
        "tc-A": 1,
        "tc-B": 3,
    }
    assert asst_a.output_index == 2
    assert asst_b.output_index == 4


async def test_assistant_only_turn_is_backfilled(db, monkeypatch):
    async with db.async_session() as session:
        await _seed_thread(
            session,
            class_id=1,
            assistant_id=10,
            thread_id=100,
            run_pk=100,
            openai_run_id="run-A",
        )
        await _seed_message(
            session,
            id_=1001,
            thread_id=100,
            run_id=100,
            openai_message_id="msg-assistant",
            output_index=0,
            metadata={MIGRATION_KEY: {"message_parts": "complete"}},
        )
        await session.commit()

    fake_client = _fake_openai_client(
        messages_by_thread={
            "thread-100": [_openai_message("msg-assistant", "assistant", "run-A")]
        },
        runs_by_id={"run-A": _openai_run("run-A")},
        steps_by_run={
            "run-A": [
                _tool_calls_step(
                    "step-1", [_ci_tool_call("tc-1", "x()", [_ci_logs("x")])]
                )
            ]
        },
    )
    _patch_openai_client(monkeypatch, fake_client)

    async with db.async_session() as session:
        await migration.migrate_tool_calls(session)

    async with db.async_session() as session:
        tool_calls = await _all(session, models.ToolCall)
        message = await session.get(models.Message, 1001)

    assert [tc.tool_call_id for tc in tool_calls] == ["tc-1"]
    assert _tool_calls_migration_state(message) == "complete"
