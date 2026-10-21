import asyncio
import shutil
from types import SimpleNamespace
from unittest.mock import AsyncMock
from typing import Any

import pytest
from sqlalchemy import select

from pingpong import models, schemas
from pingpong.models import VoiceModeRecording
from pingpong.realtime_recorder import (
    RealtimeRecorder,
    VoiceRecordingHealth,
    make_audio_recording_id,
)


ONE_SECOND_PCM16 = b"\0" * 48_000


class FakeFfmpegStdin:
    def __init__(self):
        self.writes: list[bytes] = []
        self.closed = False
        self.on_close = lambda: None

    def write(self, data: bytes) -> None:
        self.writes.append(data)

    async def drain(self) -> None:
        pass

    def close(self) -> None:
        if self.closed:
            return
        self.closed = True
        self.on_close()


class FakeFfmpeg:
    def __init__(self):
        self.stdin = FakeFfmpegStdin()
        self.returncode = None
        self.exited = asyncio.Event()
        self.stdin.on_close = lambda: self.exit(0)

    def exit(self, code):
        if self.returncode is None:
            self.returncode = code
        self.exited.set()

    def kill(self):
        self.exit(-9)

    async def wait(self):
        await self.exited.wait()
        return self.returncode

    async def communicate(self):
        self.stdin.close()
        await self.wait()
        return b"", b""


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


async def test_health_flags_and_first_failure_details_are_sticky(db):
    health = VoiceRecordingHealth()
    health.fail(
        "recording", "save_buffer", BrokenPipeError(32, "secret URL"), "first.webm", 1
    )
    first = health.details["recording"].copy()
    health.fail("recording", "cleanup", RuntimeError("later error"), "first.webm", 1)
    health.fail("upload", "upload_part", OSError(5, "secret URL"), "first.webm", 1)
    async with db.async_session() as session:
        thread = models.Thread(thread_id="health-flags", version=3)
        session.add(thread)
        await session.flush()
        assert thread.recording_issue is False
        assert thread.upload_issue is False
        await health.persist(session, thread.id)
        await session.commit()
        thread_id = thread.id

    later = VoiceRecordingHealth()
    later.fail(
        "recording",
        "later_attempt",
        ValueError("another secret"),
        "later.webm",
        thread_id,
    )
    async with db.async_session() as session:
        await later.persist(session, thread_id)
        await VoiceRecordingHealth().persist(session, thread_id)
        await session.commit()
    async with db.async_session() as session:
        thread = await session.get(models.Thread, thread_id)
        assert thread.recording_issue and thread.upload_issue
        assert thread.recording_issue_details == first
        assert thread.recording_issue_details["error_code"] == 32
        assert thread.upload_issue_details["phase"] == "upload_part"
        assert "secret" not in str(thread.recording_issue_details)
        assert not (await session.scalars(select(VoiceModeRecording))).all()


@pytest.mark.parametrize("stage", ["upload", "encoder"])
async def test_recording_startup_failure_returns_without_recording(monkeypatch, stage):
    health = VoiceRecordingHealth()
    store = FakeAudioStoreObject()
    create_upload = AsyncMock(return_value=store)
    if stage == "upload":
        create_upload.side_effect = OSError(5, "storage unavailable")
    monkeypatch.setattr(
        "pingpong.realtime_recorder.config.audio_store.store.create_upload",
        create_upload,
    )
    monkeypatch.setattr(
        asyncio,
        "create_subprocess_exec",
        AsyncMock(side_effect=FileNotFoundError("ffmpeg")),
    )
    recorder = await RealtimeRecorder.create(1, "thread", None, health=health)
    assert recorder is None
    assert health.upload_issue == (stage == "upload")
    assert health.recording_issue == (stage == "encoder")
    assert store.deleted == (stage == "encoder")


