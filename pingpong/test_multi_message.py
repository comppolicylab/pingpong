from __future__ import annotations

from datetime import datetime, timedelta, timezone
import importlib
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from pingpong import models, schemas
from pingpong.ai import BufferedResponseStreamHandler
from pingpong.testutil import with_authz, with_user

pytestmark = pytest.mark.asyncio
server_module = importlib.import_module("pingpong.server")


async def _create_handler_context(
    db,
    *,
    user_id: int,
    email: str,
    class_id: int,
    class_name: str,
    assistant_id: int,
    assistant_name: str,
    assistant_external_id: str,
    model: str,
    thread_id: int,
    thread_external_id: str,
    run_id: int,
    run_external_id: str,
):
    base_time = datetime(2024, 1, 1, tzinfo=timezone.utc)

    async with db.async_session() as session:
        user = models.User(
            id=user_id,
            email=email,
            state=schemas.UserState.VERIFIED,
        )
        class_ = models.Class(id=class_id, name=class_name, api_key="sk-test")
        assistant = models.Assistant(
            id=assistant_id,
            name=assistant_name,
            class_id=class_id,
            assistant_id=assistant_external_id,
            model=model,
            creator_id=user_id,
        )
        thread = models.Thread(
            id=thread_id,
            thread_id=thread_external_id,
            class_id=class_id,
            assistant_id=assistant_id,
            version=3,
            tools_available="",
            private=False,
        )
        run = models.Run(
            id=run_id,
            run_id=run_external_id,
            status=schemas.RunStatus.IN_PROGRESS,
            thread_id=thread_id,
            assistant_id=assistant_id,
            creator_id=user_id,
            created=base_time,
            updated=base_time,
        )
        session.add_all([user, class_, assistant, thread, run])
        await session.commit()

    return BufferedResponseStreamHandler(
        auth=AsyncMock(),
        cli=AsyncMock(),
        run_id=run_id,
        run_status=schemas.RunStatus.IN_PROGRESS,
        prev_output_index=0,
        file_names={},
        class_id=class_id,
        thread_id=thread_id,
        assistant_id=assistant_id,
        user_id=user_id,
    )


async def _setup_handler_with_initial_message(db):
    handler = await _create_handler_context(
        db,
        user_id=9001,
        email="multi-message@test.dev",
        class_id=3001,
        class_name="Multi Message Class",
        assistant_id=6001,
        assistant_name="Handler Assistant",
        assistant_external_id="asst-handler",
        model="gpt-4o-mini",
        thread_id=4001,
        thread_external_id="thread-handler",
        run_id=5001,
        run_external_id="run-handler",
    )
    first_event = SimpleNamespace(
        id="msg-1",
        status=schemas.MessageStatus.IN_PROGRESS.value,
        role="assistant",
    )
    await handler.on_output_message_created(first_event)
    assert handler.message_id is not None
    return handler, 5001, handler.message_id


async def _setup_handler_with_phase(db, phase: str):
    handler = await _create_handler_context(
        db,
        user_id=9002,
        email="multi-message-phase@test.dev",
        class_id=3002,
        class_name="Multi Message Phase Class",
        assistant_id=6002,
        assistant_name="Handler Phase Assistant",
        assistant_external_id="asst-handler-phase",
        model="gpt-5.3-codex",
        thread_id=4002,
        thread_external_id="thread-handler-phase",
        run_id=5002,
        run_external_id="run-handler-phase",
    )
    event = SimpleNamespace(
        id="msg-phase-1",
        status=schemas.MessageStatus.IN_PROGRESS.value,
        role="assistant",
        phase=phase,
    )
    await handler.on_output_message_created(event)
    return handler, 4002


async def _create_thread_with_duplicate_assistant_messages(
    db,
    *,
    class_id: int,
    thread_id: int,
    run_id: int,
    assistant_id: int,
    older_output_index: int,
    newer_output_index: int,
    older_phase: str | None = None,
    newer_phase: str | None = None,
) -> None:
    base_time = datetime(2024, 1, 1, tzinfo=timezone.utc)
    async with db.async_session() as session:
        class_ = models.Class(id=class_id, name=f"Class {class_id}", api_key="sk-test")
        assistant = models.Assistant(
            id=assistant_id,
            name=f"Assistant {assistant_id}",
            class_id=class_id,
            assistant_id=f"asst-{assistant_id}",
            model="gpt-4o-mini",
            hide_reasoning_summaries=False,
        )
        thread = models.Thread(
            id=thread_id,
            thread_id=f"thread-{thread_id}",
            class_id=class_id,
            assistant_id=assistant_id,
            version=3,
            tools_available="",
            private=False,
        )
        run = models.Run(
            id=run_id,
            run_id=f"run-{run_id}",
            status=schemas.RunStatus.COMPLETED,
            thread_id=thread_id,
            assistant_id=assistant_id,
            created=base_time,
            updated=base_time,
        )
        older_message = models.Message(
            message_status=schemas.MessageStatus.COMPLETED,
            run_id=run_id,
            thread_id=thread_id,
            assistant_id=assistant_id,
            role=schemas.MessageRole.ASSISTANT,
            output_index=older_output_index,
            phase=older_phase,
            created=base_time,
        )
        newer_message = models.Message(
            message_status=schemas.MessageStatus.COMPLETED,
            run_id=run_id,
            thread_id=thread_id,
            assistant_id=assistant_id,
            role=schemas.MessageRole.ASSISTANT,
            output_index=newer_output_index,
            phase=newer_phase,
            created=base_time + timedelta(seconds=1),
        )

        session.add_all([class_, assistant, thread, run, older_message, newer_message])
        await session.commit()


