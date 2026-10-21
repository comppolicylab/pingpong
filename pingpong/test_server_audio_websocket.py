import asyncio
import base64
import importlib
import inspect
import json
import logging
import struct
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from openai.types.realtime import ResponseDoneEvent
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from starlette.datastructures import State
from starlette.requests import ClientDisconnect
from starlette.websockets import WebSocketDisconnect, WebSocketState

from pingpong import ai_models
from pingpong import models
from pingpong import realtime as realtime_module
from pingpong import schemas
from pingpong import websocket as websocket_module
from pingpong.realtime_recorder import RealtimeRecorder, VoiceRecordingHealth
from pingpong.testutil import with_user

server = importlib.import_module("pingpong.server")


class DummyWebSocket:
    def __init__(self, cookies: dict[str, str] | None = None):
        self.state = State()
        self.cookies: dict[str, str] = cookies or {}
        self.sent_json: list[dict] = []
        self.closed = False

    async def send_json(self, data: dict) -> None:
        self.sent_json.append(data)

    async def close(self) -> None:
        self.closed = True


async def test_audio_stream_uses_lti_session_when_cookie_missing(monkeypatch):
    browser_realtime_websocket = AsyncMock()
    monkeypatch.setattr(
        server, "browser_realtime_websocket", browser_realtime_websocket
    )

    websocket = DummyWebSocket()

    await server.audio_stream(
        websocket=websocket,
        class_id="10",
        thread_id="20",
        lti_session="lti-token",
    )

    assert websocket.cookies["session"] == "lti-token"
    browser_realtime_websocket.assert_awaited_once_with(websocket, "10", "20")


def realtime_assistant(**overrides):
    defaults = {
        "id": 30,
        "assistant_id": "asst_30",
        "model": "gpt-4o-realtime-preview",
        "assistant_should_message_first": False,
        "reasoning_effort": None,
        "realtime_vad_mode": None,
        "realtime_eagerness": None,
        "realtime_vad_threshold": None,
        "realtime_vad_prefix_padding_ms": None,
        "realtime_vad_silence_duration_ms": None,
        "realtime_vad_idle_timeout_ms": None,
        "realtime_voice": None,
        "realtime_speed": None,
        "realtime_noise_reduction": None,
        "realtime_transcription_model": None,
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


class FakeRealtimeSession:
    def __init__(self):
        self.updated_sessions: list[dict] = []

    async def update(self, *, session: dict) -> None:
        self.updated_sessions.append(session)


class FakeRealtimeResponse:
    def __init__(self):
        self.create_call_count = 0

    async def create(self) -> None:
        self.create_call_count += 1


class FakeRealtimeConnection:
    def __init__(self):
        self.session = FakeRealtimeSession()
        self.response = FakeRealtimeResponse()

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_value, traceback):
        return False


class FakeRealtimeClient:
    def __init__(self, connection: FakeRealtimeConnection):
        self.connection = connection
        self.connect_kwargs: dict | None = None

    def connect(self, **kwargs):
        self.connect_kwargs = kwargs
        return self.connection


class FakeOpenAIClient:
    def __init__(self, connection: FakeRealtimeConnection):
        self.realtime = FakeRealtimeClient(connection)


class FakeRealtimeEventStream:
    def __init__(self, events):
        self.events = events

    async def __aiter__(self):
        for event in self.events:
            yield event


def synthetic_assistant_audio(event_id="audio-1"):
    return SimpleNamespace(
        type="response.output_audio.delta",
        item_id="reply",
        event_id=event_id,
        delta=base64.b64encode(b"\0" * 480).decode("ascii"),
    )


def buffering_recorder(thread_id=1, session=None):
    # Exercise the recorder's real buffers without starting an encoder or upload.
    recorder = RealtimeRecorder(SimpleNamespace(), "synthetic.webm", thread_id, session)
    recorder.ffmpeg = SimpleNamespace()
    return recorder


def running_fake_encoder():
    exited = asyncio.Event()
    process = SimpleNamespace(returncode=None)

    def finish(code=0):
        if process.returncode is None:
            process.returncode = code
        exited.set()

    async def wait():
        await exited.wait()
        return process.returncode

    process.stdin = SimpleNamespace(
        close=Mock(side_effect=finish), write=Mock(), drain=AsyncMock()
    )
    process.wait = AsyncMock(side_effect=wait)
    process.communicate = AsyncMock(side_effect=wait)
    process.kill = Mock(side_effect=lambda: finish(-9))
    return process


def browser_with_playback_events(events):
    websocket = DummyWebSocket()
    messages = iter(events)

    async def receive():
        try:
            data = next(messages)
        except StopIteration:
            raise WebSocketDisconnect(code=1000)
        return {"type": "websocket.receive", "text": json.dumps(data)}

    websocket.receive = receive
    websocket._raise_on_disconnect = lambda message: None
    return websocket


@pytest.mark.parametrize("recording", [False, True])
@pytest.mark.parametrize("end_first", [False, True])
async def test_browser_playback_tracking_is_independent_of_recording(
    recording, end_first
):
    tracker = realtime_module.RealtimeAssistantAudioTracker()
    audio_bytes = b"\0" * 480
    await tracker.add_audio_delta("reply", "audio-1", audio_bytes)
    await tracker.add_audio_delta("unheard", "audio-2", audio_bytes)
    await tracker.mark_item_audio_done("reply")
    recorder = buffering_recorder() if recording else None
    if recorder:
        await recorder.add_assistant_response_delta(audio_bytes, "audio-1", "reply")
    start = {
        "type": "response.audio.delta.started",
        "item_id": "reply",
        "event_id": "audio-1",
        "started_playing_at": 1000,
    }
    end = {
        "type": "response.audio.delta.ended",
        "item_id": "reply",
        "event_id": "audio-1",
        "ended_playing_at": 1010,
    }
    events = [end, start] if end_first else [start, end]
    await realtime_module.handle_browser_messages(
        browser_with_playback_events(events), None, tracker, recorder
    )
    assert tracker.has_played_audio
    assert tracker.has_item_played_audio("reply")
    assert not tracker.has_item_played_audio("unheard")
    if recorder:
        chunk = recorder.assistant_responses["reply"].audio_chunks["audio-1"]
        assert chunk.starts_at == 1000
        assert chunk.ended


@pytest.mark.parametrize(
    "overrides",
    [
        {"item_id": []},
        {"event_id": {}},
        {"item_id": "unknown"},
        {"started_playing_at": None},
        {"started_playing_at": "1000"},
        {"started_playing_at": True},
        {"started_playing_at": -1},
        {"started_playing_at": 1.5},
    ],
)
async def test_invalid_browser_playback_start_does_not_corrupt_recorder(overrides):
    tracker = realtime_module.RealtimeAssistantAudioTracker()
    audio_bytes = b"\0" * 480
    await tracker.add_audio_delta("reply", "audio-1", audio_bytes)
    recorder = buffering_recorder()
    await recorder.add_assistant_response_delta(audio_bytes, "audio-1", "reply")
    start = {
        "type": "response.audio.delta.started",
        "item_id": "reply",
        "event_id": "audio-1",
        "started_playing_at": 1000,
    }
    await realtime_module.handle_browser_messages(
        browser_with_playback_events([{**start, **overrides}]), None, tracker, recorder
    )
    assert not tracker.has_played_audio
    assert (
        recorder.assistant_responses["reply"].audio_chunks["audio-1"].starts_at is None
    )
    await realtime_module.handle_browser_messages(
        browser_with_playback_events([start]), None, tracker, recorder
    )
    assert tracker.has_item_played_audio("reply")
    assert (
        recorder.assistant_responses["reply"].audio_chunks["audio-1"].starts_at == 1000
    )


@with_user(123)
@pytest.mark.parametrize("version", [1, 2, 3])
@pytest.mark.parametrize("recording", [False, True])
@pytest.mark.parametrize("played", [False, True])
@pytest.mark.parametrize("transcribed", [False, True])
async def test_session_retention_depends_on_playback_not_transcripts(
    db, user, monkeypatch, version, recording, played, transcribed
):
    audio_delivered = asyncio.Event()
    browser_processed = asyncio.Event()
    provider_messages = AsyncMock()

    class Stream:
        input_audio_buffer = SimpleNamespace(append=AsyncMock())

        async def __aiter__(self):
            yield SimpleNamespace(
                type="conversation.item.added",
                previous_item_id=None,
                item=SimpleNamespace(id="question", type="message", role="user"),
            )
            if transcribed:
                yield SimpleNamespace(
                    type="conversation.item.input_audio_transcription.completed",
                    item_id="question",
                    transcript="question",
                )
            yield SimpleNamespace(
                type="conversation.item.added",
                previous_item_id="question",
                item=SimpleNamespace(id="reply", type="message", role="assistant"),
            )
            if transcribed:
                yield SimpleNamespace(
                    type="response.output_audio_transcript.done",
                    item_id="reply",
                    transcript="answer",
                )
            yield synthetic_assistant_audio()
            await browser_processed.wait()

    async with db.async_session() as session:
        thread = models.Thread(
            version=version,
            thread_id="classic-thread" if version < 3 else None,
            user_message_ct=0,
            tools_available="[]",
            display_user_info=recording,
        )
        session.add(thread)
        await session.flush()
        thread_id = thread.id
        recorder = buffering_recorder(thread_id, session)
        store = SimpleNamespace(complete_upload=AsyncMock(), delete_file=AsyncMock())
        recorder.audio_store_obj = store
        recorder.ffmpeg = running_fake_encoder()
        monkeypatch.setattr(
            RealtimeRecorder, "create", AsyncMock(return_value=recorder)
        )
        websocket = DummyWebSocket()
        websocket.state["db"] = session
        websocket.state["session"] = SimpleNamespace(user=user)
        websocket.state["anonymous_share_token"] = None
        websocket.state["anonymous_session_token"] = None
        websocket.state["thread"] = thread
        websocket.state["openai_client"] = SimpleNamespace(
            beta=SimpleNamespace(
                threads=SimpleNamespace(
                    messages=SimpleNamespace(create=provider_messages)
                )
            )
        )
        stream = Stream()
        websocket.state["realtime_connection"] = stream
        sent_microphone = False
        sent_playback = False

        async def send_json(data):
            websocket.sent_json.append(data)
            if data.get("type") == "response.audio.delta":
                audio_delivered.set()

        async def receive():
            nonlocal sent_microphone, sent_playback
            if not sent_microphone:
                sent_microphone = True
                return {"bytes": struct.pack(">d", 1000) + b"\0" * 480}
            await audio_delivered.wait()
            if not sent_playback:
                # Transcripts queued before playback must not write history yet.
                assert not provider_messages.await_count
                assert "voice_mode_run_id" not in websocket.state._state
                sent_playback = True
                return {
                    "text": json.dumps(
                        {
                            "type": "response.audio.delta.started",
                            "item_id": "reply" if played else "unknown",
                            "event_id": "audio-1",
                            "started_playing_at": 1000,
                        }
                    )
                }
            browser_processed.set()
            return await asyncio.Future()

        websocket.send_json = send_json
        websocket.receive = receive
        websocket._raise_on_disconnect = lambda message: None
        handler = inspect.unwrap(realtime_module.browser_realtime_websocket)
        await asyncio.wait_for(handler(websocket, "1", str(thread_id)), timeout=2)
        await session.commit()
        assert thread.user_message_ct == int(played and transcribed)
        assert provider_messages.await_count == (
            2 if version < 3 and played and transcribed else 0
        )
        stream.input_audio_buffer.append.assert_awaited_once()
        if recording:
            assert recorder.closed
            assert store.complete_upload.await_count == int(played)
            assert store.delete_file.await_count == int(not played)
            if played:
                recorder.ffmpeg.stdin.close.assert_called_once()
                recorder.ffmpeg.wait.assert_awaited()
                assert recorder.audio_duration > 0
                recorder.ffmpeg.stdin.write.assert_called()
            else:
                recorder.ffmpeg.kill.assert_called_once()
                recorder.ffmpeg.communicate.assert_awaited_once()

    async with db.async_session() as session:
        assert await websocket_module._thread_has_messages(session, thread_id) == (
            version == 3 and played and transcribed
        )
        saved_recording = await session.scalar(
            select(models.VoiceModeRecording).where(
                models.VoiceModeRecording.thread_id == thread_id
            )
        )
        assert (saved_recording is not None) == (recording and played)
        assert bool(
            await session.scalar(
                select(models.Run.id).where(models.Run.thread_id == thread_id)
            )
        ) == (version == 3 and played and transcribed)