@pytest.mark.parametrize("phase", ["write", "exit", "input"])
async def test_recording_failure_disables_buffers_and_reaps_worker(phase):
    recorder = make_recorder()
    ffmpeg = cast_fake_ffmpeg(recorder.ffmpeg)
    worker = asyncio.create_task(recorder.handle_saving_buffer(every=60))
    try:
        await recorder.add_user_audio(ONE_SECOND_PCM16, 2_000)
        await recorder.add_assistant_response_delta(ONE_SECOND_PCM16, "part", "reply")
        await recorder.started_playing_assistant_response_delta("reply", "part", 1_000)
        if phase == "exit":
            ffmpeg.exit(7)
        elif phase == "input":
            await recorder.add_user_audio(b"\0", 2_000)
        else:
            ffmpeg.stdin.drain = AsyncMock(side_effect=BrokenPipeError(32, "pipe"))
            await recorder.finalize()
            await recorder.save_buffer()
        await asyncio.wait_for(worker, 1)
        assert recorder.health.recording_issue
        assert not recorder.health.upload_issue
        if phase == "exit":
            assert recorder.health.details["recording"]["encoder_exit_code"] == 7
        assert recorder.closed
        assert not recorder.user_audio and not recorder.assistant_responses
        writes = len(ffmpeg.stdin.writes)
        await recorder.add_user_audio(ONE_SECOND_PCM16, 3_000)
        await recorder.add_assistant_response_delta(ONE_SECOND_PCM16, "next", "next")
        await recorder.save_buffer()
        assert not recorder.user_audio and not recorder.assistant_responses
        assert len(ffmpeg.stdin.writes) == writes
        assert recorder.audio_store_obj.deleted
    finally:
        worker.cancel()
        await asyncio.gather(worker, return_exceptions=True)


@pytest.mark.parametrize("failure_at", ["part", "final_part", "completion"])
async def test_upload_failures_are_flagged_without_retry_or_recording_row(
    monkeypatch, failure_at
):
    recorder = make_recorder()
    store = recorder.audio_store_obj
    store.upload_part = AsyncMock(side_effect=OSError(5, "upload failed"))
    stdout = asyncio.StreamReader()
    stdout.feed_data(b"encoded audio")
    stdout.feed_eof()
    recorder.ffmpeg.stdout = stdout
    if failure_at != "completion":
        monkeypatch.setattr(
            "pingpong.realtime_recorder.MIN_AUDIO_CHUNK_SIZE",
            1 if failure_at == "part" else 100,
        )
        recorder.upload_task = asyncio.create_task(recorder._upload_ffmpeg_output())
        await recorder.upload_task
    else:
        store.complete_upload = AsyncMock(side_effect=OSError(5, "completion failed"))
    await recorder.complete_audio_upload(has_played_audio=True)
    assert recorder.health.upload_issue
    assert not recorder.health.recording_issue
    assert recorder.health.details["upload"]["phase"] == (
        "complete_upload" if failure_at == "completion" else "upload_part"
    )
    assert store.upload_part.await_count == int(failure_at != "completion")
    assert store.deleted and recorder.closed


async def test_recording_cancellation_is_not_a_failure(monkeypatch):
    store = FakeAudioStoreObject()
    health = VoiceRecordingHealth()
    monkeypatch.setattr(
        "pingpong.realtime_recorder.config.audio_store.store.create_upload",
        AsyncMock(return_value=store),
    )
    monkeypatch.setattr(
        asyncio, "create_subprocess_exec", AsyncMock(side_effect=asyncio.CancelledError)
    )
    with pytest.raises(asyncio.CancelledError):
        await RealtimeRecorder.create(1, "thread", None, health=health)
    assert store.deleted
    assert not health.recording_issue and not health.upload_issue


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="FFmpeg is not installed")
@pytest.mark.parametrize("upload_fails", [False, True])
async def test_real_encoder_finalization_and_upload_failure(monkeypatch, upload_fails):
    recorder = make_recorder()
    recorder.session = FakeSession()
    encoded = bytearray()

    async def upload_part(content):
        encoded.extend(content.getvalue())
        if upload_fails:
            raise OSError(5, "storage failure")

    recorder.audio_store_obj.upload_part = upload_part
    monkeypatch.setattr(
        VoiceModeRecording,
        "create_or_replace_for_thread",
        AsyncMock(return_value=(SimpleNamespace(id=1), None)),
    )
    await recorder._start_encoder()
    try:
        await recorder.add_assistant_response_delta(ONE_SECOND_PCM16, "part", "reply")
        await recorder.started_playing_assistant_response_delta("reply", "part", 1_000)
        await recorder.ended_playing_assistant_response_delta("reply", "part")
        await asyncio.wait_for(recorder.complete_audio_upload(has_played_audio=True), 5)
        assert encoded
        assert recorder.closed
        assert recorder.ffmpeg.returncode is not None
        assert not recorder.health.recording_issue
        assert recorder.health.upload_issue == upload_fails
        assert recorder.audio_store_obj.completed == (not upload_fails)
        assert recorder.audio_store_obj.deleted == upload_fails
    finally:
        if not recorder.closed:
            await recorder.abort()


