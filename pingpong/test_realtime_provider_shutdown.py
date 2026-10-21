import asyncio
import base64
import inspect
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from openai import WebSocketConnectionClosedError
from starlette.websockets import WebSocketDisconnect
from websockets.exceptions import ConnectionClosedError
from websockets.frames import Close

from pingpong import realtime, websocket as websocket_module
from pingpong.realtime_recorder import VoiceRecordingHealth
from pingpong.test_realtime_expiry import ExpiryBrowser
from pingpong.test_realtime_shutdown import (
    ShutdownConnection,
    event,
    mock_voice_usage_persistence as mock_voice_usage_persistence,
)
from pingpong.test_server_audio_websocket import (
    FakeOpenAIClient,
    FakeRealtimeConnection,
    realtime_assistant,
)


class ClosingConnection(ShutdownConnection):
    def __init__(self):
        super().__init__()
        self.conversation = SimpleNamespace(item=SimpleNamespace(truncate=AsyncMock()))

    async def __aiter__(self):
        try:
            while True:
                incoming = await self.events.get()
                if incoming is None:
                    return
                if isinstance(incoming, Exception):
                    raise incoming
                yield incoming
        finally:
            self.reader_stopped.set()


@pytest.mark.parametrize(
    "failure",
    [BrokenPipeError("closed"), ConnectionClosedError(None, None)],
)
async def test_failed_upstream_truncate_still_updates_local_playback(failure):
    connection = ClosingConnection()
    connection.conversation.item.truncate.side_effect = failure
    browser = ExpiryBrowser()
    tracker = realtime.RealtimeAssistantAudioTracker()
    await tracker.add_audio_delta("reply", "audio", b"\0\0" * 2400)
    recorder = AsyncMock()
    provider_unavailable = asyncio.Event()
    expiry = realtime.RealtimeSessionExpiry()
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
    browser.microphone()
    browser.telemetry(type="session.stop")
    await asyncio.wait_for(
        realtime.handle_browser_messages(
            browser,
            connection,
            tracker,
            recorder,
            provider_unavailable=provider_unavailable,
            session_expiry=expiry,
        ),
        1,
    )
    assert provider_unavailable.is_set()
    assert expiry.stopping
    assert tracker.has_played_audio
    recorder.stopped_playing_assistant_response.assert_awaited_once_with(
        item_id="reply", final_duration_ms=50
    )
    connection.conversation.item.truncate.assert_awaited_once()
    connection.input_audio_buffer.append.assert_not_awaited()
    recorder.add_user_audio.assert_not_awaited()


