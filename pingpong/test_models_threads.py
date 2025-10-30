import pytest
from datetime import datetime, timedelta, timezone

from pingpong import models, schemas


@pytest.mark.asyncio
async def test_get_run_window_paginates_runs(db):
    async with db.async_session() as session:
        thread = models.Thread(thread_id="thread_run_window", version=3)
        session.add(thread)
        await session.flush()

        base_time = datetime(2024, 1, 1, tzinfo=timezone.utc)
        created_runs: list[int] = []

        for offset in range(5):
            run = models.Run(
                status=schemas.RunStatus.COMPLETED,
                thread_id=thread.id,
                created=base_time + timedelta(minutes=offset),
                updated=base_time + timedelta(minutes=offset),
            )
            session.add(run)
            await session.flush()
            created_runs.append(run.id)

        await session.commit()
        thread_id = thread.id

    async with db.async_session() as session:
        run_ids_desc, has_more_desc = await models.Run.get_run_window(
            session, thread_id, limit=3, order="desc"
        )

    assert run_ids_desc == created_runs[::-1][:3]
    assert has_more_desc is True

    async with db.async_session() as session:
        run_ids_asc, has_more_asc = await models.Run.get_run_window(
            session,
            thread_id,
            limit=2,
            before_run_pk=created_runs[-1],
            order="asc",
        )

    assert run_ids_asc == created_runs[:2]
    assert has_more_asc is True

    async with db.async_session() as session:
        run_ids_tail, has_more_tail = await models.Run.get_run_window(
            session,
            thread_id,
            limit=2,
            before_run_pk=created_runs[1],
            order="asc",
        )

    assert run_ids_tail == created_runs[:1]
    assert has_more_tail is False


@pytest.mark.asyncio
async def test_list_messages_tool_calls_filters_and_orders(db):
    async with db.async_session() as session:
        thread = models.Thread(thread_id="thread_messages_tool_calls", version=3)
        session.add(thread)
        await session.flush()

        base_time = datetime(2024, 1, 1, tzinfo=timezone.utc)

        run_one = models.Run(
            status=schemas.RunStatus.COMPLETED,
            thread_id=thread.id,
            created=base_time,
            updated=base_time,
        )
        run_two = models.Run(
            status=schemas.RunStatus.COMPLETED,
            thread_id=thread.id,
            created=base_time + timedelta(minutes=1),
            updated=base_time + timedelta(minutes=1),
        )
        run_three = models.Run(
            status=schemas.RunStatus.COMPLETED,
            thread_id=thread.id,
            created=base_time + timedelta(minutes=2),
            updated=base_time + timedelta(minutes=2),
        )

        session.add_all([run_one, run_two, run_three])
        await session.flush()

        message_one = models.Message(
            message_status=schemas.MessageStatus.COMPLETED,
            run_id=run_one.id,
            thread_id=thread.id,
            output_index=1,
            role=schemas.MessageRole.USER,
        )
        message_two = models.Message(
            message_status=schemas.MessageStatus.COMPLETED,
            run_id=run_two.id,
            thread_id=thread.id,
            output_index=4,
            role=schemas.MessageRole.ASSISTANT,
        )
        message_three = models.Message(
            message_status=schemas.MessageStatus.COMPLETED,
            run_id=run_three.id,
            thread_id=thread.id,
            output_index=2,
            role=schemas.MessageRole.ASSISTANT,
        )

        session.add_all([message_one, message_two, message_three])

        tool_call_one = models.ToolCall(
            tool_call_id="tc_1",
            type=schemas.ToolCallType.CODE_INTERPRETER,
            status=schemas.ToolCallStatus.COMPLETED,
            run_id=run_one.id,
            thread_id=thread.id,
            output_index=1,
        )
        tool_call_two = models.ToolCall(
            tool_call_id="tc_2",
            type=schemas.ToolCallType.FILE_SEARCH,
            status=schemas.ToolCallStatus.COMPLETED,
            run_id=run_two.id,
            thread_id=thread.id,
            output_index=5,
        )
        tool_call_three = models.ToolCall(
            tool_call_id="tc_3",
            type=schemas.ToolCallType.CODE_INTERPRETER,
            status=schemas.ToolCallStatus.COMPLETED,
            run_id=run_three.id,
            thread_id=thread.id,
            output_index=3,
        )

        session.add_all([tool_call_one, tool_call_two, tool_call_three])
        await session.commit()

        run_ids = [run_one.id, run_two.id]
        message_ids = [message_one.id, message_two.id]
        tool_call_ids = [tool_call_one.id, tool_call_two.id]
        thread_id = thread.id

    async with db.async_session() as session:
        messages_asc, tool_calls_asc = await models.Thread.list_messages_tool_calls(
            session,
            thread_id,
            run_ids=run_ids,
            order="asc",
        )

    assert [message.id for message in messages_asc] == message_ids
    assert [tool_call.id for tool_call in tool_calls_asc] == tool_call_ids

    async with db.async_session() as session:
        messages_desc, tool_calls_desc = await models.Thread.list_messages_tool_calls(
            session,
            thread_id,
            run_ids=run_ids,
            order="desc",
        )

    assert [message.id for message in messages_desc] == message_ids[::-1]
    assert [tool_call.id for tool_call in tool_calls_desc] == tool_call_ids[::-1]
