import asyncio
import inspect
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from openai.types.realtime import (
    ConversationItemInputAudioTranscriptionCompletedEvent,
    ConversationItemInputAudioTranscriptionDeltaEvent,
    ConversationItemInputAudioTranscriptionFailedEvent,
    ResponseDoneEvent,
)
from sqlalchemy import select

from pingpong import models, realtime, schemas, websocket as websocket_module
from pingpong.realtime_usage import RealtimeUsage
from pingpong.test_realtime_expiry import ExpiryBrowser
from pingpong.test_realtime_shutdown import (
    ShutdownConnection,
    event,
    shutdown_ack,
    wait_until,
)
from pingpong.test_server_audio_websocket import (
    DummyWebSocket,
    FakeOpenAIClient,
    FakeRealtimeConnection,
    FakeRealtimeEventStream,
    realtime_assistant,
    synthetic_assistant_audio,
)
from pingpong.testutil import with_user


RESPONSE_USAGE = {
    "input_tokens": 100,
    "output_tokens": 30,
    "total_tokens": 130,
    "input_token_details": {
        "text_tokens": 40,
        "audio_tokens": 60,
        "cached_tokens": 20,
        "cached_tokens_details": {"text_tokens": 10, "audio_tokens": 10},
    },
    "output_token_details": {"text_tokens": 10, "audio_tokens": 20},
    "additional_provider_detail": {"tokens": 2},
}


def response_done(status="cancelled", usage=RESPONSE_USAGE, response_id="resp_1"):
    status_details = None
    if status == "cancelled":
        status_details = {"type": "cancelled", "reason": "client_cancelled"}
    elif status == "failed":
        status_details = {
            "type": "failed",
            "error": {
                "type": "server_error",
                "code": "internal_error",
                "message": "Synthetic response failure.",
            },
        }
    return ResponseDoneEvent.model_validate(
        {
            "type": "response.done",
            "event_id": "response_finished",
            "response": {
                "id": response_id,
                "status": status,
                "status_details": status_details,
                "output": [
                    {
                        "id": "reply",
                        "type": "message",
                        "role": "assistant",
                        "status": "completed",
                        "content": [{"type": "output_audio", "transcript": "answer"}],
                    }
                ],
                "usage": usage,
            },
        }
    )


def transcription_done(usage, item_id="user", content_index=0):
    return ConversationItemInputAudioTranscriptionCompletedEvent.model_validate(
        {
            "type": "conversation.item.input_audio_transcription.completed",
            "event_id": "transcription_finished",
            "item_id": item_id,
            "content_index": content_index,
            "transcript": "question",
            "usage": usage,
        }
    )


def configured_session(model="whisper-1"):
    return event(
        "session.updated",
        session=SimpleNamespace(
            audio=SimpleNamespace(
                input=SimpleNamespace(transcription=SimpleNamespace(model=model))
            )
        ),
    )


@pytest.mark.parametrize("event_type", ["session.created", "session.updated"])
def test_session_id_is_captured_without_creating_usage_records(event_type):
    usage = RealtimeUsage()
    usage.observe(event(event_type, session=SimpleNamespace(id="sess_voice")))
    # An update without an ID must not erase the ID already received.
    usage.observe(configured_session())

    assert usage.session_id == "sess_voice"
    assert not usage.has_records


@pytest.mark.parametrize("status", ["completed", "cancelled", "failed", "incomplete"])
def test_response_usage_is_idempotent_and_preserves_provider_fields(status):
    usage = RealtimeUsage()
    usage.observe(event("response.created", response=SimpleNamespace(id="resp_1")))
    usage.observe(response_done(status))
    usage.observe(response_done(status))
    usage.observe(response_done(status, usage=None))
    # An out-of-order creation must not reopen a finished response.
    usage.observe(event("response.created", response=SimpleNamespace(id="resp_1")))

    assert not usage.pending_response_ids
    assert len(usage.responses) == 1
    assert usage.responses["resp_1"]["item_ids"] == ["reply"]
    assert usage.responses["resp_1"]["status"] == status
    assert usage.responses["resp_1"]["usage"] == RESPONSE_USAGE


@pytest.mark.parametrize(
    "payload",
    [
        {"type": "duration", "seconds": 3.25},
        {
            "type": "tokens",
            "input_tokens": 13,
            "output_tokens": 9,
            "total_tokens": 22,
            "input_token_details": {"audio_tokens": 13, "text_tokens": 0},
            "provider_extension": 1,
        },
    ],
)
def test_transcription_usage_is_separate_and_keyed_by_item_and_content(payload):
    usage = RealtimeUsage()
    usage.observe(configured_session())
    usage.observe(event("input_audio_buffer.committed", item_id="user"))
    usage.observe(transcription_done(payload))
    usage.observe(transcription_done(payload))
    usage.observe(
        event("conversation.item.input_audio_transcription.failed", item_id="user")
    )
    usage.observe(transcription_done(payload, content_index=1))
    usage.observe(response_done())

    assert usage.transcriptions == {
        "user": {
            "0": {"model": "whisper-1", "usage": payload},
            "1": {"model": "whisper-1", "usage": payload},
        }
    }
    assert usage.responses["resp_1"]["usage"] == RESPONSE_USAGE


