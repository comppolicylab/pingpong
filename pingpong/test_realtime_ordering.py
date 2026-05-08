import logging

import pytest

from pingpong.realtime import (
    ConversationItemOrderingBuffer,
    RealtimeAssistantAudioTracker,
)


def _drain_ready_messages(buffer: ConversationItemOrderingBuffer):
    ready_messages: list[tuple[str, str, str, str]] = []
    while True:
        next_message = buffer.pop_next_ready_message()
        if next_message is None:
            return ready_messages
        ready_messages.append(next_message)


@pytest.mark.asyncio
async def test_assistant_audio_tracker_clamps_to_generated_duration():
    tracker = RealtimeAssistantAudioTracker()
    audio_delta = b"\0" * (24_000 * 2)

    await tracker.add_audio_delta("item-1", "event-1", audio_delta)

    assert await tracker.clamp_truncate_audio_end_ms("item-1", 1500) == 1000
    assert await tracker.clamp_truncate_audio_end_ms("item-1", 500) == 500


@pytest.mark.asyncio
async def test_assistant_audio_tracker_clamps_to_event_end_duration():
    tracker = RealtimeAssistantAudioTracker()
    half_second_audio_delta = b"\0" * (12_000 * 2)

    await tracker.add_audio_delta("item-1", "event-1", half_second_audio_delta)
    await tracker.add_audio_delta("item-1", "event-2", half_second_audio_delta)

    assert (
        await tracker.clamp_truncate_audio_end_ms(
            "item-1", requested_audio_end_ms=900, event_id="event-1"
        )
        == 500
    )
    assert (
        await tracker.clamp_truncate_audio_end_ms(
            "item-1", requested_audio_end_ms=900, event_id="event-2"
        )
        == 900
    )


@pytest.mark.asyncio
async def test_assistant_audio_tracker_keeps_pending_event_after_audio_done():
    tracker = RealtimeAssistantAudioTracker()
    half_second_audio_delta = b"\0" * (12_000 * 2)

    await tracker.add_audio_delta("item-1", "event-1", half_second_audio_delta)
    await tracker.add_audio_delta("item-1", "event-2", half_second_audio_delta)

    await tracker.mark_audio_event_playback_ended("item-1", "event-1")
    await tracker.mark_item_audio_done("item-1")

    assert (
        await tracker.clamp_truncate_audio_end_ms(
            "item-1", requested_audio_end_ms=1500, event_id="event-2"
        )
        == 1000
    )


@pytest.mark.asyncio
async def test_assistant_audio_tracker_forgets_item_after_audio_done_and_events_end():
    tracker = RealtimeAssistantAudioTracker()
    half_second_audio_delta = b"\0" * (12_000 * 2)

    await tracker.add_audio_delta("item-1", "event-1", half_second_audio_delta)
    await tracker.add_audio_delta("item-1", "event-2", half_second_audio_delta)

    await tracker.mark_audio_event_playback_ended("item-1", "event-1")
    await tracker.mark_item_audio_done("item-1")
    await tracker.mark_audio_event_playback_ended("item-1", "event-2")

    assert await tracker.clamp_truncate_audio_end_ms("item-1", 1500) == 1500


@pytest.mark.asyncio
async def test_assistant_audio_tracker_forgets_truncated_item():
    tracker = RealtimeAssistantAudioTracker()
    audio_delta = b"\0" * (24_000 * 2)

    await tracker.add_audio_delta("item-1", "event-1", audio_delta)
    await tracker.forget_item("item-1")

    assert await tracker.clamp_truncate_audio_end_ms("item-1", 1500) == 1500


@pytest.mark.asyncio
async def test_assistant_audio_tracker_leaves_unknown_item_duration_unchanged():
    tracker = RealtimeAssistantAudioTracker()

    assert await tracker.clamp_truncate_audio_end_ms("item-unknown", 1500) == 1500


def test_transcript_dispatches_once_item_is_registered():
    buffer = ConversationItemOrderingBuffer(logging.getLogger("ordering-test"))

    buffer.register_conversation_item("item-1", None, "user")
    buffer.register_transcription("item-1", "hello", "user")
    assert _drain_ready_messages(buffer) == [("item-1", "hello", "user", "0")]
    assert _drain_ready_messages(buffer) == []


