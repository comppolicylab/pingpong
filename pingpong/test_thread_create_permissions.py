import importlib
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import func, select

from pingpong import models, schemas
from pingpong.testutil import with_authz, with_user

server = importlib.import_module("pingpong.server")


@with_user(123)
@with_authz(grants=[])
@pytest.mark.parametrize("principal", ["user", "share", "session"])
@pytest.mark.parametrize(
    ("endpoint", "mode", "version"),
    [
        ("", schemas.InteractionMode.CHAT, 2),
        ("", schemas.InteractionMode.CHAT, 3),
        ("/audio", schemas.InteractionMode.VOICE, 2),
        ("/audio", schemas.InteractionMode.VOICE, 3),
        ("/lecture", schemas.InteractionMode.LECTURE_VIDEO, 3),
        ("/lecture", schemas.InteractionMode.LECTURE_SLIDES, 3),
    ],
)
async def test_thread_creation_requires_selected_assistant_permission(
    api,
    db,
    config,
    authz,
    valid_user_token,
    monkeypatch,
    principal,
    endpoint,
    mode,
    version,
):
    async with db.async_session() as session:
        session.add(models.Class(id=1, name="Class", api_key="test-key"))
        session.add_all(
            [
                models.Assistant(
                    id=assistant_id,
                    name=f"Assistant {assistant_id}",
                    class_id=1,
                    version=version,
                    interaction_mode=mode,
                    instructions="Be helpful.",
                    model="gpt-4o-mini",
                    assistant_should_message_first=False,
                )
                for assistant_id in (1, 2)
            ]
        )
        await session.flush()
        link = await models.AnonymousLink.create(
            session, share_token="assistant-one-share", assistant_id=1
        )
        anonymous_user = await models.User.create_anonymous_user(
            session, anonymous_link_id=link.id
        )
        await models.AnonymousSession.create(
            session, "assistant-one-session", user_id=anonymous_user.id
        )
        await session.commit()

    subject = (
        "user:123" if principal == "user" else "anonymous_link:assistant-one-share"
    )
    async with config.authz.driver.get_client() as client:
        await client.write_safe(
            grant=[
                (subject, "can_create_thread", "class:1"),
                (subject, "can_interact_with", "assistant:1"),
            ]
        )

    headers = {
        "user": {"Authorization": f"Bearer {valid_user_token}"},
        "share": {"X-Anonymous-Link-Share": "assistant-one-share"},
        "session": {"X-Anonymous-Thread-Session": "assistant-one-session"},
    }[principal]
    create_thread = AsyncMock(wraps=models.Thread.create)
    create_session = AsyncMock(wraps=models.AnonymousSession.create)
    create_vector_store = AsyncMock()
    create_provider_thread = AsyncMock()
    provider = SimpleNamespace(
        beta=SimpleNamespace(threads=SimpleNamespace(create=create_provider_thread))
    )
    monkeypatch.setitem(
        server.v1.dependency_overrides,
        server.get_openai_client_for_class,
        lambda: provider,
    )
    monkeypatch.setattr(models.Thread, "create", create_thread)
    monkeypatch.setattr(models.AnonymousSession, "create", create_session)
    monkeypatch.setattr(server, "create_vector_store", create_vector_store)
    monkeypatch.setattr(
        server,
        "get_initial_thread_conversation_name",
        AsyncMock(return_value="Conversation"),
    )
    calls_before = await authz.get_all_calls()

    response = api.post(
        f"/api/v1/class/1/thread{endpoint}",
        json={"assistant_id": 2, "message": "Hello"},
        headers=headers,
    )

    assert response.status_code == 403
    assert response.json() == {"detail": "Missing required role"}
    create_thread.assert_not_awaited()
    create_session.assert_not_awaited()
    create_vector_store.assert_not_awaited()
    create_provider_thread.assert_not_awaited()
    assert await authz.get_all_calls() == calls_before
    async with db.async_session() as session:
        assert (
            await session.scalar(select(func.count()).select_from(models.Thread)) == 0
        )
        assert (
            await session.scalar(
                select(func.count()).select_from(models.AnonymousSession)
            )
            == 1
        )

    if version == 3 and mode in (
        schemas.InteractionMode.CHAT,
        schemas.InteractionMode.VOICE,
    ):
        async with config.authz.driver.get_client() as client:
            await client.write_safe(
                grant=[(subject, "can_interact_with", "assistant:2")]
            )

        allowed_response = api.post(
            f"/api/v1/class/1/thread{endpoint}",
            json={"assistant_id": 2, "message": "Hello"},
            headers=headers,
        )

        assert allowed_response.status_code == 200
        assert allowed_response.json()["thread"]["assistant_id"] == 2
        create_thread.assert_awaited_once()
        assert create_session.await_count == (0 if principal == "user" else 1)


@with_user(123)
@with_authz(grants=[("user:123", "can_interact_with", "assistant:1")])
@pytest.mark.parametrize("endpoint", ["", "/audio", "/lecture"])
async def test_assistant_permission_does_not_replace_class_permission(
    api, valid_user_token, endpoint
):
    response = api.post(
        f"/api/v1/class/1/thread{endpoint}",
        json={"assistant_id": 1, "message": "Hello"},
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )

    assert response.status_code == 403
    assert response.json() == {"detail": "Missing required role"}


@with_user(123)
@with_authz(grants=[("user:123", "can_create_thread", "class:1")])
@pytest.mark.parametrize("endpoint", ["", "/audio", "/lecture"])
@pytest.mark.parametrize("assistant_id", [1, 999])
async def test_thread_creation_preserves_missing_or_wrong_class_assistant_error(
    api, db, valid_user_token, endpoint, assistant_id
):
    async with db.async_session() as session:
        session.add_all(
            [
                models.Class(id=1, name="Class", api_key="test-key"),
                models.Class(id=2, name="Other Class", api_key="test-key"),
            ]
        )
        session.add(models.Assistant(id=1, name="Other Assistant", class_id=2))
        await session.commit()

    response = api.post(
        f"/api/v1/class/1/thread{endpoint}",
        json={"assistant_id": assistant_id, "message": "Hello"},
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )

    assert response.status_code == 404
    assert response.json() == {
        "detail": "Could not find the assistant you specified. Please try again."
    }
