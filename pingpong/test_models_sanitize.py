from __future__ import annotations

from datetime import datetime, timezone

import pytest

from sqlalchemy import select

from pingpong import models, schemas

pytestmark = pytest.mark.asyncio


async def _create_base_entities(session) -> dict[str, int]:
    base_time = datetime(2024, 1, 1, tzinfo=timezone.utc)
    user = models.User(
        id=7001,
        email="sanitize@test.dev",
        state=schemas.UserState.VERIFIED,
    )
    class_ = models.Class(id=7002, name="Sanitize Class", api_key="sk-test")
    assistant = models.Assistant(
        id=7003,
        name="Sanitize Assistant",
        class_id=class_.id,
        assistant_id="asst-sanitize",
        model="gpt-4o-mini",
        creator_id=user.id,
    )
    thread = models.Thread(
        id=7004,
        thread_id="thread-sanitize",
        class_id=class_.id,
        assistant_id=assistant.id,
        version=3,
        tools_available="",
        private=False,
    )
    run = models.Run(
        id=7005,
        run_id="run-sanitize",
        status=schemas.RunStatus.IN_PROGRESS,
        thread_id=thread.id,
        assistant_id=assistant.id,
        creator_id=user.id,
        created=base_time,
        updated=base_time,
    )
    session.add_all([user, class_, assistant, thread, run])
    await session.commit()
    return {
        "user_id": user.id,
        "class_id": class_.id,
        "assistant_id": assistant.id,
        "thread_id": thread.id,
        "run_id": run.id,
    }


async def _create_tool_call(session, *, run_id: int, thread_id: int) -> models.ToolCall:
    tool_call = models.ToolCall(
        tool_call_id="tool-sanitize",
        type=schemas.ToolCallType.FILE_SEARCH,
        status=schemas.ToolCallStatus.COMPLETED,
        run_id=run_id,
        thread_id=thread_id,
        output_index=0,
    )
    session.add(tool_call)
    await session.commit()
    return tool_call


async def _create_message(session, *, run_id: int, thread_id: int, assistant_id: int):
    message = models.Message(
        message_status=schemas.MessageStatus.IN_PROGRESS,
        run_id=run_id,
        thread_id=thread_id,
        assistant_id=assistant_id,
        role=schemas.MessageRole.ASSISTANT,
        output_index=0,
        created=datetime(2024, 1, 1, tzinfo=timezone.utc),
    )
    session.add(message)
    await session.commit()
    return message


async def _create_reasoning_step(session, *, run_id: int, thread_id: int):
    reasoning = models.ReasoningStep(
        reasoning_id="reasoning-sanitize",
        run_id=run_id,
        thread_id=thread_id,
        output_index=0,
        status=schemas.ReasoningStatus.IN_PROGRESS,
    )
    session.add(reasoning)
    await session.commit()
    return reasoning


async def test_file_search_call_result_strips_nulls(db):
    async with db.async_session() as session:
        ids = await _create_base_entities(session)
        tool_call = await _create_tool_call(
            session, run_id=ids["run_id"], thread_id=ids["thread_id"]
        )
        data = {
            "attributes": "{}",
            "file_id": "file-123",
            "file_object_id": None,
            "filename": "doc.txt",
            "tool_call_id": tool_call.id,
            "score": 0.9,
            "text": "hello\x00world",
            "created": datetime(2024, 1, 1, tzinfo=timezone.utc),
        }
        await models.FileSearchCallResult.create(session, data)
        await session.commit()

        stmt = select(models.FileSearchCallResult).where(
            models.FileSearchCallResult.tool_call_id == tool_call.id
        )
        result = (await session.execute(stmt)).scalar_one()
        assert "\x00" not in (result.text or "")
        assert result.text == "helloworld"


async def test_message_part_add_text_delta_strips_nulls(db):
    async with db.async_session() as session:
        ids = await _create_base_entities(session)
        message = await _create_message(
            session,
            run_id=ids["run_id"],
            thread_id=ids["thread_id"],
            assistant_id=ids["assistant_id"],
        )
        part = models.MessagePart(
            message_id=message.id,
            part_index=0,
            type=schemas.MessagePartType.OUTPUT_TEXT,
            text="hi",
        )
        session.add(part)
        await session.commit()

        await models.MessagePart.add_text_delta(session, part.id, "a\x00b")
        await session.commit()

        refreshed = await session.get(models.MessagePart, part.id)
        assert refreshed is not None
        assert "\x00" not in (refreshed.text or "")
        assert refreshed.text == "hiab"


async def test_reasoning_summary_delta_strips_nulls(db):
    async with db.async_session() as session:
        ids = await _create_base_entities(session)
        reasoning = await _create_reasoning_step(
            session, run_id=ids["run_id"], thread_id=ids["thread_id"]
        )
        summary = models.ReasoningSummaryPart(
            reasoning_step_id=reasoning.id,
            part_index=0,
            summary_text="sum",
        )
        session.add(summary)
        await session.commit()

        await models.ReasoningSummaryPart.add_summary_text_delta(
            session, summary.id, "a\x00b"
        )
        await session.commit()

        refreshed = await session.get(models.ReasoningSummaryPart, summary.id)
        assert refreshed is not None
        assert "\x00" not in (refreshed.summary_text or "")
        assert refreshed.summary_text == "sumab"


async def test_tool_call_mcp_arguments_delta_strips_nulls(db):
    async with db.async_session() as session:
        ids = await _create_base_entities(session)
        tool_call = models.ToolCall(
            tool_call_id="tool-mcp",
            type=schemas.ToolCallType.MCP_SERVER,
            status=schemas.ToolCallStatus.IN_PROGRESS,
            run_id=ids["run_id"],
            thread_id=ids["thread_id"],
            output_index=1,
        )
        session.add(tool_call)
        await session.commit()

        await models.ToolCall.add_mcp_arguments_delta(
            session, tool_call.id, "x\x00y"
        )
        await session.commit()

        stmt = select(models.ToolCall.mcp_arguments).where(
            models.ToolCall.id == tool_call.id
        )
        mcp_arguments = (await session.execute(stmt)).scalar_one()
        assert "\x00" not in (mcp_arguments or "")
        assert mcp_arguments == "xy"
