import asyncio
import base64
import inspect
import json
import struct
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from starlette.websockets import WebSocketDisconnect

from pingpong import realtime
from pingpong.realtime_recorder import VoiceRecordingHealth
from pingpong.test_realtime_shutdown import (
    ShutdownConnection,
    event,
    shutdown_ack,
    wait_until,
)
from pingpong.test_server_audio_websocket import DummyWebSocket


@pytest.mark.parametrize("expires_at", [None, True, "1234", float("nan"), float("inf")])
async def test_missing_or_invalid_expiry_uses_maximum_session_age(expires_at):
    expiry = realtime.RealtimeSessionExpiry()
    original_deadline = expiry.deadline
    expiry.observe(SimpleNamespace(expires_at=expires_at))
    assert expiry.deadline == original_deadline
    remaining = expiry.deadline - asyncio.get_running_loop().time()
    assert 3539 < remaining <= 3540  # 60 minutes minus the one-minute margin.


async def test_provider_expiry_shortens_a_running_timer_but_cannot_extend_it():
    expiry = realtime.RealtimeSessionExpiry()
    waiter = asyncio.create_task(expiry.wait())
    try:
        await asyncio.sleep(0)
        expiry.observe(SimpleNamespace(expires_at=time.time() + 120))
        deadline = expiry.deadline
        assert 59 < deadline - asyncio.get_running_loop().time() <= 60
        expiry.observe(SimpleNamespace(expires_at=time.time() + 600))
        assert expiry.deadline == deadline
        assert not waiter.done()
        expiry.observe(SimpleNamespace(expires_at=time.time() + 59))
        await asyncio.wait_for(waiter, 1)
        assert expiry.stopping
    finally:
        waiter.cancel()
        await asyncio.gather(waiter, return_exceptions=True)


async def test_missing_expiry_still_triggers_the_fallback_timer(monkeypatch):
    monkeypatch.setattr(realtime, "REALTIME_SESSION_MAX_SECONDS", 0.02)
    monkeypatch.setattr(realtime, "REALTIME_EXPIRY_MARGIN_SECONDS", 0)
    expiry = realtime.RealtimeSessionExpiry()
    await asyncio.wait_for(expiry.wait(), 1)
    assert expiry.stopping


class ExpiryBrowser(DummyWebSocket):
    def __init__(self):
        super().__init__()
        self.incoming = asyncio.Queue()
        self.on_expiring = None

    async def receive(self):
        return await self.incoming.get()

    def _raise_on_disconnect(self, message):
        if message["type"] == "websocket.disconnect":
            raise WebSocketDisconnect()

    async def send_json(self, data):
        await super().send_json(data)
        if data["type"] == "session.expiring" and self.on_expiring:
            await self.on_expiring()

    def telemetry(self, **fields):
        self.incoming.put_nowait(
            {"type": "websocket.receive", "text": json.dumps(fields)}
        )

    def microphone(self):
        self.incoming.put_nowait(
            {"type": "websocket.receive", "bytes": struct.pack(">d", 123) + b"\0\0"}
        )