@with_user(123)
@pytest.mark.parametrize("version", [1, 2, 3])
@pytest.mark.parametrize("recording", [False, True])
@pytest.mark.parametrize("transcript_kind", ["done", "delta", "missing", "snapshot"])
@pytest.mark.parametrize("ending", ["provider", "disconnect", "cancel", "settled"])
async def test_unheard_reply_does_not_save_or_block_later_user_transcripts(
    db, user, monkeypatch, version, recording, transcript_kind, ending
):
    monkeypatch.setattr(realtime_module, "BROWSER_DISCONNECT_DRAIN_SECONDS", 0.01)
    first_played = asyncio.Event()
    provider_ready = asyncio.Event()
    finish_provider = asyncio.Event()
    prefix_saved = asyncio.Event()
    trailing_saved = asyncio.Event()
    incoming = asyncio.Queue()
    saved_ids = []
    original_write = realtime_module.add_message_to_thread

    async def write(*args, **kwargs):
        saved = await original_write(*args, **kwargs)
        if saved:
            saved_ids.append(args[3])
            if args[3] == "followup":
                prefix_saved.set()
            if args[3] == "trailing":
                trailing_saved.set()
        return saved

    monkeypatch.setattr(realtime_module, "add_message_to_thread", write)

    def item(item_id, previous_item_id, role):
        return SimpleNamespace(
            type="conversation.item.added",
            previous_item_id=previous_item_id,
            item=SimpleNamespace(id=item_id, type="message", role=role),
        )

    def transcript(item_id, role):
        return SimpleNamespace(
            type=(
                "conversation.item.input_audio_transcription.completed"
                if role == "user"
                else "response.output_audio_transcript.done"
            ),
            item_id=item_id,
            transcript=f"text for {item_id}",
        )

    class Stream:
        input_audio_buffer = SimpleNamespace(append=AsyncMock())

        async def __aiter__(self):
            yield item("question", None, "user")
            yield transcript("question", "user")
            yield item("reply", "question", "assistant")
            yield transcript("reply", "assistant")
            yield synthetic_assistant_audio()
            await first_played.wait()
            yield item("followup", "reply", "user")
            yield transcript("followup", "user")
            yield item("unheard", "followup", "assistant")
            audio = synthetic_assistant_audio("audio-2")
            audio.item_id = "unheard"
            yield audio
            if transcript_kind == "done":
                yield transcript("unheard", "assistant")
            elif transcript_kind == "delta":
                yield SimpleNamespace(
                    type="response.output_audio_transcript.delta",
                    item_id="unheard",
                    delta="partial unheard text",
                )
            elif transcript_kind == "snapshot":
                yield SimpleNamespace(
                    type="response.done",
                    response=SimpleNamespace(
                        output=[
                            SimpleNamespace(
                                id="unheard",
                                type="message",
                                role="assistant",
                                content=[
                                    SimpleNamespace(
                                        type="audio", transcript="unheard snapshot"
                                    )
                                ],
                            )
                        ]
                    ),
                )
            yield item("trailing", "unheard", "user")
            yield transcript("trailing", "user")
            provider_ready.set()
            await finish_provider.wait()
            if ending == "settled":
                yield audio  # A discarded reply cannot resume after settlement.
                yield transcript("unheard", "assistant")

    async with db.async_session() as session:
        thread = models.Thread(
            version=version,
            user_message_ct=0,
            tools_available="[]",
            thread_id="classic-thread" if version < 3 else None,
            display_user_info=recording,
        )
        session.add(thread)
        await session.flush()
        thread_id = thread.id
        recorder = buffering_recorder(thread_id, session)
        recorder.audio_store_obj = SimpleNamespace(
            complete_upload=AsyncMock(), delete_file=AsyncMock()
        )
        recorder.ffmpeg = running_fake_encoder()
        monkeypatch.setattr(
            RealtimeRecorder, "create", AsyncMock(return_value=recorder)
        )
        create_message = AsyncMock()
        websocket = DummyWebSocket()
        websocket.state["db"] = session
        websocket.state["session"] = SimpleNamespace(user=user)
        websocket.state["thread"] = thread
        websocket.state["anonymous_share_token"] = None
        websocket.state["anonymous_session_token"] = None
        websocket.state["openai_client"] = SimpleNamespace(
            beta=SimpleNamespace(
                threads=SimpleNamespace(messages=SimpleNamespace(create=create_message))
            )
        )
        websocket.state["realtime_connection"] = Stream()
        await incoming.put({"bytes": struct.pack(">d", 1000) + b"\0" * 480})
        playback_received = False

        async def send_json(data):
            websocket.sent_json.append(data)
            if (
                data.get("type") == "response.audio.delta"
                and data["item_id"] == "reply"
            ):
                await incoming.put(
                    {
                        "text": json.dumps(
                            {
                                "type": "response.audio.delta.started",
                                "item_id": "reply",
                                "event_id": "audio-1",
                                "started_playing_at": 1000,
                            }
                        )
                    }
                )
                await incoming.put(
                    {
                        "text": json.dumps(
                            {
                                "type": "response.audio.playback.settled",
                                "item_id": "reply",
                                "outcome": "interrupted",
                                "played": True,
                            }
                        )
                    }
                )

        async def receive():
            nonlocal playback_received
            if playback_received:
                first_played.set()
            message = await incoming.get()
            if message.get("type") == "websocket.disconnect":
                raise WebSocketDisconnect(code=1000)
            if "text" in message:
                playback_received = True
            return message

        websocket.send_json = send_json
        websocket.receive = receive
        websocket._raise_on_disconnect = lambda message: None
        task = asyncio.create_task(
            inspect.unwrap(realtime_module.browser_realtime_websocket)(
                websocket, "1", str(thread_id)
            )
        )
        try:
            await asyncio.wait_for(provider_ready.wait(), timeout=2)
            await asyncio.wait_for(prefix_saved.wait(), timeout=2)
            assert saved_ids == ["question", "reply", "followup"]
            if ending == "settled":
                await incoming.put(
                    {
                        "text": json.dumps(
                            {
                                "type": "response.audio.playback.settled",
                                "item_id": "unheard",
                                "outcome": "discarded",
                                "played": False,
                            }
                        )
                    }
                )
                await asyncio.wait_for(trailing_saved.wait(), timeout=2)
                assert saved_ids == ["question", "reply", "followup", "trailing"]
                assert not task.done()
            if ending == "cancel":
                task.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await asyncio.wait_for(task, timeout=2)
            else:
                if ending == "disconnect":
                    await incoming.put({"type": "websocket.disconnect"})
                else:
                    finish_provider.set()
                await asyncio.wait_for(task, timeout=2)
            assert saved_ids == ["question", "reply", "followup", "trailing"]
            assert (
                sum(
                    event.get("item_id") == "unheard"
                    and event["type"] == "response.audio.delta"
                    for event in websocket.sent_json
                )
                == 1
            )
            assert thread.user_message_ct == 3
            await session.commit()
        finally:
            finish_provider.set()
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
        if version < 3:
            assert [
                call.kwargs["metadata"]["item_id"]
                for call in create_message.await_args_list
            ] == saved_ids
        if recording:
            recorder.audio_store_obj.complete_upload.assert_awaited_once()
            recorder.audio_store_obj.delete_file.assert_not_awaited()

    if version == 3:
        async with db.async_session() as session:
            messages = (
                await session.scalars(
                    select(models.Message)
                    .where(models.Message.thread_id == thread_id)
                    .order_by(models.Message.output_index)
                )
            ).all()
            assert [message.message_id for message in messages] == saved_ids
            assert (
                messages[1].message_metadata["voice_playback_outcome"] == "interrupted"
            )
            assert messages[1].message_status == schemas.MessageStatus.COMPLETED