@pytest.mark.parametrize("content_index", [None, 0, 1])
def test_transcription_delta_uses_the_completed_content_index(content_index):
    usage = RealtimeUsage()
    delta = ConversationItemInputAudioTranscriptionDeltaEvent.model_validate(
        {
            "type": "conversation.item.input_audio_transcription.delta",
            "event_id": "delta",
            "item_id": "user",
            "content_index": content_index,
            "delta": "question",
        }
    )
    usage.observe(delta)
    usage.observe(
        transcription_done(
            {"type": "duration", "seconds": 1}, content_index=content_index or 0
        )
    )

    assert list(usage.transcriptions["user"]) == [str(content_index or 0)]
    assert usage.transcriptions["user"][str(content_index or 0)]["usage"] == {
        "type": "duration",
        "seconds": 1,
    }


def test_transcription_failure_diagnostics_are_separate_and_idempotent():
    failure = ConversationItemInputAudioTranscriptionFailedEvent.model_validate(
        {
            "type": "conversation.item.input_audio_transcription.failed",
            "event_id": "transcription_error",
            "item_id": "user",
            "content_index": 1,
            "error": {
                "code": "transcription_failed",
                "message": "Synthetic transcription failure.",
                "type": "server_error",
                "param": None,
            },
        }
    )
    usage = RealtimeUsage()
    usage.observe(failure)
    usage.observe(failure)

    assert usage.to_json()["transcriptions"] == {
        "user": {"1": {"model": None, "usage": None}}
    }
    diagnostics = usage.provider_metadata_to_json()
    assert diagnostics["errors"] == [
        {
            "event_id": "transcription_error",
            "item_id": "user",
            "content_index": 1,
            "error": {
                "code": "transcription_failed",
                "message": "Synthetic transcription failure.",
                "type": "server_error",
                "param": None,
                "event_id": None,
            },
        }
    ]
    diagnostics["errors"][0]["error"]["message"] = "changed"
    assert (
        usage.provider_metadata_to_json()["errors"][0]["error"]["message"]
        == failure.error.message
    )
    assert usage.final_status == schemas.RunStatus.COMPLETED


def test_missing_usage_stays_unknown_and_zero_usage_is_preserved():
    usage = RealtimeUsage()
    usage.observe(event("response.created", response=SimpleNamespace(id="unknown")))
    usage.observe(event("input_audio_buffer.committed", item_id="pending"))
    zero = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
    usage.observe(response_done(usage=zero))

    assert usage.responses["unknown"]["usage"] is None
    assert usage.responses["unknown"]["status"] is None
    assert usage.transcriptions["pending"]["0"]["usage"] is None
    assert usage.responses["resp_1"]["usage"] == zero
    assert usage.pending_response_ids == {"unknown"}


def test_output_item_links_usage_before_response_done_without_reopening_finished_response():
    usage = RealtimeUsage()
    item = event(
        "response.output_item.added",
        response_id="resp_1",
        item=SimpleNamespace(id="reply"),
    )
    usage.observe(item)
    assert usage.pending_response_ids == {"resp_1"}
    assert usage.responses["resp_1"]["item_ids"] == ["reply"]
    usage.observe(response_done())
    usage.observe(item)
    assert not usage.pending_response_ids


def test_invalid_usage_metadata_does_not_break_event_processing(caplog):
    usage = RealtimeUsage()
    usage.observe(
        event(
            "response.done",
            response=SimpleNamespace(id="bad", output=[], usage=object()),
        )
    )
    assert usage.responses["bad"]["usage"] is None
    assert "Failed to serialize realtime usage metadata" in caplog.text


def test_usage_and_diagnostic_snapshots_are_separate_and_do_not_alias_tracker_state():
    usage = RealtimeUsage()
    usage.observe(response_done("failed"))
    usage.record_error(
        event("error", event_id="event_error", error=SimpleNamespace(code="test_error"))
    )
    accounting = usage.to_json()
    diagnostics = usage.provider_metadata_to_json()

    assert accounting == {
        "schema_version": 1,
        "provider": "openai",
        "api": "realtime",
        "responses": {"resp_1": {"usage": RESPONSE_USAGE}},
        "transcriptions": {},
    }
    assert set(diagnostics) == {
        "schema_version",
        "provider",
        "api",
        "responses",
        "errors",
    }
    assert set(diagnostics["responses"]["resp_1"]) == {
        "item_ids",
        "status",
        "status_details",
    }
    assert diagnostics["errors"][0]["error"]["code"] == "test_error"

    accounting["responses"]["resp_1"]["usage"]["input_token_details"][
        "audio_tokens"
    ] = -1
    diagnostics["responses"]["resp_1"]["item_ids"].append("extra")
    diagnostics["responses"]["resp_1"]["status_details"]["error"]["code"] = "changed"
    diagnostics["errors"][0]["error"]["code"] = "changed"
    assert usage.to_json()["responses"]["resp_1"]["usage"] == RESPONSE_USAGE
    original = usage.provider_metadata_to_json()
    assert original["responses"]["resp_1"]["item_ids"] == ["reply"]
    assert (
        original["responses"]["resp_1"]["status_details"]["error"]["code"]
        == "internal_error"
    )
    assert original["errors"][0]["error"]["code"] == "test_error"


