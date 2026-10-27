import asyncio
import binascii
import base64
from collections import deque
import json
import logging
import math
import struct
import time
from dataclasses import dataclass
from heapq import heappop, heappush
from typing import Awaitable, Callable, Literal, cast

import pybase64
from fastapi import WebSocketDisconnect
from openai import OpenAIError
from sqlalchemy import func, select
from starlette.requests import ClientDisconnect
from starlette.websockets import WebSocketState

from openai.resources.realtime.realtime import AsyncRealtimeConnection


from pingpong.ai import (
    OpenAIClientType,
)
import pingpong.schemas as schemas
from pingpong.config import config
from pingpong.log_utils import sanitize_for_log
from pingpong.models import Class, Thread, MessagePart, Message, Run
from pingpong.realtime_recorder import (
    AUDIO_CHANNELS,
    AUDIO_FRAME_RATE,
    AUDIO_SAMPLE_WIDTH,
    RealtimeRecorder,
    VoiceRecordingHealth,
)
from pingpong.ai_error import get_ai_error_message
from pingpong.realtime_usage import RealtimeUsage
from pingpong.websocket import (
    REALTIME_CONNECTION_ERRORS,
    ws_auth_middleware,
    ws_check_realtime_permissions,
    ws_db_middleware,
    ws_parse_session_token,
    ws_with_single_realtime_session,
    ws_with_openai_client,
    ws_with_realtime_connection,
)
from pingpong.state_types import StateWebSocket

browser_connection_logger = logging.getLogger("realtime_browser")
openai_connection_logger = logging.getLogger("realtime_openai")

TaskFunc = Callable[[], Awaitable[object]]
ConversationRole = Literal["user", "assistant"]
VoicePlaybackOutcome = Literal["completed", "interrupted", "discarded", "unknown"]
UNSET_PREVIOUS_ITEM_ID = "__UNSET_PREVIOUS_ITEM_ID__"
BROWSER_DISCONNECT_DRAIN_SECONDS = 15.0
REALTIME_SESSION_MAX_SECONDS = 60 * 60
REALTIME_EXPIRY_MARGIN_SECONDS = 60.0
BROWSER_EXPIRY_STOP_SECONDS = 5.0
REALTIME_EXPIRY_WARNING_SECONDS = (5 * 60, 60)
EXPIRY_WARNING_SEND_SECONDS = 1.0
BROWSER_SAVE_CONFIRMATION_SECONDS = 5.0


class RealtimeSessionExpiry:
    def __init__(self):
        self.stopping = False
        self.deadline = (
            asyncio.get_running_loop().time()
            + REALTIME_SESSION_MAX_SECONDS
            - REALTIME_EXPIRY_MARGIN_SECONDS
        )
        self._changed = asyncio.Event()

    def observe(self, session) -> None:
        expires_at = getattr(session, "expires_at", None)
        if (
            isinstance(expires_at, (int, float))
            and not isinstance(expires_at, bool)
            and math.isfinite(expires_at)
        ):
            # Convert epoch time once; later wall-clock changes must not move
            # the deadline. Updates can shorten, but never extend, the session.
            self.deadline = min(
                self.deadline,
                asyncio.get_running_loop().time()
                + expires_at
                - time.time()
                - REALTIME_EXPIRY_MARGIN_SECONDS,
            )
            self._changed.set()

    async def wait(
        self, on_warning: Callable[[int], Awaitable[None]] | None = None
    ) -> None:
        warnings = set(REALTIME_EXPIRY_WARNING_SECONDS) if on_warning else set()
        while True:
            self._changed.clear()
            remaining = self.deadline - asyncio.get_running_loop().time()
            if remaining <= 0:
                self.stopping = True
                return
            due = [seconds for seconds in warnings if remaining <= seconds]
            if due:
                # If the deadline moves earlier, send only the most urgent
                # warning rather than a burst of obsolete notices.
                warnings.difference_update(due)
                try:
                    async with asyncio.timeout(
                        min(EXPIRY_WARNING_SEND_SECONDS, remaining)
                    ):
                        if on_warning is not None:
                            await on_warning(math.ceil(remaining))
                except Exception:
                    # An optional warning must never end the conversation or
                    # leave the expiry timer stuck behind a browser send.
                    browser_connection_logger.debug(
                        "Could not deliver voice expiry warning.", exc_info=True
                    )
                continue
            delay = remaining - max(warnings) if warnings else remaining
            try:
                async with asyncio.timeout(delay):
                    await self._changed.wait()
            except TimeoutError:
                continue


class RealtimeShutdownDrain:
    def __init__(self):
        self.stopping = False
        self.pending_transcripts: set[str] = set()
        self._completed_transcripts: set[str] = set()
        self._vad_disabled = False
        self._clear_requested = False
        self._buffer_cleared = False
        self._clear_failed = False
        self._cancel_event_response_ids: dict[str, str] = {}
        self.usage = RealtimeUsage()
        self._changed = asyncio.Event()

    def observe(self, event) -> None:
        # Observe after normal handling so a completion cannot cut off its
        # transcript recovery or queued database write.
        self.usage.observe(event)
        if event.type in {
            "input_audio_buffer.committed",
            "input_audio_buffer.speech_stopped",
            "conversation.item.input_audio_transcription.delta",
        }:
            if event.item_id not in self._completed_transcripts:
                self.pending_transcripts.add(event.item_id)
        elif event.type in {
            "conversation.item.input_audio_transcription.completed",
            "conversation.item.input_audio_transcription.failed",
        }:
            self._completed_transcripts.add(event.item_id)
            self.pending_transcripts.discard(event.item_id)
        elif self.stopping and event.type == "session.updated":
            audio_input = getattr(getattr(event.session, "audio", None), "input", None)
            self._vad_disabled = (
                audio_input is not None
                and hasattr(audio_input, "turn_detection")
                and audio_input.turn_detection is None
            )
        elif self._clear_requested and event.type == "input_audio_buffer.cleared":
            self._buffer_cleared = True
        elif (
            self._clear_requested
            and event.type in {"error", "session.error"}
            and getattr(event.error, "event_id", None) == "voice_shutdown_clear"
        ):
            self._clear_failed = True
            self.usage.mark_incomplete("input_audio_buffer_clear_failed")
        self._changed.set()

    def is_finished_cancellation_error(self, error) -> bool:
        event_id = getattr(error, "event_id", None)
        if not isinstance(event_id, str):
            return False
        response_id = self._cancel_event_response_ids.get(event_id)
        return (
            response_id is not None
            and response_id not in self.usage.pending_response_ids
        )

    def is_complete(self, ordering_buffer: "ConversationItemOrderingBuffer") -> bool:
        tracker = ordering_buffer.assistant_audio_tracker
        heard_item_ids = tracker.played_item_ids if tracker is not None else frozenset()
        return (
            self.stopping
            and self._vad_disabled
            and (self._buffer_cleared or self._clear_failed)
            and not self.usage.pending_response_ids
            and not self.pending_transcripts
            and not ordering_buffer.has_pending_retained_items(heard_item_ids)
        )

    async def wait(
        self,
        connection: AsyncRealtimeConnection,
        ordering_buffer: "ConversationItemOrderingBuffer",
    ) -> None:
        self.stopping = True
        cancellation_requested: set[str] = set()
        started_at = asyncio.get_running_loop().time()
        try:
            async with asyncio.timeout(BROWSER_DISCONNECT_DRAIN_SECONDS):
                try:
                    # Stop new turns without committing unfinished input.
                    await connection.session.update(
                        session={
                            "type": "realtime",
                            "audio": {"input": {"turn_detection": None}},
                        }
                    )
                except Exception:
                    openai_connection_logger.exception(
                        "Failed to disable turn detection during voice shutdown."
                    )
                self._clear_requested = True
                try:
                    await connection.input_audio_buffer.clear(
                        event_id="voice_shutdown_clear"
                    )
                except Exception as error:
                    self._clear_failed = True
                    self.usage.mark_incomplete("input_audio_buffer_clear_failed")
                    self.usage.record_exception(
                        error, code="input_audio_buffer_clear_failed"
                    )
                    openai_connection_logger.exception(
                        "Failed to clear input audio during voice shutdown."
                    )
                while True:
                    self._changed.clear()
                    # Include responses announced during draining. Playback does
                    # not gate provider usage, even when no reply was heard.
                    for response_id in sorted(
                        self.usage.pending_response_ids - cancellation_requested
                    ):
                        if response_id not in self.usage.pending_response_ids:
                            continue
                        cancellation_requested.add(response_id)
                        event_id = f"voice_shutdown_cancel_{response_id}"
                        self._cancel_event_response_ids[event_id] = response_id
                        try:
                            await connection.response.cancel(
                                response_id=response_id, event_id=event_id
                            )
                        except Exception:
                            openai_connection_logger.exception(
                                "Failed to cancel voice response_id=%s during shutdown.",
                                sanitize_for_log(response_id),
                            )
                    if self.is_complete(ordering_buffer):
                        return
                    await self._changed.wait()
        except TimeoutError:
            self.usage.mark_incomplete("shutdown_drain_timeout")
            openai_connection_logger.warning(
                "Voice shutdown drain reached its deadline: "
                "elapsed_seconds=%.2f pending_responses=%s "
                "pending_transcripts=%s vad_disabled=%s buffer_cleared=%s.",
                asyncio.get_running_loop().time() - started_at,
                sanitize_for_log(sorted(self.usage.pending_response_ids), max_len=1024),
                sanitize_for_log(sorted(self.pending_transcripts), max_len=1024),
                self._vad_disabled,
                self._buffer_cleared,
            )