async def _create_thread_with_assistant_message_sequence(
    db,
    *,
    class_id: int,
    thread_id: int,
    run_id: int,
    assistant_id: int,
    phases: list[str | None],
) -> None:
    base_time = datetime(2024, 1, 1, tzinfo=timezone.utc)
    async with db.async_session() as session:
        class_ = models.Class(id=class_id, name=f"Class {class_id}", api_key="sk-test")
        assistant = models.Assistant(
            id=assistant_id,
            name=f"Assistant {assistant_id}",
            class_id=class_id,
            assistant_id=f"asst-{assistant_id}",
            model="gpt-4o-mini",
            hide_reasoning_summaries=False,
        )
        thread = models.Thread(
            id=thread_id,
            thread_id=f"thread-{thread_id}",
            class_id=class_id,
            assistant_id=assistant_id,
            version=3,
            tools_available="",
            private=False,
        )
        run = models.Run(
            id=run_id,
            run_id=f"run-{run_id}",
            status=schemas.RunStatus.COMPLETED,
            thread_id=thread_id,
            assistant_id=assistant_id,
            created=base_time,
            updated=base_time,
        )
        messages = [
            models.Message(
                message_status=schemas.MessageStatus.COMPLETED,
                run_id=run_id,
                thread_id=thread_id,
                assistant_id=assistant_id,
                role=schemas.MessageRole.ASSISTANT,
                output_index=index + 1,
                phase=phase,
                created=base_time + timedelta(seconds=index),
            )
            for index, phase in enumerate(phases)
        ]

        session.add_all([class_, assistant, thread, run, *messages])
        await session.commit()


async def _create_server_thread(db, *, class_id: int, thread_id: int, run_id: int):
    await _create_thread_with_duplicate_assistant_messages(
        db,
        class_id=class_id,
        thread_id=thread_id,
        run_id=run_id,
        assistant_id=run_id * 2,
        older_output_index=2,
        newer_output_index=8,
        older_phase=schemas.MessagePhase.FINAL_ANSWER.value,
        newer_phase=schemas.MessagePhase.FINAL_ANSWER.value,
    )


async def _create_server_thread_alt(db, *, class_id: int, thread_id: int, run_id: int):
    await _create_thread_with_duplicate_assistant_messages(
        db,
        class_id=class_id,
        thread_id=thread_id,
        run_id=run_id,
        assistant_id=run_id * 3,
        older_output_index=3,
        newer_output_index=7,
        older_phase=schemas.MessagePhase.FINAL_ANSWER.value,
        newer_phase=schemas.MessagePhase.FINAL_ANSWER.value,
    )


async def _create_thread_with_phase_separated_assistant_messages(
    db,
    *,
    class_id: int,
    thread_id: int,
    run_id: int,
    assistant_id: int,
    older_phase: str = schemas.MessagePhase.COMMENTARY.value,
    newer_phase: str = schemas.MessagePhase.FINAL_ANSWER.value,
) -> None:
    await _create_thread_with_duplicate_assistant_messages(
        db,
        class_id=class_id,
        thread_id=thread_id,
        run_id=run_id,
        assistant_id=assistant_id,
        older_output_index=2,
        newer_output_index=8,
        older_phase=older_phase,
        newer_phase=newer_phase,
    )


async def _create_thread_with_unphased_assistant_messages(
    db,
    *,
    class_id: int,
    thread_id: int,
    run_id: int,
    assistant_id: int,
) -> None:
    await _create_thread_with_duplicate_assistant_messages(
        db,
        class_id=class_id,
        thread_id=thread_id,
        run_id=run_id,
        assistant_id=assistant_id,
        older_output_index=2,
        newer_output_index=8,
        older_phase=None,
        newer_phase=None,
    )


async def _create_thread_with_visible_prompt(
    db,
    *,
    class_id: int,
    thread_id: int,
    assistant_id: int,
    instructions: str,
    hide_prompt: bool,
) -> None:
    async with db.async_session() as session:
        class_ = models.Class(id=class_id, name=f"Class {class_id}", api_key="sk-test")
        assistant = models.Assistant(
            id=assistant_id,
            name=f"Assistant {assistant_id}",
            class_id=class_id,
            assistant_id=f"asst-{assistant_id}",
            model="gpt-4o-mini",
            hide_prompt=hide_prompt,
        )
        thread = models.Thread(
            id=thread_id,
            thread_id=f"thread-{thread_id}",
            class_id=class_id,
            assistant_id=assistant_id,
            version=3,
            tools_available="",
            private=False,
            instructions=instructions,
        )
        session.add_all([class_, assistant, thread])
        await session.commit()


async def _create_thread_with_tool_call_between_messages(
    db,
    *,
    class_id: int,
    thread_id: int,
    run_id: int,
    assistant_id: int,
):
    base_time = datetime(2024, 1, 1, tzinfo=timezone.utc)
    async with db.async_session() as session:
        class_ = models.Class(id=class_id, name=f"Class {class_id}", api_key="sk-test")
        assistant = models.Assistant(
            id=assistant_id,
            name=f"Assistant {assistant_id}",
            class_id=class_id,
            assistant_id=f"asst-{assistant_id}",
            model="gpt-4o-mini",
            hide_reasoning_summaries=False,
        )
        thread = models.Thread(
            id=thread_id,
            thread_id=f"thread-{thread_id}",
            class_id=class_id,
            assistant_id=assistant_id,
            version=3,
            tools_available="code_interpreter",
            private=False,
        )
        run = models.Run(
            id=run_id,
            run_id=f"run-{run_id}",
            status=schemas.RunStatus.COMPLETED,
            thread_id=thread_id,
            assistant_id=assistant_id,
            created=base_time,
            updated=base_time,
        )
        first_message = models.Message(
            message_status=schemas.MessageStatus.COMPLETED,
            run_id=run_id,
            thread_id=thread_id,
            assistant_id=assistant_id,
            role=schemas.MessageRole.ASSISTANT,
            output_index=1,
            created=base_time,
        )
        tool_call = models.ToolCall(
            tool_call_id="tc-1",
            type=schemas.ToolCallType.CODE_INTERPRETER,
            status=schemas.ToolCallStatus.COMPLETED,
            run_id=run_id,
            thread_id=thread_id,
            output_index=2,
            created=base_time,
        )
        second_message = models.Message(
            message_status=schemas.MessageStatus.COMPLETED,
            run_id=run_id,
            thread_id=thread_id,
            assistant_id=assistant_id,
            role=schemas.MessageRole.ASSISTANT,
            output_index=3,
            created=base_time + timedelta(seconds=1),
        )

        session.add_all(
            [
                class_,
                assistant,
                thread,
                run,
                first_message,
                tool_call,
                second_message,
            ]
        )
        await session.commit()


