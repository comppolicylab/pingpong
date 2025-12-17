import io
import json
import logging
import os
import re
import tempfile
from datetime import datetime, timezone
from collections import Counter

import openai
from openai.types.audio.transcription_diarized import TranscriptionDiarized
from openai.types.beta.threads.message import Message as OpenAIThreadMessage

import pingpong.models as models
from pingpong.animal_hash import user_names
from pingpong.auth import encode_auth_token
from pingpong.config import config
from pingpong.invite import send_transcription_download, send_transcription_failed
from pingpong.now import NowFn, utcnow
from pingpong.schemas import DownloadTranscriptExport, MessageForSpeakerMatch

logger = logging.getLogger(__name__)

_WHITESPACE_RE = re.compile(r"\s+")
_NON_ALNUM_RE = re.compile(r"[^a-z0-9 ]+")
# Minimum normalized length for a thread message to be considered for matching.
# Rationale: very short messages (e.g., "ok", "thanks") are too ambiguous and create
# false matches against diarized chunks.
_MIN_MESSAGE_LENGTH = 20
# Minimum normalized length for a diarized chunk to be considered for matching.
# Rationale: very short chunk text tends to be filler and matches many messages.
_MIN_CHUNK_LENGTH = 25
# Minimum number of words for a diarized chunk to be considered for matching.
# Rationale: additional guardrail against short acknowledgements.
_MIN_CHUNK_WORDS = 4
# Minimum normalized length before we attempt substring matching.
# Rationale: diarized chunks can be short; using substring matching on very short strings
# causes frequent false positives ("yeah", "okay", etc.). 30 chars is a practical cutoff
# that tends to include meaningful phrases while filtering fillers.
_MIN_SUBSTRING_MATCH_LENGTH = 30
# Minimum similarity score required to treat a diarized chunk as matching a thread message.
# Rationale: the similarity metric is token-overlap over the smaller token set, which can
# be overly optimistic for short/partial overlaps. 0.6 provides a balance that typically
# requires substantive overlap while still tolerating diarization/ASR differences.
_MIN_SIMILARITY_SCORE = 0.6


def _normalize_text(text: str) -> str:
    text = text.lower()
    text = _NON_ALNUM_RE.sub(" ", text)
    text = _WHITESPACE_RE.sub(" ", text)
    return text.strip()


def _token_set(text: str) -> set[str]:
    return _token_set_from_normalized(_normalize_text(text))


def _token_set_from_normalized(normalized_text: str) -> set[str]:
    return {t for t in normalized_text.split(" ") if t}


def _similarity(a: str, b: str) -> float:
    a_norm = _normalize_text(a)
    b_norm = _normalize_text(b)
    if not a_norm or not b_norm:
        return 0.0

    # Strong signal for partial matches: diarized chunks are often substrings of thread messages.
    if len(a_norm) >= _MIN_SUBSTRING_MATCH_LENGTH and a_norm in b_norm:
        return 1.0
    if len(b_norm) >= _MIN_SUBSTRING_MATCH_LENGTH and b_norm in a_norm:
        return 1.0

    a_tokens = _token_set_from_normalized(a_norm)
    b_tokens = _token_set_from_normalized(b_norm)
    if not a_tokens or not b_tokens:
        return 0.0

    return len(a_tokens & b_tokens) / float(min(len(a_tokens), len(b_tokens)))


def _similarity_precomputed(
    *,
    a_norm: str,
    a_tokens: set[str],
    b_norm: str,
    b_tokens: set[str],
) -> float:
    if not a_norm or not b_norm:
        return 0.0

    if len(a_norm) >= _MIN_SUBSTRING_MATCH_LENGTH and a_norm in b_norm:
        return 1.0
    if len(b_norm) >= _MIN_SUBSTRING_MATCH_LENGTH and b_norm in a_norm:
        return 1.0

    if not a_tokens or not b_tokens:
        return 0.0

    return len(a_tokens & b_tokens) / float(min(len(a_tokens), len(b_tokens)))


def _extract_openai_thread_message_text(message: OpenAIThreadMessage) -> str:
    """
    Extract the concatenated plain-text content from an OpenAI thread message.

    Only `text` content blocks are included; non-text blocks (images, etc.) are ignored.
    Uses `getattr` defensively because OpenAI SDK content block types can vary by version
    and not all blocks guarantee the same attribute shape at runtime.

    Args:
        message: An OpenAI thread message object.

    Returns:
        A single string containing the concatenated text values (newline-separated),
        or an empty string if no text content is present.
    """
    parts: list[str] = []
    for content in message.content:
        if getattr(content, "type", None) == "text" and getattr(content, "text", None):
            value = getattr(content.text, "value", None)
            if value:
                parts.append(value)
    return "\n".join(parts).strip()


