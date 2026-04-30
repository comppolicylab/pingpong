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


DEFAULT_LECTURE_VIDEO_INSTRUCTIONS = """You are a friendly, clear tutor helping a learner during an interactive video lesson in a chat interface. You are speaking in the voice of the person in the video, so use pronouns "I/me".
While the user can only type text, your responses will be **spoken aloud**, so they must sound natural, simple, and easy to follow.
---
### Context Provided
Each turn, the learner's question is preceded by a hidden developer message titled **"## Lecture Context"**. Carefully read the entire message before answering, as it presents the latest state and history of the learning session.
The structure within the "Lecture context" matches this format:
-----BEGIN LECTURE CONTEXT-----
## Lecture Context
- **Status:** Indicates the learner’s present activity. One of:
    - *Watching the lecture video*
    - *Answering Knowledge Check #{n}*
    - *Just answered Knowledge Check #{n}*
    - *Finished watching the lecture video*
- **Current offset:** How far into the video the learner is, in milliseconds.
### What the learner has encountered so far
A natural-language summary of the concepts, explanations, and main points already introduced in the lesson.
### Current lecture moment
- **Before this moment:** What the lecture and visuals covered just prior to the current point.
- **At this moment:** What is occurring in the video at the present offset—focus carefully on this segment when answering.
- **After this moment:** What will occur next—but you must avoid using or revealing this information unless acknowledging that it is coming (without explaining its substance).
### Current Knowledge Check
If the learner is currently working on a Knowledge Check, this section lists:
- The question text.
- Each option, marked as (correct), (incorrect), or (unknown).
- Feedback displayed after each choice.
### Upcoming Knowledge Check
If a Knowledge Check is approaching, this section provides:
- When it will occur (offset).
- The exact question and its options (with correct/incorrect/unknown labels and feedback), but **do not use, reveal, or discuss the content or answer until the student has seen it.**
  You may reference generally that a related question is coming.
### Knowledge Checks Answered
Chronological list of previous Knowledge Check interactions, each showing:
- When it occurred, which question was asked, and what option the student selected.
- How each option was marked and what feedback was given.
- Use this to reinforce prior correct answers or gently revisit mistakes.
-----END LECTURE CONTEXT-----
The learner's own question immediately follows this developer message.
---
### Instructions
**Critical Content Control Rule**
- **Never provide information, details, explanations, or content that have not yet appeared in the 'What the learner has encountered so far', 'Before this moment', 'At this moment', 'Current Knowledge Check', or past 'Knowledge Checks Answered'.**
    - Do not reveal or elaborate on any material shown in 'After this moment' or 'Upcoming Knowledge Check' before those moments or questions actually occur.
    - You may briefly state that future concepts are coming (e.g., "We'll cover that in a moment"), but do not provide their substance ahead of time.
    - This applies to all responses, including direct student questions, requests for summaries, or answers to knowledge check content.
- *Always draw only on content from the present and past portions of the context; anticipate but do not preempt upcoming information.*
- If the available present-and-past context is sparse or insufficient, **do not fill gaps by drawing from 'After this moment' or 'Upcoming Knowledge Check'.** Instead, say only what is supported by the available material and, if needed, briefly encourage the learner to continue.
**1. Be clear and easy to follow**
* Use plain language matched to the lecture level.
* Avoid jargon, or define it briefly when first used.
**2. Keep it short and focused**
* Give a direct, concise answer—usually one or two main ideas.
**3. Make it sound natural when spoken**
* Write in a conversational, instructor’s tone.
* When describing equations or notation, use words as in speech ("x squared," "one over two").
* Prefer shorter sentences and familiar phrasing.
**4. Use the lecture context when helpful**
* Ground your answer in what the lecturer just said ('At this moment') and what the learner has already encountered.
  For example: "In the step I just showed you…"
* Do **not** refer to offsets, section names, or developer message labels—translate these into natural narrative timing ("just now," "a moment ago," etc.).
**5. If asked for a summary or 'what has happened so far':**
* Only summarize content from 'What the learner has encountered so far', 'Before this moment', and 'At this moment'.
* If there is little or no content yet, say so and encourage the learner to continue.
* **Never use or mention material from 'After this moment' or 'Upcoming Knowledge Check' in summaries of "so far".**
**6. Respect the Knowledge Check flow**
* If a Knowledge Check is about to occur, mention only that a question is upcoming—do not hint or state its content or answers.
* If the learner is answering a Knowledge Check, DO NOT give them the answer, hint, suggestion, clue, or nudge—even if the learner expresses uncertainty, says they don't get it, asks for help, hesitates, requests hints, or tries to get a clue.
* In that situation, you may only do two things: (1) briefly restate useful information that has already been presented earlier in the lesson or current context, and/or (2) encourage the learner to try their best using only what has been presented so far.
* Do not suggest which option to choose, do not narrow the possibilities, and do not explain why any option is right or wrong before the learner submits an answer.
* While the learner is still in a Knowledge Check, do **not** provide explanations that would justify or effectively reveal the right answer, even indirectly.
* If there is very little prior lesson content available to restate, keep the response minimal and encouraging rather than adding new explanation.
* After a Knowledge Check has been answered, build on the shown feedback—reinforce correct answers, revisit mistakes, as shown in 'Knowledge Checks Answered'.
* Never give answers to Knowledge Checks before the learner has attempted them.
**7. Prioritise helping over completeness**
* Give the simplest explanation that supports the learner’s progress.
* Don’t launch into long derivations or depth unless asked.
**8. If the question is unclear or off-track**
* Gently redirect, or ask a single clarifying question.
* Avoid making wild guesses.
**9. Default to direct answers**
* Only ask questions if absolutely necessary for clarity.
**10. Keep the tone of a friendly teacher**
* Always sound supportive, approachable, and encouraging.
* Avoid extremes—never overly formal or overly excited.
---
### Output
Respond with **only the answer**, as if speaking to the learner directly—clear, concise, and natural for audio delivery.
# Output Format
Respond with a short, conversational spoken explanation. Avoid jargon unless defined. Do not repeat the question or instructions, and do not reference the context structure—speak only to the learner, in character.
# Notes
- Under no circumstances should you provide or explain information from 'After this moment' or 'Upcoming Knowledge Check' until it has actually become part of the "What the learner has encountered so far" or appeared in a past Knowledge Check.
- When summarizing "so far," reference only what has been encountered, not what is still to come.
- If there is insufficient past content, say so, and encourage watching further.
- Make all explanations accessible at the learner’s level and easy to follow when spoken.
- Do not refer to developer message labels, technical structure, or video offsets in your reply.
- **If the learner is in a Knowledge Check and seems uncertain—such as expressing doubt, saying they don't get it, hesitating, asking for hints, or otherwise seeking help—DO NOT provide the answer, clue, hint, suggestion, or any explanation of why an option is correct or incorrect. Instead, only restate helpful information already covered and gently encourage them to do their best based only on what has been covered so far. Never give anything away until they have submitted their answer.**
- **If there is very little prior covered material available during a Knowledge Check, do not compensate by using forthcoming content. In that case, keep the response brief, supportive, and limited to what has already been shown.**
---
**Remember: Always base your answer strictly on what has already happened in the lesson, as detailed above, and deliver your reply in a friendly, natural-sounding way suited for spoken delivery.**"""

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
DEFAULT_VIDEO_DESCRIPTION_DURATION_MS = 30_000
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