async def _create_server_thread_with_reasoning(
    db,
    *,
    class_id: int,
    thread_id: int,
    run_id: int,
    assistant_id: int,
    reasoning_step_id: int,
):
    base_time = datetime(2024, 1, 1, tzinfo=timezone.utc)
    async with db.async_session() as session:
        class_ = models.Class(id=class_id, name=f"Class {class_id}", api_key="sk-test")
        assistant = models.Assistant(
            id=assistant_id,
            name=f"Assistant {assistant_id}",
            class_id=class_id,
            assistant_id=f"asst-{assistant_id}",
            model="gpt-4o-mini",
            hide_reasoning_summaries=False,
        )
        thread = models.Thread(
            id=thread_id,
            thread_id=f"thread-{thread_id}",
            class_id=class_id,
            assistant_id=assistant_id,
            version=3,
            tools_available="",
            private=False,
        )
        run = models.Run(
            id=run_id,
            run_id=f"run-{run_id}",
            status=schemas.RunStatus.COMPLETED,
            thread_id=thread_id,
            assistant_id=assistant_id,
            created=base_time,
            updated=base_time,
        )
        message = models.Message(
            id=run_id + 1,
            message_status=schemas.MessageStatus.COMPLETED,
            run_id=run_id,
            thread_id=thread_id,
            assistant_id=assistant_id,
            role=schemas.MessageRole.ASSISTANT,
            output_index=1,
            created=base_time,
        )
        reasoning_step = models.ReasoningStep(
            id=reasoning_step_id,
            run_id=run_id,
            thread_id=thread_id,
            output_index=2,
            status=schemas.ReasoningStatus.COMPLETED,
            reasoning_id=f"rst-{reasoning_step_id}",
            created=base_time,
        )
        reasoning_step.updated = base_time + timedelta(seconds=125)

        session.add_all([class_, assistant, thread, run, message, reasoning_step])
        await session.flush()

        summary_part_one = models.ReasoningSummaryPart(
            id=reasoning_step_id * 10 + 1,
            reasoning_step_id=reasoning_step.id,
            part_index=0,
            summary_text="First reasoning summary",
            created=base_time,
        )
        summary_part_two = models.ReasoningSummaryPart(
            id=reasoning_step_id * 10 + 2,
            reasoning_step_id=reasoning_step.id,
            part_index=1,
            summary_text="Second reasoning summary",
            created=base_time,
        )
        session.add_all([summary_part_one, summary_part_two])
        await session.flush()

        summary_parts = [
            {
                "id": summary_part_one.id,
                "part_index": summary_part_one.part_index,
                "summary_text": summary_part_one.summary_text,
            },
            {
                "id": summary_part_two.id,
                "part_index": summary_part_two.part_index,
                "summary_text": summary_part_two.summary_text,
            },
        ]

        await session.commit()

    return {
        "assistant_id": assistant_id,
        "thread_id": thread_id,
        "run_id": run_id,
        "reasoning_step_id": reasoning_step_id,
        "step_identifier": f"rst-{reasoning_step_id}",
        "output_index": 2,
        "created_at": base_time.timestamp(),
        "summary_parts": summary_parts,
        "status": schemas.ReasoningStatus.COMPLETED.value,
        "thought_for": "2 minutes",
    }


async def test_buffered_handler_truncates_after_duplicate_messages(db):
    handler, run_id, first_message_id = await _setup_handler_with_initial_message(db)
    done_event = SimpleNamespace(
        id="msg-1",
        status=schemas.MessageStatus.COMPLETED.value,
    )
    await handler.on_output_message_done(done_event)
    second_event = SimpleNamespace(
        id="msg-2",
        status=schemas.MessageStatus.IN_PROGRESS.value,
        role="assistant",
    )

    await handler.on_output_message_created(second_event)

    assert handler.force_stopped is True
    assert handler.run_id is None
    assert handler.run_status is None
    assert handler.force_stop_incomplete_reason is None

    async with db.async_session() as session:
        message = await session.get(models.Message, first_message_id)
        run = await session.get(models.Run, run_id)

    assert message is not None
    assert message.message_status == schemas.MessageStatus.COMPLETED
    assert message.completed is not None
    assert run is not None
    assert run.status == schemas.RunStatus.COMPLETED
    assert run.incomplete_reason == "multi_message_truncate"


async def test_buffered_handler_accepts_message_after_tool_call(db):
    handler, run_id, first_message_id = await _setup_handler_with_initial_message(db)
    done_event = SimpleNamespace(
        id="msg-1",
        status=schemas.MessageStatus.COMPLETED.value,
    )
    await handler.on_output_message_done(done_event)

    tool_call_event = SimpleNamespace(
        id="tc-1",
        status=schemas.ToolCallStatus.IN_PROGRESS.value,
        container_id="container-1",
        code="print('hello')",
    )
    await handler.on_code_interpreter_tool_call_created(tool_call_event)

    second_event = SimpleNamespace(
        id="msg-2",
        status=schemas.MessageStatus.IN_PROGRESS.value,
        role="assistant",
    )

    await handler.on_output_message_created(second_event)

    assert handler.force_stopped is False
    assert handler.run_id == run_id
    assert handler.message_id is not None
    assert handler.last_output_item_type == "message"

    async with db.async_session() as session:
        first_message = await session.get(models.Message, first_message_id)
        second_message = await session.get(models.Message, handler.message_id)
        run = await session.get(models.Run, run_id)

    assert first_message is not None
    assert first_message.message_status == schemas.MessageStatus.COMPLETED
    assert second_message is not None
    assert second_message.message_status == schemas.MessageStatus.IN_PROGRESS
    assert run is not None
    assert run.status == schemas.RunStatus.IN_PROGRESS
    assert run.incomplete_reason is None


