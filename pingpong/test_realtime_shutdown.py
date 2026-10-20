import asyncio
import inspect
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from pingpong import realtime
from pingpong.test_server_audio_websocket import DummyWebSocket


def event(event_type, **fields):
    return SimpleNamespace(type=event_type, **fields)


def shutdown_ack():
    return event(
        "session.updated",
        session=SimpleNamespace(
            audio=SimpleNamespace(input=SimpleNamespace(turn_detection=None))
        ),
    )


class ShutdownConnection:
    def __init__(self):
        self.events = asyncio.Queue()
        self.session = SimpleNamespace(update=AsyncMock())
        self.response = SimpleNamespace(cancel=AsyncMock(), create=AsyncMock())
        self.input_audio_buffer = SimpleNamespace(
            clear=AsyncMock(), commit=AsyncMock(), append=AsyncMock()
        )
        self.reader_stopped = asyncio.Event()

    async def __aiter__(self):
        try:
            while True:
                incoming = await self.events.get()
                if incoming is None:
                    return
                yield incoming
        finally:
            self.reader_stopped.set()

    def assert_only_shutdown_update(self):
        self.session.update.assert_awaited_once_with(
            session={"type": "realtime", "audio": {"input": {"turn_detection": None}}}
        )
        self.response.cancel.assert_not_awaited()
        self.response.create.assert_not_awaited()
        self.input_audio_buffer.clear.assert_not_awaited()
        self.input_audio_buffer.commit.assert_not_awaited()
        self.input_audio_buffer.append.assert_not_awaited()


async def wait_until(predicate):
    async with asyncio.timeout(1):
        while not predicate():
            await asyncio.sleep(0)


async def playback_buffer(*heard_item_ids):
    tracker = realtime.RealtimeAssistantAudioTracker()
    for item_id in heard_item_ids:
        await tracker.add_audio_delta(item_id, item_id, b"\0\0")
        await tracker.mark_audio_event_playback_started(item_id, item_id)
    return realtime.ConversationItemOrderingBuffer(
        logging.getLogger(__name__), assistant_audio_tracker=tracker
    )


@pytest.mark.parametrize("failed", [False, True])
@pytest.mark.parametrize("assistant_first", [False, True])
async def test_early_drain_requires_ack_and_retained_transcripts(
    failed, assistant_first
):
    drain = realtime.RealtimeShutdownDrain()
    connection = ShutdownConnection()
    buffer = await playback_buffer("reply")
    buffer.register_conversation_item("user", None, "user")
    buffer.register_conversation_item("reply", "user", "assistant")
    # Startup/old updates cannot acknowledge shutdown.
    drain.observe(shutdown_ack())
    task = asyncio.create_task(drain.wait(connection, buffer))
    try:
        await wait_until(lambda: connection.session.update.await_count == 1)
        assert not task.done()
        # Delayed commits before the shutdown acknowledgement are included.
        drain.observe(event("input_audio_buffer.committed", item_id="user"))
        drain.observe(shutdown_ack())
        roles = ["assistant", "user"] if assistant_first else ["user", "assistant"]
        for index, role in enumerate(roles):
            if role == "assistant":
                buffer.register_transcription("reply", "answer", "assistant")
                drain.observe(
                    event("response.output_audio_transcript.done", item_id="reply")
                )
            else:
                if failed:
                    buffer.fail_transcription("user")
                else:
                    buffer.register_transcription("user", "question", "user")
                drain.observe(
                    event(
                        "conversation.item.input_audio_transcription."
                        + ("failed" if failed else "completed"),
                        item_id="user",
                    )
                )
            if index == 0:
                await asyncio.sleep(0)
                assert not task.done()
        # A heard reply needs its transcript, not the end of unheard generation.
        await asyncio.wait_for(task, 1)
        connection.assert_only_shutdown_update()
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


