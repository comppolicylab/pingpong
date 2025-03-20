import json
from fastapi import Response, WebSocket, WebSocketDisconnect

from pingpong import schemas
from pingpong.websocket import (
    ws_auth_middleware,
    ws_db_middleware,
    ws_parse_session_token,
)


async def check_realtime_permissions(ws: WebSocket, thread_id: str):
    if ws.state.session.status != schemas.SessionStatus.VALID:
        await ws.send_denial_response(Response(status_code=403))
        return
    if not await ws.state.authz.test(
        f"user:{ws.state.session.user.id}", "can_participate", f"thread:{thread_id}"
    ):
        await ws.send_denial_response(Response(status_code=403))


@ws_auth_middleware
@ws_db_middleware
@ws_parse_session_token
async def realtime_websocket(ws: WebSocket, class_id: str, thread_id: str):
    await check_realtime_permissions(ws, thread_id)
    await ws.accept()
    try:
        while True:
            message = await ws.receive()
            ws._raise_on_disconnect(message)
            if "text" in message:
                try:
                    data = json.loads(message["text"])
                    print("Received event:", data)
                except json.JSONDecodeError as e:
                    print("Error decoding JSON:", e)
            elif "bytes" in message:
                audio_chunk = message["bytes"]
                print(f"Received audio chunk of {len(audio_chunk)} bytes")
    except WebSocketDisconnect:
        print("Client disconnected.")
