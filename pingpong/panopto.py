"""Panopto integration: OAuth2 flow, API client, SRT parsing, and MCP endpoint handler."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from datetime import timedelta

import aiohttp
from sqlalchemy.ext.asyncio import AsyncSession

from pingpong.auth import decode_auth_token, encode_auth_token
from pingpong.config import PanoptoSettings, config
from pingpong.models import Class
from pingpong.now import NowFn, utcnow
from pingpong.schemas import PanoptoStatus

logger = logging.getLogger(__name__)


class PanoptoException(Exception):
    def __init__(self, detail: str = "", code: int | None = None):
        self.code = code
        self.detail = detail


class PanoptoTokenExpiredException(PanoptoException):
    pass


# --- Configuration ---


def get_panopto_config(tenant: str) -> PanoptoSettings:
    """Get the Panopto configuration for the given tenant."""
    for instance in config.panopto.instances:
        if instance.tenant == tenant:
            return instance
    raise PanoptoException(f"No Panopto configuration found for tenant '{tenant}'", code=404)


def get_panopto_tenants() -> list[dict]:
    """Return available Panopto tenants."""
    return [
        {"tenant": inst.tenant, "tenant_friendly_name": inst.tenant_friendly_name}
        for inst in config.panopto.instances
    ]


# --- OAuth2 State Token ---


def encode_panopto_state(
    class_id: int, user_id: int, tenant: str, nowfn: NowFn = utcnow
) -> str:
    """Encode OAuth2 state token for CSRF protection."""
    panopto_config = get_panopto_config(tenant)
    return encode_auth_token(
        sub=json.dumps(
            {"class_id": class_id, "user_id": user_id, "panopto_tenant": tenant}
        ),
        expiry=panopto_config.auth_token_expiry,
        nowfn=nowfn,
    )


def decode_panopto_state(state: str, nowfn: NowFn = utcnow) -> dict:
    """Decode and validate OAuth2 state token. Returns {class_id, user_id, panopto_tenant}."""
    auth_token = decode_auth_token(state, nowfn=nowfn)
    return json.loads(auth_token.sub)


def get_panopto_auth_link(class_id: int, user_id: int, tenant: str) -> str:
    """Generate the OAuth2 authorization redirect URL."""
    panopto_config = get_panopto_config(tenant)
    state = encode_panopto_state(class_id, user_id, tenant)
    redirect_uri = config.url("/api/v1/auth/panopto/callback")
    return panopto_config.auth_link(state, redirect_uri)


# --- Token Management ---


async def exchange_panopto_code(
    code: str, tenant: str
) -> dict:
    """Exchange OAuth2 authorization code for tokens."""
    panopto_config = get_panopto_config(tenant)
    redirect_uri = config.url("/api/v1/auth/panopto/callback")

    async with aiohttp.ClientSession() as session:
        async with session.post(
            panopto_config.token_url(),
            data={
                "grant_type": "authorization_code",
                "client_id": panopto_config.client_id,
                "client_secret": panopto_config.client_secret,
                "code": code,
                "redirect_uri": redirect_uri,
            },
        ) as resp:
            if resp.status != 200:
                text = await resp.text()
                raise PanoptoException(
                    f"Token exchange failed: {resp.status} {text}", code=resp.status
                )
            data = await resp.json()
            return {
                "access_token": data["access_token"],
                "refresh_token": data.get("refresh_token"),
                "expires_in": int(data.get("expires_in", 3600)),
            }


async def refresh_panopto_token(
    refresh_token: str, tenant: str
) -> dict:
    """Refresh Panopto access token."""
    panopto_config = get_panopto_config(tenant)

    async with aiohttp.ClientSession() as session:
        async with session.post(
            panopto_config.token_url(),
            data={
                "grant_type": "refresh_token",
                "client_id": panopto_config.client_id,
                "client_secret": panopto_config.client_secret,
                "refresh_token": refresh_token,
            },
        ) as resp:
            if resp.status != 200:
                raise PanoptoTokenExpiredException(
                    "Panopto refresh token expired", code=401
                )
            data = await resp.json()
            return {
                "access_token": data["access_token"],
                "refresh_token": data.get("refresh_token"),
                "expires_in": int(data.get("expires_in", 3600)),
            }


async def get_panopto_access_token(
    db: AsyncSession, class_id: int, buffer: int = 60
) -> tuple[str, str]:
    """Get a valid Panopto access token for a class, refreshing if needed.

    Returns:
        (access_token, tenant)
    """
    token_info = await Class.get_panopto_token(db, class_id)

    if not token_info["access_token"] or not token_info["token_added_at"]:
        raise PanoptoException("No Panopto token for this class", code=404)

    # Look up tenant for this class
    from sqlalchemy import select

    stmt = select(Class.panopto_tenant).where(Class.id == class_id)
    result = await db.execute(stmt)
    tenant = result.scalar_one_or_none()
    if not tenant:
        raise PanoptoException("No Panopto tenant for this class", code=404)

    tok = token_info["access_token"]

    # Check if token needs refresh
    if token_info["now"] > token_info["token_added_at"] + timedelta(
        seconds=(token_info["expires_in"] or 3600) - buffer
    ):
        if not token_info["refresh_token"]:
            await Class.mark_panopto_error(db, class_id)
            raise PanoptoTokenExpiredException(
                "Panopto token expired and no refresh token available", code=401
            )
        try:
            new_tokens = await refresh_panopto_token(
                token_info["refresh_token"], tenant
            )
            await Class.update_panopto_token(
                db,
                class_id,
                new_tokens["access_token"],
                new_tokens["expires_in"],
                refresh=True,
            )
            tok = new_tokens["access_token"]
        except PanoptoTokenExpiredException:
            await Class.mark_panopto_error(db, class_id)
            raise

    return tok, tenant


# --- Panopto API Requests ---


async def _panopto_api_get(
    access_token: str, tenant: str, path: str, params: dict | None = None
) -> dict:
    """Make an authenticated GET request to the Panopto API."""
    panopto_config = get_panopto_config(tenant)
    url = panopto_config.api_url(path)

    async with aiohttp.ClientSession() as session:
        async with session.get(
            url,
            params=params,
            headers={"Authorization": f"Bearer {access_token}"},
        ) as resp:
            if resp.status != 200:
                text = await resp.text()
                raise PanoptoException(
                    f"Panopto API error: {resp.status} {text}", code=resp.status
                )
            return await resp.json()


async def _panopto_legacy_login(access_token: str, tenant: str) -> dict[str, str]:
    """Get session cookies via legacy login (required for SRT download)."""
    panopto_config = get_panopto_config(tenant)
    url = panopto_config.api_url("/auth/legacyLogin")

    async with aiohttp.ClientSession() as session:
        async with session.get(
            url,
            headers={"Authorization": f"Bearer {access_token}"},
            allow_redirects=True,
        ) as resp:
            resp.raise_for_status()
            return {k: v.value for k, v in resp.cookies.items()}


async def search_panopto_sessions(
    access_token: str,
    tenant: str,
    query: str,
    folder_id: str | None = None,
) -> list[dict]:
    """Search Panopto sessions by keyword (searches captions, titles, descriptions)."""
    params = {
        "searchQuery": query,
        "pageNumber": 0,
        "sortField": "Relevance",
        "sortOrder": "Desc",
    }
    if folder_id:
        path = f"/folders/{folder_id}/sessions/search"
    else:
        path = "/sessions/search"

    result = await _panopto_api_get(access_token, tenant, path, params)
    return result.get("Results", [])


async def get_panopto_session(
    access_token: str, tenant: str, session_id: str
) -> dict:
    """Get a Panopto session by ID."""
    return await _panopto_api_get(access_token, tenant, f"/sessions/{session_id}")


async def list_panopto_folder_sessions(
    access_token: str, tenant: str, folder_id: str, page: int = 0
) -> list[dict]:
    """List sessions in a Panopto folder."""
    result = await _panopto_api_get(
        access_token,
        tenant,
        f"/folders/{folder_id}/sessions",
        params={
            "pageNumber": page,
            "sortField": "CreatedDate",
            "sortOrder": "Desc",
        },
    )
    return result.get("Results", [])


async def search_panopto_folders(
    access_token: str, tenant: str, query: str
) -> list[dict]:
    """Search Panopto folders by keyword."""
    result = await _panopto_api_get(
        access_token,
        tenant,
        "/folders/search",
        params={"searchQuery": query, "pageNumber": 0},
    )
    return result.get("Results", [])


async def download_panopto_captions(
    access_token: str, tenant: str, session_id: str
) -> str | None:
    """Download SRT captions for a session. Returns SRT text or None."""
    session_data = await get_panopto_session(access_token, tenant, session_id)
    urls = session_data.get("Urls") or {}
    caption_url = urls.get("CaptionDownloadUrl")
    if not caption_url:
        return None

    panopto_config = get_panopto_config(tenant)
    if caption_url.startswith("/"):
        caption_url = f"{panopto_config.base_url}{caption_url}"

    # SRT download requires session cookies
    cookies = await _panopto_legacy_login(access_token, tenant)

    async with aiohttp.ClientSession(cookies=cookies) as session:
        async with session.get(caption_url, allow_redirects=True) as resp:
            resp.raise_for_status()
            text = await resp.text()
            return text if text else None


# --- SRT Parsing ---


@dataclass
class CaptionSegment:
    index: int
    start_seconds: float
    end_seconds: float
    text: str


def _parse_srt_timestamp(ts: str) -> float:
    """Parse SRT timestamp (HH:MM:SS,mmm) to seconds."""
    match = re.match(r"(\d+):(\d+):(\d+)[,.](\d+)", ts.strip())
    if not match:
        raise ValueError(f"Invalid SRT timestamp: {ts}")
    h, m, s, ms = match.groups()
    return int(h) * 3600 + int(m) * 60 + int(s) + int(ms) / 1000


def _format_timestamp(seconds: float) -> str:
    """Format seconds as H:MM:SS or M:SS."""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    if h > 0:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


def parse_srt(srt_content: str) -> list[CaptionSegment]:
    """Parse SRT content into a list of CaptionSegments."""
    segments: list[CaptionSegment] = []
    blocks = re.split(r"\n\s*\n", srt_content.strip())

    for block in blocks:
        lines = block.strip().split("\n")
        if len(lines) < 3:
            continue
        try:
            index = int(lines[0].strip())
        except ValueError:
            continue

        ts_match = re.match(r"(.+?)\s*-->\s*(.+?)(?:\s|$)", lines[1].strip())
        if not ts_match:
            continue

        start = _parse_srt_timestamp(ts_match.group(1))
        end = _parse_srt_timestamp(ts_match.group(2))
        text = " ".join(line.strip() for line in lines[2:] if line.strip())
        text = re.sub(r"<[^>]+>", "", text)

        if text:
            segments.append(CaptionSegment(index=index, start_seconds=start, end_seconds=end, text=text))

    return segments


def segments_to_transcript(
    segments: list[CaptionSegment],
    timestamp_interval_seconds: float = 300,
    max_chars: int | None = 50_000,
) -> str:
    """Convert caption segments to clean transcript with periodic timestamp markers."""
    if not segments:
        return "(No transcript available)"

    parts: list[str] = []
    next_marker_time = 0.0

    for seg in segments:
        while seg.start_seconds >= next_marker_time:
            if next_marker_time > 0 or seg.start_seconds == 0:
                parts.append(f"\n[{_format_timestamp(next_marker_time)}]\n")
            next_marker_time += timestamp_interval_seconds
        parts.append(seg.text)

    transcript = " ".join(parts)
    transcript = re.sub(r"\s*\n\s*\[", "\n\n[", transcript)
    transcript = re.sub(r"\]\s*\n\s*", "]\n", transcript)
    transcript = re.sub(r"  +", " ", transcript)
    transcript = transcript.strip()

    if max_chars and len(transcript) > max_chars:
        transcript = transcript[:max_chars] + "\n\n[...transcript truncated]"

    return transcript


# --- Session Formatting ---


def format_panopto_session(s: dict) -> dict:
    """Extract key fields from a Panopto session API response."""
    urls = s.get("Urls") or {}
    folder_details = s.get("FolderDetails") or {}
    return {
        "recording_id": s.get("Id"),
        "title": s.get("Name"),
        "description": s.get("Description") or "",
        "date": s.get("StartTime"),
        "duration_seconds": s.get("Duration"),
        "folder": folder_details.get("Name") or s.get("FolderName") or s.get("Folder"),
        "folder_id": folder_details.get("Id") or s.get("FolderId") or s.get("Folder"),
        "has_captions": bool(urls.get("CaptionDownloadUrl") or s.get("CaptionDownloadUrl")),
        "viewer_url": urls.get("ViewerUrl") or s.get("ViewerUrl"),
    }


# --- MCP Tool Handlers ---


async def handle_mcp_tool_call(
    tool_name: str,
    arguments: dict,
    access_token: str,
    tenant: str,
    class_folder_id: str | None = None,
) -> str:
    """Handle an MCP tool call and return the result as text."""

    if tool_name == "search_recordings":
        query = arguments.get("query", "")
        folder_id = arguments.get("folder_id") or class_folder_id
        sessions = await search_panopto_sessions(access_token, tenant, query, folder_id)
        if not sessions:
            return f"No recordings found matching '{query}'."

        items = []
        for s in sessions[:15]:
            r = format_panopto_session(s)
            item = (
                f"- **{r['title']}** ({r['date']})\n"
                f"  ID: `{r['recording_id']}`\n"
                f"  Duration: {r['duration_seconds']}s | Folder: {r['folder']} | "
                f"Captions: {'Yes' if r['has_captions'] else 'No'}"
            )
            if r["description"]:
                item += f"\n  Description: {r['description'][:200]}"
            items.append(item)
        return f"Found {len(items)} recording(s) matching '{query}':\n\n" + "\n".join(items)

    elif tool_name == "get_transcript":
        recording_id = arguments["recording_id"]
        session_data = await get_panopto_session(access_token, tenant, recording_id)
        title = session_data.get("Name", "Unknown")
        date = session_data.get("StartTime", "")

        srt_content = await download_panopto_captions(access_token, tenant, recording_id)
        if not srt_content:
            return f"No captions/transcript available for recording '{title}'."

        segments = parse_srt(srt_content)
        if not segments:
            return f"Captions file was empty or could not be parsed for recording '{title}'."

        transcript = segments_to_transcript(segments)
        return f"## Transcript: {title}\n**Date:** {date}\n\n{transcript}"

    elif tool_name == "get_recording_info":
        recording_id = arguments["recording_id"]
        session_data = await get_panopto_session(access_token, tenant, recording_id)
        return json.dumps(format_panopto_session(session_data), indent=2, default=str)

    elif tool_name == "list_folder_recordings":
        folder_id = arguments.get("folder_id") or class_folder_id
        if not folder_id:
            return "No folder_id provided and no folder linked to this class."
        page = int(arguments.get("page", 0))
        sessions = await list_panopto_folder_sessions(access_token, tenant, folder_id, page)
        if not sessions:
            return f"No recordings found in folder (page {page})."

        items = []
        for s in sessions:
            r = format_panopto_session(s)
            item = (
                f"- **{r['title']}** ({r['date']})\n"
                f"  ID: `{r['recording_id']}` | Duration: {r['duration_seconds']}s | "
                f"Captions: {'Yes' if r['has_captions'] else 'No'}"
            )
            items.append(item)
        return f"Recordings in folder (page {page}, showing {len(items)}):\n\n" + "\n".join(items)

    elif tool_name == "list_folders":
        query = arguments.get("query", "")
        if not query:
            return "Please provide a search query to find folders."
        folders = await search_panopto_folders(access_token, tenant, query)
        if not folders:
            return f"No folders found matching '{query}'."

        items = []
        for f in folders:
            item = f"- **{f.get('Name')}**\n  ID: `{f.get('Id')}`"
            desc = f.get("Description")
            if desc:
                item += f"\n  Description: {desc[:200]}"
            items.append(item)
        return f"Found {len(folders)} folder(s):\n\n" + "\n".join(items)

    else:
        return f"Unknown tool: {tool_name}"


# --- MCP Protocol Definitions ---

MCP_TOOLS = [
    {
        "name": "search_recordings",
        "description": "Search Panopto recordings by keyword. Searches within captions, titles, and descriptions.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search keywords (e.g., 'price elasticity', 'regression analysis').",
                },
                "folder_id": {
                    "type": "string",
                    "description": "Optional folder ID to search within. If omitted, searches the linked course folder.",
                },
            },
            "required": ["query"],
        },
    },
    {
        "name": "get_transcript",
        "description": "Get the full transcript of a Panopto recording with timestamp markers.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "recording_id": {
                    "type": "string",
                    "description": "The Panopto recording ID (from search_recordings results).",
                },
            },
            "required": ["recording_id"],
        },
    },
    {
        "name": "get_recording_info",
        "description": "Get metadata about a specific Panopto recording.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "recording_id": {
                    "type": "string",
                    "description": "The Panopto recording ID.",
                },
            },
            "required": ["recording_id"],
        },
    },
    {
        "name": "list_folder_recordings",
        "description": "List all recordings in a Panopto folder.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "folder_id": {
                    "type": "string",
                    "description": "The Panopto folder ID. If omitted, uses the linked course folder.",
                },
                "page": {
                    "type": "integer",
                    "description": "Page number for pagination (starts at 0).",
                },
            },
        },
    },
    {
        "name": "list_folders",
        "description": "Search for Panopto folders by keyword.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search keywords to find folders (e.g., 'API 209', 'economics').",
                },
            },
            "required": ["query"],
        },
    },
]

MCP_SERVER_INFO = {
    "name": "Panopto",
    "version": "1.0.0",
}
