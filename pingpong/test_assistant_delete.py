import pytest
from sqlalchemy import func, select

from pingpong import models

pytestmark = pytest.mark.asyncio


async def test_assistant_delete_removes_mcp_server_tool_associations(db):
    assistant_id = 12001

    async with db.async_session() as session:
        assistant = models.Assistant(
            id=assistant_id,
            name="Assistant Delete Test",
            assistant_id="asst-delete-test",
            model="gpt-4o-mini",
        )
        mcp_tool = await models.MCPServerTool.create(
            session,
            data={
                "display_name": "Assistant Delete Tool",
                "server_url": "https://example.com/mcp",
            },
        )
        session.add(assistant)
        await session.flush()
        mcp_tool_id = mcp_tool.id
        await models.Assistant.synchronize_assistant_mcp_server_tools(
            session, assistant.id, [mcp_tool.id]
        )
        await session.commit()

    async with db.async_session() as session:
        await models.Assistant.delete(session, assistant_id)
        await session.commit()

    async with db.async_session() as session:
        association_count = await session.scalar(
            select(func.count())
            .select_from(models.mcp_server_tool_assistant_association)
            .where(
                models.mcp_server_tool_assistant_association.c.assistant_id
                == assistant_id
            )
        )
        deleted_assistant = await models.Assistant.get_by_id(session, assistant_id)
        preserved_tool = await session.get(models.MCPServerTool, mcp_tool_id)

    assert association_count == 0
    assert deleted_assistant is None
    assert preserved_tool is not None
