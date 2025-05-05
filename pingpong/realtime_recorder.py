import asyncio
import base64
import logging
import time

from pydantic import BaseModel, ConfigDict
from pydub import AudioSegment

realtime_recorder_logger = logging.getLogger("audio_recorder")


class AudioChunk(BaseModel):
    audio: AudioSegment
    timestamp: float

    model_config = ConfigDict(arbitrary_types_allowed=True)


class AssistantResponse(BaseModel):
    item_id: str
    starts_at: float
    duration: float
    complete: bool
    audio_chunks: list[AudioSegment] = []
    prev: str | None = None
    completed_at: float | None = None

    model_config = ConfigDict(arbitrary_types_allowed=True)


class RealtimeRecorder:
    def __init__(self):
        self.user_audio: list[AudioChunk] = []
        self.assistant_responses: dict[str, AssistantResponse] = {}
        self.latest_active_assistant_response_item_id: str | None = None
        self.closed = False
        self.save_lock = asyncio.Lock()
        self.end_timestamp = time.monotonic()

    def add_user_audio(self, audio_chunk: bytes, timestamp: float):
        self.user_audio.append(
            AudioChunk(
                audio=AudioSegment(
                    data=audio_chunk,
                    sample_width=2,
                    frame_rate=24000,
                    channels=1,
                ),
                timestamp=timestamp,
            )
        )

    def add_assistant_audio(self, b64_audio_chunk: str, timestamp: float, item_id: str):
        audio_chunk = AudioSegment(
            data=base64.b64decode(b64_audio_chunk),
            sample_width=2,
            frame_rate=24000,
            channels=1,
        )

        ## CASE 1: First Assistant response in the block
        if not self.latest_active_assistant_response_item_id:
            self.assistant_responses[item_id] = AssistantResponse(
                item_id=item_id,
                starts_at=timestamp,
                duration=audio_chunk.duration_seconds,
                complete=False,
                audio_chunks=[audio_chunk],
            )
            self.latest_active_assistant_response_item_id = item_id
        else:
            ## CASE 2: Adding to an already active response
            if (
                item_id == self.latest_active_assistant_response_item_id
                and not self.assistant_responses[item_id].complete
            ):
                self.assistant_responses[
                    item_id
                ].duration += audio_chunk.duration_seconds
                self.assistant_responses[item_id].audio_chunks.append(audio_chunk)
            ## CASE 3: A new response has been received
            elif item_id != self.latest_active_assistant_response_item_id:
                self.assistant_responses[
                    self.latest_active_assistant_response_item_id
                ].complete = True

                self.assistant_responses[item_id] = AssistantResponse(
                    item_id=item_id,
                    starts_at=timestamp,
                    duration=audio_chunk.duration_seconds,
                    complete=False,
                    audio_chunks=[audio_chunk],
                    prev=self.latest_active_assistant_response_item_id,
                )
                self.latest_active_assistant_response_item_id = item_id

    def stop_assistant_response(self, timestamp: float):
        if (
            self.latest_active_assistant_response_item_id
            and not self.assistant_responses[
                self.latest_active_assistant_response_item_id
            ].complete
        ):
            self.assistant_responses[
                self.latest_active_assistant_response_item_id
            ].complete = True
            self.assistant_responses[
                self.latest_active_assistant_response_item_id
            ].completed_at = timestamp

    async def save_buffer(self):
        if self.closed:
            return

        async with self.save_lock:
            current_response = self.assistant_responses.get(
                self.latest_active_assistant_response_item_id
            )
            if not current_response:
                return

            if not current_response.prev:
                return

            # Get the previous assistant response
            prev_response = self.assistant_responses.get(current_response.prev)
            if not prev_response:
                return

            extracted_responses = [
                resp
                for key, resp in list(self.assistant_responses.items())
                if resp.starts_at <= prev_response.starts_at
            ]

            # Remove them from the dict
            for resp in extracted_responses:
                self.assistant_responses.pop(resp.item_id, None)

            # Sort the extracted responses by starts_at
            extracted_responses.sort(key=lambda r: r.starts_at)

            if prev_response.completed_at and (
                prev_response.starts_at + prev_response.duration
                > prev_response.completed_at
            ):
                end_of_prev_response = prev_response.completed_at
            else:
                end_of_prev_response = prev_response.starts_at + prev_response.duration

            # Extract user audio where timestamp < prev_response.starts_at
            extracted_user_audio = [
                chunk
                for chunk in self.user_audio
                if (chunk.timestamp + chunk.audio.duration_seconds)
                < prev_response.starts_at
            ]

            # Remove them from the list
            self.user_audio = [
                chunk
                for chunk in self.user_audio
                if (chunk.timestamp + chunk.audio.duration_seconds)
                >= prev_response.starts_at
            ]

            # Sort the extracted audio by timestamp
            extracted_user_audio.sort(key=lambda c: c.timestamp)

            new_clip_duration = end_of_prev_response - self.end_timestamp

            if new_clip_duration <= 0:
                return

            # Create a new audio segment with the new clip duration
            new_audio_segment = AudioSegment.silent(
                duration=new_clip_duration * 1000, frame_rate=24000
            )

            for audio_chunk in extracted_user_audio:
                new_audio_segment = new_audio_segment.overlay(
                    audio_chunk.audio,
                    position=(audio_chunk.timestamp - self.end_timestamp) * 1000,
                )

            for response in extracted_responses:
                duration_so_far = 0
                for audio_chunk in response.audio_chunks:
                    if (
                        response.starts_at
                        + duration_so_far
                        + audio_chunk.duration_seconds
                        > response.completed_at
                    ):
                        clipped_length = response.completed_at - (
                            response.starts_at + duration_so_far
                        )
                        clipped_audio_chunk = audio_chunk[:clipped_length]
                        new_audio_segment = new_audio_segment.overlay(
                            clipped_audio_chunk,
                            position=(
                                response.starts_at
                                + duration_so_far
                                - self.end_timestamp
                            )
                            * 1000,
                        )
                        break
                    else:
                        new_audio_segment = new_audio_segment.overlay(
                            audio_chunk,
                            position=(
                                response.starts_at
                                + duration_so_far
                                - self.end_timestamp
                            )
                            * 1000,
                        )
                        duration_so_far += audio_chunk.duration_seconds

            # Save the new audio segment to a file
            new_audio_segment.export(f"output_{self.end_timestamp}.wav", format="wav")
            self.end_timestamp = end_of_prev_response
            realtime_recorder_logger.info(
                f"Saved {len(extracted_user_audio)} user audio chunks and {len(extracted_responses)} assistant audio chunks"
            )
