"""Tests for Panopto integration."""

import pytest
from unittest.mock import AsyncMock, patch
from datetime import datetime

import pytz


# --- SRT Parser Tests ---


def test_parse_srt():
    from pingpong.panopto import parse_srt

    srt = """1
00:00:00,000 --> 00:00:05,500
Welcome to today's lecture.

2
00:00:05,500 --> 00:00:12,000
We'll be covering price elasticity.

3
00:05:01,000 --> 00:05:08,000
So when we talk about elasticity, we mean
the responsiveness of quantity demanded.
"""
    segments = parse_srt(srt)
    assert len(segments) == 3
    assert segments[0].text == "Welcome to today's lecture."
    assert segments[0].start_seconds == 0.0
    assert segments[2].start_seconds == pytest.approx(301.0)
    assert "responsiveness" in segments[2].text


def test_segments_to_transcript():
    from pingpong.panopto import parse_srt, segments_to_transcript

    srt = """1
00:00:00,000 --> 00:00:05,500
Hello world.

2
00:05:01,000 --> 00:05:08,000
Five minutes in.

3
00:10:15,000 --> 00:10:22,000
Ten minutes in.
"""
    segments = parse_srt(srt)
    transcript = segments_to_transcript(segments, timestamp_interval_seconds=300)
    assert "[0:00]" in transcript
    assert "[5:00]" in transcript
    assert "[10:00]" in transcript
    assert "Hello world." in transcript
    assert "Five minutes in." in transcript


def test_segments_to_transcript_truncation():
    from pingpong.panopto import parse_srt, segments_to_transcript

    srt = """1
00:00:00,000 --> 00:00:05,000
A long segment of text that goes on and on.
"""
    segments = parse_srt(srt)
    transcript = segments_to_transcript(segments, max_chars=20)
    assert "[...transcript truncated]" in transcript


def test_parse_srt_empty():
    from pingpong.panopto import parse_srt

    assert parse_srt("") == []
    assert parse_srt("just some text\nwithout SRT format") == []


# --- State Token Tests ---


def test_encode_decode_panopto_state():
    from pingpong.panopto import encode_panopto_state, decode_panopto_state

    # Temporarily add a panopto config
    from pingpong.config import config, PanoptoSettings

    config.panopto.instances.append(
        PanoptoSettings(
            tenant="test",
            tenant_friendly_name="Test",
            base_url="https://test.panopto.com",
            client_id="test-id",
            client_secret="test-secret",
        )
    )
    try:

        def now():
            return datetime(2024, 6, 1, 0, 0, 0, tzinfo=pytz.utc)

        state = encode_panopto_state(1, 42, "test", nowfn=now)
        decoded = decode_panopto_state(state, nowfn=now)
        assert decoded["class_id"] == 1
        assert decoded["user_id"] == 42
        assert decoded["panopto_tenant"] == "test"
    finally:
        config.panopto.instances.pop()


# --- Format Session Tests ---


def test_format_panopto_session():
    from pingpong.panopto import format_panopto_session

    session = {
        "Id": "abc-123",
        "Name": "Lecture 1",
        "Description": "First lecture",
        "StartTime": "2024-10-14",
        "Duration": 3600.0,
        "Urls": {
            "CaptionDownloadUrl": "https://example.com/srt",
            "ViewerUrl": "https://example.com/viewer",
        },
        "FolderDetails": {"Id": "folder-1", "Name": "My Course"},
    }
    formatted = format_panopto_session(session)
    assert formatted["recording_id"] == "abc-123"
    assert formatted["title"] == "Lecture 1"
    assert formatted["folder"] == "My Course"
    assert formatted["has_captions"] is True
    assert formatted["viewer_url"] == "https://example.com/viewer"


def test_format_panopto_session_no_captions():
    from pingpong.panopto import format_panopto_session

    session = {
        "Id": "abc-456",
        "Name": "Lecture 2",
        "Urls": {},
        "FolderDetails": {},
    }
    formatted = format_panopto_session(session)
    assert formatted["has_captions"] is False


# --- MCP Tool Handler Tests ---


@pytest.mark.asyncio
async def test_handle_mcp_search_no_results():
    from pingpong.panopto import handle_mcp_tool_call

    with patch(
        "pingpong.panopto.search_panopto_sessions", new_callable=AsyncMock
    ) as mock:
        mock.return_value = []
        result = await handle_mcp_tool_call(
            "search_recordings",
            {"query": "nonexistent"},
            "fake-token",
            "test-tenant",
        )
        assert "No recordings found" in result


