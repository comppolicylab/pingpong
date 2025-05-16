import asyncio
import base64
import logging
import time
import uuid

from pydantic import BaseModel, ConfigDict
from pydub import AudioSegment

realtime_recorder_logger = logging.getLogger("audio_recorder")


class UserAudioChunk(BaseModel):
    id: str
    audio: AudioSegment
    ends_at: float
    prev: str | None = None

    model_config = ConfigDict(arbitrary_types_allowed=True)


class AssistantAudioChunk(BaseModel):
    audio: AudioSegment
    event_id: str
    starts_at: float | None = None

    model_config = ConfigDict(arbitrary_types_allowed=True)


class AssistantResponse(BaseModel):
    item_id: str
    starts_at: float
    duration: float
    complete: bool
    first_audio_chunk_event_id: str
    audio_chunks: dict[str, AssistantAudioChunk] = {}
    prev: str | None = None

    model_config = ConfigDict(arbitrary_types_allowed=True)


class RealtimeRecorder:
    def __init__(self):
        self.user_audio: list[UserAudioChunk] = []
        self.user_audio_lock = asyncio.Lock()
        self.latest_user_audio_chunk_id: str | None = None
        self.assistant_responses: dict[str, AssistantResponse] = {}
        self.latest_active_assistant_response_item_id: str | None = None
        self.closed = False
        self.assistant_responses_lock = asyncio.Lock()
        self.end_timestamp = time.monotonic()

    async def add_user_audio(self, audio_chunk: bytes, timestamp: float):
        """
        Adds the user audio chunk and records the timestamp when it was sent from the browser.
        """
        if self.closed:
            return
        
        # realtime_recorder_logger.info(
        #     f"Adding user audio chunk of length {len(audio_chunk)} at timestamp {timestamp}"
        # )

        user_audio_chunk_id = str(uuid.uuid4())
        async with self.user_audio_lock:
            if self.latest_user_audio_chunk_id:
                self.user_audio.append(
                    UserAudioChunk(
                        id=user_audio_chunk_id,
                        audio=AudioSegment(
                            data=audio_chunk,
                            sample_width=2,
                            frame_rate=24000,
                            channels=1,
                        ),
                        ends_at=timestamp,
                        prev=self.latest_user_audio_chunk_id,
                    )
                )
                self.latest_user_audio_chunk_id = user_audio_chunk_id
            else:
                self.user_audio.append(
                    UserAudioChunk(
                        id=user_audio_chunk_id,
                        audio=AudioSegment(
                            data=audio_chunk,
                            sample_width=2,
                            frame_rate=24000,
                            channels=1,
                        ),
                        ends_at=timestamp,
                    )
                )
                self.latest_user_audio_chunk_id = user_audio_chunk_id

    async def stopped_playing_assistant_response(
        self, item_id: str, final_duration_ms: float
    ):
        if self.closed:
            return
        realtime_recorder_logger.info(
            f"Stopped playing assistant response for item_id {item_id} with duration {final_duration_ms}"
        )
        async with self.assistant_responses_lock:
            self.assistant_responses[item_id].complete = True
            self.assistant_responses[item_id].duration = final_duration_ms

    async def started_playing_assistant_response_delta(
        self, item_id: str, event_id: str, started_playing_at_ms: float
    ):
        if self.closed:
            return
        realtime_recorder_logger.info(
            f"Started playing assistant response delta for item_id {item_id} and event_id {event_id} at {started_playing_at_ms}"
        )
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
        async with self.assistant_responses_lock:
            self.assistant_responses[item_id].audio_chunks[
                event_id
            ].starts_at = started_playing_at_ms
            if self.assistant_responses[item_id].first_audio_chunk_event_id == event_id:
                self.assistant_responses[item_id].starts_at = started_playing_at_ms

    async def add_assistant_response_delta(
        self, b64_audio_chunk: str, event_id: str, item_id: str, current_time: float
    ):
        if self.closed:
            return
        # Create an AudioSegment from the base64-encoded audio chunk
        audio_chunk = AudioSegment(
            data=base64.b64decode(b64_audio_chunk),
            sample_width=2,
            frame_rate=24000,
            channels=1,
        )
        async with self.assistant_responses_lock:
            ## Store the audio chunk in the assistant responses
            ## CASE 1: First Assistant response in the block
            if not self.latest_active_assistant_response_item_id:
                # Create a new AssistantResponse object
                self.assistant_responses[item_id] = AssistantResponse(
                    item_id=item_id,
                    starts_at=current_time,
                    duration=audio_chunk.duration_seconds,
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
                    self.assistant_responses[
                        item_id
                    ].duration += audio_chunk.duration_seconds
                    self.assistant_responses[item_id].audio_chunks[event_id] = (
                        AssistantAudioChunk(
                            audio=audio_chunk, event_id=event_id, starts_at=None
                        )
                    )

                ## CASE 3: A new response has been received
                ## which is not the active one
                elif (
                    item_id != self.latest_active_assistant_response_item_id
                    and item_id not in self.assistant_responses
                ):
                    self.assistant_responses[
                        self.latest_active_assistant_response_item_id
                    ].complete = True

                    self.assistant_responses[item_id] = AssistantResponse(
                        item_id=item_id,
                        starts_at=current_time,
                        duration=audio_chunk.duration_seconds,
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

    async def save_buffer(self):
        if self.closed:
            return

        async with self.assistant_responses_lock:
            async with self.user_audio_lock:
                current_assistant_response = self.assistant_responses.get(
                    self.latest_active_assistant_response_item_id
                )
                if not current_assistant_response:
                    return

                if (
                    not current_assistant_response.prev
                    and not current_assistant_response.complete
                ):
                    # If the current response is not complete and has no previous
                    # response, we can't save anything yet.
                    return

                last_assistant_response: AssistantResponse | None = None
                if current_assistant_response.complete:
                    last_assistant_response = current_assistant_response
                else:
                    last_assistant_response = self.assistant_responses.get(
                        current_assistant_response.prev
                    )
                if not last_assistant_response:
                    return

                last_assistant_response_ends_at = (
                    last_assistant_response.starts_at + last_assistant_response.duration
                )

                extracted_responses = [
                    resp
                    for _, resp in list(self.assistant_responses.items())
                    if resp.starts_at <= last_assistant_response.starts_at
                ]

                for resp in extracted_responses:
                    self.assistant_responses.pop(resp.item_id, None)

                extracted_responses.sort(key=lambda r: r.starts_at)

                extracted_user_audio = [
                    chunk
                    for chunk in self.user_audio
                    if chunk.ends_at <= last_assistant_response_ends_at
                ]

                # List is sorted by timestamp
                self.user_audio = self.user_audio[len(extracted_user_audio) :]
                final_user_audio_chunk = self.user_audio.pop(0)

                user_response_starts_at = (
                    final_user_audio_chunk.ends_at
                    - final_user_audio_chunk.audio.duration_seconds * 1000
                )
                user_response_duration_needed = (
                    last_assistant_response_ends_at - user_response_starts_at
                )

                self.user_audio.insert(
                    0,
                    UserAudioChunk(
                        id=final_user_audio_chunk.id,
                        audio=final_user_audio_chunk.audio[
                            user_response_duration_needed:
                        ],
                        ends_at=user_response_starts_at,
                    ),
                )
                extracted_user_audio.append(
                    UserAudioChunk(
                        id=final_user_audio_chunk.id,
                        audio=final_user_audio_chunk.audio[
                            :user_response_duration_needed
                        ],
                        ends_at=last_assistant_response_ends_at,
                    )
                )

                new_clip_duration = last_assistant_response_ends_at - self.end_timestamp

                if new_clip_duration <= 0:
                    return

                new_audio_segment = AudioSegment.silent(
                    duration=new_clip_duration, frame_rate=24000
                )

                for audio_chunk in extracted_user_audio:
                    new_audio_segment = new_audio_segment.overlay(
                        audio_chunk.audio,
                        position=(
                            audio_chunk.ends_at
                            - audio_chunk.audio.duration_seconds * 1000
                            - self.end_timestamp
                        ),
                    )

                for response in extracted_responses:
                    duration_so_far = 0.0
                    for audio_chunk in sorted(
                        [
                            x
                            for x in list(response.audio_chunks.values())
                            if x.starts_at is not None
                        ],
                        key=lambda x: x.starts_at,
                    ):
                        if (
                            duration_so_far + audio_chunk.audio.duration_seconds * 1000
                            > response.duration
                        ):
                            clipped_length = response.duration - duration_so_far

                            clipped_audio_chunk = audio_chunk[:clipped_length]
                            new_audio_segment = new_audio_segment.overlay(
                                clipped_audio_chunk,
                                position=(audio_chunk.starts_at - self.end_timestamp),
                            )
                            break
                        else:
                            new_audio_segment = new_audio_segment.overlay(
                                audio_chunk,
                                position=(audio_chunk.starts_at - self.end_timestamp),
                            )
                            duration_so_far += audio_chunk.duration_seconds * 1000

                new_audio_segment.export(
                    f"output_{self.end_timestamp}.wav", format="wav"
                )
                self.end_timestamp = last_assistant_response_ends_at
                realtime_recorder_logger.info(
                    f"Saved {len(extracted_user_audio)} user audio chunks and {len(extracted_responses)} assistant audio chunks"
                )
