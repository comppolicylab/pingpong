import asyncio
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


@pytest.mark.parametrize("previous_known", [False, True])
@pytest.mark.parametrize("played", [False, True])
@pytest.mark.parametrize("partial_text", [None, "partial reply"])
async def test_finalization_skips_only_unheard_replies_and_preserves_chain_checks(
    previous_known, played, partial_text
):
    tracker = RealtimeAssistantAudioTracker()
    buffer = ConversationItemOrderingBuffer(
        logging.getLogger(__name__), assistant_audio_tracker=tracker
    )
    if previous_known:
        buffer.register_conversation_item("question", None, "user")
        buffer.register_transcription("question", "question", "user")
    buffer.register_conversation_item("reply", "question", "assistant")
    if partial_text:
        buffer.register_transcription_delta("reply", partial_text, "assistant")
    buffer.register_conversation_item("later", "reply", "user")
    buffer.register_transcription("later", "later", "user")
    assert [message[0] for message in _drain_ready_messages(buffer)] == (
        ["question"] if previous_known else []
    )
    if played:
        await tracker.add_audio_delta("reply", "audio", b"\0\0")
        await tracker.mark_audio_event_playback_started("reply", "audio")
    tracker.finish_playback_tracking()
    buffer.discard_unheard_assistant_transcripts()
    assert [message[0] for message in _drain_ready_messages(buffer)] == (
        ["later"] if previous_known and not played else []
    )
    if played:
        # A heard reply with missing transcript completion must not be silently
        # omitted by the unheard-reply policy.
        assert not buffer.items_by_id["reply"].skip_persistence


async def test_finished_playback_resolves_pending_and_future_reply_decisions():
    tracker = RealtimeAssistantAudioTracker()
    await tracker.add_audio_delta("unheard", "audio", b"\0\0")
    pending = asyncio.create_task(tracker.wait_for_item_retention_decision("unheard"))
    await asyncio.sleep(0)
    assert not pending.done()
    tracker.finish_playback_tracking()
    assert not await asyncio.wait_for(pending, timeout=1)
    assert not await asyncio.wait_for(
        tracker.wait_for_item_retention_decision("later"), timeout=1
    )
    assert not await tracker.mark_audio_event_playback_started("unheard", "audio")
    assert not tracker.has_played_audio


@pytest.mark.parametrize("played", [False, True])
async def test_explicit_settlement_resolves_pending_and_future_decisions(played):
    tracker = RealtimeAssistantAudioTracker()
    await tracker.add_audio_delta("reply", "part", b"\0" * 480)
    pending = asyncio.create_task(tracker.wait_for_item_retention_decision("reply"))
    await asyncio.sleep(0)
    assert not pending.done()
    outcome = "interrupted" if played else "discarded"
    assert await tracker.mark_item_playback_settled("reply", outcome, played)
    assert await asyncio.wait_for(pending, timeout=1) == played
    assert (
        await asyncio.wait_for(
            tracker.wait_for_item_retention_decision("reply"), timeout=1
        )
        == played
    )
    assert tracker.has_played_audio == played
    assert not await tracker.mark_item_playback_settled("reply", outcome, played)
    assert not await tracker.mark_item_playback_settled("reply", "discarded", False)
    assert not await tracker.mark_audio_event_playback_started("reply", "part")


@pytest.mark.parametrize("played", [False, True])
async def test_settlement_releases_chunk_records_but_keeps_truncate_boundaries(played):
    tracker = RealtimeAssistantAudioTracker()
    await tracker.add_audio_delta("reply", "part-1", b"\0" * 480)
    await tracker.add_audio_delta("reply", "part-2", b"\0" * 480)
    await tracker.add_audio_delta("pending", "part-3", b"\0" * 480)
    if played:
        await tracker.mark_audio_event_playback_started("reply", "part-1")
    outcome = "interrupted" if played else "discarded"
    assert await tracker.mark_item_playback_settled("reply", outcome, played)

    assert "reply" not in tracker._playback_events_by_item_id
    assert "pending" in tracker._playback_events_by_item_id
    assert tracker.has_item_played_audio("reply") == played
    assert tracker.has_played_audio == played
    assert await tracker.clamp_truncate_audio_end_ms("reply", 1000, "part-1") == 10
    assert await tracker.clamp_truncate_audio_end_ms("reply", 1000) == 20
    assert not await tracker.mark_audio_event_playback_started("reply", "part-2")
    assert not await tracker.mark_audio_event_playback_ended("reply", "part-1")


