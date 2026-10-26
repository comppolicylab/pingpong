import importlib
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from fastapi import HTTPException
import pytest
from redis.exceptions import ConnectionError
from sqlalchemy import func, select

from pingpong import ai, model_catalog as catalog, models, schemas, websocket
from pingpong.test_ai_run_usage import make_handler
from pingpong.test_model_catalog import (
    install_memory_cache,
    provider_client,
    provider_response,
)
from pingpong.test_server_audio_websocket import DummyWebSocket, realtime_assistant
from pingpong.testutil import with_authz, with_user
from websockets.exceptions import ConnectionClosedError
from websockets.frames import Close

server = importlib.import_module("pingpong.server")


def _authorized_request(*, state):
    return SimpleNamespace(
        path_params={},
        state={
            "is_anonymous": False,
            "auth_user": "user:123",
            "anonymous_share_token_auth": "anonymous_link:test",
            "anonymous_session_token_auth": None,
            "authz": SimpleNamespace(
                check=AsyncMock(return_value=[True]),
                test=AsyncMock(return_value=True),
            ),
            **state,
        },
    )


@pytest.fixture
def memory_cache(config, monkeypatch):
    return install_memory_cache(config, monkeypatch)


@pytest.mark.parametrize("mode", list(schemas.InteractionMode))
async def test_unavailable_id_credential_does_not_create_thread_or_anonymous_session(
    db, memory_cache, monkeypatch, mode
):
    client = provider_client()
    monkeypatch.setattr(
        server, "get_openai_client_from_api_key", Mock(return_value=client)
    )
    async with db.async_session() as session:
        key = models.APIKey(id=17, api_key="synthetic", provider="openai")
        group = models.Class(id=1, name="Group", api_key_id=17)
        assistant = models.Assistant(
            id=1,
            name="Assistant",
            class_id=1,
            model="missing",
            interaction_mode=mode,
            version=3,
        )
        session.add_all([key, group, assistant])
        await session.commit()
    async with db.async_session() as session:
        request = _authorized_request(
            state={
                "db": session,
                "is_anonymous": True,
                "session": SimpleNamespace(
                    user=None, status=schemas.SessionStatus.ANONYMOUS
                ),
            }
        )
        with pytest.raises(HTTPException) as raised:
            if mode == schemas.InteractionMode.CHAT:
                await server.create_thread(
                    "1",
                    schemas.CreateThread(assistant_id=1, message="hello"),
                    request,
                    client,
                )
            elif mode == schemas.InteractionMode.VOICE:
                await server.create_audio_thread(
                    "1", schemas.CreateAudioThread(assistant_id=1), request, client
                )
            else:
                await server.create_lecture_thread(
                    "1", schemas.CreateLectureThread(assistant_id=1), request
                )
        assert raised.value.status_code == 400
        assert raised.value.detail == catalog.MODEL_NOT_AVAILABLE_MESSAGE
        assert (
            await session.scalar(select(func.count()).select_from(models.Thread)) == 0
        )
        assert (
            await session.scalar(
                select(func.count()).select_from(models.AnonymousSession)
            )
            == 0
        )
        assert await session.scalar(select(func.count()).select_from(models.Run)) == 0
    client.models.list.assert_awaited_once()


@pytest.mark.parametrize("operation", ["send_message", "create_run"])
async def test_existing_thread_is_checked_before_writing_or_generating(
    db, memory_cache, operation
):
    client = provider_client()
    async with db.async_session() as session:
        group = models.Class(id=1, name="Group")
        assistant = models.Assistant(
            id=1, name="Assistant", class_id=1, model="missing", version=3
        )
        thread = models.Thread(
            id=1, class_id=1, assistant_id=1, version=3, tools_available="[]"
        )
        session.add_all([group, assistant, thread])
        await session.commit()
    async with db.async_session() as session:
        request = _authorized_request(
            state={
                "db": session,
                "is_anonymous": False,
                "auth_user": "user:123",
            }
        )
        with pytest.raises(HTTPException) as raised:
            if operation == "send_message":
                await server.send_message(
                    "1",
                    "1",
                    schemas.NewThreadMessage(message="hello"),
                    request,
                    await server.get_bound_message_context(request, "1", "1"),
                    client,
                )
            else:
                await server.create_run(
                    "1",
                    "1",
                    request,
                    await server.get_bound_run_context(request, "1", "1"),
                    client,
                )
        assert raised.value.status_code == 400
        assert (
            await session.scalar(select(func.count()).select_from(models.Message)) == 0
        )
        assert await session.scalar(select(func.count()).select_from(models.Run)) == 0


