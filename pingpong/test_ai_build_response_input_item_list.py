from datetime import timedelta

import pytest

from pingpong import models, schemas
from pingpong.ai import build_response_input_item_list
from pingpong.now import utcnow


@pytest.mark.asyncio
async def test_build_response_input_item_list_drops_reasoning_for_expired_ci(db):
    async with db.async_session() as session:
        thread = models.Thread(thread_id="thread_expired_ci", version=3)
        session.add(thread)
        await session.flush()

        run = models.Run(status=schemas.RunStatus.COMPLETED, thread_id=thread.id)
        session.add(run)
        await session.flush()

        base_time = utcnow() - timedelta(hours=1)

        message = models.Message(
            message_status=schemas.MessageStatus.COMPLETED,
            run_id=run.id,
            thread_id=thread.id,
            output_index=1,
            role=schemas.MessageRole.ASSISTANT,
            created=base_time + timedelta(minutes=1),
        )
        reasoning_one = models.ReasoningStep(
            run_id=run.id,
            thread_id=thread.id,
            reasoning_id="rst-1",
            output_index=2,
            status=schemas.ReasoningStatus.COMPLETED,
            created=base_time + timedelta(minutes=2),
        )
        reasoning_two = models.ReasoningStep(
            run_id=run.id,
            thread_id=thread.id,
            reasoning_id="rst-2",
            output_index=3,
            status=schemas.ReasoningStatus.COMPLETED,
            created=base_time + timedelta(minutes=3),
        )
        tool_call = models.ToolCall(
            tool_call_id="tc_1",
            type=schemas.ToolCallType.CODE_INTERPRETER,
            status=schemas.ToolCallStatus.COMPLETED,
            run_id=run.id,
            thread_id=thread.id,
            output_index=4,
            code="print('hi')",
            container_id="container-1",
            created=base_time + timedelta(minutes=4),
            completed=base_time + timedelta(minutes=5),
        )

        session.add_all([message, reasoning_one, reasoning_two, tool_call])
        await session.commit()

        thread_id = thread.id

    async with db.async_session() as session:
        items = await build_response_input_item_list(
            session, thread_id=thread_id, uses_reasoning=True
        )

    item_types = [item.get("type") for item in items if "type" in item]
    assert "code_interpreter_call" not in item_types
    assert "reasoning" not in item_types

    summary_messages = [item for item in items if isinstance(item.get("content"), str)]
    assert len(summary_messages) == 1
    assert "code interpreter tool" in summary_messages[0]["content"]


@pytest.mark.asyncio
async def test_build_response_input_item_list_keeps_reasoning_for_active_ci(db):
    async with db.async_session() as session:
        thread = models.Thread(thread_id="thread_active_ci", version=3)
        session.add(thread)
        await session.flush()

        run = models.Run(status=schemas.RunStatus.COMPLETED, thread_id=thread.id)
        session.add(run)
        await session.flush()

        base_time = utcnow() - timedelta(minutes=5)

        message = models.Message(
            message_status=schemas.MessageStatus.COMPLETED,
            run_id=run.id,
            thread_id=thread.id,
            output_index=1,
            role=schemas.MessageRole.ASSISTANT,
            created=base_time + timedelta(minutes=1),
        )
        reasoning = models.ReasoningStep(
            run_id=run.id,
            thread_id=thread.id,
            reasoning_id="rst-active",
            output_index=2,
            status=schemas.ReasoningStatus.COMPLETED,
            created=base_time + timedelta(minutes=2),
        )
        tool_call = models.ToolCall(
            tool_call_id="tc_active",
            type=schemas.ToolCallType.CODE_INTERPRETER,
            status=schemas.ToolCallStatus.COMPLETED,
            run_id=run.id,
            thread_id=thread.id,
            output_index=3,
            code="print('ok')",
            container_id="container-active",
            created=base_time + timedelta(minutes=3),
            completed=base_time + timedelta(minutes=4),
        )

        session.add_all([message, reasoning, tool_call])
        await session.commit()

        thread_id = thread.id

    async with db.async_session() as session:
        items = await build_response_input_item_list(
            session, thread_id=thread_id, uses_reasoning=True
        )

    item_types = [item.get("type") for item in items if "type" in item]
    assert "code_interpreter_call" in item_types
    assert "reasoning" in item_types
    assert not any(
        isinstance(item.get("content"), str)
        and "code interpreter tool" in item["content"]
        for item in items
    )


@pytest.mark.asyncio
async def test_build_response_input_item_list_drops_only_contiguous_reasoning(db):
    async with db.async_session() as session:
        thread = models.Thread(thread_id="thread_contiguous_reasoning", version=3)
        session.add(thread)
        await session.flush()

        run = models.Run(status=schemas.RunStatus.COMPLETED, thread_id=thread.id)
        session.add(run)
        await session.flush()

        base_time = utcnow() - timedelta(hours=1)

        message_one = models.Message(
            message_status=schemas.MessageStatus.COMPLETED,
            run_id=run.id,
            thread_id=thread.id,
            output_index=1,
            role=schemas.MessageRole.ASSISTANT,
            created=base_time + timedelta(minutes=1),
        )
        reasoning_keep = models.ReasoningStep(
            run_id=run.id,
            thread_id=thread.id,
            reasoning_id="rst-keep",
            output_index=2,
            status=schemas.ReasoningStatus.COMPLETED,
            created=base_time + timedelta(minutes=2),
        )
        message_two = models.Message(
            message_status=schemas.MessageStatus.COMPLETED,
            run_id=run.id,
            thread_id=thread.id,
            output_index=3,
            role=schemas.MessageRole.ASSISTANT,
            created=base_time + timedelta(minutes=3),
        )
        reasoning_drop = models.ReasoningStep(
            run_id=run.id,
            thread_id=thread.id,
            reasoning_id="rst-drop",
            output_index=4,
            status=schemas.ReasoningStatus.COMPLETED,
            created=base_time + timedelta(minutes=4),
        )
        tool_call = models.ToolCall(
            tool_call_id="tc_expired",
            type=schemas.ToolCallType.CODE_INTERPRETER,
            status=schemas.ToolCallStatus.COMPLETED,
            run_id=run.id,
            thread_id=thread.id,
            output_index=5,
            code="print('expired')",
            container_id="container-expired",
            created=base_time + timedelta(minutes=5),
            completed=base_time + timedelta(minutes=6),
        )

        session.add_all(
            [message_one, reasoning_keep, message_two, reasoning_drop, tool_call]
        )
        await session.commit()

        thread_id = thread.id

    async with db.async_session() as session:
        items = await build_response_input_item_list(
            session, thread_id=thread_id, uses_reasoning=True
        )

    reasoning_ids = [
        item.get("id") for item in items if item.get("type") == "reasoning"
    ]
    assert "rst-keep" in reasoning_ids
    assert "rst-drop" not in reasoning_ids
