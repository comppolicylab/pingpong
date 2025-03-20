from fastapi import WebSocket

from pingpong.websocket import (
    ws_auth_middleware,
    ws_db_middleware,
    ws_parse_session_token,
)


@ws_auth_middleware
@ws_db_middleware
@ws_parse_session_token
async def realtime_websocket(ws: WebSocket):
    print(ws.state.session)