@pytest.mark.asyncio
async def test_handle_mcp_search_with_results():
    from pingpong.panopto import handle_mcp_tool_call

    mock_sessions = [
        {
            "Id": "abc",
            "Name": "Test Lecture",
            "StartTime": "2024-01-01",
            "Duration": 3600,
            "Urls": {"CaptionDownloadUrl": "https://x.com/srt"},
            "FolderDetails": {"Name": "Course"},
            "Description": None,
        }
    ]
    with patch(
        "pingpong.panopto.search_panopto_sessions", new_callable=AsyncMock
    ) as mock:
        mock.return_value = mock_sessions
        result = await handle_mcp_tool_call(
            "search_recordings",
            {"query": "test"},
            "fake-token",
            "test-tenant",
        )
        assert "Test Lecture" in result
        assert "abc" in result


@pytest.mark.asyncio
async def test_handle_mcp_unknown_tool():
    from pingpong.panopto import handle_mcp_tool_call

    result = await handle_mcp_tool_call("nonexistent_tool", {}, "token", "tenant")
    assert "Unknown tool" in result


# --- MCP Protocol Definition Tests ---


def test_mcp_tools_defined():
    from pingpong.panopto import MCP_TOOLS

    assert len(MCP_TOOLS) == 5
    names = [t["name"] for t in MCP_TOOLS]
    assert "search_recordings" in names
    assert "get_transcript" in names
    assert "get_recording_info" in names
    assert "list_folder_recordings" in names
    assert "list_folders" in names

    # Each tool should have required fields
    for tool in MCP_TOOLS:
        assert "name" in tool
        assert "description" in tool
        assert "inputSchema" in tool


# --- Model Method Tests (DB-backed) ---


async def _create_class_with_mcp_tools(db, *, num_internal=1, num_external=0):
    """Helper: create a class, institution, and MCP tools linked via association table.

    Returns (class_id, internal_tool_ids, external_tool_ids).
    """
    from pingpong.models import (
        Class,
        Institution,
        MCPServerTool,
        mcp_server_tool_class_association,
    )

    async with db.async_session() as session:
        inst = Institution(name="Test Inst")
        session.add(inst)
        await session.flush()

        cls = Class(name="Test Class", institution_id=inst.id)
        session.add(cls)
        await session.flush()
        class_id = cls.id

        internal_ids = []
        external_ids = []
        for i in range(num_internal):
            tool = MCPServerTool(
                display_name=f"Internal Tool {i}",
                server_url=f"https://internal-{i}.example.com",
                server_label=f"internal-tool-{i}-{class_id}",
                is_internal=True,
                enabled=True,
            )
            session.add(tool)
            await session.flush()
            internal_ids.append(tool.id)
            await session.execute(
                mcp_server_tool_class_association.insert().values(
                    mcp_server_tool_id=tool.id, class_id=class_id
                )
            )

        for i in range(num_external):
            tool = MCPServerTool(
                display_name=f"External Tool {i}",
                server_url=f"https://external-{i}.example.com",
                server_label=f"external-tool-{i}-{class_id}",
                is_internal=False,
                enabled=True,
            )
            session.add(tool)
            await session.flush()
            external_ids.append(tool.id)
            await session.execute(
                mcp_server_tool_class_association.insert().values(
                    mcp_server_tool_id=tool.id, class_id=class_id
                )
            )

        await session.commit()
    return class_id, internal_ids, external_ids


@pytest.mark.asyncio
async def test_get_class_mcp_server_tools(db):
    """get_class_mcp_server_tools returns enabled tools linked to the class."""
    from pingpong.models import Class

    class_id, internal_ids, external_ids = await _create_class_with_mcp_tools(
        db, num_internal=1, num_external=1
    )

    async with db.async_session() as session:
        tools = await Class.get_class_mcp_server_tools(session, class_id)

    assert len(tools) == 2
    returned_ids = {t.id for t in tools}
    assert returned_ids == set(internal_ids + external_ids)