async def test_buffered_handler_accepts_final_answer_after_commentary(db):
    handler, thread_id = await _setup_handler_with_phase(db, "commentary")
    assert handler.message_id is not None
    assert handler.run_id is not None
    run_id = handler.run_id
    first_message_id = handler.message_id

    commentary_done_event = SimpleNamespace(
        id="msg-phase-1",
        status=schemas.MessageStatus.COMPLETED.value,
        phase=schemas.MessagePhase.COMMENTARY.value,
    )
    await handler.on_output_message_done(commentary_done_event)

    followup_event = SimpleNamespace(
        id="msg-phase-2",
        status=schemas.MessageStatus.IN_PROGRESS.value,
        role="assistant",
        phase=schemas.MessagePhase.FINAL_ANSWER.value,
    )
    await handler.on_output_message_created(followup_event)

    assert handler.force_stopped is False
    assert handler.run_id == run_id
    assert handler.message_id is not None

    async with db.async_session() as session:
        first_message = await session.get(models.Message, first_message_id)
        run = await session.get(models.Run, run_id)
        messages = (
            (
                await session.execute(
                    select(models.Message)
                    .where(models.Message.thread_id == thread_id)
                    .order_by(models.Message.output_index.asc())
                )
            )
            .scalars()
            .all()
        )

    assert first_message is not None
    assert first_message.message_status == schemas.MessageStatus.COMPLETED
    assert first_message.phase == schemas.MessagePhase.COMMENTARY.value
    assert run is not None
    assert run.status == schemas.RunStatus.IN_PROGRESS
    assert run.incomplete_reason is None
    assert len(messages) == 2
    assert [message.phase for message in messages] == [
        schemas.MessagePhase.COMMENTARY.value,
        schemas.MessagePhase.FINAL_ANSWER.value,
    ]


async def test_buffered_handler_accepts_final_answer_after_commentary_and_tool_call(db):
    handler, thread_id = await _setup_handler_with_phase(db, "commentary")
    assert handler.message_id is not None
    assert handler.run_id is not None
    run_id = handler.run_id
    first_message_id = handler.message_id

    commentary_done_event = SimpleNamespace(
        id="msg-phase-1",
        status=schemas.MessageStatus.COMPLETED.value,
        phase=schemas.MessagePhase.COMMENTARY.value,
    )
    await handler.on_output_message_done(commentary_done_event)

    tool_call_event = SimpleNamespace(
        id="tc-phase-commentary",
        status=schemas.ToolCallStatus.IN_PROGRESS.value,
        container_id="container-commentary",
        code="print('commentary')",
    )
    await handler.on_code_interpreter_tool_call_created(tool_call_event)

    followup_event = SimpleNamespace(
        id="msg-phase-2",
        status=schemas.MessageStatus.IN_PROGRESS.value,
        role="assistant",
        phase=schemas.MessagePhase.FINAL_ANSWER.value,
    )
    await handler.on_output_message_created(followup_event)

    assert handler.force_stopped is False
    assert handler.run_id == run_id
    assert handler.message_id is not None

    async with db.async_session() as session:
        first_message = await session.get(models.Message, first_message_id)
        run = await session.get(models.Run, run_id)
        messages = (
            (
                await session.execute(
                    select(models.Message)
                    .where(models.Message.thread_id == thread_id)
                    .order_by(models.Message.output_index.asc())
                )
            )
            .scalars()
            .all()
        )

    assert first_message is not None
    assert first_message.message_status == schemas.MessageStatus.COMPLETED
    assert first_message.phase == schemas.MessagePhase.COMMENTARY.value
    assert run is not None
    assert run.status == schemas.RunStatus.IN_PROGRESS
    assert run.incomplete_reason is None
    assert len(messages) == 2
    assert [message.phase for message in messages] == [
        schemas.MessagePhase.COMMENTARY.value,
        schemas.MessagePhase.FINAL_ANSWER.value,
    ]


async def test_buffered_handler_accepts_final_answer_after_tool_call(db):
    handler, _thread_id = await _setup_handler_with_phase(db, "final_answer")
    assert handler.message_id is not None
    assert handler.run_id is not None
    run_id = handler.run_id
    first_message_id = handler.message_id

    first_done_event = SimpleNamespace(
        id="msg-phase-1",
        status=schemas.MessageStatus.COMPLETED.value,
        phase=schemas.MessagePhase.FINAL_ANSWER.value,
    )
    await handler.on_output_message_done(first_done_event)

    tool_call_event = SimpleNamespace(
        id="tc-phase-1",
        status=schemas.ToolCallStatus.IN_PROGRESS.value,
        container_id="container-phase-1",
        code="print('phase')",
    )
    await handler.on_code_interpreter_tool_call_created(tool_call_event)

    second_final_answer_event = SimpleNamespace(
        id="msg-phase-2",
        status=schemas.MessageStatus.IN_PROGRESS.value,
        role="assistant",
        phase=schemas.MessagePhase.FINAL_ANSWER.value,
    )
    await handler.on_output_message_created(second_final_answer_event)

    assert handler.force_stopped is False
    assert handler.run_id == run_id
    assert handler.message_id is not None

    async with db.async_session() as session:
        first_message = await session.get(models.Message, first_message_id)
        run = await session.get(models.Run, run_id)
        messages = (
            (
                await session.execute(
                    select(models.Message)
                    .where(models.Message.run_id == run_id)
                    .order_by(models.Message.output_index.asc())
                )
            )
            .scalars()
            .all()
        )

    assert first_message is not None
    assert first_message.message_status == schemas.MessageStatus.COMPLETED
    assert run is not None
    assert run.status == schemas.RunStatus.IN_PROGRESS
    assert run.incomplete_reason is None
    assert len(messages) == 2
    assert [message.phase for message in messages] == [
        schemas.MessagePhase.FINAL_ANSWER.value,
        schemas.MessagePhase.FINAL_ANSWER.value,
    ]