def test_transcription_only_usage_has_no_response_diagnostics():
    usage = RealtimeUsage()
    usage.observe(configured_session())
    usage.observe(transcription_done({"type": "duration", "seconds": 2.5}))

    assert usage.to_json()["transcriptions"] == {
        "user": {
            "0": {"model": "whisper-1", "usage": {"type": "duration", "seconds": 2.5}}
        }
    }
    assert usage.provider_metadata_to_json() is None


def test_content_filter_reason_is_preserved_only_in_provider_metadata():
    payload = response_done("incomplete").model_dump(mode="json", exclude_unset=True)
    payload["response"]["status_details"] = {
        "type": "incomplete",
        "reason": "content_filter",
    }
    usage = RealtimeUsage()
    usage.observe(ResponseDoneEvent.model_validate(payload))

    assert usage.to_json()["responses"] == {"resp_1": {"usage": RESPONSE_USAGE}}
    assert usage.provider_metadata_to_json()["responses"]["resp_1"] == {
        "item_ids": ["reply"],
        "status": "incomplete",
        "status_details": {"type": "incomplete", "reason": "content_filter"},
    }


async def test_received_usage_survives_cancellation_during_browser_delivery():
    drain = realtime.RealtimeShutdownDrain()
    browser = DummyWebSocket()
    started = asyncio.Event()

    async def blocked(data):
        started.set()
        await asyncio.Future()

    browser.send_json = blocked
    task = asyncio.create_task(
        realtime.handle_openai_events(
            browser,
            FakeRealtimeEventStream([response_done()]),
            None,
            SimpleNamespace(version=1),
            asyncio.Queue(),
            realtime.RealtimeAssistantAudioTracker(),
            shutdown_drain=drain,
        )
    )
    try:
        await asyncio.wait_for(started.wait(), 1)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, 1)
        assert drain.usage.responses["resp_1"]["usage"] == RESPONSE_USAGE
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


async def test_shutdown_cancels_late_responses_and_waits_for_each_final_event():
    drain = realtime.RealtimeShutdownDrain()
    connection = ShutdownConnection()
    drain.observe(event("response.created", response=SimpleNamespace(id="resp_1")))
    buffer = realtime.ConversationItemOrderingBuffer(realtime.openai_connection_logger)
    task = asyncio.create_task(drain.wait(connection, buffer))
    try:
        await wait_until(lambda: connection.response.cancel.await_count == 1)
        drain.observe(shutdown_ack())
        drain.observe(event("input_audio_buffer.cleared"))
        drain.observe(event("response.created", response=SimpleNamespace(id="late")))
        await wait_until(lambda: connection.response.cancel.await_count == 2)
        drain.observe(response_done())
        await asyncio.sleep(0)
        assert not task.done()
        drain.observe(response_done(response_id="late"))
        await asyncio.wait_for(task, 1)
        connection.assert_shutdown_controls(response_ids=("resp_1", "late"))
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