def _serialize_realtime_error(error) -> dict[str, str | None]:
    # Keep internal OpenAI details out of browser-visible errors.
    return {
        "type": "invalid_request_error",
        "code": "openai_realtime_session",
        "message": get_ai_error_message(
            error, "We were unable to start the voice session."
        ),
        "param": None,
    }


def _has_non_empty_transcript(transcript_text: str | None) -> bool:
    if transcript_text is None:
        return False
    return bool(transcript_text.strip())


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
    skip_persistence: bool = False


@dataclass
class _AssistantAudioPlaybackEvent:
    started: bool = False
    ended: bool = False


class RealtimeAssistantAudioTracker:
    """Tracks generated duration and browser-confirmed playback independently."""

    _BYTES_PER_FRAME = AUDIO_SAMPLE_WIDTH * AUDIO_CHANNELS

    def __init__(self):
        self._lock = asyncio.Lock()
        self._sample_counts_by_item_id: dict[str, int] = {}
        self._event_end_sample_counts_by_item_id: dict[str, dict[str, int]] = {}
        self._audio_done_item_ids: set[str] = set()
        self._playback_events_by_item_id: dict[
            str, dict[str, _AssistantAudioPlaybackEvent]
        ] = {}
        self._played_item_ids: set[str] = set()
        self._retention_decided = asyncio.Event()
        self._playback_tracking_finished = False
        self._item_retention_decisions: dict[str, asyncio.Event] = {}
        self._known_item_ids: set[str] = set()
        self._items_with_audio: set[str] = set()
        self._playback_outcomes: dict[str, VoicePlaybackOutcome] = {}
        self._generation_done_item_ids: set[str] = set()

    @property
    def has_played_audio(self) -> bool:
        return bool(self._played_item_ids)

    @property
    def played_item_ids(self) -> frozenset[str]:
        return frozenset(self._played_item_ids)

    def has_item_played_audio(self, item_id: str) -> bool:
        return item_id in self._played_item_ids

    async def wait_for_retention_decision(self) -> bool:
        await self._retention_decided.wait()
        return self.has_played_audio

    async def wait_for_item_retention_decision(self, item_id: str) -> bool:
        if (
            not self.has_item_played_audio(item_id)
            and not self._playback_tracking_finished
            and item_id not in self._playback_outcomes
        ):
            decision = self._item_retention_decisions.setdefault(
                item_id, asyncio.Event()
            )
            await decision.wait()
        return self.has_item_played_audio(item_id)

    def get_item_playback_outcome(self, item_id: str) -> VoicePlaybackOutcome:
        return self._playback_outcomes.get(item_id, "unknown")

    def register_item(self, item_id: str | None) -> None:
        if isinstance(item_id, str) and item_id:
            self._known_item_ids.add(item_id)

    def is_item_playback_settled(self, item_id: str) -> bool:
        return item_id in self._playback_outcomes

    async def mark_item_playback_settled(
        self, item_id: str | None, outcome: str | None, played: bool | None
    ) -> bool:
        if (
            not isinstance(item_id, str)
            or not isinstance(outcome, str)
            or outcome not in {"completed", "interrupted", "discarded"}
            or not isinstance(played, bool)
        ):
            return False
        async with self._lock:
            if (
                self._playback_tracking_finished
                or item_id not in self._known_item_ids
                or item_id in self._playback_outcomes
                or (played and item_id not in self._items_with_audio)
                or (not played and self.has_item_played_audio(item_id))
                or (outcome == "completed" and not played)
                or (
                    outcome == "completed"
                    and item_id not in self._generation_done_item_ids
                )
                or (outcome == "discarded" and played)
            ):
                return False
            self._playback_outcomes[item_id] = cast(VoicePlaybackOutcome, outcome)
            self._playback_events_by_item_id.pop(item_id, None)
            if played:
                self._played_item_ids.add(item_id)
                self._retention_decided.set()
            decision = self._item_retention_decisions.pop(item_id, None)
            if decision is not None:
                decision.set()
            browser_connection_logger.debug(
                "Confirmed browser playback settled item_id=%s outcome=%s played=%s.",
                sanitize_for_log(item_id, max_len=256),
                sanitize_for_log(outcome),
                sanitize_for_log(played),
            )
            return True

    def finish_playback_tracking(self) -> None:
        # Stop the browser reader first: absent playback is now a final decision.
        self._playback_tracking_finished = True
        self._playback_events_by_item_id.clear()
        self._retention_decided.set()
        for decision in self._item_retention_decisions.values():
            decision.set()
        self._item_retention_decisions.clear()

    async def add_audio_delta(
        self,
        item_id: str | None,
        event_id: str | None,
        audio_bytes: bytes | None,
    ) -> None:
        if not item_id or audio_bytes is None:
            return

        sample_count = len(audio_bytes) // self._BYTES_PER_FRAME
        async with self._lock:
            item_sample_count = (
                self._sample_counts_by_item_id.get(item_id, 0) + sample_count
            )
            self._sample_counts_by_item_id[item_id] = item_sample_count
            if event_id:
                self._event_end_sample_counts_by_item_id.setdefault(item_id, {})[
                    event_id
                ] = item_sample_count
                if sample_count > 0:
                    self.register_item(item_id)
                    self._items_with_audio.add(item_id)
                    self._playback_events_by_item_id.setdefault(item_id, {}).setdefault(
                        event_id, _AssistantAudioPlaybackEvent()
                    )
            browser_connection_logger.debug(
                "Tracked realtime assistant audio delta item_id=%s event_id=%s "
                "delta_samples=%s total_duration_ms=%s.",
                sanitize_for_log(item_id, max_len=256),
                sanitize_for_log(str(event_id), max_len=256),
                sanitize_for_log(str(sample_count)),
                sanitize_for_log(
                    str(self._duration_ms_for_sample_count(item_sample_count))
                ),
            )

    async def mark_audio_event_playback_started(
        self, item_id: str | None, event_id: str | None
    ) -> bool:
        if (
            not isinstance(item_id, str)
            or not isinstance(event_id, str)
            or not item_id
            or not event_id
        ):
            return False

        async with self._lock:
            return self._mark_playback_event(item_id, event_id, ended=False)

    async def mark_audio_event_playback_ended(
        self, item_id: str | None, event_id: str | None
    ) -> bool:
        if (
            not isinstance(item_id, str)
            or not isinstance(event_id, str)
            or not item_id
            or not event_id
        ):
            return False

        async with self._lock:
            accepted = self._mark_playback_event(item_id, event_id, ended=True)
            event_sample_counts = self._event_end_sample_counts_by_item_id.get(item_id)
            if event_sample_counts is None:
                return accepted

            event_sample_counts.pop(event_id, None)
            if event_sample_counts:
                return accepted

            self._event_end_sample_counts_by_item_id.pop(item_id, None)
            self._forget_item_if_audio_is_done(item_id)
            return accepted

    def _mark_playback_event(self, item_id: str, event_id: str, *, ended: bool) -> bool:
        # Called under _lock. Keep pending callbacks independent of duration
        # cleanup: browser telemetry may arrive after generation or truncation.
        if self._playback_tracking_finished or item_id in self._playback_outcomes:
            return False
        events = self._playback_events_by_item_id.get(item_id)
        event = events.get(event_id) if events is not None else None
        if event is None:
            return False
        if ended:
            if event.ended:
                return False
            event.ended = True
        else:
            if event.started:
                return False
            event.started = True
        self._played_item_ids.add(item_id)
        self._retention_decided.set()
        decision = self._item_retention_decisions.pop(item_id, None)
        if decision is not None:
            decision.set()
        if event.started and event.ended:
            del self._playback_events_by_item_id[item_id][event_id]
            if not self._playback_events_by_item_id[item_id]:
                del self._playback_events_by_item_id[item_id]
        return True

    async def mark_item_audio_done(self, item_id: str | None) -> None:
        if not item_id:
            return

        async with self._lock:
            self._generation_done_item_ids.add(item_id)
            self._audio_done_item_ids.add(item_id)
            self._forget_item_if_audio_is_done(item_id)

    async def forget_item(self, item_id: str | None) -> None:
        if not item_id:
            return

        async with self._lock:
            self._forget_item(item_id)

    async def clamp_truncate_audio_end_ms(
        self, item_id: str, requested_audio_end_ms: int, event_id: str | None = None
    ) -> int:
        sanitized_item_id = sanitize_for_log(item_id, max_len=256)
        sanitized_event_id = sanitize_for_log(str(event_id), max_len=256)
        event_sample_count: int | None = None
        async with self._lock:
            sample_count = self._sample_counts_by_item_id.get(item_id)
            if event_id:
                event_sample_count = self._event_end_sample_counts_by_item_id.get(
                    item_id, {}
                ).get(event_id)
                if event_sample_count is not None:
                    sample_count = event_sample_count

        if sample_count is None:
            browser_connection_logger.warning(
                "Received truncate for assistant item_id %s before any tracked audio duration.",
                sanitized_item_id,
            )
            return requested_audio_end_ms

        if event_id and event_sample_count is None:
            browser_connection_logger.warning(
                "Realtime truncate event_id=%s for item_id=%s had no tracked event boundary; "
                "falling back to item duration.",
                sanitized_event_id,
                sanitized_item_id,
            )

        generated_duration_ms = self._duration_ms_for_sample_count(sample_count)
        if requested_audio_end_ms <= generated_duration_ms:
            browser_connection_logger.debug(
                "Realtime truncate did not require clamping item_id=%s event_id=%s "
                "requested_audio_end_ms=%s generated_duration_ms=%s.",
                sanitized_item_id,
                sanitized_event_id,
                sanitize_for_log(str(requested_audio_end_ms)),
                sanitize_for_log(str(generated_duration_ms)),
            )
            return requested_audio_end_ms

        browser_connection_logger.warning(
            "Clamping realtime truncate audio_end_ms for item_id %s from %s to %s.",
            sanitized_item_id,
            sanitize_for_log(str(requested_audio_end_ms)),
            sanitize_for_log(str(generated_duration_ms)),
        )
        return generated_duration_ms

    @staticmethod
    def _duration_ms_for_sample_count(sample_count: int) -> int:
        return (sample_count * 1000) // AUDIO_FRAME_RATE

    def _forget_item_if_audio_is_done(self, item_id: str) -> None:
        if item_id not in self._audio_done_item_ids:
            return
        if self._event_end_sample_counts_by_item_id.get(item_id):
            return

        self._forget_item(item_id)

    def _forget_item(self, item_id: str) -> None:
        self._sample_counts_by_item_id.pop(item_id, None)
        self._event_end_sample_counts_by_item_id.pop(item_id, None)
        self._audio_done_item_ids.discard(item_id)


