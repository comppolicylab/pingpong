import asyncio
import inspect
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select
from starlette.websockets import WebSocketDisconnect

from pingpong import realtime, websocket as websocket_module
from pingpong.models import Message, Thread
from pingpong.realtime_recorder import VoiceRecordingHealth
from pingpong.test_realtime_expiry import ExpiryBrowser
from pingpong.test_realtime_shutdown import ShutdownConnection, event, shutdown_ack
from pingpong.testutil import with_user


@pytest.mark.parametrize("recording", [False, True])
@pytest.mark.parametrize(
    "failure", [None, "commit", "browser_gone", "stalled_ack", "stalled_close"]
)
async def test_stop_acknowledgement_follows_recording_and_database_commit(
    monkeypatch, recording, failure
):
    monkeypatch.setattr(realtime, "BROWSER_SAVE_CONFIRMATION_SECONDS", 0.02)
    connection = ShutdownConnection()
    browser = ExpiryBrowser()
    browser.state["thread"] = SimpleNamespace(
        id=1, thread_id=None, version=1, display_user_info=recording
    )
    browser.state["openai_client"] = None
    browser.state["realtime_connection"] = connection
    db = AsyncMock()
    finalizing = asyncio.Event()
    finish_recording = asyncio.Event()
    committing = asyncio.Event()
    finish_commit = asyncio.Event()
    order = []

    async def commit():
        committing.set()
        await finish_commit.wait()
        if failure == "commit":
            raise RuntimeError("synthetic commit failure")
        order.append("commit")

    db.commit.side_effect = commit
    context = AsyncMock()
    context.__aenter__.return_value = db
    monkeypatch.setattr(
        websocket_module.config.db.driver,
        "async_session_with_args",
        lambda **kwargs: lambda: context,
    )

    async def periodic(**kwargs):
        await asyncio.Future()

    async def finalize(**kwargs):
        finalizing.set()
        await finish_recording.wait()
        order.append("recording")

    recorder = SimpleNamespace(
        health=VoiceRecordingHealth(),
        handle_saving_buffer=periodic,
        complete_audio_upload=finalize,
    )
    monkeypatch.setattr(
        realtime.RealtimeRecorder, "create", AsyncMock(return_value=recorder)
    )
    connection.session.update.side_effect = (
        lambda **kwargs: connection.events.put_nowait(shutdown_ack())
    )
    original_send = browser.send_json
    original_close = browser.close

    async def close():
        if failure == "stalled_close":
            await asyncio.Future()
        await original_close()

    browser.close = close

    async def send(data):
        if data["type"] == "session.stopped":
            assert not browser.closed
            assert db.commit.await_count == 1
            if failure == "browser_gone":
                raise WebSocketDisconnect()
            if failure == "stalled_ack":
                await asyncio.Future()
            order.append("ack")
        await original_send(data)

    browser.send_json = send
    handler = websocket_module.ws_db_middleware(
        inspect.unwrap(realtime.browser_realtime_websocket)
    )
    browser.telemetry(type="session.stop")
    browser.microphone()  # Buffered input beyond the explicit cutoff must not be forwarded.
    task = asyncio.create_task(handler(browser, "1", "1"))
    try:
        if recording:
            await asyncio.wait_for(finalizing.wait(), 1)
            assert (
                not browser.sent_json and not browser.closed and not committing.is_set()
            )
            finish_recording.set()
        await asyncio.wait_for(committing.wait(), 1)
        assert not browser.sent_json and not browser.closed
        finish_commit.set()
        if failure == "commit":
            with pytest.raises(RuntimeError, match="synthetic commit failure"):
                await asyncio.wait_for(task, 1)
            db.rollback.assert_awaited_once()
            assert browser.sent_json == [{"type": "session.stopped", "saved": False}]
        else:
            await asyncio.wait_for(task, 1)
            db.rollback.assert_not_awaited()
            assert browser.sent_json == (
                []
                if failure in {"browser_gone", "stalled_ack"}
                else [{"type": "session.stopped", "saved": True}]
            )
        assert browser.closed == (failure != "stalled_close")
        assert connection.reader_stopped.is_set()
        assert order == (["recording"] if recording else []) + (
            [] if failure == "commit" else ["commit"]
        ) + ([] if failure in {"browser_gone", "stalled_ack"} else ["ack"])
        connection.assert_only_shutdown_update()
    finally:
        finish_recording.set()
        finish_commit.set()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@with_user(123)
async def test_save_confirmation_exposes_committed_history_to_another_reader(db, user):
    async with db.async_session() as session:
        thread = Thread(
            version=3, tools_available="[]", user_message_ct=0, display_user_info=False
        )
        session.add(thread)
        await session.flush()
        thread_id = thread.id
        await session.commit()
    connection = ShutdownConnection()
    browser = ExpiryBrowser()
    browser.state["openai_client"] = None
    browser.state["realtime_connection"] = connection
    browser.state["session"] = SimpleNamespace(user=user)
    visible_history = []
    original_send = browser.send_json

    async def send(data):
        if data["type"] == "response.audio.delta":
            browser.telemetry(
                type="response.audio.delta.started",
                item_id="reply",
                event_id="audio",
                started_playing_at=123,
            )
            browser.telemetry(
                type="response.audio.delta.ended", item_id="reply", event_id="audio"
            )
            browser.telemetry(
                type="response.audio.playback.settled",
                item_id="reply",
                outcome="completed",
                played=True,
            )
            browser.telemetry(type="session.stop")
        if data["type"] == "session.stopped":
            assert data["saved"] is True
            async with db.async_session() as reader:
                visible_history.extend(
                    await reader.scalars(
                        select(Message.message_id)
                        .where(Message.thread_id == thread_id)
                        .order_by(Message.output_index)
                    )
                )
        await original_send(data)

    browser.send_json = send
    connection.session.update.side_effect = (
        lambda **kwargs: connection.events.put_nowait(shutdown_ack())
    )
    for incoming in [
        event(
            "conversation.item.added",
            previous_item_id=None,
            item=SimpleNamespace(id="user", role="user", type="message"),
        ),
        event(
            "conversation.item.input_audio_transcription.completed",
            item_id="user",
            transcript="question",
        ),
        event(
            "conversation.item.added",
            previous_item_id="user",
            item=SimpleNamespace(id="reply", role="assistant", type="message"),
        ),
        event(
            "response.output_audio_transcript.done",
            item_id="reply",
            transcript="answer",
        ),
        event(
            "response.output_audio.delta",
            item_id="reply",
            event_id="audio",
            delta="AAA=",
        ),
        event("response.output_audio.done", item_id="reply"),
    ]:
        connection.events.put_nowait(incoming)

    async def handler(ws, *args):
        ws.state["thread"] = await ws.state["db"].get(Thread, thread_id)
        await inspect.unwrap(realtime.browser_realtime_websocket)(ws, *args)

    await asyncio.wait_for(
        websocket_module.ws_db_middleware(handler)(browser, "1", str(thread_id)), 3
    )
    assert visible_history == ["user", "reply"]
    assert browser.closed