async def test_clear_ack_is_required_but_old_clear_ack_does_not_count():
    drain = realtime.RealtimeShutdownDrain()
    connection = ShutdownConnection()
    drain.observe(event("input_audio_buffer.cleared"))
    buffer = realtime.ConversationItemOrderingBuffer(realtime.openai_connection_logger)
    task = asyncio.create_task(drain.wait(connection, buffer))
    try:
        await wait_until(lambda: connection.input_audio_buffer.clear.await_count == 1)
        drain.observe(shutdown_ack())
        await asyncio.sleep(0)
        assert not task.done()
        drain.observe(event("input_audio_buffer.cleared"))
        await asyncio.wait_for(task, 1)
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.parametrize("failure", ["send", "error", "session.error"])
async def test_failed_clear_releases_only_its_ack_wait(monkeypatch, failure):
    monkeypatch.setattr(realtime, "BROWSER_DISCONNECT_DRAIN_SECONDS", 1)
    drain = realtime.RealtimeShutdownDrain()
    drain.observe(event("response.created", response=SimpleNamespace(id="resp_1")))
    drain.observe(event("input_audio_buffer.committed", item_id="user"))
    connection = ShutdownConnection()
    if failure == "send":
        connection.input_audio_buffer.clear.side_effect = BrokenPipeError(
            "Clear failed."
        )
    else:
        connection.input_audio_buffer.clear.side_effect = None
    buffer = realtime.ConversationItemOrderingBuffer(realtime.openai_connection_logger)
    task = asyncio.create_task(drain.wait(connection, buffer))
    try:
        await wait_until(lambda: connection.input_audio_buffer.clear.await_count == 1)
        drain.observe(shutdown_ack())
        unrelated = event("error", error=SimpleNamespace(event_id="unrelated"))
        drain.observe(unrelated)
        if failure != "send":
            assert not drain._clear_failed
            rejection = event(
                failure,
                error=SimpleNamespace(
                    event_id="voice_shutdown_clear", code="clear_rejected"
                ),
            )
            await realtime.handle_openai_events(
                DummyWebSocket(),
                FakeRealtimeEventStream([rejection]),
                None,
                SimpleNamespace(version=1),
                asyncio.Queue(),
                realtime.RealtimeAssistantAudioTracker(),
                shutdown_drain=drain,
            )
        assert not drain._buffer_cleared
        assert drain._clear_failed
        assert not task.done()
        drain.observe(response_done())
        await asyncio.sleep(0)
        assert not task.done()
        drain.observe(transcription_done({"type": "duration", "seconds": 1}))
        await asyncio.wait_for(task, 0.5)
        assert drain.usage.final_status == schemas.RunStatus.INCOMPLETE
        assert drain.usage.incomplete_reason == "input_audio_buffer_clear_failed"
        assert len(drain.usage.provider_metadata_to_json()["errors"]) == 1
        assert drain.usage.responses["resp_1"]["usage"] == RESPONSE_USAGE
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.parametrize("stalled", ["update", "clear", "cancel", "response_done"])
async def test_shutdown_controls_and_missing_response_share_one_deadline(
    monkeypatch, caplog, stalled
):
    monkeypatch.setattr(realtime, "BROWSER_DISCONNECT_DRAIN_SECONDS", 0.02)
    drain = realtime.RealtimeShutdownDrain()
    connection = ShutdownConnection()
    drain.observe(event("response.created", response=SimpleNamespace(id="resp_1")))

    async def block(**kwargs):
        await asyncio.Future()

    if stalled == "update":
        connection.session.update.side_effect = block
    elif stalled == "clear":
        connection.input_audio_buffer.clear.side_effect = block
    elif stalled == "cancel":
        connection.response.cancel.side_effect = block
    buffer = realtime.ConversationItemOrderingBuffer(realtime.openai_connection_logger)
    await asyncio.wait_for(drain.wait(connection, buffer), 1)

    assert drain.usage.responses["resp_1"]["usage"] is None
    assert drain.usage.final_status == schemas.RunStatus.INCOMPLETE
    assert drain.usage.incomplete_reason == "shutdown_drain_timeout"
    assert "Voice shutdown drain reached its deadline" in caplog.text
    assert "pending_responses=" in caplog.text
    connection.input_audio_buffer.commit.assert_not_awaited()
    connection.response.create.assert_not_awaited()


@with_user(123)
@pytest.mark.parametrize("version", [1, 3])
@pytest.mark.parametrize("session_id", [None, "sess_voice"])
async def test_usage_only_run_preserves_cost_data_without_retaining_a_conversation(
    db, user, version, session_id
):
    async with db.async_session() as session:
        thread = models.Thread(version=version, user_message_ct=0, tools_available="[]")
        session.add(thread)
        await session.flush()
        browser = DummyWebSocket()
        browser.state["db"] = session
        browser.state["session"] = SimpleNamespace(user=user)
        browser.state["assistant"] = realtime_assistant()
        usage = RealtimeUsage()
        usage.observe(event("session.updated", session=SimpleNamespace(id=session_id)))
        usage.observe(response_done("failed"))
        await realtime.save_voice_usage(browser, thread, usage)
        usage.observe(response_done(response_id="resp_2"))
        await realtime.save_voice_usage(browser, thread, usage)
        await session.commit()

    async with db.async_session() as session:
        runs = (await session.scalars(select(models.Run))).all()
        assert len(runs) == 1
        assert runs[0].run_id == session_id
        assert runs[0].status == schemas.RunStatus.COMPLETED
        assert runs[0].completed is not None
        assert runs[0].usage == usage.to_json()
        assert runs[0].provider_metadata == usage.provider_metadata_to_json()
        assert runs[0].usage["responses"] == {
            "resp_1": {"usage": RESPONSE_USAGE},
            "resp_2": {"usage": RESPONSE_USAGE},
        }
        assert runs[0].model == browser.state["assistant"].model
        assert not await websocket_module._thread_has_messages(
            session, runs[0].thread_id
        )
        assert await session.scalar(select(models.VoiceModeRecording.id)) is None
        saved_thread = await session.get(models.Thread, runs[0].thread_id)
        assert saved_thread.user_message_ct == 0