class ConversationItemOrderingBuffer:
    """Tracks conversation chain items and returns ready transcripts in order."""

    _UNSET_PREVIOUS_ITEM_ID = UNSET_PREVIOUS_ITEM_ID

    def __init__(
        self,
        logger: logging.Logger,
        initial_output_index: int = 0,
        assistant_audio_tracker: RealtimeAssistantAudioTracker | None = None,
    ):
        self._logger = logger
        self.assistant_audio_tracker = assistant_audio_tracker
        self.items_by_id: dict[str, ConversationChainItem] = {}
        self.children_by_previous_item_id: dict[str, set[str]] = {}
        self.ready_item_heap: list[tuple[int, str]] = []
        self.queued_ready_item_ids: set[str] = set()
        self.pruned_saved_item_ids: set[str] = set()
        self.failed_transcription_item_ids: set[str] = set()
        self.incomplete_transcription_item_ids: set[str] = set()
        self.next_conversation_order = 0
        self.next_output_index = max(0, initial_output_index)

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
        if item_id in self.pruned_saved_item_ids:
            self._logger.warning(
                "Received conversation.item.added for already-saved item_id %s. Ignoring duplicate.",
                item_id,
            )
            return

        item = self._get_item(item_id=item_id)
        if item is None:
            item = ConversationChainItem(
                item_id=item_id,
                conversation_order=self.next_conversation_order,
            )
            self.next_conversation_order += 1
            self.items_by_id[item_id] = item
        elif item.previous_item_id == self._UNSET_PREVIOUS_ITEM_ID:
            item.conversation_order = self.next_conversation_order
            self.next_conversation_order += 1
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
        if item_id in self.pruned_saved_item_ids:
            self._logger.warning(
                "Received transcript for already-saved item_id %s. Ignoring duplicate.",
                item_id,
            )
            return

        item = self._get_or_create_transcript_item(item_id)

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
        if item_id in self.pruned_saved_item_ids:
            self._logger.warning(
                "Received transcription delta for already-saved item_id %s. Ignoring.",
                item_id,
            )
            return

        item = self._get_or_create_transcript_item(item_id)

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

    def has_completed_transcription(self, item_id: str) -> bool:
        item = self._get_item(item_id)
        return item_id in self.pruned_saved_item_ids or bool(
            item and item.is_transcription_complete
        )

    def fail_transcription(self, item_id: str) -> None:
        if item_id in self.pruned_saved_item_ids:
            return
        item = self._get_or_create_transcript_item(item_id)
        if item.is_transcription_complete:
            return
        self.failed_transcription_item_ids.add(item_id)
        # A failed attempt is terminal for ordering, even without any text.
        # Preserve deltas already received instead of blocking its descendants.
        self.register_transcription(item_id, item.transcription_text or "", "user")

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
            if item.skip_persistence:
                item.is_message_saved = True
                self._mark_item_and_descendants_for_readiness(item.item_id)
                self._prune_saved_items()
                continue
            if item.transcription_text is None or item.role is None:
                continue
            if not _has_non_empty_transcript(item.transcription_text):
                self._logger.warning(
                    "Skipping realtime transcript with empty content for item_id %s.",
                    item.item_id,
                )
                item.is_message_saved = True
                self._mark_item_and_descendants_for_readiness(item.item_id)
                self._prune_saved_items()
                continue
            output_index = str(self.next_output_index)
            self.next_output_index += 1
            item.is_message_saved = True
            self._mark_item_and_descendants_for_readiness(item.item_id)
            self._prune_saved_items()
            return item.item_id, item.transcription_text, item.role, output_index

        return None

    def discard_unheard_assistant_transcripts(self, item_id: str | None = None) -> None:
        if self.assistant_audio_tracker is None:
            return
        for item in self.items_by_id.values():
            if item_id is not None and item.item_id != item_id:
                continue
            if item.role == "assistant" and not (
                self.assistant_audio_tracker.has_item_played_audio(item.item_id)
            ):
                # This is terminal for ordering even if transcript.done never
                # arrived. Keep predecessor checks so unknown links fail closed.
                item.skip_persistence = True
                self._mark_item_and_descendants_for_readiness(item.item_id)

    def finalize_pending_transcriptions(self) -> None:
        # Call only after provider/browser producers stop. Recover known turns
        # without inventing text or repairing unknown predecessor relationships.
        for item in list(self.items_by_id.values()):
            if (
                item.is_message_saved
                or item.is_transcription_complete
                or item.skip_persistence
                or item.role not in {"user", "assistant"}
                or item.previous_item_id == self._UNSET_PREVIOUS_ITEM_ID
            ):
                continue
            if _has_non_empty_transcript(item.transcription_text):
                self.incomplete_transcription_item_ids.add(item.item_id)
            self.register_transcription(
                item.item_id, item.transcription_text or "", item.role
            )

    def has_pending_retained_items(self, heard_item_ids: frozenset[str]) -> bool:
        retained_item_ids = set(heard_item_ids)
        retained_item_ids.update(
            item.item_id for item in self.items_by_id.values() if item.role == "user"
        )
        for item_id in retained_item_ids:
            if item_id in self.pruned_saved_item_ids:
                continue
            item = self.items_by_id.get(item_id)
            if item is None or (
                not item.skip_persistence and not item.is_transcription_complete
            ):
                return True
            # Unheard assistant ancestors need their ordering links, not text.
            seen: set[str] = set()
            current_item_id: str | None = item_id
            while (
                current_item_id is not None
                and current_item_id not in self.pruned_saved_item_ids
            ):
                if current_item_id in seen:
                    return True
                seen.add(current_item_id)
                item = self.items_by_id.get(current_item_id)
                if (
                    item is None
                    or item.previous_item_id == self._UNSET_PREVIOUS_ITEM_ID
                ):
                    return True
                current_item_id = item.previous_item_id
        return False

    def _get_item(self, item_id: str) -> ConversationChainItem | None:
        return self.items_by_id.get(item_id)

    def _get_or_create_transcript_item(self, item_id: str) -> ConversationChainItem:
        item = self._get_item(item_id)
        if item is None:
            # Keep early text, but leave the predecessor unresolved so it cannot
            # dispatch until conversation.item.added supplies its chain position.
            item = ConversationChainItem(item_id=item_id)
            self.items_by_id[item_id] = item
        return item

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
        # This is an O(size_of_subtree) walk by design. The conversation chain is
        # expected to stay small in practice, and this keeps readiness updates simple
        # when late predecessor links or completion events arrive out of order.
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

        # Defensive cycle guard: realtime events can be out-of-order or malformed,
        # so a bad previous_item_id chain must fail closed instead of looping forever.
        seen_item_ids = {item.item_id}
        previous_item_id = item.previous_item_id

        while previous_item_id is not None:
            if previous_item_id in seen_item_ids:
                return False, None

            previous_item = self._get_item(previous_item_id)
            if previous_item is None:
                if previous_item_id in self.pruned_saved_item_ids:
                    return True, None
                return False, None
            if previous_item.has_transcription:
                return True, previous_item

            if previous_item.previous_item_id == self._UNSET_PREVIOUS_ITEM_ID:
                return False, None
            seen_item_ids.add(previous_item_id)
            previous_item_id = previous_item.previous_item_id

        return True, None

    def _prune_saved_items(self) -> None:
        stale_saved_item_ids = [
            item_id
            for item_id, item in self.items_by_id.items()
            if item.is_message_saved
        ]
        for stale_item_id in stale_saved_item_ids:
            self.items_by_id.pop(stale_item_id, None)
            self.pruned_saved_item_ids.add(stale_item_id)

    def _is_item_ready_to_dispatch(self, item: ConversationChainItem) -> bool:
        if item.role not in {"user", "assistant"}:
            return False
        if not item.has_transcription:
            return False
        if item.is_message_saved:
            return False
        if not item.is_transcription_complete and not item.skip_persistence:
            return False
        if item.transcription_text is None and not item.skip_persistence:
            return False

        is_resolved, previous_relevant_item = self._resolve_previous_relevant_item(item)
        if not is_resolved:
            return False
        if previous_relevant_item is not None and not self._is_message_saved(
            previous_relevant_item
        ):
            return False

        return True