@pytest.mark.parametrize("playback_first", [False, True])
@pytest.mark.parametrize("ended", [False, True])
async def test_each_assistant_write_waits_for_its_own_playback(
    monkeypatch, playback_first, ended
):
    tracker = realtime_module.RealtimeAssistantAudioTracker()
    for item_id in ("earlier", "held", "unrelated"):
        await tracker.add_audio_delta(item_id, item_id, b"\0\0")
    await tracker.mark_audio_event_playback_started("earlier", "earlier")
    callback = (
        tracker.mark_audio_event_playback_ended
        if ended
        else tracker.mark_audio_event_playback_started
    )
    if playback_first:
        await callback("held", "held")
    buffer = realtime_module.ConversationItemOrderingBuffer(
        logging.getLogger(__name__), assistant_audio_tracker=tracker
    )
    for item_id, previous, role in [
        ("held", None, "assistant"),
        ("later", "held", "user"),
    ]:
        buffer.register_conversation_item(item_id, previous, role)
        buffer.register_transcription(item_id, item_id, role)
    write = AsyncMock(return_value=True)
    monkeypatch.setattr(realtime_module, "add_message_to_thread", write)
    queue = realtime_module.NamedQueue("per-reply-retention")
    await realtime_module.enqueue_ready_thread_message_tasks(
        buffer, queue, None, DummyWebSocket(), SimpleNamespace(version=3), None
    )
    worker = asyncio.create_task(
        realtime_module.process_queue_tasks(queue, logging.getLogger(__name__), tracker)
    )
    try:
        if not playback_first:
            with pytest.raises(TimeoutError):
                await asyncio.wait_for(queue.join(), timeout=0.02)
            write.assert_not_awaited()
            await callback("unrelated", "unrelated")
            with pytest.raises(TimeoutError):
                await asyncio.wait_for(queue.join(), timeout=0.02)
            write.assert_not_awaited()
            await callback("held", "held")
        await asyncio.wait_for(queue.join(), timeout=1)
        assert [call.args[3] for call in write.await_args_list] == ["held", "later"]
        assert write.await_args_list[0].kwargs["playback_outcome"] == "unknown"
        await tracker.mark_item_playback_settled("held", "interrupted", True)
        assert tracker.get_item_playback_outcome("held") == "interrupted"
        assert not await callback("held", "held")
    finally:
        worker.cancel()
        await asyncio.gather(worker, return_exceptions=True)


@with_user(123)
@pytest.mark.parametrize("settlement", ["during_write", "after_write", "missing"])
async def test_heard_transcripts_save_before_settlement_and_enrich_later(
    db, user, monkeypatch, settlement
):
    ready = asyncio.Event()
    writing = asyncio.Event()
    following_saved = asyncio.Event()
    settled = asyncio.Event()
    updated = asyncio.Event()
    finish = asyncio.Event()
    incoming = asyncio.Queue()
    initial_outcomes = []
    original_write = realtime_module.add_message_to_thread
    original_update = realtime_module.update_message_playback_outcome

    async def write(*args, **kwargs):
        if args[3] == "reply":
            initial_outcomes.append(kwargs["playback_outcome"])
            writing.set()
            if settlement == "during_write":
                await settled.wait()
        saved = await original_write(*args, **kwargs)
        if args[3] == "following":
            following_saved.set()
        return saved

    async def update(*args):
        await original_update(*args)
        updated.set()

    async def provider(*args, ordering_buffer):
        queue, tracker = args[4:6]
        await tracker.add_audio_delta("reply", "audio", b"\0" * 480)
        for item_id, previous, role in [
            ("reply", None, "assistant"),
            ("following", "reply", "user"),
        ]:
            ordering_buffer.register_conversation_item(item_id, previous, role)
            ordering_buffer.register_transcription(item_id, f"text for {item_id}", role)
        await realtime_module.enqueue_ready_thread_message_tasks(
            ordering_buffer, queue, args[2], args[0], args[3], None
        )
        ready.set()
        await finish.wait()

    monkeypatch.setattr(realtime_module, "add_message_to_thread", write)
    monkeypatch.setattr(realtime_module, "update_message_playback_outcome", update)
    monkeypatch.setattr(realtime_module, "handle_openai_events", provider)
    async with db.async_session() as session:
        thread = models.Thread(
            version=3,
            user_message_ct=0,
            tools_available="[]",
            display_user_info=False,
        )
        session.add(thread)
        await session.flush()
        websocket = DummyWebSocket()
        websocket.state = State(
            {
                "db": session,
                "session": SimpleNamespace(user=user),
                "thread": thread,
                "anonymous_share_token": None,
                "anonymous_session_token": None,
                "openai_client": None,
                "realtime_connection": None,
            }
        )
        last_settlement = False

        async def receive():
            nonlocal last_settlement
            if last_settlement:
                settled.set()
            data = await incoming.get()
            last_settlement = data["type"] == "response.audio.playback.settled"
            return {"text": json.dumps(data)}

        websocket.receive = receive
        websocket._raise_on_disconnect = lambda message: None
        task = asyncio.create_task(
            inspect.unwrap(realtime_module.browser_realtime_websocket)(
                websocket, "1", str(thread.id)
            )
        )
        try:
            await asyncio.wait_for(ready.wait(), timeout=2)
            await incoming.put(
                {
                    "type": "response.audio.delta.started",
                    "item_id": "reply",
                    "event_id": "audio",
                    "started_playing_at": 1000,
                }
            )
            if settlement == "during_write":
                await asyncio.wait_for(writing.wait(), timeout=2)
            else:
                await asyncio.wait_for(following_saved.wait(), timeout=2)
            assert initial_outcomes == ["unknown"]
            if settlement != "missing":
                await incoming.put(
                    {
                        "type": "response.audio.playback.settled",
                        "item_id": "reply",
                        "outcome": "interrupted",
                        "played": True,
                    }
                )
                await asyncio.wait_for(updated.wait(), timeout=2)
            await asyncio.wait_for(following_saved.wait(), timeout=2)
            finish.set()
            await asyncio.wait_for(task, timeout=2)
            messages = (
                await session.scalars(
                    select(models.Message)
                    .where(models.Message.thread_id == thread.id)
                    .order_by(models.Message.output_index)
                )
            ).all()
            assert [message.message_id for message in messages] == [
                "reply",
                "following",
            ]
            assert messages[0].message_metadata["voice_playback_outcome"] == (
                "unknown" if settlement == "missing" else "interrupted"
            )
            await session.commit()
        finally:
            finish.set()
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)


@pytest.mark.parametrize("played", [False, True])
@pytest.mark.parametrize("ended", [False, True])
async def test_queued_writes_wait_for_session_retention_decision(played, ended):
    tracker = realtime_module.RealtimeAssistantAudioTracker()
    queue = realtime_module.NamedQueue("retention-test")
    write = AsyncMock()
    await queue.put(write)
    worker = asyncio.create_task(
        realtime_module.process_queue_tasks(queue, logging.getLogger(__name__), tracker)
    )
    try:
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(queue.join(), timeout=0.02)
        write.assert_not_awaited()
        await tracker.add_audio_delta("reply", "audio", b"\0\0")
        if played:
            callback = (
                tracker.mark_audio_event_playback_ended
                if ended
                else tracker.mark_audio_event_playback_started
            )
            await callback("reply", "audio")
        else:
            tracker.finish_playback_tracking()
        await asyncio.wait_for(queue.join(), timeout=1)
        assert write.await_count == int(played)
    finally:
        worker.cancel()
        await asyncio.gather(worker, return_exceptions=True)