async def test_already_settled_session_exits_on_ack_without_waiting_five_seconds():
    drain = realtime.RealtimeShutdownDrain()
    connection = ShutdownConnection()
    drain.observe(event("response.created", response=SimpleNamespace(id="reply")))
    drain.observe(event("response.done", response=SimpleNamespace(id="reply")))
    drain.observe(
        event("conversation.item.input_audio_transcription.completed", item_id="user")
    )
    # A delayed commit or duplicate delta must not reopen completed transcription.
    drain.observe(event("input_audio_buffer.committed", item_id="user"))
    drain.observe(
        event("conversation.item.input_audio_transcription.delta", item_id="user")
    )
    # Uncommitted speech must not be committed or awaited by this drain.
    drain.observe(event("input_audio_buffer.speech_started", item_id="unfinished"))
    task = asyncio.create_task(
        drain.wait(
            connection,
            realtime.ConversationItemOrderingBuffer(logging.getLogger(__name__)),
        )
    )
    try:
        await wait_until(lambda: connection.session.update.await_count == 1)
        assert not task.done()
        drain.observe(shutdown_ack())
        await asyncio.wait_for(task, 1)
        connection.assert_only_shutdown_update()
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.parametrize(
    "failure",
    [
        "missing_ack",
        "pending_transcript",
        "pending_heard_transcript",
        "send_error",
        "stalled_send",
    ],
)
async def test_missing_events_and_failed_controls_keep_the_original_deadline(
    monkeypatch, failure
):
    monkeypatch.setattr(realtime, "BROWSER_DISCONNECT_DRAIN_SECONDS", 0.02)
    drain = realtime.RealtimeShutdownDrain()
    connection = ShutdownConnection()
    buffer = (
        await playback_buffer("reply")
        if failure == "pending_heard_transcript"
        else await playback_buffer()
    )
    if failure == "pending_transcript":
        drain.observe(event("input_audio_buffer.speech_stopped", item_id="user"))
    elif failure == "send_error":
        connection.session.update.side_effect = OSError("synthetic failure")
    elif failure == "stalled_send":

        async def stalled(**kwargs):
            await asyncio.Future()

        connection.session.update.side_effect = stalled
    task = asyncio.create_task(drain.wait(connection, buffer))
    try:
        await wait_until(lambda: connection.session.update.await_count == 1)
        if failure in {"pending_transcript", "pending_heard_transcript"}:
            drain.observe(shutdown_ack())
        await asyncio.sleep(0)
        assert not task.done()
        await asyncio.wait_for(task, 1)
        connection.assert_only_shutdown_update()
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.parametrize(
    "ending",
    [
        "early",
        "snapshot",
        "timeout",
        "rejected_update",
        "provider_closed",
        "parent_cancel",
    ],
)
@pytest.mark.parametrize("played", [False, True])
async def test_session_cleanup_keeps_late_text_and_playback_retention(
    monkeypatch, ending, played
):
    connection = ShutdownConnection()
    websocket = DummyWebSocket()
    websocket.state["thread"] = SimpleNamespace(version=1, display_user_info=False)
    websocket.state["openai_client"] = None
    websocket.state["realtime_connection"] = connection
    websocket.state["db"] = AsyncMock()
    write = AsyncMock(return_value=True)
    monkeypatch.setattr(realtime, "add_message_to_thread", write)
    if ending in {"timeout", "rejected_update"}:
        monkeypatch.setattr(realtime, "BROWSER_DISCONNECT_DRAIN_SECONDS", 0.05)

    async def browser(ws, provider, tracker, *args, **kwargs):
        await tracker.add_audio_delta("reply", "audio", b"\0\0")
        if played:
            await tracker.mark_audio_event_playback_started("reply", "audio")
        await tracker.mark_item_playback_settled(
            "reply", "interrupted" if played else "discarded", played
        )

    monkeypatch.setattr(realtime, "handle_browser_messages", browser)
    for incoming in [
        event("input_audio_buffer.committed", item_id="user"),
        event(
            "conversation.item.added",
            previous_item_id=None,
            item=SimpleNamespace(id="user", type="message", role="user"),
        ),
        event(
            "conversation.item.input_audio_transcription.delta",
            item_id="user",
            delta="partial question",
        ),
        event("response.created", response=SimpleNamespace(id="response")),
        event(
            "conversation.item.added",
            previous_item_id="user",
            item=SimpleNamespace(id="reply", type="message", role="assistant"),
        ),
        event(
            "response.output_audio_transcript.delta",
            item_id="reply",
            delta="partial answer",
        ),
    ]:
        connection.events.put_nowait(incoming)
    task = asyncio.create_task(
        inspect.unwrap(realtime.browser_realtime_websocket)(websocket, "1", "1")
    )
    try:
        await wait_until(lambda: connection.session.update.await_count == 1)
        if ending == "provider_closed":
            connection.events.put_nowait(None)
        elif ending == "parent_cancel":
            task.cancel()
        else:
            connection.events.put_nowait(
                event(
                    "error",
                    error=SimpleNamespace(param="session.audio.input.turn_detection"),
                )
                if ending == "rejected_update"
                else shutdown_ack()
            )
            if ending != "timeout":
                connection.events.put_nowait(
                    event(
                        "response.done",
                        response=SimpleNamespace(
                            id="response",
                            output=[
                                SimpleNamespace(
                                    id="reply",
                                    type="message",
                                    role="assistant",
                                    content=[
                                        SimpleNamespace(
                                            type="output_audio",
                                            transcript="final answer",
                                        )
                                    ],
                                )
                            ]
                            if ending == "snapshot"
                            else [],
                        ),
                    )
                )
                if ending != "snapshot":
                    connection.events.put_nowait(
                        event(
                            "response.output_audio_transcript.done",
                            item_id="reply",
                            transcript="final answer",
                        )
                    )
                connection.events.put_nowait(
                    event(
                        "conversation.item.input_audio_transcription.completed",
                        item_id="user",
                        transcript="late question",
                    )
                )
        if ending == "parent_cancel":
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(task, 1)
            websocket.state["db"].commit.assert_awaited_once()
        else:
            await asyncio.wait_for(task, 1)
        assert connection.reader_stopped.is_set()
        assert websocket.closed
        assert [call.args[3] for call in write.await_args_list] == (
            ["user", "reply"] if played else []
        )
        if played:
            expected = (
                ["late question", "final answer"]
                if ending in {"early", "snapshot", "rejected_update"}
                else ["partial question", "partial answer"]
            )
            assert [call.args[4] for call in write.await_args_list] == expected
            assert all(
                call.kwargs["transcription_incomplete"]
                for call in write.await_args_list
            ) == (ending not in {"early", "snapshot", "rejected_update"})
        assert not any(
            msg["type"] in {"session.updated", "error"} for msg in websocket.sent_json
        )
        connection.assert_only_shutdown_update()
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.parametrize(
    "missing", ["item", "predecessor", "discarded_predecessor", "unheard_predecessor"]
)
async def test_completed_transcript_waits_for_late_ordering_metadata(missing):
    drain = realtime.RealtimeShutdownDrain()
    connection = ShutdownConnection()
    buffer = realtime.ConversationItemOrderingBuffer(logging.getLogger(__name__))
    buffer.register_transcription("user", "complete text", "user")
    if missing != "item":
        buffer.register_conversation_item("user", "previous", "user")
    if missing in {"discarded_predecessor", "unheard_predecessor"}:
        buffer.register_transcription_delta("previous", "unheard", "assistant")
        buffer.items_by_id["previous"].skip_persistence = (
            missing == "discarded_predecessor"
        )
    drain.observe(
        event("conversation.item.input_audio_transcription.completed", item_id="user")
    )
    task = asyncio.create_task(drain.wait(connection, buffer))
    try:
        await wait_until(lambda: connection.session.update.await_count == 1)
        drain.observe(shutdown_ack())
        await asyncio.sleep(0)
        assert not task.done()
        item_id = "user" if missing == "item" else "previous"
        buffer.register_conversation_item(
            item_id, None, None if missing != "item" else "user"
        )
        drain.observe(event("conversation.item.added"))
        await asyncio.wait_for(task, 1)
        connection.assert_only_shutdown_update()
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.parametrize("when", ["before_end", "during_drain"])
async def test_unheard_reply_does_not_delay_early_cleanup_or_get_saved(
    monkeypatch, when
):
    connection = ShutdownConnection()
    websocket = DummyWebSocket()
    websocket.state["thread"] = SimpleNamespace(version=1, display_user_info=False)
    websocket.state["openai_client"] = None
    websocket.state["realtime_connection"] = connection
    websocket.state["db"] = None
    write = AsyncMock(return_value=True)
    monkeypatch.setattr(realtime, "add_message_to_thread", write)
    end = asyncio.Event()

    async def browser(ws, provider, tracker, *args, **kwargs):
        await tracker.add_audio_delta("heard", "audio", b"\0\0")
        await tracker.mark_audio_event_playback_started("heard", "audio")
        await end.wait()
        await tracker.mark_item_playback_settled("heard", "interrupted", True)

    monkeypatch.setattr(realtime, "handle_browser_messages", browser)
    for incoming in [
        event("input_audio_buffer.committed", item_id="user"),
        event(
            "conversation.item.added",
            previous_item_id=None,
            item=SimpleNamespace(id="user", type="message", role="user"),
        ),
        event(
            "conversation.item.input_audio_transcription.completed",
            item_id="user",
            transcript="question",
        ),
        event(
            "conversation.item.added",
            previous_item_id="user",
            item=SimpleNamespace(id="heard", type="message", role="assistant"),
        ),
        event(
            "response.output_audio_transcript.done",
            item_id="heard",
            transcript="heard answer",
        ),
    ]:
        connection.events.put_nowait(incoming)

    def add_unheard_reply():
        # Neither response.done nor transcript.done will arrive for this reply.
        connection.events.put_nowait(
            event("response.created", response=SimpleNamespace(id="unheard-response"))
        )
        connection.events.put_nowait(
            event(
                "conversation.item.added",
                previous_item_id="heard",
                item=SimpleNamespace(id="unheard", type="message", role="assistant"),
            )
        )
        connection.events.put_nowait(
            event(
                "response.output_audio_transcript.delta",
                item_id="unheard",
                delta="unheard partial text",
            )
        )
        # Unrelated missing metadata must not extend the retained-items wait.
        connection.events.put_nowait(
            event(
                "response.output_audio_transcript.delta",
                item_id="orphan-unheard",
                delta="orphan partial text",
            )
        )

    task = asyncio.create_task(
        inspect.unwrap(realtime.browser_realtime_websocket)(websocket, "1", "1")
    )
    try:
        await wait_until(lambda: write.await_count == 1)
        if when == "before_end":
            add_unheard_reply()
        end.set()
        await wait_until(lambda: connection.session.update.await_count == 1)
        if when == "during_drain":
            add_unheard_reply()
        connection.events.put_nowait(shutdown_ack())
        await asyncio.wait_for(task, 1)
        assert connection.reader_stopped.is_set()
        assert [call.args[3:5] for call in write.await_args_list] == [
            ("user", "question"),
            ("heard", "heard answer"),
        ]
        connection.assert_only_shutdown_update()
    finally:
        end.set()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.parametrize("missing", ["transcript", "metadata", "both"])