@with_user(123)
@pytest.mark.parametrize("version", [1, 3])
async def test_failed_response_without_usage_or_playback_is_retained(db, user, version):
    async with db.async_session() as session:
        thread = models.Thread(
            version=version,
            user_message_ct=0,
            tools_available="[]",
            instructions="Thread-owned voice instructions.",
        )
        session.add(thread)
        await session.flush()
        thread_id = thread.id
        browser = DummyWebSocket()
        browser.state["db"] = session
        browser.state["session"] = SimpleNamespace(user=user)
        browser.state["conversation_instructions"] = "Effective voice instructions."
        usage = RealtimeUsage()
        usage.observe(
            event("session.created", session=SimpleNamespace(id="sess_failed"))
        )
        usage.observe(response_done("failed", usage=None))

        await realtime.save_voice_usage(browser, thread, usage)
        await session.commit()

    async with db.async_session() as session:
        run = (await session.scalars(select(models.Run))).one()
        assert run.run_id == "sess_failed"
        assert run.instructions is None
        assert run.usage["responses"]["resp_1"] == {"usage": None}
        assert run.provider_metadata["responses"]["resp_1"] == {
            "item_ids": ["reply"],
            "status": "failed",
            "status_details": {
                "type": "failed",
                "error": {
                    "type": "server_error",
                    "code": "internal_error",
                    "message": "Synthetic response failure.",
                },
            },
        }
        assert not await websocket_module._thread_has_messages(session, thread_id)
        assert await session.scalar(select(models.VoiceModeRecording.id)) is None
        saved_thread = await session.get(models.Thread, thread_id)
        assert saved_thread.instructions == "Thread-owned voice instructions."
        assert saved_thread.user_message_ct == 0


@with_user(123)
@pytest.mark.parametrize("event_type", ["error", "session.error"])
async def test_startup_error_without_provider_operations_is_retained(
    db, user, event_type
):
    async with db.async_session() as session:
        thread = models.Thread(version=3, user_message_ct=0, tools_available="[]")
        session.add(thread)
        await session.flush()
        browser = DummyWebSocket()
        browser.state["db"] = session
        browser.state["session"] = SimpleNamespace(user=user)
        drain = realtime.RealtimeShutdownDrain()
        failure = event(
            event_type,
            event_id="event_failure",
            error=SimpleNamespace(
                type="invalid_request_error",
                code="model_not_found",
                message="Synthetic startup failure.",
                param="session.model",
                event_id="client_update",
            ),
        )
        await realtime.handle_openai_events(
            browser,
            FakeRealtimeEventStream(
                [
                    event("session.created", session=SimpleNamespace(id="sess_failed")),
                    failure,
                ]
            ),
            None,
            thread,
            asyncio.Queue(),
            realtime.RealtimeAssistantAudioTracker(),
            shutdown_drain=drain,
        )
        # Replayed delivery must not duplicate an error record.
        drain.usage.record_error(failure)
        await realtime.save_voice_usage(browser, thread, drain.usage)
        await session.commit()

    async with db.async_session() as session:
        run = (await session.scalars(select(models.Run))).one()
        assert run.run_id == "sess_failed"
        assert run.status == schemas.RunStatus.FAILED
        assert run.error_code == "model_not_found"
        assert run.error_message == "Synthetic startup failure."
        assert run.incomplete_reason is None
        assert run.completed is not None
        assert run.instructions is None
        assert run.usage is None
        assert run.provider_metadata["responses"] == {}
        assert run.provider_metadata["errors"] == [
            {
                "event_id": "event_failure",
                "error": {
                    "type": "invalid_request_error",
                    "code": "model_not_found",
                    "message": "Synthetic startup failure.",
                    "param": "session.model",
                    "event_id": "client_update",
                },
            }
        ]
        assert not await websocket_module._thread_has_messages(session, run.thread_id)


@with_user(123)
@pytest.mark.parametrize("stage", ["connect", "update", "greeting", "handler"])
@pytest.mark.parametrize("save_fails", [False, True])
async def test_provider_startup_failure_survives_transaction_rollback(
    db, user, monkeypatch, caplog, stage, save_fails
):
    async with db.async_session() as session:
        thread = models.Thread(version=3, user_message_ct=0, tools_available="[]")
        session.add(thread)
        await session.flush()
        thread_id = thread.id
        await session.commit()

    browser = DummyWebSocket()
    browser.state["session"] = SimpleNamespace(user=user)
    browser.state["assistant"] = realtime_assistant(assistant_should_message_first=True)
    browser.state["conversation_instructions"] = "Speak clearly."
    failure = RuntimeError("Synthetic provider startup failure.")
    connection = FakeRealtimeConnection()
    client = FakeOpenAIClient(connection)
    if stage == "connect":
        client.realtime.connect = Mock(side_effect=failure)
    elif stage == "update":
        connection.session.update = AsyncMock(side_effect=failure)
    elif stage == "greeting":
        connection.response.create = AsyncMock(side_effect=failure)
    handler = AsyncMock(side_effect=failure if stage == "handler" else None)
    browser.state["openai_client"] = client
    provider_handler = websocket_module.ws_with_realtime_connection(handler)

    async def load_thread(socket, class_id, thread_id):
        thread = await socket.state["db"].scalar(
            select(models.Thread)
            .where(models.Thread.id == int(thread_id))
            .with_for_update()
        )
        socket.state["thread"] = thread
        thread.user_message_ct = 42
        await socket.state["db"].flush()
        await provider_handler(socket, class_id, thread_id)

    if save_fails:
        monkeypatch.setattr(
            db,
            "async_session",
            Mock(side_effect=RuntimeError("Error run save failed.")),
        )
    with pytest.raises(RuntimeError) as raised:
        await websocket_module.ws_db_middleware(load_thread)(
            browser, "1", str(thread_id)
        )
    assert raised.value is failure
    assert handler.await_count == int(stage == "handler")
    assert len(browser.state["after_db_rollback"]) == int(stage != "handler")
    if save_fails:
        monkeypatch.undo()
        if stage != "handler":
            assert "Websocket database completion notification failed" in caplog.text

    async with db.async_session() as session:
        saved_thread = await session.get(models.Thread, thread_id)
        assert saved_thread.user_message_ct == 0
        assert not await websocket_module._thread_has_messages(session, thread_id)
        assert await session.scalar(select(models.VoiceModeRecording.id)) is None
        runs = (await session.scalars(select(models.Run))).all()
        if stage == "handler" or save_fails:
            assert runs == []
        else:
            assert len(runs) == 1
            run = runs[0]
            assert run.status == schemas.RunStatus.FAILED
            assert run.completed is not None
            assert run.error_code == "provider_startup_error"
            assert run.error_message == str(failure)
            assert run.model == browser.state["assistant"].model
            assert run.creator_id == user.id
            assert run.usage is None
            assert run.instructions is None
            assert run.provider_metadata["errors"] == [
                {
                    "event_id": None,
                    "error": {
                        "type": "RuntimeError",
                        "code": "provider_startup_error",
                        "message": str(failure),
                        "param": None,
                        "event_id": None,
                    },
                }
            ]


