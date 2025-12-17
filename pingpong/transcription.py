import io
import json
import logging
import os
import tempfile
from datetime import datetime, timezone

import openai
from openai.types.audio.transcription_diarized import TranscriptionDiarized

import pingpong.models as models
from pingpong.auth import encode_auth_token
from pingpong.config import config
from pingpong.invite import send_transcription_download, send_transcription_failed
from pingpong.now import NowFn, utcnow
from pingpong.schemas import DownloadExport

logger = logging.getLogger(__name__)


def _format_mmss(seconds: float) -> str:
    total_seconds = max(0, int(seconds))
    minutes, secs = divmod(total_seconds, 60)
    return f"{minutes:02d}:{secs:02d}"


def format_diarized_transcription_txt(
    transcription: TranscriptionDiarized,
) -> str:
    speaker_labels: dict[str, int] = {}
    next_speaker_num = 1

    chunks: list[str] = []

    current_speaker: str | None = None
    current_start: float | None = None
    current_end: float | None = None
    current_text_parts: list[str] = []

    def flush() -> None:
        nonlocal \
            current_speaker, \
            current_start, \
            current_end, \
            current_text_parts, \
            next_speaker_num
        if current_speaker is None or current_start is None or current_end is None:
            return

        if current_speaker not in speaker_labels:
            speaker_labels[current_speaker] = next_speaker_num
            next_speaker_num += 1

        speaker_num = speaker_labels[current_speaker]
        start = _format_mmss(current_start)
        end = _format_mmss(current_end)
        text = " ".join(part for part in current_text_parts if part).strip()
        chunks.append(f"Speaker {speaker_num} ({start}-{end})\n{text}\n")

        current_speaker = None
        current_start = None
        current_end = None
        current_text_parts = []

    for segment in transcription.segments:
        speaker = segment.speaker or "unknown"
        text = (segment.text or "").strip()

        if current_speaker is None:
            current_speaker = speaker
            current_start = segment.start
            current_end = segment.end
            current_text_parts = [text] if text else []
            continue

        if speaker != current_speaker:
            flush()
            current_speaker = speaker
            current_start = segment.start
            current_end = segment.end
            current_text_parts = [text] if text else []
            continue

        # Same speaker as previous segment: collapse into a single blob.
        current_end = segment.end
        if text:
            current_text_parts.append(text)

    flush()

    return "\n".join(chunks).strip() + "\n"


async def transcribe_thread_recording_and_email_link(
    cli: openai.AsyncClient | openai.AsyncAzureOpenAI,
    class_id: str,
    thread_id: str,
    user_id: int,
    nowfn: NowFn = utcnow,
) -> None:
    class_name: str | None = None
    user_email: str | None = None
    group_link = config.url(f"/group/{class_id}/thread/{thread_id}")

    try:
        async with config.db.driver.async_session() as session:
            class_ = await models.Class.get_by_id(session, int(class_id))
            if not class_:
                raise ValueError(f"Class with ID {class_id} not found")
            class_name = class_.name

            user = await models.User.get_by_id(session, user_id)
            if not user:
                raise ValueError(f"User with ID {user_id} not found")
            user_email = user.email

            thread = await models.Thread.get_by_id_with_users_voice_mode(
                session, int(thread_id)
            )
            if not thread:
                raise ValueError(f"Thread with ID {thread_id} not found")
            if not thread.voice_mode_recording:
                raise ValueError(f"Thread with ID {thread_id} has no recording")

            recording_key = thread.voice_mode_recording.recording_id

        suffix = os.path.splitext(recording_key)[1] or ".webm"
        tmp_path = None
        with tempfile.NamedTemporaryFile(mode="wb", suffix=suffix, delete=False) as tmp:
            tmp_path = tmp.name
            async for chunk in config.audio_store.store.get_file(recording_key):
                tmp.write(chunk)

        with open(tmp_path, "rb") as audio_file:
            transcription = await cli.audio.transcriptions.create(
                file=audio_file,
                model="gpt-4o-transcribe-diarize",
                response_format="diarized_json",
                chunking_strategy="auto",
                language="en",
            )

        if not isinstance(transcription, TranscriptionDiarized):
            raise TypeError(
                f"Unexpected transcription response type: {type(transcription)}"
            )

        transcription_txt = format_diarized_transcription_txt(transcription)

        txt_buffer = io.StringIO(transcription_txt)
        file_name = f"thread_recording_transcription_{class_id}_{thread_id}_{user_id}_{datetime.now(timezone.utc).isoformat()}.txt"
        await config.artifact_store.store.put(
            file_name, txt_buffer, "text/plain;charset=utf-8"
        )
        txt_buffer.close()

        tok = encode_auth_token(
            sub=json.dumps(
                {
                    "user_id": user_id,
                    "download_name": file_name,
                }
            ),
            expiry=config.artifact_store.download_link_expiration,
            nowfn=nowfn,
        )

        download_link = config.url(
            f"/api/v1/class/{class_id}/thread/{thread_id}/recording/transcribe/download?token={tok}"
        )

        invite = DownloadExport(
            class_name=class_.name,
            email=user.email,
            link=download_link,
        )
        await send_transcription_download(
            config.email.sender,
            invite,
            expires=config.artifact_store.download_link_expiration,
        )
    except Exception:
        logger.exception(
            "Failed to create transcription for class=%s thread=%s user=%s",
            class_id,
            thread_id,
            user_id,
        )
        if class_name and user_email:
            try:
                await send_transcription_failed(
                    config.email.sender,
                    DownloadExport(
                        class_name=class_name,
                        email=user_email,
                        link=group_link,
                    ),
                )
            except Exception:
                logger.exception(
                    "Failed to send transcription failure email for class=%s thread=%s user=%s",
                    class_id,
                    thread_id,
                    user_id,
                )
    finally:
        if tmp_path:
            try:
                os.remove(tmp_path)
            except OSError:
                logger.warning("Failed to remove temp recording file %s", tmp_path)