@pytest.mark.parametrize("blocked_operation", ["drain", "exit"])
async def test_upload_failure_unblocks_final_encoding_without_worker(
    monkeypatch, blocked_operation
):
    recorder = make_recorder()
    encoder = cast_fake_ffmpeg(recorder.ffmpeg)
    encoder.stdout = asyncio.StreamReader()
    recorder.audio_store_obj.upload_part = AsyncMock(side_effect=OSError(5, "upload"))
    recorder.upload_task = asyncio.create_task(recorder._upload_ffmpeg_output())
    monkeypatch.setattr("pingpong.realtime_recorder.MIN_AUDIO_CHUNK_SIZE", 1)

    def fail_upload():
        encoder.stdout.feed_data(b"encoded audio")
        encoder.stdout.feed_eof()

    if blocked_operation == "drain":

        async def drain():
            fail_upload()
            await asyncio.Future()

        encoder.stdin.drain = drain
        await recorder.add_assistant_response_delta(ONE_SECOND_PCM16, "part", "reply")
        await recorder.started_playing_assistant_response_delta("reply", "part", 1_000)
    else:
        # The uploader fails while the child is still running. Finalization
        # must wake and abort it instead of waiting on a pipe nobody drains.
        encoder.stdin.on_close = fail_upload

    await asyncio.wait_for(
        recorder.complete_audio_upload(has_played_audio=True),
        1,
    )
    assert recorder.closed and recorder.health.upload_issue
    assert not recorder.health.recording_issue
    assert encoder.returncode == -9


@pytest.mark.parametrize("encoder_error", [False, True])
async def test_unheard_recording_stops_writers_before_deleting(encoder_error):
    recorder = make_recorder()
    await recorder.add_user_audio(ONE_SECOND_PCM16, 2_000)
    store = recorder.audio_store_obj
    encoder_finished = asyncio.Event()
    upload_finished = asyncio.Event()

    async def finish_encoding():
        assert recorder.ffmpeg.stdin.closed
        if encoder_error:
            raise RuntimeError("encoder failed")
        encoder_finished.set()

    async def upload():
        try:
            await encoder_finished.wait()
        finally:
            upload_finished.set()

    async def delete():
        assert upload_finished.is_set()
        store.deleted = True

    recorder.ffmpeg.wait = finish_encoding
    store.delete_file = delete
    recorder.upload_task = asyncio.create_task(upload())
    # Ensure the uploader is running when shutdown begins.
    await asyncio.sleep(0)
    await recorder.complete_audio_upload(has_played_audio=False)
    assert recorder.health.recording_issue == encoder_error
    assert recorder.upload_task.done()
    assert recorder.closed
    assert store.deleted
    assert not store.completed
    assert get_write_count(recorder) == 0