@pytest.mark.asyncio
async def test_get_class_mcp_server_tools_excludes_disabled(db):
    """get_class_mcp_server_tools should not return disabled tools."""
    from pingpong.models import Class, MCPServerTool
    from sqlalchemy import update

    class_id, internal_ids, _ = await _create_class_with_mcp_tools(
        db, num_internal=2, num_external=0
    )

    # Disable one tool
    async with db.async_session() as session:
        await session.execute(
            update(MCPServerTool)
            .where(MCPServerTool.id == internal_ids[0])
            .values(enabled=False)
        )
        await session.commit()

    async with db.async_session() as session:
        tools = await Class.get_class_mcp_server_tools(session, class_id)

    assert len(tools) == 1
    assert tools[0].id == internal_ids[1]


@pytest.mark.asyncio
async def test_get_class_mcp_server_tools_empty(db):
    """get_class_mcp_server_tools returns empty list when no tools linked."""
    from pingpong.models import Class, Institution

    async with db.async_session() as session:
        inst = Institution(name="Empty Inst")
        session.add(inst)
        await session.flush()
        cls = Class(name="Empty Class", institution_id=inst.id)
        session.add(cls)
        await session.flush()
        class_id = cls.id
        await session.commit()

    async with db.async_session() as session:
        tools = await Class.get_class_mcp_server_tools(session, class_id)

    assert tools == []


@pytest.mark.asyncio
async def test_get_internal_mcp_tool_ids(db):
    """get_internal_mcp_tool_ids returns only internal tool IDs."""
    from pingpong.models import Class

    class_id, internal_ids, external_ids = await _create_class_with_mcp_tools(
        db, num_internal=2, num_external=1
    )

    async with db.async_session() as session:
        result_ids = await Class.get_internal_mcp_tool_ids(session, class_id)

    assert set(result_ids) == set(internal_ids)
    # External tool should not be included
    for eid in external_ids:
        assert eid not in result_ids


@pytest.mark.asyncio
async def test_get_internal_mcp_tool_ids_empty(db):
    """get_internal_mcp_tool_ids returns empty list when no internal tools."""
    from pingpong.models import Class

    class_id, _, _ = await _create_class_with_mcp_tools(
        db, num_internal=0, num_external=1
    )

    async with db.async_session() as session:
        result_ids = await Class.get_internal_mcp_tool_ids(session, class_id)

    assert result_ids == []


@pytest.mark.asyncio
async def test_link_panopto_folder(db):
    """link_panopto_folder sets folder fields and creates class association."""
    from pingpong.models import (
        Class,
        Institution,
        MCPServerTool,
        mcp_server_tool_class_association,
    )
    from pingpong import schemas
    from sqlalchemy import select

    async with db.async_session() as session:
        inst = Institution(name="Link Inst")
        session.add(inst)
        await session.flush()
        cls = Class(name="Link Class", institution_id=inst.id)
        session.add(cls)
        await session.flush()
        class_id = cls.id

        tool = MCPServerTool(
            display_name="Panopto MCP",
            server_url="https://panopto.example.com",
            server_label=f"panopto-{class_id}",
            is_internal=True,
            enabled=True,
        )
        session.add(tool)
        await session.flush()
        tool_id = tool.id
        await session.commit()

    async with db.async_session() as session:
        await Class.link_panopto_folder(
            session, class_id, "folder-abc", "My Folder", tool_id
        )
        await session.commit()

    # Verify class fields updated
    async with db.async_session() as session:
        stmt = select(Class).where(Class.id == class_id)
        result = await session.execute(stmt)
        cls = result.scalar_one()
        assert cls.panopto_folder_id == "folder-abc"
        assert cls.panopto_folder_name == "My Folder"
        assert cls.panopto_status == schemas.PanoptoStatus.LINKED

        # Verify association was created
        assoc_stmt = select(mcp_server_tool_class_association).where(
            mcp_server_tool_class_association.c.class_id == class_id,
            mcp_server_tool_class_association.c.mcp_server_tool_id == tool_id,
        )
        assoc_result = await session.execute(assoc_stmt)
        rows = assoc_result.all()
        assert len(rows) == 1