async def test_recording_finalization_waits_for_in_flight_transcript_write(monkeypatch):
    writing = asyncio.Event()
    release_write = asyncio.Event()
    periodic_stopped = asyncio.Event()
    write_finished = False

    async def write():
        nonlocal write_finished
        writing.set()
        await release_write.wait()
        write_finished = True

    async def provider(*args, **kwargs):
        queue, tracker = args[4:6]
        await tracker.add_audio_delta("reply", "audio", b"\0\0")
        await tracker.mark_audio_event_playback_started("reply", "audio")
        await queue.put(write)
        await writing.wait()

    async def browser(*args, **kwargs):
        await asyncio.Future()

    async def periodic(**kwargs):
        try:
            await asyncio.Future()
        finally:
            periodic_stopped.set()

    async def finalize(*, has_played_audio):
        assert has_played_audio
        assert write_finished

    recorder = SimpleNamespace(
        health=VoiceRecordingHealth(),
        handle_saving_buffer=periodic,
        complete_audio_upload=AsyncMock(side_effect=finalize),
    )
    monkeypatch.setattr(realtime_module, "handle_openai_events", provider)
    monkeypatch.setattr(realtime_module, "handle_browser_messages", browser)
    monkeypatch.setattr(RealtimeRecorder, "create", AsyncMock(return_value=recorder))
    websocket = DummyWebSocket()
    websocket.state["thread"] = SimpleNamespace(
        id=1, thread_id=None, display_user_info=True
    )
    websocket.state["db"] = None
    websocket.state["openai_client"] = None
    websocket.state["realtime_connection"] = None
    task = asyncio.create_task(
        inspect.unwrap(realtime_module.browser_realtime_websocket)(websocket, "1", "1")
    )
    try:
        await asyncio.wait_for(periodic_stopped.wait(), timeout=1)
        recorder.complete_audio_upload.assert_not_awaited()
        assert not websocket.closed
        assert not task.done()
        release_write.set()
        await asyncio.wait_for(task, timeout=1)
        recorder.complete_audio_upload.assert_awaited_once_with(has_played_audio=True)
        assert websocket.closed
    finally:
        release_write.set()
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@with_user(123)
@pytest.mark.parametrize(
    "failure", ["upload_setup", "encoder_setup", "recording", "upload"]
)
async def test_recording_failure_preserves_live_session_and_transcripts(
    db, user, monkeypatch, failure
):
    ready = asyncio.Event()
    release = asyncio.Event()
    browser_alive = asyncio.Event()
    recorder = None

    async def browser(*args, **kwargs):
        browser_alive.set()
        await asyncio.Future()

    async def provider(*args, **kwargs):
        nonlocal recorder
        recorder = args[6]
        queue, tracker = args[4:6]
        await tracker.add_audio_delta("reply", "audio", b"\0\0")
        await tracker.mark_audio_event_playback_started("reply", "audio")
        if failure == "recording":
            await recorder.add_user_audio(b"\0", 1_000)
        elif failure == "upload":
            recorder.ffmpeg.stdout.feed_data(b"encoded")
            await recorder._failure_event.wait()
        else:
            assert recorder is None

        async def write_transcript():
            assert await realtime_module.add_message_to_thread(
                None,
                args[0],
                args[3],
                "after-failure",
                "Transcript received after recording failed",
                "assistant",
                output_index="0",
            )
            ready.set()

        await queue.put(write_transcript)
        await release.wait()

    encoder = running_fake_encoder()
    encoder.stdout = asyncio.StreamReader()
    finish = encoder.stdin.close.side_effect

    def close_encoder():
        finish()
        encoder.stdout.feed_eof()

    encoder.stdin.close.side_effect = close_encoder
    store = SimpleNamespace(
        delete_file=AsyncMock(),
        complete_upload=AsyncMock(),
        upload_part=AsyncMock(side_effect=OSError(5, "storage failure")),
    )
    create_upload = AsyncMock(return_value=store)
    if failure == "upload_setup":
        create_upload.side_effect = OSError(5, "storage setup failure")
    monkeypatch.setattr(
        "pingpong.realtime_recorder.config.audio_store.store.create_upload",
        create_upload,
    )
    create_encoder = AsyncMock(return_value=encoder)
    if failure == "encoder_setup":
        create_encoder.side_effect = FileNotFoundError("ffmpeg")
    monkeypatch.setattr(asyncio, "create_subprocess_exec", create_encoder)
    monkeypatch.setattr("pingpong.realtime_recorder.MIN_AUDIO_CHUNK_SIZE", 1)
    monkeypatch.setattr(realtime_module, "handle_openai_events", provider)
    monkeypatch.setattr(realtime_module, "handle_browser_messages", browser)
    async with db.async_session() as session:
        thread = models.Thread(
            thread_id="health-live",
            version=3,
            display_user_info=True,
            tools_available="[]",
        )
        session.add(thread)
        await session.flush()
        thread_id = thread.id
        websocket = DummyWebSocket()
        websocket.state["thread"] = thread
        websocket.state["db"] = session
        websocket.state["session"] = SimpleNamespace(user=user)
        websocket.state["realtime_connection"] = None
        websocket.state["openai_client"] = None
        task = asyncio.create_task(
            inspect.unwrap(realtime_module.browser_realtime_websocket)(
                websocket, "1", str(thread_id)
            )
        )
        try:
            await asyncio.wait_for(ready.wait(), 2)
            await asyncio.wait_for(browser_alive.wait(), 1)
            # Let the failed recorder worker finish while voice stays active.
            await asyncio.sleep(0.02)
            assert not task.done()
            assert not websocket.closed
            if recorder:
                assert recorder.closed
                assert not recorder.user_audio and not recorder.assistant_responses
            release.set()
            await asyncio.wait_for(task, 2)
            await session.commit()
        finally:
            release.set()
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
    async with db.async_session() as session:
        saved = await session.get(models.Thread, thread_id)
        kind = "upload" if failure in {"upload", "upload_setup"} else "recording"
        assert saved.recording_issue == (kind == "recording")
        assert saved.upload_issue == (kind == "upload")
        assert getattr(saved, f"{kind}_issue_details")["recording_id"]
        assert await session.scalar(
            select(models.Message).where(models.Message.thread_id == thread_id)
        )
        assert not await session.scalar(
            select(models.VoiceModeRecording).where(
                models.VoiceModeRecording.thread_id == thread_id
            )
        )


@pytest.mark.parametrize("prior_playback", [False, True])
async def test_final_playback_callback_before_browser_stops_can_qualify_reply(
    monkeypatch,
    prior_playback,
):
    browser_ready = asyncio.Event()
    write = AsyncMock()

    async def browser(*args, **kwargs):
        tracker = args[2]
        browser_ready.set()
        try:
            await asyncio.Future()
        finally:
            await tracker.mark_audio_event_playback_ended("reply", "audio")

    async def provider(*args, **kwargs):
        queue, tracker = args[4:6]
        await browser_ready.wait()
        if prior_playback:
            await tracker.add_audio_delta("earlier", "earlier", b"\0\0")
            await tracker.mark_audio_event_playback_started("earlier", "earlier")
        await tracker.add_audio_delta("reply", "audio", b"\0\0")
        buffer = kwargs["ordering_buffer"]
        buffer.register_conversation_item("reply", None, "assistant")
        buffer.register_transcription("reply", "answer", "assistant")
        await realtime_module.enqueue_ready_thread_message_tasks(
            buffer, queue, None, args[0], SimpleNamespace(version=3), None
        )

    monkeypatch.setattr(realtime_module, "handle_openai_events", provider)
    monkeypatch.setattr(realtime_module, "handle_browser_messages", browser)
    monkeypatch.setattr(realtime_module, "add_message_to_thread", write)
    websocket = DummyWebSocket()
    websocket.state["thread"] = SimpleNamespace(display_user_info=False)
    websocket.state["db"] = None
    websocket.state["openai_client"] = None
    websocket.state["realtime_connection"] = None
    await asyncio.wait_for(
        inspect.unwrap(realtime_module.browser_realtime_websocket)(websocket, "1", "1"),
        timeout=1,
    )
    write.assert_awaited_once()


@with_user(123)
@pytest.mark.parametrize("played", [False, True])
async def test_session_saves_late_transcripts_after_browser_disconnect(
    db, user, played
):
    disconnect = asyncio.Event()
    browser_disconnected = asyncio.Event()
    provider_waiting = asyncio.Event()
    finish_transcript = asyncio.Event()
    provider_cancelled = asyncio.Event()

    class DelayedTranscriptStream:
        async def __aiter__(self):
            try:
                yield SimpleNamespace(
                    type="conversation.item.added",
                    previous_item_id=None,
                    item=SimpleNamespace(id="question", type="message", role="user"),
                )
                yield SimpleNamespace(
                    type="conversation.item.added",
                    previous_item_id="question",
                    item=SimpleNamespace(id="reply", type="message", role="assistant"),
                )
                yield SimpleNamespace(
                    type="response.output_audio_transcript.done",
                    item_id="reply",
                    transcript="answer",
                )
                yield synthetic_assistant_audio()
                provider_waiting.set()
                await finish_transcript.wait()
                yield SimpleNamespace(
                    type="conversation.item.input_audio_transcription.completed",
                    item_id="question",
                    transcript="question",
                )
            except asyncio.CancelledError:
                provider_cancelled.set()
                raise

    async with db.async_session() as session:
        thread = models.Thread(
            version=3, user_message_ct=0, tools_available="[]", display_user_info=False
        )
        session.add(thread)
        await session.flush()
        thread_id = thread.id
        websocket = DummyWebSocket()
        websocket.state["db"] = session
        websocket.state["session"] = SimpleNamespace(user=user)
        websocket.state["thread"] = thread
        websocket.state["openai_client"] = None
        websocket.state["realtime_connection"] = DelayedTranscriptStream()

        async def receive():
            if played and not getattr(websocket, "playback_sent", False):
                await provider_waiting.wait()
                websocket.playback_sent = True
                return {
                    "text": json.dumps(
                        {
                            "type": "response.audio.delta.started",
                            "item_id": "reply",
                            "event_id": "audio-1",
                            "started_playing_at": 1000,
                        }
                    )
                }
            await disconnect.wait()
            browser_disconnected.set()
            raise WebSocketDisconnect(code=1000)

        websocket.receive = receive
        websocket._raise_on_disconnect = lambda message: None
        handler = inspect.unwrap(realtime_module.browser_realtime_websocket)
        task = asyncio.create_task(handler(websocket, "1", str(thread_id)))
        try:
            await asyncio.wait_for(provider_waiting.wait(), timeout=1)
            disconnect.set()
            await asyncio.wait_for(browser_disconnected.wait(), timeout=1)
            with pytest.raises(TimeoutError):
                await asyncio.wait_for(asyncio.shield(task), timeout=0.02)
            assert not provider_cancelled.is_set()
            finish_transcript.set()
            await asyncio.wait_for(task, timeout=1)
            await session.commit()
        finally:
            finish_transcript.set()
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    async with db.async_session() as session:
        messages = (
            await session.scalars(
                select(models.Message)
                .where(models.Message.thread_id == thread_id)
                .order_by(models.Message.output_index)
                .options(selectinload(models.Message.content))
            )
        ).all()
        assert [message.message_id for message in messages] == (
            ["question", "reply"] if played else []
        )
        assert [message.content[0].text for message in messages] == (
            ["question", "answer"] if played else []
        )
        assert await websocket_module._thread_has_messages(session, thread_id) == played
        saved_thread = await session.get(models.Thread, thread_id)
        assert saved_thread.user_message_ct == int(played)
        assert (
            bool(
                await session.scalar(
                    select(models.Run.id).where(models.Run.thread_id == thread_id)
                )
            )
            == played
        )


