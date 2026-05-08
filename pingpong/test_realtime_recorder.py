from typing import Any

import pytest
from sqlalchemy import select

from pingpong import models, schemas
from pingpong.models import VoiceModeRecording
from pingpong.realtime_recorder import RealtimeRecorder, make_audio_recording_id


ONE_SECOND_PCM16 = b"\0" * 48_000


class FakeFfmpegStdin:
    def __init__(self):
        self.writes: list[bytes] = []
        self.closed = False

    def write(self, data: bytes) -> None:
        self.writes.append(data)

    async def drain(self) -> None:
        pass

    def close(self) -> None:
        self.closed = True


class FakeFfmpeg:
    def __init__(self):
        self.stdin = FakeFfmpegStdin()

    async def wait(self) -> None:
        pass


class FakeAudioStoreObject:
    def __init__(self):
        self.completed = False
        self.deleted = False

    async def complete_upload(self) -> None:
        self.completed = True

    async def delete_file(self) -> None:
        self.deleted = True


class FakeNestedTransaction:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False


class FakeSession:
    def begin_nested(self) -> FakeNestedTransaction:
        return FakeNestedTransaction()


def make_recorder() -> RealtimeRecorder:
    audio_store_obj = FakeAudioStoreObject()
    recorder = RealtimeRecorder(
        audio_store_obj=audio_store_obj,  # type: ignore[arg-type]
        audio_recording_id="test.webm",
        thread_id=1,
        session=None,  # type: ignore[arg-type]
    )
    recorder.ffmpeg = FakeFfmpeg()  # type: ignore[assignment]
    recorder.end_timestamp = 1_000
    return recorder


def test_make_audio_recording_id_keeps_thread_id_and_adds_unique_suffix():
    first = make_audio_recording_id("79169")
    second = make_audio_recording_id("79169")

    assert first.startswith("realtime_recorder_79169_")
    assert first.endswith(".webm")
    assert second.startswith("realtime_recorder_79169_")
    assert second.endswith(".webm")
    assert first != second


@pytest.mark.asyncio
async def test_create_or_replace_for_thread_updates_existing_recording(db):
    async with db.async_session() as session:
        existing = await VoiceModeRecording.create(
            session,
            {
                "thread_id": 123,
                "recording_id": "old.webm",
                "duration": 1000,
            },
        )
        existing_id = existing.id
        await session.commit()

        (
            recording,
            previous_recording_id,
        ) = await VoiceModeRecording.create_or_replace_for_thread(
            session,
            {
                "thread_id": 123,
                "recording_id": "new.webm",
                "duration": 2000,
            },
        )
        await session.commit()

        assert recording.id == existing_id
        assert previous_recording_id == "old.webm"

    async with db.async_session() as session:
        recording = await session.get(VoiceModeRecording, existing_id)
        assert recording is not None
        assert recording.recording_id == "new.webm"
        assert recording.duration == 2000


@pytest.mark.asyncio
async def test_complete_audio_upload_keeps_completed_object_on_metadata_error(
    monkeypatch,
):
    recorder = make_recorder()
    audio_store_obj = recorder.audio_store_obj
    assert isinstance(audio_store_obj, FakeAudioStoreObject)
    recorder.session = FakeSession()  # type: ignore[assignment]
    recorder.should_save_audio = True
    recorder.audio_duration = 1000

    async def fail_create_or_replace_for_thread(cls, session, data):
        raise RuntimeError("metadata failed")

    monkeypatch.setattr(
        VoiceModeRecording,
        "create_or_replace_for_thread",
        classmethod(fail_create_or_replace_for_thread),
    )

    await recorder.complete_audio_upload()

    assert audio_store_obj.completed
    assert not audio_store_obj.deleted
    assert recorder.closed


@pytest.mark.asyncio
async def test_recording_metadata_error_does_not_roll_back_transcript_messages(db):
    async with db.async_session() as session:
        await VoiceModeRecording.create(
            session,
            {
                "thread_id": 999,
                "recording_id": "test.webm",
                "duration": 500,
            },
        )
        await session.commit()

    async with db.async_session() as session:
        thread = models.Thread(thread_id="thread-recording-savepoint", version=3)
        session.add(thread)
        await session.flush()

        run = models.Run(status=schemas.RunStatus.COMPLETED, thread_id=thread.id)
        session.add(run)
        await session.flush()

        message = await models.Message.create(
            session,
            {
                "message_id": "item-1",
                "message_status": schemas.MessageStatus.COMPLETED,
                "run_id": run.id,
                "thread_id": thread.id,
                "output_index": 1,
                "role": schemas.MessageRole.USER,
            },
        )
        await models.MessagePart.create(
            session,
            {
                "message_id": message.id,
                "part_index": 0,
                "type": schemas.MessagePartType.INPUT_TEXT,
                "text": "hello",
            },
        )

        recorder = make_recorder()
        audio_store_obj = recorder.audio_store_obj
        assert isinstance(audio_store_obj, FakeAudioStoreObject)
        recorder.session = session
        recorder.thread_id = thread.id
        recorder.should_save_audio = True
        recorder.audio_duration = 1000

        await recorder.complete_audio_upload()
        await session.commit()
        message_id = message.id

    async with db.async_session() as session:
        saved_message = await session.get(models.Message, message_id)
        assert saved_message is not None
        assert saved_message.message_id == "item-1"
        saved_message_part = await session.scalar(
            select(models.MessagePart).where(
                models.MessagePart.message_id == message_id
            )
        )
        assert saved_message_part is not None
        assert saved_message_part.text == "hello"


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