@pytest.mark.parametrize("recording", [False, True])
@pytest.mark.parametrize("played", [False, True])
async def test_expiry_preserves_final_playback_and_late_transcripts_without_extra_input(
    monkeypatch, recording, played
):
    connection = ShutdownConnection()
    connection.conversation = SimpleNamespace(
        item=SimpleNamespace(truncate=AsyncMock())
    )
    browser = ExpiryBrowser()
    browser.state["thread"] = SimpleNamespace(
        id=1, thread_id=None, version=1, display_user_info=recording
    )
    browser.state["openai_client"] = None
    browser.state["realtime_connection"] = connection
    browser.state["db"] = AsyncMock()
    write = AsyncMock(return_value=True)
    monkeypatch.setattr(realtime, "add_message_to_thread", write)

    async def save_buffer(**kwargs):
        await asyncio.Future()

    recorder = AsyncMock()
    recorder.health = VoiceRecordingHealth()
    recorder.handle_saving_buffer.side_effect = save_buffer
    monkeypatch.setattr(
        realtime.RealtimeRecorder, "create", AsyncMock(return_value=recorder)
    )

    async def stop_playback():
        # Queued microphone input after cutoff must be discarded, while final
        # browser playback telemetry must still reach the recording/tracker.
        browser.microphone()
        if played:
            browser.telemetry(
                type="response.audio.delta.started",
                item_id="reply",
                event_id="audio",
                started_playing_at=123,
            )
            browser.telemetry(
                type="conversation.item.truncate",
                item_id="reply",
                event_id="audio",
                audio_end_ms=50,
            )
        browser.telemetry(
            type="response.audio.playback.settled",
            item_id="reply",
            outcome="interrupted" if played else "discarded",
            played=played,
        )
        browser.incoming.put_nowait({"type": "websocket.disconnect"})

    browser.on_expiring = stop_playback

    async def disable_vad(**kwargs):
        connection.events.put_nowait(
            event(
                "conversation.item.input_audio_transcription.completed",
                item_id="user",
                transcript="late question",
            )
        )
        connection.events.put_nowait(
            event(
                "response.output_audio_transcript.done",
                item_id="reply",
                transcript="final answer",
            )
        )
        connection.events.put_nowait(shutdown_ack())

    connection.session.update.side_effect = disable_vad
    for incoming in [
        event(
            "session.created", session=SimpleNamespace(expires_at=time.time() + 3600)
        ),
        event(
            "conversation.item.added",
            previous_item_id=None,
            item=SimpleNamespace(id="user", type="message", role="user"),
        ),
        event("input_audio_buffer.committed", item_id="user"),
        event(
            "conversation.item.added",
            previous_item_id="user",
            item=SimpleNamespace(id="reply", type="message", role="assistant"),
        ),
        event(
            "response.output_audio.delta",
            item_id="reply",
            event_id="audio",
            delta=base64.b64encode(b"\0" * 4800).decode(),
        ),
    ]:
        connection.events.put_nowait(incoming)
    task = asyncio.create_task(
        inspect.unwrap(realtime.browser_realtime_websocket)(browser, "1", "1")
    )
    try:
        await wait_until(
            lambda: any(
                msg["type"] == "response.audio.delta" for msg in browser.sent_json
            )
        )
        browser.microphone()
        await wait_until(lambda: connection.input_audio_buffer.append.await_count == 1)
        connection.events.put_nowait(
            event(
                "session.updated",
                session=SimpleNamespace(expires_at=time.time() + 59),
            )
        )
        await asyncio.wait_for(task, 1)
        assert browser.closed and connection.reader_stopped.is_set()
        assert [call.args[4] for call in write.await_args_list] == (
            ["late question", "final answer"] if played else []
        )
        connection.input_audio_buffer.append.assert_awaited_once()
        connection.input_audio_buffer.commit.assert_not_awaited()
        connection.input_audio_buffer.clear.assert_not_awaited()
        connection.response.create.assert_not_awaited()
        connection.response.cancel.assert_not_awaited()
        assert sum(msg["type"] == "session.expiring" for msg in browser.sent_json) == 1
        if played:
            connection.conversation.item.truncate.assert_awaited_once_with(
                item_id="reply",
                content_index=0,
                audio_end_ms=50,
            )
        if recording:
            recorder.add_user_audio.assert_awaited_once()
            recorder.complete_audio_upload.assert_awaited_once_with(
                has_played_audio=played
            )
            if played:
                recorder.stopped_playing_assistant_response.assert_awaited_once_with(
                    item_id="reply",
                    final_duration_ms=50,
                )
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.parametrize(
    "browser_failure", ["unresponsive", "stalled_send", "disconnected"]
)
async def test_expiry_fallback_still_drains_and_finalizes(monkeypatch, browser_failure):
    monkeypatch.setattr(realtime, "BROWSER_EXPIRY_STOP_SECONDS", 0.02)
    connection = ShutdownConnection()
    browser = ExpiryBrowser()
    browser.state["thread"] = SimpleNamespace(version=1, display_user_info=False)
    browser.state["openai_client"] = None
    browser.state["realtime_connection"] = connection
    browser.state["db"] = AsyncMock()

    async def failed_notification():
        if browser_failure == "stalled_send":
            await asyncio.Future()
        if browser_failure == "disconnected":
            raise WebSocketDisconnect()

    browser.on_expiring = failed_notification
    connection.session.update.side_effect = (
        lambda **kwargs: connection.events.put_nowait(shutdown_ack())
    )
    connection.events.put_nowait(
        event("session.created", session=SimpleNamespace(expires_at=time.time()))
    )
    await asyncio.wait_for(
        inspect.unwrap(realtime.browser_realtime_websocket)(browser, "1", "1"), 1
    )
    assert browser.closed and connection.reader_stopped.is_set()
    connection.assert_only_shutdown_update()


async def test_expiry_stops_new_playback_but_keeps_processing_transcripts():
    from pingpong.test_server_audio_websocket import FakeRealtimeEventStream

    expiry = realtime.RealtimeSessionExpiry()
    expiry.stopping = True
    browser = DummyWebSocket()
    tracker = realtime.RealtimeAssistantAudioTracker()
    recorder = AsyncMock()
    queue = asyncio.Queue()
    buffer = realtime.ConversationItemOrderingBuffer(realtime.openai_connection_logger)
    await realtime.handle_openai_events(
        browser,
        FakeRealtimeEventStream(
            [
                event("session.updated", session=SimpleNamespace()),
                event("input_audio_buffer.speech_started"),
                event(
                    "response.output_audio.delta",
                    item_id="unheard",
                    event_id="new",
                    delta=base64.b64encode(b"\0\0").decode(),
                ),
                event(
                    "conversation.item.input_audio_transcription.completed",
                    item_id="user",
                    transcript="late question",
                ),
            ]
        ),
        None,
        SimpleNamespace(version=1),
        queue,
        tracker,
        recorder,
        ordering_buffer=buffer,
        session_expiry=expiry,
    )
    assert not browser.sent_json
    recorder.add_assistant_response_delta.assert_not_awaited()
    assert not tracker.has_played_audio
    assert buffer.has_completed_transcription("user")
    assert buffer.items_by_id["user"].transcription_text == "late question"