@pytest.mark.parametrize(
    "ending", ["provider", "disconnect_timeout", "cancel", "provider_error"]
)
@pytest.mark.parametrize("recording", [False, True])
@pytest.mark.parametrize("played", [False, True])
async def test_realtime_session_stops_browser_before_final_queue_drain(
    monkeypatch, caplog, ending, recording, played
):
    browser_ready = asyncio.Event()
    disconnect = asyncio.Event()
    provider_ready = asyncio.Event()
    finish_provider = asyncio.Event()
    recorder_ready = asyncio.Event()
    children = []
    cleanup = []

    async def browser(*args, **kwargs):
        children.append(asyncio.current_task())
        if played:
            tracker = args[2]
            await tracker.add_audio_delta("reply", "audio", b"\0\0")
            await tracker.mark_audio_event_playback_started("reply", "audio")
        browser_ready.set()
        try:
            await disconnect.wait()
        finally:
            cleanup.append("browser")

    async def provider(*args, **kwargs):
        children.append(asyncio.current_task())
        provider_ready.set()
        try:
            await finish_provider.wait()
            if ending == "provider_error":
                raise RuntimeError("synthetic provider failure")
        finally:
            cleanup.append("provider")

    async def save_recording(*args, **kwargs):
        children.append(asyncio.current_task())
        recorder_ready.set()
        try:
            await asyncio.Future()
        finally:
            cleanup.append("recorder")

    async def finalize_recording(*, has_played_audio):
        assert has_played_audio == played
        assert "writer" in cleanup
        assert "browser" in cleanup
        cleanup.append("finalize")

    process_queue = realtime_module.process_queue_tasks

    async def writer(*args):
        children.append(asyncio.current_task())
        try:
            await process_queue(*args)
        finally:
            cleanup.append("writer")

    monkeypatch.setattr(realtime_module, "handle_browser_messages", browser)
    monkeypatch.setattr(realtime_module, "handle_openai_events", provider)
    monkeypatch.setattr(realtime_module, "process_queue_tasks", writer)
    monkeypatch.setattr(
        realtime_module.RealtimeRecorder,
        "create",
        AsyncMock(
            return_value=SimpleNamespace(
                health=VoiceRecordingHealth(),
                handle_saving_buffer=save_recording,
                complete_audio_upload=finalize_recording,
            )
        ),
    )
    monkeypatch.setattr(
        realtime_module, "BROWSER_DISCONNECT_DRAIN_SECONDS", 0.02, raising=False
    )
    websocket = DummyWebSocket()
    websocket.state["thread"] = SimpleNamespace(
        id=1, thread_id=None, display_user_info=recording
    )
    websocket.state["realtime_connection"] = None
    websocket.state["openai_client"] = None
    websocket.state["db"] = None
    handler = inspect.unwrap(realtime_module.browser_realtime_websocket)
    task = asyncio.create_task(handler(websocket, "1", "1"))
    try:
        await asyncio.wait_for(browser_ready.wait(), timeout=1)
        await asyncio.wait_for(provider_ready.wait(), timeout=1)
        if recording:
            await asyncio.wait_for(recorder_ready.wait(), timeout=1)
        if ending == "disconnect_timeout":
            disconnect.set()
        elif ending == "cancel":
            task.cancel()
        else:
            finish_provider.set()
        if ending == "cancel":
            with pytest.raises(asyncio.CancelledError):
                await asyncio.wait_for(task, timeout=1)
        else:
            await asyncio.wait_for(task, timeout=1)
        assert all(child.done() for child in children)
        assert cleanup.index("browser") < cleanup.index("writer")
        if recording:
            assert cleanup.index("recorder") < cleanup.index("writer")
            assert cleanup[-1] == "finalize"
        if ending == "provider_error":
            assert "synthetic provider failure" in caplog.text
    finally:
        task.cancel()
        for child in children:
            child.cancel()
        await asyncio.gather(task, *children, return_exceptions=True)


async def test_realtime_cleanup_does_not_close_browser_twice():
    websocket = DummyWebSocket()
    websocket.application_state = WebSocketState.CONNECTED
    websocket.state["thread"] = SimpleNamespace(
        id=1, version=1, display_user_info=False
    )
    websocket.state["openai_client"] = None
    websocket.state["realtime_connection"] = FakeRealtimeEventStream(
        [SimpleNamespace(type="error", error=SimpleNamespace())]
    )

    async def receive():
        await asyncio.Future()

    async def close():
        if websocket.application_state == WebSocketState.DISCONNECTED:
            raise RuntimeError("already closed")
        websocket.application_state = WebSocketState.DISCONNECTED

    websocket.receive = receive
    websocket.close = AsyncMock(side_effect=close)
    handler = inspect.unwrap(realtime_module.browser_realtime_websocket)
    await asyncio.wait_for(handler(websocket, "1", "1"), timeout=1)
    websocket.close.assert_awaited_once()


@with_user(123)
@pytest.mark.parametrize(
    "failure", ["disconnect", "client_disconnect", "broken_pipe", "closed"]
)
@pytest.mark.parametrize(
    "first_event", ["audio", "speech", "session_update", "session_end"]
)
async def test_browser_delivery_failure_does_not_drop_later_transcripts(
    db, user, caplog, failure, first_event
):
    async with db.async_session() as session:
        thread = models.Thread(version=3, user_message_ct=0, tools_available="[]")
        session.add(thread)
        await session.flush()
        thread_id = thread.id
        websocket = DummyWebSocket()
        websocket.state["db"] = session
        websocket.state["session"] = SimpleNamespace(user=user)

        async def fail_delivery(data):
            if failure == "closed":
                websocket.application_state = WebSocketState.DISCONNECTED
                raise RuntimeError(
                    'Cannot call "send" once a close message has been sent.'
                )
            if failure == "client_disconnect":
                raise ClientDisconnect()
            if failure == "broken_pipe":
                raise BrokenPipeError()
            raise WebSocketDisconnect(code=1006)

        websocket.send_json = AsyncMock(side_effect=fail_delivery)
        events = {
            "audio": synthetic_assistant_audio(),
            "speech": SimpleNamespace(type="input_audio_buffer.speech_started"),
            "session_update": SimpleNamespace(
                type="session.updated", session=SimpleNamespace()
            ),
            "session_end": SimpleNamespace(
                type="session.ended", session=SimpleNamespace()
            ),
        }
        recorder = buffering_recorder(thread_id, session)
        queue = asyncio.Queue()
        await asyncio.wait_for(
            realtime_module.handle_openai_events(
                websocket,
                FakeRealtimeEventStream(
                    [
                        events[first_event],
                        SimpleNamespace(
                            type="conversation.item.added",
                            previous_item_id=None,
                            item=SimpleNamespace(
                                id="question", type="message", role="user"
                            ),
                        ),
                        SimpleNamespace(
                            type="conversation.item.added",
                            previous_item_id="question",
                            item=SimpleNamespace(
                                id="reply", type="message", role="assistant"
                            ),
                        ),
                        SimpleNamespace(
                            type="response.output_audio_transcript.done",
                            item_id="reply",
                            transcript="answer",
                        ),
                        synthetic_assistant_audio("audio-2"),
                        events["speech"],
                        events["session_update"],
                        events["session_end"],
                        SimpleNamespace(
                            type="conversation.item.input_audio_transcription.completed",
                            item_id="question",
                            transcript="question",
                        ),
                    ]
                ),
                None,
                thread,
                queue,
                realtime_module.RealtimeAssistantAudioTracker(),
                recorder,
            ),
            timeout=1,
        )
        while not queue.empty():
            await (await queue.get())()
        websocket.send_json.assert_awaited_once()
        assert "Error handling OpenAI event" not in caplog.text
        # Generated audio still needs real browser telemetry to count as heard.
        response = recorder.assistant_responses["reply"]
        assert len(response.audio_chunks) == (2 if first_event == "audio" else 1)
        assert all(chunk.starts_at is None for chunk in response.audio_chunks.values())
        await recorder.finalize()
        assert not recorder.assistant_responses
        await session.commit()

    async with db.async_session() as session:
        messages = (
            await session.scalars(
                select(models.Message)
                .where(models.Message.thread_id == thread_id)
                .order_by(models.Message.output_index)
                .options(selectinload(models.Message.content))
            )
        ).all()
        assert [message.message_id for message in messages] == ["question", "reply"]
        assert [message.content[0].text for message in messages] == [
            "question",
            "answer",
        ]
        assert [message.output_index for message in messages] == [0, 1]


async def test_audio_is_registered_before_browser_can_report_playback():
    websocket = DummyWebSocket()
    recorder = buffering_recorder()

    async def report_playback(data):
        await recorder.started_playing_assistant_response_delta(
            item_id=data["item_id"],
            event_id=data["event_id"],
            started_playing_at_ms=1000,
        )

    websocket.send_json = AsyncMock(side_effect=report_playback)
    await realtime_module.handle_openai_events(
        websocket,
        FakeRealtimeEventStream([synthetic_assistant_audio()]),
        None,
        SimpleNamespace(id=1, version=1),
        asyncio.Queue(),
        realtime_module.RealtimeAssistantAudioTracker(),
        recorder,
    )
    assert (
        recorder.assistant_responses["reply"].audio_chunks["audio-1"].starts_at == 1000
    )


@pytest.mark.parametrize("phase", ["send", "close"])
async def test_browser_delivery_cancellation_propagates(phase):
    websocket = DummyWebSocket()
    started = asyncio.Event()
    stopped = asyncio.Event()

    async def block(*args):
        started.set()
        try:
            await asyncio.Future()
        finally:
            stopped.set()

    if phase == "send":
        websocket.send_json = AsyncMock(side_effect=block)
        event = synthetic_assistant_audio()
    else:
        websocket.close = AsyncMock(side_effect=block)
        event = SimpleNamespace(type="error", error=SimpleNamespace())
    task = asyncio.create_task(
        realtime_module.handle_openai_events(
            websocket,
            FakeRealtimeEventStream([event]),
            None,
            SimpleNamespace(id=1, version=1),
            asyncio.Queue(),
            realtime_module.RealtimeAssistantAudioTracker(),
        )
    )
    try:
        await asyncio.wait_for(started.wait(), timeout=1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, timeout=1)
        assert stopped.is_set()
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.parametrize("error_type", [RuntimeError, ValueError])
async def test_unexpected_browser_delivery_error_is_still_reported(caplog, error_type):
    websocket = DummyWebSocket()
    websocket.application_state = WebSocketState.CONNECTED
    websocket.send_json = AsyncMock(
        side_effect=error_type("synthetic unexpected failure")
    )
    await realtime_module.handle_openai_events(
        websocket,
        FakeRealtimeEventStream([synthetic_assistant_audio()]),
        None,
        SimpleNamespace(id=1, version=1),
        asyncio.Queue(),
        realtime_module.RealtimeAssistantAudioTracker(),
    )
    assert "Error handling OpenAI event: synthetic unexpected failure" in caplog.text


async def test_startup_error_close_tolerates_browser_disconnect(caplog):
    websocket = DummyWebSocket()

    async def fail_close():
        raise WebSocketDisconnect(code=1006)

    websocket.close = AsyncMock(side_effect=fail_close)
    await asyncio.wait_for(
        realtime_module.handle_openai_events(
            websocket,
            FakeRealtimeEventStream(
                [SimpleNamespace(type="error", error=SimpleNamespace())]
            ),
            None,
            SimpleNamespace(id=1, version=1),
            asyncio.Queue(),
            realtime_module.RealtimeAssistantAudioTracker(),
        ),
        timeout=1,
    )
    assert websocket.sent_json[0]["type"] == "error"
    websocket.close.assert_awaited_once()
    assert "Error handling OpenAI event" not in caplog.text