@pytest.mark.asyncio
async def test_link_panopto_folder_idempotent(db):
    """link_panopto_folder can be called twice without duplicate associations."""
    from pingpong.models import Class, Institution, MCPServerTool
    from sqlalchemy import select

    async with db.async_session() as session:
        inst = Institution(name="Idempotent Inst")
        session.add(inst)
        await session.flush()
        cls = Class(name="Idempotent Class", institution_id=inst.id)
        session.add(cls)
        await session.flush()
        class_id = cls.id

        tool = MCPServerTool(
            display_name="Panopto MCP 2",
            server_url="https://panopto2.example.com",
            server_label=f"panopto-idem-{class_id}",
            is_internal=True,
            enabled=True,
        )
        session.add(tool)
        await session.flush()
        tool_id = tool.id
        await session.commit()

    # Call twice
    async with db.async_session() as session:
        await Class.link_panopto_folder(
            session, class_id, "folder-1", "Folder 1", tool_id
        )
        await session.commit()

    async with db.async_session() as session:
        await Class.link_panopto_folder(
            session, class_id, "folder-2", "Folder 2", tool_id
        )
        await session.commit()

    # Should not raise and class should reflect latest folder
    async with db.async_session() as session:
        stmt = select(Class).where(Class.id == class_id)
        result = await session.execute(stmt)
        cls = result.scalar_one()
        assert cls.panopto_folder_id == "folder-2"
        assert cls.panopto_folder_name == "Folder 2"


@pytest.mark.asyncio
async def test_cleanup_panopto_mcp_tool(db):
    """cleanup_panopto_mcp_tool removes internal tools from associations and disables them."""
    from pingpong.models import (
        Assistant,
        Class,
        MCPServerTool,
        mcp_server_tool_assistant_association,
        mcp_server_tool_class_association,
    )
    from sqlalchemy import select

    class_id, internal_ids, external_ids = await _create_class_with_mcp_tools(
        db, num_internal=1, num_external=1
    )

    # Also associate the internal tool with an assistant
    async with db.async_session() as session:
        assistant = Assistant(name="Test Asst", class_id=class_id)
        session.add(assistant)
        await session.flush()
        await session.execute(
            mcp_server_tool_assistant_association.insert().values(
                mcp_server_tool_id=internal_ids[0], assistant_id=assistant.id
            )
        )
        await session.commit()

    # Run cleanup
    async with db.async_session() as session:
        await Class.cleanup_panopto_mcp_tool(session, class_id)
        await session.commit()

    async with db.async_session() as session:
        # Internal tool should be disabled
        stmt = select(MCPServerTool).where(MCPServerTool.id == internal_ids[0])
        result = await session.execute(stmt)
        internal_tool = result.scalar_one()
        assert internal_tool.enabled is False

        # Internal tool removed from class association
        assoc_stmt = select(mcp_server_tool_class_association).where(
            mcp_server_tool_class_association.c.mcp_server_tool_id == internal_ids[0]
        )
        assert len((await session.execute(assoc_stmt)).all()) == 0

        # Internal tool removed from assistant association
        asst_assoc_stmt = select(mcp_server_tool_assistant_association).where(
            mcp_server_tool_assistant_association.c.mcp_server_tool_id
            == internal_ids[0]
        )
        assert len((await session.execute(asst_assoc_stmt)).all()) == 0

        # External tool should still be enabled and in class association
        ext_stmt = select(MCPServerTool).where(MCPServerTool.id == external_ids[0])
        ext_result = await session.execute(ext_stmt)
        external_tool = ext_result.scalar_one()
        assert external_tool.enabled is True

        ext_assoc_stmt = select(mcp_server_tool_class_association).where(
            mcp_server_tool_class_association.c.mcp_server_tool_id == external_ids[0]
        )
        assert len((await session.execute(ext_assoc_stmt)).all()) == 1


@pytest.mark.asyncio
async def test_cleanup_panopto_mcp_tool_no_tools(db):
    """cleanup_panopto_mcp_tool does nothing when no internal tools exist."""
    from pingpong.models import Class, Institution

    async with db.async_session() as session:
        inst = Institution(name="No Tools Inst")
        session.add(inst)
        await session.flush()
        cls = Class(name="No Tools Class", institution_id=inst.id)
        session.add(cls)
        await session.flush()
        class_id = cls.id
        await session.commit()

    # Should not raise
    async with db.async_session() as session:
        await Class.cleanup_panopto_mcp_tool(session, class_id)
        await session.commit()


