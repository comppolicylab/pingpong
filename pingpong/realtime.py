import asyncio
import base64
from functools import partial
import json
import logging
import struct
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
from pingpong.realtime_recorder import RealtimeRecorder
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
realtime_recorder_logger = logging.getLogger("audio_recorder")


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
    browser_connection: WebSocket,
    realtime_connection: AsyncRealtimeConnection,
    realtime_recorder: RealtimeRecorder,
    user_audio_queue: asyncio.Queue,
    assistant_audio_queue: asyncio.Queue,
):
    try:
        while True:
            message = await browser_connection.receive()
            browser_connection._raise_on_disconnect(message)
            if "text" in message:
                try:
                    data = json.loads(message["text"])
                    type = data.get("type")
                    if not type:
                        browser_connection_logger.exception(
                            f"Received unexpected message: {data}"
                        )
                    elif type == "conversation.item.truncate":
                        item_id = data.get("item_id")
                        audio_end_ms = data.get("audio_end_ms")
                        if item_id is None or audio_end_ms is None:
                            browser_connection_logger.exception(
                                "Received conversation.item.truncate message without item_id or audio_end_ms"
                            )
                            continue
                        # Truncate the audio buffer for the specified item
                        await realtime_connection.conversation.item.truncate(
                            audio_end_ms=audio_end_ms,
                            content_index=0,
                            item_id=item_id,
                        )
                        await assistant_audio_queue.put(
                            partial(
                                realtime_recorder.stopped_playing_assistant_response,
                                item_id=item_id,
                                final_duration_ms=audio_end_ms,
                            )
                        )
                    elif type == "response.audio.delta.started":
                        item_id = data.get("item_id")
                        event_id = data.get("event_id")
                        started_playing_at_ms = data.get("started_playing_at")
                        if (
                            item_id is None
                            or event_id is None
                            or started_playing_at_ms is None
                        ):
                            browser_connection_logger.exception(
                                f"Received response.audio.delta.started message without item_id, event_id, or started_playing_at {data}"
                            )
                            continue
                        else:
                            await assistant_audio_queue.put(
                                partial(
                                    realtime_recorder.started_playing_assistant_response_delta,
                                    item_id=item_id,
                                    event_id=event_id,
                                    started_playing_at_ms=started_playing_at_ms,
                                )
                            )

                except json.JSONDecodeError as e:
                    browser_connection_logger.exception(
                        f"Failed to decode unexpected message JSON: {e}"
                    )
            elif "bytes" in message:
                buffer = message["bytes"]

                timestamp_size = 8
                if len(buffer) >= timestamp_size:
                    timestamp = struct.unpack(">d", buffer[:8])[0]
                    audio_chunk = buffer[8:]
                    await realtime_connection.input_audio_buffer.append(
                        audio=base64.b64encode(cast(bytes, audio_chunk)).decode("utf-8")
                    )
                    await user_audio_queue.put(
                        partial(
                            realtime_recorder.add_user_audio,
                            audio_chunk=audio_chunk,
                            timestamp=timestamp,
                        )
                    )
                else:
                    browser_connection_logger.exception(
                        f"Received insufficient data for timestamp and audio: {len(buffer)} bytes"
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
    realtime_recorder: RealtimeRecorder,
    assistant_audio_queue: asyncio.Queue,
):
    try:
        async for event in realtime_connection:
            match event.type:
                case "response.audio_transcript.done":
                    await openai_task_queue.put(
                        partial(
                            add_message_to_thread,
                            openai_client,
                            browser_connection,
                            thread,
                            event,
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
                        partial(
                            add_message_to_thread,
                            openai_client,
                            browser_connection,
                            thread,
                            event,
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
                            "event_id": event.event_id,
                        }
                    )
                    await assistant_audio_queue.put(
                        partial(
                            realtime_recorder.add_assistant_response_delta,
                            b64_audio_chunk=delta_audio_b64,
                            event_id=event.event_id,
                            item_id=event.item_id,
                        )
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


class NamedQueue(asyncio.Queue):
    def __init__(self, name, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = name


async def process_queue_tasks(
    task_queue: NamedQueue,
    task_logger: logging.Logger,
):
    try:
        while True:
            task_func = await task_queue.get()
            try:
                await task_func()
            except Exception as e:
                task_logger.exception(f"Error processing {task_queue.name} task: {e}")
            task_queue.task_done()
    except asyncio.CancelledError:
        task_logger.debug("Task queue processor was cancelled.")


async def handle_saving_buffer(realtime_recorder: RealtimeRecorder):
    try:
        while True:
            await asyncio.sleep(60)
            try:
                await realtime_recorder.save_buffer()
            except Exception as e:
                realtime_recorder_logger.exception("Error in save_buffer: %s", e)
    except asyncio.CancelledError:
        try:
            realtime_recorder_logger.info(
                "Received task cancellation signal. Saving buffer before closing."
            )
            await realtime_recorder.finalize()
            await realtime_recorder.save_buffer()
        except Exception as e:
            realtime_recorder_logger.exception("Error in save_buffer: %s", e)
        finally:
            raise


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

    openai_task_queue: NamedQueue = NamedQueue("openai_task_queue")
    user_audio_queue: NamedQueue = NamedQueue("user_audio_queue")
    assistant_audio_queue: NamedQueue = NamedQueue("assistant_audio_queue")

    realtime_recorder = RealtimeRecorder()
    browser_task = asyncio.create_task(
        handle_browser_messages(
            browser_connection,
            realtime_connection,
            realtime_recorder,
            user_audio_queue,
            assistant_audio_queue,
        )
    )
    openai_task = asyncio.create_task(
        handle_openai_events(
            browser_connection,
            realtime_connection,
            openai_client,
            thread,
            openai_task_queue,
            realtime_recorder,
            assistant_audio_queue,
        )
    )
    openai_queue_processor = asyncio.create_task(
        process_queue_tasks(openai_task_queue, openai_connection_logger)
    )
    user_audio_queue_processor = asyncio.create_task(
        process_queue_tasks(
            user_audio_queue,
            realtime_recorder_logger,
        )
    )
    assistant_audio_queue_processor = asyncio.create_task(
        process_queue_tasks(assistant_audio_queue, realtime_recorder_logger)
    )

    recording_task = asyncio.create_task(handle_saving_buffer(realtime_recorder))

    _, pending = await asyncio.wait(
        [browser_task, openai_task, recording_task],
        return_when=asyncio.FIRST_COMPLETED,
    )

    for task in pending:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    # Wait for the task queues to finish processing
    await asyncio.gather(
        openai_task_queue.join(),
        user_audio_queue.join(),
        assistant_audio_queue.join(),
    )

    openai_queue_processor.cancel()
    user_audio_queue_processor.cancel()
    assistant_audio_queue_processor.cancel()
    try:
        asyncio.gather(
            openai_queue_processor,
            user_audio_queue_processor,
            assistant_audio_queue_processor,
        )
    except asyncio.CancelledError:
        pass