async def test_finish_playback_tracking_releases_all_pending_chunk_records():
    tracker = RealtimeAssistantAudioTracker()
    await tracker.add_audio_delta("heard", "part-1", b"\0" * 480)
    await tracker.add_audio_delta("unheard", "part-2", b"\0" * 480)
    await tracker.mark_audio_event_playback_started("heard", "part-1")
    tracker.finish_playback_tracking()

    assert not tracker._playback_events_by_item_id
    assert tracker.has_item_played_audio("heard")
    assert tracker.has_played_audio
    assert not tracker.has_item_played_audio("unheard")
    assert not await tracker.mark_audio_event_playback_started("unheard", "part-2")
    assert not await tracker.mark_audio_event_playback_ended("heard", "part-1")
    assert await tracker.clamp_truncate_audio_end_ms("heard", 1000, "part-1") == 10


@pytest.mark.parametrize(
    "item_id,outcome,played",
    [
        ("unknown", "discarded", False),
        ([], "discarded", False),
        ("reply", [], False),
        ("reply", "invalid", False),
        ("reply", "discarded", 0),
        ("reply", "discarded", None),
        ("reply", "discarded", True),
        ("reply", "completed", False),
        ("reply", "completed", True),
    ],
)
async def test_invalid_settlements_do_not_resolve_item(item_id, outcome, played):
    tracker = RealtimeAssistantAudioTracker()
    await tracker.add_audio_delta("reply", "part", b"\0\0")
    assert not await tracker.mark_item_playback_settled(item_id, outcome, played)
    assert not tracker.is_item_playback_settled("reply")
    assert not tracker.has_played_audio


async def test_settlement_cannot_erase_known_playback_or_invent_audio():
    tracker = RealtimeAssistantAudioTracker()
    tracker.register_item("empty")
    assert not await tracker.mark_item_playback_settled("empty", "completed", True)
    assert await tracker.mark_item_playback_settled("empty", "discarded", False)
    await tracker.add_audio_delta("heard", "part", b"\0\0")
    await tracker.mark_audio_event_playback_started("heard", "part")
    await tracker.mark_audio_event_playback_ended("heard", "part")
    await tracker.mark_item_audio_done("heard")
    assert not await tracker.mark_item_playback_settled("heard", "discarded", False)
    assert await tracker.mark_item_playback_settled("heard", "completed", True)
    assert tracker.has_item_played_audio("heard")


async def test_skipping_unheard_reply_releases_later_heard_reply_in_order():
    tracker = RealtimeAssistantAudioTracker()
    await tracker.add_audio_delta("heard", "audio", b"\0\0")
    await tracker.mark_audio_event_playback_started("heard", "audio")
    buffer = ConversationItemOrderingBuffer(
        logging.getLogger(__name__), assistant_audio_tracker=tracker
    )
    for item_id, previous, role in [
        ("unheard", None, "assistant"),
        ("question", "unheard", "user"),
        ("heard", "question", "assistant"),
    ]:
        buffer.register_conversation_item(item_id, previous, role)
        if item_id != "unheard":
            buffer.register_transcription(item_id, item_id, role)
    assert not _drain_ready_messages(buffer)
    tracker.finish_playback_tracking()
    buffer.discard_unheard_assistant_transcripts()
    assert _drain_ready_messages(buffer) == [
        ("question", "question", "user", "0"),
        ("heard", "heard", "assistant", "1"),
    ]


@pytest.mark.parametrize("end_first", [False, True])
@pytest.mark.parametrize("retire_before_playback", [None, "audio_done", "truncate"])
async def test_confirmed_playback_survives_generation_and_duration_cleanup(
    end_first, retire_before_playback
):
    tracker = RealtimeAssistantAudioTracker()
    await tracker.add_audio_delta("heard", "event-1", b"\0" * 480)
    await tracker.add_audio_delta("unheard", "event-2", b"\0" * 480)
    assert not tracker.has_played_audio
    assert not tracker.has_item_played_audio("heard")
    if retire_before_playback == "audio_done":
        await tracker.mark_item_audio_done("heard")
    elif retire_before_playback == "truncate":
        await tracker.forget_item("heard")

    callbacks = [
        tracker.mark_audio_event_playback_started,
        tracker.mark_audio_event_playback_ended,
    ]
    if end_first:
        callbacks.reverse()
    for callback in callbacks:
        assert await callback("heard", "event-1")
        assert not await callback("heard", "event-1")
        assert tracker.has_played_audio
        assert tracker.has_item_played_audio("heard")
        assert not tracker.has_item_played_audio("unheard")
        if end_first:
            # A late start must still be recognized after generated-duration
            # bookkeeping has been retired by the provider-done event.
            await tracker.mark_item_audio_done("heard")
    await tracker.mark_item_audio_done("heard")
    await tracker.forget_item("heard")
    assert tracker.has_played_audio
    assert tracker.has_item_played_audio("heard")