@with_user(123)
@pytest.mark.parametrize(
    "ending",
    [
        "completed",
        "failed",
        "incomplete",
        "failure_then_disconnect",
        "disconnect_then_failure",
    ],
)
async def test_existing_voice_run_gets_session_outcome_at_finalization(
    db, user, ending
):
    async with db.async_session() as session:
        thread = models.Thread(version=3, user_message_ct=0, tools_available="[]")
        session.add(thread)
        await session.flush()
        browser = DummyWebSocket()
        browser.state["db"] = session
        browser.state["session"] = SimpleNamespace(user=user)
        assert await realtime.add_message_to_thread(
            None, browser, thread, "user", "question", "user"
        )
        run_id = browser.state["voice_mode_run_id"]
        run = await session.get(models.Run, run_id)
        assert run.status == schemas.RunStatus.IN_PROGRESS
        assert run.completed is None
        usage = RealtimeUsage()
        if ending == "disconnect_then_failure":
            usage.mark_incomplete("provider_connection_closed")
        if ending in {"failed", "failure_then_disconnect", "disconnect_then_failure"}:
            usage.fail("invalid_session", "Synthetic terminal failure.")
            usage.fail("later_error", "This must not replace the first error.")
        if ending in {"incomplete", "failure_then_disconnect"}:
            usage.mark_incomplete("provider_connection_closed")
        await realtime.save_voice_usage(browser, thread, usage)
        await session.commit()

    async with db.async_session() as session:
        run = (await session.scalars(select(models.Run))).one()
        assert run.id == run_id
        assert run.completed is not None
        if ending == "completed":
            assert run.status == schemas.RunStatus.COMPLETED
            assert run.error_code is None and run.error_message is None
            assert run.incomplete_reason is None
        elif ending == "incomplete":
            assert run.status == schemas.RunStatus.INCOMPLETE
            assert run.incomplete_reason == "provider_connection_closed"
            assert run.error_code is None and run.error_message is None
        else:
            assert run.status == schemas.RunStatus.FAILED
            assert run.error_code == "invalid_session"
            assert run.error_message == "Synthetic terminal failure."
            assert run.incomplete_reason is None


@with_user(123)
async def test_session_id_alone_does_not_create_a_run(db, user):
    async with db.async_session() as session:
        thread = models.Thread(version=3, user_message_ct=0, tools_available="[]")
        session.add(thread)
        await session.flush()
        browser = DummyWebSocket()
        browser.state["db"] = session
        browser.state["session"] = SimpleNamespace(user=user)
        usage = RealtimeUsage()
        usage.observe(
            event("session.created", session=SimpleNamespace(id="sess_empty"))
        )

        await realtime.save_voice_usage(browser, thread, usage)

        assert await session.scalar(select(models.Run.id)) is None


@with_user(123)
@pytest.mark.parametrize("ending", ["eof", "transport_error", "internal_error"])
async def test_provider_reader_failure_without_usage_is_retained(db, user, ending):
    class EndingStream:
        async def __aiter__(self):
            yield event("session.created", session=SimpleNamespace(id="sess_ended"))
            if ending == "transport_error":
                raise BrokenPipeError("Synthetic transport failure.")
            if ending == "internal_error":
                raise RuntimeError("Synthetic internal failure with private detail.")

    async with db.async_session() as session:
        thread = models.Thread(version=3, user_message_ct=0, tools_available="[]")
        session.add(thread)
        await session.flush()
        browser = DummyWebSocket()
        browser.state["db"] = session
        browser.state["session"] = SimpleNamespace(user=user)
        drain = realtime.RealtimeShutdownDrain()
        await realtime.handle_openai_events(
            browser,
            EndingStream(),
            None,
            thread,
            asyncio.Queue(),
            realtime.RealtimeAssistantAudioTracker(),
            shutdown_drain=drain,
        )
        await realtime.save_voice_usage(browser, thread, drain.usage)
        await session.commit()

    async with db.async_session() as session:
        run = (await session.scalars(select(models.Run))).one()
        assert run.run_id == "sess_ended"
        assert run.completed is not None
        assert run.usage is None
        assert run.provider_metadata is None
        if ending == "internal_error":
            assert run.status == schemas.RunStatus.FAILED
            assert run.error_code == "voice_event_processing_error"
            assert (
                run.error_message
                == "An internal error interrupted voice event processing."
            )
            assert run.incomplete_reason is None
        else:
            assert run.status == schemas.RunStatus.INCOMPLETE
            assert run.incomplete_reason == "provider_connection_closed"
            assert run.error_code is None and run.error_message is None


