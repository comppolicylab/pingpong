import asyncio
import base64
import logging

from pydantic import BaseModel, ConfigDict, Field
from pydub import AudioSegment

realtime_recorder_logger = logging.getLogger("audio_recorder")

AUDIO_SAMPLE_WIDTH = 2
AUDIO_FRAME_RATE = 24000
AUDIO_CHANNELS = 1


class UserAudioChunk(BaseModel):
    audio: AudioSegment
    ends_at: float

    model_config = ConfigDict(arbitrary_types_allowed=True)


class AssistantAudioChunk(BaseModel):
    audio: AudioSegment
    event_id: str
    starts_at: float | None = None

    model_config = ConfigDict(arbitrary_types_allowed=True)


class AssistantResponse(BaseModel):
    item_id: str
    starts_at: float | None = None
    duration: float
    complete: bool
    first_audio_chunk_event_id: str
    audio_chunks: dict[str, AssistantAudioChunk] = Field(default_factory=dict)
    prev: str | None = None

    model_config = ConfigDict(arbitrary_types_allowed=True)


class RealtimeRecorder:
    def __init__(self):
        self.user_audio: list[UserAudioChunk] = []
        self.user_audio_lock = asyncio.Lock()
        self.assistant_responses: dict[str, AssistantResponse] = {}
        self.latest_active_assistant_response_item_id: str | None = None
        self.closed = False
        self.assistant_responses_lock = asyncio.Lock()
        self.end_timestamp: float | None = None

    async def add_user_audio(self, audio_chunk: bytes, timestamp: float):
        """
        Adds the user audio chunk and records the timestamp when it was sent from the browser.
        """
        if self.closed:
            return

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

    async def stopped_playing_assistant_response(
        self, item_id: str, final_duration_ms: float
    ):
        if self.closed:
            return

        async with self.assistant_responses_lock:
            self.assistant_responses[item_id].complete = True
            self.assistant_responses[item_id].duration = final_duration_ms

    async def started_playing_assistant_response_delta(
        self, item_id: str, event_id: str, started_playing_at_ms: float
    ):
        if self.closed:
            return

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
        self, b64_audio_chunk: str, event_id: str, item_id: str
    ):
        if self.closed:
            return

        # Create an AudioSegment from the base64-encoded audio chunk
        audio_chunk = AudioSegment(
            data=base64.b64decode(b64_audio_chunk),
            sample_width=AUDIO_SAMPLE_WIDTH,
            frame_rate=AUDIO_FRAME_RATE,
            channels=AUDIO_CHANNELS,
        )

        async with self.assistant_responses_lock:
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

    async def finalize(self):
        """
        Finalizes the current assistant response and saves the buffer.
        """
        if self.closed:
            return

        async with self.assistant_responses_lock:
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

    async def save_buffer(self):
        """
        Saves the completed part of the buffer to a file.
        """
        if self.closed:
            return

        async with self.assistant_responses_lock:
            async with self.user_audio_lock:
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
                    return

                if (
                    not current_assistant_response.prev
                    and not current_assistant_response.complete
                ):
                    # If the current response is not complete and there's no
                    # previous response, we can't save anything yet.
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
                    return

                realtime_recorder_logger.debug(
                    f"Last assistant response item ID: {last_assistant_response.item_id}"
                )

                if not last_assistant_response.starts_at:
                    # If we don't have a start time for the last assistant response,
                    # we can't save anything.
                    # This can happen if the assistant response is not complete
                    # and we haven't received the first audio chunk yet.
                    return

                last_assistant_response_ends_at = (
                    last_assistant_response.starts_at + last_assistant_response.duration
                )

                assistance_responses_to_save = [
                    resp
                    for _, resp in list(self.assistant_responses.items())
                    if resp.starts_at is not None
                    and resp.starts_at <= last_assistant_response.starts_at
                ]

                for resp in assistance_responses_to_save:
                    self.assistant_responses.pop(resp.item_id, None)

                assistance_responses_to_save.sort(
                    key=lambda r: r.starts_at
                    if r.starts_at is not None
                    else float("inf")
                )

                user_audio_chunks_to_save = [
                    chunk
                    for chunk in self.user_audio
                    if chunk.ends_at <= last_assistant_response_ends_at
                ]

                # List is sorted by timestamp
                self.user_audio = self.user_audio[len(user_audio_chunks_to_save) :]

                if self.user_audio:
                    next_user_audio_chunk_starts_at = self.user_audio[0].ends_at - len(
                        self.user_audio[0].audio
                    )

                    # If the last assistant response ends after the next user audio chunk starts,
                    # we need to retrieve part of the user audio chunk to fit in the gap.
                    if (
                        last_assistant_response_ends_at
                        > next_user_audio_chunk_starts_at
                    ):
                        user_response_duration_needed = int(
                            last_assistant_response_ends_at
                            - next_user_audio_chunk_starts_at
                        )
                        final_user_audio_chunk_to_save = self.user_audio.pop(0)
                        self.user_audio.insert(
                            0,
                            UserAudioChunk(
                                audio=final_user_audio_chunk_to_save.audio[
                                    user_response_duration_needed:
                                ],
                                ends_at=next_user_audio_chunk_starts_at
                                + user_response_duration_needed,
                            ),
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
                        assistance_responses_to_save[0].starts_at
                        if assistance_responses_to_save[0].starts_at
                        else float("inf"),
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
                    duration=buffer_to_save_duration, frame_rate=24000
                )

                # Overlay the user audio chunks on top of the silent audio segment
                for audio_chunk in user_audio_chunks_to_save:
                    new_audio_segment = new_audio_segment.overlay(
                        audio_chunk.audio,
                        position=(
                            audio_chunk.ends_at
                            - len(audio_chunk.audio)
                            - self.end_timestamp
                        ),
                    )

                # Overlay the assistant audio chunks on top of the audio segment
                for response in assistance_responses_to_save:
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
                        key=lambda x: x.starts_at
                        if x.starts_at is not None
                        else float("inf"),
                    ):
                        if not audio_chunk.starts_at:
                            realtime_recorder_logger.exception(
                                f"Audio chunk {audio_chunk.event_id} has no start time."
                            )
                            continue
                        if duration_so_far + len(audio_chunk.audio) > response.duration:
                            # Assistant response was interrupted during this chunk
                            clipped_length = int(response.duration - duration_so_far)

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
                    new_audio_segment.export(
                        f"output_{self.end_timestamp}.wav", format="wav"
                    )
                    self.end_timestamp = last_assistant_response_ends_at
                    realtime_recorder_logger.debug(
                        f"Saved {len(user_audio_chunks_to_save)} user audio chunks and {len(assistance_responses_to_save)} assistant audio chunks"
                    )
                except Exception as e:
                    realtime_recorder_logger.exception(f"Failed to save buffer: {e}")