def assistant_response_snapshot(
    status="completed", content_type="output_audio", transcript="complete answer"
):
    return ResponseDoneEvent.model_validate(
        {
            "event_id": "response-finished",
            "type": "response.done",
            "response": {
                "id": "response",
                "status": status,
                "output": [
                    {
                        "id": "reply",
                        "type": "message",
                        "role": "assistant",
                        "status": "completed"
                        if status == "completed"
                        else "incomplete",
                        "content": [{"type": content_type, "transcript": transcript}],
                    }
                ],
            },
        }
    )


@with_user(123)
@pytest.mark.parametrize(
    "response_status", ["completed", "cancelled", "failed", "incomplete"]
)
@pytest.mark.parametrize("metadata_first", [False, True])
@pytest.mark.parametrize("content_type", [None, "output_audio"])
async def test_response_snapshot_recovers_transcript_and_unblocks_followup(
    db, user, response_status, metadata_first, content_type
):
    async with db.async_session() as session:
        thread = models.Thread(version=3, tools_available="[]", user_message_ct=0)
        session.add(thread)
        await session.flush()
        websocket = DummyWebSocket()
        websocket.state["db"] = session
        websocket.state["session"] = SimpleNamespace(user=SimpleNamespace(id=123))
        reply_metadata = SimpleNamespace(
            type="conversation.item.added",
            previous_item_id="question",
            item=SimpleNamespace(id="reply", type="message", role="assistant"),
        )
        events = [
            SimpleNamespace(
                type="conversation.item.added",
                previous_item_id=None,
                item=SimpleNamespace(id="question", type="message", role="user"),
            ),
            SimpleNamespace(
                type="conversation.item.input_audio_transcription.completed",
                item_id="question",
                transcript="question",
            ),
        ]
        if metadata_first:
            events.append(reply_metadata)
        events.extend(
            [
                SimpleNamespace(
                    type="response.output_audio_transcript.delta",
                    item_id="reply",
                    delta="partial",
                ),
                SimpleNamespace(
                    type="conversation.item.added",
                    previous_item_id="reply",
                    item=SimpleNamespace(id="followup", type="message", role="user"),
                ),
                SimpleNamespace(
                    type="conversation.item.input_audio_transcription.completed",
                    item_id="followup",
                    transcript="followup",
                ),
                assistant_response_snapshot(response_status, content_type),
            ]
        )
        if not metadata_first:
            events.append(reply_metadata)
        events.append(assistant_response_snapshot(response_status, content_type))
        queue = asyncio.Queue()
        await realtime_module.handle_openai_events(
            websocket,
            FakeRealtimeEventStream(events),
            object(),
            thread,
            queue,
            realtime_module.RealtimeAssistantAudioTracker(),
        )
        while not queue.empty():
            await (await queue.get())()
        messages = (
            await session.scalars(
                select(models.Message)
                .where(models.Message.thread_id == thread.id)
                .order_by(models.Message.output_index)
                .options(selectinload(models.Message.content))
            )
        ).all()
        assert [message.message_id for message in messages] == [
            "question",
            "reply",
            "followup",
        ]
        assert [message.output_index for message in messages] == [0, 1, 2]
        assert messages[1].content[0].text == "complete answer"
        assert messages[1].message_status == schemas.MessageStatus.COMPLETED
        assert not messages[1].message_metadata


@pytest.mark.parametrize("user_complete_first", [False, True])
@pytest.mark.parametrize("snapshot_first", [False, True])
async def test_response_snapshot_and_transcript_completion_are_idempotent(
    monkeypatch, caplog, user_complete_first, snapshot_first
):
    save = AsyncMock()
    monkeypatch.setattr(realtime_module, "add_message_to_thread", save)
    user_completion = SimpleNamespace(
        type="conversation.item.input_audio_transcription.completed",
        item_id="question",
        transcript="question",
    )
    transcript_completion = SimpleNamespace(
        type="response.output_audio_transcript.done",
        item_id="reply",
        transcript="complete answer",
    )
    events = [
        SimpleNamespace(
            type="conversation.item.added",
            previous_item_id=None,
            item=SimpleNamespace(id="question", type="message", role="user"),
        ),
        SimpleNamespace(
            type="conversation.item.added",
            previous_item_id="question",
            item=SimpleNamespace(id="reply", type="message", role="assistant"),
        ),
    ]
    if user_complete_first:
        events.append(user_completion)
    terminal_events = [assistant_response_snapshot("cancelled"), transcript_completion]
    events.extend(terminal_events if snapshot_first else reversed(terminal_events))
    events.append(assistant_response_snapshot("cancelled"))
    if not user_complete_first:
        events.append(user_completion)
    queue = asyncio.Queue()
    await realtime_module.handle_openai_events(
        DummyWebSocket(),
        FakeRealtimeEventStream(events),
        object(),
        SimpleNamespace(id=1, version=1),
        queue,
        realtime_module.RealtimeAssistantAudioTracker(),
    )
    while not queue.empty():
        await (await queue.get())()
    assert [call.args[3] for call in save.await_args_list] == ["question", "reply"]
    assert save.await_args_list[1].args[4] == "complete answer"
    assert save.await_args_list[1].kwargs["transcription_failed"] is False
    assert "already-saved" not in caplog.text
    assert "already-complete" not in caplog.text


@pytest.mark.parametrize(
    "output",
    [
        None,
        [],
        [
            {
                "id": "reply",
                "type": "function_call",
                "call_id": "call",
                "name": "tool",
                "arguments": "{}",
            }
        ],
        [
            {
                "id": "reply",
                "type": "message",
                "role": "assistant",
                "content": [{"type": "output_text", "text": "not an audio transcript"}],
            }
        ],
    ],
)
async def test_response_snapshot_without_audio_text_keeps_waiting(monkeypatch, output):
    save = AsyncMock()
    monkeypatch.setattr(realtime_module, "add_message_to_thread", save)
    events = [
        SimpleNamespace(
            type="conversation.item.added",
            previous_item_id=None,
            item=SimpleNamespace(id="reply", type="message", role="assistant"),
        ),
        SimpleNamespace(
            type="response.output_audio_transcript.delta",
            item_id="reply",
            delta="partial",
        ),
        ResponseDoneEvent.model_validate(
            {
                "type": "response.done",
                "event_id": "empty-snapshot",
                "response": {"id": "response", "status": "completed", "output": output},
            }
        ),
        assistant_response_snapshot(),
    ]
    queue = asyncio.Queue()
    await realtime_module.handle_openai_events(
        DummyWebSocket(),
        FakeRealtimeEventStream(events),
        object(),
        SimpleNamespace(id=1, version=1),
        queue,
        realtime_module.RealtimeAssistantAudioTracker(),
    )
    while not queue.empty():
        await (await queue.get())()
    save.assert_awaited_once()
    assert save.await_args.args[4] == "complete answer"


@pytest.mark.parametrize("snapshot_text", ["", " \t\n"])
@pytest.mark.parametrize("partial_text", [None, "partial answer"])
async def test_blank_response_snapshot_preserves_buffered_delta_text(
    monkeypatch, snapshot_text, partial_text
):
    enqueue = AsyncMock(wraps=realtime_module.enqueue_ready_thread_message_tasks)
    monkeypatch.setattr(realtime_module, "enqueue_ready_thread_message_tasks", enqueue)
    snapshot = assistant_response_snapshot("cancelled", transcript=snapshot_text)
    events = [
        SimpleNamespace(
            type="conversation.item.added",
            previous_item_id=None,
            item=SimpleNamespace(id="reply", type="message", role="assistant"),
        )
    ]
    if partial_text:
        events.append(
            SimpleNamespace(
                type="response.output_audio_transcript.delta",
                item_id="reply",
                delta=partial_text,
            )
        )
    events.append(snapshot)
    queue = asyncio.Queue()
    await realtime_module.handle_openai_events(
        DummyWebSocket(),
        FakeRealtimeEventStream(events),
        object(),
        SimpleNamespace(id=1, version=1),
        queue,
        realtime_module.RealtimeAssistantAudioTracker(),
    )
    buffer = enqueue.await_args_list[0].kwargs["ordering_buffer"]
    assert queue.empty()
    if partial_text:
        assert buffer.items_by_id["reply"].transcription_text == partial_text
        assert not buffer.has_completed_transcription("reply")
        assert enqueue.await_count == 1  # Only item registration changed readiness.
    else:
        assert buffer.has_completed_transcription("reply")


@with_user(123)
@pytest.mark.parametrize("partial_text", [None, "partial question"])
async def test_failed_transcription_does_not_block_persisting_later_reply(
    db, user, partial_text
):
    async with db.async_session() as session:
        thread = models.Thread(version=3, tools_available="[]", user_message_ct=0)
        session.add(thread)
        await session.flush()
        websocket = DummyWebSocket()
        websocket.state["db"] = session
        websocket.state["session"] = SimpleNamespace(user=SimpleNamespace(id=123))
        events = [
            SimpleNamespace(
                type="conversation.item.added",
                previous_item_id=None,
                item=SimpleNamespace(id="question", type="message", role="user"),
            ),
            SimpleNamespace(
                type="conversation.item.added",
                previous_item_id="question",
                item=SimpleNamespace(id="reply", type="message", role="assistant"),
            ),
            SimpleNamespace(
                type="response.output_audio_transcript.done",
                item_id="reply",
                transcript="answer",
            ),
        ]
        if partial_text:
            events.append(
                SimpleNamespace(
                    type="conversation.item.input_audio_transcription.delta",
                    item_id="question",
                    delta=partial_text,
                )
            )
        events.append(
            SimpleNamespace(
                type="conversation.item.input_audio_transcription.failed",
                item_id="question",
            )
        )
        queue = asyncio.Queue()
        await realtime_module.handle_openai_events(
            websocket,
            FakeRealtimeEventStream(events),
            object(),
            thread,
            queue,
            realtime_module.RealtimeAssistantAudioTracker(),
        )
        while not queue.empty():
            await (await queue.get())()
        messages = (
            await session.scalars(
                select(models.Message)
                .where(models.Message.thread_id == thread.id)
                .order_by(models.Message.output_index)
                .options(selectinload(models.Message.content))
            )
        ).all()
        assert [message.message_id for message in messages] == (
            ["question", "reply"] if partial_text else ["reply"]
        )
        assert messages[-1].content[0].text == "answer"
        assert messages[-1].message_status == schemas.MessageStatus.COMPLETED
        if partial_text:
            assert messages[0].content[0].text == partial_text
            assert messages[0].message_status == schemas.MessageStatus.INCOMPLETE
            assert messages[0].message_metadata["voice_transcription_failed"] is True
        assert thread.user_message_ct == int(bool(partial_text))