@pytest.mark.parametrize("connection_error", [False, True])
async def test_provider_close_after_final_events_keeps_session_completed(
    connection_error,
):
    class FinalEvents:
        async def __aiter__(self):
            yield response_done(usage=None)
            if connection_error:
                raise BrokenPipeError("Provider closed after the final events.")

    drain = realtime.RealtimeShutdownDrain()
    drain.stopping = True
    drain._clear_requested = True
    drain.observe(shutdown_ack())
    drain.observe(event("input_audio_buffer.cleared"))
    await realtime.handle_openai_events(
        DummyWebSocket(),
        FinalEvents(),
        None,
        SimpleNamespace(version=1),
        asyncio.Queue(),
        realtime.RealtimeAssistantAudioTracker(),
        shutdown_drain=drain,
    )

    assert drain.usage.final_status == schemas.RunStatus.COMPLETED
    assert drain.usage.incomplete_reason is None
    assert drain.usage.error_code is None
    assert drain.usage.responses["resp_1"]["usage"] is None


@with_user(123)
@pytest.mark.parametrize("ending", ["completed", "failed", "incomplete"])
@pytest.mark.parametrize("fallback_fails", [False, True])
async def test_failed_usage_save_does_not_rollback_saved_transcripts(
    db, user, monkeypatch, ending, fallback_fails
):
    async with db.async_session() as session:
        thread = models.Thread(version=3, user_message_ct=0, tools_available="[]")
        session.add(thread)
        await session.flush()
        browser = DummyWebSocket()
        browser.state["db"] = session
        browser.state["session"] = SimpleNamespace(user=user)
        assert await realtime.add_message_to_thread(
            None, browser, thread, "user", "question", "user"
        )
        usage = RealtimeUsage()
        usage.observe(response_done())
        if ending == "failed":
            usage.fail("provider_error", "Synthetic provider failure.")
        elif ending == "incomplete":
            usage.mark_incomplete("provider_connection_closed")
        flush = session.flush

        async def fail_usage_flush(*args, **kwargs):
            if any(isinstance(obj, models.Run) and obj.usage for obj in session.dirty):
                raise RuntimeError("synthetic usage save failure")
            if fallback_fails and any(
                isinstance(obj, models.Run) for obj in session.dirty
            ):
                raise RuntimeError("synthetic terminal status save failure")
            await flush(*args, **kwargs)

        monkeypatch.setattr(session, "flush", fail_usage_flush)
        await realtime.save_voice_usage(browser, thread, usage)
        monkeypatch.setattr(session, "flush", flush)
        assert session.is_active
        await session.commit()

    async with db.async_session() as session:
        assert (
            await session.scalars(select(models.Message))
        ).one().message_id == "user"
        run = (await session.scalars(select(models.Run))).one()
        assert run.usage is None
        assert run.provider_metadata is None
        if fallback_fails:
            assert run.status == schemas.RunStatus.IN_PROGRESS
            assert run.completed is None
        else:
            assert run.completed is not None
            assert run.status == (
                schemas.RunStatus.FAILED
                if ending == "failed"
                else schemas.RunStatus.INCOMPLETE
            )
            assert run.error_code == usage.error_code
            assert run.error_message == usage.error_message
            assert run.incomplete_reason == (
                None
                if ending == "failed"
                else usage.incomplete_reason or "usage_save_failed"
            )