@pytest.mark.parametrize("periodic_save", [False, True])
@pytest.mark.parametrize("overlap", [False, True])
@pytest.mark.parametrize("unheard_reply", [False, True])
async def test_complete_upload_preserves_trailing_user_audio(
    db, periodic_save, overlap, unheard_reply
):
    recorder = make_recorder()
    recorder.end_timestamp = None
    initial_user = b"\x01\x00" * 24_000
    assistant = b"\x02\x00" * 24_000
    trailing_user = b"\x03\x00" * 24_000
    tail_ends_at = 2_500 if overlap else 3_500
    await recorder.add_user_audio(initial_user, 1_000)
    await recorder.add_assistant_response_delta(assistant, "event-1", "item-1")
    await recorder.started_playing_assistant_response_delta("item-1", "event-1", 1_000)
    await recorder.ended_playing_assistant_response_delta("item-1", "event-1")
    await recorder.stopped_playing_assistant_response("item-1", 1_000)
    await recorder.add_user_audio(trailing_user, tail_ends_at)
    if periodic_save:
        await recorder.save_buffer()
        assert "item-1" not in recorder.assistant_responses
        assert recorder.end_timestamp == 2_000
        # A later idle save must not consume the tail or extend the file.
        await recorder.save_buffer()
        assert recorder.end_timestamp == 2_000
    if unheard_reply:
        await recorder.add_assistant_response_delta(
            b"\x09\x00" * 24_000, "event-unheard", "item-unheard"
        )

    async with db.async_session() as session:
        thread = models.Thread(thread_id="thread-tail", version=3)
        session.add(thread)
        await session.flush()
        recorder.thread_id = thread.id
        recorder.session = session
        await recorder.complete_audio_upload(has_played_audio=True)
        await session.commit()
        saved = await session.scalar(
            select(VoiceModeRecording).where(VoiceModeRecording.thread_id == thread.id)
        )
        assert saved is not None
        assert saved.duration == tail_ends_at

    if overlap:
        expected = (
            initial_user
            + assistant[:24_000]
            + b"\x05\x00" * 12_000
            + trailing_user[24_000:]
        )
    else:
        expected = initial_user + assistant + ONE_SECOND_PCM16[:24_000] + trailing_user
    assert b"".join(cast_fake_ffmpeg(recorder.ffmpeg).stdin.writes) == expected
    assert recorder.audio_duration == tail_ends_at
    assert recorder.end_timestamp == tail_ends_at
    assert not recorder.user_audio
    assert recorder.closed
    assert recorder.audio_store_obj.completed


@pytest.mark.parametrize(
    "stage,error", [("write", BrokenPipeError), ("drain", ConnectionResetError)]
)
async def test_tail_write_failure_preserves_prefix_and_failure_flags(
    db, monkeypatch, stage, error
):
    recorder = make_recorder()
    recorder.end_timestamp = None
    await recorder.add_user_audio(ONE_SECOND_PCM16, 1_000)
    await recorder.add_assistant_response_delta(ONE_SECOND_PCM16, "audio", "reply")
    await recorder.started_playing_assistant_response_delta("reply", "audio", 1_000)
    await recorder.stopped_playing_assistant_response("reply", 1_000)
    await recorder.save_buffer()
    assert recorder.audio_duration == 2_000
    await recorder.add_user_audio(ONE_SECOND_PCM16, 3_000)

    def fail_write(data):
        raise error("injected tail write failure")

    async def fail_drain():
        raise error("injected tail drain failure")

    monkeypatch.setattr(
        recorder.ffmpeg.stdin, stage, fail_write if stage == "write" else fail_drain
    )
    async with db.async_session() as session:
        thread = models.Thread(version=3)
        session.add(thread)
        await session.flush()
        recorder.thread_id = thread.id
        recorder.session = session
        await asyncio.wait_for(
            recorder.complete_audio_upload(has_played_audio=True), timeout=1
        )
        await recorder.health.persist(session, thread.id)
        await session.commit()
        await session.refresh(thread)
        recording = await session.scalar(
            select(VoiceModeRecording).where(VoiceModeRecording.thread_id == thread.id)
        )
        assert recording is not None
        assert recording.duration == 2_000
        assert thread.recording_issue and not thread.upload_issue
        assert thread.recording_issue_details["phase"] == "write_user_audio_tail"
    assert recorder.health.recording_issue
    assert not recorder.health.upload_issue
    assert recorder.health.details["recording"]["phase"] == "write_user_audio_tail"
    assert recorder.closed
    assert not recorder.audio_store_obj.deleted
    assert recorder.audio_store_obj.completed
    assert recorder.audio_duration == 2_000
    assert recorder.end_timestamp == 2_000
    assert cast_fake_ffmpeg(recorder.ffmpeg).returncode == 0