async def test_buffered_handler_accepts_commentary_after_final_answer(db):
    handler, thread_id = await _setup_handler_with_phase(db, "final_answer")
    assert handler.message_id is not None
    assert handler.run_id is not None
    run_id = handler.run_id
    first_message_id = handler.message_id

    first_done_event = SimpleNamespace(
        id="msg-phase-1",
        status=schemas.MessageStatus.COMPLETED.value,
        phase=schemas.MessagePhase.FINAL_ANSWER.value,
    )
    await handler.on_output_message_done(first_done_event)

    commentary_event = SimpleNamespace(
        id="msg-phase-2",
        status=schemas.MessageStatus.IN_PROGRESS.value,
        role="assistant",
        phase=schemas.MessagePhase.COMMENTARY.value,
    )
    await handler.on_output_message_created(commentary_event)

    assert handler.force_stopped is False
    assert handler.run_id == run_id
    assert handler.message_id is not None

    async with db.async_session() as session:
        first_message = await session.get(models.Message, first_message_id)
        run = await session.get(models.Run, run_id)
        messages = (
            (
                await session.execute(
                    select(models.Message)
                    .where(models.Message.thread_id == thread_id)
                    .order_by(models.Message.output_index.asc())
                )
            )
            .scalars()
            .all()
        )

    assert first_message is not None
    assert first_message.message_status == schemas.MessageStatus.COMPLETED
    assert first_message.phase == schemas.MessagePhase.FINAL_ANSWER.value
    assert run is not None
    assert run.status == schemas.RunStatus.IN_PROGRESS
    assert run.incomplete_reason is None
    assert len(messages) == 2
    assert [message.phase for message in messages] == [
        schemas.MessagePhase.FINAL_ANSWER.value,
        schemas.MessagePhase.COMMENTARY.value,
    ]


async def test_buffered_handler_accepts_final_answer_after_unknown_phase(db):
    handler, thread_id = await _setup_handler_with_phase(db, "future_phase")
    assert handler.message_id is not None
    assert handler.run_id is not None
    run_id = handler.run_id
    first_message_id = handler.message_id

    first_done_event = SimpleNamespace(
        id="msg-phase-1",
        status=schemas.MessageStatus.COMPLETED.value,
        phase="future_phase",
    )
    await handler.on_output_message_done(first_done_event)

    final_answer_event = SimpleNamespace(
        id="msg-phase-2",
        status=schemas.MessageStatus.IN_PROGRESS.value,
        role="assistant",
        phase=schemas.MessagePhase.FINAL_ANSWER.value,
    )
    await handler.on_output_message_created(final_answer_event)

    assert handler.force_stopped is False
    assert handler.run_id == run_id
    assert handler.message_id is not None

    async with db.async_session() as session:
        first_message = await session.get(models.Message, first_message_id)
        run = await session.get(models.Run, run_id)
        messages = (
            (
                await session.execute(
                    select(models.Message)
                    .where(models.Message.thread_id == thread_id)
                    .order_by(models.Message.output_index.asc())
                )
            )
            .scalars()
            .all()
        )

    assert first_message is not None
    assert first_message.message_status == schemas.MessageStatus.COMPLETED
    assert first_message.phase == "future_phase"
    assert run is not None
    assert run.status == schemas.RunStatus.IN_PROGRESS
    assert run.incomplete_reason is None
    assert len(messages) == 2
    assert [message.phase for message in messages] == [
        "future_phase",
        schemas.MessagePhase.FINAL_ANSWER.value,
    ]


async def test_buffered_handler_truncates_after_consecutive_final_answers(db):
    handler, _thread_id = await _setup_handler_with_phase(db, "final_answer")
    assert handler.message_id is not None
    assert handler.run_id is not None
    run_id = handler.run_id
    first_message_id = handler.message_id

    first_done_event = SimpleNamespace(
        id="msg-phase-1",
        status=schemas.MessageStatus.COMPLETED.value,
        phase=schemas.MessagePhase.FINAL_ANSWER.value,
    )
    await handler.on_output_message_done(first_done_event)

    second_final_answer_event = SimpleNamespace(
        id="msg-phase-2",
        status=schemas.MessageStatus.IN_PROGRESS.value,
        role="assistant",
        phase=schemas.MessagePhase.FINAL_ANSWER.value,
    )
    await handler.on_output_message_created(second_final_answer_event)

    assert handler.force_stopped is True
    assert handler.run_id is None
    assert handler.run_status is None
    assert handler.force_stop_incomplete_reason is None

    async with db.async_session() as session:
        first_message = await session.get(models.Message, first_message_id)
        run = await session.get(models.Run, run_id)
        messages = (
            (
                await session.execute(
                    select(models.Message)
                    .where(models.Message.run_id == run_id)
                    .order_by(models.Message.output_index.asc())
                )
            )
            .scalars()
            .all()
        )

    assert first_message is not None
    assert first_message.message_status == schemas.MessageStatus.COMPLETED
    assert run is not None
    assert run.status == schemas.RunStatus.COMPLETED
    assert run.incomplete_reason == "multi_message_truncate"
    assert len(messages) == 1
    assert messages[0].phase == schemas.MessagePhase.FINAL_ANSWER.value


