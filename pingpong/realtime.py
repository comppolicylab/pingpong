import asyncio
import base64
from collections import deque
import json
import logging
import struct
from dataclasses import dataclass
from heapq import heappop, heappush
from typing import Awaitable, Callable, Literal, cast
from fastapi import WebSocket, WebSocketDisconnect
from openai import OpenAIError
from sqlalchemy import func
from starlette.requests import ClientDisconnect

from openai.resources.realtime.realtime import AsyncRealtimeConnection


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
ConversationRole = Literal["user", "assistant"]
UNSET_PREVIOUS_ITEM_ID = "__UNSET_PREVIOUS_ITEM_ID__"


@dataclass
class ConversationChainItem:
    item_id: str
    conversation_order: int = -1
    has_transcription: bool = False
    is_transcription_complete: bool = False
    is_message_saved: bool = False
    previous_item_id: str | None = UNSET_PREVIOUS_ITEM_ID
    transcription_text: str | None = None
    role: ConversationRole | None = None


class ConversationItemOrderingBuffer:
    """Tracks conversation chain items and returns ready transcripts in order."""

    _UNSET_PREVIOUS_ITEM_ID = UNSET_PREVIOUS_ITEM_ID

    def __init__(self, logger: logging.Logger):
        self._logger = logger
        self.items_by_id: dict[str, ConversationChainItem] = {}
        self.children_by_previous_item_id: dict[str, set[str]] = {}
        self.ready_item_heap: list[tuple[int, str]] = []
        self.queued_ready_item_ids: set[str] = set()
        self.next_conversation_order = 0
        self.next_output_index = 0

    @staticmethod
    def is_relevant_conversation_item(item) -> bool:
        item_role = getattr(item, "role", None)
        item_type = getattr(item, "type", None)
        return item_type == "message" and item_role in {"user", "assistant"}

    def register_conversation_item(
        self,
        item_id: str | None,
        previous_item_id: str | None,
        role: ConversationRole | None,
    ):
        if not item_id:
            return

        item = self._get_item(item_id=item_id)
        if item is None:
            item = ConversationChainItem(
                item_id=item_id,
                conversation_order=self.next_conversation_order,
            )
            self.next_conversation_order += 1
            self.items_by_id[item_id] = item
        else:
            self._logger.warning(
                "Received duplicate conversation.item.added for item_id %s.",
                item_id,
            )

        self._set_item_previous_item_id(item=item, previous_item_id=previous_item_id)
        if role is not None:
            item.role = role
            item.has_transcription = True
        self._mark_item_and_descendants_for_readiness(item.item_id)

    def register_transcription(
        self,
        item_id: str | None,
        transcription_text: str | None,
        role: ConversationRole,
    ):
        if not item_id:
            self._logger.warning(
                "Received transcript event without an item_id. Skipping message ordering."
            )
            return

        item = self._get_item(item_id=item_id)
        if item is None:
            self._logger.warning(
                "Received completed transcript for unknown item_id %s before conversation.item.added.",
                item_id,
            )
            return

        if self._is_message_saved(item):
            self._logger.warning(
                "Received transcript for already-saved item_id %s. Ignoring duplicate.",
                item_id,
            )
            return

        if item.is_transcription_complete:
            self._logger.warning(
                "Received transcription completion for already-complete item_id %s.",
                item_id,
            )
            return

        if transcription_text is not None:
            item.transcription_text = transcription_text
        if item.transcription_text is None:
            self._logger.warning(
                "Received completed transcript without text for item_id %s.",
                item_id,
            )
            return

        item.is_transcription_complete = True
        item.has_transcription = True
        if item.role is None:
            item.role = role
        self._mark_item_and_descendants_for_readiness(item.item_id)

    def register_transcription_delta(
        self, item_id: str | None, delta_text: str | None, role: ConversationRole
    ):
        if not item_id or not delta_text:
            return

        item = self._get_item(item_id=item_id)
        if item is None:
            self._logger.warning(
                "Received transcript delta for unknown item_id %s before conversation.item.added.",
                item_id,
            )
            return

        if self._is_message_saved(item):
            self._logger.warning(
                "Received transcription delta for already-saved item_id %s. Ignoring.",
                item_id,
            )
            return
        if item.is_transcription_complete:
            self._logger.warning(
                "Received transcription delta after completion for item_id %s. Ignoring.",
                item_id,
            )
            return

        if item.transcription_text is None:
            item.transcription_text = ""
        item.transcription_text += delta_text
        item.has_transcription = True
        if item.role is None:
            item.role = role
        self._mark_item_and_descendants_for_readiness(item.item_id)

    def pop_next_ready_message(
        self,
    ) -> tuple[str, str, ConversationRole, str] | None:
        while self.ready_item_heap:
            _, item_id = heappop(self.ready_item_heap)
            self.queued_ready_item_ids.discard(item_id)
            item = self._get_item(item_id=item_id)
            if item is None:
                continue
            if not self._is_item_ready_to_dispatch(item):
                continue
            if item.transcription_text is None or item.role is None:
                continue
            output_index = str(self.next_output_index)
            self.next_output_index += 1
            item.is_message_saved = True
            self._mark_item_and_descendants_for_readiness(item.item_id)
            return item.item_id, item.transcription_text, item.role, output_index

        return None

    def _get_item(self, item_id: str) -> ConversationChainItem | None:
        return self.items_by_id.get(item_id)

    def _set_item_previous_item_id(
        self, *, item: ConversationChainItem, previous_item_id: str | None
    ):
        if item.previous_item_id == self._UNSET_PREVIOUS_ITEM_ID:
            item.previous_item_id = previous_item_id
            if previous_item_id is not None:
                self.children_by_previous_item_id.setdefault(
                    previous_item_id, set()
                ).add(item.item_id)
            return

        if item.previous_item_id is None and previous_item_id is not None:
            item.previous_item_id = previous_item_id
            self.children_by_previous_item_id.setdefault(previous_item_id, set()).add(
                item.item_id
            )

    def _is_message_saved(self, item: ConversationChainItem) -> bool:
        return item.is_message_saved

    def _queue_if_item_ready(self, item: ConversationChainItem):
        if item.item_id in self.queued_ready_item_ids:
            return
        if not self._is_item_ready_to_dispatch(item):
            return

        heappush(self.ready_item_heap, (item.conversation_order, item.item_id))
        self.queued_ready_item_ids.add(item.item_id)

    def _mark_item_and_descendants_for_readiness(self, item_id: str):
        pending_item_ids = deque([item_id])
        visited_item_ids: set[str] = set()

        while pending_item_ids:
            current_item_id = pending_item_ids.popleft()
            if current_item_id in visited_item_ids:
                continue
            visited_item_ids.add(current_item_id)

            current_item = self._get_item(current_item_id)
            if current_item is not None:
                self._queue_if_item_ready(current_item)

            for child_item_id in self.children_by_previous_item_id.get(
                current_item_id, set()
            ):
                pending_item_ids.append(child_item_id)

    def _resolve_previous_relevant_item(
        self, item: ConversationChainItem
    ) -> tuple[bool, ConversationChainItem | None]:
        if item.previous_item_id == self._UNSET_PREVIOUS_ITEM_ID:
            return False, None

        seen_item_ids = {item.item_id}
        previous_item_id = item.previous_item_id

        while previous_item_id is not None:
            if previous_item_id in seen_item_ids:
                return False, None

            previous_item = self._get_item(previous_item_id)
            if previous_item is None:
                return False, None
            if previous_item.has_transcription:
                return True, previous_item

            if previous_item.previous_item_id == self._UNSET_PREVIOUS_ITEM_ID:
                return False, None
            seen_item_ids.add(previous_item_id)
            previous_item_id = previous_item.previous_item_id

        return True, None

    def _is_item_ready_to_dispatch(self, item: ConversationChainItem) -> bool:
        if item.role not in {"user", "assistant"}:
            return False
        if not item.has_transcription:
            return False
        if item.is_message_saved:
            return False
        if not item.is_transcription_complete:
            return False
        if item.transcription_text is None:
            return False

        is_resolved, previous_relevant_item = self._resolve_previous_relevant_item(item)
        if not is_resolved:
            return False
        if previous_relevant_item is not None and not self._is_message_saved(
            previous_relevant_item
        ):
            return False

        return True


