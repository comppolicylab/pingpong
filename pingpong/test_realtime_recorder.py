from typing import Any

import pytest

from pingpong.realtime_recorder import RealtimeRecorder


ONE_SECOND_PCM16 = b"\0" * 48_000


class FakeFfmpegStdin:
    def __init__(self):
        self.writes: list[bytes] = []

    def write(self, data: bytes) -> None:
        self.writes.append(data)

    async def drain(self) -> None:
        pass


class FakeFfmpeg:
    def __init__(self):
        self.stdin = FakeFfmpegStdin()


def make_recorder() -> RealtimeRecorder:
    recorder = RealtimeRecorder(
        audio_store_obj=object(),  # type: ignore[arg-type]
        audio_recording_id="test.webm",
        thread_id=1,
        session=None,  # type: ignore[arg-type]
    )
    recorder.ffmpeg = FakeFfmpeg()  # type: ignore[assignment]
    recorder.end_timestamp = 1_000
    return recorder


@pytest.mark.asyncio
async def test_save_buffer_keeps_completed_response_until_queued_chunks_end():
    recorder = make_recorder()

    await recorder.add_assistant_response_delta(
        audio_chunk_bytes=ONE_SECOND_PCM16,
        event_id="event-1",
        item_id="item-1",
    )
    await recorder.started_playing_assistant_response_delta(
        item_id="item-1",
        event_id="event-1",
        started_playing_at_ms=1_000,
    )
    await recorder.ended_playing_assistant_response_delta(
        item_id="item-1",
        event_id="event-1",
    )
    await recorder.add_assistant_response_delta(
        audio_chunk_bytes=ONE_SECOND_PCM16,
        event_id="event-2",
        item_id="item-1",
    )
    await recorder.add_assistant_response_delta(
        audio_chunk_bytes=ONE_SECOND_PCM16,
        event_id="event-3",
        item_id="item-2",
    )

    await recorder.save_buffer()

    assert "item-1" in recorder.assistant_responses
    assert get_write_count(recorder) == 0

    await recorder.started_playing_assistant_response_delta(
        item_id="item-1",
        event_id="event-2",
        started_playing_at_ms=2_000,
    )
    await recorder.save_buffer()

    assert "item-1" in recorder.assistant_responses
    assert get_write_count(recorder) == 0

    await recorder.ended_playing_assistant_response_delta(
        item_id="item-1",
        event_id="event-2",
    )
    await recorder.save_buffer()

    assert "item-1" not in recorder.assistant_responses
    assert get_write_count(recorder) > 0


@pytest.mark.asyncio
async def test_save_buffer_allows_truncated_response_without_delta_end():
    recorder = make_recorder()

    await recorder.add_assistant_response_delta(
        audio_chunk_bytes=ONE_SECOND_PCM16,
        event_id="event-1",
        item_id="item-1",
    )
    await recorder.started_playing_assistant_response_delta(
        item_id="item-1",
        event_id="event-1",
        started_playing_at_ms=1_000,
    )
    await recorder.stopped_playing_assistant_response(
        item_id="item-1",
        final_duration_ms=500,
    )

    await recorder.save_buffer()

    assert "item-1" not in recorder.assistant_responses
    assert get_write_count(recorder) > 0


@pytest.mark.asyncio
async def test_save_buffer_allows_truncated_response_extending_into_unstarted_chunk():
    recorder = make_recorder()

    for event_id in ("event-1", "event-2", "event-3"):
        await recorder.add_assistant_response_delta(
            audio_chunk_bytes=ONE_SECOND_PCM16,
            event_id=event_id,
            item_id="item-1",
        )
    await recorder.started_playing_assistant_response_delta(
        item_id="item-1",
        event_id="event-1",
        started_playing_at_ms=1_000,
    )
    await recorder.ended_playing_assistant_response_delta(
        item_id="item-1",
        event_id="event-1",
    )
    await recorder.started_playing_assistant_response_delta(
        item_id="item-1",
        event_id="event-2",
        started_playing_at_ms=2_000,
    )

    await recorder.stopped_playing_assistant_response(
        item_id="item-1",
        final_duration_ms=2_500,
    )
    await recorder.save_buffer()

    assert "item-1" not in recorder.assistant_responses
    assert get_write_count(recorder) > 0
    assert recorder.audio_duration == 2_000


@pytest.mark.asyncio
async def test_truncate_discards_response_when_no_chunks_started():
    recorder = make_recorder()

    await recorder.add_assistant_response_delta(
        audio_chunk_bytes=ONE_SECOND_PCM16,
        event_id="event-1",
        item_id="item-1",
    )

    await recorder.stopped_playing_assistant_response(
        item_id="item-1",
        final_duration_ms=500,
    )

    assert "item-1" not in recorder.assistant_responses
    assert recorder.latest_active_assistant_response_item_id is None


@pytest.mark.asyncio
async def test_finalize_clamps_duration_to_started_chunks():
    recorder = make_recorder()

    for event_id in ("event-1", "event-2", "event-3"):
        await recorder.add_assistant_response_delta(
            audio_chunk_bytes=ONE_SECOND_PCM16,
            event_id=event_id,
            item_id="item-1",
        )
    await recorder.started_playing_assistant_response_delta(
        item_id="item-1",
        event_id="event-1",
        started_playing_at_ms=1_000,
    )
    await recorder.ended_playing_assistant_response_delta(
        item_id="item-1",
        event_id="event-1",
    )

    await recorder.finalize()
    await recorder.save_buffer()

    assert "item-1" not in recorder.assistant_responses
    assert get_write_count(recorder) > 0
    assert recorder.audio_duration == 1_000


def get_write_count(recorder: RealtimeRecorder) -> int:
    ffmpeg = recorder.ffmpeg
    assert ffmpeg is not None
    return len(cast_fake_ffmpeg(ffmpeg).stdin.writes)


def cast_fake_ffmpeg(ffmpeg: Any) -> FakeFfmpeg:
    assert isinstance(ffmpeg, FakeFfmpeg)
    return ffmpeg