@with_user(111)
@with_authz(grants=[("user:111", "can_view", "thread:2101")])
async def test_get_thread_skips_duplicate_assistant_messages(api, db, valid_user_token):
    class_id = 2001
    thread_id = 2101
    run_id = 2201
    await _create_server_thread(
        db,
        class_id=class_id,
        thread_id=thread_id,
        run_id=run_id,
    )

    response = api.get(
        f"/api/v1/class/{class_id}/thread/{thread_id}",
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )

    assert response.status_code == 200
    messages = response.json()["messages"]
    assert len(messages) == 1
    assert messages[0]["output_index"] == 2
    assert messages[0]["run_id"] == str(run_id)


@with_user(222)
@with_authz(grants=[("user:222", "can_view", "thread:7101")])
async def test_get_thread_shows_prompt_when_not_hidden(api, db, valid_user_token):
    class_id = 7001
    thread_id = 7101
    assistant_id = 7201
    instructions = "Visible instructions"

    await _create_thread_with_visible_prompt(
        db,
        class_id=class_id,
        thread_id=thread_id,
        assistant_id=assistant_id,
        instructions=instructions,
        hide_prompt=False,
    )

    response = api.get(
        f"/api/v1/class/{class_id}/thread/{thread_id}",
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )

    assert response.status_code == 200
    assert response.json()["instructions"] == instructions


@with_user(223)
@with_authz(grants=[("user:223", "can_view", "thread:7201")])
async def test_get_thread_hides_prompt_when_hidden(api, db, valid_user_token):
    class_id = 7101
    thread_id = 7201
    assistant_id = 7301
    instructions = "Hidden instructions"

    await _create_thread_with_visible_prompt(
        db,
        class_id=class_id,
        thread_id=thread_id,
        assistant_id=assistant_id,
        instructions=instructions,
        hide_prompt=True,
    )

    response = api.get(
        f"/api/v1/class/{class_id}/thread/{thread_id}",
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )

    assert response.status_code == 200
    assert response.json()["instructions"] is None


@with_user(333)
@with_authz(grants=[("user:333", "can_view", "thread:3101")])
async def test_list_thread_messages_deduplicates_extra_assistant_messages(
    api, db, valid_user_token
):
    class_id = 3001
    thread_id = 3101
    run_id = 3201
    await _create_server_thread_alt(
        db,
        class_id=class_id,
        thread_id=thread_id,
        run_id=run_id,
    )

    response = api.get(
        f"/api/v1/class/{class_id}/thread/{thread_id}/messages",
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )

    assert response.status_code == 200
    messages = response.json()["messages"]
    assert len(messages) == 1
    assert messages[0]["output_index"] == 3
    assert messages[0]["run_id"] == str(run_id)


@with_user(334)
@with_authz(grants=[("user:334", "can_view", "thread:3111")])
async def test_get_thread_keeps_phase_separated_assistant_messages(
    api, db, valid_user_token
):
    class_id = 3011
    thread_id = 3111
    run_id = 3211

    await _create_thread_with_phase_separated_assistant_messages(
        db,
        class_id=class_id,
        thread_id=thread_id,
        run_id=run_id,
        assistant_id=3311,
    )

    response = api.get(
        f"/api/v1/class/{class_id}/thread/{thread_id}",
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )

    assert response.status_code == 200
    messages = response.json()["messages"]
    assert len(messages) == 2
    assert [message["output_index"] for message in messages] == [2, 8]


@with_user(335)
@with_authz(grants=[("user:335", "can_view", "thread:3112")])
async def test_list_thread_messages_keeps_phase_separated_assistant_messages(
    api, db, valid_user_token
):
    class_id = 3012
    thread_id = 3112
    run_id = 3212

    await _create_thread_with_phase_separated_assistant_messages(
        db,
        class_id=class_id,
        thread_id=thread_id,
        run_id=run_id,
        assistant_id=3312,
    )

    response = api.get(
        f"/api/v1/class/{class_id}/thread/{thread_id}/messages",
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )

    assert response.status_code == 200
    messages = response.json()["messages"]
    assert len(messages) == 2
    assert [message["output_index"] for message in messages] == [2, 8]


@with_user(336)
@with_authz(grants=[("user:336", "can_view", "thread:3113")])
async def test_get_thread_keeps_unknown_phase_separated_assistant_messages(
    api, db, valid_user_token
):
    class_id = 3013
    thread_id = 3113
    run_id = 3213

    await _create_thread_with_phase_separated_assistant_messages(
        db,
        class_id=class_id,
        thread_id=thread_id,
        run_id=run_id,
        assistant_id=3313,
        older_phase="future_phase",
    )

    response = api.get(
        f"/api/v1/class/{class_id}/thread/{thread_id}",
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )

    assert response.status_code == 200
    messages = response.json()["messages"]
    assert len(messages) == 2
    assert [message["output_index"] for message in messages] == [2, 8]
    assert all(message["run_id"] == str(run_id) for message in messages)


@with_user(337)
@with_authz(grants=[("user:337", "can_view", "thread:3114")])
async def test_list_thread_messages_keeps_unknown_phase_separated_assistant_messages(
    api, db, valid_user_token
):
    class_id = 3014
    thread_id = 3114
    run_id = 3214

    await _create_thread_with_phase_separated_assistant_messages(
        db,
        class_id=class_id,
        thread_id=thread_id,
        run_id=run_id,
        assistant_id=3314,
        older_phase="future_phase",
    )

    response = api.get(
        f"/api/v1/class/{class_id}/thread/{thread_id}/messages",
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )

    assert response.status_code == 200
    messages = response.json()["messages"]
    assert len(messages) == 2
    assert [message["output_index"] for message in messages] == [2, 8]
    assert all(message["run_id"] == str(run_id) for message in messages)