async def add_message_to_thread(
    openai_client: OpenAIClientType,
    browser_connection: WebSocket,
    thread: Thread,
    item_id: str,
    transcript_text: str,
    role: ConversationRole,
    realtime_recorder: RealtimeRecorder | None = None,
    output_index: str | None = None,
):
    is_user_message = role == "user"
    try:
        metadata = {
            "item_id": item_id,
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
            role=role,
            content=transcript_text,
            metadata=metadata,
        )

        if realtime_recorder and not realtime_recorder.should_save_audio:
            realtime_recorder.should_save_audio = True
    except OpenAIError as e:
        openai_connection_logger.exception(
            f"Failed to send message to OpenAI: {e}, item_id={item_id}, role={role}"
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


async def enqueue_ready_thread_message_tasks(
    ordering_buffer: ConversationItemOrderingBuffer,
    openai_task_queue: asyncio.Queue,
    openai_client: OpenAIClientType,
    browser_connection: WebSocket,
    thread: Thread,
    realtime_recorder: RealtimeRecorder | None,
) -> None:
    while True:
        next_ready_message = ordering_buffer.pop_next_ready_message()
        if next_ready_message is None:
            return

        item_id, transcript_text, role, output_index = next_ready_message

        async def task(
            item_id: str = item_id,
            transcript_text: str = transcript_text,
            role: ConversationRole = role,
            output_index: str = output_index,
        ):
            await add_message_to_thread(
                openai_client,
                browser_connection,
                thread,
                item_id,
                transcript_text,
                role,
                realtime_recorder=realtime_recorder,
                output_index=output_index,
            )

        await openai_task_queue.put(task)


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
    ordering_buffer = ConversationItemOrderingBuffer(openai_connection_logger)

    try:
        async for event in realtime_connection:
            match event.type:
                case "conversation.item.added":
                    item = getattr(event, "item", None)
                    item_role = getattr(item, "role", None) if item else None
                    role: ConversationRole | None = None
                    if (
                        item
                        and ConversationItemOrderingBuffer.is_relevant_conversation_item(
                            item
                        )
                    ):
                        role = cast(ConversationRole, item_role)

                    ordering_buffer.register_conversation_item(
                        getattr(item, "id", None) if item else None,
                        getattr(event, "previous_item_id", None),
                        role,
                    )
                    await enqueue_ready_thread_message_tasks(
                        ordering_buffer=ordering_buffer,
                        openai_task_queue=openai_task_queue,
                        openai_client=openai_client,
                        browser_connection=browser_connection,
                        thread=thread,
                        realtime_recorder=realtime_recorder,
                    )
                case "response.output_audio_transcript.done":
                    ordering_buffer.register_transcription(
                        event.item_id, event.transcript, "assistant"
                    )
                    await enqueue_ready_thread_message_tasks(
                        ordering_buffer=ordering_buffer,
                        openai_task_queue=openai_task_queue,
                        openai_client=openai_client,
                        browser_connection=browser_connection,
                        thread=thread,
                        realtime_recorder=realtime_recorder,
                    )
                case "response.output_audio_transcript.delta":
                    ordering_buffer.register_transcription_delta(
                        event.item_id, event.delta, "assistant"
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
                    ordering_buffer.register_transcription(
                        event.item_id, event.transcript, "user"
                    )
                    await enqueue_ready_thread_message_tasks(
                        ordering_buffer=ordering_buffer,
                        openai_task_queue=openai_task_queue,
                        openai_client=openai_client,
                        browser_connection=browser_connection,
                        thread=thread,
                        realtime_recorder=realtime_recorder,
                    )
                case "conversation.item.input_audio_transcription.delta":
                    ordering_buffer.register_transcription_delta(
                        event.item_id, event.delta, "user"
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
