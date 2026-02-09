from __future__ import annotations

from typing import TYPE_CHECKING

import openai
from openai.resources.realtime.realtime import AsyncRealtimeConnection
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.requests import Request
from starlette.websockets import WebSocket
from typing_extensions import NotRequired, TypeAlias, TypedDict

from pingpong.authz.base import AuthzClient
from pingpong.now import NowFn
import pingpong.schemas as schemas

if TYPE_CHECKING:
    import pingpong.models as models


OpenAIClientType: TypeAlias = openai.AsyncClient | openai.AsyncAzureOpenAI


class AppState(TypedDict, total=False):
    now: NowFn


class BaseConnectionState(TypedDict):
    db: AsyncSession
    authz: AuthzClient
    session: schemas.SessionState
    auth_user: str | None
    is_anonymous: bool
    anonymous_share_token_auth: str | None
    anonymous_session_token_auth: str | None
    anonymous_session: schemas.SessionState
    anonymous_share_token: str | None
    anonymous_session_token: str | None
    anonymous_session_id: int | None
    anonymous_link_id: int | None
    permissions: dict[str, bool]


class RequestState(BaseConnectionState):
    pass


class WebSocketState(BaseConnectionState):
    openai_client: NotRequired[OpenAIClientType]
    thread: NotRequired[models.Thread]
    assistant: NotRequired[models.Assistant]
    conversation_instructions: NotRequired[str]
    realtime_connection: NotRequired[AsyncRealtimeConnection]
    voice_mode_run_id: NotRequired[int]


if TYPE_CHECKING:
    StateRequest: TypeAlias = Request[RequestState]
    StateWebSocket: TypeAlias = WebSocket[WebSocketState]
else:
    StateRequest = Request
    StateWebSocket = WebSocket
