import asyncio
import base64
import json
import logging
from typing import cast
from fastapi import WebSocket, WebSocketDisconnect
from openai import OpenAIError
from sqlalchemy import func

from openai.resources.beta.realtime.realtime import AsyncRealtimeConnection
from openai.types.beta.realtime import (
    ConversationItemInputAudioTranscriptionCompletedEvent,
    ResponseAudioTranscriptDoneEvent,
)


from pingpong.ai import (
    OpenAIClientType,
)
from pingpong.models import Thread
from pingpong.websocket import (
    ws_auth_middleware,
    ws_check_realtime_permissions,
    ws_db_middleware,
    ws_parse_session_token,
    ws_with_openai_client,
    ws_with_realtime_connection,
    ws_with_thread_assistant_prompt,
)

browser_connection_logger = logging.getLogger("realtime_browser")
openai_connection_logger = logging.getLogger("realtime_openai")


async def add_message_to_thread(
    openai_client: OpenAIClientType,
    browser_connection: WebSocket,
    thread: Thread,
    event: ConversationItemInputAudioTranscriptionCompletedEvent
    | ResponseAudioTranscriptDoneEvent,
    is_user_message: bool = False,
):
    try:
        metadata = {
            "item_id": event.item_id,
        }
        if is_user_message:
            metadata["user_id"] = str(browser_connection.state.session.user.id)

        await openai_client.beta.threads.messages.create(
            thread_id=thread.thread_id,
            role="user" if is_user_message else "assistant",
            content=event.transcript,
            metadata=metadata,
        )
    except OpenAIError as e:
        openai_connection_logger.exception(
            f"Failed to send message to OpenAI: {e}, {event}"
        )
        return

    if is_user_message:
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


async def handle_browser_messages(
    browser_connection: WebSocket, realtime_connection: AsyncRealtimeConnection
):
    try:
        while True:
            message = await browser_connection.receive()
            browser_connection._raise_on_disconnect(message)
            if "text" in message:
                try:
                    data = json.loads(message["text"])
                    browser_connection_logger.exception(
                        f"Received unexpected message: {data}"
                    )
                except json.JSONDecodeError as e:
                    browser_connection_logger.exception(
                        f"Failed to decode unexpected message JSON: {e}"
                    )
            elif "bytes" in message:
                audio_chunk = message["bytes"]
                await realtime_connection.input_audio_buffer.append(
                    audio=base64.b64encode(cast(bytes, audio_chunk)).decode("utf-8")
                )
            else:
                browser_connection_logger.exception(
                    f"Received unexpected message: {message}"
                )

    except WebSocketDisconnect:
        browser_connection_logger.debug("Browser closed the websocket connection.")
    except asyncio.CancelledError:
        browser_connection_logger.debug(
            "Received task cancellation signal. Closing the browser websocket."
        )
        await browser_connection.close()
        raise


async def handle_openai_events(
    browser_connection: WebSocket,
    realtime_connection: AsyncRealtimeConnection,
    openai_client: OpenAIClientType,
    thread: Thread,
    openai_task_queue: asyncio.Queue,
):
    try:
        async for event in realtime_connection:
            match event.type:
                case "response.audio_transcript.done":
                    await openai_task_queue.put(
                        lambda _event=event: add_message_to_thread(
                            openai_client,
                            browser_connection,
                            thread,
                            _event,
                            is_user_message=False,
                        )
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
                    openai_connection_logger.exception(f"Session error: {event.error}")
                case "session.ended":
                    openai_connection_logger.debug(f"Session ended: {event.session}")
                    await browser_connection.send_json(
                        {
                            "type": "session.ended",
                            "message": "Session ended.",
                        }
                    )
                case "conversation.item.input_audio_transcription.completed":
                    await openai_task_queue.put(
                        lambda _event=event: add_message_to_thread(
                            openai_client,
                            browser_connection,
                            thread,
                            _event,
                            is_user_message=True,
                        )
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
                    # Making sure we don't miss any events
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


async def process_openai_tasks(openai_task_queue: asyncio.Queue):
    try:
        while True:
            task_func = await openai_task_queue.get()
            try:
                await task_func()
            except Exception as e:
                openai_connection_logger.exception(f"Error processing OpenAI task: {e}")
            openai_task_queue.task_done()
    except asyncio.CancelledError:
        openai_connection_logger.debug("Task queue processor was cancelled.")


@ws_auth_middleware
@ws_db_middleware
@ws_parse_session_token
@ws_check_realtime_permissions
@ws_with_openai_client
@ws_with_thread_assistant_prompt
@ws_with_realtime_connection
async def browser_realtime_websocket(
    browser_connection: WebSocket, class_id: str, thread_id: str
):
    realtime_connection: AsyncRealtimeConnection = (
        browser_connection.state.realtime_connection
    )
    openai_client: OpenAIClientType = browser_connection.state.openai_client
    thread: Thread = browser_connection.state.thread

    openai_task_queue: asyncio.Queue = asyncio.Queue()

    browser_task = asyncio.create_task(
        handle_browser_messages(browser_connection, realtime_connection)
    )
    openai_task = asyncio.create_task(
        handle_openai_events(
            browser_connection,
            realtime_connection,
            openai_client,
            thread,
            openai_task_queue,
        )
    )
    openai_queue_processor = asyncio.create_task(
        process_openai_tasks(openai_task_queue)
    )

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

    # Make sure to wait for the task queue to finish processing
    await openai_task_queue.join()

    openai_queue_processor.cancel()
    try:
        await openai_queue_processor
    except asyncio.CancelledError:
        pass
