import asyncio
import functools
import json
import logging
import os
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, TypeVar

import openai
from google.genai.client import AsyncClient
from google.genai import types
from pydantic import BaseModel, ConfigDict, Field

import pingpong.schemas as schemas
from pingpong import gemini as gemini_helpers

logger = logging.getLogger(__name__)

_ResponseModelT = TypeVar("_ResponseModelT", bound=BaseModel)

_WHISPER_UPLOAD_MAX_BYTES = 25_000_000
_WHISPER_UPLOAD_TARGET_BYTES = 24_500_000
_TRANSCRIPTION_AUDIO_SAMPLE_RATE = 16_000
_TRANSCRIPTION_AUDIO_BITRATES = ("32k", "24k", "16k", "12k")


@functools.cache
def _log_missing_ffprobe_once() -> None:
    logger.warning(
        "ffprobe is unavailable; lecture video duration will be omitted "
        "from manifest generation prompts."
    )


DEFAULT_LECTURE_VIDEO_INSTRUCTIONS = """You are a friendly, clear tutor helping a learner during an interactive video lesson.

While the user can only type text, your responses will be **spoken aloud**, so they must sound natural, simple, and easy to follow.

---

### Context Provided

Each turn, the learner's question is preceded by a hidden developer message titled **"## Lecture Context"**. Read it before answering. It uses this structure:

* **Status** — either *Watching the lecture video* or *Just answered Knowledge Check #N*. Tells you what the learner is doing right now.
* **Current offset** — how far into the video they are, in milliseconds.
* **### Recent Transcript** (sometimes **"Since Last Lecture Chat"**) — what the lecturer has just said. This is the main thing the learner is reacting to.
* **### Lookahead Transcript** — a short window of what's about to be said. Use it to avoid spoiling upcoming explanations and to align your wording with what's coming.
* **### Relevant Video Descriptions** — text descriptions of what's on screen during that window. Use this in place of "what I can see in the frame".
* **### Upcoming Knowledge Check** — the next question the learner will be asked, with its options. Don't reveal the answer; you may nudge toward the relevant idea.
* **### Knowledge Checks Answered** — earlier checks with the option chosen, whether it was correct, and any feedback shown. Build on these — reinforce what they got right, gently revisit what they missed.

The learner's own question follows the developer message.

---

### Instructions

**Critical Content Control Rule**
- **Never provide information, details, explanations, or content that have not yet appeared in the Recent Transcript or previous interaction.**
    - Do not give away, explain, or elaborate on anything from the Lookahead Transcript or Upcoming Knowledge Check, regardless of student prompting.
    - You may state that certain topics, explanations, or questions will be covered soon (e.g., "We'll get to that later," "That's coming up in a moment"), but do not provide their substance until they actually appear.
    - This applies to all responses, including direct questions, summaries, or anticipatory questions from the learner.

**1. Be clear and easy to follow**

* Use plain language and match the level of the lecture.
* Avoid jargon, or define it briefly the first time it appears.

**2. Keep it short and focused**

* Answer as directly as possible.
* One or two key ideas is usually enough.

**3. Make it sound natural when spoken**

* Write like you're talking, not like a textbook.
* Read symbols and notation aloud (e.g., "x squared", "one over two") rather than using characters.
* Avoid long or complex sentences.

**4. Use the lecture context when helpful**

* Ground your answer in what the lecturer just said (Recent Transcript) and what's on screen (Relevant Video Descriptions).
  (e.g., "In the example the lecturer just worked through…")
* Don't reference offsets, milliseconds, or section names from the developer message — translate them into natural phrases like "just now" or "in a moment".

**5. If asked for a summary or what has happened so far:**

* Only summarize the content from the Recent Transcript (NOT from the Lookahead Transcript or Upcoming Knowledge Check).
* If the Recent Transcript is empty or nearly empty, state that there isn't anything to summarize yet, and suggest watching further. **Do NOT explain or mention any content from the Lookahead Transcript or Upcoming Knowledge Check when the Recent Transcript is empty or minimal.**
* Make clear your summary is based strictly on what has happened so far, not what's about to happen or be assessed.

**6. Respect the upcoming Knowledge Check**

* If the question is heading toward an Upcoming Knowledge Check, you can reference that they’re about to get a question related to the topic, but do not give the content of the question or its answer, nor discuss supporting details until after it is shown.
* Do not give answers to knowledge check questions unless the student has attempted it first.
* If they're asking after answering one (Status says *Just answered Knowledge Check #N*), build on the feedback they already saw.

**7. Prioritise helping over completeness**

* Give the simplest explanation that moves the learner forward.
* Don't unfold long derivations or background unless asked.

**8. If the question is unclear or off-track**

* Gently steer back, or ask one brief clarifying question.
* Don't guess wildly.

**9. Default to direct answers**

* Only ask a question back if it's needed to help them.

**10. Keep the tone of a friendly teacher**

* Supportive, calm, and encouraging.
* Not overly excited or overly formal.

---

### Output

Respond with **only the answer**, written as a short, spoken explanation.

# Output Format

Respond with a concise, natural-sounding spoken explanation suited for audio delivery. Avoid technical jargon unless defined. Do not repeat the question, list instructions, or provide extra context—just the answer itself.

# Notes

- Under all circumstances, **never provide content, definitions, or explanations from the Lookahead Transcript or Upcoming Knowledge Check before they occur**; at most, acknowledge that something is coming but do not reveal any details.
- When summarizing, **never use Lookahead Transcript or Upcoming Knowledge Check content** if Recent Transcript is empty or nearly empty.
- If there's little or no content yet, say so directly, and encourage the learner to watch further for more to discuss.
- All explanations must be accessible to the learner's level and sound conversational.
- Never refer explicitly to developer message components (e.g., "Recent Transcript," "Lookahead," etc.)."""

DEFAULT_GENERATION_PROMPT_CONTENT = """You will generate an interactive video lesson for the given lecture video and transcript.

GUIDELINES FOR QUESTION PLACEMENT:
- Aim for roughly one question every 60 seconds, but prioritize pedagogical appropriateness over rigid timing. Place questions at natural conceptual breakpoints.
- If no natural breakpoint exists within a 60-second window, skip the question rather than forcing one at an awkward moment. An awkward question should be penalized more than a lack of question.
- If the teacher poses a question to the viewer — either verbally or on screen — that is a very ideal place to insert an interactive question. Prioritize these over generating new questions, but still fill gaps if the teacher doesn't ask enough questions to maintain ~60 second intervals.
- Never place a question mid-sentence or mid-explanation as this will turn into an attention check. Always pause at a completed thought.

HANDLING TEACHER-POSED QUESTIONS:
When the teacher asks a question in the video that you want to use as an interactive question:
- Let the teacher ask the question. The pause should come AFTER the student has heard the full question.
- voice_over_intro should be empty ("") or at most a brief first-person nudge like "What do you think?" — do NOT restate or rephrase the question.
- question_text should convey the same intent as the teacher's question but rewritten as a clean, concise on-screen prompt. You do NOT need to preserve the teacher's exact wording — rephrase freely for clarity and brevity. For example, if the teacher says "So what do you think happens when we multiply both sides by negative one? Does the sign flip or stay the same?", the question_text might simply be: "What happens to the inequality sign when you multiply by a negative?" Rephrase for clarity and brevity while preserving the core question.
- If the teacher answers their own question after asking it, DO NOT skip past the answer. Instead, use the teacher's answer as part of the experience:
  - For correct choices: resume so the student hears the teacher confirm and explain naturally.
  - For incorrect choices: the voice-over feedback should transition the student back into the teacher's answer, not restate it. Use your discretion on where to resume so the teacher's own words complete the correction smoothly.
  - Different choices may have different resume points when it makes the flow more natural. For example, a correct answer might resume at the teacher saying "Yeah, it's 2.5..." while an incorrect answer might resume mid-sentence at "...2.5. So now let us think about..." after the voice-over has already set up the transition.

GUIDELINES FOR QUESTIONS:
- Questions should be quick comprehension checks that a student can answer in a few seconds. They are not meant to be tricky or challenging.
- Question text should be concise — one short sentence, directly asking what you want to know.
- Use 2 to 4 answer choices per question. Use fewer when the question naturally calls for it (e.g., True/False, or a simple either/or). Do not force 4 choices when 2 or 3 are more natural.
- Do NOT label choices with A, B, C, D or any letters/numbers. Just provide the choice text. The choices will be randomized at display time.
- Exactly one answer is correct.
- Answer choices should be direct and concise — not full sentences unless necessary.
- Distractors should reflect common misconceptions or errors, not random values. Document each distractor's targeted misconception in the "misconception" field.
- TRIVIALITY CHECK: Before finalizing a question, ask: has the teacher ALREADY answered this exact concept in the preceding 15-20 seconds? If the teacher just demonstrated or explained the answer for a similar case (e.g., showed that angles A, B, and C are NOT supplementary pairs, then asking whether D and E are), the student already knows the pattern. The question becomes a trivial repetition, not a comprehension check. In such cases, either:
  (a) Ask a higher-order question that builds on the pattern (e.g., "Why are D and E different from the other pairs?"), or
  (b) Skip the question entirely and wait for the next genuine conceptual breakpoint.
  A question that any attentive student can answer without thinking is worse than no question at all."""