@pytest.mark.parametrize("recording", [False, True])
@pytest.mark.parametrize("heard", [False, True])
@pytest.mark.parametrize("ending", ["eof", "receive", "sdk", "send", "ended", "error"])
async def test_provider_shutdown_preserves_final_playback_and_confirms_commit(
    monkeypatch, recording, heard, ending, request
):
    connection = ClosingConnection()
    browser = ExpiryBrowser()
    browser.state["thread"] = SimpleNamespace(
        id=1, thread_id=None, version=1, display_user_info=recording
    )
    browser.state["openai_client"] = None
    browser.state["realtime_connection"] = connection
    db = AsyncMock()
    context = AsyncMock()
    context.__aenter__.return_value = db
    monkeypatch.setattr(
        websocket_module.config.db.driver,
        "async_session_with_args",
        lambda **kwargs: lambda: context,
    )
    write = AsyncMock(return_value=True)
    monkeypatch.setattr(realtime, "add_message_to_thread", write)

    async def periodic(**kwargs):
        await asyncio.Future()

    recorder = AsyncMock()
    recorder.health = VoiceRecordingHealth()
    recorder.handle_saving_buffer.side_effect = periodic
    monkeypatch.setattr(
        realtime.RealtimeRecorder, "create", AsyncMock(return_value=recorder)
    )
    if ending == "send":
        connection.input_audio_buffer.append.side_effect = BrokenPipeError(
            "provider closed"
        )

    original_send = browser.send_json

    async def send(data):
        await original_send(data)
        if data["type"] == "response.audio.delta" and ending == "send":
            browser.microphone()
        if data["type"] == "session.ended":
            assert not browser.closed
            assert db.commit.await_count == 0
            # No more microphone input may be sent, but final playback telemetry
            # must still be processed after the provider is no longer available.
            browser.microphone()
            if heard:
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
                outcome="interrupted" if heard else "discarded",
                played=heard,
            )
            browser.telemetry(type="session.stop")
            if ending in {"send", "ended"}:
                # A terminal event/write failure need not exhaust buffered reads.
                connection.events.put_nowait(
                    event(
                        "error",
                        error=SimpleNamespace(
                            param="session.audio.input.turn_detection"
                        ),
                    )
                )
                connection.events.put_nowait(
                    event(
                        "conversation.item.input_audio_transcription.completed",
                        item_id="user",
                        transcript="final question",
                    )
                )
                connection.events.put_nowait(None)
        if data["type"] == "session.stopped":
            db.commit.assert_awaited_once()
            assert data["saved"] is True
            if recording:
                recorder.complete_audio_upload.assert_awaited_once_with(
                    has_played_audio=heard
                )

    browser.send_json = send
    for incoming in [
        event("session.updated", session=SimpleNamespace()),
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
        event(
            "response.output_audio.delta",
            item_id="reply",
            event_id="audio",
            delta=base64.b64encode(b"\0\0" * 2400).decode(),
        ),
    ]:
        connection.events.put_nowait(incoming)
    if ending == "eof":
        connection.events.put_nowait(None)
    elif ending == "receive":
        connection.events.put_nowait(
            ConnectionClosedError(Close(1011, "provider ended"), None)
        )
    elif ending == "sdk":
        connection.events.put_nowait(
            WebSocketConnectionClosedError("provider ended", unsent_messages=[])
        )
    elif ending == "ended":
        connection.events.put_nowait(event("session.ended", session=SimpleNamespace()))
    elif ending == "error":
        connection.events.put_nowait(
            event(
                "error",
                error=SimpleNamespace(
                    type="invalid_request_error",
                    code="invalid_value",
                    param="session.model",
                    message="The model cannot be changed during the session.",
                ),
            )
        )
        connection.events.put_nowait(
            event(
                "conversation.item.input_audio_transcription.completed",
                item_id="user",
                transcript="final question",
            )
        )
        connection.events.put_nowait(
            event(
                "response.output_audio.delta",
                item_id="reply",
                event_id="after_error",
                delta=base64.b64encode(b"\0\0" * 2400).decode(),
            )
        )
        connection.events.put_nowait(None)

    handler = websocket_module.ws_db_middleware(
        inspect.unwrap(realtime.browser_realtime_websocket)
    )
    await asyncio.wait_for(handler(browser, "1", "1"), 2)
    usage = request.getfixturevalue("mock_voice_usage_persistence").await_args.args[2]
    assert usage.final_status == (
        realtime.schemas.RunStatus.FAILED
        if ending == "error"
        else realtime.schemas.RunStatus.INCOMPLETE
    )
    if ending == "error":
        assert usage.error_code == "provider_session_error"
    else:
        assert usage.error_code is None
    assert browser.closed
    assert connection.reader_stopped.is_set()
    assert [msg["type"] for msg in browser.sent_json].count("session.ended") == 1
    if ending == "error":
        audio_events = [
            msg["event_id"]
            for msg in browser.sent_json
            if msg["type"] == "response.audio.delta"
        ]
        assert audio_events == ["audio", "after_error"]
    assert browser.sent_json[-1] == {"type": "session.stopped", "saved": True}
    db.rollback.assert_not_awaited()
    connection.conversation.item.truncate.assert_not_awaited()
    connection.session.update.assert_not_awaited()
    connection.input_audio_buffer.commit.assert_not_awaited()
    connection.input_audio_buffer.clear.assert_not_awaited()
    connection.response.create.assert_not_awaited()
    assert connection.input_audio_buffer.append.await_count == (ending == "send")
    if recording:
        recorder.add_user_audio.assert_not_awaited()
        assert recorder.stopped_playing_assistant_response.await_count == int(heard)
        if heard:
            recorder.stopped_playing_assistant_response.assert_awaited_once_with(
                item_id="reply", final_duration_ms=50
            )
    assert write.await_count == (2 if heard else 0)
    if heard:
        assert [call.args[4] for call in write.await_args_list] == [
            "final question"
            if ending in {"send", "ended", "error"}
            else "partial question",
            "partial answer",
        ]