async def test_expiry_warns_once_at_each_threshold_and_uses_actual_remaining_time():
    expiry = realtime.RealtimeSessionExpiry()
    warnings = []

    async def warn(seconds):
        warnings.append(seconds)

    task = asyncio.create_task(expiry.wait(warn))
    try:
        expiry.observe(SimpleNamespace(expires_at=time.time() + 60 + 299.5))
        await wait_until(lambda: warnings == [300])
        expiry.observe(SimpleNamespace(expires_at=time.time() + 60 + 200))
        await asyncio.sleep(0)
        assert warnings == [300]
        expiry.observe(SimpleNamespace(expires_at=time.time() + 60 + 59.5))
        await wait_until(lambda: warnings == [300, 60])
        assert not expiry.stopping and not task.done()
        expiry.observe(SimpleNamespace(expires_at=time.time()))
        await asyncio.wait_for(task, 1)
        assert expiry.stopping and warnings == [300, 60]
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


async def test_shortened_expiry_skips_obsolete_warning_without_repeating():
    expiry = realtime.RealtimeSessionExpiry()
    warn = AsyncMock()
    task = asyncio.create_task(expiry.wait(warn))
    try:
        expiry.observe(SimpleNamespace(expires_at=time.time() + 60 + 19.5))
        await wait_until(lambda: warn.await_count == 1)
        warn.assert_awaited_once_with(20)
        expiry.observe(SimpleNamespace(expires_at=time.time() + 60 + 10))
        await asyncio.sleep(0)
        assert warn.await_count == 1
        expiry.observe(SimpleNamespace(expires_at=time.time()))
        await asyncio.wait_for(task, 1)
        assert warn.await_count == 1
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.parametrize("failure", ["disconnect", "error", "stalled"])
async def test_warning_delivery_failure_does_not_end_or_block_session(
    monkeypatch, failure
):
    monkeypatch.setattr(realtime, "EXPIRY_WARNING_SEND_SECONDS", 0.01)
    attempted = asyncio.Event()
    expiry = realtime.RealtimeSessionExpiry()

    async def warn(seconds):
        attempted.set()
        if failure == "stalled":
            await asyncio.Future()
        elif failure == "disconnect":
            raise WebSocketDisconnect()
        else:
            raise RuntimeError("synthetic send failure")

    task = asyncio.create_task(expiry.wait(warn))
    try:
        expiry.observe(SimpleNamespace(expires_at=time.time() + 60 + 59.5))
        await asyncio.wait_for(attempted.wait(), 1)
        await asyncio.sleep(0.02)
        assert not task.done() and not expiry.stopping
        expiry.observe(SimpleNamespace(expires_at=time.time()))
        await asyncio.wait_for(task, 1)
        assert expiry.stopping
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


async def test_warning_schedule_does_not_finish_at_the_first_threshold(monkeypatch):
    monkeypatch.setattr(realtime, "REALTIME_SESSION_MAX_SECONDS", 0.08)
    monkeypatch.setattr(realtime, "REALTIME_EXPIRY_MARGIN_SECONDS", 0)
    monkeypatch.setattr(realtime, "REALTIME_EXPIRY_WARNING_SECONDS", (0.05, 0.02))
    expiry = realtime.RealtimeSessionExpiry()
    warn = AsyncMock()
    await asyncio.wait_for(expiry.wait(warn), 1)
    assert warn.await_count == 2
    assert expiry.stopping


async def test_session_delivers_warning_before_cutoff_and_then_ends_normally():
    connection = ShutdownConnection()
    browser = ExpiryBrowser()
    browser.state["thread"] = SimpleNamespace(version=1, display_user_info=False)
    browser.state["openai_client"] = None
    browser.state["realtime_connection"] = connection
    browser.state["db"] = AsyncMock()

    async def stopped():
        browser.incoming.put_nowait({"type": "websocket.disconnect"})

    browser.on_expiring = stopped
    connection.session.update.side_effect = (
        lambda **kwargs: connection.events.put_nowait(shutdown_ack())
    )
    connection.events.put_nowait(
        event(
            "session.created",
            session=SimpleNamespace(expires_at=time.time() + 60 + 59.5),
        )
    )
    task = asyncio.create_task(
        inspect.unwrap(realtime.browser_realtime_websocket)(browser, "1", "1")
    )
    try:
        await wait_until(
            lambda: any(
                msg["type"] == "session.expiry_warning" for msg in browser.sent_json
            )
        )
        assert browser.sent_json == [
            {"type": "session.expiry_warning", "seconds_remaining": 60}
        ]
        assert not task.done() and not browser.closed
        connection.events.put_nowait(
            event("session.created", session=SimpleNamespace(expires_at=time.time()))
        )
        await asyncio.wait_for(task, 1)
        assert [msg["type"] for msg in browser.sent_json] == [
            "session.expiry_warning",
            "session.expiring",
        ]
        assert browser.closed
        connection.assert_only_shutdown_update()
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
