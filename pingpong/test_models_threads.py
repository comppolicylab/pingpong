import pytest
from datetime import datetime, timedelta, timezone

from pingpong import models, schemas


@pytest.mark.asyncio
async def test_get_run_window_paginates_runs(db):
    """
    Test that demonstrates the pagination bug when loading older messages.

    Setup: Create 10 runs in chronological order (run_0 oldest -> run_9 newest)

    Expected pagination behavior (loading older messages):
    1. First page: Get latest 3 runs [run_9, run_8, run_7] (desc order)
    2. Second page: Load older messages before run_7, should get [run_6, run_5, run_4]
    3. Third page: Load older messages before run_4, should get [run_3, run_2, run_1]
    4. Fourth page: Load older messages before run_1, should get [run_0]

    Bug: When calling get_run_window with order="asc" and before_run_pk=run_7,
    it returns [run_0, run_1, run_2] (the EARLIEST runs) instead of
    [run_6, run_5, run_4] (the runs IMMEDIATELY BEFORE run_7).
    """
    async with db.async_session() as session:
        thread = models.Thread(thread_id="thread_run_window", version=3)
        session.add(thread)
        await session.flush()

        base_time = datetime(2024, 1, 1, tzinfo=timezone.utc)
        created_runs: list[int] = []

        # Create 10 runs to make the pagination bug more obvious
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

    # Page 1: Get the 3 most recent runs (descending order)
    async with db.async_session() as session:
        run_ids_page1, has_more_page1 = await models.Run.get_run_window(
            session, thread_id, limit=3, order="desc"
        )

    # Should return runs [9, 8, 7] in desc order
    assert run_ids_page1 == [created_runs[9], created_runs[8], created_runs[7]]
    assert has_more_page1 is True

    # Page 2: Load older messages before run_7 (using asc order for UI display)
    # This simulates what list_thread_messages does when paginating backwards
    async with db.async_session() as session:
        run_ids_page2, has_more_page2 = await models.Run.get_run_window(
            session,
            thread_id,
            limit=3,
            before_run_pk=created_runs[7],  # Load runs before run_7
            order="asc",
        )

    # BUG: Currently returns [run_0, run_1, run_2] - the EARLIEST runs
    # EXPECTED: Should return [run_4, run_5, run_6] - runs immediately before run_7
    # (in ascending order for display, but still the correct window)
    print("\nPage 2 results (runs before run_7):")
    print(f"  Expected: {[created_runs[4], created_runs[5], created_runs[6]]}")
    print(f"  Actual:   {run_ids_page2}")

    # This assertion will FAIL, demonstrating the bug
    assert run_ids_page2 == [created_runs[4], created_runs[5], created_runs[6]], (
        "Bug confirmed: get_run_window skipped to earliest runs instead of runs immediately before pivot"
    )
    assert has_more_page2 is True

    # Page 3: Load older messages before run_4
    async with db.async_session() as session:
        run_ids_page3, has_more_page3 = await models.Run.get_run_window(
            session,
            thread_id,
            limit=3,
            before_run_pk=created_runs[4],  # Load runs before run_4
            order="asc",
        )

    # Should return [run_1, run_2, run_3]
    assert run_ids_page3 == [created_runs[1], created_runs[2], created_runs[3]]
    assert has_more_page3 is True

    # Page 4: Load older messages before run_1
    async with db.async_session() as session:
        run_ids_page4, has_more_page4 = await models.Run.get_run_window(
            session,
            thread_id,
            limit=3,
            before_run_pk=created_runs[1],  # Load runs before run_1
            order="asc",
        )

    # Should return only [run_0], with has_more=False
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

        # Create 12 runs
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

    # Simulate continuous pagination collecting all runs
    all_paginated_runs = []
    page_size = 3
    before_run = None

    # First page: newest runs
    async with db.async_session() as session:
        run_ids, has_more = await models.Run.get_run_window(
            session, thread_id, limit=page_size, order="desc"
        )
    all_paginated_runs.extend(run_ids)
    before_run = run_ids[-1]  # Oldest run in this page
    print(f"\nPage 1: {run_ids} (newest runs)")

    # Continue paginating until no more runs
    page_num = 2
    while has_more:
        async with db.async_session() as session:
            run_ids, has_more = await models.Run.get_run_window(
                session,
                thread_id,
                limit=page_size,
                before_run_pk=before_run,
                order="asc",  # BUG: This causes incorrect pagination
            )

        print(f"Page {page_num}: {run_ids} (older runs before run {before_run})")

        if run_ids:
            # When displaying in desc order, we'd reverse these
            # But the bug is in which runs are selected, not display order
            all_paginated_runs.extend(run_ids[::-1])  # Reverse to maintain desc order
            before_run = run_ids[0]  # New pivot for next page

        page_num += 1

        # Safety check to prevent infinite loop
        if page_num > 10:
            break

    print(f"\nAll runs collected via pagination: {all_paginated_runs}")
    print(f"Expected (all runs in desc order): {created_runs[::-1]}")
    print(f"Missing runs: {set(created_runs) - set(all_paginated_runs)}")

    # This will FAIL due to the bug: runs will be skipped during pagination
    assert all_paginated_runs == created_runs[::-1], (
        f"Pagination skipped runs! Missing: {set(created_runs) - set(all_paginated_runs)}"
    )


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
