import pytest
from datetime import datetime, timedelta, timezone

from pingpong import models, schemas


@pytest.mark.asyncio
async def test_get_run_window_paginates_runs(db):
    """
    Test that get_run_window correctly paginates runs in a thread.

    This test simulates how list_thread_messages should work when paginating
    backwards through runs in a thread. It verifies that no runs are skipped
    during pagination.
    """
    async with db.async_session() as session:
        thread = models.Thread(thread_id="thread_run_window", version=3)
        session.add(thread)
        await session.flush()

        base_time = datetime(2024, 1, 1, tzinfo=timezone.utc)
        created_runs: list[int] = []

        for offset in range(10):
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
        run_ids_page1, has_more_page1 = await models.Run.get_run_window(
            session, thread_id, limit=3, order="desc"
        )

    assert run_ids_page1 == [created_runs[9], created_runs[8], created_runs[7]]
    assert has_more_page1 is True

    async with db.async_session() as session:
        run_ids_page2, has_more_page2 = await models.Run.get_run_window(
            session,
            thread_id,
            limit=3,
            before_run_pk=created_runs[7],
            order="asc",
        )

    assert run_ids_page2 == [created_runs[4], created_runs[5], created_runs[6]]
    assert has_more_page2 is True

    async with db.async_session() as session:
        run_ids_page3, has_more_page3 = await models.Run.get_run_window(
            session,
            thread_id,
            limit=3,
            before_run_pk=created_runs[4],
            order="asc",
        )

    assert run_ids_page3 == [created_runs[1], created_runs[2], created_runs[3]]
    assert has_more_page3 is True

    async with db.async_session() as session:
        run_ids_page4, has_more_page4 = await models.Run.get_run_window(
            session,
            thread_id,
            limit=3,
            before_run_pk=created_runs[1],
            order="asc",
        )

    assert run_ids_page4 == [created_runs[0]]
    assert has_more_page4 is False


@pytest.mark.asyncio
async def test_get_run_window_continuous_pagination(db):
    """
    Test continuous backward pagination to verify no runs are skipped.

    This test simulates how list_thread_messages should work when a user
    repeatedly clicks "load more" to see older messages. Each page should
    contain the runs immediately before the previous page's oldest run.
    """
    async with db.async_session() as session:
        thread = models.Thread(thread_id="thread_continuous_pagination", version=3)
        session.add(thread)
        await session.flush()

        base_time = datetime(2024, 1, 1, tzinfo=timezone.utc)
        created_runs: list[int] = []

        for offset in range(12):
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

    all_paginated_runs = []
    page_size = 3
    before_run = None

    async with db.async_session() as session:
        run_ids, has_more = await models.Run.get_run_window(
            session, thread_id, limit=page_size, order="desc"
        )
    all_paginated_runs.extend(run_ids)
    before_run = run_ids[-1]

    page_num = 2
    while has_more:
        async with db.async_session() as session:
            run_ids, has_more = await models.Run.get_run_window(
                session,
                thread_id,
                limit=page_size,
                before_run_pk=before_run,
                order="asc",
            )

        if run_ids:
            all_paginated_runs.extend(run_ids[::-1])
            before_run = run_ids[0]

        page_num += 1

        # Safety check to prevent infinite loop
        if page_num > 10:
            break

    assert all_paginated_runs == created_runs[::-1]


@pytest.mark.asyncio
async def test_list_messages_tool_calls_filters_and_orders(db):
    """
    Test filtering and ordering of messages and tool calls.
    """
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

        reasoning_step_one = models.ReasoningStep(
            run_id=run_one.id,
            thread_id=thread.id,
            reasoning_id="rst_1",
            output_index=6,
            status=schemas.ReasoningStatus.COMPLETED,
        )
        reasoning_step_two = models.ReasoningStep(
            run_id=run_two.id,
            thread_id=thread.id,
            reasoning_id="rst_2",
            output_index=7,
            status=schemas.ReasoningStatus.IN_PROGRESS,
        )
        reasoning_step_three = models.ReasoningStep(
            run_id=run_three.id,
            thread_id=thread.id,
            reasoning_id="rst_3",
            output_index=8,
            status=schemas.ReasoningStatus.COMPLETED,
        )

        session.add_all([reasoning_step_one, reasoning_step_two, reasoning_step_three])
        await session.commit()

        run_ids = [run_one.id, run_two.id]
        message_ids = [message_one.id, message_two.id]
        tool_call_ids = [tool_call_one.id, tool_call_two.id]
        reasoning_ids = [reasoning_step_one.id, reasoning_step_two.id]
        thread_id = thread.id

    async with db.async_session() as session:
        (
            messages_asc,
            tool_calls_asc,
            reasoning_steps_asc,
        ) = await models.Thread.list_messages_tool_calls(
            session,
            thread_id,
            run_ids=run_ids,
            order="asc",
        )

    assert [message.id for message in messages_asc] == message_ids
    assert [tool_call.id for tool_call in tool_calls_asc] == tool_call_ids
    assert [reasoning.id for reasoning in reasoning_steps_asc] == reasoning_ids

    async with db.async_session() as session:
        (
            messages_desc,
            tool_calls_desc,
            reasoning_steps_desc,
        ) = await models.Thread.list_messages_tool_calls(
            session,
            thread_id,
            run_ids=run_ids,
            order="desc",
        )

    assert [message.id for message in messages_desc] == message_ids[::-1]
    assert [tool_call.id for tool_call in tool_calls_desc] == tool_call_ids[::-1]
    assert [reasoning.id for reasoning in reasoning_steps_desc] == reasoning_ids[::-1]
