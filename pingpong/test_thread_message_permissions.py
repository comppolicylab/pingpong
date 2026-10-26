import importlib
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from sqlalchemy import func, select

from pingpong import models, schemas
from pingpong.testutil import with_authz, with_user

server = importlib.import_module("pingpong.server")


@with_user(123)
@with_authz(grants=[])
@pytest.mark.parametrize("principal", ["user", "anonymous", "hybrid"])
@pytest.mark.parametrize("version", [2, 3])
@pytest.mark.parametrize(
    ("endpoint", "run_status"),
    [
        ("", schemas.RunStatus.COMPLETED),
        ("/run", schemas.RunStatus.COMPLETED),
        ("/run", schemas.RunStatus.PENDING),
    ],
)
@pytest.mark.parametrize("permission", ["allowed", "assistant_denied", "thread_denied"])
async def test_sending_requires_thread_and_selected_assistant_permission(
    api,
    db,
    config,
    valid_user_token,
    monkeypatch,
    principal,
    version,
    endpoint,
    run_status,
    permission,
):
    async with db.async_session() as session:
        session.add(models.Class(id=1, name="Class", api_key="test-key"))
        session.add_all(
            models.Assistant(
                id=assistant_id,
                name=f"Assistant {assistant_id}",
                class_id=1,
                version=version,
                model="gpt-4o-mini",
                assistant_id=f"asst-{assistant_id}",
                instructions="Be helpful.",
            )
            for assistant_id in (1, 2)
        )
        await session.flush()
        link = await models.AnonymousLink.create(
            session, share_token="share", assistant_id=2
        )
        anonymous_user = await models.User.create_anonymous_user(
            session, anonymous_link_id=link.id
        )
        await models.AnonymousSession.create(
            session, "session", user_id=anonymous_user.id
        )
        session.add(
            models.Thread(
                id=20,
                name="Conversation",
                thread_id="thread-provider",
                class_id=1,
                assistant_id=2,
                version=version,
                tools_available="[]",
                instructions="Existing instructions",
                user_message_ct=0,
            )
        )
        session.add(
            models.Run(
                id=30,
                thread_id=20,
                assistant_id=2,
                creator_id=123,
                status=run_status,
                instructions="Existing instructions",
            )
        )
        await session.commit()

    thread_subject = "user:123" if principal == "user" else "anonymous_user:session"
    assistant_subject = (
        "anonymous_link:share" if principal == "anonymous" else "user:123"
    )
    granted_assistant_id = 1 if permission == "assistant_denied" else 2
    grants = [
        (assistant_subject, "can_interact_with", f"assistant:{granted_assistant_id}")
    ]
    if permission != "thread_denied":
        grants.append((thread_subject, "can_participate", "thread:20"))
    async with config.authz.driver.get_client() as client:
        await client.write_safe(grant=grants)

    def stream_response(*args, **kwargs):
        async def stream():
            yield b"event: done\ndata: [DONE]\n\n"

        return stream()

    run_response = Mock(side_effect=stream_response)
    run_thread = Mock(side_effect=stream_response)
    list_provider_runs = AsyncMock(
        return_value=SimpleNamespace(data=[SimpleNamespace(status="completed")])
    )
    provider = SimpleNamespace(
        beta=SimpleNamespace(
            threads=SimpleNamespace(runs=SimpleNamespace(list=list_provider_runs))
        )
    )
    monkeypatch.setitem(
        server.v1.dependency_overrides,
        server.get_openai_client_for_class,
        lambda: provider,
    )
    monkeypatch.setattr(server, "run_response", run_response)
    monkeypatch.setattr(server, "run_thread", run_thread)
    headers = {}
    if principal != "anonymous":
        headers["Authorization"] = f"Bearer {valid_user_token}"
    if principal != "user":
        headers["X-Anonymous-Thread-Session"] = "session"

    response = api.post(
        f"/api/v1/class/1/thread/20{endpoint}",
        json={"message": "Hello"} if endpoint == "" else {},
        headers=headers,
    )

    if permission == "allowed":
        assert response.status_code == 200, response.text
        (run_response if version == 3 else run_thread).assert_called_once()
    else:
        assert response.status_code == 403, response.text
        assert response.json() == {
            "detail": (
                "You do not have permission to interact with this assistant."
                if permission == "assistant_denied"
                else "Missing required role"
            )
        }
        run_response.assert_not_called()
        run_thread.assert_not_called()
        list_provider_runs.assert_not_awaited()
        async with db.async_session() as session:
            assert (
                await session.scalar(select(func.count()).select_from(models.Run)) == 1
            )
            assert (
                await session.scalar(select(func.count()).select_from(models.Message))
                == 0
            )
            thread = await models.Thread.get_by_id(session, 20)
            assert thread.instructions == "Existing instructions"
            assert thread.user_message_ct == 0
            run = await session.get(models.Run, 30)
            assert run.status == run_status


@with_user(123)
@with_authz(grants=[("user:123", "can_participate", "thread:999")])
async def test_create_run_rejects_missing_thread(api, db, valid_user_token):
    async with db.async_session() as session:
        session.add(models.Class(id=1, name="Class", api_key="test-key"))
        await session.commit()

    response = api.post(
        "/api/v1/class/1/thread/999/run",
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )

    assert response.status_code == 404
    assert response.json() == {
        "detail": "We could not find the thread or assistant you specified. Please try again."
    }