_GEMINI_MODEL = "gemini-3.1-pro-preview"
_VIDEO_DESCRIPTION_WINDOW_MS = 30_000
_MANIFEST_CHUNK_DURATION_MS = 5 * 60 * 1000
_MANIFEST_CHUNK_MIN_TAIL_MS = 3 * 60 * 1000
_MANIFEST_CHUNK_OVERLAP_MS = 30_000
_MANIFEST_CHUNK_MIN_SPLIT_MS = 3 * 60 * 1000
_GEMINI_GENERATION_MAX_ATTEMPTS = 3
_GEMINI_GENERATION_RETRY_DELAY_SECONDS = 5.0


@dataclass(frozen=True)
class GeminiFileRef:
    name: str
    uri: str | None = None
    mime_type: str | None = None


@dataclass(frozen=True)
class ManifestGenerationChunk:
    generation_start_ms: int
    generation_end_ms: int
    context_start_ms: int
    context_end_ms: int

    @property
    def generation_duration_ms(self) -> int:
        return self.generation_end_ms - self.generation_start_ms


class GeneratedChoice(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(description="The exact choice text shown to the student.")
    misconception: str | None = Field(
        description="The misconception this choice represents, or null for the correct answer.",
    )


class GeneratedChoiceFeedback(BaseModel):
    model_config = ConfigDict(extra="forbid")

    voice_over: str = Field(
        description="The spoken feedback to play when this choice is selected."
    )
    resume_at_word_id: str = Field(
        description="The transcript word ID where the lecture resumes after feedback."
    )
    resume_at_word: str = Field(
        description="The transcript word where the lecture resumes after feedback."
    )
    resume_at: float = Field(description="The resume timestamp in seconds.")


class GeneratedQuestion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: int | str = Field(description="Stable generated question identifier.")
    question_source: Literal["teacher", "generated"] = Field(
        description="Whether the question came from the teacher or was generated."
    )
    pause_after_word_id: str = Field(
        description="The last transcript word ID heard before the question appears."
    )
    pause_after_word: str = Field(
        description="The last transcript word heard before the question appears."
    )
    pause_at: float = Field(description="The pause timestamp in seconds.")
    voice_over_intro: str = Field(
        description="The spoken intro before showing the question."
    )
    question_text: str = Field(description="The question text shown to the student.")
    choices: list[GeneratedChoice] = Field(
        min_length=2,
        max_length=4,
        description="Two to four concise answer choices.",
    )
    correct_answer: str = Field(description="The exact text of the correct choice.")
    choice_feedback: dict[str, GeneratedChoiceFeedback] = Field(
        description="Feedback keyed by exact choice text."
    )


class GeneratedVideoDescription(BaseModel):
    model_config = ConfigDict(extra="forbid")

    start_offset_ms: int = Field(ge=0, description="Start offset in milliseconds.")
    end_offset_ms: int = Field(ge=1, description="End offset in milliseconds.")
    description: str = Field(description="Visual description for this video window.")


class GeneratedQuizWithVideo(BaseModel):
    model_config = ConfigDict(extra="forbid")

    video_summary: str = Field(description="Brief summary of the lesson.")
    questions: list[GeneratedQuestion] = Field(
        min_length=1,
        description="Generated comprehension checks.",
    )
    video_descriptions: list[GeneratedVideoDescription] = Field(
        min_length=1,
        description="Contiguous visual descriptions covering the source video.",
    )


class ReconciledGeneratedQuiz(BaseModel):
    model_config = ConfigDict(extra="forbid")

    questions: list[GeneratedQuestion] = Field(
        min_length=1,
        description="Final reconciled comprehension checks for the full video.",
    )


def _timestamp_to_ms(value: float | int) -> int:
    return int(round(float(value) * 1000))


@dataclass(frozen=True)
class TranscriptWordIndex:
    by_id: dict[str, schemas.LectureVideoManifestWordV3]
    by_start_ms: dict[int, list[schemas.LectureVideoManifestWordV3]]
    by_end_ms: dict[int, list[schemas.LectureVideoManifestWordV3]]
    position_by_id: dict[str, int]


def _transcript_word_index(
    transcript: list[schemas.LectureVideoManifestWordV3],
) -> TranscriptWordIndex:
    words_by_id: dict[str, schemas.LectureVideoManifestWordV3] = {}
    words_by_start_ms: dict[int, list[schemas.LectureVideoManifestWordV3]] = {}
    words_by_end_ms: dict[int, list[schemas.LectureVideoManifestWordV3]] = {}
    position_by_id: dict[str, int] = {}
    for index, word in enumerate(transcript):
        if word.id in words_by_id:
            raise ValueError(f"Transcript contains duplicate word ID {word.id!r}.")
        words_by_id[word.id] = word
        words_by_start_ms.setdefault(word.start_offset_ms, []).append(word)
        words_by_end_ms.setdefault(word.end_offset_ms, []).append(word)
        position_by_id[word.id] = index
    return TranscriptWordIndex(
        by_id=words_by_id,
        by_start_ms=words_by_start_ms,
        by_end_ms=words_by_end_ms,
        position_by_id=position_by_id,
    )


def _validated_transcript_timestamp_ms(
    *,
    transcript_word_index: TranscriptWordIndex,
    word_id: str,
    word_text: str,
    timestamp: float,
    timestamp_kind: Literal["start", "end"],
) -> int:
    generated_offset_ms = _timestamp_to_ms(timestamp)

    def score_word(word: schemas.LectureVideoManifestWordV3) -> int:
        transcript_offset_ms = (
            word.start_offset_ms if timestamp_kind == "start" else word.end_offset_ms
        )
        return sum(
            (
                word.id == word_id,
                word.word == word_text,
                transcript_offset_ms == generated_offset_ms,
            )
        )

    candidate_words_by_id: dict[str, schemas.LectureVideoManifestWordV3] = {}
    word_by_id = transcript_word_index.by_id.get(word_id)
    if word_by_id is not None:
        candidate_words_by_id[word_by_id.id] = word_by_id
    timestamp_words = (
        transcript_word_index.by_start_ms
        if timestamp_kind == "start"
        else transcript_word_index.by_end_ms
    ).get(generated_offset_ms, [])
    for word in timestamp_words:
        candidate_words_by_id[word.id] = word
    candidate_words = sorted(
        candidate_words_by_id.values(),
        key=lambda word: transcript_word_index.position_by_id[word.id],
    )
    best_word = max(
        candidate_words,
        key=lambda word: (
            score_word(word),
            word.id == word_id,
            (word.start_offset_ms if timestamp_kind == "start" else word.end_offset_ms)
            == generated_offset_ms,
        ),
        default=None,
    )
    best_score = score_word(best_word) if best_word is not None else 0
    if best_score < 2:
        raise ValueError(
            f"Generated word reference did not match at least two of id, "
            f"word, and {timestamp_kind} timestamp: id={word_id!r}, "
            f"word={word_text!r}, timestamp={generated_offset_ms}ms."
        )
    assert best_word is not None
    expected_offset_ms = (
        best_word.start_offset_ms
        if timestamp_kind == "start"
        else best_word.end_offset_ms
    )
    if best_score == 2:
        logger.warning(
            "Generated word reference matched transcript with one mismatched field. "
            "timestamp_kind=%s generated_id=%r matched_id=%r generated_word=%r "
            "matched_word=%r generated_offset_ms=%s matched_offset_ms=%s",
            timestamp_kind,
            word_id,
            best_word.id,
            word_text,
            best_word.word,
            generated_offset_ms,
            expected_offset_ms,
        )
    return expected_offset_ms


def _word_to_generation_word(
    word: schemas.LectureVideoManifestWordV3 | dict[str, Any],
    index: int,
) -> dict[str, Any]:
    if isinstance(word, schemas.LectureVideoManifestWordV3):
        return {
            "id": word.id,
            "word": word.word,
            "start": word.start_offset_ms / 1000,
            "end": word.end_offset_ms / 1000,
        }
    return {
        "id": str(word.get("id", index)),
        "word": str(word.get("word", "")),
        "start": float(word.get("start", word.get("start_offset_ms", 0)) or 0)
        / (1000 if "start_offset_ms" in word else 1),
        "end": float(word.get("end", word.get("end_offset_ms", 0)) or 0)
        / (1000 if "end_offset_ms" in word else 1),
    }


def _align_offset_down(offset_ms: int, alignment_ms: int) -> int:
    if alignment_ms <= 0:
        return offset_ms
    return (offset_ms // alignment_ms) * alignment_ms


def _aligned_split_offset(
    start_ms: int,
    end_ms: int,
    *,
    alignment_ms: int = _VIDEO_DESCRIPTION_WINDOW_MS,
) -> int:
    midpoint_ms = start_ms + (end_ms - start_ms) // 2
    split_ms = _align_offset_down(midpoint_ms, alignment_ms)
    if split_ms <= start_ms:
        split_ms = start_ms + max(alignment_ms, (end_ms - start_ms) // 2)
    if split_ms >= end_ms:
        split_ms = midpoint_ms
    return split_ms


def _plan_manifest_generation_chunks(
    video_duration_ms: int | None,
    *,
    max_chunk_duration_ms: int = _MANIFEST_CHUNK_DURATION_MS,
    min_tail_duration_ms: int = _MANIFEST_CHUNK_MIN_TAIL_MS,
    overlap_ms: int = _MANIFEST_CHUNK_OVERLAP_MS,
    alignment_ms: int = _VIDEO_DESCRIPTION_WINDOW_MS,
) -> list[ManifestGenerationChunk]:
    if video_duration_ms is None or video_duration_ms <= max_chunk_duration_ms:
        duration_ms = max(video_duration_ms or 1, 1)
        return [
            ManifestGenerationChunk(
                generation_start_ms=0,
                generation_end_ms=duration_ms,
                context_start_ms=0,
                context_end_ms=duration_ms,
            )
        ]

    boundaries = list(range(0, video_duration_ms, max_chunk_duration_ms))
    boundaries.append(video_duration_ms)
    if len(boundaries) >= 3:
        tail_duration_ms = boundaries[-1] - boundaries[-2]
        if tail_duration_ms < min_tail_duration_ms:
            tail_start_ms = boundaries[-3]
            tail_end_ms = boundaries[-1]
            split_ms = _aligned_split_offset(
                tail_start_ms,
                tail_end_ms,
                alignment_ms=alignment_ms,
            )
            boundaries = boundaries[:-3] + [tail_start_ms, split_ms, tail_end_ms]

    chunks = []
    for start_ms, end_ms in zip(boundaries, boundaries[1:]):
        chunks.append(
            ManifestGenerationChunk(
                generation_start_ms=start_ms,
                generation_end_ms=end_ms,
                context_start_ms=max(start_ms - overlap_ms, 0),
                context_end_ms=min(end_ms + overlap_ms, video_duration_ms),
            )
        )
    return chunks


def _split_manifest_generation_chunk(
    chunk: ManifestGenerationChunk,
    *,
    video_duration_ms: int,
    overlap_ms: int = _MANIFEST_CHUNK_OVERLAP_MS,
    alignment_ms: int = _VIDEO_DESCRIPTION_WINDOW_MS,
) -> list[ManifestGenerationChunk]:
    split_ms = _aligned_split_offset(
        chunk.generation_start_ms,
        chunk.generation_end_ms,
        alignment_ms=alignment_ms,
    )
    return [
        ManifestGenerationChunk(
            generation_start_ms=chunk.generation_start_ms,
            generation_end_ms=split_ms,
            context_start_ms=max(chunk.generation_start_ms - overlap_ms, 0),
            context_end_ms=min(split_ms + overlap_ms, video_duration_ms),
        ),
        ManifestGenerationChunk(
            generation_start_ms=split_ms,
            generation_end_ms=chunk.generation_end_ms,
            context_start_ms=max(split_ms - overlap_ms, 0),
            context_end_ms=min(
                chunk.generation_end_ms + overlap_ms,
                video_duration_ms,
            ),
        ),
    ]


def _transcript_for_window(
    transcript: list[schemas.LectureVideoManifestWordV3],
    *,
    start_offset_ms: int,
    end_offset_ms: int,
) -> list[schemas.LectureVideoManifestWordV3]:
    return [
        word
        for word in transcript
        if word.end_offset_ms >= start_offset_ms
        and word.start_offset_ms <= end_offset_ms
    ]


def _word_to_manifest_word(word: Any, *, word_index: int) -> dict[str, Any]:
    word_id = getattr(word, "id", None)
    word_text = getattr(word, "word", None)
    start = getattr(word, "start", None)
    end = getattr(word, "end", None)
    if isinstance(word, dict):
        word_id = word.get("id", word_id)
        word_text = word.get("word", word_text)
        start = word.get("start", start)
        end = word.get("end", end)
    if word_text is None or start is None or end is None:
        raise ValueError(f"Transcription word {word_index} is missing required fields.")
    return {
        "id": str(word_id if word_id is not None else word_index),
        "word": str(word_text),
        "start_offset_ms": _timestamp_to_ms(start),
        "end_offset_ms": _timestamp_to_ms(end),
    }


def _log_empty_transcription_word(
    manifest_words: list[dict[str, Any]],
    *,
    index: int,
) -> None:
    word = manifest_words[index]
    previous_word = next(
        (
            str(candidate["word"])
            for candidate in reversed(manifest_words[:index])
            if candidate["word"] != ""
        ),
        None,
    )
    next_word = next(
        (
            str(candidate["word"])
            for candidate in manifest_words[index + 1 :]
            if candidate["word"] != ""
        ),
        None,
    )
    logger.warning(
        "Skipping empty OpenAI transcription word. index=%s start_offset_ms=%s "
        "end_offset_ms=%s previous_word=%r next_word=%r",
        index,
        word["start_offset_ms"],
        word["end_offset_ms"],
        previous_word,
        next_word,
    )


def _prepare_lecture_video_audio_for_whisper(*, video_path: str, temp_dir: str) -> str:
    ffmpeg_path = shutil.which("ffmpeg")
    if ffmpeg_path is None:
        raise RuntimeError("ffmpeg is required for lecture video transcription.")

    last_size: int | None = None
    acceptable_path: str | None = None
    for bitrate in _TRANSCRIPTION_AUDIO_BITRATES:
        output_path = str(
            Path(temp_dir) / f"lecture-video-transcription-{bitrate}.webm"
        )
        try:
            subprocess.run(
                [
                    ffmpeg_path,
                    "-y",
                    "-i",
                    video_path,
                    "-vn",
                    "-ac",
                    "1",
                    "-ar",
                    str(_TRANSCRIPTION_AUDIO_SAMPLE_RATE),
                    "-c:a",
                    "libopus",
                    "-b:a",
                    bitrate,
                    "-application",
                    "voip",
                    output_path,
                ],
                capture_output=True,
                text=True,
                check=True,
                timeout=60 * 10,
            )
        except (
            subprocess.CalledProcessError,
            subprocess.TimeoutExpired,
        ) as exc:
            try:
                os.remove(output_path)
            except OSError:
                logger.warning(
                    "Failed to remove failed lecture video transcription audio %s",
                    output_path,
                    exc_info=True,
                )
            raise RuntimeError(
                "Failed to prepare lecture video audio for transcription."
            ) from exc

        size = os.path.getsize(output_path)
        last_size = size
        logger.info(
            "Prepared lecture video audio for Whisper. bitrate=%s size_bytes=%s",
            bitrate,
            size,
        )
        if size <= _WHISPER_UPLOAD_TARGET_BYTES:
            if acceptable_path is not None:
                try:
                    os.remove(acceptable_path)
                except OSError:
                    logger.warning(
                        "Failed to remove previous lecture video transcription "
                        "audio %s",
                        acceptable_path,
                        exc_info=True,
                    )
            return output_path

        if size <= _WHISPER_UPLOAD_MAX_BYTES:
            if acceptable_path is not None:
                try:
                    os.remove(acceptable_path)
                except OSError:
                    logger.warning(
                        "Failed to remove previous lecture video transcription "
                        "audio %s",
                        acceptable_path,
                        exc_info=True,
                    )
            acceptable_path = output_path
            continue

        try:
            os.remove(output_path)
        except OSError:
            logger.warning(
                "Failed to remove oversized lecture video transcription audio %s",
                output_path,
                exc_info=True,
            )

    if acceptable_path is not None:
        return acceptable_path

    raise ValueError(
        "Lecture video audio is too large for Whisper after compression "
        f"(last size: {last_size or 0} bytes; limit: {_WHISPER_UPLOAD_MAX_BYTES} bytes)."
    )


async def _prepare_lecture_video_audio_for_whisper_async(
    *, video_path: str, temp_dir: str
) -> str:
    return await asyncio.to_thread(
        _prepare_lecture_video_audio_for_whisper,
        video_path=video_path,
        temp_dir=temp_dir,
    )


async def transcribe_video_words(
    video_path: str,
    openai_client: openai.AsyncClient | openai.AsyncAzureOpenAI,
    *,
    temp_dir: str,
) -> list[schemas.LectureVideoManifestWordV3]:
    path_to_send = await _prepare_lecture_video_audio_for_whisper_async(
        video_path=video_path,
        temp_dir=temp_dir,
    )
    with open(path_to_send, "rb") as audio_file:
        transcription = await openai_client.audio.transcriptions.create(
            file=audio_file,
            model="whisper-1",
            response_format="verbose_json",
            timestamp_granularities=["word"],
            timeout=60 * 20,
        )

    words = getattr(transcription, "words", None)
    if words is None and isinstance(transcription, dict):
        words = transcription.get("words")
    if not words:
        raise ValueError("OpenAI transcription returned no word-level timestamps.")

    manifest_words = [
        _word_to_manifest_word(word, word_index=index)
        for index, word in enumerate(words)
    ]
    non_empty_manifest_words = []
    for index, word in enumerate(manifest_words):
        if word["word"] == "":
            _log_empty_transcription_word(manifest_words, index=index)
            continue
        non_empty_manifest_words.append(word)
    if not non_empty_manifest_words:
        raise ValueError("OpenAI transcription returned no non-empty words.")
    return [
        schemas.LectureVideoManifestWordV3.model_validate(word)
        for word in non_empty_manifest_words
    ]


async def _ffprobe_duration_ms(video_path: str) -> int | None:
    def run_ffprobe() -> int | None:
        ffprobe_path = shutil.which("ffprobe")
        if ffprobe_path is None:
            _log_missing_ffprobe_once()
            return None
        try:
            result = subprocess.run(
                [
                    ffprobe_path,
                    "-v",
                    "quiet",
                    "-show_entries",
                    "format=duration",
                    "-of",
                    "csv=p=0",
                    video_path,
                ],
                capture_output=True,
                text=True,
                check=True,
                timeout=30,
            )
            return _timestamp_to_ms(float(result.stdout.strip()))
        except (
            subprocess.CalledProcessError,
            subprocess.TimeoutExpired,
            ValueError,
        ):
            logger.warning("Failed to determine lecture video duration.", exc_info=True)
            return None

    return await asyncio.to_thread(run_ffprobe)


async def upload_video_to_gemini(
    video_path: str,
    client: AsyncClient,
    *,
    poll_interval_seconds: float = 2,
    timeout_seconds: float = 600,
) -> GeminiFileRef:
    gemini_file = await client.files.upload(file=video_path)
    started_at = time.monotonic()
    while getattr(getattr(gemini_file, "state", None), "name", "") == "PROCESSING":
        if time.monotonic() - started_at > timeout_seconds:
            raise TimeoutError("Gemini file processing timed out.")
        await asyncio.sleep(poll_interval_seconds)
        gemini_file = await client.files.get(name=gemini_file.name)
    if getattr(getattr(gemini_file, "state", None), "name", "") == "FAILED":
        raise ValueError(f"Gemini file processing failed: {gemini_file.state}")
    return GeminiFileRef(
        name=gemini_file.name,
        uri=getattr(gemini_file, "uri", None),
        mime_type=getattr(gemini_file, "mime_type", None),
    )


async def delete_gemini_file(name: str | None, client: AsyncClient) -> None:
    if not name:
        return
    try:
        await gemini_helpers.delete_file(client, name)
    except Exception:
        logger.warning("Failed to delete Gemini file %s.", name, exc_info=True)


async def _write_video_clip(
    video_path: str,
    *,
    temp_dir: str,
    chunk: ManifestGenerationChunk,
) -> str:
    def run_ffmpeg() -> str:
        ffmpeg_path = shutil.which("ffmpeg")
        if ffmpeg_path is None:
            raise RuntimeError(
                "ffmpeg is required for chunked lecture video generation."
            )

        source_suffix = Path(video_path).suffix or ".mp4"
        output_path = (
            Path(temp_dir)
            / f"manifest_chunk_{chunk.context_start_ms}_{chunk.context_end_ms}{source_suffix}"
        )
        duration_seconds = (chunk.context_end_ms - chunk.context_start_ms) / 1000
        subprocess.run(
            [
                ffmpeg_path,
                "-y",
                "-ss",
                f"{chunk.context_start_ms / 1000:.3f}",
                "-t",
                f"{duration_seconds:.3f}",
                "-i",
                video_path,
                "-map",
                "0",
                "-c",
                "copy",
                "-avoid_negative_ts",
                "make_zero",
                str(output_path),
            ],
            capture_output=True,
            text=True,
            check=True,
            timeout=60 * 20,
        )
        return str(output_path)

    return await asyncio.to_thread(run_ffmpeg)


def build_generation_prompt(
    content_section: str,
    transcript: list[schemas.LectureVideoManifestWordV3],
    *,
    compact: bool = False,
    video_duration_ms: int | None = None,
    generation_start_ms: int | None = None,
    generation_end_ms: int | None = None,
    context_start_ms: int | None = None,
    context_end_ms: int | None = None,
) -> str:
    if compact:
        transcript_text = "\n".join(
            f"{word.id}|{word.start_offset_ms / 1000}|{word.end_offset_ms / 1000}|{word.word.replace('|', '/')}"
            for word in transcript
        )
        transcript_description = "Each transcript line is id|start|end|word."
    else:
        transcript_text = json.dumps(
            [
                _word_to_generation_word(word, index)
                for index, word in enumerate(transcript)
            ],
            indent=2,
        )
        transcript_description = """A word-level transcript of the lesson. Each word has a unique "id", a "start" timestamp, an "end" timestamp, and the "word" text:
[
{{"id": "0", "word": "Hello", "start": 0.00, "end": 0.52}},
{{"id": "1", "word": "Let's", "start": 1.26, "end": 1.66}},
{{"id": "2", "word": "imagine", "start": 1.66, "end": 2.10}},
...
]"""

    duration_text = (
        f"\nThe video duration is {video_duration_ms} milliseconds."
        if video_duration_ms is not None
        else ""
    )
    generation_window_text = ""
    video_description_scope = "the whole video"
    video_description_start_rule = (
        "Use consecutive millisecond ranges starting at 0: 0-30000, "
        "30000-60000, 60000-90000, and so on through the full video."
    )
    video_description_end_rule = (
        "The final segment must end exactly at the video duration. It may be "
        "shorter than 30 seconds. Never set the final end_offset_ms after the "
        "end of the video."
    )
    video_description_reminder = (
        'The top-level "video_descriptions" array is REQUIRED for video-based '
        "generation. It must be non-empty and must use contiguous millisecond "
        "windows starting at 0. The final segment must end exactly at the video "
        "duration, not after it."
    )
    if generation_start_ms is not None and generation_end_ms is not None:
        video_description_scope = "the requested generation window"
        video_description_start_rule = (
            "Use consecutive millisecond ranges starting at the requested "
            "generation window start. Use absolute offsets from the original "
            "video, not clip-relative offsets."
        )
        video_description_end_rule = (
            "The final segment must end exactly at the requested generation "
            "window end. It may be shorter than 30 seconds. Never set the final "
            "end_offset_ms after the requested generation window end."
        )
        video_description_reminder = (
            'The top-level "video_descriptions" array is REQUIRED for '
            "video-based generation. It must be non-empty and must use "
            "contiguous millisecond windows starting at the requested generation "
            "window start. The final segment must end exactly at the requested "
            "generation window end, not after it."
        )
        context_window_text = (
            f" The provided video clip covers absolute offsets "
            f"{context_start_ms}ms through {context_end_ms}ms."
            if context_start_ms is not None and context_end_ms is not None
            else ""
        )
        generation_window_text = f"""

CHUNK BOUNDARIES:
This is one chunk from a longer lecture video.{context_window_text}
Clip time 0 corresponds to absolute offset {context_start_ms or 0}ms in the original video.
Use the whole clip as context, but generate output ONLY for the generation window from {generation_start_ms}ms through {generation_end_ms}ms.
Do not create questions with pause points before {generation_start_ms}ms or after {generation_end_ms}ms.
Generate "video_descriptions" starting exactly at {generation_start_ms}ms and ending exactly at {generation_end_ms}ms.
Every non-final video description segment inside this generation window must be exactly 30000ms long.
"""

    return f"""You are an expert educational content designer specializing in interactive video lessons. You speak as the teacher in first person, directly to the student.

You will be given a lecture video and a word-level transcript. {transcript_description}{duration_text}
{generation_window_text}

Here's the WORD-LEVEL TRANSCRIPT:
{transcript_text}

TO-DO's FOR SUCCESSFUL QUIZ-GENERATION:
To ensure high confidence in analyzing the lesson, watch the video along with the transcript. Don't make up anything or assume based on your preconceived idea of the lecture - always remember you have the transcript.

YOUR TASK:
Analyze the provided lesson materials to identify natural pause points where a multiple-choice comprehension check can be inserted. At each pause point, the video will stop, a question will be displayed as text on screen, and a voice clone of the teacher will introduce the question out loud. After the student selects an answer, the voice clone will give spoken feedback, and the video will resume. The resume point may differ depending on which answer the student chose.

Also create a top-level "video_descriptions" array that describes what is visibly happening in fixed 30-second windows across {video_description_scope}.

VISUAL DESCRIPTION GUIDELINES:
- {video_description_start_rule}
- Every segment except the final segment must be exactly 30 seconds long.
- {video_description_end_rule}
- Each segment description should be concise and general-purpose, usually 1-2 sentences.
- Focus only on observable teaching state: screen or board contents, written text, diagrams, values, equations, cursor movement, gesture emphasis, and meaningful visual changes.
- Do not infer concepts from visuals alone. Tie visual details to what can actually be seen.
- If the visual state is mostly unchanged from the prior window, briefly say what remains visible and note any small meaningful changes.

IMPORTANT CONTEXT:
- The student sees subtitles/captions during playback, so they both hear and read what the teacher says. For your purposes, that means attention-based questions are not useful here.
- The voice-over feedback is spoken by a clone of the teacher's voice. It must sound like the teacher is speaking directly to the student in first person — not a separate narrator or tutor commenting from the outside.
- The feedback voice-over is spliced into the lecture audio. When the video resumes, the teacher's voice continues seamlessly. Your feedback must flow naturally into whatever the teacher says at the determined resume point — as if it were all one continuous spoken experience.

EDITABLE GENERATION GUIDANCE:
{content_section.strip() or DEFAULT_GENERATION_PROMPT_CONTENT}

GUIDELINES FOR VOICE AND PERSPECTIVE:
- You ARE the teacher. Speak in first person, directly to the student.
- Match the tone and style of the teacher in the video: warm, friendly, supportive, and encouraging.
- NEVER reference "the video," "the story," "the lecture," "the speaker," "the teacher," or "the professor." Do not describe the video from the outside.
- NEVER describe or summarize what happened in the video. The student just watched it — they know.
- Everything should feel like the teacher is personally interacting with the student in real time.

GUIDELINES FOR VOICE-OVER INTRO:
- The voice_over_intro is a spoken line played BEFORE the question appears on screen. It gives the student an audio cue that the video is pausing for interaction.
- The approach depends on the question source:

  FOR TEACHER-POSED QUESTIONS (question_source: "teacher"):
  - The teacher already asked the question out loud — the student heard it.
  - voice_over_intro should be empty ("") or at most a brief nudge like "What do you think?" or "Go ahead and pick one."
  - Do NOT restate, rephrase, or summarize the teacher's question.

  FOR AI-GENERATED QUESTIONS (question_source: "generated"):
  - The student has NO audio cue that the video is pausing. Without an intro, the video silently freezes and the student is left reading cold.
  - voice_over_intro MUST contain two parts:
    1. A brief pause cue that signals the interaction (e.g., "Let's pause for a quick check.").
    2. A natural spoken version of the question itself.
  - Combine them into one short, flowing line. Examples:
    - "Quick check — what do angles on a straight line add up to?"
    - "Before we move on: does the inequality sign flip or stay the same?"
    - "Let's make sure we've got this. What's the first step when solving for x?"
    - "Hold on — is that fraction in simplest form?"
  - The spoken question does NOT need to match question_text word-for-word. It should sound natural when spoken aloud, while question_text is optimized for on-screen reading. They convey the same question but may be worded differently.
  - Vary the pause cue phrasing across questions — do not reuse the same opener within a single video.

GUIDELINES FOR VOICE-OVER FEEDBACK:
- Provide a unique spoken response for EACH choice.
- For incorrect answers, lead with a brief indicator (e.g., "Not quite," "Oops," "Hmm, not exactly") before any correction or transition. Don't over-soften.
- Keep feedback to 1-2 sentences max.
- The feedback is spliced directly into the lecture. After the feedback plays, the video resumes at the resume point for that choice. The combined experience — your feedback followed by the teacher's words at the resume point — must sound natural, non-redundant, and coherent.
- Since the student sees subtitles during playback, do NOT repeat information the teacher is about to say at the resume point. If the teacher is about to reveal or explain the answer, let them — your feedback should set up the transition, not steal it.
- Before writing feedback for each choice, read the transcript starting at the resume point. Ask yourself: does the teacher address this answer (confirm it, explain it, or build on it) in their next few sentences?
-- If YES: your feedback is ONLY a brief reaction — "Exactly!", "Not quite.",
  etc. Do NOT explain, bridge, or preview. The teacher handles it.
-- If NO: your feedback must close the loop — provide the correction,
  explanation, or transition that the student needs, because the teacher
  won't.
-- The mistake to avoid: writing bridge/setup language ("Let's see how this
works", "Let's use a diagram to check") when the teacher is about to do
exactly that. That creates redundancy. But if the teacher moves on without
addressing the concept, your feedback IS the only place the student gets
closure — so don't be too brief in that case.
- The goal: feedback + resumed video = one smooth, continuous, non-repetitive experience.

HOW TO SPECIFY TIMESTAMPS — CRITICAL:
You MUST specify pause and resume points using word IDs from the transcript, NOT by inventing timestamps.

WARNING: Word IDs in the transcript are NOT necessarily sequential indices into the text. You MUST look up the actual "id" field from the transcript entry for each word. Do NOT count words manually or guess IDs based on position. The "id", "word", "start", and "end" fields must ALL come from the same transcript entry and must be copied exactly.

OUTPUT FORMAT:
Return a single JSON object. Do not include any text outside the JSON.
```json
{{
  "video_summary": "Brief description of the video topic",
  "video_descriptions": [
    {{
      "start_offset_ms": 0,
      "end_offset_ms": 30000,
      "description": "The teacher's screen shows a slide with a title and two bullet points. A cursor circles the first bullet while the speaker emphasizes the main idea."
    }},
    {{
      "start_offset_ms": 30000,
      "end_offset_ms": 60000,
      "description": "The same slide remains visible while a short example is added underneath the bullets. The cursor moves between the example and the earlier text to connect them."
    }}
  ],
  "questions": [
    {{
      "id": 1,
      "question_source": "teacher",
      "pause_after_word_id": "77",
      "pause_after_word": "correct",
      "pause_at": 26.80,
      "voice_over_intro": "",
      "question_text": "Is it correct to round 2.4 up to 3?",
      "choices": [
        {{"text": "Yes", "misconception": "Thinks any digit above 0 rounds up, ignoring the 5-or-above rule"}},
        {{"text": "No", "misconception": null}}
      ],

      "correct_answer": "No",
      "choice_feedback": {{
        "Yes": {{
          "voice_over": "Hmm, not quite.",
          "resume_at_word_id": "78",
          "resume_at_word": "Well",
          "resume_at": 27.58
        }},
        "No": {{
          "voice_over": "Good instinct!",
          "resume_at_word_id": "78",
          "resume_at_word": "Well",
          "resume_at": 27.58
        }}
      }}
    }},
    {{
      "id": 2,
      "question_source": "generated",
      "pause_after_word_id": "120",
      "pause_after_word": "together",
      "pause_at": 42.15,
      "voice_over_intro": "Let's pause here for a quick check. What place value do you look at when rounding to the nearest ten?",
      "question_text": "What place value do you look at when rounding to the nearest ten?",
      "choices": [
        {{"text": "The ones place", "misconception": null}},
        {{"text": "The tens place", "misconception": "Confuses the place being rounded with the digit that determines rounding"}},
        {{"text": "The hundreds place", "misconception": "Looks at a higher place value instead of the digit immediately to the right"}}
      ],
      "correct_answer": "The ones place",
      "choice_feedback": {{
        "The ones place": {{
          "voice_over": "That's right!",
          "resume_at_word_id": "121",
          "resume_at_word": "So",
          "resume_at": 43.00
        }},
        "The tens place": {{
          "voice_over": "Not quite — you look at the digit to the right of the place you're rounding to, which is the ones place.",
          "resume_at_word_id": "121",
          "resume_at_word": "So",
          "resume_at": 43.00
        }},
        "The hundreds place": {{
          "voice_over": "Not quite — you look at the digit to the right of the place you're rounding to, which is the ones place.",
          "resume_at_word_id": "121",
          "resume_at_word": "So",
          "resume_at": 43.00
        }}
      }}
    }}
  ]
}}
```

FIELD DEFINITIONS:
- "question_source": Either "teacher" (based on a question the teacher posed in the video) or "generated" (a comprehension check you created). This determines voice_over_intro requirements.
- "pause_after_word_id": The "id" of the last word the student hears before the pause. Copied exactly from the transcript.
- "pause_after_word": The "word" text of that transcript entry. Copied exactly.
- "pause_at": The "end" timestamp of the pause word. Copied exactly from the transcript — do not round or modify.
- "voice_over_intro": Brief first-person spoken intro. For "generated" questions, this must include both a pause cue and a spoken version of the question. For "teacher" questions, empty or minimal.
- "question_text": The question displayed as text on screen.
- "choices": Array of answer choice objects. Each object contains:
  - "text": The answer choice string. No letter labels.
  - "misconception": For distractors (incorrect choices), a brief description of the common misconception or error this choice is designed to surface. For the correct answer, this is null. This field is for analytics only — it is never shown to the student.
- "correct_answer": The correct choice string, matching the "text" of one entry in choices exactly.
- "choice_feedback": Object keyed by each choice's "text" string, containing:
  - "voice_over": The spoken feedback for this choice (1-2 sentences).
  - "resume_at_word_id": The "id" of the first word the student hears when the video resumes after this choice. Copied exactly from the transcript.
  - "resume_at_word": The "word" text of that transcript entry. Copied exactly.
  - "resume_at": The "start" timestamp of the resume word. Copied exactly from the transcript — do not round or modify.
- "video_descriptions": Array of contiguous visual segments covering the whole video. Each non-final segment is 30 seconds; the final segment ends exactly at the video duration and may be shorter. Each segment contains:
  - "start_offset_ms": Integer millisecond offset where this visual window starts.
  - "end_offset_ms": Integer millisecond offset where this visual window ends. This must be exactly 30000ms after start_offset_ms except for the final segment, which must equal the video duration.
  - "description": Concise observable description of the teaching visuals in that window.

IMPORTANT REMINDERS:
- ALL word IDs and timestamps must come directly from the transcript entries. Look up each word's actual "id" field — do not count or guess. Copy "word", "start", and "end" exactly.
- For teacher-posed questions: let them ask it, pause after the question, and resume into the teacher's own answer — do NOT skip past it.
- For "generated" questions, voice_over_intro MUST include both a pause cue and the question spoken aloud. The student needs to hear it, not just read it.
- {video_description_reminder}

REDUNDANCY CHECK:
- Before finalizing each voice_over, read it concatenated with the teacher's words starting at the resume point. If any fact, number, or concept appears in both your feedback AND the teacher's next sentence, remove it from your feedback. The combined audio must never say the same thing twice.

Now analyze the provided lesson materials and generate the interactive question layer.

"""


def _is_context_limit_error(exc: Exception) -> bool:
    return (
        "input token count exceeds the maximum number of tokens allowed"
        in str(exc).lower()
    )


def _should_split_manifest_chunk_error(exc: Exception) -> bool:
    error_text = str(exc).lower()
    return _is_context_limit_error(exc) or (
        "deadline expired" in error_text and "unavailable" in error_text
    )


def _is_retryable_gemini_generation_error(exc: Exception) -> bool:
    if _is_context_limit_error(exc):
        return False
    error_text = str(exc).lower()
    return any(
        marker in error_text
        for marker in (
            "500 internal",
            "503 unavailable",
            "internal error encountered",
            "deadline expired",
            "resource_exhausted",
            "429",
        )
    )


async def _generate_manifest_quiz_with_retries(
    gemini_client: AsyncClient,
    *,
    model: str,
    prompt: str,
    contents: types.ContentListUnion,
    response_model: type[_ResponseModelT],
    request_label: str,
) -> _ResponseModelT:
    for attempt in range(1, _GEMINI_GENERATION_MAX_ATTEMPTS + 1):
        try:
            return await gemini_helpers.generate_manifest_quiz(
                gemini_client,
                model=model,
                prompt=prompt,
                contents=contents,
                response_model=response_model,
            )
        except Exception as exc:
            if (
                attempt >= _GEMINI_GENERATION_MAX_ATTEMPTS
                or not _is_retryable_gemini_generation_error(exc)
            ):
                raise
            delay_seconds = _GEMINI_GENERATION_RETRY_DELAY_SECONDS * attempt
            logger.warning(
                "Retrying Gemini manifest generation after transient provider "
                "failure. request_label=%s attempt=%s max_attempts=%s "
                "delay_seconds=%.1f error=%s",
                request_label,
                attempt,
                _GEMINI_GENERATION_MAX_ATTEMPTS,
                delay_seconds,
                exc,
            )
            await asyncio.sleep(delay_seconds)
    raise RuntimeError("Gemini manifest generation retry loop exited unexpectedly.")


def _question_to_manifest_question(
    question: GeneratedQuestion,
    transcript_word_index: TranscriptWordIndex,
) -> schemas.LectureVideoManifestQuestionV1:
    choices = question.choices
    feedback_by_choice = question.choice_feedback
    correct_answer = question.correct_answer
    stop_offset_ms = _validated_transcript_timestamp_ms(
        transcript_word_index=transcript_word_index,
        word_id=question.pause_after_word_id,
        word_text=question.pause_after_word,
        timestamp=question.pause_at,
        timestamp_kind="end",
    )

    options = []
    correct_count = 0
    for choice in choices:
        choice_text = choice.text
        feedback = feedback_by_choice.get(choice_text)
        if feedback is None:
            raise ValueError(
                f"Generated question feedback is missing for choice {choice_text!r}."
            )
        is_correct = choice_text == correct_answer
        correct_count += 1 if is_correct else 0
        continue_offset_ms = _validated_transcript_timestamp_ms(
            transcript_word_index=transcript_word_index,
            word_id=feedback.resume_at_word_id,
            word_text=feedback.resume_at_word,
            timestamp=feedback.resume_at,
            timestamp_kind="start",
        )
        options.append(
            schemas.LectureVideoManifestOptionV1(
                option_text=choice_text,
                post_answer_text=feedback.voice_over,
                continue_offset_ms=continue_offset_ms,
                correct=is_correct,
            )
        )
    if correct_count != 1:
        raise ValueError("Generated question must have exactly one correct answer.")
    return schemas.LectureVideoManifestQuestionV1(
        type=schemas.LectureVideoQuestionType.SINGLE_SELECT,
        question_text=question.question_text,
        intro_text=question.voice_over_intro,
        stop_offset_ms=stop_offset_ms,
        options=options,
    )


def _fallback_video_descriptions(
    video_duration_ms: int | None,
    *,
    start_offset_ms: int = 0,
) -> list[schemas.LectureVideoManifestVideoDescriptionV3]:
    end_offset_ms = max(video_duration_ms or 1, start_offset_ms + 1)
    return [
        schemas.LectureVideoManifestVideoDescriptionV3(
            start_offset_ms=start_offset_ms,
            end_offset_ms=end_offset_ms,
            description="Visual descriptions were unavailable for this transcript-only generation pass.",
        )
    ]


def _video_descriptions_to_manifest_video_descriptions(
    video_descriptions: list[GeneratedVideoDescription],
) -> list[schemas.LectureVideoManifestVideoDescriptionV3]:
    return [
        schemas.LectureVideoManifestVideoDescriptionV3.model_validate(
            description.model_dump()
        )
        for description in video_descriptions
    ]


def _validate_manifest_video_descriptions(
    video_descriptions: list[schemas.LectureVideoManifestVideoDescriptionV3],
    *,
    start_offset_ms: int = 0,
    end_offset_ms: int | None,
) -> str | None:
    if len(video_descriptions) == 0:
        return "video_descriptions is empty"
    if end_offset_ms is None:
        return None

    expected_start_offset_ms = start_offset_ms
    for index, description in enumerate(video_descriptions):
        if description.start_offset_ms != expected_start_offset_ms:
            return (
                f"video_descriptions[{index}] starts at "
                f"{description.start_offset_ms}ms; expected "
                f"{expected_start_offset_ms}ms"
            )

        segment_duration_ms = description.end_offset_ms - description.start_offset_ms
        is_final_segment = index == len(video_descriptions) - 1
        if not is_final_segment and segment_duration_ms != _VIDEO_DESCRIPTION_WINDOW_MS:
            return (
                f"video_descriptions[{index}] duration is "
                f"{segment_duration_ms}ms; expected "
                f"{_VIDEO_DESCRIPTION_WINDOW_MS}ms"
            )
        if is_final_segment and segment_duration_ms > _VIDEO_DESCRIPTION_WINDOW_MS:
            return (
                f"final video description duration is {segment_duration_ms}ms; "
                f"expected at most {_VIDEO_DESCRIPTION_WINDOW_MS}ms"
            )

        expected_start_offset_ms = description.end_offset_ms

    final_end_offset_ms = video_descriptions[-1].end_offset_ms
    if final_end_offset_ms != end_offset_ms:
        return (
            f"final video description ends at {final_end_offset_ms}ms; "
            f"expected video duration {end_offset_ms}ms"
        )
    return None


def _validated_or_fallback_video_descriptions(
    video_descriptions: list[schemas.LectureVideoManifestVideoDescriptionV3],
    *,
    start_offset_ms: int = 0,
    end_offset_ms: int | None,
) -> list[schemas.LectureVideoManifestVideoDescriptionV3]:
    validation_error = _validate_manifest_video_descriptions(
        video_descriptions,
        start_offset_ms=start_offset_ms,
        end_offset_ms=end_offset_ms,
    )
    if validation_error is None:
        return video_descriptions

    logger.warning(
        "Generated video_descriptions failed structural validation: %s. "
        "Falling back to transcript-only visual description.",
        validation_error,
    )
    return _fallback_video_descriptions(
        end_offset_ms,
        start_offset_ms=start_offset_ms,
    )


def _validated_or_fallback_chunk_video_descriptions(
    video_descriptions: list[schemas.LectureVideoManifestVideoDescriptionV3],
    *,
    chunk_index: int,
    start_offset_ms: int,
    end_offset_ms: int,
) -> list[schemas.LectureVideoManifestVideoDescriptionV3]:
    validation_error = _validate_manifest_video_descriptions(
        video_descriptions,
        start_offset_ms=start_offset_ms,
        end_offset_ms=end_offset_ms,
    )
    if validation_error is None:
        return video_descriptions

    logger.warning(
        "Generated chunk video_descriptions failed structural validation: %s. "
        "chunk_index=%s Falling back for this chunk only.",
        validation_error,
        chunk_index,
    )
    return _fallback_video_descriptions(
        end_offset_ms,
        start_offset_ms=start_offset_ms,
    )


def _quiz_to_manifest(
    quiz: GeneratedQuizWithVideo,
    transcript: list[schemas.LectureVideoManifestWordV3],
    *,
    video_duration_ms: int | None,
    video_description_start_offset_ms: int = 0,
    video_description_end_offset_ms: int | None = None,
) -> schemas.LectureVideoManifestV3:
    transcript_word_index = _transcript_word_index(transcript)
    video_descriptions = _video_descriptions_to_manifest_video_descriptions(
        quiz.video_descriptions
    )
    video_descriptions = _validated_or_fallback_video_descriptions(
        video_descriptions,
        start_offset_ms=video_description_start_offset_ms,
        end_offset_ms=(
            video_description_end_offset_ms
            if video_description_end_offset_ms is not None
            else video_duration_ms
        ),
    )
    return schemas.LectureVideoManifestV3(
        word_level_transcription=transcript,
        video_descriptions=video_descriptions,
        questions=[
            _question_to_manifest_question(question, transcript_word_index)
            for question in quiz.questions
        ],
    )


def _gemini_contents_for_file(gemini_file: GeminiFileRef) -> types.ContentListUnion:
    if gemini_file.uri is None:
        raise ValueError("Gemini file is missing a URI.")
    return [
        types.Part.from_uri(
            file_uri=gemini_file.uri,
            mime_type=gemini_file.mime_type,
        )
    ]


def _filter_questions_for_window(
    questions: list[schemas.LectureVideoManifestQuestionV1],
    *,
    start_offset_ms: int,
    end_offset_ms: int,
    is_final_chunk: bool,
) -> list[schemas.LectureVideoManifestQuestionV1]:
    return [
        question
        for question in questions
        if start_offset_ms <= question.stop_offset_ms
        and (
            question.stop_offset_ms < end_offset_ms
            or (is_final_chunk and question.stop_offset_ms <= end_offset_ms)
        )
    ]


def _manifest_question_to_reconciliation_candidate(
    question: schemas.LectureVideoManifestQuestionV1,
) -> dict[str, Any]:
    return {
        "type": question.type.value,
        "question_text": question.question_text,
        "intro_text": question.intro_text,
        "stop_offset_ms": question.stop_offset_ms,
        "options": [
            {
                "option_text": option.option_text,
                "post_answer_text": option.post_answer_text,
                "continue_offset_ms": option.continue_offset_ms,
                "correct": option.correct,
            }
            for option in question.options
        ],
    }


def _reconciliation_prompt(generation_prompt_content: str) -> str:
    return f"""You are an expert educational content designer reconciling independently generated interactive question candidates from chunks of one lecture video.

You will be given:
- The instructor's generation guidance.
- The full word-level transcript for the complete video.
- The final merged video_descriptions for the complete video.
- Candidate questions generated independently from video chunks.

Your task is to create the final question list for the complete video.

Global requirements:
- Follow the instructor's generation guidance globally, not per chunk. If it asks for a specific number of questions, output that number total across the whole video.
- Candidate questions are suggestions, not requirements. You may keep, drop, rewrite, merge, or replace them to satisfy the instructor guidance.
- Remove duplicate or near-duplicate questions, especially near chunk boundaries.
- Prefer natural conceptual breakpoints and keep the selected questions appropriately spread across the complete video unless the instructor guidance says otherwise.
- Preserve teacher-posed questions when they are pedagogically better than generated questions.
- Do not include questions that depend on context outside their pause/resume location.
- All pause and resume word IDs, words, and timestamps in your output must come exactly from the full transcript.
- Do not invent word IDs or timestamps. Copy the "id", "word", "start", and "end" values from one transcript entry.
- For teacher-posed questions, let the teacher ask the question and pause after the full question.
- For generated questions, voice_over_intro must include both a pause cue and the question spoken aloud.
- Output only JSON matching the requested schema.

INSTRUCTOR GENERATION GUIDANCE:
{generation_prompt_content.strip() or DEFAULT_GENERATION_PROMPT_CONTENT}
"""


def _reconciliation_payload(
    *,
    transcript: list[schemas.LectureVideoManifestWordV3],
    video_descriptions: list[schemas.LectureVideoManifestVideoDescriptionV3],
    chunk_manifests: list[schemas.LectureVideoManifestV3],
    video_duration_ms: int | None,
) -> str:
    payload = {
        "video_duration_ms": video_duration_ms,
        "word_level_transcript": [
            _word_to_generation_word(word, index)
            for index, word in enumerate(transcript)
        ],
        "video_descriptions": [
            description.model_dump() for description in video_descriptions
        ],
        "candidate_question_groups": [
            {
                "candidate_group_index": index,
                "questions": [
                    _manifest_question_to_reconciliation_candidate(question)
                    for question in manifest.questions
                ],
            }
            for index, manifest in enumerate(chunk_manifests)
        ],
    }
    return json.dumps(payload, indent=2)


def _final_questions_to_manifest(
    quiz: ReconciledGeneratedQuiz,
    transcript: list[schemas.LectureVideoManifestWordV3],
) -> list[schemas.LectureVideoManifestQuestionV1]:
    transcript_word_index = _transcript_word_index(transcript)
    return [
        _question_to_manifest_question(question, transcript_word_index)
        for question in quiz.questions
    ]


async def _reconcile_chunk_questions(
    *,
    gemini_client: AsyncClient,
    generation_prompt_content: str,
    transcript: list[schemas.LectureVideoManifestWordV3],
    video_descriptions: list[schemas.LectureVideoManifestVideoDescriptionV3],
    chunk_manifests: list[schemas.LectureVideoManifestV3],
    video_duration_ms: int | None,
    model: str,
) -> list[schemas.LectureVideoManifestQuestionV1]:
    quiz = await _generate_manifest_quiz_with_retries(
        gemini_client,
        model=model,
        prompt=_reconciliation_prompt(generation_prompt_content),
        contents=[
            types.Part.from_text(
                text=_reconciliation_payload(
                    transcript=transcript,
                    video_descriptions=video_descriptions,
                    chunk_manifests=chunk_manifests,
                    video_duration_ms=video_duration_ms,
                )
            )
        ],
        response_model=ReconciledGeneratedQuiz,
        request_label="manifest_reconciliation",
    )
    return _final_questions_to_manifest(quiz, transcript)


async def _merge_chunk_manifests(
    *,
    gemini_client: AsyncClient,
    generation_prompt_content: str,
    model: str,
    chunk_manifests: list[schemas.LectureVideoManifestV3],
    full_transcript: list[schemas.LectureVideoManifestWordV3],
    video_duration_ms: int | None,
) -> schemas.LectureVideoManifestV3:
    if video_duration_ms is None:
        video_descriptions = [
            description
            for manifest in chunk_manifests
            for description in manifest.video_descriptions
        ]
        video_descriptions = _validated_or_fallback_video_descriptions(
            video_descriptions,
            end_offset_ms=video_duration_ms,
        )
    else:
        video_descriptions = []
        expected_start_offset_ms = 0
        for index, manifest in enumerate(chunk_manifests):
            chunk_end_offset_ms = (
                video_duration_ms
                if index == len(chunk_manifests) - 1
                else max(
                    manifest.video_descriptions[-1].end_offset_ms,
                    expected_start_offset_ms + 1,
                )
            )
            chunk_descriptions = _validated_or_fallback_chunk_video_descriptions(
                manifest.video_descriptions,
                chunk_index=index,
                start_offset_ms=expected_start_offset_ms,
                end_offset_ms=chunk_end_offset_ms,
            )
            video_descriptions.extend(chunk_descriptions)
            expected_start_offset_ms = chunk_descriptions[-1].end_offset_ms
        if expected_start_offset_ms < video_duration_ms:
            video_descriptions.extend(
                _fallback_video_descriptions(
                    video_duration_ms,
                    start_offset_ms=expected_start_offset_ms,
                )
            )
    questions = await _reconcile_chunk_questions(
        gemini_client=gemini_client,
        generation_prompt_content=generation_prompt_content,
        transcript=full_transcript,
        video_descriptions=video_descriptions,
        chunk_manifests=chunk_manifests,
        video_duration_ms=video_duration_ms,
        model=model,
    )
    return schemas.LectureVideoManifestV3(
        word_level_transcription=full_transcript,
        video_descriptions=video_descriptions,
        questions=questions,
    )


async def _generate_manifest_from_gemini_file(
    *,
    gemini_client: AsyncClient,
    gemini_file: GeminiFileRef,
    generation_prompt_content: str,
    transcript: list[schemas.LectureVideoManifestWordV3],
    video_duration_ms: int | None,
    model: str,
    compact: bool = False,
    generation_start_ms: int | None = None,
    generation_end_ms: int | None = None,
    context_start_ms: int | None = None,
    context_end_ms: int | None = None,
) -> schemas.LectureVideoManifestV3:
    prompt = build_generation_prompt(
        generation_prompt_content,
        transcript,
        compact=compact,
        video_duration_ms=video_duration_ms,
        generation_start_ms=generation_start_ms,
        generation_end_ms=generation_end_ms,
        context_start_ms=context_start_ms,
        context_end_ms=context_end_ms,
    )
    request_label = (
        "manifest_chunk_compact"
        if compact
        else "manifest_chunk"
        if generation_start_ms is not None
        else "manifest_full"
    )
    quiz = await _generate_manifest_quiz_with_retries(
        gemini_client,
        model=model,
        prompt=prompt,
        contents=_gemini_contents_for_file(gemini_file),
        response_model=GeneratedQuizWithVideo,
        request_label=request_label,
    )
    return _quiz_to_manifest(
        quiz,
        transcript,
        video_duration_ms=video_duration_ms,
        video_description_start_offset_ms=generation_start_ms or 0,
        video_description_end_offset_ms=generation_end_ms,
    )


async def generate_manifest(
    *,
    video_path: str,
    gemini_client: AsyncClient,
    gemini_file: GeminiFileRef,
    generation_prompt_content: str,
    transcript: list[schemas.LectureVideoManifestWordV3],
    model: str = _GEMINI_MODEL,
) -> schemas.LectureVideoManifestV3:
    video_duration_ms = await _ffprobe_duration_ms(video_path)
    try:
        return await _generate_manifest_from_gemini_file(
            gemini_client=gemini_client,
            gemini_file=gemini_file,
            generation_prompt_content=generation_prompt_content,
            transcript=transcript,
            video_duration_ms=video_duration_ms,
            model=model,
        )
    except Exception as exc:
        if not _is_context_limit_error(exc):
            raise
        return await _generate_manifest_from_gemini_file(
            gemini_client=gemini_client,
            gemini_file=gemini_file,
            generation_prompt_content=generation_prompt_content,
            transcript=transcript,
            video_duration_ms=video_duration_ms,
            model=model,
            compact=True,
        )


async def _upload_and_generate_whole_manifest(
    *,
    video_path: str,
    gemini_client: AsyncClient,
    generation_prompt_content: str,
    transcript: list[schemas.LectureVideoManifestWordV3],
    video_duration_ms: int | None,
    model: str,
) -> schemas.LectureVideoManifestV3:
    gemini_file_name: str | None = None
    try:
        logger.info("Uploading full lecture video to Gemini for manifest generation.")
        gemini_file = await upload_video_to_gemini(video_path, gemini_client)
        gemini_file_name = gemini_file.name
        logger.info(
            "Generating lecture video manifest from full Gemini upload. gemini_file=%s",
            gemini_file_name,
        )
        try:
            return await _generate_manifest_from_gemini_file(
                gemini_client=gemini_client,
                gemini_file=gemini_file,
                generation_prompt_content=generation_prompt_content,
                transcript=transcript,
                video_duration_ms=video_duration_ms,
                model=model,
            )
        except Exception as exc:
            if not _is_context_limit_error(exc):
                raise
            return await _generate_manifest_from_gemini_file(
                gemini_client=gemini_client,
                gemini_file=gemini_file,
                generation_prompt_content=generation_prompt_content,
                transcript=transcript,
                video_duration_ms=video_duration_ms,
                model=model,
                compact=True,
            )
    finally:
        if gemini_file_name is not None:
            logger.info(
                "Deleting full lecture video Gemini upload. gemini_file=%s",
                gemini_file_name,
            )
            await delete_gemini_file(gemini_file_name, gemini_client)


async def _upload_and_generate_manifest_chunk(
    *,
    video_path: str,
    gemini_client: AsyncClient,
    generation_prompt_content: str,
    transcript: list[schemas.LectureVideoManifestWordV3],
    video_duration_ms: int,
    chunk: ManifestGenerationChunk,
    temp_dir: str,
    model: str,
) -> schemas.LectureVideoManifestV3:
    chunk_transcript = _transcript_for_window(
        transcript,
        start_offset_ms=chunk.context_start_ms,
        end_offset_ms=chunk.context_end_ms,
    )
    clip_path = await _write_video_clip(video_path, temp_dir=temp_dir, chunk=chunk)
    gemini_file_name: str | None = None
    try:
        logger.info(
            "Uploading lecture video chunk to Gemini for manifest generation. "
            "generation_start_ms=%s generation_end_ms=%s context_start_ms=%s "
            "context_end_ms=%s",
            chunk.generation_start_ms,
            chunk.generation_end_ms,
            chunk.context_start_ms,
            chunk.context_end_ms,
        )
        gemini_file = await upload_video_to_gemini(clip_path, gemini_client)
        gemini_file_name = gemini_file.name
        logger.info(
            "Generating lecture video manifest chunk. gemini_file=%s "
            "generation_start_ms=%s generation_end_ms=%s",
            gemini_file_name,
            chunk.generation_start_ms,
            chunk.generation_end_ms,
        )
        try:
            manifest = await _generate_manifest_from_gemini_file(
                gemini_client=gemini_client,
                gemini_file=gemini_file,
                generation_prompt_content=generation_prompt_content,
                transcript=chunk_transcript,
                video_duration_ms=video_duration_ms,
                model=model,
                generation_start_ms=chunk.generation_start_ms,
                generation_end_ms=chunk.generation_end_ms,
                context_start_ms=chunk.context_start_ms,
                context_end_ms=chunk.context_end_ms,
            )
        except Exception as exc:
            if not _is_context_limit_error(exc):
                raise
            manifest = await _generate_manifest_from_gemini_file(
                gemini_client=gemini_client,
                gemini_file=gemini_file,
                generation_prompt_content=generation_prompt_content,
                transcript=chunk_transcript,
                video_duration_ms=video_duration_ms,
                model=model,
                compact=True,
                generation_start_ms=chunk.generation_start_ms,
                generation_end_ms=chunk.generation_end_ms,
                context_start_ms=chunk.context_start_ms,
                context_end_ms=chunk.context_end_ms,
            )
        manifest.questions = _filter_questions_for_window(
            manifest.questions,
            start_offset_ms=chunk.generation_start_ms,
            end_offset_ms=chunk.generation_end_ms,
            is_final_chunk=chunk.generation_end_ms == video_duration_ms,
        )
        return manifest
    finally:
        if gemini_file_name is not None:
            logger.info(
                "Deleting lecture video chunk Gemini upload. gemini_file=%s",
                gemini_file_name,
            )
            await delete_gemini_file(gemini_file_name, gemini_client)


async def _upload_and_generate_manifest_chunks(
    *,
    video_path: str,
    gemini_client: AsyncClient,
    generation_prompt_content: str,
    transcript: list[schemas.LectureVideoManifestWordV3],
    video_duration_ms: int,
    chunk: ManifestGenerationChunk,
    temp_dir: str,
    model: str,
) -> list[schemas.LectureVideoManifestV3]:
    try:
        return [
            await _upload_and_generate_manifest_chunk(
                video_path=video_path,
                gemini_client=gemini_client,
                generation_prompt_content=generation_prompt_content,
                transcript=transcript,
                video_duration_ms=video_duration_ms,
                chunk=chunk,
                temp_dir=temp_dir,
                model=model,
            )
        ]
    except Exception as exc:
        if (
            not _should_split_manifest_chunk_error(exc)
            or chunk.generation_duration_ms <= _MANIFEST_CHUNK_MIN_SPLIT_MS
        ):
            raise
        child_chunks = _split_manifest_generation_chunk(
            chunk,
            video_duration_ms=video_duration_ms,
        )
        logger.info(
            "Splitting lecture video manifest chunk after provider limit. "
            "generation_start_ms=%s generation_end_ms=%s split_ms=%s",
            chunk.generation_start_ms,
            chunk.generation_end_ms,
            child_chunks[0].generation_end_ms,
        )
        chunk_manifests: list[schemas.LectureVideoManifestV3] = []
        for child_chunk in child_chunks:
            chunk_manifests.extend(
                await _upload_and_generate_manifest_chunks(
                    video_path=video_path,
                    gemini_client=gemini_client,
                    generation_prompt_content=generation_prompt_content,
                    transcript=transcript,
                    video_duration_ms=video_duration_ms,
                    chunk=child_chunk,
                    temp_dir=temp_dir,
                    model=model,
                )
            )
        return chunk_manifests


async def upload_and_generate_manifest(
    *,
    video_path: str,
    gemini_client: AsyncClient,
    generation_prompt_content: str,
    transcript: list[schemas.LectureVideoManifestWordV3],
    temp_dir: str,
    model: str = _GEMINI_MODEL,
) -> schemas.LectureVideoManifestV3:
    video_duration_ms = await _ffprobe_duration_ms(video_path)
    if video_duration_ms is None:
        raise RuntimeError(
            "Unable to determine lecture video duration with ffprobe; "
            "manifest generation requires a valid video duration."
        )
    chunks = _plan_manifest_generation_chunks(video_duration_ms)
    if len(chunks) == 1:
        try:
            return await _upload_and_generate_whole_manifest(
                video_path=video_path,
                gemini_client=gemini_client,
                generation_prompt_content=generation_prompt_content,
                transcript=transcript,
                video_duration_ms=video_duration_ms,
                model=model,
            )
        except Exception as exc:
            if (
                video_duration_ms is None
                or not _should_split_manifest_chunk_error(exc)
                or chunks[0].generation_duration_ms <= _MANIFEST_CHUNK_MIN_SPLIT_MS
            ):
                raise
            chunks = _split_manifest_generation_chunk(
                chunks[0],
                video_duration_ms=video_duration_ms,
            )

    logger.info(
        "Generating lecture video manifest in chunks. video_duration_ms=%s "
        "chunk_count=%s",
        video_duration_ms,
        len(chunks),
    )
    chunk_manifests: list[schemas.LectureVideoManifestV3] = []
    for chunk in chunks:
        chunk_manifests.extend(
            await _upload_and_generate_manifest_chunks(
                video_path=video_path,
                gemini_client=gemini_client,
                generation_prompt_content=generation_prompt_content,
                transcript=transcript,
                video_duration_ms=video_duration_ms or chunk.generation_end_ms,
                chunk=chunk,
                temp_dir=temp_dir,
                model=model,
            )
        )
    return await _merge_chunk_manifests(
        gemini_client=gemini_client,
        generation_prompt_content=generation_prompt_content,
        model=model,
        chunk_manifests=chunk_manifests,
        full_transcript=transcript,
        video_duration_ms=video_duration_ms,
    )


def video_suffix_for_content_type(content_type: str | None) -> str:
    if content_type == "video/webm":
        return ".webm"
    suffix = Path(str(content_type or "")).suffix
    return suffix or ".mp4"
