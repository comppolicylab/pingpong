from __future__ import annotations

import importlib
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import func, select

from pingpong import models, schemas
from pingpong.testutil import with_authz, with_user

pytestmark = pytest.mark.asyncio


async def test_thread_delete_removes_mcp_server_tool_associations(db):
    thread_id = 1101

    async with db.async_session() as session:
        user = models.User(
            id=1100,
            email="thread-delete@test.dev",
            state=schemas.UserState.VERIFIED,
        )
        class_ = models.Class(id=1102, name="Thread Delete Class", api_key="sk-test")
        assistant = models.Assistant(
            id=1103,
            name="Thread Delete Assistant",
            class_id=class_.id,
            assistant_id="asst-thread-delete",
            model="gpt-4o-mini",
            creator_id=user.id,
        )
        thread = models.Thread(
            id=thread_id,
            thread_id="thread-delete-1101",
            class_id=class_.id,
            assistant_id=assistant.id,
            version=3,
            tools_available="",
            private=False,
        )
        mcp_tool = await models.MCPServerTool.create(
            session,
            data={
                "display_name": "Thread Delete Tool",
                "server_url": "https://example.com/mcp",
            },
        )

        session.add_all([user, class_, assistant, thread])
        await session.flush()
        await models.Thread.add_mcp_server_tools(session, thread.id, [mcp_tool.id])
        await session.commit()

    async with db.async_session() as session:
        pre_delete_assoc_count = await session.scalar(
            select(func.count())
            .select_from(models.mcp_server_tool_thread_association)
            .where(models.mcp_server_tool_thread_association.c.thread_id == thread_id)
        )

    assert pre_delete_assoc_count == 1

    async with db.async_session() as session:
        thread = await models.Thread.get_by_id(session, thread_id)
        assert thread is not None
        await thread.delete(session)
        await session.commit()

    async with db.async_session() as session:
        assoc_count = await session.scalar(
            select(func.count())
            .select_from(models.mcp_server_tool_thread_association)
            .where(models.mcp_server_tool_thread_association.c.thread_id == thread_id)
        )
        deleted_thread = await models.Thread.get_by_id(session, thread_id)

    assert assoc_count == 0
    assert deleted_thread is None


async def test_thread_delete_removes_mcp_server_tool_run_associations(db):
    thread_id = 2101

    async with db.async_session() as session:
        user = models.User(
            id=2100,
            email="thread-delete-run@test.dev",
            state=schemas.UserState.VERIFIED,
        )
        class_ = models.Class(
            id=2102, name="Thread Delete Run Class", api_key="sk-test"
        )
        assistant = models.Assistant(
            id=2103,
            name="Thread Delete Run Assistant",
            class_id=class_.id,
            assistant_id="asst-thread-delete-run",
            model="gpt-4o-mini",
            creator_id=user.id,
        )
        thread = models.Thread(
            id=thread_id,
            thread_id="thread-delete-run-2101",
            class_id=class_.id,
            assistant_id=assistant.id,
            version=3,
            tools_available="",
            private=False,
        )
        mcp_tool = await models.MCPServerTool.create(
            session,
            data={
                "display_name": "Thread Delete Run Tool",
                "server_url": "https://example.com/mcp/run",
            },
        )

        session.add_all([user, class_, assistant, thread])
        await session.flush()

        run = models.Run(
            run_id="run-thread-delete-2101",
            status=schemas.RunStatus.COMPLETED,
            thread_id=thread.id,
            assistant_id=assistant.id,
            creator_id=user.id,
        )
        session.add(run)
        await session.flush()
        run_pk = run.id

        await models.Run.add_mcp_server_tools(session, run_pk, [mcp_tool.id])
        await session.commit()

    async with db.async_session() as session:
        pre_delete_run_assoc_count = await session.scalar(
            select(func.count())
            .select_from(models.mcp_server_tool_run_association)
            .where(models.mcp_server_tool_run_association.c.run_id == run_pk)
        )

    assert pre_delete_run_assoc_count == 1

    async with db.async_session() as session:
        thread = await models.Thread.get_by_id(session, thread_id)
        assert thread is not None
        await thread.delete(session)
        await session.commit()

    async with db.async_session() as session:
        run_assoc_count = await session.scalar(
            select(func.count())
            .select_from(models.mcp_server_tool_run_association)
            .where(models.mcp_server_tool_run_association.c.run_id == run_pk)
        )
        deleted_thread = await models.Thread.get_by_id(session, thread_id)

    assert run_assoc_count == 0
    assert deleted_thread is None


@with_user(3100)
@with_authz(grants=[("user:3100", "can_delete", "thread:3101")])
async def test_protected_thread_cannot_be_deleted_by_participant(
    api, db, valid_user_token
):
    async with db.async_session() as session:
        session.add(
            models.Class(id=3102, name="Recorded Thread Class", api_key="sk-test")
        )
        session.add(
            models.Thread(
                id=3101,
                thread_id="recorded-thread-3101",
                class_id=3102,
                version=3,
                private=True,
                display_user_info=True,
                prevent_user_thread_deletion=True,
            )
        )
        await session.commit()

    response = api.delete(
        "/api/v1/class/3102/thread/3101",
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )

    assert response.status_code == 403, response.text
    assert response.json() == {
        "detail": "Recorded conversations cannot be deleted by participants."
    }

    async with db.async_session() as session:
        assert await models.Thread.get_by_id(session, 3101) is not None