async def test_voice_reconnect_checks_availability_before_connecting(memory_cache):
    client = provider_client()
    client.realtime = SimpleNamespace(
        connect=Mock(side_effect=AssertionError("Must not connect"))
    )
    browser = DummyWebSocket()
    browser.state["openai_client"] = client
    browser.state["assistant"] = realtime_assistant()
    browser.state["thread"] = SimpleNamespace(
        id=1, class_id=1, assistant_id=1, tools_available="[]"
    )
    browser.state["conversation_instructions"] = "Be helpful."
    browser.state["session"] = SimpleNamespace(user=SimpleNamespace(id=123))
    browser.state["after_db_rollback"] = []
    handler = AsyncMock()
    with pytest.raises(HTTPException) as raised:
        await websocket.ws_with_realtime_connection(handler)(browser, "1", "1")
    assert raised.value.status_code == 400
    assert (
        browser.sent_json[0]["error"]["message"] == catalog.MODEL_NOT_AVAILABLE_MESSAGE
    )
    assert browser.closed
    handler.assert_not_awaited()
    client.realtime.connect.assert_not_called()
    assert not browser.state["after_db_rollback"]


async def test_voice_model_not_found_close_invalidates_inventory(memory_cache):
    client = provider_client("gpt-4o-realtime-preview")
    await catalog.get_model_catalog(client)
    error = ConnectionClosedError(
        Close(4013, "invalid_request_error.model_not_found"), None
    )
    client.realtime = SimpleNamespace(connect=Mock(side_effect=error))
    browser = DummyWebSocket()
    browser.state["openai_client"] = client
    browser.state["assistant"] = realtime_assistant()
    browser.state["thread"] = SimpleNamespace(
        id=1, class_id=1, assistant_id=1, tools_available="[]"
    )
    browser.state["conversation_instructions"] = "Be helpful."
    browser.state["session"] = SimpleNamespace(user=SimpleNamespace(id=123))
    browser.state["after_db_rollback"] = []
    with pytest.raises(ConnectionClosedError):
        await websocket.ws_with_realtime_connection(AsyncMock())(browser, "1", "1")
    client.models.list.return_value = provider_response("replacement")
    assert (await catalog.get_model_catalog(client)).models[0].id == "replacement"
    assert client.models.list.await_count == 2


@pytest.mark.parametrize("cache_unavailable", [False, True])
async def test_voice_uses_provider_rejection_when_cache_cannot_be_used(
    config, monkeypatch, cache_unavailable
):
    monkeypatch.setattr(config.model_cache, "redis", None)
    monkeypatch.setattr(config.model_cache, "build_revision", "test-build")
    if cache_unavailable:

        @asynccontextmanager
        async def unavailable():
            raise ConnectionError("offline")
            yield

        monkeypatch.setattr(catalog, "catalog_redis", unavailable)
    client = provider_client()
    error = ConnectionClosedError(
        Close(4013, "invalid_request_error.model_not_found"), None
    )
    client.realtime = SimpleNamespace(connect=Mock(side_effect=error))
    browser = DummyWebSocket()
    browser.state["openai_client"] = client
    browser.state["assistant"] = realtime_assistant()
    browser.state["thread"] = SimpleNamespace(
        id=1, class_id=1, assistant_id=1, tools_available="[]"
    )
    browser.state["conversation_instructions"] = "Be helpful."
    browser.state["session"] = SimpleNamespace(user=SimpleNamespace(id=123))
    browser.state["after_db_rollback"] = []
    with pytest.raises(ConnectionClosedError):
        await websocket.ws_with_realtime_connection(AsyncMock())(browser, "1", "1")
    client.models.list.assert_not_awaited()
    client.realtime.connect.assert_called_once()
    assert (
        browser.sent_json[0]["error"]["message"] == catalog.MODEL_NOT_AVAILABLE_MESSAGE
    )


