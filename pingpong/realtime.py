import asyncio
import base64
import json
import logging
import struct
from typing import Awaitable, Callable, cast
from fastapi import WebSocket, WebSocketDisconnect
from openai import OpenAIError
from sqlalchemy import func
from starlette.requests import ClientDisconnect

from openai.resources.realtime.realtime import AsyncRealtimeConnection
from openai.types.realtime import (
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

TaskFunc = Callable[[], Awaitable[object]]
TaskFactory = Callable[[str], TaskFunc]


class ConversationItemOrderingBuffer:
    """Ensures thread messages are enqueued in the order items appear in the conversation."""

    def __init__(self, task_queue: asyncio.Queue, logger: logging.Logger):
        self._task_queue = task_queue
        self._logger = logger
        self.relevant_item_order: list[str] = []
        self.relevant_item_previous: dict[str, str | None] = {}
        self.relevant_item_registration_order: dict[str, int] = {}
        self.relevant_item_registration_counter = 0
        self.pending_message_tasks: dict[str, TaskFactory] = {}
        self.dispatched_item_ids: set[str] = set()
        self.next_relevant_index_to_dispatch = 0
        self.next_output_index = 0

    @staticmethod
    def is_relevant_conversation_item(item) -> bool:
        item_role = getattr(item, "role", None)
        item_type = getattr(item, "type", None)
        return item_type == "message" and item_role in {"user", "assistant"}

    def register_relevant_item(self, item_id: str | None, previous_item_id: str | None):
        if not item_id:
            return

        if item_id not in self.relevant_item_previous:
            self.relevant_item_registration_order[item_id] = (
                self.relevant_item_registration_counter
            )
            self.relevant_item_registration_counter += 1
            self.relevant_item_previous[item_id] = previous_item_id
            self._rebuild_relevant_item_order()
            return

        current_previous_item_id = self.relevant_item_previous[item_id]
        if current_previous_item_id is None and previous_item_id is not None:
            self.relevant_item_previous[item_id] = previous_item_id
            self._rebuild_relevant_item_order()

    def _rebuild_relevant_item_order(self):
        child_item_ids_by_parent_item_id: dict[str, list[str]] = {}
        root_item_ids: list[str] = []

        for item_id, previous_item_id in self.relevant_item_previous.items():
            if previous_item_id and previous_item_id in self.relevant_item_previous:
                child_item_ids_by_parent_item_id.setdefault(
                    previous_item_id, []
                ).append(item_id)
                continue
            root_item_ids.append(item_id)

        root_item_ids.sort(
            key=lambda item_id: self.relevant_item_registration_order[item_id]
        )
        for child_item_ids in child_item_ids_by_parent_item_id.values():
            child_item_ids.sort(
                key=lambda item_id: self.relevant_item_registration_order[item_id]
            )

        ordered_item_ids: list[str] = []
        visited_item_ids: set[str] = set()

        def visit(item_id: str):
            if item_id in visited_item_ids:
                return
            visited_item_ids.add(item_id)
            ordered_item_ids.append(item_id)
            for child_item_id in child_item_ids_by_parent_item_id.get(item_id, []):
                visit(child_item_id)

        for root_item_id in root_item_ids:
            visit(root_item_id)

        for item_id in sorted(
            self.relevant_item_previous.keys(),
            key=lambda current_item_id: self.relevant_item_registration_order[
                current_item_id
            ],
        ):
            visit(item_id)

        self.relevant_item_order = ordered_item_ids

        for idx, current_item_id in enumerate(self.relevant_item_order):
            if current_item_id not in self.dispatched_item_ids:
                self.next_relevant_index_to_dispatch = idx
                return
        self.next_relevant_index_to_dispatch = len(self.relevant_item_order)

    def _is_item_anchored(self, item_id: str, visited_item_ids: set[str] | None = None):
        previous_item_id = self.relevant_item_previous.get(item_id)
        if previous_item_id is None:
            return True
        if previous_item_id not in self.relevant_item_previous:
            return False

        if visited_item_ids is None:
            visited_item_ids = set()
        if item_id in visited_item_ids:
            return False
        visited_item_ids.add(item_id)
        return self._is_item_anchored(previous_item_id, visited_item_ids)

    async def dispatch_ready_messages(self):
        while self.next_relevant_index_to_dispatch < len(self.relevant_item_order):
            current_item_id = self.relevant_item_order[
                self.next_relevant_index_to_dispatch
            ]
            if current_item_id in self.dispatched_item_ids:
                self.next_relevant_index_to_dispatch += 1
                continue
            if not self._is_item_anchored(current_item_id):
                break

            task_factory = self.pending_message_tasks.get(current_item_id)
            if not task_factory:
                break

            output_index_str = str(self.next_output_index)
            task = task_factory(output_index_str)
            self.pending_message_tasks.pop(current_item_id, None)
            self.dispatched_item_ids.add(current_item_id)
            self.next_relevant_index_to_dispatch += 1
            self.next_output_index += 1
            await self._task_queue.put(task)

    async def enqueue_message_task(
        self, item_id: str | None, task_factory: TaskFactory
    ):
        if not item_id:
            self._logger.warning(
                "Received transcript event without an item_id. Skipping message ordering."
            )
            return

        self.pending_message_tasks[item_id] = task_factory
        await self.dispatch_ready_messages()


async def add_message_to_thread(
    openai_client: OpenAIClientType,
    browser_connection: WebSocket,
    thread: Thread,
    event: ConversationItemInputAudioTranscriptionCompletedEvent
    | ResponseAudioTranscriptDoneEvent,
    realtime_recorder: RealtimeRecorder | None = None,
    is_user_message: bool = False,
    output_index: str | None = None,
):
    try:
        metadata = {
            "item_id": event.item_id,
        }
        if output_index is not None:
            metadata["output_index"] = str(output_index)
        if is_user_message:
            metadata["user_id"] = str(browser_connection.state.session.user.id)

        if (
            hasattr(browser_connection.state, "anonymous_share_token")
            and browser_connection.state.anonymous_share_token is not None
        ):
            metadata["share_token"] = str(
                browser_connection.state.anonymous_share_token
            )
        if (
            hasattr(browser_connection.state, "anonymous_session_token")
            and browser_connection.state.anonymous_session_token is not None
        ):
            metadata["anonymous_session_token"] = str(
                browser_connection.state.anonymous_session_token
            )

        await openai_client.beta.threads.messages.create(
            thread_id=thread.thread_id,
            role="user" if is_user_message else "assistant",
            content=event.transcript,
            metadata=metadata,
        )

        if realtime_recorder and not realtime_recorder.should_save_audio:
            realtime_recorder.should_save_audio = True
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


def _build_thread_message_task_factory(
    *,
    event: ConversationItemInputAudioTranscriptionCompletedEvent
    | ResponseAudioTranscriptDoneEvent,
    is_user_message: bool,
    openai_client: OpenAIClientType,
    browser_connection: WebSocket,
    thread: Thread,
    realtime_recorder: RealtimeRecorder | None,
) -> TaskFactory:
    def factory(output_index: str) -> TaskFunc:
        async def task():
            await add_message_to_thread(
                openai_client,
                browser_connection,
                thread,
                event,
                realtime_recorder=realtime_recorder,
                is_user_message=is_user_message,
                output_index=output_index,
            )

        return task

    return factory


async def handle_browser_messages(
    browser_connection: WebSocket,
    realtime_connection: AsyncRealtimeConnection,
    realtime_recorder: RealtimeRecorder | None = None,
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
                        # NOTE: This does not impact the transcription process,
                        # which might affect the quality of the transcription.
                        await realtime_connection.conversation.item.truncate(
                            audio_end_ms=audio_end_ms,
                            content_index=0,
                            item_id=item_id,
                        )
                        if realtime_recorder:
                            await realtime_recorder.stopped_playing_assistant_response(
                                item_id=item_id,
                                final_duration_ms=audio_end_ms,
                            )
                    elif type == "response.audio.delta.started":
                        if not realtime_recorder:
                            continue
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
                        await (
                            realtime_recorder.started_playing_assistant_response_delta(
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
                    if realtime_recorder:
                        await realtime_recorder.add_user_audio(
                            audio_chunk=audio_chunk,
                            timestamp=timestamp,
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
    except (asyncio.CancelledError, ClientDisconnect):
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
    realtime_recorder: RealtimeRecorder | None = None,
):
    ordering_buffer = ConversationItemOrderingBuffer(
        openai_task_queue, openai_connection_logger
    )

    try:
        async for event in realtime_connection:
            match event.type:
                case "conversation.item.added":
                    item = getattr(event, "item", None)
                    if (
                        item
                        and ConversationItemOrderingBuffer.is_relevant_conversation_item(
                            item
                        )
                    ):
                        ordering_buffer.register_relevant_item(
                            getattr(item, "id", None),
                            getattr(event, "previous_item_id", None),
                        )
                        await ordering_buffer.dispatch_ready_messages()
                case "response.output_audio_transcript.done":
                    await ordering_buffer.enqueue_message_task(
                        event.item_id,
                        _build_thread_message_task_factory(
                            event=event,
                            is_user_message=False,
                            openai_client=openai_client,
                            browser_connection=browser_connection,
                            thread=thread,
                            realtime_recorder=realtime_recorder,
                        ),
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
                case "session.error" | "error":
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
                    await ordering_buffer.enqueue_message_task(
                        event.item_id,
                        _build_thread_message_task_factory(
                            event=event,
                            is_user_message=True,
                            openai_client=openai_client,
                            browser_connection=browser_connection,
                            thread=thread,
                            realtime_recorder=realtime_recorder,
                        ),
                    )
                case "response.output_audio.delta":
                    delta_audio_b64 = event.delta
                    await browser_connection.send_json(
                        {
                            "type": "response.audio.delta",
                            "audio": delta_audio_b64,
                            "item_id": event.item_id,
                            "event_id": event.event_id,
                        }
                    )
                    if realtime_recorder:
                        await realtime_recorder.add_assistant_response_delta(
                            b64_audio_chunk=delta_audio_b64,
                            event_id=event.event_id,
                            item_id=event.item_id,
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
                    | "conversation.item.retrieved"
                    | "conversation.item.truncated"
                    | "conversation.item.done"
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
                    | "response.output_audio_transcript.delta"
                    | "response.output_audio.done"
                    | "response.output_text.delta"
                    | "response.output_text.done"
                    | "response.function_call_arguments.delta"
                    | "response.function_call_arguments.done"
                    | "transcription_session.updated"
                    | "rate_limits.updated"
                    | "input_audio_buffer.timeout_triggered"
                    | "conversation.item.input_audio_transcription.segment"
                ):
                    # Making sure we don't miss any events
                    continue
                case _:
                    openai_connection_logger.warning(
                        f"Ignoring unknown event type... {event.type}"
                    )

    except (asyncio.CancelledError, ClientDisconnect):
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
    except (asyncio.CancelledError, ClientDisconnect):
        task_logger.debug("Task queue processor was cancelled.")


@ws_auth_middleware
@ws_db_middleware
@ws_parse_session_token
@ws_check_realtime_permissions
@ws_with_openai_client
@ws_with_thread_assistant_prompt
@ws_with_realtime_connection
async def browser_realtime_websocket(
    browser_connection: WebSocket,
    class_id: str,
    thread_id: str,
):
    realtime_connection: AsyncRealtimeConnection = (
        browser_connection.state.realtime_connection
    )
    openai_client: OpenAIClientType = browser_connection.state.openai_client
    thread: Thread = browser_connection.state.thread

    openai_task_queue: NamedQueue = NamedQueue("openai_task_queue")

    realtime_recorder: RealtimeRecorder | None = None
    if thread.display_user_info:
        realtime_recorder = await RealtimeRecorder.create(
            thread_id=thread.id,
            thread_obj_id=thread.thread_id,
            session=browser_connection.state.db,
        )

    realtime_tasks: list[asyncio.Task] = []

    realtime_tasks.append(
        asyncio.create_task(
            handle_browser_messages(
                browser_connection,
                realtime_connection,
                realtime_recorder,
            )
        )
    )
    realtime_tasks.append(
        asyncio.create_task(
            handle_openai_events(
                browser_connection,
                realtime_connection,
                openai_client,
                thread,
                openai_task_queue,
                realtime_recorder,
            )
        )
    )
    openai_queue_processor = asyncio.create_task(
        process_queue_tasks(openai_task_queue, openai_connection_logger)
    )

    if realtime_recorder:
        realtime_tasks.append(
            asyncio.create_task(realtime_recorder.handle_saving_buffer(every=10))
        )

    _, pending = await asyncio.wait(
        realtime_tasks,
        return_when=asyncio.FIRST_COMPLETED,
    )

    for task in pending:
        task.cancel()
        try:
            await task
        except (asyncio.CancelledError, ClientDisconnect):
            # Suppress cancellation/client disconnect exceptions: expected during shutdown/cleanup.
            pass

    # Make sure to wait for the task queue to finish processing
    await openai_task_queue.join()

    openai_queue_processor.cancel()
    try:
        await openai_queue_processor
    except (asyncio.CancelledError, ClientDisconnect):
        # Suppress cancellation/client disconnect exceptions: expected during shutdown/cleanup.
        pass