async def _list_openai_thread_messages(
    cli: openai.AsyncClient | openai.AsyncAzureOpenAI,
    openai_thread_id: str,
    *,
    limit: int = 200,
) -> list[OpenAIThreadMessage]:
    """
    List messages for a classic (v2) OpenAI thread, handling pagination.

    Pagination strategy:
    - Fetches pages in ascending order using the `after` cursor.
    - Uses `page.last_id` as the next cursor and stops when `page.has_more` is false.
    - Caps results at `limit` (default 200) to bound latency and token usage.

    Early termination can happen when:
    - The API indicates there are no more pages (`has_more` is false).
    - The API response does not include a `last_id` cursor (defensive stop).
    - `limit` is reached.
    """
    messages: list[OpenAIThreadMessage] = []
    after: str | None = None
    per_page = min(100, limit)

    while len(messages) < limit:
        page = await cli.beta.threads.messages.list(
            thread_id=openai_thread_id,
            limit=per_page,
            order="asc",
            after=after,
        )
        messages.extend(page.data)
        if not getattr(page, "has_more", False):
            break
        after = getattr(page, "last_id", None)
        if after is None:
            break

    return messages[:limit]


def _iter_diarized_chunks(
    transcription: TranscriptionDiarized,
) -> list[tuple[str, float, float, str]]:
    """
    Consolidate diarized segments into contiguous chunks per speaker.

    Strategy:
    - Walks the diarized `segments` in order.
    - Merges consecutive segments with the same `segment.speaker` into one chunk,
      concatenating their non-empty `segment.text` values with spaces.
    - Starts a new chunk when the speaker changes.

    Returns:
        A list of tuples `(speaker_id, start_seconds, end_seconds, text)` where:
        - `speaker_id` is `segment.speaker` (or "unknown" if missing/falsy),
        - `start_seconds` is the first segment's start time in the chunk,
        - `end_seconds` is the last segment's end time in the chunk,
        - `text` is the concatenated transcript text for that chunk.
    """
    chunks: list[tuple[str, float, float, str]] = []

    current_speaker: str | None = None
    current_start: float | None = None
    current_end: float | None = None
    current_text_parts: list[str] = []

    def flush() -> None:
        nonlocal current_speaker, current_start, current_end, current_text_parts
        if current_speaker is None or current_start is None or current_end is None:
            return
        text = " ".join(part for part in current_text_parts if part).strip()
        chunks.append((current_speaker, current_start, current_end, text))
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

        current_end = segment.end
        if text:
            current_text_parts.append(text)

    flush()
    return chunks


def infer_speaker_display_names_from_thread_messages(
    *,
    transcription: TranscriptionDiarized,
    thread_messages: list[OpenAIThreadMessage],
    user_id_to_name: dict[int, str],
) -> dict[str, str]:
    """
    Use existing thread messages to classify diarization speakers as Assistant vs a specific user.

    We only need a single strong match to decide a speaker mapping; once mapped, all occurrences
    of that diarization speaker id are labeled consistently.
    """

    filtered_messages: list[MessageForSpeakerMatch] = []
    for msg in thread_messages:
        role = getattr(msg, "role", None)
        if role not in {"assistant", "user"}:
            continue
        text = _extract_openai_thread_message_text(msg)
        norm_text = _normalize_text(text)
        if len(norm_text) < _MIN_MESSAGE_LENGTH:
            continue

        user_id: int | None = None
        if role == "user":
            metadata = getattr(msg, "metadata", None) or {}
            raw_user_id = metadata.get("user_id")
            try:
                user_id = int(raw_user_id) if raw_user_id is not None else None
            except (TypeError, ValueError):
                user_id = None

        filtered_messages.append(
            MessageForSpeakerMatch(
                role=role,
                user_id=user_id,
                text=text,
                norm_text=norm_text,
                tokens=_token_set_from_normalized(norm_text),
            )
        )

    token_to_message_idxs: dict[str, list[int]] = {}
    for idx, message in enumerate(filtered_messages):
        for token in message.tokens:
            token_to_message_idxs.setdefault(token, []).append(idx)

    speaker_assistant_votes: Counter[str] = Counter()
    speaker_user_votes: dict[str, Counter[int]] = {}
    speaker_unknown_user_votes: Counter[str] = Counter()

    for speaker, _start, _end, text in _iter_diarized_chunks(transcription):
        norm = _normalize_text(text)
        words = [w for w in norm.split(" ") if w]
        if len(norm) < _MIN_CHUNK_LENGTH or len(words) < _MIN_CHUNK_WORDS:
            continue
        chunk_tokens = set(words)

        best_score = 0.0
        best_role: str | None = None
        best_user_id: int | None = None

        candidate_idxs: set[int] = set()
        for token in chunk_tokens:
            candidate_idxs.update(token_to_message_idxs.get(token, []))

        for idx in sorted(candidate_idxs):
            m = filtered_messages[idx]
            score = _similarity_precomputed(
                a_norm=norm,
                a_tokens=chunk_tokens,
                b_norm=m.norm_text,
                b_tokens=m.tokens,
            )
            if score > best_score:
                best_score = score
                best_role = m.role
                best_user_id = m.user_id

        if best_score < _MIN_SIMILARITY_SCORE or best_role is None:
            continue

        if best_role == "assistant":
            speaker_assistant_votes[speaker] += 1
        elif best_role == "user":
            if isinstance(best_user_id, int):
                speaker_user_votes.setdefault(speaker, Counter())[best_user_id] += 1
            else:
                speaker_unknown_user_votes[speaker] += 1

    speaker_display_names: dict[str, str] = {}

    for speaker in {
        *(speaker_assistant_votes.keys()),
        *(speaker_user_votes.keys()),
        *(speaker_unknown_user_votes.keys()),
    }:
        assistant_votes = speaker_assistant_votes.get(speaker, 0)
        user_votes = speaker_user_votes.get(speaker, Counter()).total()
        unknown_user_votes = speaker_unknown_user_votes.get(speaker, 0)
        total_user_votes = user_votes + unknown_user_votes

        if assistant_votes > 0 and assistant_votes >= total_user_votes:
            speaker_display_names[speaker] = "Assistant"
            continue

        user_votes_by_id = speaker_user_votes.get(speaker)
        if user_votes_by_id:
            user_id, _ct = user_votes_by_id.most_common(1)[0]
            name = user_id_to_name.get(user_id)
            if name:
                speaker_display_names[speaker] = name
                continue

    return speaker_display_names