@pytest.mark.parametrize("pending_model", ["retired", None])
async def test_pending_run_checks_its_execution_model(
    db, memory_cache, monkeypatch, pending_model
):
    client = provider_client("replacement")
    stream = Mock()
    monkeypatch.setattr(server, "run_response", stream)
    async with db.async_session() as session:
        group = models.Class(id=1, name="Group")
        assistant = models.Assistant(
            id=1,
            name="Assistant",
            class_id=1,
            model="replacement" if pending_model is not None else "retired",
            version=3,
        )
        thread = models.Thread(
            id=1, class_id=1, assistant_id=1, version=3, tools_available="[]"
        )
        run = models.Run(
            thread_id=1, model=pending_model, status=schemas.RunStatus.PENDING
        )
        session.add_all([group, assistant, thread, run])
        await session.commit()
    async with db.async_session() as session:
        request = _authorized_request(state={"db": session})
        with pytest.raises(HTTPException) as raised:
            await server.create_run(
                "1",
                "1",
                request,
                await server.get_bound_run_context(request, "1", "1"),
                client,
            )
        assert raised.value.status_code == 400
    stream.assert_not_called()
    async with db.async_session() as session:
        saved = await session.scalar(select(models.Run))
        assert saved.status == schemas.RunStatus.PENDING
        assert saved.model == pending_model
    client.models.list.assert_awaited_once()


