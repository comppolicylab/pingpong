import importlib
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from pingpong import schemas
from pingpong import websocket as websocket_module

server = importlib.import_module("pingpong.server")


class DummyWebSocket:
    def __init__(self, cookies: dict[str, str] | None = None):
        self.state: dict[str, object] = {}
        self.cookies: dict[str, str] = cookies or {}


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
        "model": "gpt-4o-realtime-preview",
        "assistant_should_message_first": False,
        "realtime_vad_mode": None,
        "realtime_eagerness": None,
        "realtime_vad_threshold": None,
        "realtime_vad_prefix_padding_ms": None,
        "realtime_vad_silence_duration_ms": None,
        "realtime_vad_idle_timeout_ms": None,
        "realtime_voice": None,
        "realtime_speed": None,
        "realtime_noise_reduction": None,
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def test_realtime_session_uses_create_defaults_for_null_fields():
    session = websocket_module.build_realtime_session(
        realtime_assistant(),
        "Speak clearly.",
    )

    assert session["instructions"] == "Speak clearly."
    assert session["audio"]["output"] == {"voice": "marin", "speed": 1.0}
    assert session["audio"]["input"]["noise_reduction"] == {"type": "far_field"}
    assert session["audio"]["input"]["turn_detection"] == {
        "create_response": True,
        "type": "semantic_vad",
        "interrupt_response": False,
        "eagerness": "auto",
    }


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
        "interrupt_response": False,
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