async def test_failed_partial_transcription_marks_classic_message_metadata():
    websocket = DummyWebSocket()
    websocket.state["session"] = SimpleNamespace(user=SimpleNamespace(id=123))
    websocket.state["anonymous_share_token"] = None
    websocket.state["anonymous_session_token"] = None
    websocket.state["db"] = SimpleNamespace(
        add=lambda thread: None, flush=AsyncMock(), refresh=AsyncMock()
    )
    create = AsyncMock()
    client = SimpleNamespace(
        beta=SimpleNamespace(
            threads=SimpleNamespace(messages=SimpleNamespace(create=create))
        )
    )
    thread = SimpleNamespace(version=2, thread_id="legacy-thread", user_message_ct=0)
    await realtime_module.add_message_to_thread(
        client,
        websocket,
        thread,
        "question",
        "partial question",
        "user",
        transcription_failed=True,
    )
    create.assert_awaited_once_with(
        thread_id="legacy-thread",
        role="user",
        content="partial question",
        metadata={
            "item_id": "question",
            "user_id": "123",
            "voice_transcription_failed": "true",
        },
    )


@pytest.mark.parametrize("version", [1, 2])
@pytest.mark.parametrize("outcome", ["completed", "interrupted", "unknown"])
async def test_classic_voice_transcript_records_playback_outcome_without_changing_text(
    version, outcome
):
    websocket = DummyWebSocket()
    websocket.state["anonymous_share_token"] = None
    websocket.state["anonymous_session_token"] = None
    create = AsyncMock()
    client = SimpleNamespace(
        beta=SimpleNamespace(
            threads=SimpleNamespace(messages=SimpleNamespace(create=create))
        )
    )
    text = "The complete available transcript, including potentially unheard words."
    assert await realtime_module.add_message_to_thread(
        client,
        websocket,
        SimpleNamespace(version=version, thread_id="classic-thread"),
        "reply",
        text,
        "assistant",
        output_index="7",
        playback_outcome=outcome,
    )
    create.assert_awaited_once_with(
        thread_id="classic-thread",
        role="assistant",
        content=text,
        metadata={
            "item_id": "reply",
            "output_index": "7",
            "voice_playback_outcome": outcome,
        },
    )


def test_realtime_session_uses_create_defaults_for_null_fields():
    session = websocket_module.build_realtime_session(
        realtime_assistant(),
        "Speak clearly.",
    )

    assert session["instructions"] == "Speak clearly."
    assert session["audio"]["output"] == {"voice": "marin", "speed": 1.0}
    assert "reasoning" not in session
    assert session["audio"]["input"]["noise_reduction"] == {"type": "far_field"}
    assert session["audio"]["input"]["transcription"] == {
        "model": "whisper-1",
        "language": "en",
    }
    assert session["audio"]["input"]["turn_detection"] == {
        "create_response": True,
        "type": "semantic_vad",
        "interrupt_response": True,
        "eagerness": "auto",
    }


def test_realtime_session_includes_tracing_config():
    tracing_config = {
        "workflow_name": "PingPong Voice Mode",
        "group_id": "pp_test_assistant_30",
        "metadata": {"deployment_identifier": "test"},
    }

    session = websocket_module.build_realtime_session(
        realtime_assistant(),
        "Speak clearly.",
        tracing_config,
    )

    assert session["tracing"] == tracing_config


def test_realtime_pingpong_version_uses_sentry_release(monkeypatch):
    monkeypatch.setenv("SENTRY_RELEASE", "pingpong@7.60.0+123")
    websocket_module._get_pingpong_version.cache_clear()

    try:
        assert websocket_module._get_pingpong_version() == "pingpong@7.60.0+123"
    finally:
        websocket_module._get_pingpong_version.cache_clear()


def test_realtime_pingpong_version_falls_back_to_local_dev_version(
    monkeypatch, tmp_path
):
    monkeypatch.delenv("SENTRY_RELEASE", raising=False)
    monkeypatch.setattr(websocket_module.config, "development", True)
    monkeypatch.setattr(websocket_module, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        websocket_module, "_get_local_dev_version_suffix", lambda: "dev.abc123.dirty"
    )
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "pingpong"\nversion = "7.61.0"\n',
        encoding="utf-8",
    )
    websocket_module._get_pingpong_version.cache_clear()

    try:
        assert (
            websocket_module._get_pingpong_version()
            == "pingpong@7.61.0+dev.abc123.dirty"
        )
    finally:
        websocket_module._get_pingpong_version.cache_clear()


def test_realtime_pingpong_version_warns_without_release_outside_development(
    monkeypatch, tmp_path, caplog
):
    monkeypatch.delenv("SENTRY_RELEASE", raising=False)
    monkeypatch.setattr(websocket_module.config, "development", False)
    monkeypatch.setattr(websocket_module, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        websocket_module, "_get_local_dev_version_suffix", lambda: "dev"
    )
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "pingpong"\nversion = "7.61.0"\n',
        encoding="utf-8",
    )
    websocket_module._get_pingpong_version.cache_clear()

    try:
        with caplog.at_level(logging.WARNING, logger="realtime_openai"):
            assert websocket_module._get_pingpong_version() == "pingpong@7.61.0+dev"
    finally:
        websocket_module._get_pingpong_version.cache_clear()

    assert "SENTRY_RELEASE is not set" in caplog.text


def test_realtime_tracing_config_includes_stable_filter_metadata(monkeypatch):
    monkeypatch.setattr(websocket_module.config, "deployment_identifier", "staging")
    monkeypatch.setattr(
        websocket_module.config, "public_url", "https://example.edu/app"
    )
    monkeypatch.setattr(websocket_module, "_get_pingpong_version", lambda: "7.60.0")
    thread = SimpleNamespace(
        id=20,
        thread_id="thread_20",
        interaction_mode=schemas.InteractionMode.VOICE,
    )
    assistant = realtime_assistant(
        id=30,
        assistant_id="asst_30",
        model="gpt-realtime-2",
    )

    tracing_config = websocket_module.build_realtime_tracing_config(
        thread,
        assistant,
        "10",
        "safety-id",
    )

    assert tracing_config == {
        "workflow_name": "PingPong Voice Mode",
        "group_id": "pp_staging_assistant_30",
        "metadata": {
            "metadata_version": "1",
            "deployment_identifier": "staging",
            "pingpong_version": "7.60.0",
            "deployment_url": "example.edu",
            "class": "10",
            "assistant": "30",
            "thread": "20",
            "model": "gpt-realtime-2",
            "safety_identifier": "safety-id",
        },
    }


def test_realtime_tracing_config_omits_unavailable_pingpong_version(monkeypatch):
    monkeypatch.setattr(websocket_module.config, "deployment_identifier", "staging")
    monkeypatch.setattr(websocket_module, "_get_pingpong_version", lambda: None)
    thread = SimpleNamespace(id=20, thread_id="thread_20")

    tracing_config = websocket_module.build_realtime_tracing_config(
        thread,
        realtime_assistant(model="gpt-realtime-2"),
        "10",
    )

    assert tracing_config["metadata"]["metadata_version"] == "1"
    assert "pingpong_version" not in tracing_config["metadata"]


def test_realtime_tracing_config_sanitizes_group_id(monkeypatch):
    monkeypatch.setattr(
        websocket_module.config, "deployment_identifier", "staging:blue/green"
    )

    tracing_config = websocket_module.build_realtime_tracing_config(
        SimpleNamespace(id="thread:20/voice"),
        realtime_assistant(id="assistant:30/voice", model="gpt-realtime-2"),
        "10",
    )

    assert (
        tracing_config["group_id"]
        == "pp_staging_blue_green_assistant_assistant_30_voice"
    )


@pytest.mark.parametrize(
    "model", ["gpt-realtime-2", "gpt-realtime-2.1", "gpt-realtime-2.1-mini"]
)
def test_realtime_reasoning_models_add_low_reasoning_by_default(model):
    session = websocket_module.build_realtime_session(
        realtime_assistant(model=model),
        "Speak clearly.",
    )

    assert session["reasoning"] == {"effort": "low"}


@pytest.mark.parametrize(
    "model", ["gpt-realtime-2", "gpt-realtime-2.1", "gpt-realtime-2.1-mini"]
)
def test_realtime_reasoning_models_use_selected_reasoning(model):
    session = websocket_module.build_realtime_session(
        realtime_assistant(model=model, reasoning_effort=-1),
        "Speak clearly.",
    )

    assert session["reasoning"] == {"effort": "minimal"}


def test_realtime_session_uses_selected_transcription_model():
    session = websocket_module.build_realtime_session(
        realtime_assistant(
            realtime_transcription_model=schemas.RealtimeTranscriptionModel.GPT_REALTIME_WHISPER,
        ),
        "Speak clearly.",
    )

    assert session["audio"]["input"]["transcription"] == {
        "model": "gpt-realtime-whisper",
        "language": "en",
    }


def test_realtime_extra_headers_include_safety_identifier():
    assert websocket_module.build_realtime_extra_headers("pp:v1:safety-id") == {
        "OpenAI-Safety-Identifier": "pp:v1:safety-id",
    }


def test_realtime_extra_headers_omit_missing_safety_identifier():
    assert websocket_module.build_realtime_extra_headers(None) == {}