@with_user(123)
@pytest.mark.parametrize(
    "run_case", ["new", "snapshot", "missing-model", "newer-pending-run"]
)
async def test_run_checks_only_the_model_it_will_execute(
    db, user, memory_cache, monkeypatch, run_case
):
    pending = run_case != "new"
    client = provider_client("available")
    events = []
    snapshots = []
    load_thread = server.get_thread_for_class

    async def fetch_catalog(client):
        events.append("fetch")
        assert "lock" not in events
        result = await catalog.get_runtime_model_catalog(client)
        snapshots.append(result)
        if run_case == "newer-pending-run":
            # Simulate another request publishing a pending run during the fetch.
            async with db.async_session() as session:
                session.add(
                    models.Run(
                        id=2,
                        thread_id=1,
                        model="available",
                        status=schemas.RunStatus.PENDING,
                    )
                )
                await session.commit()
        events.append("fetched")
        return result

    async def lock_thread(*args, **kwargs):
        if kwargs.get("for_update"):
            assert events == ["fetch", "fetched"]
            thread = await load_thread(*args, **kwargs)
            events.append("lock")
            return thread
        return await load_thread(*args, **kwargs)

    def validate(client, model_id, snapshot):
        assert events == ["fetch", "fetched", "lock"]
        events.append("validate")
        catalog.validate_model_available(client, model_id, snapshot)

    check = Mock(side_effect=validate)
    stream = Mock(return_value=iter(()))
    monkeypatch.setattr(server, "get_runtime_model_catalog", fetch_catalog)
    monkeypatch.setattr(server, "get_thread_for_class", lock_thread)
    monkeypatch.setattr(server, "validate_model_available", check)
    monkeypatch.setattr(server, "run_response", stream)
    async with db.async_session() as session:
        session.add_all(
            [
                models.Class(id=1, name="Group"),
                models.Assistant(
                    id=1,
                    name="Assistant",
                    class_id=1,
                    version=3,
                    model="retired" if run_case == "snapshot" else "available",
                ),
                models.Thread(
                    id=1,
                    class_id=1,
                    assistant_id=1,
                    version=3,
                    tools_available="[]",
                    instructions="Be helpful.",
                ),
                models.Run(
                    id=1,
                    thread_id=1,
                    model=(
                        None
                        if run_case == "missing-model"
                        else "available" if run_case == "snapshot" else "retired"
                    ),
                    created=datetime(2020, 1, 1, tzinfo=timezone.utc),
                    status=schemas.RunStatus.PENDING
                    if pending
                    else schemas.RunStatus.COMPLETED,
                ),
            ]
        )
        await session.commit()
    async with db.async_session() as session:
        request = _authorized_request(
            state={
                "db": session,
                "session": SimpleNamespace(user=user),
                "auth_user": "user:123",
                "anonymous_session_token_auth": None,
                "anonymous_share_token_auth": None,
                "anonymous_session_id": None,
                "anonymous_link_id": None,
                "response_safety_identifier": "test-user",
            }
        )
        response = await server.create_run(
            "1",
            "1",
            request,
            await server.get_bound_run_context(request, "1", "1"),
            client,
        )
        assert response.status_code == 200
        check.assert_called_once_with(client, "available", snapshots[0])
        assert events == ["fetch", "fetched", "lock", "validate"]
        stream.assert_called_once()
        run = stream.call_args.kwargs["run"]
        assert run.model == "available"
        assert run.status == schemas.RunStatus.QUEUED
        expected_runs = 2 if run_case in {"new", "newer-pending-run"} else 1
        assert run.id == expected_runs
        assert (
            await session.scalar(select(func.count()).select_from(models.Run))
            == expected_runs
        )
        run_id = run.id
        await session.commit()
    async with db.async_session() as session:
        saved = await session.get(models.Run, run_id)
        assert saved.model == "available"
        assert saved.status == schemas.RunStatus.QUEUED
    client.models.list.assert_awaited_once()


@pytest.mark.parametrize("cache_state", ["disabled", "missing-build", "enabled"])
async def test_lecture_resolves_credentials_once_and_only_when_cache_is_usable(
    config, memory_cache, monkeypatch, cache_state
):
    if cache_state == "disabled":
        monkeypatch.setattr(config.model_cache, "redis", None)
    elif cache_state == "missing-build":
        monkeypatch.setattr(config.model_cache, "build_revision", None)
        monkeypatch.delenv("SENTRY_RELEASE", raising=False)
    client = provider_client("available")
    factory = Mock(return_value=client)
    monkeypatch.setattr(ai, "get_openai_client", factory)
    lookup = AsyncMock(
        return_value=SimpleNamespace(
            api_key_obj=SimpleNamespace(
                id=17,
                api_key="synthetic",
                provider="openai",
                api_version=None,
            )
        )
    )
    monkeypatch.setattr(models.Class, "get_api_key", lookup)
    monkeypatch.setattr(
        models.Assistant,
        "get_by_id_with_lecture_video",
        AsyncMock(
            return_value=SimpleNamespace(
                id=1,
                class_id=1,
                model="available",
                lecture_video=None,
                interaction_mode=schemas.InteractionMode.LECTURE_VIDEO,
            )
        ),
    )
    request = _authorized_request(
        state={
            "db": object(),
            "is_anonymous": False,
            "session": SimpleNamespace(
                user=None, status=schemas.SessionStatus.ANONYMOUS
            ),
        }
    )
    with pytest.raises(HTTPException) as raised:
        await server.create_lecture_thread(
            "1", schemas.CreateLectureThread(assistant_id=1), request
        )
    assert raised.value.status_code == 400
    assert "does not have a lecture video" in raised.value.detail
    expected_calls = 1 if cache_state == "enabled" else 0
    assert (
        lookup.await_count
        == factory.call_count
        == client.models.list.await_count
        == expected_calls
    )


