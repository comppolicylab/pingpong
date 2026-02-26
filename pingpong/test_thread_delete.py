from __future__ import annotations

import pytest
from sqlalchemy import func, select

from pingpong import models, schemas

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