@pytest.mark.parametrize("disconnect", [False, True])
async def test_provider_shutdown_does_not_wait_forever_for_browser(
    monkeypatch, disconnect
):
    monkeypatch.setattr(realtime, "BROWSER_EXPIRY_STOP_SECONDS", 0.02)
    connection = ClosingConnection()
    connection.events.put_nowait(None)
    browser = ExpiryBrowser()
    browser.state["thread"] = SimpleNamespace(version=1, display_user_info=False)
    browser.state["openai_client"] = None
    browser.state["realtime_connection"] = connection
    browser.state["db"] = AsyncMock()
    if disconnect:
        browser.send_json = AsyncMock(side_effect=WebSocketDisconnect())
    await asyncio.wait_for(
        inspect.unwrap(realtime.browser_realtime_websocket)(browser, "1", "1"), 1
    )
    assert browser.closed
    assert connection.reader_stopped.is_set()


@pytest.mark.parametrize("failure", ["pipe", "websocket", "sdk", "unexpected"])
@pytest.mark.parametrize("failure_stage", ["handler", "context"])
async def test_provider_context_close_preserves_finalized_transaction(
    monkeypatch, failure, failure_stage
):
    error = {
        "pipe": BrokenPipeError("provider closed"),
        "websocket": ConnectionClosedError(Close(1011, "provider closed"), None),
        "sdk": WebSocketConnectionClosedError("provider closed", unsent_messages=[]),
        "unexpected": RuntimeError("unexpected"),
    }[failure]
    close_calls = 0

    class Connection(FakeRealtimeConnection):
        async def __aexit__(self, *args):
            nonlocal close_calls
            close_calls += 1
            if failure_stage == "context":
                assert args == (None, None, None)
                raise error
            assert args[1] is error
            return False

    browser = ExpiryBrowser()
    browser.state["openai_client"] = FakeOpenAIClient(Connection())
    browser.state["assistant"] = realtime_assistant()
    browser.state["thread"] = SimpleNamespace(id=1, thread_id=None)
    browser.state["conversation_instructions"] = "Speak clearly."
    db = AsyncMock()
    context = AsyncMock()
    context.__aenter__.return_value = db
    monkeypatch.setattr(
        websocket_module.config.db.driver,
        "async_session_with_args",
        lambda **kwargs: lambda: context,
    )
    saved = AsyncMock()

    async def finalized(ws, *args):
        ws.state["after_db_commit"].append(saved)
        if failure_stage == "handler":
            raise error

    handler = websocket_module.ws_db_middleware(
        websocket_module.ws_with_realtime_connection(finalized)
    )
    if failure_stage == "context" and failure != "unexpected":
        await handler(browser, "1", "1")
        db.commit.assert_awaited_once()
        db.rollback.assert_not_awaited()
        saved.assert_awaited_once()
        assert not browser.sent_json
    else:
        with pytest.raises(type(error)) as raised:
            await handler(browser, "1", "1")
        assert raised.value is error
        db.rollback.assert_awaited_once()
        db.commit.assert_not_awaited()
        saved.assert_not_awaited()
    assert close_calls == 1