def _new_voice_run(browser_connection: StateWebSocket, thread: Thread) -> Run:
    assistant = (
        browser_connection.state["assistant"]
        if "assistant" in browser_connection.state
        else None
    )
    return Run(
        status=schemas.RunStatus.IN_PROGRESS,
        thread_id=thread.id,
        assistant_id=thread.assistant_id,
        model=getattr(assistant, "model", None),
        reasoning_effort=getattr(assistant, "reasoning_effort", None),
        verbosity=getattr(assistant, "verbosity", None),
        temperature=getattr(assistant, "temperature", None),
        tools_available=thread.tools_available,
        creator_id=browser_connection.state["session"].user.id,
    )


def retain_voice_startup_failure(
    browser_connection: StateWebSocket, thread: Thread, error: Exception
) -> None:
    # Snapshot attributes before rollback expires the session's ORM objects.
    run = _new_voice_run(browser_connection, thread)
    usage = RealtimeUsage()
    code = getattr(error, "code", None) or "provider_startup_error"
    usage.fail(code, str(error))
    usage.record_exception(error, code=code)
    run.status = usage.final_status
    run.error_code = usage.error_code
    run.error_message = usage.error_message
    run.completed = func.now()
    run.provider_metadata = usage.provider_metadata_to_json()

    async def save_after_rollback() -> None:
        # Release the original transaction's thread lock before inserting a run
        # in a separate transaction that survives the startup failure.
        async with config.db.driver.async_session() as session:
            session.add(run)
            await session.commit()

    browser_connection.state["after_db_rollback"].append(save_after_rollback)


async def save_voice_usage(
    browser_connection: StateWebSocket, thread: Thread, usage: RealtimeUsage
) -> None:
    run_id = browser_connection.state._state.get("voice_mode_run_id")
    if not usage.has_records and run_id is None:
        return
    session = browser_connection.state["db"]
    thread_id = None
    try:
        thread_id = thread.id
        # Producers and the transcript writer must stop first: this shares
        # their DB session, but usage is independent of playback qualification.
        async with session.begin_nested():
            run = await Run.get_by_id(session, run_id) if run_id is not None else None
            if run is None or run.thread_id != thread_id:
                run = _new_voice_run(browser_connection, thread)
                session.add(run)
            if usage.session_id is not None:
                run.run_id = usage.session_id
            run.status = usage.final_status
            run.error_code = usage.error_code
            run.error_message = usage.error_message
            run.incomplete_reason = (
                usage.incomplete_reason
                if run.status == schemas.RunStatus.INCOMPLETE
                else None
            )
            run.completed = func.now()
            run.usage = usage.to_json()
            run.provider_metadata = usage.provider_metadata_to_json()
            await session.flush()
        browser_connection.state["voice_mode_run_id"] = run.id
    except Exception:
        openai_connection_logger.exception(
            "Failed to save voice usage for thread_id=%s.", thread_id
        )
        # Preserve earlier transcript writes after a failed usage savepoint.
        try:
            await session.refresh(thread)
        except Exception:
            openai_connection_logger.exception(
                "Failed to reload thread after voice usage save failure."
            )
        if run_id is not None:
            try:
                async with session.begin_nested():
                    run = await Run.get_by_id(session, run_id)
                    if run is not None and run.thread_id == thread_id:
                        # Keep a failed accounting payload out of this fallback.
                        run.status = (
                            schemas.RunStatus.FAILED
                            if usage.error_code is not None
                            else schemas.RunStatus.INCOMPLETE
                        )
                        run.error_code = usage.error_code
                        run.error_message = usage.error_message
                        run.incomplete_reason = (
                            usage.incomplete_reason or "usage_save_failed"
                            if run.status == schemas.RunStatus.INCOMPLETE
                            else None
                        )
                        run.completed = func.now()
                        await session.flush()
            except Exception:
                openai_connection_logger.exception(
                    "Failed to finalize voice run after usage save failure."
                )


async def add_message_to_thread(
    openai_client: OpenAIClientType,
    browser_connection: StateWebSocket,
    thread: Thread,
    item_id: str,
    transcript_text: str,
    role: ConversationRole,
    realtime_recorder: RealtimeRecorder | None = None,
    output_index: str | None = None,
    transcription_failed: bool = False,
    playback_outcome: VoicePlaybackOutcome | None = None,
    transcription_incomplete: bool = False,
) -> bool:
    is_user_message = role == "user"
    message_saved = False

    if not _has_non_empty_transcript(transcript_text):
        openai_connection_logger.warning(
            "Skipping realtime message with empty transcript content: item_id=%s, role=%s, output_index=%s",
            item_id,
            role,
            output_index,
        )
        return False

    message_metadata: dict[str, str | bool] = {}
    if transcription_failed:
        message_metadata["voice_transcription_failed"] = True
    if transcription_incomplete:
        message_metadata["voice_transcript_incomplete"] = True
    if not is_user_message and playback_outcome is not None:
        message_metadata["voice_playback_outcome"] = playback_outcome

    if thread.version == 3:
        session = browser_connection.state["db"]
        try:
            # Keep the run, message text and user counter atomic without rolling
            # back transcripts already written by this session.
            async with session.begin_nested():
                existing_message_run_id = await session.scalar(
                    select(Message.run_id).where(
                        Message.thread_id == thread.id, Message.message_id == item_id
                    )
                )
                if existing_message_run_id is not None:
                    browser_connection.state["voice_mode_run_id"] = (
                        existing_message_run_id
                    )
                    return True
                existing_run_id = (
                    browser_connection.state["voice_mode_run_id"]
                    if "voice_mode_run_id" in browser_connection.state
                    else None
                )
                run = None
                if existing_run_id is not None:
                    run = await Run.get_by_id(
                        browser_connection.state["db"], int(existing_run_id)
                    )
                    if run and run.thread_id != thread.id:
                        run = None

                if run is None:
                    run = _new_voice_run(browser_connection, thread)
                    browser_connection.state["db"].add(run)
                    await browser_connection.state["db"].flush()
                    await browser_connection.state["db"].refresh(run)

                try:
                    output_index_int = (
                        int(output_index) if output_index is not None else None
                    )
                except (TypeError, ValueError):
                    output_index_int = None

                if output_index_int is None:
                    output_index_int = (
                        await Thread.get_max_output_sequence(
                            browser_connection.state["db"], thread.id
                        )
                        + 1
                    )

                message = await Message.create(
                    browser_connection.state["db"],
                    {
                        "message_id": item_id,
                        "message_status": schemas.MessageStatus.INCOMPLETE
                        if transcription_failed or transcription_incomplete
                        else schemas.MessageStatus.COMPLETED,
                        "message_metadata": message_metadata or None,
                        "run_id": run.id,
                        "thread_id": thread.id,
                        "assistant_id": thread.assistant_id
                        if not is_user_message
                        else None,
                        "output_index": output_index_int,
                        "role": (
                            schemas.MessageRole.USER
                            if is_user_message
                            else schemas.MessageRole.ASSISTANT
                        ),
                        "user_id": (
                            browser_connection.state["session"].user.id
                            if is_user_message
                            else None
                        ),
                        "completed": func.now(),
                    },
                )
                await MessagePart.create(
                    browser_connection.state["db"],
                    {
                        "message_id": message.id,
                        "part_index": 0,
                        "type": (
                            schemas.MessagePartType.INPUT_TEXT
                            if is_user_message
                            else schemas.MessagePartType.OUTPUT_TEXT
                        ),
                        "text": transcript_text,
                    },
                )
                if is_user_message:
                    thread.user_message_ct += 1
                    thread.last_activity = func.now()
                    session.add(thread)
                    await session.flush()
                    await session.refresh(thread)
            # Publish the run ID only after its savepoint succeeds.
            browser_connection.state["voice_mode_run_id"] = run.id
            message_saved = True
        except Exception as e:
            openai_connection_logger.exception(
                f"Failed to save Version 3 realtime transcript: {e}, item_id={item_id}, role={role}"
            )
            # A savepoint rollback expires modified ORM state. Reload explicitly
            # so later queued writes do not attempt implicit async database IO.
            try:
                await session.refresh(thread)
            except Exception:
                openai_connection_logger.exception(
                    "Failed to reload thread after realtime transcript rollback."
                )
            return False
    elif thread.version <= 2:
        try:
            metadata = {
                "item_id": item_id,
            }
            if transcription_failed:
                metadata["voice_transcription_failed"] = "true"
            if transcription_incomplete:
                metadata["voice_transcript_incomplete"] = "true"
            if not is_user_message and playback_outcome is not None:
                metadata["voice_playback_outcome"] = playback_outcome
            if output_index is not None:
                metadata["output_index"] = str(output_index)
            if is_user_message:
                metadata["user_id"] = str(browser_connection.state["session"].user.id)

            if browser_connection.state["anonymous_share_token"] is not None:
                metadata["share_token"] = str(
                    browser_connection.state["anonymous_share_token"]
                )
            if browser_connection.state["anonymous_session_token"] is not None:
                metadata["anonymous_session_token"] = str(
                    browser_connection.state["anonymous_session_token"]
                )

            await openai_client.beta.threads.messages.create(
                thread_id=thread.thread_id,
                role=role,
                content=transcript_text,
                metadata=metadata,
            )
            message_saved = True
        except OpenAIError as e:
            openai_connection_logger.exception(
                f"Failed to send message to OpenAI: {e}, item_id={item_id}, role={role}"
            )
            return False
    else:
        openai_connection_logger.error(
            "Unsupported thread version %s for realtime transcript persistence.",
            thread.version,
        )
        return False

    if not message_saved:
        return False

    if is_user_message and thread.version <= 2:
        try:
            thread.user_message_ct += 1
            thread.last_activity = func.now()

            browser_connection.state["db"].add(thread)
            await browser_connection.state["db"].flush()
            await browser_connection.state["db"].refresh(thread)
        except Exception as e:
            openai_connection_logger.exception(
                f"Failed to update thread in database: {e}"
            )
    return True