@with_user(123)
@pytest.mark.parametrize("played", [False, True])
@pytest.mark.parametrize(
    "ending",
    [
        "cancelled",
        "completed_race",
        "completed_without_usage",
        "missing_done",
        "closed",
        "closed_after_done",
        "recovered",
        "shutdown_control_error",
    ],
)
async def test_session_persists_usage_after_transcripts_without_playback_gating(
    db, user, monkeypatch, caplog, played, ending
):
    connection = ShutdownConnection()
    if ending in {"missing_done", "shutdown_control_error"}:
        monkeypatch.setattr(realtime, "BROWSER_DISCONNECT_DRAIN_SECONDS", 0.02)
    transcription_usage = {"type": "duration", "seconds": 3.25}

    async def cancel(*, response_id, event_id):
        if ending == "closed":
            connection.events.put_nowait(None)
            return
        if ending != "missing_done":
            connection.events.put_nowait(
                response_done(
                    "completed"
                    if ending in {"completed_race", "completed_without_usage"}
                    else "cancelled",
                    usage=None
                    if ending == "completed_without_usage"
                    else RESPONSE_USAGE,
                )
            )
        if ending == "completed_race":
            connection.events.put_nowait(
                event(
                    "error",
                    error=SimpleNamespace(
                        code="response_cancel_not_active", event_id=event_id
                    ),
                )
            )
        connection.events.put_nowait(transcription_done(transcription_usage))
        if ending == "closed_after_done":
            connection.events.put_nowait(None)

    connection.response.cancel.side_effect = cancel
    connection.session.update.side_effect = (
        lambda **kwargs: connection.events.put_nowait(
            event(
                "error",
                error=SimpleNamespace(
                    code="invalid_value",
                    param="session.audio.input.turn_detection",
                    message="Synthetic shutdown update rejection.",
                ),
            )
            if ending == "shutdown_control_error"
            else shutdown_ack()
        )
    )

    async with db.async_session() as session:
        thread = models.Thread(
            version=3,
            user_message_ct=0,
            tools_available="[]",
            display_user_info=False,
            instructions="Thread-owned voice instructions.",
        )
        session.add(thread)
        await session.flush()
        thread_id = thread.id
        browser = ExpiryBrowser()
        browser.state["db"] = session
        browser.state["session"] = SimpleNamespace(user=user)
        browser.state["assistant"] = realtime_assistant()
        browser.state["conversation_instructions"] = "Effective voice instructions."
        browser.state["thread"] = thread
        browser.state["openai_client"] = None
        browser.state["realtime_connection"] = connection
        browser.state["after_db_commit"] = []
        browser.state["after_db_rollback"] = []
        send_json = browser.send_json

        async def report_playback_and_end(data):
            await send_json(data)
            if data["type"] == "response.audio.delta":
                if played:
                    browser.telemetry(
                        type="response.audio.delta.started",
                        item_id="reply",
                        event_id="audio-1",
                        started_playing_at=123,
                    )
                browser.telemetry(
                    type="response.audio.playback.settled",
                    item_id="reply",
                    outcome="interrupted" if played else "discarded",
                    played=played,
                )
                browser.telemetry(type="session.stop")

        browser.send_json = report_playback_and_end
        failed_response = response_done("failed", response_id="resp_failed")
        failed_response.response.output = []
        for incoming in [
            event("session.created", session=SimpleNamespace(id="sess_voice")),
            configured_session(),
            *([failed_response] if ending == "recovered" else []),
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
            event("response.created", response=SimpleNamespace(id="resp_1")),
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
            synthetic_assistant_audio(),
        ]:
            connection.events.put_nowait(incoming)

        await asyncio.wait_for(
            inspect.unwrap(realtime.browser_realtime_websocket)(
                browser, "1", str(thread_id)
            ),
            2,
        )
        await session.commit()
        for callback in browser.state["after_db_commit"]:
            await callback()
        assert connection.reader_stopped.is_set()
        assert browser.sent_json[-1] == {"type": "session.stopped", "saved": True}
        assert sum(message["type"] == "error" for message in browser.sent_json) == int(
            ending == "recovered"
        )
        assert ("Session error:" in caplog.text) == (ending == "shutdown_control_error")
        connection.assert_shutdown_controls(response_ids=("resp_1",))

    async with db.async_session() as session:
        run = (await session.scalars(select(models.Run))).one()
        assert run.run_id == "sess_voice"
        assert "errors" not in run.usage
        assert ("errors" in run.provider_metadata) == (
            ending == "shutdown_control_error"
        )
        assert run.status == (
            schemas.RunStatus.INCOMPLETE
            if ending in {"missing_done", "closed", "shutdown_control_error"}
            else schemas.RunStatus.COMPLETED
        )
        assert run.error_code is None and run.error_message is None
        assert run.completed is not None
        assert run.incomplete_reason == (
            "provider_connection_closed"
            if ending == "closed"
            else "shutdown_drain_timeout"
            if ending in {"missing_done", "shutdown_control_error"}
            else None
        )
        if ending == "recovered":
            assert (
                run.provider_metadata["responses"]["resp_failed"]["status"] == "failed"
            )
        assert run.instructions is None
        saved_thread = await session.get(models.Thread, thread_id)
        assert saved_thread.instructions == "Thread-owned voice instructions."
        response = run.usage["responses"]["resp_1"]
        assert response["usage"] == (
            None
            if ending in {"missing_done", "closed", "completed_without_usage"}
            else RESPONSE_USAGE
        )
        assert run.usage["transcriptions"]["user"]["0"] == {
            "model": "whisper-1",
            "usage": None if ending == "closed" else transcription_usage,
        }
        messages = (await session.scalars(select(models.Message))).all()
        assert len(messages) == (2 if played else 0)
        assert all(message.run_id == run.id for message in messages)
        assert await websocket_module._thread_has_messages(session, thread_id) == played
        if played and ending in {"missing_done", "closed"}:
            reply = next(
                message
                for message in messages
                if message.role == schemas.MessageRole.ASSISTANT
            )
            assert reply.message_status == schemas.MessageStatus.INCOMPLETE
