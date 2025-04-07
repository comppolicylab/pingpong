import asyncio
import base64
import json
import logging
from typing import Any, cast
from fastapi import WebSocket, WebSocketDisconnect


from pingpong import schemas
from pingpong.ai import OpenAIClientType, get_openai_client_by_class_id
from pingpong.websocket import (
    ws_auth_middleware,
    ws_db_middleware,
    ws_parse_session_token,
)

logger = logging.getLogger(__name__)

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
            "temperature": 0.8,
            "tool_choice": "none",
            "voice": "alloy",
        },
    ) as openai_connection:
        await openai_connection.session.update(
            session={"input_audio_transcription": {"language": "en", "model": "gpt-4o-transcribe"}, "temperature": 0.8,
            "tool_choice": "none",
            "voice": "alloy"}
        )
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
                        await openai_connection.input_audio_buffer.append(
                            audio=base64.b64encode(cast(Any, audio_chunk)).decode("utf-8")
                        )
                        await asyncio.sleep(0)

            except WebSocketDisconnect:
                print("WebSocket disconnected.")
            except asyncio.CancelledError:
                print("❌ Browser message task cancelled.")
                await browser_connection.close()
                raise
            finally:
                print("🧹 Cleanup for browser message handler.")

        async def handle_openai_events():
            try:
                async for event in openai_connection:
                    if event.type == "response.content_part.done":
                        print("🔁 Received OpenAI event:", event)
                    elif event.type == "session.created":
                        print("Session created:", event)
                    elif event.type == "session.updated":
                        print("Session updated:", event)
                    elif event.type == "session.error":
                        print("Session error:", event)
                    elif event.type == "session.ended":
                        print("Session ended:", event)
                    elif event.type == "conversation.item.input_audio_transcription.completed":
                        print("Audio transcription completed:", event)
                    elif event.type == "response.audio.delta":
                        delta_audio_b64 = event.delta  # base64-encoded audio
                        await browser_connection.send_json({
                            "type": "audio",
                            "audio": delta_audio_b64,
                            "content_index": event.content_index
                        })
                    else:
                        print("Unknown event type:", event.type)

            except asyncio.CancelledError:
                print("❌ OpenAI event task cancelled.")
                raise
            except Exception as e:
                print("Error receiving from OpenAI:", e)
            finally:
                print("🧹 Cleanup for OpenAI event handler.")

        browser_task = asyncio.create_task(handle_browser_messages())
        openai_task = asyncio.create_task(handle_openai_events())

        _, pending = await asyncio.wait(
            [browser_task, openai_task],
            return_when=asyncio.FIRST_COMPLETED,
        )

        for task in pending:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass