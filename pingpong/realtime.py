import asyncio
import base64
import json
from typing import Any, cast
from fastapi import WebSocket, WebSocketDisconnect


from pingpong import schemas
from pingpong.ai import OpenAIClientType, get_openai_client_by_class_id
from pingpong.websocket import (
    ws_auth_middleware,
    ws_db_middleware,
    ws_parse_session_token,
)


async def check_realtime_permissions(ws: WebSocket, thread_id: str):
    if ws.state.session.status != schemas.SessionStatus.VALID:
        raise ValueError("Your session token is invalid. Try logging in again.")
    if not await ws.state.authz.test(
        f"user:{ws.state.session.user.id}", "can_participate", f"thread:{thread_id}"
    ):
        raise ValueError("You are not allowed to participate in this thread.")


@ws_auth_middleware
@ws_db_middleware
@ws_parse_session_token
async def browser_realtime_websocket(
    browser_connection: WebSocket, class_id: str, thread_id: str
):
    await browser_connection.accept()
    try:
        await check_realtime_permissions(browser_connection, thread_id)
    except ValueError as e:
        await browser_connection.send_json(
            {
                "type": "error",
                "error": {
                    "type": "invalid_request_error",
                    "code": "invalid_permissions",
                    "message": str(e),
                },
            }
        )
        await browser_connection.close()
        return
    try:
        openai_client: OpenAIClientType = await get_openai_client_by_class_id(
            browser_connection.state.db, int(class_id)
        )
    except Exception:
        await browser_connection.send_json(
            {
                "type": "error",
                "error": {
                    "type": "invalid_request_error",
                    "code": "invalid_api_key",
                    "message": "We were unable to connect to OpenAI.",
                },
            }
        )
        await browser_connection.close()
        return
    async with openai_client.beta.realtime.connect(
        model="gpt-4o-realtime-preview",
        extra_query={
            "input_audio_transcription": {
                "language": "en",
                "model": "gpt-4o-transcribe",
            },
            "temperature": 0.8,
            "tool_choice": "none",
            "turn_direction": {"type": "semantic_vad"},
            "voice": "alloy",
        },
    ) as openai_connection:
        await browser_connection.send_json(
            {
                "type": "session.created",
                "message": "Connected to OpenAI.",
            }
        )
        async def handle_browser_messages():
            try:
                while True:
                    message = await browser_connection.receive()
                    browser_connection._raise_on_disconnect(message)
                    if "text" in message:
                        try:
                            data = json.loads(message["text"])
                            print("Received event:", data)
                        except json.JSONDecodeError as e:
                            print("Error decoding JSON:", e)
                    elif "bytes" in message:
                        audio_chunk = message["bytes"]
                        print(f"Received audio chunk of {len(audio_chunk)} bytes")

                        await openai_connection.input_audio_buffer.append(
                            audio=base64.b64encode(cast(Any, audio_chunk)).decode("utf-8")
                        )

            except WebSocketDisconnect:
                print("Client disconnected.")

        async def handle_openai_events():
            try:
                async for event in openai_connection:
                    print("🔁 Received OpenAI event:", event)
            except Exception as e:
                print("Error receiving from OpenAI:", e)

        await asyncio.gather(
            handle_browser_messages(),
            handle_openai_events(),
        )