class GeneratedSummaryCheckpoint(BaseModel):
    model_config = ConfigDict(extra="forbid")

    end_offset_ms: int = Field(
        ge=0, description="Checkpoint end offset in milliseconds."
    )
    summary: str = Field(
        description=(
            "Cumulative summary through end_offset_ms, extending any supplied "
            "prior cumulative summary."
        )
    )


class GeneratedMomentContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    center_offset_ms: int = Field(
        ge=0, description="The center offset for this local context."
    )
    start_offset_ms: int = Field(
        ge=0, description="The start offset of the local context window."
    )
    end_offset_ms: int = Field(
        ge=0, description="The end offset of the local context window."
    )
    before: str = Field(description="What immediately leads into this moment.")
    at: str = Field(description="What is happening at the center moment.")
    after: str = Field(description="What immediately follows this moment.")


class GeneratedQuizWithVideoContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    video_summary: str = Field(description="Brief summary of the lesson.")
    questions: list[GeneratedQuestion] = Field(
        min_length=1,
        description="Generated comprehension checks.",
    )
    summary_checkpoints: list[GeneratedSummaryCheckpoint] = Field(
        default_factory=list,
        description=(
            "Cumulative summaries from the relevant generation scope start "
            "through increasing checkpoint offsets."
        ),
    )
    moment_contexts: list[GeneratedMomentContext] = Field(
        default_factory=list,
        description="Local context windows centered on increasing offsets.",
    )


class ReconciledGeneratedQuiz(BaseModel):
    model_config = ConfigDict(extra="forbid")

    questions: list[GeneratedQuestion] = Field(
        min_length=1,
        description="Final reconciled comprehension checks for the full video.",
    )


def _timestamp_to_ms(value: float | int) -> int:
    return int(round(float(value) * 1000))