@with_user(3200)
@with_authz(
    grants=[
        ("user:3200", "can_delete", "thread:3201"),
        ("user:3200", "can_manage_threads", "class:3202"),
    ]
)
async def test_protected_thread_can_be_deleted_by_supervisor(api, db, valid_user_token):
    async with db.async_session() as session:
        session.add(
            models.Class(id=3202, name="Recorded Thread Class", api_key="sk-test")
        )
        session.add(
            models.Thread(
                id=3201,
                thread_id="recorded-thread-3201",
                class_id=3202,
                version=3,
                private=True,
                display_user_info=True,
                prevent_user_thread_deletion=True,
            )
        )
        await session.commit()

    response = api.delete(
        "/api/v1/class/3202/thread/3201",
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )

    assert response.status_code == 200, response.text

    async with db.async_session() as session:
        assert await models.Thread.get_by_id(session, 3201) is None


@with_user(3300)
@with_authz(grants=[("user:3300", "can_delete", "thread:3301")])
async def test_recorded_thread_can_be_deleted_when_protection_is_off(
    api, db, valid_user_token
):
    async with db.async_session() as session:
        session.add(
            models.Class(id=3302, name="Recorded Thread Class", api_key="sk-test")
        )
        session.add(
            models.Thread(
                id=3301,
                thread_id="recorded-thread-3301",
                class_id=3302,
                version=3,
                private=True,
                display_user_info=True,
            )
        )
        await session.commit()

    response = api.delete(
        "/api/v1/class/3302/thread/3301",
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )

    assert response.status_code == 200, response.text

    async with db.async_session() as session:
        assert await models.Thread.get_by_id(session, 3301) is None


@with_user(3400)
@with_authz(grants=[("user:3400", "can_delete", "thread:3401")])
async def test_protection_flag_is_ignored_without_recorded_user_information(
    api, db, valid_user_token
):
    async with db.async_session() as session:
        session.add(
            models.Class(id=3402, name="Unrecorded Thread Class", api_key="sk-test")
        )
        session.add(
            models.Thread(
                id=3401,
                thread_id="unrecorded-thread-3401",
                class_id=3402,
                version=3,
                private=True,
                display_user_info=False,
                prevent_user_thread_deletion=True,
            )
        )
        await session.commit()

    response = api.delete(
        "/api/v1/class/3402/thread/3401",
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )

    assert response.status_code == 200, response.text

    async with db.async_session() as session:
        assert await models.Thread.get_by_id(session, 3401) is None


@with_user(3450)
@with_authz(grants=[("user:3450", "can_delete", "thread:3451")])
async def test_delete_missing_thread_returns_not_found(
    api, db, valid_user_token, monkeypatch
):
    server_module = importlib.import_module("pingpong.server")
    monkeypatch.setattr(
        server_module,
        "get_openai_client_for_class",
        AsyncMock(return_value=SimpleNamespace()),
    )

    async with db.async_session() as session:
        session.add(
            models.Class(
                id=3452,
                name="Missing Thread Class",
                api_key="sk-test",
            )
        )
        await session.commit()

    response = api.delete(
        "/api/v1/class/3452/thread/3451",
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )

    assert response.status_code == 404, response.text
    assert response.json() == {"detail": "Thread not found"}


@with_user(3470)
@with_authz(grants=[("user:3470", "can_delete", "class:3472")])
async def test_private_class_with_protected_thread_can_be_deleted(
    api, db, valid_user_token, monkeypatch
):
    server_module = importlib.import_module("pingpong.server")
    monkeypatch.setattr(
        server_module,
        "get_openai_client_for_class",
        AsyncMock(return_value=SimpleNamespace()),
    )

    async with db.async_session() as session:
        class_ = models.Class(
            id=3472,
            name="Private Recorded Thread Class",
            api_key="sk-test",
            private=True,
        )
        thread = models.Thread(
            id=3471,
            thread_id=None,
            class_id=class_.id,
            version=3,
            private=True,
            display_user_info=True,
            prevent_user_thread_deletion=True,
        )
        session.add_all([class_, thread])
        await session.commit()

    response = api.delete(
        "/api/v1/class/3472",
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )

    assert response.status_code == 200, response.text
    assert response.json() == {"status": "ok"}

    async with db.async_session() as session:
        assert await models.Thread.get_by_id(session, 3471) is None
        assert await models.Class.get_by_id(session, 3472) is None


@with_user(3500)
@with_authz(grants=[("user:3500", "can_create_thread", "class:3502")])
async def test_chat_thread_copies_deletion_protection_from_assistant(
    api, db, valid_user_token
):
    async with db.async_session() as session:
        class_ = models.Class(
            id=3502,
            name="Protected Chat Class",
            api_key="sk-test",
            private=False,
        )
        assistant = models.Assistant(
            id=3503,
            name="Protected Chat Assistant",
            version=3,
            instructions="You are helpful.",
            interaction_mode=schemas.InteractionMode.CHAT,
            description="Chat assistant",
            tools="[]",
            model="gpt-4o-mini",
            class_id=class_.id,
            creator_id=3500,
            use_latex=False,
            use_image_descriptions=False,
            assistant_should_message_first=False,
            should_record_user_information=True,
            prevent_user_thread_deletion=True,
        )
        session.add_all([class_, assistant])
        await session.commit()

    response = api.post(
        "/api/v1/class/3502/thread",
        json={"assistant_id": 3503, "message": "Hello"},
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )

    assert response.status_code == 200, response.text
    thread_id = response.json()["thread"]["id"]

    async with db.async_session() as session:
        thread = await models.Thread.get_by_id(session, thread_id)
        assert thread is not None
        assert thread.display_user_info is True
        assert thread.prevent_user_thread_deletion is True