@with_user(338)
@with_authz(grants=[("user:338", "can_view", "thread:3115")])
async def test_get_thread_deduplicates_unphased_assistant_messages(
    api, db, valid_user_token
):
    class_id = 3015
    thread_id = 3115
    run_id = 3215

    await _create_thread_with_unphased_assistant_messages(
        db,
        class_id=class_id,
        thread_id=thread_id,
        run_id=run_id,
        assistant_id=3315,
    )

    response = api.get(
        f"/api/v1/class/{class_id}/thread/{thread_id}",
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )

    assert response.status_code == 200
    messages = response.json()["messages"]
    assert len(messages) == 1
    assert messages[0]["output_index"] == 2
    assert messages[0]["run_id"] == str(run_id)


@with_user(339)
@with_authz(grants=[("user:339", "can_view", "thread:3116")])
async def test_list_thread_messages_deduplicates_unphased_assistant_messages(
    api, db, valid_user_token
):
    class_id = 3016
    thread_id = 3116
    run_id = 3216

    await _create_thread_with_unphased_assistant_messages(
        db,
        class_id=class_id,
        thread_id=thread_id,
        run_id=run_id,
        assistant_id=3316,
    )

    response = api.get(
        f"/api/v1/class/{class_id}/thread/{thread_id}/messages",
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )

    assert response.status_code == 200
    messages = response.json()["messages"]
    assert len(messages) == 1
    assert messages[0]["output_index"] == 2
    assert messages[0]["run_id"] == str(run_id)


@with_user(340)
@with_authz(grants=[("user:340", "can_view", "thread:3117")])
async def test_get_thread_keeps_unphased_messages_after_phased_output(
    api, db, valid_user_token
):
    class_id = 3017
    thread_id = 3117
    run_id = 3217

    await _create_thread_with_assistant_message_sequence(
        db,
        class_id=class_id,
        thread_id=thread_id,
        run_id=run_id,
        assistant_id=3317,
        phases=[schemas.MessagePhase.COMMENTARY.value, None, None],
    )

    response = api.get(
        f"/api/v1/class/{class_id}/thread/{thread_id}",
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )

    assert response.status_code == 200
    messages = response.json()["messages"]
    assert len(messages) == 3
    assert [message["output_index"] for message in messages] == [1, 2, 3]
    assert all(message["run_id"] == str(run_id) for message in messages)


@with_user(341)
@with_authz(grants=[("user:341", "can_view", "thread:3118")])
async def test_list_thread_messages_keeps_unphased_messages_after_phased_output(
    api, db, valid_user_token
):
    class_id = 3018
    thread_id = 3118
    run_id = 3218

    await _create_thread_with_assistant_message_sequence(
        db,
        class_id=class_id,
        thread_id=thread_id,
        run_id=run_id,
        assistant_id=3318,
        phases=[schemas.MessagePhase.COMMENTARY.value, None, None],
    )

    response = api.get(
        f"/api/v1/class/{class_id}/thread/{thread_id}/messages",
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )

    assert response.status_code == 200
    messages = response.json()["messages"]
    assert len(messages) == 3
    assert [message["output_index"] for message in messages] == [1, 2, 3]
    assert all(message["run_id"] == str(run_id) for message in messages)


async def test_buffered_handler_records_assistant_phase(db):
    handler, thread_id = await _setup_handler_with_phase(db, "commentary")
    assert handler.message_id is not None

    async with db.async_session() as session:
        message = await session.scalar(
            select(models.Message)
            .where(models.Message.thread_id == thread_id)
            .where(models.Message.message_id == "msg-phase-1")
        )

    assert message is not None
    assert message.phase == "commentary"


async def test_buffered_handler_preserves_unknown_assistant_phase(db):
    handler, thread_id = await _setup_handler_with_phase(db, "future_phase")
    assert handler.message_id is not None

    unknown_done_event = SimpleNamespace(
        id="msg-phase-1",
        status=schemas.MessageStatus.COMPLETED.value,
        phase="future_phase",
    )
    await handler.on_output_message_done(unknown_done_event)

    async with db.async_session() as session:
        message = await session.scalar(
            select(models.Message)
            .where(models.Message.thread_id == thread_id)
            .where(models.Message.message_id == "msg-phase-1")
        )

    assert message is not None
    assert message.phase == "future_phase"


@with_user(444)
@with_authz(grants=[("user:444", "can_view", "thread:4101")])
async def test_get_thread_keeps_assistant_message_after_tool_call(
    api, db, valid_user_token
):
    class_id = 4001
    thread_id = 4101
    run_id = 4201
    assistant_id = 4301

    await _create_thread_with_tool_call_between_messages(
        db,
        class_id=class_id,
        thread_id=thread_id,
        run_id=run_id,
        assistant_id=assistant_id,
    )

    response = api.get(
        f"/api/v1/class/{class_id}/thread/{thread_id}",
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )

    assert response.status_code == 200
    messages = response.json()["messages"]
    assert len(messages) == 2
    assert [message["output_index"] for message in messages] == [1, 3]
    assert all(message["run_id"] == str(run_id) for message in messages)


@with_user(545)
@with_authz(grants=[("user:545", "can_view", "thread:5101")])
async def test_list_thread_messages_keeps_assistant_message_after_tool_call(
    api, db, valid_user_token
):
    class_id = 5001
    thread_id = 5101
    run_id = 5201
    assistant_id = 5301

    await _create_thread_with_tool_call_between_messages(
        db,
        class_id=class_id,
        thread_id=thread_id,
        run_id=run_id,
        assistant_id=assistant_id,
    )

    response = api.get(
        f"/api/v1/class/{class_id}/thread/{thread_id}/messages",
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )

    assert response.status_code == 200
    messages = response.json()["messages"]
    assert len(messages) == 2
    assert [message["output_index"] for message in messages] == [1, 3]
    assert all(message["run_id"] == str(run_id) for message in messages)