def _manifest_chunk_overlap_ms(video_description_window_ms: int) -> int:
    return max(_MANIFEST_CHUNK_OVERLAP_MS, video_description_window_ms // 2)


def _resolve_context_schedule_bounds(
    *,
    video_duration_ms: int | None,
    generation_start_ms: int | None,
    generation_end_ms: int | None,
    video_description_window_ms: int,
) -> tuple[int, int] | None:
    if video_description_window_ms <= 0:
        return None
    effective_end_ms = (
        generation_end_ms if generation_end_ms is not None else video_duration_ms
    )
    if effective_end_ms is None:
        return None
    effective_start_ms = max(generation_start_ms or 0, 0)
    effective_end_ms = max(effective_end_ms, 0)
    return effective_start_ms, effective_end_ms


def _scheduled_summary_checkpoint_offsets(
    *,
    video_duration_ms: int | None,
    generation_start_ms: int | None,
    generation_end_ms: int | None,
    video_description_window_ms: int,
) -> list[int]:
    bounds = _resolve_context_schedule_bounds(
        video_duration_ms=video_duration_ms,
        generation_start_ms=generation_start_ms,
        generation_end_ms=generation_end_ms,
        video_description_window_ms=video_description_window_ms,
    )
    if bounds is None:
        return []
    effective_start_ms, effective_end_ms = bounds
    if effective_end_ms <= effective_start_ms:
        return []
    first_offset_ms = (
        (effective_start_ms // video_description_window_ms) + 1
    ) * video_description_window_ms
    offsets = list(
        range(first_offset_ms, effective_end_ms + 1, video_description_window_ms)
    )
    if not offsets or offsets[-1] != effective_end_ms:
        offsets.append(effective_end_ms)
    return offsets


def _scheduled_moment_context_windows(
    *,
    video_duration_ms: int | None,
    generation_start_ms: int | None,
    generation_end_ms: int | None,
    video_description_window_ms: int,
) -> list[tuple[int, int, int]]:
    bounds = _resolve_context_schedule_bounds(
        video_duration_ms=video_duration_ms,
        generation_start_ms=generation_start_ms,
        generation_end_ms=generation_end_ms,
        video_description_window_ms=video_description_window_ms,
    )
    if bounds is None:
        return []
    effective_start_ms, effective_end_ms = bounds
    if effective_end_ms < effective_start_ms:
        return []
    if effective_start_ms == 0:
        first_center_ms = 0
    else:
        first_center_ms = (
            (effective_start_ms + video_description_window_ms - 1)
            // video_description_window_ms
        ) * video_description_window_ms
    if first_center_ms > effective_end_ms:
        return []
    half_window_ms = video_description_window_ms // 2
    duration_cap_ms = (
        video_duration_ms if video_duration_ms is not None else effective_end_ms
    )
    windows: list[tuple[int, int, int]] = []
    for center_offset_ms in range(
        first_center_ms, effective_end_ms + 1, video_description_window_ms
    ):
        start_offset_ms = max(0, center_offset_ms - half_window_ms)
        end_offset_ms = min(duration_cap_ms, center_offset_ms + half_window_ms)
        windows.append((center_offset_ms, start_offset_ms, end_offset_ms))
    if windows and windows[-1][0] != effective_end_ms:
        start_offset_ms = max(0, effective_end_ms - half_window_ms)
        windows.append((effective_end_ms, start_offset_ms, effective_end_ms))
    return windows


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
    alignment_ms: int = DEFAULT_VIDEO_DESCRIPTION_DURATION_MS,
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
    alignment_ms: int = DEFAULT_VIDEO_DESCRIPTION_DURATION_MS,
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

    chunk_duration_ms = _align_offset_down(max_chunk_duration_ms, alignment_ms)
    if chunk_duration_ms <= 0:
        chunk_duration_ms = max_chunk_duration_ms
    boundaries = list(range(0, video_duration_ms, chunk_duration_ms))
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
    alignment_ms: int = DEFAULT_VIDEO_DESCRIPTION_DURATION_MS,
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
    video_description_window_ms: int = DEFAULT_VIDEO_DESCRIPTION_DURATION_MS,
    previous_summary_checkpoint: schemas.LectureVideoManifestSummaryCheckpointV4
    | None = None,
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

    video_description_window_seconds = video_description_window_ms / 1000
    video_description_next_window_ms = video_description_window_ms * 2
    video_description_half_window_ms = video_description_window_ms // 2
    video_description_half_window_seconds = video_description_half_window_ms / 1000
    video_description_window_text = f"{video_description_window_seconds:g}"
    video_description_window_unit_text = f"{video_description_window_text}-second"
    video_description_half_window_text = f"{video_description_half_window_seconds:g}"
    context_array_summary_scope = "0ms through each end_offset_ms"
    summary_schedule_guidance = (
        f"- Generate summary checkpoints exactly every {video_description_window_text} "
        "seconds from the start of the video, plus the final video end if it is "
        "not already on that cadence, using absolute millisecond offsets."
    )
    moment_schedule_guidance = (
        f"- Generate moment contexts centered exactly every {video_description_window_text} "
        "seconds from the start of the video, plus a final context centered on "
        "the final video/request end if it is not already on that cadence, using "
        "absolute millisecond offsets."
    )
    initial_moment_guidance = (
        "- Always include an initial moment_context with start_offset_ms=0, "
        "center_offset_ms=0, and end_offset_ms="
        f"{video_description_half_window_ms}."
    )
    duration_text = (
        f"\nThe video duration is {video_duration_ms} milliseconds."
        if video_duration_ms is not None
        else ""
    )
    generation_window_text = ""
    previous_summary_text = ""
    context_array_scope = "the whole video"
    chunk_moment_boundary_guidance = ""
    summary_cumulative_guidance = (
        f"- Each summary must be cumulative over {context_array_summary_scope}."
    )
    context_offset_guidance = (
        "- Use absolute millisecond offsets from the original video for every "
        "summary end_offset_ms and every moment center_offset_ms, start_offset_ms, "
        "and end_offset_ms."
    )
    context_array_reminder = (
        'The top-level "summary_checkpoints" and "moment_contexts" arrays are '
        "REQUIRED for video-based generation. They must be non-empty and use "
        "absolute millisecond offsets from the original video."
    )
    if generation_start_ms is not None and generation_end_ms is not None:
        context_array_scope = "the requested generation window"
        context_array_summary_scope = (
            f"{generation_start_ms}ms through each end_offset_ms"
        )
        summary_cumulative_guidance = (
            "- Each summary must be cumulative from the requested generation start "
            "through end_offset_ms; do not claim to summarize unseen earlier video "
            "content."
        )
        summary_schedule_guidance = (
            f"- Generate summary checkpoints at the fixed {video_description_window_unit_text} "
            "cadence inside the requested generation window, plus the "
            "request end if it is not already on that cadence, using absolute "
            "millisecond offsets from the original video. The first checkpoint is "
            f"the first cadence offset greater than {generation_start_ms}ms; do "
            "not force a checkpoint at 0ms for a chunk that starts later."
        )
        moment_schedule_guidance = (
            f"- Generate moment contexts centered at the fixed {video_description_window_unit_text} "
            "cadence inside the requested generation window, plus a final "
            "context centered on the request end if it is not already on that "
            "cadence, using absolute millisecond offsets from the original video."
        )
        initial_moment_guidance = (
            "- If the requested generation window starts at 0ms, include the "
            "initial moment_context with start_offset_ms=0, center_offset_ms=0, "
            f"and end_offset_ms={video_description_half_window_ms}. If the "
            "requested generation window starts later, do not include a 0ms "
            "moment_context; start with the first fixed-cadence center inside "
            "the requested generation window."
        )
        if generation_start_ms == 0:
            first_moment_center_ms = 0
        else:
            first_moment_center_ms = (
                (generation_start_ms + video_description_window_ms - 1)
                // video_description_window_ms
            ) * video_description_window_ms
        chunk_moment_boundary_guidance = (
            "- For moment_contexts near the requested generation window boundaries, "
            'use the surrounding clip context when writing "before" and "after". '
            "The local context window may extend outside the generation window, "
            "but center_offset_ms must stay inside the generation window.\n"
            f"- The first required moment_context center is {first_moment_center_ms}ms. "
            "Include it even when it equals generation_start_ms; boundary centers "
            "are required, not optional."
        )
        context_offset_guidance = (
            "- Use absolute millisecond offsets from the original video for every "
            "summary end_offset_ms and every moment center_offset_ms, start_offset_ms, "
            "and end_offset_ms. The provided media is a clipped excerpt, so do "
            "not emit excerpt-relative offsets."
        )
        context_array_reminder = (
            'The top-level "summary_checkpoints" and "moment_contexts" arrays '
            "are REQUIRED for video-based generation. They must be non-empty, "
            "must use absolute offsets from the original video, and should only "
            "cover the requested generation window."
        )
        if previous_summary_checkpoint is not None:
            context_array_summary_scope = (
                "the full lecture so far at each end_offset_ms"
            )
            previous_summary_text = (
                "\nPRIOR CUMULATIVE SUMMARY:\n"
                "The previous generated chunk summarized the lecture through "
                f"{previous_summary_checkpoint.end_offset_ms}ms:\n"
                f"{previous_summary_checkpoint.summary}\n\n"
                "Use this as the only source for lecture content before "
                f"{generation_start_ms}ms. Do not invent or infer earlier content "
                "beyond this prior summary.\n"
            )
            summary_cumulative_guidance = (
                "- Each summary must be cumulative for the full lecture so far: "
                "start from the supplied prior cumulative summary, then add only "
                "content supported by this chunk's transcript/video through "
                "end_offset_ms."
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
Generate "summary_checkpoints" and "moment_contexts" for offsets inside {generation_start_ms}ms through {generation_end_ms}ms.
"""

    return f"""You are an expert educational content designer specializing in interactive video lessons. You speak as the teacher in first person, directly to the student.

You will be given a lecture video and a word-level transcript. {transcript_description}{duration_text}
{generation_window_text}
{previous_summary_text}

Here's the WORD-LEVEL TRANSCRIPT:
{transcript_text}

TO-DO's FOR SUCCESSFUL QUIZ-GENERATION:
To ensure high confidence in analyzing the lesson, watch the video along with the transcript. Don't make up anything or assume based on your preconceived idea of the lecture - always remember you have the transcript.

YOUR TASK:
Analyze the provided lesson materials to identify natural pause points where a multiple-choice comprehension check can be inserted. At each pause point, the video will stop, a question will be displayed as text on screen, and a voice clone of the teacher will introduce the question out loud. After the student selects an answer, the voice clone will give spoken feedback, and the video will resume. The resume point may differ depending on which answer the student chose.

Also create two top-level context arrays across {context_array_scope}:
- "summary_checkpoints": cumulative summaries over {context_array_summary_scope}, ordered by increasing end_offset_ms.
- "moment_contexts": local context windows centered on increasing center_offset_ms values, with separate "before", "at", and "after" fields.

CONTEXT ARRAY GROUNDING:
- Use a {video_description_window_unit_text} context cadence ({video_description_window_ms}ms): summary checkpoints and moment_context centers follow this cadence.
{context_offset_guidance}
- Do not choose semantically interesting offsets instead of the fixed cadence.
- Use the provided transcript and visible video content as the source of truth. You may combine spoken content with observable teaching state, but make conceptual claims only when they are supported by the transcript, visible text, or clearly visible teaching action.

SUMMARY CHECKPOINT GUIDELINES:
{summary_schedule_guidance}
- Do not skip the first required checkpoint for this generation scope.
{summary_cumulative_guidance}

MOMENT CONTEXT GUIDELINES:
{moment_schedule_guidance}
- Moment context windows must extend half the context cadence on each side of the center: start_offset_ms = center_offset_ms - {video_description_half_window_text} seconds, end_offset_ms = center_offset_ms + {video_description_half_window_text} seconds, clamped to 0ms and the video duration.
- For example, with a 5-second context cadence, center_offset_ms=10000 must use start_offset_ms=7500 and end_offset_ms=12500.
{initial_moment_guidance}
{chunk_moment_boundary_guidance}
- For every moment_context, enforce start_offset_ms <= center_offset_ms <= end_offset_ms.
- "before" should explain what immediately leads into the center moment.
- "at" should explain what is happening at the center moment.
- "after" should explain what immediately follows the center moment.
- Context text should combine spoken content and observable teaching state where useful: screen or board contents, written text, diagrams, values, equations, cursor movement, gesture emphasis, and meaningful visual changes.

IMPORTANT CONTEXT:
- The voice-over feedback is spoken by a clone of the teacher's voice. It must sound like the teacher is speaking directly to the student in first person — not a separate narrator or tutor commenting from the outside.
- The feedback voice-over is spliced into the lecture audio. When the video resumes, the teacher's voice continues seamlessly. Your feedback must flow naturally into whatever the teacher says at the determined resume point — as if it were all one continuous spoken experience.

GENERATION GUIDANCE SPECIFIC TO THIS VIDEO:
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
  "summary_checkpoints": [
    {{
      "end_offset_ms": {video_description_window_ms},
      "summary": "From the start through this point, the teacher introduces the main idea and works through the first example."
    }},
    {{
      "end_offset_ms": {video_description_next_window_ms},
      "summary": "From the start through this point, the teacher introduces the main idea, works through the first example, and connects it to the next step."
    }}
  ],
  "moment_contexts": [
    {{
      "center_offset_ms": 0,
      "start_offset_ms": 0,
      "end_offset_ms": {video_description_half_window_ms},
      "before": "The lesson is just beginning.",
      "at": "The teacher introduces the topic and the first visible teaching materials.",
      "after": "The teacher begins the first example."
    }},
    {{
      "center_offset_ms": {video_description_window_ms},
      "start_offset_ms": {video_description_half_window_ms},
      "end_offset_ms": {video_description_window_ms + video_description_half_window_ms},
      "before": "The teacher has introduced the main idea.",
      "at": "The teacher is working through the next step of the example.",
      "after": "The teacher connects the example back to the main concept."
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
- "summary_checkpoints": Array of cumulative summaries. Each entry contains:
  - "end_offset_ms": Integer millisecond offset through which this summary applies.
  - "summary": Non-empty cumulative summary through end_offset_ms, extending any supplied prior cumulative summary.
- "moment_contexts": Array of local context windows. Each entry contains:
  - "center_offset_ms": Integer millisecond offset used to select this local context.
  - "start_offset_ms": Integer millisecond offset where the local window starts.
  - "end_offset_ms": Integer millisecond offset where the local window ends.
  - "before": Non-empty local context before center_offset_ms.
  - "at": Non-empty local context at center_offset_ms.
  - "after": Non-empty local context after center_offset_ms.

IMPORTANT REMINDERS:
- ALL word IDs and timestamps must come directly from the transcript entries. Look up each word's actual "id" field — do not count or guess. Copy "word", "start", and "end" exactly.
- For teacher-posed questions: let them ask it, pause after the question, and resume into the teacher's own answer — do NOT skip past it.
- For "generated" questions, voice_over_intro MUST include both a pause cue and the question spoken aloud. The student needs to hear it, not just read it.
- {context_array_reminder}

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


def _fallback_summary_checkpoints(
    video_duration_ms: int | None,
) -> list[schemas.LectureVideoManifestSummaryCheckpointV4]:
    return [
        schemas.LectureVideoManifestSummaryCheckpointV4(
            end_offset_ms=max(video_duration_ms or 0, 0),
            summary="A cumulative lecture summary was unavailable for this generation pass.",
        )
    ]


def _fallback_moment_contexts(
    video_duration_ms: int | None = None,
) -> list[schemas.LectureVideoManifestMomentContextV4]:
    end_offset_ms = max(video_duration_ms or 0, 0)
    return [
        schemas.LectureVideoManifestMomentContextV4(
            center_offset_ms=0,
            start_offset_ms=0,
            end_offset_ms=end_offset_ms,
            before="No earlier local lecture context is available.",
            at="Local lecture context was unavailable for this generation pass.",
            after="No later local lecture context is available.",
        )
    ]


def _generated_summary_checkpoints_to_manifest(
    checkpoints: list[GeneratedSummaryCheckpoint],
) -> list[schemas.LectureVideoManifestSummaryCheckpointV4]:
    return [
        schemas.LectureVideoManifestSummaryCheckpointV4.model_validate(
            checkpoint.model_dump()
        )
        for checkpoint in checkpoints
    ]


def _generated_moment_contexts_to_manifest(
    moments: list[GeneratedMomentContext],
) -> list[schemas.LectureVideoManifestMomentContextV4]:
    return [
        schemas.LectureVideoManifestMomentContextV4.model_validate(moment.model_dump())
        for moment in moments
    ]


def _normalize_v4_context_arrays(
    *,
    summary_checkpoints: list[schemas.LectureVideoManifestSummaryCheckpointV4],
    moment_contexts: list[schemas.LectureVideoManifestMomentContextV4],
    video_duration_ms: int | None,
    generation_start_ms: int | None = None,
    generation_end_ms: int | None = None,
    video_description_window_ms: int = DEFAULT_VIDEO_DESCRIPTION_DURATION_MS,
) -> tuple[
    list[schemas.LectureVideoManifestSummaryCheckpointV4],
    list[schemas.LectureVideoManifestMomentContextV4],
]:
    summary_checkpoint_by_offset = {
        checkpoint.end_offset_ms: checkpoint for checkpoint in summary_checkpoints
    }
    required_summary_offsets = _scheduled_summary_checkpoint_offsets(
        video_duration_ms=video_duration_ms,
        generation_start_ms=generation_start_ms,
        generation_end_ms=generation_end_ms,
        video_description_window_ms=video_description_window_ms,
    )
    if required_summary_offsets:
        summary_checkpoints = []
        for end_offset_ms in required_summary_offsets:
            checkpoint = summary_checkpoint_by_offset.get(end_offset_ms)
            if checkpoint is not None:
                summary_checkpoints.append(checkpoint)
                continue
            logger.warning(
                "Generated summary_checkpoints missing required offset %sms; "
                "falling back to unavailable summary for that checkpoint.",
                end_offset_ms,
            )
            summary_checkpoints.append(
                schemas.LectureVideoManifestSummaryCheckpointV4(
                    end_offset_ms=end_offset_ms,
                    summary=(
                        "A cumulative lecture summary was unavailable for this "
                        "checkpoint."
                    ),
                )
            )
    else:
        summary_checkpoints = sorted(
            summary_checkpoint_by_offset.values(),
            key=lambda item: item.end_offset_ms,
        )

    moment_context_by_center = {
        moment.center_offset_ms: moment for moment in moment_contexts
    }
    required_moment_windows = _scheduled_moment_context_windows(
        video_duration_ms=video_duration_ms,
        generation_start_ms=generation_start_ms,
        generation_end_ms=generation_end_ms,
        video_description_window_ms=video_description_window_ms,
    )
    if required_moment_windows:
        moment_contexts = []
        for center_offset_ms, start_offset_ms, end_offset_ms in required_moment_windows:
            moment = moment_context_by_center.get(center_offset_ms)
            if moment is None:
                logger.warning(
                    "Generated moment_contexts missing required center %sms; "
                    "falling back to unavailable local context for that moment.",
                    center_offset_ms,
                )
                moment_contexts.append(
                    schemas.LectureVideoManifestMomentContextV4(
                        center_offset_ms=center_offset_ms,
                        start_offset_ms=start_offset_ms,
                        end_offset_ms=end_offset_ms,
                        before="No earlier local lecture context is available.",
                        at=("Local lecture context was unavailable for this moment."),
                        after="No later local lecture context is available.",
                    )
                )
                continue
            moment_contexts.append(
                schemas.LectureVideoManifestMomentContextV4(
                    center_offset_ms=center_offset_ms,
                    start_offset_ms=start_offset_ms,
                    end_offset_ms=end_offset_ms,
                    before=moment.before,
                    at=moment.at,
                    after=moment.after,
                )
            )
    else:
        moment_contexts = sorted(
            moment_context_by_center.values(),
            key=lambda item: item.center_offset_ms,
        )
    if not summary_checkpoints:
        logger.warning(
            "Generated summary_checkpoints was empty; falling back to unavailable summary."
        )
        summary_checkpoints = _fallback_summary_checkpoints(video_duration_ms)
    if not moment_contexts:
        logger.warning(
            "Generated moment_contexts was empty; falling back to unavailable moment context."
        )
        moment_contexts = _fallback_moment_contexts(video_duration_ms)
    return summary_checkpoints, moment_contexts


def _quiz_to_manifest(
    quiz: GeneratedQuizWithVideoContext,
    transcript: list[schemas.LectureVideoManifestWordV3],
    *,
    video_duration_ms: int | None,
    video_description_start_offset_ms: int = 0,
    video_description_end_offset_ms: int | None = None,
    video_description_window_ms: int = DEFAULT_VIDEO_DESCRIPTION_DURATION_MS,
) -> schemas.LectureVideoManifestV4:
    transcript_word_index = _transcript_word_index(transcript)
    summary_checkpoints, moment_contexts = _normalize_v4_context_arrays(
        summary_checkpoints=_generated_summary_checkpoints_to_manifest(
            quiz.summary_checkpoints
        ),
        moment_contexts=_generated_moment_contexts_to_manifest(quiz.moment_contexts),
        video_duration_ms=video_duration_ms or video_description_end_offset_ms,
        generation_start_ms=video_description_start_offset_ms,
        generation_end_ms=video_description_end_offset_ms,
        video_description_window_ms=video_description_window_ms,
    )
    return schemas.LectureVideoManifestV4(
        word_level_transcription=transcript,
        summary_checkpoints=summary_checkpoints,
        moment_contexts=moment_contexts,
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


def _latest_summary_checkpoint(
    manifests: list[schemas.LectureVideoManifestV4],
    fallback: schemas.LectureVideoManifestSummaryCheckpointV4 | None = None,
) -> schemas.LectureVideoManifestSummaryCheckpointV4 | None:
    checkpoints = [
        checkpoint
        for manifest in manifests
        for checkpoint in manifest.summary_checkpoints
    ]
    if not checkpoints:
        return fallback
    return max(checkpoints, key=lambda checkpoint: checkpoint.end_offset_ms)


def _reconciliation_prompt(generation_prompt_content: str) -> str:
    return f"""You are an expert educational content designer reconciling independently generated interactive question candidates from chunks of one lecture video.

You will be given:
- The instructor's generation guidance.
- The full word-level transcript for the complete video.
- The final merged summary_checkpoints and moment_contexts for the complete video.
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
    summary_checkpoints: list[schemas.LectureVideoManifestSummaryCheckpointV4],
    moment_contexts: list[schemas.LectureVideoManifestMomentContextV4],
    chunk_manifests: list[schemas.LectureVideoManifestV4],
    video_duration_ms: int | None,
) -> str:
    payload = {
        "video_duration_ms": video_duration_ms,
        "word_level_transcript": [
            _word_to_generation_word(word, index)
            for index, word in enumerate(transcript)
        ],
        "summary_checkpoints": [
            checkpoint.model_dump() for checkpoint in summary_checkpoints
        ],
        "moment_contexts": [moment.model_dump() for moment in moment_contexts],
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
    summary_checkpoints: list[schemas.LectureVideoManifestSummaryCheckpointV4],
    moment_contexts: list[schemas.LectureVideoManifestMomentContextV4],
    chunk_manifests: list[schemas.LectureVideoManifestV4],
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
                    summary_checkpoints=summary_checkpoints,
                    moment_contexts=moment_contexts,
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
    chunk_manifests: list[schemas.LectureVideoManifestV4],
    full_transcript: list[schemas.LectureVideoManifestWordV3],
    video_duration_ms: int | None,
    video_description_window_ms: int = DEFAULT_VIDEO_DESCRIPTION_DURATION_MS,
) -> schemas.LectureVideoManifestV4:
    summary_checkpoints, moment_contexts = _normalize_v4_context_arrays(
        summary_checkpoints=[
            checkpoint
            for manifest in chunk_manifests
            for checkpoint in manifest.summary_checkpoints
        ],
        moment_contexts=[
            moment
            for manifest in chunk_manifests
            for moment in manifest.moment_contexts
        ],
        video_duration_ms=video_duration_ms,
        video_description_window_ms=video_description_window_ms,
    )
    questions = await _reconcile_chunk_questions(
        gemini_client=gemini_client,
        generation_prompt_content=generation_prompt_content,
        transcript=full_transcript,
        summary_checkpoints=summary_checkpoints,
        moment_contexts=moment_contexts,
        chunk_manifests=chunk_manifests,
        video_duration_ms=video_duration_ms,
        model=model,
    )
    return schemas.LectureVideoManifestV4(
        word_level_transcription=full_transcript,
        summary_checkpoints=summary_checkpoints,
        moment_contexts=moment_contexts,
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
    video_description_window_ms: int = DEFAULT_VIDEO_DESCRIPTION_DURATION_MS,
    previous_summary_checkpoint: schemas.LectureVideoManifestSummaryCheckpointV4
    | None = None,
) -> schemas.LectureVideoManifestV4:
    prompt = build_generation_prompt(
        generation_prompt_content,
        transcript,
        compact=compact,
        video_duration_ms=video_duration_ms,
        generation_start_ms=generation_start_ms,
        generation_end_ms=generation_end_ms,
        context_start_ms=context_start_ms,
        context_end_ms=context_end_ms,
        video_description_window_ms=video_description_window_ms,
        previous_summary_checkpoint=previous_summary_checkpoint,
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
        response_model=GeneratedQuizWithVideoContext,
        request_label=request_label,
    )
    return _quiz_to_manifest(
        quiz,
        transcript,
        video_duration_ms=video_duration_ms,
        video_description_start_offset_ms=generation_start_ms or 0,
        video_description_end_offset_ms=generation_end_ms,
        video_description_window_ms=video_description_window_ms,
    )


async def generate_manifest(
    *,
    video_path: str,
    gemini_client: AsyncClient,
    gemini_file: GeminiFileRef,
    generation_prompt_content: str,
    transcript: list[schemas.LectureVideoManifestWordV3],
    model: str = _GEMINI_MODEL,
    video_description_duration_ms: int = DEFAULT_VIDEO_DESCRIPTION_DURATION_MS,
) -> schemas.LectureVideoManifestV4:
    video_duration_ms = await _ffprobe_duration_ms(video_path)
    video_description_window_ms = video_description_duration_ms
    try:
        return await _generate_manifest_from_gemini_file(
            gemini_client=gemini_client,
            gemini_file=gemini_file,
            generation_prompt_content=generation_prompt_content,
            transcript=transcript,
            video_duration_ms=video_duration_ms,
            model=model,
            video_description_window_ms=video_description_window_ms,
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
            video_description_window_ms=video_description_window_ms,
        )


async def _upload_and_generate_whole_manifest(
    *,
    video_path: str,
    gemini_client: AsyncClient,
    generation_prompt_content: str,
    transcript: list[schemas.LectureVideoManifestWordV3],
    video_duration_ms: int | None,
    model: str,
    video_description_window_ms: int = DEFAULT_VIDEO_DESCRIPTION_DURATION_MS,
) -> schemas.LectureVideoManifestV4:
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
                video_description_window_ms=video_description_window_ms,
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
                video_description_window_ms=video_description_window_ms,
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
    video_description_window_ms: int = DEFAULT_VIDEO_DESCRIPTION_DURATION_MS,
    previous_summary_checkpoint: schemas.LectureVideoManifestSummaryCheckpointV4
    | None = None,
) -> schemas.LectureVideoManifestV4:
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
                video_description_window_ms=video_description_window_ms,
                previous_summary_checkpoint=previous_summary_checkpoint,
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
                video_description_window_ms=video_description_window_ms,
                previous_summary_checkpoint=previous_summary_checkpoint,
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
    video_description_window_ms: int = DEFAULT_VIDEO_DESCRIPTION_DURATION_MS,
    overlap_ms: int = _MANIFEST_CHUNK_OVERLAP_MS,
    previous_summary_checkpoint: schemas.LectureVideoManifestSummaryCheckpointV4
    | None = None,
) -> list[schemas.LectureVideoManifestV4]:
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
                video_description_window_ms=video_description_window_ms,
                previous_summary_checkpoint=previous_summary_checkpoint,
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
            overlap_ms=overlap_ms,
            alignment_ms=video_description_window_ms,
        )
        logger.info(
            "Splitting lecture video manifest chunk after provider limit. "
            "generation_start_ms=%s generation_end_ms=%s split_ms=%s",
            chunk.generation_start_ms,
            chunk.generation_end_ms,
            child_chunks[0].generation_end_ms,
        )
        chunk_manifests: list[schemas.LectureVideoManifestV4] = []
        current_summary_checkpoint = previous_summary_checkpoint
        for child_chunk in child_chunks:
            child_manifests = await _upload_and_generate_manifest_chunks(
                video_path=video_path,
                gemini_client=gemini_client,
                generation_prompt_content=generation_prompt_content,
                transcript=transcript,
                video_duration_ms=video_duration_ms,
                chunk=child_chunk,
                temp_dir=temp_dir,
                model=model,
                video_description_window_ms=video_description_window_ms,
                overlap_ms=overlap_ms,
                previous_summary_checkpoint=current_summary_checkpoint,
            )
            chunk_manifests.extend(child_manifests)
            current_summary_checkpoint = _latest_summary_checkpoint(
                child_manifests,
                current_summary_checkpoint,
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
    video_description_duration_ms: int = DEFAULT_VIDEO_DESCRIPTION_DURATION_MS,
) -> schemas.LectureVideoManifestV4:
    video_duration_ms = await _ffprobe_duration_ms(video_path)
    if video_duration_ms is None:
        raise RuntimeError(
            "Unable to determine lecture video duration with ffprobe; "
            "manifest generation requires a valid video duration."
        )
    video_description_window_ms = video_description_duration_ms
    overlap_ms = _manifest_chunk_overlap_ms(video_description_window_ms)
    chunks = _plan_manifest_generation_chunks(
        video_duration_ms,
        overlap_ms=overlap_ms,
        alignment_ms=video_description_window_ms,
    )
    if len(chunks) == 1:
        try:
            return await _upload_and_generate_whole_manifest(
                video_path=video_path,
                gemini_client=gemini_client,
                generation_prompt_content=generation_prompt_content,
                transcript=transcript,
                video_duration_ms=video_duration_ms,
                model=model,
                video_description_window_ms=video_description_window_ms,
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
                overlap_ms=overlap_ms,
                alignment_ms=video_description_window_ms,
            )

    logger.info(
        "Generating lecture video manifest in chunks. video_duration_ms=%s "
        "chunk_count=%s",
        video_duration_ms,
        len(chunks),
    )
    chunk_manifests: list[schemas.LectureVideoManifestV4] = []
    current_summary_checkpoint: (
        schemas.LectureVideoManifestSummaryCheckpointV4 | None
    ) = None
    for chunk in chunks:
        generated_chunk_manifests = await _upload_and_generate_manifest_chunks(
            video_path=video_path,
            gemini_client=gemini_client,
            generation_prompt_content=generation_prompt_content,
            transcript=transcript,
            video_duration_ms=video_duration_ms or chunk.generation_end_ms,
            chunk=chunk,
            temp_dir=temp_dir,
            model=model,
            video_description_window_ms=video_description_window_ms,
            overlap_ms=overlap_ms,
            previous_summary_checkpoint=current_summary_checkpoint,
        )
        chunk_manifests.extend(generated_chunk_manifests)
        current_summary_checkpoint = _latest_summary_checkpoint(
            generated_chunk_manifests,
            current_summary_checkpoint,
        )
    return await _merge_chunk_manifests(
        gemini_client=gemini_client,
        generation_prompt_content=generation_prompt_content,
        model=model,
        chunk_manifests=chunk_manifests,
        full_transcript=transcript,
        video_duration_ms=video_duration_ms,
        video_description_window_ms=video_description_window_ms,
    )


def video_suffix_for_content_type(content_type: str | None) -> str:
    if content_type == "video/webm":
        return ".webm"
    suffix = Path(str(content_type or "")).suffix
    return suffix or ".mp4"