def test_empty_transcript_is_skipped_and_descendant_still_dispatches():
    buffer = ConversationItemOrderingBuffer(logging.getLogger("ordering-test"))

    buffer.register_conversation_item("item-1", None, "user")
    buffer.register_conversation_item("item-2", "item-1", "assistant")

    buffer.register_transcription("item-1", "   ", "user")
    buffer.register_transcription("item-2", "assistant text", "assistant")

    assert _drain_ready_messages(buffer) == [
        ("item-2", "assistant text", "assistant", "0")
    ]
    assert _drain_ready_messages(buffer) == []


def test_transcript_before_item_added_is_ignored(caplog: pytest.LogCaptureFixture):
    logger_name = "ordering-test-before-item-added"
    buffer = ConversationItemOrderingBuffer(logging.getLogger(logger_name))
    caplog.set_level(logging.WARNING, logger=logger_name)

    buffer.register_transcription("item-1", "hello", "user")
    buffer.register_transcription_delta("item-1", "hi", "user")
    assert buffer.items_by_id == {}

    buffer.register_conversation_item("item-1", None, "user")
    assert _drain_ready_messages(buffer) == []

    assert "before conversation.item.added" in caplog.text


def test_relevant_registration_sets_has_transcription_flag():
    buffer = ConversationItemOrderingBuffer(logging.getLogger("ordering-test"))

    buffer.register_conversation_item("user-1", None, "user")
    buffer.register_conversation_item("system-1", "user-1", None)

    user_item = buffer.items_by_id["user-1"]
    system_item = buffer.items_by_id["system-1"]
    assert user_item.has_transcription
    assert not system_item.has_transcription


def test_transcription_deltas_wait_for_completion():
    buffer = ConversationItemOrderingBuffer(logging.getLogger("ordering-test"))

    buffer.register_conversation_item("item-1", None, "user")
    buffer.register_transcription_delta("item-1", "hel", "user")
    buffer.register_transcription_delta("item-1", "lo", "user")

    assert _drain_ready_messages(buffer) == []
    item = buffer.items_by_id["item-1"]
    assert item.has_transcription
    assert not item.is_transcription_complete
    assert item.transcription_text == "hello"

    buffer.register_transcription("item-1", None, "user")
    assert buffer.items_by_id["item-1"].is_transcription_complete
    assert _drain_ready_messages(buffer) == [("item-1", "hello", "user", "0")]


def test_completed_transcription_overrides_deltas():
    buffer = ConversationItemOrderingBuffer(logging.getLogger("ordering-test"))

    buffer.register_conversation_item("item-1", None, "assistant")
    buffer.register_transcription_delta("item-1", "part", "assistant")
    buffer.register_transcription_delta("item-1", "ial", "assistant")

    buffer.register_transcription("item-1", "final", "assistant")
    assert _drain_ready_messages(buffer) == [("item-1", "final", "assistant", "0")]


def test_dispatch_respects_previous_item_relationships():
    buffer = ConversationItemOrderingBuffer(logging.getLogger("ordering-test"))

    buffer.register_conversation_item("item-1", None, "user")
    buffer.register_conversation_item("item-2", "item-1", "assistant")

    buffer.register_transcription("item-2", "assistant text", "assistant")
    buffer.register_transcription("item-1", "user text", "user")

    assert _drain_ready_messages(buffer) == [
        ("item-1", "user text", "user", "0"),
        ("item-2", "assistant text", "assistant", "1"),
    ]


def test_transcript_without_item_id_logs_warning(caplog: pytest.LogCaptureFixture):
    logger_name = "ordering-test-missing-id"
    buffer = ConversationItemOrderingBuffer(logging.getLogger(logger_name))
    caplog.set_level(logging.WARNING, logger=logger_name)

    buffer.register_transcription(None, "missing", "user")

    assert "without an item_id" in caplog.text
    assert buffer.items_by_id == {}


def test_interleaving_transcripts_follow_conversation_order():
    buffer = ConversationItemOrderingBuffer(logging.getLogger("ordering-test"))

    buffer.register_conversation_item("user-1", None, "user")
    buffer.register_conversation_item("assistant-1", "user-1", "assistant")

    buffer.register_transcription("assistant-1", "assistant-1", "assistant")
    assert _drain_ready_messages(buffer) == []

    buffer.register_conversation_item("user-2", "assistant-1", "user")
    buffer.register_transcription("user-1", "user-1", "user")
    assert _drain_ready_messages(buffer) == [
        ("user-1", "user-1", "user", "0"),
        ("assistant-1", "assistant-1", "assistant", "1"),
    ]

    buffer.register_conversation_item("assistant-2", "user-2", "assistant")
    buffer.register_transcription("assistant-2", "assistant-2", "assistant")
    assert _drain_ready_messages(buffer) == []

    buffer.register_transcription("user-2", "user-2", "user")
    assert _drain_ready_messages(buffer) == [
        ("user-2", "user-2", "user", "2"),
        ("assistant-2", "assistant-2", "assistant", "3"),
    ]