@pytest.mark.parametrize(
    "callback", ["mark_audio_event_playback_started", "mark_audio_event_playback_ended"]
)
@pytest.mark.parametrize(
    "item_id,event_id",
    [
        ("unknown", "event-1"),
        ("known", "unknown"),
        ("another", "event-1"),
        (None, "event-1"),
        ("known", None),
        ([], "event-1"),
        ("known", {}),
    ],
)
async def test_unknown_or_malformed_audio_events_do_not_qualify_playback(
    callback, item_id, event_id
):
    tracker = RealtimeAssistantAudioTracker()
    await tracker.add_audio_delta("known", "event-1", b"\0" * 480)
    await tracker.add_audio_delta("another", "event-2", b"\0" * 480)
    assert not await getattr(tracker, callback)(item_id, event_id)
    assert not tracker.has_played_audio


@pytest.mark.parametrize("audio", [b"", b"\0"])
async def test_empty_audio_event_does_not_qualify_playback_after_nonempty_audio(audio):
    tracker = RealtimeAssistantAudioTracker()
    await tracker.add_audio_delta("known", "event-1", b"\0" * 480)
    await tracker.add_audio_delta("known", "empty", audio)
    assert not await tracker.mark_audio_event_playback_started("known", "empty")
    assert not await tracker.mark_audio_event_playback_ended("known", "empty")
    assert not tracker.has_played_audio


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


@pytest.mark.parametrize("role", ["user", "assistant"])
def test_completed_transcript_waits_for_item_metadata(
    role, caplog: pytest.LogCaptureFixture
):
    logger_name = "ordering-test-before-item-added"
    buffer = ConversationItemOrderingBuffer(logging.getLogger(logger_name))
    caplog.set_level(logging.WARNING, logger=logger_name)

    buffer.register_transcription("item-1", "hello", role)
    assert _drain_ready_messages(buffer) == []

    buffer.register_conversation_item("item-1", None, role)
    assert _drain_ready_messages(buffer) == [("item-1", "hello", role, "0")]
    assert _drain_ready_messages(buffer) == []
    assert not caplog.records


@pytest.mark.parametrize("role", ["user", "assistant"])
@pytest.mark.parametrize("completed_text", [None, "corrected transcript"])
def test_early_deltas_survive_item_registration(role, completed_text):
    buffer = ConversationItemOrderingBuffer(logging.getLogger("ordering-test"))
    buffer.register_transcription_delta("item-1", "hel", role)
    assert _drain_ready_messages(buffer) == []

    buffer.register_conversation_item("item-1", None, role)
    buffer.register_transcription_delta("item-1", "lo", role)
    assert _drain_ready_messages(buffer) == []

    buffer.register_transcription("item-1", completed_text, role)
    assert _drain_ready_messages(buffer) == [
        ("item-1", completed_text or "hello", role, "0")
    ]


def test_early_transcripts_follow_late_predecessor_metadata():
    buffer = ConversationItemOrderingBuffer(
        logging.getLogger("ordering-test"), initial_output_index=7
    )
    buffer.register_transcription("reply", "answer", "assistant")
    buffer.register_transcription("question", "question", "user")
    assert _drain_ready_messages(buffer) == []

    buffer.register_conversation_item("reply", "question", "assistant")
    assert _drain_ready_messages(buffer) == []
    buffer.register_conversation_item("question", None, "user")
    assert _drain_ready_messages(buffer) == [
        ("question", "question", "user", "7"),
        ("reply", "answer", "assistant", "8"),
    ]
    assert _drain_ready_messages(buffer) == []


@pytest.mark.parametrize("metadata_first", [False, True])
@pytest.mark.parametrize("partial_text", [None, "partial question"])
def test_failed_transcription_releases_later_messages(metadata_first, partial_text):
    buffer = ConversationItemOrderingBuffer(logging.getLogger("ordering-test"))
    if metadata_first:
        buffer.register_conversation_item("question", None, "user")
    if partial_text:
        buffer.register_transcription_delta("question", partial_text, "user")
    buffer.register_conversation_item("reply", "question", "assistant")
    buffer.register_transcription("reply", "answer", "assistant")
    assert _drain_ready_messages(buffer) == []

    buffer.fail_transcription("question")
    if not metadata_first:
        assert _drain_ready_messages(buffer) == []
        buffer.register_conversation_item("question", None, "user")
    expected = [("question", partial_text, "user", "0")] if partial_text else []
    expected.append(("reply", "answer", "assistant", str(len(expected))))
    assert _drain_ready_messages(buffer) == expected
    assert "question" in buffer.failed_transcription_item_ids
    buffer.fail_transcription("question")
    assert _drain_ready_messages(buffer) == []


def test_late_failure_does_not_replace_completed_transcription():
    buffer = ConversationItemOrderingBuffer(logging.getLogger("ordering-test"))
    buffer.register_conversation_item("question", None, "user")
    buffer.register_transcription("question", "complete question", "user")
    buffer.fail_transcription("question")
    assert _drain_ready_messages(buffer) == [
        ("question", "complete question", "user", "0")
    ]
    assert "question" not in buffer.failed_transcription_item_ids


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
