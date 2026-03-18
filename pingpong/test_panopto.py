"""Tests for Panopto integration."""

import json
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from datetime import datetime, timedelta

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
        now = lambda: datetime(2024, 6, 1, 0, 0, 0, tzinfo=pytz.utc)
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

    with patch("pingpong.panopto.search_panopto_sessions", new_callable=AsyncMock) as mock:
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
    with patch("pingpong.panopto.search_panopto_sessions", new_callable=AsyncMock) as mock:
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

    result = await handle_mcp_tool_call(
        "nonexistent_tool", {}, "token", "tenant"
    )
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