def test_late_predecessor_registration_reorders_before_dispatch():
    buffer = ConversationItemOrderingBuffer(logging.getLogger("ordering-test"))

    buffer.register_conversation_item("assistant-1", "user-1", "assistant")
    buffer.register_conversation_item("assistant-2", "assistant-1", "assistant")

    buffer.register_transcription("assistant-2", "assistant-2", "assistant")
    buffer.register_transcription("assistant-1", "assistant-1", "assistant")
    assert _drain_ready_messages(buffer) == []

    buffer.register_conversation_item("user-1", None, "user")
    buffer.register_transcription("user-1", "user-1", "user")
    assert _drain_ready_messages(buffer) == [
        ("user-1", "user-1", "user", "0"),
        ("assistant-1", "assistant-1", "assistant", "1"),
        ("assistant-2", "assistant-2", "assistant", "2"),
    ]


def test_existing_item_can_adopt_late_previous_item_id():
    buffer = ConversationItemOrderingBuffer(logging.getLogger("ordering-test"))

    buffer.register_conversation_item("assistant-1", None, "assistant")
    buffer.register_conversation_item("user-1", None, "user")
    buffer.register_conversation_item("assistant-1", "user-1", "assistant")

    buffer.register_transcription("assistant-1", "assistant-1", "assistant")
    assert _drain_ready_messages(buffer) == []

    buffer.register_transcription("user-1", "user-1", "user")
    assert _drain_ready_messages(buffer) == [
        ("user-1", "user-1", "user", "0"),
        ("assistant-1", "assistant-1", "assistant", "1"),
    ]


def test_item_after_non_relevant_predecessor_dispatches():
    buffer = ConversationItemOrderingBuffer(logging.getLogger("ordering-test"))

    buffer.register_conversation_item("user-1", None, "user")
    buffer.register_conversation_item("system-1", "user-1", None)
    buffer.register_conversation_item("assistant-1", "system-1", "assistant")

    buffer.register_transcription("assistant-1", "assistant-1", "assistant")
    buffer.register_transcription("user-1", "user-1", "user")

    assert _drain_ready_messages(buffer) == [
        ("user-1", "user-1", "user", "0"),
        ("assistant-1", "assistant-1", "assistant", "1"),
    ]


def test_late_non_relevant_predecessor_unblocks_dispatch():
    buffer = ConversationItemOrderingBuffer(logging.getLogger("ordering-test"))

    buffer.register_conversation_item("user-1", None, "user")
    buffer.register_conversation_item("assistant-1", "system-1", "assistant")

    buffer.register_transcription("user-1", "user-1", "user")
    assert _drain_ready_messages(buffer) == [("user-1", "user-1", "user", "0")]

    buffer.register_transcription("assistant-1", "assistant-1", "assistant")
    assert _drain_ready_messages(buffer) == []

    buffer.register_conversation_item("system-1", "user-1", None)
    assert _drain_ready_messages(buffer) == [
        ("assistant-1", "assistant-1", "assistant", "1")
    ]


def test_pruned_saved_predecessor_still_allows_late_descendant_dispatch():
    buffer = ConversationItemOrderingBuffer(logging.getLogger("ordering-test"))

    buffer.register_conversation_item("user-1", None, "user")
    buffer.register_transcription("user-1", "user-1", "user")
    assert _drain_ready_messages(buffer) == [("user-1", "user-1", "user", "0")]

    buffer.register_conversation_item("assistant-1", "user-1", "assistant")
    buffer.register_transcription("assistant-1", "assistant-1", "assistant")
    assert _drain_ready_messages(buffer) == [
        ("assistant-1", "assistant-1", "assistant", "1")
    ]
    assert "user-1" not in buffer.items_by_id
    assert "assistant-1" not in buffer.items_by_id

    buffer.register_conversation_item("system-1", "user-1", None)
    buffer.register_conversation_item("assistant-2", "system-1", "assistant")
    buffer.register_transcription("assistant-2", "assistant-2", "assistant")
    assert _drain_ready_messages(buffer) == [
        ("assistant-2", "assistant-2", "assistant", "2")
    ]