async def update_message_playback_outcome(
    browser_connection: StateWebSocket,
    thread: Thread,
    item_id: str,
    playback_outcome: VoicePlaybackOutcome,
) -> None:
    if thread.version != 3 or playback_outcome not in {"completed", "interrupted"}:
        return
    session = browser_connection.state["db"]
    try:
        async with session.begin_nested():
            message = await session.scalar(
                select(Message).where(
                    Message.thread_id == thread.id,
                    Message.message_id == item_id,
                    Message.role == schemas.MessageRole.ASSISTANT,
                )
            )
            if message is None:
                return
            metadata = dict(message.message_metadata or {})
            if metadata.get("voice_playback_outcome") == playback_outcome:
                return
            message.message_metadata = {
                **metadata,
                "voice_playback_outcome": playback_outcome,
            }
            await session.flush()
    except Exception:
        openai_connection_logger.exception(
            "Failed to update realtime playback metadata item_id=%s.",
            sanitize_for_log(item_id, max_len=256),
        )


async def enqueue_ready_thread_message_tasks(
    ordering_buffer: ConversationItemOrderingBuffer,
    openai_task_queue: asyncio.Queue,
    openai_client: OpenAIClientType,
    browser_connection: StateWebSocket,
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
            playback_outcome: VoicePlaybackOutcome | None = None
            if (
                role == "assistant"
                and ordering_buffer.assistant_audio_tracker is not None
            ):
                if not await ordering_buffer.assistant_audio_tracker.wait_for_item_retention_decision(
                    item_id
                ):
                    return
                playback_outcome = (
                    ordering_buffer.assistant_audio_tracker.get_item_playback_outcome(
                        item_id
                    )
                )
            # Retry in place so later writes cannot overtake this item. Classic
            # provider-side writes have no local idempotency guarantee.
            max_attempts = 2 if thread.version == 3 else 1
            for attempt in range(max_attempts):
                saved = await add_message_to_thread(
                    openai_client,
                    browser_connection,
                    thread,
                    item_id,
                    transcript_text,
                    role,
                    realtime_recorder=realtime_recorder,
                    output_index=output_index,
                    transcription_failed=item_id
                    in ordering_buffer.failed_transcription_item_ids,
                    playback_outcome=playback_outcome,
                    transcription_incomplete=item_id
                    in ordering_buffer.incomplete_transcription_item_ids,
                )
                if saved:
                    return
                if attempt + 1 < max_attempts:
                    if not browser_connection.state["db"].is_active:
                        return
                    openai_connection_logger.warning(
                        "Retrying Version 3 realtime transcript write for item_id=%s.",
                        item_id,
                    )

        await openai_task_queue.put(task)


async def _close_browser_connection(browser_connection: StateWebSocket) -> None:
    try:
        if (
            getattr(browser_connection, "application_state", None)
            != WebSocketState.DISCONNECTED
        ):
            await browser_connection.close()
    except (WebSocketDisconnect, ClientDisconnect, OSError):
        browser_connection_logger.debug("Browser disconnected during close.")


async def handle_browser_messages(
    browser_connection: StateWebSocket,
    realtime_connection: AsyncRealtimeConnection,
    assistant_audio_tracker: RealtimeAssistantAudioTracker,
    realtime_recorder: RealtimeRecorder | None = None,
    *,
    close_on_cancel: bool = True,
    on_playback_settled: Callable[[str], Awaitable[None]] | None = None,
    session_expiry: RealtimeSessionExpiry | None = None,
    on_session_stop: Callable[[], None] | None = None,
    provider_unavailable: asyncio.Event | None = None,
):
    async def send_to_provider(operation: Callable[[], Awaitable[None]]) -> bool:
        if provider_unavailable is not None and provider_unavailable.is_set():
            return False
        try:
            await operation()
            return True
        except REALTIME_CONNECTION_ERRORS:
            if provider_unavailable is None:
                raise
            provider_unavailable.set()
            if session_expiry is not None:
                session_expiry.stopping = True
            openai_connection_logger.warning(
                "Provider connection closed while forwarding browser audio.",
                exc_info=True,
            )
            return False

    try:
        while True:
            message = await browser_connection.receive()
            browser_connection._raise_on_disconnect(message)
            if "text" in message:
                try:
                    data = json.loads(message["text"])
                    type = data.get("type")
                    if type == "session.stop":
                        if on_session_stop is not None:
                            on_session_stop()
                        return
                    if not type:
                        browser_connection_logger.exception(
                            "Received unexpected message: %s",
                            sanitize_for_log(
                                json.dumps(data, sort_keys=True), max_len=512
                            ),
                        )
                    elif type == "conversation.item.truncate":
                        item_id = data.get("item_id")
                        event_id = data.get("event_id")
                        audio_end_ms = data.get("audio_end_ms")
                        if item_id is None or audio_end_ms is None:
                            browser_connection_logger.exception(
                                "Received conversation.item.truncate message without item_id or audio_end_ms"
                            )
                            continue
                        if event_id is not None and not isinstance(event_id, str):
                            browser_connection_logger.warning(
                                "Received conversation.item.truncate message with invalid event_id: %s",
                                sanitize_for_log(
                                    json.dumps(data, sort_keys=True), max_len=512
                                ),
                            )
                            event_id = None
                        if not isinstance(audio_end_ms, int) or isinstance(
                            audio_end_ms, bool
                        ):
                            browser_connection_logger.warning(
                                "Received conversation.item.truncate message with invalid audio_end_ms: %s",
                                sanitize_for_log(
                                    json.dumps(data, sort_keys=True), max_len=512
                                ),
                            )
                            continue
                        requested_audio_end_ms = audio_end_ms
                        audio_end_ms = max(
                            0,
                            await assistant_audio_tracker.clamp_truncate_audio_end_ms(
                                item_id=item_id,
                                event_id=event_id,
                                requested_audio_end_ms=audio_end_ms,
                            ),
                        )
                        browser_connection_logger.debug(
                            "Applying browser truncate item_id=%s event_id=%s "
                            "requested_audio_end_ms=%s forwarded_audio_end_ms=%s.",
                            sanitize_for_log(item_id, max_len=256),
                            sanitize_for_log(str(event_id), max_len=256),
                            sanitize_for_log(str(requested_audio_end_ms)),
                            sanitize_for_log(str(audio_end_ms)),
                        )
                        # Truncate the audio buffer for the specified item
                        # NOTE: This does not impact the transcription process,
                        # which might affect the quality of the transcription.
                        await send_to_provider(
                            lambda: realtime_connection.conversation.item.truncate(
                                audio_end_ms=audio_end_ms,
                                content_index=0,
                                item_id=item_id,
                            )
                        )
                        await assistant_audio_tracker.forget_item(item_id)
                        if realtime_recorder:
                            await realtime_recorder.stopped_playing_assistant_response(
                                item_id=item_id,
                                final_duration_ms=audio_end_ms,
                            )
                    elif type == "response.audio.playback.settled":
                        item_id = data.get("item_id")
                        if await assistant_audio_tracker.mark_item_playback_settled(
                            item_id, data.get("outcome"), data.get("played")
                        ):
                            if on_playback_settled is not None:
                                await on_playback_settled(item_id)
                    elif type == "response.audio.delta.started":
                        item_id = data.get("item_id")
                        event_id = data.get("event_id")
                        started_playing_at_ms = data.get("started_playing_at")
                        if (
                            not isinstance(item_id, str)
                            or not isinstance(event_id, str)
                            or not item_id
                            or not event_id
                            or not isinstance(started_playing_at_ms, int)
                            or isinstance(started_playing_at_ms, bool)
                            or started_playing_at_ms < 0
                        ):
                            browser_connection_logger.warning(
                                "Received invalid response.audio.delta.started metadata."
                            )
                            continue
                        if assistant_audio_tracker.is_item_playback_settled(item_id):
                            continue
                        await assistant_audio_tracker.mark_audio_event_playback_started(
                            item_id, event_id
                        )
                        if realtime_recorder:
                            await realtime_recorder.started_playing_assistant_response_delta(
                                item_id=item_id,
                                event_id=event_id,
                                started_playing_at_ms=started_playing_at_ms,
                            )
                    elif type == "response.audio.delta.ended":
                        item_id = data.get("item_id")
                        event_id = data.get("event_id")
                        if (
                            not isinstance(item_id, str)
                            or not isinstance(event_id, str)
                            or not item_id
                            or not event_id
                        ):
                            browser_connection_logger.warning(
                                "Received response.audio.delta.ended message with invalid item_id or event_id: %s",
                                sanitize_for_log(
                                    json.dumps(data, sort_keys=True), max_len=512
                                ),
                            )
                            continue
                        if isinstance(
                            item_id, str
                        ) and assistant_audio_tracker.is_item_playback_settled(item_id):
                            continue
                        await assistant_audio_tracker.mark_audio_event_playback_ended(
                            item_id=item_id,
                            event_id=event_id,
                        )
                        if not realtime_recorder:
                            continue
                        await realtime_recorder.ended_playing_assistant_response_delta(
                            item_id=item_id,
                            event_id=event_id,
                        )

                except json.JSONDecodeError as e:
                    browser_connection_logger.exception(
                        f"Failed to decode unexpected message JSON: {e}"
                    )
            elif "bytes" in message:
                if session_expiry is not None and session_expiry.stopping:
                    continue
                buffer = message["bytes"]

                timestamp_size = 8
                if len(buffer) >= timestamp_size:
                    timestamp = struct.unpack(">d", buffer[:8])[0]
                    audio_chunk = buffer[8:]
                    sent = await send_to_provider(
                        lambda: realtime_connection.input_audio_buffer.append(
                            audio=base64.b64encode(cast(bytes, audio_chunk)).decode(
                                "utf-8"
                            )
                        )
                    )
                    if sent and realtime_recorder:
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
                    "Received unexpected message: %s",
                    sanitize_for_log(str(message), max_len=512),
                )

    except WebSocketDisconnect:
        browser_connection_logger.debug("Browser closed the websocket connection.")
    except (asyncio.CancelledError, ClientDisconnect):
        browser_connection_logger.debug("Browser message reader was cancelled.")
        if close_on_cancel:
            await _close_browser_connection(browser_connection)
        raise


