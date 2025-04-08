import asyncio
import base64
import json
import logging
from typing import Any, cast
from fastapi import WebSocket, WebSocketDisconnect
from openai import OpenAIError
from sqlalchemy import func


from pingpong import schemas
from pingpong.ai import (
    OpenAIClientType,
    format_instructions,
    get_openai_client_by_class_id,
)
from pingpong.models import Thread
from pingpong.websocket import (
    ws_auth_middleware,
    ws_db_middleware,
    ws_parse_session_token,
)

browser_connection_logger = logging.getLogger("realtime_browser")
openai_connection_logger = logging.getLogger("realtime_openai")


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
    thread = await Thread.get_by_id_with_assistant(
        browser_connection.state.db,
        int(thread_id),
    )
    assistant = thread.assistant
    conversation_instructions = format_instructions(
        assistant.instructions,
        interaction_mode=schemas.InteractionMode.LIVE_AUDIO,
    )
    async with openai_client.beta.realtime.connect(
        model=assistant.model,
    ) as openai_connection:
        await openai_connection.session.update(
            session={
                "input_audio_transcription": {
                    "model": "gpt-4o-transcribe",
                },
                "temperature": assistant.temperature,
                "tool_choice": "none",
                "voice": "alloy",
                "turn_detection": {"type": "server_vad"},
                "instructions": conversation_instructions,
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
                            browser_connection_logger.warning(
                                f"Received unexpected message: {data}"
                            )
                        except json.JSONDecodeError as e:
                            browser_connection_logger.error(
                                f"Failed to decode unexpected message JSON: {e}"
                            )
                    elif "bytes" in message:
                        audio_chunk = message["bytes"]
                        await openai_connection.input_audio_buffer.append(
                            audio=base64.b64encode(cast(Any, audio_chunk)).decode(
                                "utf-8"
                            )
                        )
                        await asyncio.sleep(0)

            except WebSocketDisconnect:
                browser_connection_logger.debug(
                    "Browser closed the websocket connection."
                )
            except asyncio.CancelledError:
                browser_connection_logger.debug(
                    "Received task cancellation signal. Closing the browser websocket."
                )
                await browser_connection.close()
                raise
            finally:
                browser_connection_logger.debug(
                    "Cleanup for browser connection handler."
                )

        async def handle_openai_events():
            try:
                async for event in openai_connection:
                    match event.type:
                        case "response.audio_transcript.done":
                            await openai_client.beta.threads.messages.create(
                                thread_id=thread.thread_id,
                                role="assistant",
                                content=event.transcript,
                                metadata={
                                    "item_id": event.item_id,
                                },
                            )
                        case "session.created":
                            openai_connection_logger.debug(
                                f"Session successfully created: {event.session}"
                            )
                        case "session.updated":
                            openai_connection_logger.debug(
                                f"Session successfully updated: {event.session}"
                            )
                            await browser_connection.send_json(
                                {
                                    "type": "session.updated",
                                    "message": "Connected to OpenAI.",
                                }
                            )
                        case "session.error":
                            openai_connection_logger.exception(
                                f"Session error: {event.error}"
                            )
                        case "session.ended":
                            openai_connection_logger.debug(
                                f"Session ended: {event.session}"
                            )
                            await browser_connection.send_json(
                                {
                                    "type": "session.ended",
                                    "message": "Session ended.",
                                }
                            )
                        case "conversation.item.input_audio_transcription.completed":
                            try:
                                await openai_client.beta.threads.messages.create(
                                    thread_id=thread.thread_id,
                                    role="user",
                                    content=event.transcript,
                                    metadata={
                                        "user_id": str(
                                            browser_connection.state.session.user.id
                                        ),
                                        "item_id": event.item_id,
                                    },
                                )
                            except OpenAIError as e:
                                openai_connection_logger.exception(
                                    f"Failed to send message to OpenAI: {e}, {event}"
                                )
                            try:
                                thread.user_message_ct += 1
                                thread.last_activity = func.now()

                                browser_connection.state.db.add(thread)
                                await browser_connection.state.db.flush()
                                await browser_connection.state.db.refresh(thread)
                            except Exception as e:
                                openai_connection_logger.exception(
                                    f"Failed to update thread in database: {e}"
                                )
                        case "response.audio.delta":
                            delta_audio_b64 = event.delta
                            await browser_connection.send_json(
                                {
                                    "type": "response.audio.delta",
                                    "audio": delta_audio_b64,
                                    "item_id": event.item_id,
                                }
                            )
                        case "input_audio_buffer.speech_started":
                            await browser_connection.send_json(
                                {
                                    "type": "input_audio_buffer.speech_started",
                                    "message": "User speech detected.",
                                }
                            )
                        case (
                            "conversation.created"
                            | "conversation.item.created"
                            | "conversation.item.input_audio_transcription.delta"
                            | "conversation.item.input_audio_transcription.failed"
                            | "conversation.item.truncated"
                            | "conversation.item.deleted"
                            | "input_audio_buffer.committed"
                            | "input_audio_buffer.cleared"
                            | "input_audio_buffer.speech_stopped"
                            | "response.created"
                            | "response.done"
                            | "response.output_item.added"
                            | "response.output_item.done"
                            | "response.content_part.added"
                            | "response.content_part.done"
                            | "response.text.delta"
                            | "response.text.done"
                            | "response.audio_transcript.delta"
                            | "response.audio.done"
                            | "response.function_call_arguments.delta"
                            | "response.function_call_arguments.done"
                            | "transcription_session.updated"
                            | "rate_limits.updated"
                        ):
                            continue
                        case _:
                            openai_connection_logger.warning(
                                f"Ignoring unknown event type... {event.type}"
                            )

            except asyncio.CancelledError:
                openai_connection_logger.debug(
                    "Received task cancellation signal. Closing the OpenAI connection."
                )
                raise
            except Exception as e:
                openai_connection_logger.exception(f"Error handling OpenAI event: {e}")
            finally:
                openai_connection_logger.debug("Cleanup for OpenAI connection handler.")

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
