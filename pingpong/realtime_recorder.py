import asyncio
from bisect import bisect
from functools import wraps
import inspect
from io import BytesIO
import logging
import sys
from typing import Union

import pybase64

from pingpong.audio_store import LocalAudioUploadObject, S3AudioUploadObject
from pingpong.models import VoiceModeRecording

from .config import config
from pydantic import BaseModel, ConfigDict, Field
from pydub import AudioSegment
from sqlalchemy.ext.asyncio import AsyncSession

realtime_recorder_logger = logging.getLogger("audio_recorder")

AUDIO_SAMPLE_WIDTH = 2
AUDIO_FRAME_RATE = 24000
AUDIO_CHANNELS = 1
AUDIO_APPLICATION = "voip"
MIN_AUDIO_CHUNK_SIZE = 5 * 1024 * 1024  # S3 multipart minimum (except last)
AUDIO_SIZE_TO_READ = 4_096
STDIN_CHUNK_SIZE = 32_768


class UserAudioChunk(BaseModel):
    audio: AudioSegment
    ends_at: int

    model_config = ConfigDict(arbitrary_types_allowed=True)


class AssistantAudioChunk(BaseModel):
    audio: AudioSegment
    event_id: str
    starts_at: int | None = None

    model_config = ConfigDict(arbitrary_types_allowed=True)


class AssistantResponse(BaseModel):
    item_id: str
    starts_at: int | None = None
    duration: int
    complete: bool
    first_audio_chunk_event_id: str
    audio_chunks: dict[str, AssistantAudioChunk] = Field(default_factory=dict)
    prev: str | None = None

    model_config = ConfigDict(arbitrary_types_allowed=True)


def not_closed(func):
    """
    Decorator that skips the function if the recorder is closed,
    ffmpeg is not running, or audio_store_obj is not set.
    """
    if inspect.iscoroutinefunction(func):

        @wraps(func)
        async def async_wrapper(self, *args, **kwargs):
            if getattr(self, "closed", False):
                realtime_recorder_logger.warning(
                    f"Skipping {func.__name__} because the recorder is closed."
                )
                return None
            if getattr(self, "ffmpeg", None) is None:
                realtime_recorder_logger.exception(
                    f"Skipping {func.__name__} because ffmpeg is not running."
                )
                return None
            if getattr(self, "audio_store_obj", None) is None:
                realtime_recorder_logger.exception(
                    f"Skipping {func.__name__} because audio_store_obj is not set."
                )
                return None
            return await func(self, *args, **kwargs)

        return async_wrapper
    else:

        @wraps(func)
        def sync_wrapper(self, *args, **kwargs):
            if getattr(self, "closed", False):
                realtime_recorder_logger.warning(
                    f"Skipping {func.__name__} because the recorder is closed."
                )
                return None
            return func(self, *args, **kwargs)

        return sync_wrapper