@pytest.mark.parametrize("prior_failure", [None, "recording", "upload"])
@pytest.mark.parametrize("delete_fails", [False, True])
async def test_discard_stops_uploader_first_and_keeps_existing_failures(
    prior_failure, delete_fails
):
    recorder = make_recorder()
    encoder = cast_fake_ffmpeg(recorder.ffmpeg)
    encoder.stdout = asyncio.StreamReader()

    def end_stream():
        encoder.exit(0)
        encoder.stdout.feed_data(b"discarded encoder tail")
        encoder.stdout.feed_eof()

    encoder.stdin.on_close = end_stream
    recorder.audio_store_obj.upload_part = AsyncMock(
        side_effect=OSError(5, "unused upload")
    )
    recorder.audio_store_obj.delete_file = AsyncMock(
        side_effect=OSError(5, "delete failed") if delete_fails else None
    )
    if prior_failure:
        recorder._fail(prior_failure, "earlier_failure", OSError(5, "earlier failure"))
    original_details = {
        kind: details.copy() for kind, details in recorder.health.details.items()
    }
    recorder.upload_task = asyncio.create_task(recorder._upload_ffmpeg_output())
    await asyncio.sleep(0)
    await asyncio.wait_for(recorder.complete_audio_upload(has_played_audio=False), 1)

    assert recorder.closed and recorder.upload_task.done()
    recorder.audio_store_obj.upload_part.assert_not_awaited()
    recorder.audio_store_obj.delete_file.assert_awaited_once()
    assert not recorder.audio_store_obj.completed
    assert recorder.health.recording_issue == (prior_failure == "recording")
    assert recorder.health.upload_issue == (prior_failure == "upload" or delete_fails)
    for kind, details in original_details.items():
        assert recorder.health.details[kind] == details
    if delete_fails and prior_failure != "upload":
        assert recorder.health.details["upload"]["phase"] == "abort_upload"


