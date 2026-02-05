from __future__ import annotations

import asyncio
import logging

import pytest

from pingpong.realtime import ConversationItemOrderingBuffer

pytestmark = pytest.mark.asyncio


def _task_factory(label: str):
    def factory(output_index: str):
        async def task():
            return label, output_index

        return task

    return factory


async def test_enqueue_dispatches_once_item_is_registered():
    queue: asyncio.Queue = asyncio.Queue()
    buffer = ConversationItemOrderingBuffer(queue, logging.getLogger("ordering-test"))

    task = _task_factory("item-1")

    await buffer.enqueue_message_task("item-1", task)
    assert queue.empty()

    buffer.register_relevant_item("item-1", None)
    await buffer.dispatch_ready_messages()

    dequeued = await queue.get()
    assert await dequeued() == ("item-1", "0")


async def test_dispatch_respects_previous_item_relationships():
    queue: asyncio.Queue = asyncio.Queue()
    buffer = ConversationItemOrderingBuffer(queue, logging.getLogger("ordering-test"))

    buffer.register_relevant_item("item-1", None)
    buffer.register_relevant_item("item-2", "item-1")

    task_two = _task_factory("item-2")
    task_one = _task_factory("item-1")

    await buffer.enqueue_message_task("item-2", task_two)
    await buffer.enqueue_message_task("item-1", task_one)

    first_task = await queue.get()
    second_task = await queue.get()

    assert await first_task() == ("item-1", "0")
    assert await second_task() == ("item-2", "1")


async def test_enqueue_without_item_id_logs_warning(caplog: pytest.LogCaptureFixture):
    queue: asyncio.Queue = asyncio.Queue()
    logger_name = "ordering-test-missing-id"
    buffer = ConversationItemOrderingBuffer(queue, logging.getLogger(logger_name))
    caplog.set_level(logging.WARNING, logger=logger_name)

    await buffer.enqueue_message_task(None, _task_factory("missing"))

    assert "Skipping message ordering" in caplog.text
    assert queue.empty()
    assert buffer.pending_message_tasks == {}


async def test_interleaving_transcripts_follow_conversation_order():
    queue: asyncio.Queue = asyncio.Queue()
    buffer = ConversationItemOrderingBuffer(queue, logging.getLogger("ordering-test"))

    buffer.register_relevant_item("user-1", None)
    buffer.register_relevant_item("assistant-1", "user-1")

    task_assistant_1 = _task_factory("assistant-1")
    await buffer.enqueue_message_task("assistant-1", task_assistant_1)
    assert queue.empty()

    buffer.register_relevant_item("user-2", "assistant-1")

    task_user_1 = _task_factory("user-1")
    await buffer.enqueue_message_task("user-1", task_user_1)

    dequeued_user_1 = await queue.get()
    dequeued_assistant_1 = await queue.get()
    assert await dequeued_user_1() == ("user-1", "0")
    assert await dequeued_assistant_1() == ("assistant-1", "1")

    buffer.register_relevant_item("assistant-2", "user-2")
    task_assistant_2 = _task_factory("assistant-2")
    await buffer.enqueue_message_task("assistant-2", task_assistant_2)
    assert queue.empty()

    task_user_2 = _task_factory("user-2")
    await buffer.enqueue_message_task("user-2", task_user_2)

    dequeued_user_2 = await queue.get()
    assert await dequeued_user_2() == ("user-2", "2")
    dequeued_assistant_2 = await queue.get()
    assert await dequeued_assistant_2() == ("assistant-2", "3")

    buffer.register_relevant_item("user-3", "assistant-2")
    assert queue.empty()


async def test_late_predecessor_registration_reorders_before_dispatch():
    queue: asyncio.Queue = asyncio.Queue()
    buffer = ConversationItemOrderingBuffer(queue, logging.getLogger("ordering-test"))

    buffer.register_relevant_item("assistant-1", "user-1")
    buffer.register_relevant_item("assistant-2", "assistant-1")

    await buffer.enqueue_message_task("assistant-2", _task_factory("assistant-2"))
    await buffer.enqueue_message_task("assistant-1", _task_factory("assistant-1"))
    assert queue.empty()

    buffer.register_relevant_item("user-1", None)
    await buffer.enqueue_message_task("user-1", _task_factory("user-1"))

    first_task = await queue.get()
    second_task = await queue.get()
    third_task = await queue.get()

    assert await first_task() == ("user-1", "0")
    assert await second_task() == ("assistant-1", "1")
    assert await third_task() == ("assistant-2", "2")


async def test_existing_item_can_adopt_late_previous_item_id():
    queue: asyncio.Queue = asyncio.Queue()
    buffer = ConversationItemOrderingBuffer(queue, logging.getLogger("ordering-test"))

    buffer.register_relevant_item("assistant-1", None)
    buffer.register_relevant_item("user-1", None)
    buffer.register_relevant_item("assistant-1", "user-1")

    await buffer.enqueue_message_task("assistant-1", _task_factory("assistant-1"))
    assert queue.empty()

    await buffer.enqueue_message_task("user-1", _task_factory("user-1"))

    first_task = await queue.get()
    second_task = await queue.get()

    assert await first_task() == ("user-1", "0")
    assert await second_task() == ("assistant-1", "1")