class RealtimeRecorder:
    def __init__(
        self,
        audio_store_obj: Union[LocalAudioUploadObject, S3AudioUploadObject],
        audio_recording_id: str,
        thread_id: int,
        session: AsyncSession,
    ):
        self.user_audio: list[UserAudioChunk] = []
        self.save_lock = asyncio.Lock()
        self.assistant_responses: dict[str, AssistantResponse] = {}
        self.latest_active_assistant_response_item_id: str | None = None
        self.closed = False
        self.end_timestamp: int | None = None
        self.audio_duration: int = 0
        self.audio_store_obj = audio_store_obj
        self.audio_recording_id = audio_recording_id
        self.ffmpeg: asyncio.subprocess.Process | None = None
        self.upload_task: asyncio.Task | None = None
        self.thread_id = thread_id
        self.session = session
        self.should_save_audio = False

    @classmethod
    async def create(
        cls,
        thread_id: int,
        thread_obj_id: str,
        session: AsyncSession,
    ) -> "RealtimeRecorder":
        """
        Creates a new RealtimeRecorder instance.
        """
        audio_recording_id = f"realtime_recorder_{thread_obj_id}.webm"
        audio_store_obj = await config.audio_store.store.create_upload(
            name=audio_recording_id,
            content_type="audio/webm",
        )
        self = cls(
            audio_store_obj=audio_store_obj,
            audio_recording_id=audio_recording_id,
            thread_id=thread_id,
            session=session,
        )

        self.ffmpeg = await asyncio.create_subprocess_exec(
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "s16le",
            "-ar",
            str(AUDIO_FRAME_RATE),
            "-ac",
            str(AUDIO_CHANNELS),
            "-i",
            "pipe:0",
            "-c:a",
            "libopus",
            "-application",
            AUDIO_APPLICATION,
            "-f",
            "webm",
            "-live",
            "1",
            "-cluster_time_limit",
            "1000",
            "pipe:1",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        self.upload_task = asyncio.create_task(self._upload_ffmpeg_output())
        return self

    @not_closed
    async def _upload_ffmpeg_output(self) -> None:
        """
        Reads FFmpeg stdout, buffers ≥5 MiB, and uploads each as one part.
        """
        buf = BytesIO()
        if not self.ffmpeg or not self.ffmpeg.stdout:
            raise RuntimeError("FFmpeg process is not running.")
        try:
            while True:
                data = await self.ffmpeg.stdout.read(AUDIO_SIZE_TO_READ)
                if not data:
                    break
                buf.write(data)
                if buf.tell() >= MIN_AUDIO_CHUNK_SIZE:
                    await self.audio_store_obj.upload_part(content=buf)
                    buf.truncate(0)
                    buf.seek(0)
        finally:
            if buf.tell() > 0:
                await self.audio_store_obj.upload_part(content=buf)

    @not_closed
    async def _write_to_ffmpeg(self, data: bytes) -> None:
        if not self.ffmpeg or not self.ffmpeg.stdin:
            raise RuntimeError("FFmpeg process is not running.")

        view = memoryview(data)
        for pos in range(0, len(view), STDIN_CHUNK_SIZE):
            self.ffmpeg.stdin.write(view[pos : pos + STDIN_CHUNK_SIZE])
            await self.ffmpeg.stdin.drain()
            await asyncio.sleep(0)

    @not_closed
    async def add_user_audio(self, audio_chunk: bytes, timestamp: int):
        """
        Adds the user audio chunk and records the timestamp when it was sent from the browser.
        """

        async with self.save_lock:
            self.user_audio.append(
                UserAudioChunk(
                    audio=AudioSegment(
                        data=audio_chunk,
                        sample_width=AUDIO_SAMPLE_WIDTH,
                        frame_rate=AUDIO_FRAME_RATE,
                        channels=AUDIO_CHANNELS,
                    ),
                    ends_at=timestamp,
                )
            )

    @not_closed
    async def stopped_playing_assistant_response(
        self, item_id: str, final_duration_ms: int
    ):
        async with self.save_lock:
            self.assistant_responses[item_id].complete = True
            self.assistant_responses[item_id].duration = final_duration_ms

    @not_closed
    async def started_playing_assistant_response_delta(
        self, item_id: str, event_id: str, started_playing_at_ms: int
    ):
        async with self.save_lock:
            if not self.assistant_responses.get(item_id):
                realtime_recorder_logger.exception(
                    f"Started playing assistant response delta for item_id {item_id} but no such response exists."
                )
                return
            if not self.assistant_responses[item_id].audio_chunks.get(event_id):
                realtime_recorder_logger.exception(
                    f"Started playing assistant response delta for item_id {item_id} and event_id {event_id} but no such audio chunk exists."
                )
                return
            self.assistant_responses[item_id].audio_chunks[
                event_id
            ].starts_at = started_playing_at_ms
            if self.assistant_responses[item_id].first_audio_chunk_event_id == event_id:
                self.assistant_responses[item_id].starts_at = started_playing_at_ms

    @not_closed
    async def add_assistant_response_delta(
        self, b64_audio_chunk: str, event_id: str, item_id: str
    ):
        # Create an AudioSegment from the base64-encoded audio chunk
        audio_chunk = AudioSegment(
            data=pybase64.b64decode(b64_audio_chunk),
            sample_width=AUDIO_SAMPLE_WIDTH,
            frame_rate=AUDIO_FRAME_RATE,
            channels=AUDIO_CHANNELS,
        )

        async with self.save_lock:
            ## Store the audio chunk in the assistant responses
            ## CASE 1: First Assistant response in the block
            if not self.latest_active_assistant_response_item_id:
                # Create a new AssistantResponse object
                realtime_recorder_logger.debug(
                    f"Adding first assistant response delta for item_id {item_id} and event_id {event_id}"
                )
                self.assistant_responses[item_id] = AssistantResponse(
                    item_id=item_id,
                    starts_at=None,
                    duration=len(audio_chunk),
                    complete=False,
                    audio_chunks={
                        event_id: AssistantAudioChunk(
                            audio=audio_chunk, event_id=event_id, starts_at=None
                        )
                    },
                    first_audio_chunk_event_id=event_id,
                )
                self.latest_active_assistant_response_item_id = item_id
            else:
                ## CASE 2: Adding to an active response
                if (
                    item_id == self.latest_active_assistant_response_item_id
                    and not self.assistant_responses[item_id].complete
                ):
                    realtime_recorder_logger.debug(
                        f"Adding assistant response delta to active response for item_id {item_id} and event_id {event_id}"
                    )
                    self.assistant_responses[item_id].duration += len(audio_chunk)
                    self.assistant_responses[item_id].audio_chunks[event_id] = (
                        AssistantAudioChunk(
                            audio=audio_chunk, event_id=event_id, starts_at=None
                        )
                    )

                ## CASE 3: A new response has been received
                ## which is not the active one
                ## This means that the assistant has started a new response
                ## and the previous one is now complete
                elif (
                    item_id != self.latest_active_assistant_response_item_id
                    and item_id not in self.assistant_responses
                ):
                    realtime_recorder_logger.debug(
                        f"Received new assistant response delta for item_id {item_id} and event_id {event_id} while another response with item_id {self.latest_active_assistant_response_item_id} is active."
                    )

                    # Mark the previous response as complete
                    # Check that we have not already saved the previous response
                    if (
                        self.latest_active_assistant_response_item_id
                        in self.assistant_responses
                    ):
                        self.assistant_responses[
                            self.latest_active_assistant_response_item_id
                        ].complete = True

                    self.assistant_responses[item_id] = AssistantResponse(
                        item_id=item_id,
                        starts_at=None,
                        duration=len(audio_chunk),
                        complete=False,
                        audio_chunks={
                            event_id: AssistantAudioChunk(
                                audio=audio_chunk, event_id=event_id, starts_at=None
                            )
                        },
                        prev=self.latest_active_assistant_response_item_id,
                        first_audio_chunk_event_id=event_id,
                    )
                    self.latest_active_assistant_response_item_id = item_id
                else:
                    realtime_recorder_logger.exception(
                        f"Received assistant response delta for item_id {item_id} but no such response exists."
                    )
                    return

    @not_closed
    async def finalize(self):
        """
        Finalizes the current assistant response and saves the buffer.
        """
        async with self.save_lock:
            item_id = self.latest_active_assistant_response_item_id
            if not item_id:
                # No current assistant response to finalize.
                return

            response = self.assistant_responses.get(item_id)
            if not response:
                # Item id does not correspond to an existing response.
                return

            # Mark as complete.
            response.complete = True

            # Only retain played audio chunks.
            response.audio_chunks = {
                k: v
                for k, v in response.audio_chunks.items()
                if v.starts_at is not None
            }

    @not_closed
    async def save_buffer(self):
        """
        Saves the completed part of the buffer to a file.
        """
        async with self.save_lock:
            # Check if we have a current assistant response
            if not self.latest_active_assistant_response_item_id:
                # If we don't have a current assistant response,
                # we can't save anything.
                return
            realtime_recorder_logger.debug(
                f"Latest active assistant response item ID: {self.latest_active_assistant_response_item_id}"
            )
            current_assistant_response = self.assistant_responses.get(
                self.latest_active_assistant_response_item_id
            )
            if not current_assistant_response:
                # If we haven't received a single assistant response yet,
                # we can't save anything.
                realtime_recorder_logger.debug(
                    "No current assistant response found. Skipping save."
                )
                return

            if (
                not current_assistant_response.prev
                and not current_assistant_response.complete
            ):
                # If the current response is not complete and there's no
                # previous response, we can't save anything yet.
                realtime_recorder_logger.debug(
                    "Current assistant response is not complete and there's no previous response. Skipping save."
                )
                return

            # The last assistant response we will save to the file
            last_assistant_response: AssistantResponse | None = None
            if current_assistant_response.complete:
                last_assistant_response = current_assistant_response
            elif current_assistant_response.prev:
                last_assistant_response = self.assistant_responses.get(
                    current_assistant_response.prev
                )
            if not last_assistant_response:
                realtime_recorder_logger.debug(
                    "No last assistant response found. Skipping save."
                )
                return

            realtime_recorder_logger.debug(
                f"Last assistant response item ID: {last_assistant_response.item_id}"
            )

            if not last_assistant_response.starts_at:
                # If we don't have a start time for the last assistant response,
                # we can't save anything.
                # This can happen if the assistant response is not complete
                # and we haven't received the first audio chunk yet.
                realtime_recorder_logger.debug(
                    "Last assistant response has no start time. Skipping save."
                )
                return

            last_assistant_response_ends_at = (
                last_assistant_response.starts_at + last_assistant_response.duration
            )

            assistant_responses_to_save: list[AssistantResponse] = []
            item_ids_to_pop: list[str] = []
            for item_id, item in self.assistant_responses.items():
                if (
                    item.starts_at is None
                    or item.starts_at > last_assistant_response.starts_at
                ):
                    continue

                item_ids_to_pop.append(item_id)
                assistant_responses_to_save.append(item)

            for item_id in item_ids_to_pop:
                self.assistant_responses.pop(item_id)

            assistant_responses_to_save.sort(key=lambda x: x.starts_at)

            split_point = bisect(
                self.user_audio,
                last_assistant_response_ends_at,
                key=lambda chunk: chunk.ends_at,
            )

            user_audio_chunks_to_save, self.user_audio = (
                self.user_audio[:split_point],
                self.user_audio[split_point:],
            )

            if self.user_audio:
                next_user_audio_chunk_starts_at = self.user_audio[0].ends_at - len(
                    self.user_audio[0].audio
                )

                # If the last assistant response ends after the next user audio chunk starts,
                # we need to retrieve part of the user audio chunk to fit in the gap.
                if last_assistant_response_ends_at > next_user_audio_chunk_starts_at:
                    user_response_duration_needed = (
                        last_assistant_response_ends_at
                        - next_user_audio_chunk_starts_at
                    )
                    final_user_audio_chunk_to_save = self.user_audio[0]
                    self.user_audio[0] = UserAudioChunk(
                        audio=final_user_audio_chunk_to_save.audio[
                            user_response_duration_needed:
                        ],
                        ends_at=final_user_audio_chunk_to_save.ends_at,
                    )
                    user_audio_chunks_to_save.append(
                        UserAudioChunk(
                            audio=final_user_audio_chunk_to_save.audio[
                                :user_response_duration_needed
                            ],
                            ends_at=last_assistant_response_ends_at,
                        )
                    )

            # If this is the first time we are saving the buffer,
            # set the end timestamp to start of the earliest
            # (user or assistant) audio chunk
            if not self.end_timestamp:
                self.end_timestamp = min(
                    assistant_responses_to_save[0].starts_at
                    if assistant_responses_to_save[0].starts_at
                    else sys.maxsize,
                    user_audio_chunks_to_save[0].ends_at
                    - len(user_audio_chunks_to_save[0].audio),
                )

            # Calculate how long the buffer to save is
            buffer_to_save_duration = (
                last_assistant_response_ends_at - self.end_timestamp
            )

        if buffer_to_save_duration <= 0:
            return

        new_audio_segment = AudioSegment.silent(
            duration=buffer_to_save_duration, frame_rate=AUDIO_FRAME_RATE
        )

        # Overlay the user audio chunks on top of the silent audio segment
        for audio_chunk in user_audio_chunks_to_save:
            new_audio_segment = new_audio_segment.overlay(
                audio_chunk.audio,
                position=(
                    audio_chunk.ends_at - len(audio_chunk.audio) - self.end_timestamp
                ),
            )

        # Overlay the assistant audio chunks on top of the audio segment
        for response in assistant_responses_to_save:
            if response.starts_at is None:
                continue
            duration_so_far = 0.0
            # Sort the audio chunks by their start time
            for audio_chunk in sorted(
                [
                    x
                    for x in list(response.audio_chunks.values())
                    if x.starts_at is not None
                ],
                key=lambda x: x.starts_at if x.starts_at is not None else float("inf"),
            ):
                if not audio_chunk.starts_at:
                    realtime_recorder_logger.exception(
                        f"Audio chunk {audio_chunk.event_id} has no start time."
                    )
                    continue
                if duration_so_far + len(audio_chunk.audio) > response.duration:
                    # Assistant response was interrupted during this chunk
                    clipped_length = response.duration - duration_so_far

                    clipped_audio_chunk = audio_chunk.audio[:clipped_length]
                    new_audio_segment = new_audio_segment.overlay(
                        clipped_audio_chunk,
                        position=(audio_chunk.starts_at - self.end_timestamp),
                    )
                    break
                else:
                    new_audio_segment = new_audio_segment.overlay(
                        audio_chunk.audio,
                        position=(audio_chunk.starts_at - self.end_timestamp),
                    )
                    duration_so_far += len(audio_chunk.audio)

        # Export the audio segment to a file
        try:
            # Write the audio segment to FFmpeg's stdin
            await self._write_to_ffmpeg(new_audio_segment.raw_data)

            # Update the end timestamp to the last assistant response ends at
            self.end_timestamp = last_assistant_response_ends_at
            self.audio_duration += buffer_to_save_duration

            realtime_recorder_logger.debug(
                f"Saved {len(user_audio_chunks_to_save)} user audio chunks and {len(assistant_responses_to_save)} assistant audio chunks"
            )
        except Exception as e:
            realtime_recorder_logger.exception(f"Failed to save buffer: {e}")

    @not_closed
    async def complete_audio_upload(self):
        """
        Completes the audio upload.
        """
        # If we haven't added any messages to the thread,
        # we should delete the file from the audio store
        if not self.should_save_audio:
            realtime_recorder_logger.warning(
                "No audio to save, deleting the file from the audio store."
            )
            await self.audio_store_obj.delete_file()
            self.closed = True
            return

        # Finish bundling any responses or user audio still in RAM
        await self.finalize()
        await self.save_buffer()

        # Close FFmpeg's stdin so it processes the remaining clusters
        if not self.ffmpeg or not self.ffmpeg.stdin:
            raise RuntimeError("FFmpeg process is not running.")
        self.ffmpeg.stdin.close()
        await self.ffmpeg.wait()

        # Wait for the upload task to upload any tail data
        if self.upload_task:
            await self.upload_task

        # Complete the upload
        await self.audio_store_obj.complete_upload()

        # Save the recording metadata to the database
        try:
            await VoiceModeRecording.create(
                session=self.session,
                data={
                    "recording_id": self.audio_recording_id,
                    "thread_id": self.thread_id,
                    "duration": self.audio_duration,
                },
            )
        except Exception as e:
            realtime_recorder_logger.exception("Error saving VoiceModeRecording: %s", e)
            await self.audio_store_obj.delete_file()

        self.closed = True

    async def handle_saving_buffer(self, every: int = 5):
        try:
            while True:
                await asyncio.sleep(every)
                try:
                    await self.save_buffer()
                except Exception as e:
                    realtime_recorder_logger.exception("Error in save_buffer: %s", e)
        except asyncio.CancelledError:
            try:
                realtime_recorder_logger.debug(
                    "Received task cancellation signal. Saving buffer before closing."
                )
                await self.complete_audio_upload()
            except Exception as e:
                realtime_recorder_logger.exception("Error in save_buffer: %s", e)
            finally:
                raise