async def test_realtime_connection_updates_session_with_tracing(monkeypatch):
    monkeypatch.setattr(websocket_module.config, "deployment_identifier", "staging")
    monkeypatch.setattr(
        websocket_module.config, "public_url", "https://example.edu/app"
    )
    monkeypatch.setattr(websocket_module, "_get_pingpong_version", lambda: "7.60.0")
    connection = FakeRealtimeConnection()
    openai_client = FakeOpenAIClient(connection)
    websocket = DummyWebSocket()
    websocket.state["response_safety_identifier"] = "safety-id"
    websocket.state["openai_client"] = openai_client
    websocket.state["assistant"] = realtime_assistant(
        id=30,
        assistant_id="asst_30",
        model="gpt-realtime-2",
    )
    websocket.state["thread"] = SimpleNamespace(
        id=20,
        thread_id="thread_20",
        interaction_mode=schemas.InteractionMode.VOICE,
    )
    websocket.state["conversation_instructions"] = "Speak clearly."
    handler = AsyncMock()
    wrapped = websocket_module.ws_with_realtime_connection(handler)

    await wrapped(websocket, "10", "20")

    assert openai_client.realtime.connect_kwargs == {
        "model": "gpt-realtime-2",
        "extra_headers": {
            "OpenAI-Safety-Identifier": "pp:v1:safety-id",
        },
    }
    assert connection.session.updated_sessions[0]["tracing"] == {
        "workflow_name": "PingPong Voice Mode",
        "group_id": "pp_staging_assistant_30",
        "metadata": {
            "metadata_version": "1",
            "deployment_identifier": "staging",
            "pingpong_version": "7.60.0",
            "deployment_url": "example.edu",
            "class": "10",
            "assistant": "30",
            "thread": "20",
            "model": "gpt-realtime-2",
            "safety_identifier": "pp:v1:safety-id",
        },
    }
    handler.assert_awaited_once_with(websocket, "10", "20")


async def test_openai_session_update_error_notifies_browser_and_closes_websocket():
    websocket = DummyWebSocket()
    error = SimpleNamespace(
        message=("Invalid 'session.tracing.group_id': string does not match pattern."),
        type="invalid_request_error",
        code="invalid_value",
        event_id=None,
        param="session.tracing.group_id",
    )
    realtime_connection = FakeRealtimeEventStream(
        [SimpleNamespace(type="error", error=error)]
    )

    await realtime_module.handle_openai_events(
        websocket,
        realtime_connection,
        openai_client=object(),
        thread=SimpleNamespace(id=20, version=1),
        openai_task_queue=asyncio.Queue(),
        assistant_audio_tracker=realtime_module.RealtimeAssistantAudioTracker(),
    )

    assert websocket.closed is True
    assert websocket.sent_json == [
        {
            "type": "error",
            "error": {
                "type": "invalid_request_error",
                "code": "openai_realtime_session",
                "message": "We were unable to start the voice session.",
                "param": None,
            },
        }
    ]


async def test_openai_startup_error_without_param_notifies_browser_and_closes_websocket():
    websocket = DummyWebSocket()
    error = SimpleNamespace(
        message="Model is unavailable.",
        type="invalid_request_error",
        code="model_unavailable",
        event_id="event_1",
        param=None,
    )
    realtime_connection = FakeRealtimeEventStream(
        [SimpleNamespace(type="error", error=error)]
    )

    await realtime_module.handle_openai_events(
        websocket,
        realtime_connection,
        openai_client=object(),
        thread=SimpleNamespace(id=20, version=1),
        openai_task_queue=asyncio.Queue(),
        assistant_audio_tracker=realtime_module.RealtimeAssistantAudioTracker(),
    )

    assert websocket.closed is True
    assert websocket.sent_json == [
        {
            "type": "error",
            "error": {
                "type": "invalid_request_error",
                "code": "openai_realtime_session",
                "message": "We were unable to start the voice session.",
                "param": None,
            },
        }
    ]


async def test_openai_recoverable_error_is_logged_without_closing_websocket():
    websocket = DummyWebSocket()
    error = SimpleNamespace(
        message="Temporary realtime error.",
        type="server_error",
        code="server_error",
        event_id="event_1",
        param=None,
    )
    realtime_connection = FakeRealtimeEventStream(
        [
            SimpleNamespace(type="session.updated", session=SimpleNamespace()),
            SimpleNamespace(type="error", error=error),
        ]
    )

    await realtime_module.handle_openai_events(
        websocket,
        realtime_connection,
        openai_client=object(),
        thread=SimpleNamespace(id=20, version=1),
        openai_task_queue=asyncio.Queue(),
        assistant_audio_tracker=realtime_module.RealtimeAssistantAudioTracker(),
    )

    assert websocket.closed is False
    assert websocket.sent_json == [
        {
            "type": "session.updated",
            "message": "Connected to OpenAI.",
        }
    ]


@pytest.mark.parametrize("has_recording,has_messages", [(True, False), (False, True)])
async def test_single_realtime_session_rejects_finished_thread(
    monkeypatch, has_recording, has_messages
):
    async def fake_get_by_id_with_assistant(_session, thread_id, **kwargs):
        assert kwargs == {
            "for_update": True,
            "include_voice_mode_recording": True,
        }
        return SimpleNamespace(
            id=thread_id,
            assistant=realtime_assistant(),
            instructions="Speak clearly.",
            timezone=None,
            voice_mode_recording=(
                SimpleNamespace(recording_id="recording.webm")
                if has_recording
                else None
            ),
        )

    async def fake_thread_has_messages(_db, _thread_id):
        return has_messages

    monkeypatch.setattr(
        models.Thread,
        "get_by_id_with_assistant",
        fake_get_by_id_with_assistant,
    )
    monkeypatch.setattr(
        websocket_module,
        "_thread_has_messages",
        fake_thread_has_messages,
    )

    websocket = DummyWebSocket()
    websocket.state["db"] = object()
    handler = AsyncMock()
    wrapped = websocket_module.ws_with_single_realtime_session(handler)

    await wrapped(websocket, "10", "20")

    handler.assert_not_awaited()
    assert websocket.closed is True
    assert (
        websocket.sent_json[0]["error"]["message"]
        == websocket_module.VOICE_SESSION_FINAL_MESSAGE
    )


@pytest.mark.parametrize(
    "model_id", ["gpt-realtime-2", "gpt-realtime-2.1", "gpt-realtime-2.1-mini"]
)
def test_realtime_reasoning_model_metadata(model_id):
    model = ai_models.KNOWN_MODELS[model_id]

    assert model["type"] == "voice"
    assert model["supports_reasoning"] is True
    assert model["supports_minimal_reasoning_effort"] is True
    assert ai_models.get_reasoning_effort_map(model_id) == {
        -1: "minimal",
        0: "low",
        1: "medium",
        2: "high",
    }


async def test_create_non_lecture_assistant_clears_elevenlabs_settings(db):
    req = schemas.CreateAssistant(
        name="Chat Assistant",
        instructions="You are a helpful assistant.",
        description="",
        model="gpt-4o-mini",
        elevenlabs_stability=0.9,
        elevenlabs_similarity_boost=0.4,
        elevenlabs_use_speaker_boost=False,
        elevenlabs_style=0.2,
        elevenlabs_speed=1.1,
    )
    for field in (
        "file_search_file_ids",
        "deleted_private_files",
        "mcp_servers",
        "lecture_video_id",
        "lecture_video_manifest",
        "voice_id",
        "generation_prompt",
        "video_description_duration_ms",
        "overwrite_manifest",
        "create_classic_assistant",
    ):
        delattr(req, field)

    async with db.async_session() as session:
        class_ = models.Class(id=1, name="Test Class", api_key="test-key")
        user = models.User(email="assistant-creator@example.com")
        session.add_all([class_, user])
        await session.flush()

        assistant = await models.Assistant.create(
            session,
            req,
            class_id=class_.id,
            user_id=user.id,
        )

        assert assistant.elevenlabs_stability is None
        assert assistant.elevenlabs_similarity_boost is None
        assert assistant.elevenlabs_use_speaker_boost is None
        assert assistant.elevenlabs_style is None
        assert assistant.elevenlabs_speed is None


def test_realtime_session_builds_server_vad_payload():
    session = websocket_module.build_realtime_session(
        realtime_assistant(
            realtime_vad_mode=schemas.RealtimeVadMode.SERVER_VAD,
            realtime_vad_threshold=0.7,
            realtime_vad_prefix_padding_ms=200,
            realtime_vad_silence_duration_ms=650,
            realtime_vad_idle_timeout_ms=10000,
            realtime_voice=schemas.RealtimeVoice.CEDAR,
            realtime_speed=0.75,
            realtime_noise_reduction=schemas.RealtimeNoiseReduction.NONE,
        ),
        "Speak clearly.",
    )

    assert session["audio"]["output"] == {"voice": "cedar", "speed": 0.75}
    assert session["audio"]["input"]["noise_reduction"] is None
    assert session["audio"]["input"]["turn_detection"] == {
        "create_response": True,
        "type": "server_vad",
        "interrupt_response": True,
        "threshold": 0.7,
        "prefix_padding_ms": 200,
        "silence_duration_ms": 650,
        "idle_timeout_ms": 10000,
    }


@pytest.mark.parametrize(
    "schema_type",
    [schemas.CreateAssistant, schemas.UpdateAssistant],
)
@pytest.mark.parametrize("idle_timeout_ms", [4999, 30001])
def test_realtime_vad_idle_timeout_validation_range(schema_type, idle_timeout_ms):
    payload = {"realtime_vad_idle_timeout_ms": idle_timeout_ms}
    if schema_type is schemas.CreateAssistant:
        payload |= {
            "name": "Voice assistant",
            "instructions": "You are a helpful assistant.",
            "description": "",
            "model": "gpt-4o-realtime-preview",
        }

    with pytest.raises(ValidationError):
        schema_type(**payload)


@pytest.mark.parametrize("idle_timeout_ms", [None, 5000, 30000])
def test_update_assistant_accepts_nullable_realtime_vad_idle_timeout(
    idle_timeout_ms,
):
    req = schemas.UpdateAssistant(realtime_vad_idle_timeout_ms=idle_timeout_ms)

    assert req.realtime_vad_idle_timeout_ms == idle_timeout_ms