async def test_heard_reply_still_waits_for_its_own_transcript_and_metadata(missing):
    drain = realtime.RealtimeShutdownDrain()
    connection = ShutdownConnection()
    buffer = await playback_buffer("heard")
    if missing == "transcript":
        buffer.register_conversation_item("heard", None, "assistant")
    elif missing == "metadata":
        buffer.register_transcription("heard", "heard text", "assistant")
    task = asyncio.create_task(drain.wait(connection, buffer))
    try:
        await wait_until(lambda: connection.session.update.await_count == 1)
        drain.observe(shutdown_ack())
        await asyncio.sleep(0)
        assert not task.done()
        if missing != "transcript":
            buffer.register_conversation_item("heard", None, "assistant")
        if missing != "metadata":
            buffer.register_transcription("heard", "heard text", "assistant")
        drain.observe(event("response.output_audio_transcript.done", item_id="heard"))
        await asyncio.wait_for(task, 1)
        connection.assert_only_shutdown_update()
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.parametrize("self_cycle", [False, True])
def test_retained_item_with_cyclic_ordering_cannot_finish_drain_early(self_cycle):
    buffer = realtime.ConversationItemOrderingBuffer(logging.getLogger(__name__))
    buffer.register_conversation_item(
        "user", "user" if self_cycle else "unheard", "user"
    )
    buffer.register_transcription("user", "question", "user")
    if not self_cycle:
        buffer.register_conversation_item("unheard", "user", "assistant")
    assert buffer.has_pending_retained_items(frozenset())