async def handle_openai_events(
    browser_connection: StateWebSocket,
    realtime_connection: AsyncRealtimeConnection,
    openai_client: OpenAIClientType,
    thread: Thread,
    openai_task_queue: asyncio.Queue,
    assistant_audio_tracker: RealtimeAssistantAudioTracker,
    realtime_recorder: RealtimeRecorder | None = None,
    ordering_buffer: ConversationItemOrderingBuffer | None = None,
    shutdown_drain: RealtimeShutdownDrain | None = None,
    session_expiry: RealtimeSessionExpiry | None = None,
    on_provider_end: Callable[[], None] | None = None,
):
    # Transcript savepoint rollbacks can expire the shared thread during a session.
    thread_id = getattr(thread, "id", None)
    class_id = getattr(thread, "class_id", None)
    initial_output_index = 0
    if thread.version == 3:
        try:
            initial_output_index = (
                await Thread.get_max_output_sequence(
                    browser_connection.state["db"], thread.id
                )
            ) + 1
        except Exception as e:
            openai_connection_logger.exception(
                "Failed to initialize Version 3 realtime output index for thread %s: %s",
                thread.id,
                e,
            )

    if ordering_buffer is None:
        ordering_buffer = ConversationItemOrderingBuffer(openai_connection_logger)
    ordering_buffer.next_output_index = max(0, initial_output_index)

    session_updated = False
    browser_delivery_available = True

    async def send_browser_event(data: dict, *, close: bool = False) -> None:
        nonlocal browser_delivery_available
        if not browser_delivery_available:
            return
        if (
            session_expiry is not None
            and session_expiry.stopping
            and data["type"]
            in {
                "session.updated",
                "response.audio.delta",
                "input_audio_buffer.speech_started",
            }
        ):
            return
        try:
            await browser_connection.send_json(data)
            if close:
                await browser_connection.close()
        except (WebSocketDisconnect, ClientDisconnect, OSError):
            browser_connection_logger.debug(
                "Browser disconnected; disabling provider event delivery."
            )
        except RuntimeError:
            # Starlette also raises RuntimeError when a concurrent close has
            # already changed the websocket state. Preserve unrelated failures.
            if (
                getattr(browser_connection, "application_state", None)
                != WebSocketState.DISCONNECTED
                and getattr(browser_connection, "client_state", None)
                != WebSocketState.DISCONNECTED
            ):
                raise
            browser_connection_logger.debug(
                "Browser websocket already closed; disabling provider event delivery."
            )
        else:
            return
        browser_delivery_available = False

    try:
        async for event in realtime_connection:
            if shutdown_drain is not None:
                # Keep received usage even if cancellation interrupts a delivery
                # await below. The post-handling observation is idempotent.
                shutdown_drain.usage.observe(event)
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
                    if role == "assistant":
                        assistant_audio_tracker.register_item(getattr(item, "id", None))
                    await enqueue_ready_thread_message_tasks(
                        ordering_buffer=ordering_buffer,
                        openai_task_queue=openai_task_queue,
                        openai_client=openai_client,
                        browser_connection=browser_connection,
                        thread=thread,
                        realtime_recorder=realtime_recorder,
                    )
                case "response.output_audio_transcript.done":
                    if ordering_buffer.has_completed_transcription(event.item_id):
                        continue
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
                    if assistant_audio_tracker.is_item_playback_settled(
                        event.item_id
                    ) and not assistant_audio_tracker.has_item_played_audio(
                        event.item_id
                    ):
                        continue
                    ordering_buffer.register_transcription_delta(
                        event.item_id, event.delta, "assistant"
                    )
                case "session.created":
                    if session_expiry is not None:
                        session_expiry.observe(event.session)
                    openai_connection_logger.debug(
                        f"Session successfully created: {event.session}"
                    )
                case "session.updated":
                    if session_expiry is not None:
                        session_expiry.observe(event.session)
                    openai_connection_logger.debug(
                        f"Session successfully updated: {event.session}"
                    )
                    session_updated = True
                    if shutdown_drain is None or not shutdown_drain.stopping:
                        await send_browser_event(
                            {
                                "type": "session.updated",
                                "message": "Connected to OpenAI.",
                            }
                        )
                case "session.error" | "error":
                    if shutdown_drain and shutdown_drain.is_finished_cancellation_error(
                        event.error
                    ):
                        openai_connection_logger.debug(
                            "Shutdown cancellation arrived after the response finished."
                        )
                    else:
                        if shutdown_drain is not None:
                            shutdown_drain.usage.record_error(event)
                        openai_connection_logger.exception(
                            f"Session error: {event.error}"
                        )
                    # A rejected command does not end an established session,
                    # even when error.param identifies a session setting.
                    if not session_updated and not (
                        (shutdown_drain and shutdown_drain.stopping)
                        or (session_expiry and session_expiry.stopping)
                    ):
                        if shutdown_drain is not None:
                            shutdown_drain.usage.fail(
                                getattr(event.error, "code", None)
                                or getattr(event.error, "type", None)
                                or "provider_session_error",
                                getattr(event.error, "message", None)
                                or "The provider ended the voice session with an error.",
                            )
                        await send_browser_event(
                            {
                                "type": "error",
                                "error": _serialize_realtime_error(event.error),
                            },
                            close=True,
                        )
                        return
                case "session.ended":
                    openai_connection_logger.debug(f"Session ended: {event.session}")
                    if on_provider_end is not None:
                        on_provider_end()
                        continue
                    await send_browser_event(
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
                case "conversation.item.input_audio_transcription.failed":
                    openai_connection_logger.warning(
                        "Realtime input transcription failed for item_id=%s.",
                        event.item_id,
                    )
                    ordering_buffer.fail_transcription(event.item_id)
                    await enqueue_ready_thread_message_tasks(
                        ordering_buffer,
                        openai_task_queue,
                        openai_client,
                        browser_connection,
                        thread,
                        realtime_recorder,
                    )
                case "response.done":
                    # The final snapshot can supply text when transcript.done was
                    # missed. Replayed snapshots must not duplicate completed items.
                    registered_transcript = False
                    for item in event.response.output or []:
                        item_id = getattr(item, "id", None)
                        if (
                            not item_id
                            or getattr(item, "role", None) != "assistant"
                            or getattr(item, "type", None) != "message"
                        ):
                            continue
                        assistant_audio_tracker.register_item(item_id)
                        await assistant_audio_tracker.mark_item_audio_done(item_id)
                        await send_browser_event(
                            {"type": "response.audio.done", "item_id": item_id}
                        )
                        if ordering_buffer.has_completed_transcription(item_id):
                            continue
                        transcripts = []
                        for content in getattr(item, "content", None) or []:
                            if getattr(content, "type", None) in {
                                None,
                                "audio",
                                "output_audio",
                            }:
                                transcript = getattr(content, "transcript", None)
                                if transcript is not None:
                                    transcripts.append(transcript)
                        if transcripts:
                            transcript_text = "".join(transcripts)
                            pending_item = ordering_buffer.items_by_id.get(item_id)
                            if (
                                not _has_non_empty_transcript(transcript_text)
                                and pending_item is not None
                                and _has_non_empty_transcript(
                                    pending_item.transcription_text
                                )
                            ):
                                # A blank snapshot cannot safely replace known text.
                                continue
                            ordering_buffer.register_transcription(
                                item_id, transcript_text, "assistant"
                            )
                            registered_transcript = True
                    if registered_transcript:
                        await enqueue_ready_thread_message_tasks(
                            ordering_buffer,
                            openai_task_queue,
                            openai_client,
                            browser_connection,
                            thread,
                            realtime_recorder,
                        )
                    if getattr(event.response, "status", None) == "failed":
                        error = getattr(event.response.status_details, "error", None)
                        openai_connection_logger.error(
                            "Realtime response failed response_id=%s "
                            "error_type=%s error_code=%s error_message=%s.",
                            sanitize_for_log(event.response.id),
                            sanitize_for_log(getattr(error, "type", None)),
                            sanitize_for_log(getattr(error, "code", None)),
                            sanitize_for_log(
                                getattr(error, "message", None), max_len=512
                            ),
                        )
                        if getattr(error, "code", None) == "rate_limit_exceeded":
                            try:
                                async with config.db.driver.async_session() as session:
                                    await Class.log_rate_limit_error(
                                        session, class_id=str(class_id)
                                    )
                                    await session.commit()
                            except Exception:
                                openai_connection_logger.exception(
                                    "Failed to record realtime rate limit for thread_id=%s.",
                                    thread_id,
                                )
                        if not (
                            (shutdown_drain and shutdown_drain.stopping)
                            or (session_expiry and session_expiry.stopping)
                        ):
                            # A failed reply is recoverable, unlike a startup error.
                            await send_browser_event(
                                {
                                    "type": "error",
                                    "error": {
                                        "type": "server_error",
                                        "code": "openai_realtime_response",
                                        "message": get_ai_error_message(
                                            error,
                                            "The assistant couldn't respond. Please try speaking to continue.",
                                        ),
                                        "param": None,
                                    },
                                }
                            )
                case "response.output_audio.delta":
                    if session_expiry is not None and session_expiry.stopping:
                        continue
                    if assistant_audio_tracker.is_item_playback_settled(event.item_id):
                        continue
                    delta_audio_b64 = event.delta
                    try:
                        delta_audio_bytes = pybase64.b64decode(delta_audio_b64)
                    except (binascii.Error, TypeError, ValueError) as e:
                        openai_connection_logger.warning(
                            "Failed to decode realtime assistant audio delta: %s",
                            e,
                        )
                        continue
                    await assistant_audio_tracker.add_audio_delta(
                        item_id=event.item_id,
                        event_id=event.event_id,
                        audio_bytes=delta_audio_bytes,
                    )
                    # Register generated audio before the browser can start it
                    # and send playback telemetry back on the other task.
                    if realtime_recorder:
                        await realtime_recorder.add_assistant_response_delta(
                            audio_chunk_bytes=delta_audio_bytes,
                            event_id=event.event_id,
                            item_id=event.item_id,
                        )
                    await send_browser_event(
                        {
                            "type": "response.audio.delta",
                            "audio": delta_audio_b64,
                            "item_id": event.item_id,
                            "event_id": event.event_id,
                        }
                    )
                case "response.output_audio.done" | "response.audio.done":
                    item_id = getattr(event, "item_id", None)
                    assistant_audio_tracker.register_item(item_id)
                    await assistant_audio_tracker.mark_item_audio_done(item_id)
                    if item_id:
                        await send_browser_event(
                            {"type": "response.audio.done", "item_id": item_id}
                        )
                case "input_audio_buffer.speech_started":
                    await send_browser_event(
                        {
                            "type": "input_audio_buffer.speech_started",
                            "message": "User speech detected.",
                        }
                    )
                case (
                    "conversation.created"
                    | "conversation.item.created"
                    | "conversation.item.retrieved"
                    | "conversation.item.truncated"
                    | "conversation.item.done"
                    | "conversation.item.deleted"
                    | "input_audio_buffer.committed"
                    | "input_audio_buffer.cleared"
                    | "input_audio_buffer.speech_stopped"
                    | "response.created"
                    | "response.output_item.added"
                    | "response.output_item.done"
                    | "response.content_part.added"
                    | "response.content_part.done"
                    | "response.text.delta"
                    | "response.text.done"
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
                    pass
                case _:
                    openai_connection_logger.warning(
                        f"Ignoring unknown event type... {event.type}"
                    )
            if shutdown_drain is not None:
                shutdown_drain.observe(event)

        if shutdown_drain is not None and not shutdown_drain.is_complete(
            ordering_buffer
        ):
            shutdown_drain.usage.mark_incomplete("provider_connection_closed")

    except (asyncio.CancelledError, ClientDisconnect):
        openai_connection_logger.debug(
            "Received task cancellation signal. Closing the OpenAI connection."
        )
        raise
    except Exception as e:
        if shutdown_drain is not None:
            if isinstance(e, REALTIME_CONNECTION_ERRORS):
                if not shutdown_drain.is_complete(ordering_buffer):
                    shutdown_drain.usage.mark_incomplete("provider_connection_closed")
            else:
                shutdown_drain.usage.fail(
                    "voice_event_processing_error",
                    "An internal error interrupted voice event processing.",
                )
        openai_connection_logger.exception(f"Error handling OpenAI event: {e}")


class NamedQueue(asyncio.Queue):
    def __init__(self, name, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.name = name


async def process_queue_tasks(
    task_queue: NamedQueue,
    task_logger: logging.Logger,
    assistant_audio_tracker: RealtimeAssistantAudioTracker,
):
    try:
        while True:
            task_func = await task_queue.get()
            try:
                if await assistant_audio_tracker.wait_for_retention_decision():
                    await task_func()
            except Exception as e:
                task_logger.exception(f"Error processing {task_queue.name} task: {e}")
            finally:
                task_queue.task_done()
    except (asyncio.CancelledError, ClientDisconnect):
        task_logger.debug("Task queue processor was cancelled.")


@ws_auth_middleware
@ws_db_middleware
@ws_parse_session_token
@ws_check_realtime_permissions
@ws_with_single_realtime_session
@ws_with_openai_client
@ws_with_realtime_connection
async def browser_realtime_websocket(
    browser_connection: StateWebSocket,
    class_id: str,
    thread_id: str,
):
    realtime_connection: AsyncRealtimeConnection = browser_connection.state[
        "realtime_connection"
    ]
    openai_client: OpenAIClientType = browser_connection.state["openai_client"]
    thread: Thread = browser_connection.state["thread"]

    openai_task_queue: NamedQueue = NamedQueue("openai_task_queue")
    assistant_audio_tracker = RealtimeAssistantAudioTracker()
    shutdown_drain = RealtimeShutdownDrain()
    session_expiry = RealtimeSessionExpiry()
    ordering_buffer = ConversationItemOrderingBuffer(
        openai_connection_logger, assistant_audio_tracker=assistant_audio_tracker
    )

    realtime_recorder: RealtimeRecorder | None = None
    recording_health = VoiceRecordingHealth()
    if thread.display_user_info:
        realtime_recorder = await RealtimeRecorder.create(
            thread_id=thread.id,
            thread_obj_id=thread.thread_id if thread.thread_id else str(thread.id),
            session=browser_connection.state["db"],
            health=recording_health,
        )
        if realtime_recorder is not None:
            recording_health = realtime_recorder.health

    async def on_playback_settled(item_id: str) -> None:
        ordering_buffer.discard_unheard_assistant_transcripts(item_id)
        await enqueue_ready_thread_message_tasks(
            ordering_buffer,
            openai_task_queue,
            openai_client,
            browser_connection,
            thread,
            realtime_recorder,
        )
        if assistant_audio_tracker.has_item_played_audio(item_id):

            async def update_playback_metadata():
                await update_message_playback_outcome(
                    browser_connection,
                    thread,
                    item_id,
                    assistant_audio_tracker.get_item_playback_outcome(item_id),
                )

            await openai_task_queue.put(update_playback_metadata)

    stop_requested = False
    provider_unavailable = asyncio.Event()

    def provider_ended() -> None:
        session_expiry.stopping = True
        provider_unavailable.set()

    async def acknowledge_stop(saved: bool) -> None:
        try:
            async with asyncio.timeout(BROWSER_SAVE_CONFIRMATION_SECONDS):
                await browser_connection.send_json(
                    {"type": "session.stopped", "saved": saved}
                )
        except (TimeoutError, WebSocketDisconnect, ClientDisconnect, OSError):
            browser_connection_logger.debug(
                "Could not deliver voice save confirmation to the browser."
            )
        except RuntimeError:
            if (
                getattr(browser_connection, "application_state", None)
                != WebSocketState.DISCONNECTED
                and getattr(browser_connection, "client_state", None)
                != WebSocketState.DISCONNECTED
            ):
                raise
        finally:
            try:
                async with asyncio.timeout(BROWSER_SAVE_CONFIRMATION_SECONDS):
                    await _close_browser_connection(browser_connection)
            except TimeoutError:
                browser_connection_logger.debug(
                    "Browser close timed out after voice save confirmation."
                )

    def request_stop() -> None:
        nonlocal stop_requested
        stop_requested = True
        session_expiry.stopping = True
        # The middleware owns the final transaction, including recorder metadata.
        browser_connection.state["after_db_commit"].append(
            lambda: acknowledge_stop(True)
        )
        browser_connection.state["after_db_rollback"].append(
            lambda: acknowledge_stop(False)
        )

    browser_task = asyncio.create_task(
        handle_browser_messages(
            browser_connection,
            realtime_connection,
            assistant_audio_tracker,
            realtime_recorder,
            close_on_cancel=False,
            on_playback_settled=on_playback_settled,
            session_expiry=session_expiry,
            on_session_stop=request_stop,
            provider_unavailable=provider_unavailable,
        )
    )

    async def read_provider_events() -> None:
        try:
            await handle_openai_events(
                browser_connection,
                realtime_connection,
                openai_client,
                thread,
                openai_task_queue,
                assistant_audio_tracker,
                realtime_recorder,
                ordering_buffer=ordering_buffer,
                shutdown_drain=shutdown_drain,
                session_expiry=session_expiry,
                on_provider_end=provider_ended,
            )
        finally:
            provider_ended()

    provider_task = asyncio.create_task(read_provider_events())

    async def wait_for_browser_disconnect_drain():
        async def warn_browser(seconds_remaining: int) -> None:
            await browser_connection.send_json(
                {
                    "type": "session.expiry_warning",
                    "seconds_remaining": seconds_remaining,
                }
            )

        expiry_task = asyncio.create_task(session_expiry.wait(warn_browser))
        provider_end_task = asyncio.create_task(provider_unavailable.wait())
        drain_task = None
        try:
            # Keep the browser reader alive for the final played offsets, even
            # after microphone input and new playback have been cut off.
            await asyncio.wait(
                {browser_task, expiry_task, provider_end_task},
                return_when=asyncio.FIRST_COMPLETED,
            )
            if not browser_task.done():
                event_type = (
                    "session.ended"
                    if provider_unavailable.is_set()
                    else "session.expiring"
                )
                session_expiry.stopping = True
                try:
                    async with asyncio.timeout(BROWSER_EXPIRY_STOP_SECONDS):
                        await browser_connection.send_json({"type": event_type})
                        await asyncio.wait({browser_task})
                except (TimeoutError, WebSocketDisconnect, ClientDisconnect, OSError):
                    browser_connection_logger.debug(
                        "Browser did not finish the server-requested shutdown handshake."
                    )
                except RuntimeError:
                    if (
                        getattr(browser_connection, "application_state", None)
                        != WebSocketState.DISCONNECTED
                        and getattr(browser_connection, "client_state", None)
                        != WebSocketState.DISCONNECTED
                    ):
                        raise
                if not browser_task.done():
                    browser_task.cancel()
                    await asyncio.wait({browser_task})
            if provider_unavailable.is_set():
                if not shutdown_drain.is_complete(ordering_buffer):
                    shutdown_drain.usage.mark_incomplete("provider_connection_closed")
                # A terminal provider event can precede its last buffered text.
                # A completed reader returns immediately; never send controls to
                # a provider that has already ended or rejected a write.
                await asyncio.wait(
                    {provider_task}, timeout=BROWSER_DISCONNECT_DRAIN_SECONDS
                )
            else:
                drain_task = asyncio.create_task(
                    shutdown_drain.wait(realtime_connection, ordering_buffer)
                )
                await asyncio.wait(
                    {drain_task, provider_task}, return_when=asyncio.FIRST_COMPLETED
                )
                if drain_task.done() and not drain_task.cancelled():
                    drain_task.result()
        finally:
            expiry_task.cancel()
            provider_end_task.cancel()
            if drain_task is not None:
                drain_task.cancel()
            await asyncio.gather(
                expiry_task,
                provider_end_task,
                *([drain_task] if drain_task is not None else []),
                return_exceptions=True,
            )

    shutdown_task = asyncio.create_task(wait_for_browser_disconnect_drain())
    realtime_tasks = [provider_task, shutdown_task]
    openai_queue_processor = asyncio.create_task(
        process_queue_tasks(
            openai_task_queue, openai_connection_logger, assistant_audio_tracker
        )
    )

    recorder_task = (
        asyncio.create_task(realtime_recorder.handle_saving_buffer(every=10))
        if realtime_recorder
        else None
    )

    async def finish_session():
        if recorder_task is not None:
            recorder_task.cancel()
        for task in realtime_tasks:
            task.cancel()
        results = await asyncio.gather(
            *realtime_tasks,
            *([recorder_task] if recorder_task is not None else []),
            return_exceptions=True,
        )
        try:
            # Per-reply decisions cannot finish while playback callbacks can
            # still arrive. Settle the reader before releasing unheard replies.
            browser_task.cancel()
            await asyncio.wait({browser_task})
            assistant_audio_tracker.finish_playback_tracking()
            ordering_buffer.discard_unheard_assistant_transcripts()
            ordering_buffer.finalize_pending_transcriptions()
            await enqueue_ready_thread_message_tasks(
                ordering_buffer,
                openai_task_queue,
                openai_client,
                browser_connection,
                thread,
                realtime_recorder,
            )
            # Stop producers first, then save qualified messages or discard the
            # queued writes without touching local or provider-side history.
            await openai_task_queue.join()
        finally:
            openai_queue_processor.cancel()
            results.extend(
                await asyncio.gather(openai_queue_processor, return_exceptions=True)
            )
            if not browser_task.done():
                browser_task.cancel()
            results.extend(await asyncio.gather(browser_task, return_exceptions=True))
            # Stop reading before deciding which replies were heard, but keep
            # the socket open until queued history writes have finished.
            if not stop_requested:
                try:
                    await _close_browser_connection(browser_connection)
                except Exception as error:
                    results.append(error)
            # The recorder shares the transcript writer's DB session. Finalize
            # only after writes and browser buffer mutations have stopped.
            if realtime_recorder:
                try:
                    await realtime_recorder.complete_audio_upload(
                        has_played_audio=assistant_audio_tracker.has_played_audio
                    )
                except Exception:
                    openai_connection_logger.exception(
                        "Error finalizing realtime recording."
                    )
            if recording_health.recording_issue or recording_health.upload_issue:
                try:
                    await recording_health.persist(
                        browser_connection.state["db"], thread.id
                    )
                except Exception:
                    openai_connection_logger.exception(
                        "Error saving voice recording health flags for thread_id=%s",
                        thread.id,
                    )
            for task in (provider_task, shutdown_task, browser_task):
                if task.done() and not task.cancelled():
                    task_error = task.exception()
                    if task_error is not None and not isinstance(
                        task_error, (WebSocketDisconnect, ClientDisconnect)
                    ):
                        if isinstance(task_error, REALTIME_CONNECTION_ERRORS):
                            if not shutdown_drain.is_complete(ordering_buffer):
                                shutdown_drain.usage.mark_incomplete(
                                    "provider_connection_closed"
                                )
                        else:
                            shutdown_drain.usage.fail(
                                "voice_session_error",
                                "An internal error interrupted the voice session.",
                            )
            await save_voice_usage(browser_connection, thread, shutdown_drain.usage)
        for result in results:
            if isinstance(result, Exception) and not isinstance(
                result, (ClientDisconnect, WebSocketDisconnect)
            ):
                openai_connection_logger.error(
                    "Realtime session task failed during cleanup.", exc_info=result
                )

    async def commit_cancelled_session():
        # The DB middleware commits only on normal return. Preserve completed
        # cleanup before propagating cancellation, even if commit/rollback fail.
        session = browser_connection.state["db"]
        try:
            await session.commit()
        except Exception:
            openai_connection_logger.exception(
                "Error committing cancelled voice session for thread_id=%s",
                sanitize_for_log(thread_id),
            )
            try:
                await session.rollback()
            except Exception:
                openai_connection_logger.exception(
                    "Error rolling back cancelled voice session for thread_id=%s",
                    sanitize_for_log(thread_id),
                )
        finally:
            # Cancellation bypasses the middleware's acknowledgement callbacks,
            # including when it first arrives during recording finalization.
            if stop_requested:
                try:
                    async with asyncio.timeout(BROWSER_SAVE_CONFIRMATION_SECONDS):
                        await _close_browser_connection(browser_connection)
                except Exception:
                    openai_connection_logger.exception(
                        "Error closing cancelled voice session for thread_id=%s",
                        sanitize_for_log(thread_id),
                    )

    cancelled: asyncio.CancelledError | None = None

    async def await_cleanup(task: asyncio.Task):
        nonlocal cancelled
        while True:
            try:
                return await asyncio.shield(task)
            except asyncio.CancelledError as error:
                if task.cancelled():
                    raise
                # Retain and await the same task through repeated cancellation.
                if cancelled is None:
                    cancelled = error
                    shutdown_drain.usage.mark_incomplete("session_cancelled")

    try:
        # Provider completion starts the browser handshake rather than cancelling
        # its playback reader before the final heard-audio offsets arrive.
        await asyncio.wait({shutdown_task})
    except asyncio.CancelledError as error:
        cancelled = error
        shutdown_drain.usage.mark_incomplete("session_cancelled")
    finally:
        try:
            await await_cleanup(asyncio.create_task(finish_session()))
        finally:
            if cancelled is not None:
                await await_cleanup(asyncio.create_task(commit_cancelled_session()))
    if cancelled is not None:
        raise cancelled