def _format_mmss(seconds: float) -> str:
    total_seconds = max(0, int(seconds))
    minutes, secs = divmod(total_seconds, 60)
    return f"{minutes:02d}:{secs:02d}"


def format_diarized_transcription_txt(
    transcription: TranscriptionDiarized,
    *,
    speaker_display_names: dict[str, str] | None = None,
    assistant_name: str | None = None,
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

        display_name = (
            speaker_display_names.get(current_speaker)
            if speaker_display_names is not None
            else None
        )
        speaker_num = speaker_labels[current_speaker]
        start = _format_mmss(current_start)
        end = _format_mmss(current_end)
        text = " ".join(part for part in current_text_parts if part).strip()
        if display_name == "Assistant":
            header = f"[Assistant] {assistant_name or 'Assistant'}"
        else:
            header = display_name or f"Speaker {speaker_num}"
        chunks.append(f"{header} ({start}-{end})\n{text}\n")

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
    tmp_path: str | None = None

    try:
        async with config.authz.driver.get_client() as authz:
            is_supervisor_check = await authz.check(
                [
                    (
                        f"user:{user_id}",
                        "supervisor",
                        f"class:{class_id}",
                    ),
                ]
            )
            is_supervisor = (
                bool(is_supervisor_check[0]) if is_supervisor_check else False
            )

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
            thread_users = user_names(thread, user_id, is_supervisor=is_supervisor)
            visible_users = [
                u for u in thread.users if not u.anonymous_link_id or u.id == user_id
            ]
            user_id_to_name = {
                u.id: thread_users[idx]
                for idx, u in enumerate(visible_users)
                if idx < len(thread_users)
            }

        suffix = os.path.splitext(recording_key)[1] or ".webm"
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

        speaker_display_names: dict[str, str] | None = None
        try:
            thread_messages = await _list_openai_thread_messages(cli, thread.thread_id)
            speaker_display_names = infer_speaker_display_names_from_thread_messages(
                transcription=transcription,
                thread_messages=thread_messages,
                user_id_to_name=user_id_to_name,
            )
        except Exception:
            logger.exception(
                "Failed to infer speaker names from thread messages for thread=%s",
                thread.thread_id,
            )

        transcription_txt = format_diarized_transcription_txt(
            transcription,
            speaker_display_names=speaker_display_names,
            assistant_name=getattr(thread.assistant, "name", None),
        )
        transcription_txt = (
            f"Thread link: {group_link}\n"
            f"Thread participants: {', '.join(thread_users)}\n\n"
            f"{transcription_txt}"
        )

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

        invite = DownloadTranscriptExport(
            class_name=class_.name,
            email=user.email,
            link=download_link,
            thread_link=group_link,
            thread_users=thread_users,
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
                    DownloadTranscriptExport(
                        class_name=class_name,
                        email=user_email,
                        link=group_link,
                        thread_link=group_link,
                        thread_users=[],
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