@with_user(555)
@with_authz(grants=[("user:555", "can_view", "thread:6101")])
async def test_get_thread_includes_reasoning_messages(api, db, valid_user_token):
    class_id = 6001
    thread_id = 6101
    run_id = 6201
    assistant_id = 6301
    reasoning_step_id = 6401

    expected = await _create_server_thread_with_reasoning(
        db,
        class_id=class_id,
        thread_id=thread_id,
        run_id=run_id,
        assistant_id=assistant_id,
        reasoning_step_id=reasoning_step_id,
    )

    response = api.get(
        f"/api/v1/class/{class_id}/thread/{thread_id}",
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )

    assert response.status_code == 200
    reasoning_messages = response.json()["reasoning_messages"]
    assert len(reasoning_messages) == 1
    reasoning_message = reasoning_messages[0]

    assert reasoning_message["id"] == str(expected["reasoning_step_id"])
    assert reasoning_message["assistant_id"] == str(expected["assistant_id"])
    assert reasoning_message["thread_id"] == str(expected["thread_id"])
    assert reasoning_message["run_id"] == str(expected["run_id"])
    assert reasoning_message["output_index"] == expected["output_index"]
    assert reasoning_message["message_type"] == "reasoning"
    assert reasoning_message["role"] == "assistant"
    assert reasoning_message["metadata"] == {}
    assert reasoning_message["object"] == "thread.message"
    assert reasoning_message["created_at"] > 0

    assert len(reasoning_message["content"]) == 1
    call = reasoning_message["content"][0]
    assert call["type"] == "reasoning"
    assert call["step_id"] == expected["step_identifier"]
    assert call["status"] == expected["status"]
    actual_summary = sorted(call["summary"], key=lambda part: part["part_index"])
    expected_summary = sorted(
        expected["summary_parts"], key=lambda part: part["part_index"]
    )
    assert actual_summary == expected_summary


@with_user(777)
@with_authz(grants=[("user:777", "can_view", "thread:7101")])
async def test_list_thread_messages_includes_reasoning_messages(
    api, db, valid_user_token
):
    class_id = 7001
    thread_id = 7101
    run_id = 7201
    assistant_id = 7301
    reasoning_step_id = 7401

    expected = await _create_server_thread_with_reasoning(
        db,
        class_id=class_id,
        thread_id=thread_id,
        run_id=run_id,
        assistant_id=assistant_id,
        reasoning_step_id=reasoning_step_id,
    )

    response = api.get(
        f"/api/v1/class/{class_id}/thread/{thread_id}/messages",
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )

    assert response.status_code == 200
    reasoning_messages = response.json()["reasoning_messages"]
    assert len(reasoning_messages) == 1
    reasoning_message = reasoning_messages[0]

    assert reasoning_message["id"] == str(expected["reasoning_step_id"])
    assert reasoning_message["assistant_id"] == str(expected["assistant_id"])
    assert reasoning_message["thread_id"] == str(expected["thread_id"])
    assert reasoning_message["run_id"] == str(expected["run_id"])
    assert reasoning_message["output_index"] == expected["output_index"]
    assert reasoning_message["message_type"] == "reasoning"
    assert reasoning_message["role"] == "assistant"
    assert reasoning_message["metadata"] == {}
    assert reasoning_message["object"] == "thread.message"
    assert reasoning_message["created_at"] > 0

    assert len(reasoning_message["content"]) == 1
    call = reasoning_message["content"][0]
    assert call["type"] == "reasoning"
    assert call["step_id"] == expected["step_identifier"]
    assert call["status"] == expected["status"]
    actual_summary = sorted(call["summary"], key=lambda part: part["part_index"])
    expected_summary = sorted(
        expected["summary_parts"], key=lambda part: part["part_index"]
    )
    assert actual_summary == expected_summary


@with_user(888)
@with_authz(grants=[("user:888", "can_participate", "thread:8101")])
async def test_create_run_locks_thread_before_checking_latest_run(
    api, db, valid_user_token, monkeypatch
):
    base_time = datetime(2024, 1, 1, tzinfo=timezone.utc)

    async with db.async_session() as session:
        class_ = models.Class(id=8001, name="Run Lock Class", api_key="sk-test")
        assistant = models.Assistant(
            id=8002,
            name="Run Lock Assistant",
            class_id=class_.id,
            assistant_id="asst-run-lock",
            model="gpt-4o-mini",
            creator_id=888,
        )
        thread = models.Thread(
            id=8101,
            thread_id="thread-run-lock",
            class_id=class_.id,
            assistant_id=assistant.id,
            version=3,
            tools_available="",
            private=False,
            instructions="Existing instructions",
        )
        run = models.Run(
            id=8201,
            run_id="run-run-lock",
            status=schemas.RunStatus.COMPLETED,
            thread_id=thread.id,
            assistant_id=assistant.id,
            creator_id=888,
            created=base_time,
            updated=base_time,
            instructions="Existing instructions",
        )
        session.add_all([class_, assistant, thread, run])
        await session.commit()

    def fake_run_response(*args, **kwargs):
        async def stream():
            yield b"event: done\ndata: [DONE]\n\n"

        return stream()

    lock_calls: list[bool] = []
    original_get_by_id = models.Thread.get_by_id

    async def tracking_get_by_id(cls, session, id_, *, for_update=False):
        lock_calls.append(for_update)
        return await original_get_by_id.__func__(
            cls, session, id_, for_update=for_update
        )

    monkeypatch.setattr(server_module, "run_response", fake_run_response)
    monkeypatch.setattr(models.Thread, "get_by_id", classmethod(tracking_get_by_id))

    response = api.post(
        "/api/v1/class/8001/thread/8101/run",
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )

    assert response.status_code == 200
    assert any(lock_calls)