@pytest.mark.asyncio
async def test_disconnect_panopto(db):
    """disconnect_panopto cleans up MCP tools and clears all Panopto fields."""
    from pingpong.models import Class, MCPServerTool
    from pingpong import schemas
    from sqlalchemy import select

    class_id, internal_ids, _ = await _create_class_with_mcp_tools(
        db, num_internal=1, num_external=0
    )

    # Set Panopto fields on the class
    async with db.async_session() as session:
        from sqlalchemy import update

        await session.execute(
            update(Class)
            .where(Class.id == class_id)
            .values(
                panopto_status=schemas.PanoptoStatus.LINKED,
                panopto_tenant="test-tenant",
                panopto_user_id=1,
                panopto_folder_id="folder-123",
                panopto_folder_name="My Folder",
                panopto_access_token="token-abc",
                panopto_refresh_token="refresh-xyz",
                panopto_expires_in=3600,
            )
        )
        await session.commit()

    # Disconnect
    async with db.async_session() as session:
        await Class.disconnect_panopto(session, class_id)
        await session.commit()

    # Verify all fields cleared
    async with db.async_session() as session:
        stmt = select(Class).where(Class.id == class_id)
        result = await session.execute(stmt)
        cls = result.scalar_one()
        assert cls.panopto_status == schemas.PanoptoStatus.NONE
        assert cls.panopto_tenant is None
        assert cls.panopto_user_id is None
        assert cls.panopto_folder_id is None
        assert cls.panopto_folder_name is None
        assert cls.panopto_access_token is None
        assert cls.panopto_refresh_token is None
        assert cls.panopto_expires_in is None
        assert cls.panopto_token_added_at is None

        # Internal tool should be disabled
        tool_stmt = select(MCPServerTool).where(MCPServerTool.id == internal_ids[0])
        tool_result = await session.execute(tool_stmt)
        tool = tool_result.scalar_one()
        assert tool.enabled is False


@pytest.mark.asyncio
async def test_get_panopto_token_no_class(db):
    """get_panopto_token returns dict of Nones when class does not exist."""
    from pingpong.models import Class

    async with db.async_session() as session:
        result = await Class.get_panopto_token(session, 99999)

    assert result["user_id"] is None
    assert result["access_token"] is None
    assert result["refresh_token"] is None
    assert result["expires_in"] is None
    assert result["token_added_at"] is None
    assert result["now"] is None


@pytest.mark.asyncio
async def test_get_panopto_token_with_class(db):
    """get_panopto_token returns stored token info for an existing class."""
    from pingpong.models import Class, Institution
    from sqlalchemy import update

    async with db.async_session() as session:
        inst = Institution(name="Token Inst")
        session.add(inst)
        await session.flush()
        cls = Class(name="Token Class", institution_id=inst.id)
        session.add(cls)
        await session.flush()
        class_id = cls.id

        await session.execute(
            update(Class)
            .where(Class.id == class_id)
            .values(
                panopto_access_token="access-123",
                panopto_refresh_token="refresh-456",
                panopto_expires_in=7200,
            )
        )
        await session.commit()

    async with db.async_session() as session:
        result = await Class.get_panopto_token(session, class_id)

    assert result["access_token"] == "access-123"
    assert result["refresh_token"] == "refresh-456"
    assert result["expires_in"] == 7200
    assert result["now"] is not None


def test_mcp_server_tool_is_internal_column_exists():
    """MCPServerTool has is_internal column with a server_default."""
    from pingpong.models import MCPServerTool

    col = MCPServerTool.__table__.c.is_internal
    assert col is not None
    assert col.nullable is False
    assert col.server_default is not None


@pytest.mark.asyncio
async def test_mcp_server_tool_explicit_is_internal(db):
    """MCPServerTool.is_internal can be explicitly set to True or False."""
    from pingpong.models import MCPServerTool
    from sqlalchemy import select

    async with db.async_session() as session:
        internal = MCPServerTool(
            display_name="Internal",
            server_url="https://internal.example.com",
            server_label="explicit-internal",
            is_internal=True,
        )
        external = MCPServerTool(
            display_name="External",
            server_url="https://external.example.com",
            server_label="explicit-external",
            is_internal=False,
        )
        session.add_all([internal, external])
        await session.commit()
        internal_id = internal.id
        external_id = external.id

    async with db.async_session() as session:
        stmt = select(MCPServerTool).where(MCPServerTool.id == internal_id)
        result = await session.execute(stmt)
        assert result.scalar_one().is_internal is True

        stmt = select(MCPServerTool).where(MCPServerTool.id == external_id)
        result = await session.execute(stmt)
        assert result.scalar_one().is_internal is False