@pytest.mark.parametrize(
    "failure", ["encoder_exit", "encoder_timeout", "upload", "read_output"]
)
async def test_partial_recording_is_discarded_if_finalization_cannot_succeed(
    monkeypatch, failure
):
    recorder = make_recorder()
    recorder.audio_duration = 1_000
    recorder._fail("recording", "earlier_failure", ValueError("invalid audio"))
    encoder = cast_fake_ffmpeg(recorder.ffmpeg)
    if failure == "encoder_exit":
        encoder.exit(7)
    elif failure == "encoder_timeout":
        encoder.stdin.on_close = lambda: None
        monkeypatch.setattr(
            "pingpong.realtime_recorder.ENCODER_FINALIZATION_TIMEOUT_SECONDS", 0.01
        )
    elif failure == "upload":
        encoder.stdout = asyncio.StreamReader()
        recorder.audio_store_obj.upload_part = AsyncMock(
            side_effect=OSError(5, "upload failed")
        )

        def fail_upload():
            encoder.stdout.feed_data(b"encoded prefix")
            encoder.stdout.feed_eof()

        encoder.stdin.on_close = fail_upload
        recorder.upload_task = asyncio.create_task(recorder._upload_ffmpeg_output())
    else:
        encoder.stdout = SimpleNamespace(
            read=AsyncMock(side_effect=OSError("read failed"))
        )
        recorder.upload_task = asyncio.create_task(recorder._upload_ffmpeg_output())
    await asyncio.wait_for(recorder.complete_audio_upload(has_played_audio=True), 1)
    assert recorder.closed and recorder.audio_store_obj.deleted
    assert not recorder.audio_store_obj.completed
    assert recorder.health.recording_issue
    assert recorder.health.details["recording"]["phase"] == "earlier_failure"
    assert recorder.health.upload_issue == (failure == "upload")
    if failure == "upload":
        recorder.audio_store_obj.upload_part.assert_awaited_once()
        assert recorder.upload_task.done()


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="FFmpeg is not installed")
@pytest.mark.parametrize("has_played_audio", [False, True])
async def test_failed_worker_keeps_decodable_prefix_until_retention_is_decided(
    monkeypatch, has_played_audio
):
    recorder = make_recorder()
    recorder.session = FakeSession()
    encoded = bytearray()

    async def upload_part(content):
        encoded.extend(content.getvalue())

    recorder.audio_store_obj.upload_part = upload_part
    save_metadata = AsyncMock(return_value=(SimpleNamespace(id=1), None))
    monkeypatch.setattr(
        VoiceModeRecording, "create_or_replace_for_thread", save_metadata
    )
    await recorder._start_encoder()
    worker = asyncio.create_task(recorder.handle_saving_buffer(every=60))
    try:
        await recorder.add_assistant_response_delta(ONE_SECOND_PCM16, "part", "reply")
        await recorder.started_playing_assistant_response_delta("reply", "part", 1_000)
        await recorder.ended_playing_assistant_response_delta("reply", "part")
        await recorder.finalize()
        await recorder.save_buffer()
        assert recorder.audio_duration == 1_000
        await recorder.add_user_audio(b"\0", 3_000)
        await asyncio.wait_for(worker, 5)
        assert recorder.health.recording_issue and not recorder.health.upload_issue
        assert not recorder.closed and not recorder.audio_store_obj.deleted
        assert recorder.ffmpeg.returncode == 0
        await recorder.add_assistant_response_delta(ONE_SECOND_PCM16, "late", "later")
        assert not recorder.assistant_responses
        await asyncio.wait_for(
            recorder.complete_audio_upload(has_played_audio=has_played_audio), 5
        )
        assert recorder.closed
        assert recorder.audio_store_obj.completed == has_played_audio
        assert recorder.audio_store_obj.deleted == (not has_played_audio)
        assert recorder.health.recording_issue
        assert recorder.health.details["recording"]["phase"] == "add_user_audio"
        assert save_metadata.await_count == int(has_played_audio)
        if has_played_audio:
            assert save_metadata.await_args.kwargs["data"]["duration"] == 1_000
            decoder = await asyncio.create_subprocess_exec(
                "ffmpeg",
                "-v",
                "error",
                "-i",
                "pipe:0",
                "-f",
                "s16le",
                "-ar",
                "24000",
                "-ac",
                "1",
                "pipe:1",
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            pcm, errors = await asyncio.wait_for(decoder.communicate(bytes(encoded)), 5)
            assert decoder.returncode == 0, errors.decode()
            assert len(pcm) >= 24_000
    finally:
        worker.cancel()
        await asyncio.gather(worker, return_exceptions=True)
        if not recorder.closed:
            await recorder.abort()


async def test_first_assistant_save_preserves_existing_zero_boundary():
    recorder = make_recorder()
    recorder.end_timestamp = 0
    assistant_pcm = b"\x02\x00" * 24_000
    await recorder.add_assistant_response_delta(assistant_pcm, "event-1", "item-1")
    await recorder.started_playing_assistant_response_delta("item-1", "event-1", 1_000)
    await recorder.ended_playing_assistant_response_delta("item-1", "event-1")
    await recorder.stopped_playing_assistant_response("item-1", 1_000)

    await recorder.save_buffer()

    assert b"".join(cast_fake_ffmpeg(recorder.ffmpeg).stdin.writes) == (
        ONE_SECOND_PCM16 + assistant_pcm
    )
    assert recorder.audio_duration == 2_000
    assert recorder.end_timestamp == 2_000


@pytest.mark.parametrize("saved_until", [None, 0, 1_000, 1_500, 2_000])
async def test_final_user_audio_flush_respects_saved_boundary(db, saved_until):
    recorder = make_recorder()
    recorder.end_timestamp = saved_until
    recorder.audio_duration = saved_until or 0
    # An old late-arriving chunk must not be appended a second time. A chunk
    # crossing the saved boundary must contribute only its unsaved suffix.
    await recorder.add_user_audio(b"\x01\x00" * 24_000, 1_000)
    await recorder.add_user_audio(b"\x02\x00" * 24_000, 2_000)
    async with db.async_session() as session:
        thread = models.Thread(thread_id="thread-tail-boundary", version=3)
        session.add(thread)
        await session.flush()
        recorder.thread_id = thread.id
        recorder.session = session
        await recorder.complete_audio_upload(has_played_audio=True)

    expected = b"\x01\x00" * 24_000 + b"\x02\x00" * 24_000
    expected = expected[(saved_until or 0) * 48 :]
    assert b"".join(cast_fake_ffmpeg(recorder.ffmpeg).stdin.writes) == expected
    assert recorder.end_timestamp == 2_000
    assert recorder.audio_duration == 2_000
    assert not recorder.user_audio


@pytest.mark.parametrize("assistant_starts_at", [0, 1_000])
@pytest.mark.parametrize("user_timing", ["absent", "before", "after"])
@pytest.mark.parametrize("periodic_save", [False, True])
async def test_first_recording_save_uses_available_audio(
    db, assistant_starts_at, user_timing, periodic_save
):
    recorder = make_recorder()
    recorder.end_timestamp = None
    assistant_pcm = b"\x02\x00" * 24_000
    user_pcm = b"\x01\x00" * 24_000
    if user_timing == "before":
        await recorder.add_user_audio(user_pcm, assistant_starts_at)
    await recorder.add_assistant_response_delta(assistant_pcm, "event-1", "item-1")
    await recorder.started_playing_assistant_response_delta(
        "item-1", "event-1", assistant_starts_at
    )
    await recorder.ended_playing_assistant_response_delta("item-1", "event-1")
    await recorder.stopped_playing_assistant_response("item-1", 1_000)
    if user_timing == "after":
        await recorder.add_user_audio(user_pcm, assistant_starts_at + 2_500)

    expected = assistant_pcm
    if user_timing == "before":
        expected = user_pcm + expected
    elif user_timing == "after":
        expected += ONE_SECOND_PCM16[:24_000] + user_pcm
    expected_duration = len(expected) // 48
    if periodic_save:
        await recorder.save_buffer()
        assert "item-1" not in recorder.assistant_responses
        assert recorder.end_timestamp == assistant_starts_at + 1_000
        # Once saved, the same reply must not be encoded again.
        await recorder.save_buffer()

    async with db.async_session() as session:
        thread = models.Thread(thread_id="thread-first-recording-save", version=3)
        session.add(thread)
        await session.flush()
        recorder.thread_id = thread.id
        recorder.session = session
        await recorder.complete_audio_upload(has_played_audio=True)
        await session.commit()
        saved = await session.scalar(
            select(VoiceModeRecording).where(VoiceModeRecording.thread_id == thread.id)
        )
        assert saved is not None
        assert saved.duration == expected_duration

    assert b"".join(cast_fake_ffmpeg(recorder.ffmpeg).stdin.writes) == expected
    assert recorder.audio_duration == expected_duration
    assert not recorder.user_audio
    assert not recorder.assistant_responses
    assert recorder.closed
    assert recorder.audio_store_obj.completed


@pytest.mark.parametrize("first_start", [0, 1000])
@pytest.mark.parametrize("event_id", ["event-1", "event-2"])
@pytest.mark.parametrize("phase", ["playing", "ended", "truncated", "finalized"])
async def test_duplicate_playback_start_preserves_recording_timeline(
    first_start, event_id, phase
):
    recorder = make_recorder()
    for index, chunk_id in enumerate(("event-1", "event-2")):
        await recorder.add_assistant_response_delta(
            ONE_SECOND_PCM16, chunk_id, "item-1"
        )
        await recorder.started_playing_assistant_response_delta(
            "item-1", chunk_id, first_start + index * 1000
        )
    if phase == "ended":
        await recorder.ended_playing_assistant_response_delta("item-1", event_id)
    elif phase == "truncated":
        await recorder.stopped_playing_assistant_response(
            "item-1", final_duration_ms=1500
        )
    elif phase == "finalized":
        await recorder.finalize()
    response = recorder.assistant_responses["item-1"]

    def timeline():
        return (
            response.starts_at,
            response.duration,
            response.complete,
            response.truncated,
            {
                chunk_id: (chunk.starts_at, chunk.ended)
                for chunk_id, chunk in response.audio_chunks.items()
            },
        )

    before = timeline()
    await recorder.started_playing_assistant_response_delta(
        "item-1", event_id, first_start + 5000
    )
    if phase != "playing":
        await recorder.ended_playing_assistant_response_delta("item-1", event_id)
    assert timeline() == before


async def test_late_first_playback_start_is_accepted_after_end():
    recorder = make_recorder()
    await recorder.add_assistant_response_delta(ONE_SECOND_PCM16, "event-1", "item-1")
    await recorder.ended_playing_assistant_response_delta("item-1", "event-1")
    await recorder.ended_playing_assistant_response_delta("item-1", "event-1")
    await recorder.started_playing_assistant_response_delta("item-1", "event-1", 1000)
    await recorder.started_playing_assistant_response_delta("item-1", "event-1", 5000)
    response = recorder.assistant_responses["item-1"]
    assert response.starts_at == 1000
    assert response.audio_chunks["event-1"].starts_at == 1000
    assert response.audio_chunks["event-1"].ended


@pytest.mark.parametrize("duplicate_start", [500, 5000])
async def test_duplicate_playback_start_does_not_change_exported_audio_duration(
    duplicate_start,
):
    recorder = make_recorder()
    await recorder.add_assistant_response_delta(ONE_SECOND_PCM16, "event-1", "item-1")
    await recorder.started_playing_assistant_response_delta("item-1", "event-1", 1000)
    await recorder.ended_playing_assistant_response_delta("item-1", "event-1")
    await recorder.started_playing_assistant_response_delta(
        "item-1", "event-1", duplicate_start
    )
    await recorder.finalize()
    await recorder.save_buffer()
    assert recorder.audio_duration == 1000
    assert recorder.end_timestamp == 2000
    assert len(b"".join(cast_fake_ffmpeg(recorder.ffmpeg).stdin.writes)) == len(
        ONE_SECOND_PCM16
    )


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
        thread = models.Thread(thread_id="thread-create-or-replace", version=3)
        session.add(thread)
        await session.flush()

        existing = await VoiceModeRecording.create(
            session,
            {
                "thread_id": thread.id,
                "recording_id": "old.webm",
                "duration": 1000,
            },
        )
        existing_id = existing.id
        thread_id = thread.id
        await session.commit()

        (
            recording,
            previous_recording_id,
        ) = await VoiceModeRecording.create_or_replace_for_thread(
            session,
            {
                "thread_id": thread_id,
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
    recorder.audio_duration = 1000

    async def fail_create_or_replace_for_thread(cls, session, data):
        raise RuntimeError("metadata failed")

    monkeypatch.setattr(
        VoiceModeRecording,
        "create_or_replace_for_thread",
        classmethod(fail_create_or_replace_for_thread),
    )

    await recorder.complete_audio_upload(has_played_audio=True)

    assert audio_store_obj.completed
    assert not audio_store_obj.deleted
    assert recorder.closed


@pytest.mark.asyncio
async def test_recording_metadata_error_does_not_roll_back_transcript_messages(
    db,
    monkeypatch,
):
    async def fail_create_or_replace_for_thread(cls, session, data):
        raise RuntimeError("metadata failed")

    monkeypatch.setattr(
        VoiceModeRecording,
        "create_or_replace_for_thread",
        classmethod(fail_create_or_replace_for_thread),
    )

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
        recorder.audio_duration = 1000

        await recorder.complete_audio_upload(has_played_audio=True)
        await session.commit()
        message_id = message.id
        thread_id = thread.id

    async with db.async_session() as session:
        recording = await session.scalar(
            select(VoiceModeRecording).where(
                VoiceModeRecording.thread_id == thread_id,
            )
        )
        assert recording is None

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
