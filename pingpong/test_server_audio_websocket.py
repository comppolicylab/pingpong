import asyncio
import importlib
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from openai.types.realtime import ResponseDoneEvent
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import selectinload
from starlette.datastructures import State

from pingpong import ai_models
from pingpong import models
from pingpong import realtime as realtime_module
from pingpong import schemas
from pingpong import websocket as websocket_module
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