@pytest.mark.parametrize("event_type", ["error", "response.failed"])
async def test_response_events_invalidate_the_actual_credential_catalog(
    db, memory_cache, event_type
):
    client = provider_client("selected")
    await catalog.get_model_catalog(client)
    async with db.async_session() as session:
        run = models.Run(status=schemas.RunStatus.IN_PROGRESS)
        session.add(run)
        await session.flush()
        run_id = run.id
        await session.commit()
    handler = make_handler(run_id)
    handler.openai_cli = client
    error = SimpleNamespace(code="model_not_found", message="Synthetic failure")
    if event_type == "error":
        await handler.on_response_error(error)
    else:
        await handler.on_response_completed(
            SimpleNamespace(
                response=SimpleNamespace(
                    status="failed",
                    error=error,
                    usage=None,
                    moderation=None,
                    incomplete_details=None,
                )
            )
        )
    client.models.list.return_value = provider_response("new")
    fresh = await catalog.get_model_catalog(client)
    assert fresh.models[0].id == "new"
    assert client.models.list.await_count == 2


@with_user(123)
@pytest.mark.parametrize(
    "authz",
    [
        {"grants": [("user:123", "member", "class:1")]},
        {"grants": [("user:123", "admin", "class:1")]},
        {"grants": [("user:123", "admin", "institution:1")]},
    ],
    indirect=True,
)
async def test_only_root_admins_can_reset(api, memory_cache, valid_user_token):
    response = api.post(
        "/api/v1/admin/model-cache/reset",
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )
    assert response.status_code == 403
    assert not memory_cache.values


@with_user(123)
@with_authz(grants=[("user:123", "admin", "root:0")])
async def test_admin_reset_invalidates_all_credentials_and_build_versions(
    api, config, memory_cache, monkeypatch, valid_user_token
):
    inventories = []
    for build in ("build-a", "build-b"):
        monkeypatch.setattr(config.model_cache, "build_revision", build)
        for key_id in (17, 18):
            client = provider_client("old", key_id=key_id)
            await catalog.get_model_catalog(client)
            inventories.append((build, client))
            client.models.list.return_value = provider_response("new")
    old_keys = set(memory_cache.values)
    memory_cache.values["pingpong:login-exchange:untouched"] = "login-grant"
    # Reset is independent of the build handling the admin request.
    monkeypatch.setattr(config.model_cache, "build_revision", None)
    monkeypatch.delenv("SENTRY_RELEASE", raising=False)
    response = api.post(
        "/api/v1/admin/model-cache/reset",
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )
    assert response.status_code == 200, response.text
    assert response.json() == {"status": "ok"}
    assert old_keys <= memory_cache.values.keys()
    assert memory_cache.values["pingpong:login-exchange:untouched"] == "login-grant"
    for build, client in inventories:
        client.models.list.assert_awaited_once()
        monkeypatch.setattr(config.model_cache, "build_revision", build)
        fresh = await catalog.get_model_catalog(client)
        assert fresh.models[0].id == "new"
        assert client.models.list.await_count == 2


@with_user(123)
@with_authz(grants=[("user:123", "admin", "root:0")])
async def test_admin_reset_reports_cache_outage(
    api, memory_cache, monkeypatch, valid_user_token
):
    monkeypatch.setattr(
        memory_cache, "set", AsyncMock(side_effect=ConnectionError("offline"))
    )
    response = api.post(
        "/api/v1/admin/model-cache/reset",
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )
    assert response.status_code == 503


@with_user(123)
@with_authz(grants=[("user:123", "admin", "root:0")])
async def test_admin_reset_reports_unconfigured_cache(
    api, config, monkeypatch, valid_user_token
):
    monkeypatch.setattr(config.model_cache, "redis", None)
    response = api.post(
        "/api/v1/admin/model-cache/reset",
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )
    assert response.status_code == 503
    assert response.json()["detail"] == "Model caching is not configured."
