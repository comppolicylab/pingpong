import asyncio
import contextlib
import io
import json
import logging
import multiprocessing
import os
import secrets
import shutil
import socket
import subprocess
import tempfile
import time
from collections.abc import Callable, Coroutine, Mapping, Sequence
from dataclasses import dataclass
from datetime import timedelta
from functools import cache
from pathlib import Path
from typing import Any, Literal, TypeVar, TypedDict, cast

import openai
import tiktoken
from openai.types import Reasoning
import uuid_utils as uuid
from openai.types.audio import TranscriptionWord
from openai.types.responses.response_input_param import ResponseInputParam
from pydantic import BaseModel, ConfigDict, Field, ValidationError, create_model
from pydub import AudioSegment
from pypdf import PdfReader
from sqlalchemy import and_, delete, func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

import pingpong.models as models
import pingpong.schemas as schemas
from pingpong import lecture_slide_service
from pingpong import lecture_video_processing
from pingpong.ai import get_openai_client_by_class_id
from pingpong.class_credential_validation import (
    ClassCredentialValidationSSLError,
    ClassCredentialValidationUnavailableError,
    ClassCredentialVoiceValidationError,
)
from pingpong.config import config
from pingpong.errors import capture_exception_to_sentry, sentry
from pingpong.elevenlabs import synthesize_elevenlabs_speech
from pingpong.lecture_video_manifest_generation import (
    DEFAULT_LECTURE_INSTRUCTIONS,
    DEFAULT_GENERATION_PROMPT_CONTENT,
    _augment_manifest_words_with_segment_text,
    _generation_transcript_source_text,
)
from pingpong.lecture_video_service import (
    TRANSCRIPT_DATA_VERSION,
    lecture_video_words_to_webvtt,
)
from pingpong.lecture_slide_service import upload_lecture_slide_source_to_openai
from pingpong.now import utcnow
from pingpong.worker_pool import (
    DEFAULT_WORKER_POLL_INTERVAL_SECONDS,
    DEFAULT_WORKER_SHUTDOWN_GRACE_SECONDS,
    RunAssignment,
    WorkerCompleted,
    WorkerJobException,
    WorkerPoolManager,
    WorkerReady,
    WorkerStarted,
    ignore_sigint_in_worker,
)

logger = logging.getLogger(__name__)

_ResponseModelT = TypeVar("_ResponseModelT", bound=BaseModel)
_TranscriptionWordField = Literal["word", "start", "end"]
_TranscriptionWordValue = str | int | float


class SlidePageRange(TypedDict):
    slide_position: int
    start_offset_ms: int | None
    end_offset_ms: int | None


class SlideQuestionPauseOffsets(TypedDict):
    slide_offset_ms: int
    stop_offset_ms: int


OptionalSlideQuestionPauseOffsets = SlideQuestionPauseOffsets | None


LECTURE_SLIDES_CONTENT_SECTION = """### Context Provided
The conversation always begins with a developer message **hidden from the learner** and titled **"## Lecture Context"**. It is refreshed each turn to reflect the learner's latest position in the lesson. Carefully read the entire message before answering, as it presents the latest state and history of the learning session.

The structure within the "Lecture Context" matches this format:

-----BEGIN LECTURE CONTEXT-----

## Lecture Context
- **Status:** Indicates the learner’s present activity. One of:
    - *Viewing the lecture slides*
    - *Answering Knowledge Check #{n}*
    - *Just answered Knowledge Check #{n}*
    - *Finished the lecture slides*
- **Current offset:** How far into the narrated slide lesson the learner is currently, in milliseconds.
- **Furthest watched offset:** How far into the narrated slide lesson the learner has progressed so far, in milliseconds. The learner may have paused or rewound the lesson.
- **Current slide:** The slide currently on the learner's screen (e.g., *Slide 3*).
- **Furthest reached slide:** The furthest slide the learner has reached so far.

### Lecture Summary So Far
A cumulative natural-language summary of the concepts, explanations, and main points already introduced, from the start of the lesson through the learner's furthest watched offset and slide.

### Current Moment Context
- **Before this moment:** What the narration covered just prior to the current point.
- **At this moment:** What the narration is presenting at the present offset—focus carefully on this segment when answering.
- **After this moment:** What the narration will cover next—but you must avoid using or revealing this information unless acknowledging that it is coming (without explaining its substance).

### Current Slide
Details of the slide currently on the learner's screen—use this as the source of truth for answers about slide visuals, text, diagrams, equations, and layout:
- The slide number and title.
- **Visible text:** Important readable text on the slide.
- **Visual context:** The slide's layout, images, charts, code, or other visual elements.
- **Narration summary:** A summary of the narration spoken over this slide.
- **Key points:** Concise concept bullets from the slide.
- **Diagrams:** Notable diagrams on the slide.
- **Equations or symbols:** Notable equations and symbols on the slide.

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

The previous conversation messages between you and the learner follow this developer message, ending with the learner's newest question.
"""


DEFAULT_LECTURE_SLIDE_INSTRUCTIONS = DEFAULT_LECTURE_INSTRUCTIONS.safe_substitute(
    {
        "lecture_type": "slides",
        "activity_lesson": "narrating the slides",
        "context_provided_text": LECTURE_SLIDES_CONTENT_SECTION,
        "context_array_scope": "'Lecture Summary So Far', 'Before this moment', 'At this moment', 'Current Slide', 'Current Knowledge Check', or past 'Knowledge Checks Answered'",
        "content_array_scope_2": "'After this moment' or 'Upcoming Knowledge Check'",
        "notes_text": "Under no circumstances should you provide or explain information from 'After this moment' or 'Upcoming Knowledge Check' until it has actually become part of the 'Lecture Summary So Far' or appeared in a past Knowledge Check.",
    }
)

DEFAULT_NARRATION_PROMPT = """You are the instructor giving a lecture from this PDF slide deck.

Critical rules:
- Use the PDF itself as the source of truth.
- Write narration as if you are speaking live to students while each slide is visible.
- Teach the material on the slide; do not merely describe the slide's layout.
- Stay grounded in what appears on the current slide and the necessary connective context from earlier slides.
- Additional context files may clarify terminology, course emphasis, or background, but the PDF remains the source of truth for what students can see.
- Do not invent facts, examples, equations, citations, or course context that are not supported by the deck or instructor-provided additional context.
- Do not mention the PDF, the prompt, the model, schemas, extraction, or any implementation details.

For each slide:
1. Explain the slide's main point in a clear instructor voice.
2. Connect it briefly to the previous slide when that helps the lecture flow.
3. Highlight important definitions, steps, diagrams, equations, or contrasts visible on the slide.
4. When the slide naturally leads to a later knowledge check, end with a concise takeaway or setup that supports that style; do not force this on transition or low-substance slides.
5. Use natural spoken language suitable for text-to-speech.
6. Keep the narration focused and proportional to the slide's density: usually 30 to 90 seconds of spoken content, shorter for simple transition slides.

Output requirements:
- Return one narration item per slide.
- Use zero-based slide_position values.
- Keep narration_text as plain spoken prose, with no markdown, bullets, slide labels, or stage directions."""

RUN_LEASE_DURATION = timedelta(minutes=10)
RUN_LEASE_HEARTBEAT_INTERVAL = min(timedelta(minutes=1), RUN_LEASE_DURATION / 2)
UNEXPECTED_WORKER_EXIT_ERROR_MESSAGE = "Lecture slide worker exited unexpectedly."
LECTURE_SLIDE_AUDIO_CONTENT_TYPE = "audio/ogg"
LECTURE_SLIDE_CONTINUOUS_AUDIO_CONTENT_TYPE = "audio/webm"
FFMPEG_CONCAT_TIMEOUT_SECONDS = 300
MAX_RUN_CREATE_RETRIES = 3
OPENAI_GENERATION_MAX_ATTEMPTS = 3
OPENAI_GENERATION_RETRY_DELAY_SECONDS = 5.0
GPT_5_4_CONTEXT_WINDOW_TOKENS = 1_000_000
GPT_5_4_MAX_OUTPUT_TOKENS = 128_000
SLIDE_MANIFEST_FIXED_INPUT_TOKEN_RESERVE = 100_000
SLIDE_MANIFEST_TOKEN_SAFETY_MARGIN = 50_000
SLIDE_MANIFEST_INPUT_TOKEN_BUDGET = (
    GPT_5_4_CONTEXT_WINDOW_TOKENS
    - GPT_5_4_MAX_OUTPUT_TOKENS
    - SLIDE_MANIFEST_FIXED_INPUT_TOKEN_RESERVE
    - SLIDE_MANIFEST_TOKEN_SAFETY_MARGIN
)
SLIDE_MANIFEST_CHUNK_CONTEXT_OVERLAP_TOKENS = 10_000
SLIDE_MANIFEST_CHUNK_MIN_SPLIT_MS = 60 * 1000
SLIDE_MANIFEST_MIN_CHUNK_SOURCE_TOKENS = 25_000
SLIDE_MANIFEST_TOKENIZER_MODEL = "gpt-5.4"
SLIDE_MANIFEST_TOKENIZER_FALLBACK_ENCODING = "o200k_base"


class GeneratedSlideNarration(BaseModel):
    model_config = ConfigDict(extra="forbid")

    slide_position: int = Field(..., ge=0)
    title: str | None = None
    narration_text: str = Field(..., min_length=1)


class GeneratedSlideNarrationSet(BaseModel):
    model_config = ConfigDict(extra="forbid")

    slides: list[GeneratedSlideNarration] = Field(..., min_length=1)


def _generated_slide_narration_set_model(
    slide_count: int,
) -> type[GeneratedSlideNarrationSet]:
    if slide_count < 1:
        raise ValueError(
            "Lecture slide narration generation requires at least one slide."
        )
    return cast(
        type[GeneratedSlideNarrationSet],
        create_model(
            f"GeneratedSlideNarrationSet{slide_count}Slides",
            __base__=GeneratedSlideNarrationSet,
            slides=(
                list[GeneratedSlideNarration],
                Field(..., min_length=slide_count, max_length=slide_count),
            ),
        ),
    )


class GeneratedSlideChoice(BaseModel):
    model_config = ConfigDict(extra="forbid")

    option_text: str = Field(..., min_length=1)
    post_answer_text: str = ""
    correct: bool


class GeneratedSlideQuestion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    slide_position: int = Field(..., ge=0)
    question_text: str = Field(..., min_length=1)
    intro_text: str = ""
    options: list[GeneratedSlideChoice] = Field(..., min_length=2)


class GeneratedSlideManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    deck_summary: str = ""
    slides: list[schemas.LectureSlideContextSlideV5] = Field(default_factory=list)
    summary_checkpoints: list[schemas.LectureSlideContextSummaryCheckpointV5] = Field(
        default_factory=list
    )
    moment_contexts: list[schemas.LectureSlideContextMomentV5] = Field(
        default_factory=list
    )
    questions: list[GeneratedSlideQuestion] = Field(default_factory=list)


class GeneratedSlideContext(BaseModel):
    model_config = ConfigDict(extra="forbid")

    deck_summary: str = Field(..., min_length=1)
    slides: list[schemas.LectureSlideContextSlideV5] = Field(..., min_length=1)
    summary_checkpoints: list[schemas.LectureSlideContextSummaryCheckpointV5] = Field(
        ..., min_length=1
    )
    moment_contexts: list[schemas.LectureSlideContextMomentV5] = Field(
        ..., min_length=1
    )


def _build_slide_manifest_generation_instructions(
    content_section: str,
    *,
    total_duration_ms: int | None,
    manual_questions: list[GeneratedSlideQuestion] | None = None,
    question_requests: list[schemas.LectureSlideQuestionInput] | None = None,
    generation_start_ms: int | None = None,
    generation_end_ms: int | None = None,
    context_start_ms: int | None = None,
    context_end_ms: int | None = None,
) -> str:
    duration_text = (
        f"\nThe combined slide narration duration is {total_duration_ms} milliseconds."
        if total_duration_ms is not None
        else ""
    )
    generation_window_text = ""
    if generation_start_ms is not None and generation_end_ms is not None:
        generation_window_interval_text = (
            f"offsets greater than {generation_start_ms}ms and less than or equal "
            f"to {generation_end_ms}ms"
        )
        if generation_start_ms == 0:
            generation_window_interval_text = (
                f"offsets from 0ms through {generation_end_ms}ms"
            )
        context_range_text = (
            f" The supplied context covers offsets {context_start_ms}ms through "
            f"{context_end_ms}ms."
            if context_start_ms is not None and context_end_ms is not None
            else ""
        )
        generation_window_text = f"""

GENERATION WINDOW:
This is one chunk from a longer slide lesson.{context_range_text}
Generate questions only for {generation_window_interval_text}.
Use surrounding context to avoid boundary artifacts, but keep generated offsets inside the requested generation window.
"""
    manual_question_positions = sorted(
        {question.slide_position for question in manual_questions or []}
    )
    partial_question_positions = sorted(
        [
            question.slide_position
            for question in question_requests or []
            if question.mode == schemas.LectureSlideQuestionDraftMode.PARTIAL
        ]
    )
    marker_question_positions = sorted(
        [
            question.slide_position
            for question in question_requests or []
            if question.mode == schemas.LectureSlideQuestionDraftMode.MARKER
        ]
    )
    manual_question_guidance = ""
    if manual_question_positions:
        manual_question_guidance = f"""

COMPLETE INSTRUCTOR-AUTHORED QUESTIONS:
The request includes instructor-authored questions after these zero-based slide positions: {manual_question_positions}.
These questions will be inserted separately. Do not repeat, rephrase, replace, or generate additional questions after those slide positions.
You may generate questions at other slide breakpoints only when they satisfy the unmarked autogenerated question rules in the QUESTIONS section.
"""
    question_request_guidance = ""
    if partial_question_positions or marker_question_positions:
        question_request_guidance = f"""

INSTRUCTOR QUESTION REQUESTS:
The instructor requested model-completed questions after these zero-based slide positions.
- Partial question drafts to complete: {partial_question_positions}
- Marker-only required questions to create: {marker_question_positions}
You must include exactly one distinct question for each requested entry unless that slide is outside the generation window.
These requested entries are required minimums. Other autogenerated questions are allowed only under the unmarked autogenerated question rules in the QUESTIONS section.
Use any provided partial prompt, narration, options, feedback, or correct-answer hints as constraints, and fill missing details.
Do not generate additional unrequested questions after instructor-selected slide positions.
"""

    return f"""You are an expert educational content designer creating an interactive slide lesson from a PDF deck.

You will be given the PDF, optional instructor-provided additional context files, slide timing source data, and word-level narration transcript source data.{duration_text}
{generation_window_text}
{manual_question_guidance}
{question_request_guidance}

Use the PDF, additional context, slide timing source data, and transcript together. The PDF is the visual source of truth; the transcript is the spoken narration timeline. Additional context may clarify terminology, course emphasis, or background, but it is not slide-visible content unless also supported by the PDF or transcript.

GENERATION GUIDANCE SPECIFIC TO THIS LESSON:
{content_section.strip() or DEFAULT_GENERATION_PROMPT_CONTENT}

YOUR TASK:
Create a JSON object with these top-level fields:
- deck_summary: a compact one-paragraph summary of the full slide lesson.
- slides: compact per-slide chat context objects.
- summary_checkpoints: cumulative summaries through increasing timeline offsets.
- moment_contexts: local before/at/after context windows around important moments.
- questions: optional interaction questions placed only where the slide content naturally calls for one (see QUESTIONS).

SLIDE CHAT CONTEXT:
- Include one slides entry for each slide in the supplied generation window.
- slide_position is the zero-based slide number.
- title should match the slide title when visible; otherwise use a short descriptive title.
- start_offset_ms and end_offset_ms must come from the timing source row when available.
- visible_text should compactly capture important readable text on the slide.
- visual_context should describe diagrams, layout, images, charts, code, symbols, or other visual information needed to answer questions about the slide.
- narration_summary should summarize what the narration says for this slide.
- key_points should contain concise concept bullets grounded in the PDF and transcript.
- diagrams and equations_or_symbols should list notable visual diagrams or equations/symbols, or be empty arrays.
- For summary_checkpoints, each summary is cumulative from the start of the lesson through end_offset_ms, and end_slide_position is the zero-based slide reached by that offset.
- For moment_contexts, create useful local windows with start_offset_ms <= center_offset_ms <= end_offset_ms and a zero-based slide_position.
- If a generation window is provided, create slides, summary_checkpoints, and moment_contexts only for that requested generation window, not the surrounding context overlap.

QUESTIONS:
- Instructor-authored questions and instructor-marked question requests are required as described above.
- Any question that is not instructor-authored or instructor-marked is an unmarked autogenerated question.
- Add unmarked autogenerated questions only when the slide visibly contains an interaction prompt, such as a Poll Everywhere or multiple-choice question, an explicit quiz or check-your-understanding prompt, or a similar on-slide audience-participation cue.
- Do not add unmarked autogenerated questions to ordinary content, agenda, transition, summary, definition, or dense exposition slides just because the material could be tested.
- It is valid to return no unmarked autogenerated questions when the supplied slides do not contain a natural interaction point.
- A question appears between slides, after the selected slide finishes.
- For each question, set slide_position to the zero-based slide after which the question should appear.
- A slide is eligible for a question only when its timing source row has both start_offset_ms and end_offset_ms.
- Use question_text for the concise on-screen prompt.
- Use intro_text for a short spoken cue before the question appears. It may be empty when no cue is needed.
- Each question's options array uses option_text, post_answer_text, and correct.
- Exactly one option must have correct=true for every question.
- Keep answer choices concise, plausible, and focused on likely misconceptions.
- Keep post_answer_text to one or two natural spoken sentences.
- If a generation window is provided, create questions only after slides whose end_offset_ms is inside that same requested generation window.

- Use concrete evidence from the PDF, transcript, and instructor-provided additional context. Do not invent unsupported facts.

OUTPUT FORMAT:
Return a single JSON object matching the requested schema. Do not include any text outside the JSON.
Include questions only as permitted above; questions may be an empty array.
"""


def _build_slide_context_generation_instructions(
    content_section: str,
    *,
    total_duration_ms: int | None,
    generation_start_ms: int | None = None,
    generation_end_ms: int | None = None,
    context_start_ms: int | None = None,
    context_end_ms: int | None = None,
) -> str:
    duration_text = (
        f"\nThe combined slide narration duration is {total_duration_ms} milliseconds."
        if total_duration_ms is not None
        else ""
    )
    generation_window_text = ""
    if generation_start_ms is not None and generation_end_ms is not None:
        generation_window_interval_text = (
            f"offsets greater than {generation_start_ms}ms and less than or equal "
            f"to {generation_end_ms}ms"
        )
        if generation_start_ms == 0:
            generation_window_interval_text = (
                f"offsets from 0ms through {generation_end_ms}ms"
            )
        context_range_text = (
            f" The supplied context covers offsets {context_start_ms}ms through "
            f"{context_end_ms}ms."
            if context_start_ms is not None and context_end_ms is not None
            else ""
        )
        generation_window_text = f"""

GENERATION WINDOW:
This is one chunk from a longer slide lesson.{context_range_text}
Create context only for {generation_window_interval_text}.
Use surrounding context to avoid boundary artifacts, but keep generated offsets inside the requested generation window.
"""

    return f"""You are an expert educational content designer creating chat context for an interactive slide lesson from a PDF deck.

You will be given the PDF, optional instructor-provided additional context files, slide timing source data, and word-level narration transcript source data.{duration_text}
{generation_window_text}

Use the PDF, additional context, slide timing source data, and transcript together. The PDF is the visual source of truth; the transcript is the spoken narration timeline. Additional context may clarify terminology, course emphasis, or background, but it is not slide-visible content unless also supported by the PDF or transcript.

GENERATION GUIDANCE SPECIFIC TO THIS LESSON:
{content_section.strip() or DEFAULT_GENERATION_PROMPT_CONTENT}

YOUR TASK:
Create a JSON object with these top-level fields:
- deck_summary: a compact one-paragraph summary of the full slide lesson.
- slides: compact per-slide chat context objects.
- summary_checkpoints: cumulative summaries through increasing timeline offsets.
- moment_contexts: local before/at/after context windows around important moments.

SLIDE CHAT CONTEXT:
- Include one slides entry for each slide in the supplied generation window.
- slide_position is the zero-based slide number.
- title should match the slide title when visible; otherwise use a short descriptive title.
- start_offset_ms and end_offset_ms must come from the timing source row when available.
- visible_text should compactly capture important readable text on the slide.
- visual_context should describe diagrams, layout, images, charts, code, symbols, or other visual information needed to answer questions about the slide.
- narration_summary should summarize what the narration says for this slide.
- key_points should contain concise concept bullets grounded in the PDF and transcript.
- diagrams and equations_or_symbols should list notable visual diagrams or equations/symbols, or be empty arrays.
- For summary_checkpoints, each summary is cumulative from the start of the lesson through end_offset_ms, and end_slide_position is the zero-based slide reached by that offset.
- For moment_contexts, create useful local windows with start_offset_ms <= center_offset_ms <= end_offset_ms and a zero-based slide_position.
- If a generation window is provided, create slides, summary_checkpoints, and moment_contexts only for that requested generation window, not the surrounding context overlap.

Do not create, rewrite, summarize, or include knowledge-check questions. Existing questions are managed separately and are out of scope for this task.

Use concrete evidence from the PDF, transcript, and instructor-provided additional context. Do not invent unsupported facts.

OUTPUT FORMAT:
Return a single JSON object matching the requested schema. Do not include any text outside the JSON.
"""


def _slide_timing_source_text(page_ranges: list[SlidePageRange]) -> str:
    return (
        "SLIDE TIMING SOURCE DATA:\n"
        "Each range uses zero-based slide_position values and absolute "
        "millisecond offsets in the combined narration timeline.\n\n"
        f"{json.dumps(page_ranges, indent=2)}"
    )


def _slide_generation_final_task_text() -> str:
    return (
        "Based on the PDF, slide timing source data, and word-level transcript "
        "source data above, generate the interactive slide lesson manifest now. "
        "Follow the instructions and return only the schema-valid JSON object."
    )


def _slide_context_generation_final_task_text() -> str:
    return (
        "Based on the PDF, slide timing source data, and word-level transcript "
        "source data above, generate the slide lesson chat context now. Follow "
        "the instructions and return only the schema-valid JSON object."
    )


def _additional_context_user_message(
    additional_context_file_ids: Sequence[str],
) -> dict[str, object] | None:
    if not additional_context_file_ids:
        return None
    return {
        "role": "user",
        "content": [
            {
                "type": "input_text",
                "text": (
                    "The following files are instructor-provided additional context. "
                    "Use them only to clarify terminology, course emphasis, or background "
                    "that helps generate better narration and questions. Do not treat "
                    "these files as lecture slides, and do not invent slide-visible "
                    "content from them."
                ),
            },
            *[
                {"type": "input_file", "file_id": additional_context_file_id}
                for additional_context_file_id in additional_context_file_ids
            ],
        ],
    }


def _append_additional_context_message(
    input_messages: list[dict[str, object]],
    additional_context_file_ids: Sequence[str],
) -> list[dict[str, object]]:
    additional_context_message = _additional_context_user_message(
        additional_context_file_ids
    )
    if additional_context_message is None:
        return input_messages
    return [*input_messages, additional_context_message]


def _manual_slide_questions_from_context(
    context_data: Mapping[str, Any] | None,
) -> list[GeneratedSlideQuestion]:
    question_inputs = _manual_slide_question_inputs_from_context(context_data)
    return [
        GeneratedSlideQuestion(
            slide_position=question.slide_position,
            question_text=question.question_text,
            intro_text=question.intro_text,
            options=[
                GeneratedSlideChoice(
                    option_text=option.option_text,
                    post_answer_text=option.post_answer_text,
                    correct=option.correct,
                )
                for option in question.options
            ],
        )
        for question in question_inputs
        if question.mode == schemas.LectureSlideQuestionDraftMode.COMPLETE
    ]


def _manual_slide_question_inputs_from_context(
    context_data: Mapping[str, Any] | None,
) -> list[schemas.LectureSlideQuestionInput]:
    if not context_data:
        return []
    raw_questions = context_data.get(schemas.LECTURE_SLIDE_MANUAL_QUESTIONS_CONTEXT_KEY)
    if not isinstance(raw_questions, list):
        return []
    questions: list[schemas.LectureSlideQuestionInput] = []
    for raw_question in raw_questions:
        questions.append(schemas.LectureSlideQuestionInput.model_validate(raw_question))
    return questions


def _manual_slide_questions_source_text(
    complete_questions: list[GeneratedSlideQuestion],
    question_requests: list[schemas.LectureSlideQuestionInput] | None = None,
) -> str | None:
    partial_questions = [
        question
        for question in question_requests or []
        if question.mode == schemas.LectureSlideQuestionDraftMode.PARTIAL
    ]
    marker_questions = [
        question
        for question in question_requests or []
        if question.mode == schemas.LectureSlideQuestionDraftMode.MARKER
    ]
    if not complete_questions and not partial_questions and not marker_questions:
        return None
    payload: dict[str, object] = {}
    if complete_questions:
        payload["complete_questions_to_preserve"] = [
            question.model_dump() for question in complete_questions
        ]
    if partial_questions:
        payload["partial_questions_to_complete"] = [
            question.model_dump(mode="json") for question in partial_questions
        ]
    if marker_questions:
        payload["required_question_markers"] = [
            {
                "slide_position": question.slide_position,
            }
            for question in marker_questions
        ]
    return (
        "INSTRUCTOR QUESTION SOURCE DATA:\n"
        "This data was added by the instructor before generation. Preserve complete "
        "questions exactly. For partial questions, keep the instructor-provided "
        "details and fill in missing prompt, narration, answer choices, feedback, "
        "and correct answer as needed. For required_question_markers, create one "
        "useful question after each listed slide_position.\n\n"
        f"{json.dumps(payload, indent=2)}"
    )


@dataclass(frozen=True)
class ExtractedSlideAsset:
    position: int
    image_path: str
    width_px: int
    height_px: int
    extracted_text: str | None


@dataclass(frozen=True)
class SlideAudioArtifact:
    page_id: int
    page_position: int
    content_type: str
    audio: bytes
    duration_ms: int
    store_key: str
    stored_object_id: int


@dataclass(frozen=True)
class SlideManifestGenerationChunk:
    generation_start_ms: int
    generation_end_ms: int
    context_start_ms: int
    context_end_ms: int

    @property
    def generation_duration_ms(self) -> int:
        return self.generation_end_ms - self.generation_start_ms


class LectureSlideWorkerPoolManager(WorkerPoolManager):
    def __init__(
        self,
        *,
        workers: int,
        poll_interval_seconds: float = DEFAULT_WORKER_POLL_INTERVAL_SECONDS,
        shutdown_grace_seconds: float = DEFAULT_WORKER_SHUTDOWN_GRACE_SECONDS,
        process_context: Any | None = None,
        claim_run_fn: Callable[[str], RunAssignment | None] | None = None,
        recover_run_fn: Callable[[RunAssignment, str], bool] | None = None,
        sleep_fn: Callable[[float], None] = time.sleep,
        time_fn: Callable[[], float] = time.monotonic,
    ) -> None:
        self.async_runner: asyncio.Runner | None = None
        super().__init__(
            workers=workers,
            worker_target=_worker_process_main,
            process_context=process_context or get_forkserver_context(),
            claim_run_fn=claim_run_fn or self._claim_next_processing_run_sync,
            recover_run_fn=recover_run_fn or self._recover_failed_processing_run_sync,
            build_runner_id_fn=build_runner_id,
            worker_label="lecture processing worker",
            unexpected_exit_error_message=UNEXPECTED_WORKER_EXIT_ERROR_MESSAGE,
            poll_interval_seconds=poll_interval_seconds,
            shutdown_grace_seconds=shutdown_grace_seconds,
            sleep_fn=sleep_fn,
            time_fn=time_fn,
        )

    def _ensure_async_runner(self) -> asyncio.Runner:
        if self.async_runner is None:
            self.async_runner = asyncio.Runner()
        return self.async_runner

    def _claim_next_processing_run_sync(self, runner_id: str) -> RunAssignment | None:
        return self._ensure_async_runner().run(
            claim_next_any_processing_run(leased_by=runner_id)
        )

    def _recover_failed_processing_run_sync(
        self,
        assignment: RunAssignment,
        error_message: str,
    ) -> bool:
        return self._ensure_async_runner().run(
            recover_failed_processing_assignment(
                assignment,
                error_message=error_message,
            )
        )

    def _shutdown_resources(self) -> None:
        if self.async_runner is not None:
            self.async_runner.close()
            self.async_runner = None


def build_runner_id(worker_slot: int | None = None, pid: int | None = None) -> str:
    effective_pid = pid if pid is not None else os.getpid()
    if worker_slot is None:
        return f"lecture-processing:{socket.gethostname()}:{effective_pid}"
    return (
        f"lecture-processing:{socket.gethostname()}:{effective_pid}:"
        f"worker-{worker_slot}"
    )


def get_forkserver_context() -> multiprocessing.context.BaseContext:
    if "forkserver" not in multiprocessing.get_all_start_methods():
        raise RuntimeError(
            "The lecture processing worker pool requires the 'forkserver' start method."
        )
    return multiprocessing.get_context("forkserver")


def run_processing_worker_pool(
    *,
    workers: int = 1,
    poll_interval_seconds: float = DEFAULT_WORKER_POLL_INTERVAL_SECONDS,
    shutdown_grace_seconds: float = DEFAULT_WORKER_SHUTDOWN_GRACE_SECONDS,
    process_context: Any | None = None,
    claim_run_fn: Callable[[str], RunAssignment | None] | None = None,
    recover_run_fn: Callable[[RunAssignment, str], bool] | None = None,
    sleep_fn: Callable[[float], None] = time.sleep,
    time_fn: Callable[[], float] = time.monotonic,
) -> None:
    manager = LectureSlideWorkerPoolManager(
        workers=workers,
        poll_interval_seconds=poll_interval_seconds,
        shutdown_grace_seconds=shutdown_grace_seconds,
        process_context=process_context,
        claim_run_fn=claim_run_fn,
        recover_run_fn=recover_run_fn,
        sleep_fn=sleep_fn,
        time_fn=time_fn,
    )
    manager.run()


def _worker_process_main(worker_slot: int, assignment_queue, result_queue) -> None:
    with sentry():
        ignore_sigint_in_worker()
        result_queue.put(WorkerReady(worker_slot=worker_slot, pid=os.getpid()))
        with asyncio.Runner() as runner:
            while True:
                assignment = assignment_queue.get()
                if assignment is None:
                    logger.info(
                        "Lecture processing worker shutting down. slot=%s pid=%s",
                        worker_slot,
                        os.getpid(),
                    )
                    return
                if not isinstance(assignment, RunAssignment):
                    raise TypeError(
                        f"Expected RunAssignment, got {type(assignment).__name__}"
                    )

                result_queue.put(
                    WorkerStarted(
                        worker_slot=worker_slot,
                        kind=assignment.kind,
                        run_id=assignment.run_id,
                        lease_token=assignment.lease_token,
                    )
                )
                try:
                    runner.run(process_claimed_run(assignment))
                except Exception as exc:
                    logger.exception(
                        "Lecture processing worker failed. run_id=%s slot=%s pid=%s",
                        assignment.run_id,
                        worker_slot,
                        os.getpid(),
                    )
                    capture_exception_to_sentry(
                        exc,
                        source="lecture-processing-worker-child",
                        worker_slot=worker_slot,
                        pid=os.getpid(),
                        run_id=assignment.run_id,
                    )
                    result_queue.put(
                        WorkerJobException(
                            worker_slot=worker_slot,
                            kind=assignment.kind,
                            run_id=assignment.run_id,
                            lease_token=assignment.lease_token,
                            error_message=str(exc)
                            or UNEXPECTED_WORKER_EXIT_ERROR_MESSAGE,
                        )
                    )
                else:
                    result_queue.put(
                        WorkerCompleted(
                            worker_slot=worker_slot,
                            kind=assignment.kind,
                            run_id=assignment.run_id,
                            lease_token=assignment.lease_token,
                        )
                    )


async def queue_lecture_slide_processing_run(
    session: AsyncSession,
    deck: models.LectureSlideDeck,
    *,
    requested_by_assistant_id: int | None = None,
    stage: schemas.LectureSlideProcessingStage = (
        schemas.LectureSlideProcessingStage.SLIDE_ASSET_EXTRACTION
    ),
    force_manifest_generation: bool = False,
) -> models.LectureSlideProcessingRun | None:
    if deck.status == schemas.LectureSlideDeckStatus.FAILED:
        deck.status = schemas.LectureSlideDeckStatus.PROCESSING
    if (
        deck.status == schemas.LectureSlideDeckStatus.READY
        and stage != schemas.LectureSlideProcessingStage.SLIDE_ASSET_EXTRACTION
    ):
        deck.status = schemas.LectureSlideDeckStatus.PROCESSING
    if deck.status not in {
        schemas.LectureSlideDeckStatus.UPLOADED,
        schemas.LectureSlideDeckStatus.PROCESSING,
    }:
        return None

    async def reuse_existing_run(
        run: models.LectureSlideProcessingRun,
    ) -> models.LectureSlideProcessingRun:
        if force_manifest_generation and not run.force_manifest_generation:
            run.force_manifest_generation = True
            session.add(run)
            await session.flush()
        return run

    existing_run = await models.LectureSlideProcessingRun.get_non_terminal_by_snapshot(
        session,
        deck.id,
    )
    if existing_run is not None:
        if existing_run.stage_precedes_current(stage):
            existing_run.mark_cancelled_for_rewind()
            session.add(existing_run)
            await session.flush()
        else:
            return await reuse_existing_run(existing_run)

    deck.status = schemas.LectureSlideDeckStatus.PROCESSING
    deck.error_message = None
    attempt_number = (
        await models.LectureSlideProcessingRun.get_latest_attempt_number(
            session,
            deck.id,
        )
        + 1
    )
    last_error: IntegrityError | None = None
    for _ in range(MAX_RUN_CREATE_RETRIES):
        async with session.begin_nested() as savepoint:
            try:
                return await models.LectureSlideProcessingRun.create(
                    session,
                    lecture_slide_deck_id=deck.id,
                    lecture_slide_deck_id_snapshot=deck.id,
                    class_id=deck.class_id,
                    assistant_id_at_start=requested_by_assistant_id,
                    stage=stage,
                    attempt_number=attempt_number,
                    status=schemas.LectureSlideProcessingRunStatus.QUEUED,
                    force_manifest_generation=force_manifest_generation,
                )
            except IntegrityError as exc:
                last_error = exc
                await savepoint.rollback()

        existing_run = (
            await models.LectureSlideProcessingRun.get_non_terminal_by_snapshot(
                session,
                deck.id,
            )
        )
        if existing_run is not None:
            if existing_run.stage_precedes_current(stage):
                existing_run.mark_cancelled_for_rewind()
                session.add(existing_run)
                await session.flush()
            else:
                return await reuse_existing_run(existing_run)
        attempt_number = (
            await models.LectureSlideProcessingRun.get_latest_attempt_number(
                session,
                deck.id,
            )
            + 1
        )

    assert last_error is not None
    raise last_error


async def queue_narration_text_processing_run(
    session: AsyncSession,
    deck: models.LectureSlideDeck,
    *,
    requested_by_assistant_id: int | None = None,
) -> models.LectureSlideProcessingRun | None:
    return await queue_lecture_slide_processing_run(
        session,
        deck,
        requested_by_assistant_id=requested_by_assistant_id,
        stage=schemas.LectureSlideProcessingStage.NARRATION_TEXT,
    )


async def queue_audio_processing_run(
    session: AsyncSession,
    deck: models.LectureSlideDeck,
    *,
    requested_by_assistant_id: int | None = None,
    force_manifest_generation: bool = False,
) -> models.LectureSlideProcessingRun | None:
    return await queue_lecture_slide_processing_run(
        session,
        deck,
        requested_by_assistant_id=requested_by_assistant_id,
        stage=schemas.LectureSlideProcessingStage.NARRATION_AUDIO,
        force_manifest_generation=force_manifest_generation,
    )


async def queue_manifest_generation_processing_run(
    session: AsyncSession,
    deck: models.LectureSlideDeck,
    *,
    requested_by_assistant_id: int | None = None,
) -> models.LectureSlideProcessingRun | None:
    return await queue_lecture_slide_processing_run(
        session,
        deck,
        requested_by_assistant_id=requested_by_assistant_id,
        stage=schemas.LectureSlideProcessingStage.MANIFEST_GENERATION,
        force_manifest_generation=True,
    )


async def cancel_processing_runs(
    session: AsyncSession,
    deck_id: int,
    cancel_reason: schemas.LectureSlideProcessingCancelReason,
) -> None:
    now = utcnow()
    await session.execute(
        update(models.LectureSlideProcessingRun)
        .where(
            models.LectureSlideProcessingRun.lecture_slide_deck_id_snapshot == deck_id,
            models.LectureSlideProcessingRun.status.in_(
                [
                    schemas.LectureSlideProcessingRunStatus.QUEUED,
                    schemas.LectureSlideProcessingRunStatus.RUNNING,
                ]
            ),
        )
        .values(
            status=schemas.LectureSlideProcessingRunStatus.CANCELLED,
            cancel_reason=cancel_reason,
            finished_at=now,
            lease_token=None,
            leased_by=None,
            lease_expires_at=None,
        )
    )


def _claimable_processing_run_condition(now) -> Any:
    return or_(
        models.LectureSlideProcessingRun.status
        == schemas.LectureSlideProcessingRunStatus.QUEUED,
        and_(
            models.LectureSlideProcessingRun.status
            == schemas.LectureSlideProcessingRunStatus.RUNNING,
            or_(
                models.LectureSlideProcessingRun.lease_expires_at.is_(None),
                models.LectureSlideProcessingRun.lease_expires_at < now,
            ),
        ),
    )


async def claim_next_processing_run(
    *,
    leased_by: str | None = None,
) -> tuple[int, str] | None:
    async with config.db.driver.async_session() as session:
        now = utcnow()
        condition = _claimable_processing_run_condition(now)
        effective_leased_by = leased_by or build_runner_id()
        candidate_ids = list(
            (
                await session.scalars(
                    select(models.LectureSlideProcessingRun.id)
                    .where(condition)
                    .order_by(
                        func.coalesce(
                            models.LectureSlideProcessingRun.created, now
                        ).asc(),
                        models.LectureSlideProcessingRun.id.asc(),
                    )
                    .limit(25)
                )
            ).all()
        )
        for candidate_id in candidate_ids:
            lease_token = secrets.token_urlsafe(24)
            result = await session.execute(
                update(models.LectureSlideProcessingRun)
                .where(models.LectureSlideProcessingRun.id == candidate_id)
                .where(condition)
                .values(
                    status=schemas.LectureSlideProcessingRunStatus.RUNNING,
                    lease_token=lease_token,
                    leased_by=effective_leased_by,
                    lease_expires_at=now + RUN_LEASE_DURATION,
                    started_at=func.coalesce(
                        models.LectureSlideProcessingRun.started_at, now
                    ),
                    cancel_reason=None,
                    finished_at=None,
                )
            )
            if result.rowcount:
                await session.commit()
                return candidate_id, lease_token
    return None


async def claim_next_any_processing_run(
    *,
    leased_by: str | None = None,
) -> RunAssignment | None:
    async with config.db.driver.async_session() as session:
        now = utcnow()
        slide_result = await session.execute(
            select(
                models.LectureSlideProcessingRun.id,
                models.LectureSlideProcessingRun.created,
            )
            .where(_claimable_processing_run_condition(now))
            .order_by(
                func.coalesce(models.LectureSlideProcessingRun.created, now).asc(),
                models.LectureSlideProcessingRun.id.asc(),
            )
            .limit(1)
        )
        slide_candidate = slide_result.first()
        video_result = await session.execute(
            select(
                models.LectureVideoProcessingRun.id,
                models.LectureVideoProcessingRun.created,
            )
            .where(lecture_video_processing._claimable_processing_run_condition(now))
            .order_by(
                func.coalesce(models.LectureVideoProcessingRun.created, now).asc(),
                models.LectureVideoProcessingRun.id.asc(),
            )
            .limit(1)
        )
        video_candidate = video_result.first()

    try_video_first = False
    if video_candidate is not None and slide_candidate is None:
        try_video_first = True
    elif video_candidate is not None and slide_candidate is not None:
        video_created = video_candidate.created or utcnow()
        slide_created = slide_candidate.created or utcnow()
        try_video_first = (video_created, video_candidate.id) < (
            slide_created,
            slide_candidate.id,
        )

    if try_video_first:
        claimed_video = await lecture_video_processing._claim_next_processing_run(
            leased_by=leased_by
        )
        if claimed_video is not None:
            run_id, lease_token = claimed_video
            return RunAssignment(kind="video", run_id=run_id, lease_token=lease_token)
        claimed_slide = await claim_next_processing_run(leased_by=leased_by)
        if claimed_slide is None:
            return None
        run_id, lease_token = claimed_slide
        return RunAssignment(kind="slide", run_id=run_id, lease_token=lease_token)

    claimed_slide = await claim_next_processing_run(leased_by=leased_by)
    if claimed_slide is not None:
        run_id, lease_token = claimed_slide
        return RunAssignment(kind="slide", run_id=run_id, lease_token=lease_token)
    claimed_video = await lecture_video_processing._claim_next_processing_run(
        leased_by=leased_by
    )
    if claimed_video is None:
        return None
    run_id, lease_token = claimed_video
    return RunAssignment(kind="video", run_id=run_id, lease_token=lease_token)


async def recover_failed_processing_assignment(
    assignment: RunAssignment,
    *,
    error_message: str = UNEXPECTED_WORKER_EXIT_ERROR_MESSAGE,
) -> bool:
    if assignment.kind == "video":
        return await lecture_video_processing.recover_failed_processing_run(
            assignment.run_id,
            assignment.lease_token,
            error_message=error_message,
        )
    if assignment.kind != "slide":
        return False
    return await recover_failed_processing_run(
        assignment.run_id,
        assignment.lease_token,
        error_message=error_message,
    )


async def recover_failed_processing_run(
    run_id: int,
    lease_token: str,
    *,
    error_message: str = UNEXPECTED_WORKER_EXIT_ERROR_MESSAGE,
) -> bool:
    async with config.db.driver.async_session() as session:
        run = await models.LectureSlideProcessingRun.get_by_id(session, run_id)
        if run is None:
            return False
        if (
            run.status != schemas.LectureSlideProcessingRunStatus.RUNNING
            or run.lease_token != lease_token
        ):
            return False
        run.status = schemas.LectureSlideProcessingRunStatus.FAILED
        run.error_message = error_message
        run.finished_at = utcnow()
        run.cancel_reason = None
        run.lease_token = None
        run.leased_by = None
        run.lease_expires_at = None
        if run.lecture_slide_deck_id is not None:
            deck = await models.LectureSlideDeck.get_by_id_with_processing_context(
                session, run.lecture_slide_deck_id
            )
            if deck is not None:
                deck.status = schemas.LectureSlideDeckStatus.FAILED
                deck.error_message = error_message
                session.add(deck)
        session.add(run)
        await session.commit()
        return True


async def process_claimed_run(assignment: RunAssignment) -> None:
    if assignment.kind == "video":
        await lecture_video_processing._process_claimed_run(
            assignment.run_id,
            assignment.lease_token,
        )
        return
    if assignment.kind != "slide":
        return
    await _process_claimed_slide_run(assignment.run_id, assignment.lease_token)


async def _deck_has_slide_manifest(deck_id: int) -> bool:
    async with config.db.driver.async_session() as session:
        deck = await models.LectureSlideDeck.get_by_id(session, deck_id)
        if deck is None or deck.context_version not in {4, 5}:
            return False
        question_count = await session.scalar(
            select(func.count(models.LectureSlideQuestion.id)).where(
                models.LectureSlideQuestion.lecture_slide_deck_id == deck_id
            )
        )
        return bool(question_count)


async def _process_claimed_slide_run(run_id: int, lease_token: str) -> None:
    try:
        async with config.db.driver.async_session() as session:
            run = await models.LectureSlideProcessingRun.get_by_id(session, run_id)
            if run is None:
                return
            if (
                run.status != schemas.LectureSlideProcessingRunStatus.RUNNING
                or run.lease_token != lease_token
                or run.lecture_slide_deck_id is None
            ):
                return
            deck_id = run.lecture_slide_deck_id
            class_id = run.class_id
            start_stage = schemas.LectureSlideProcessingStage(run.stage)
            original_start_stage = start_stage
            force_manifest_generation = run.force_manifest_generation

        openai_client = None
        with tempfile.TemporaryDirectory(prefix="pingpong_ls_") as temp_dir:
            needs_pdf = (
                start_stage
                in {
                    schemas.LectureSlideProcessingStage.SLIDE_ASSET_EXTRACTION,
                    schemas.LectureSlideProcessingStage.NARRATION_TEXT,
                    schemas.LectureSlideProcessingStage.MANIFEST_GENERATION,
                }
                or force_manifest_generation
            )
            pdf_path = None
            if needs_pdf:
                pdf_path = await _download_source_pdf(
                    run_id, lease_token, deck_id, temp_dir
                )
                if pdf_path is None:
                    return

            needs_openai = start_stage in {
                schemas.LectureSlideProcessingStage.SLIDE_ASSET_EXTRACTION,
                schemas.LectureSlideProcessingStage.NARRATION_TEXT,
                schemas.LectureSlideProcessingStage.NARRATION_AUDIO,
                schemas.LectureSlideProcessingStage.NARRATION_TRANSCRIPTION,
                schemas.LectureSlideProcessingStage.MANIFEST_GENERATION,
            }
            responses_model = None
            if needs_openai:
                async with config.db.driver.async_session() as session:
                    openai_client = await get_openai_client_by_class_id(
                        session, class_id
                    )
                    responses_model = await _get_responses_model_for_run(
                        session,
                        run_id,
                        deck_id,
                    )

            transcript: list[schemas.LectureVideoManifestWordV3] | None = None
            openai_input_file_id: str | None = None

            if (
                start_stage
                == schemas.LectureSlideProcessingStage.SLIDE_ASSET_EXTRACTION
            ):
                assert pdf_path is not None
                await _set_run_stage(
                    run_id,
                    lease_token,
                    schemas.LectureSlideProcessingStage.SLIDE_ASSET_EXTRACTION,
                )
                await _extract_and_store_slide_assets(
                    run_id, lease_token, deck_id, pdf_path
                )
                if not await _ensure_run_can_continue(run_id, lease_token):
                    return
                start_stage = schemas.LectureSlideProcessingStage.NARRATION_TEXT

            if start_stage == schemas.LectureSlideProcessingStage.NARRATION_TEXT:
                assert pdf_path is not None
                assert openai_client is not None
                assert responses_model is not None
                openai_input_file_id = await _get_or_upload_openai_input_pdf(
                    run_id, lease_token, deck_id, pdf_path
                )
                if openai_input_file_id is None:
                    return
                await _set_run_stage(
                    run_id,
                    lease_token,
                    schemas.LectureSlideProcessingStage.NARRATION_TEXT,
                )
                narration_set = await _generate_narration_text(
                    run_id,
                    lease_token,
                    deck_id,
                    openai_input_file_id,
                    responses_model,
                    openai_client,
                )
                if narration_set is None:
                    return
                await _persist_narration_text(
                    run_id, lease_token, deck_id, narration_set
                )
                if not await _ensure_run_can_continue(run_id, lease_token):
                    return
                start_stage = schemas.LectureSlideProcessingStage.NARRATION_AUDIO

            if start_stage == schemas.LectureSlideProcessingStage.NARRATION_AUDIO:
                assert openai_client is not None
                await _set_run_stage(
                    run_id,
                    lease_token,
                    schemas.LectureSlideProcessingStage.NARRATION_AUDIO,
                )
                slide_audio = await _synthesize_slide_audio(
                    run_id, lease_token, deck_id
                )
                if slide_audio is None:
                    return

                await _set_run_stage(
                    run_id,
                    lease_token,
                    schemas.LectureSlideProcessingStage.NARRATION_TRANSCRIPTION,
                )
                transcript = await _transcribe_and_persist_slide_audio(
                    run_id,
                    lease_token,
                    deck_id,
                    slide_audio,
                    openai_client,
                    temp_dir,
                )
                if transcript is None:
                    return
                has_manifest = await _deck_has_slide_manifest(deck_id)
                start_stage = (
                    schemas.LectureSlideProcessingStage.COMPOSITE_ARTIFACTS
                    if original_start_stage
                    == schemas.LectureSlideProcessingStage.NARRATION_AUDIO
                    and has_manifest
                    and not force_manifest_generation
                    else schemas.LectureSlideProcessingStage.MANIFEST_GENERATION
                )

            if start_stage == schemas.LectureSlideProcessingStage.MANIFEST_GENERATION:
                if transcript is None:
                    transcript = await _load_slide_transcript_for_processing(deck_id)
                assert pdf_path is not None
                assert openai_client is not None
                assert responses_model is not None
                if openai_input_file_id is None:
                    openai_input_file_id = await _get_or_upload_openai_input_pdf(
                        run_id, lease_token, deck_id, pdf_path
                    )
                    if openai_input_file_id is None:
                        return
                await _set_run_stage(
                    run_id,
                    lease_token,
                    schemas.LectureSlideProcessingStage.MANIFEST_GENERATION,
                )
                manifest = await _generate_slide_manifest(
                    run_id,
                    lease_token,
                    deck_id,
                    openai_input_file_id,
                    transcript,
                    responses_model,
                    openai_client,
                )
                if manifest is None:
                    return
                await _persist_slide_manifest(
                    run_id, lease_token, deck_id, manifest, transcript
                )
                if not await _ensure_run_can_continue(run_id, lease_token):
                    return

            await _set_run_stage(
                run_id,
                lease_token,
                schemas.LectureSlideProcessingStage.COMPOSITE_ARTIFACTS,
            )
            if transcript is None:
                transcript = await _load_slide_transcript_for_processing(deck_id)
            await _synthesize_knowledge_check_audio(run_id, lease_token, deck_id)
            await _persist_composite_artifacts(run_id, lease_token, deck_id, transcript)
            await _mark_run_completed(run_id, lease_token)
    except Exception as exc:
        logger.exception("Lecture slide processing failed. run_id=%s", run_id)
        await recover_failed_processing_run(
            run_id,
            lease_token,
            error_message=_user_safe_processing_error_message(exc),
        )


async def _load_slide_transcript_for_processing(
    deck_id: int,
) -> list[schemas.LectureVideoManifestWordV3]:
    async with config.db.driver.async_session() as session:
        deck = await models.LectureSlideDeck.get_by_id_with_processing_context(
            session, deck_id
        )
        if deck is None or deck.transcript_data is None:
            raise RuntimeError("Lecture slide transcript is required for this update.")
        words = deck.transcript_data.get("word_level_transcription")
        if not isinstance(words, list):
            raise RuntimeError("Lecture slide transcript is invalid.")
        return [
            schemas.LectureVideoManifestWordV3.model_validate(word) for word in words
        ]


async def _await_with_run_lease_heartbeat(
    run_id: int,
    lease_token: str,
    operation: Coroutine[Any, Any, Any],
) -> Any | None:
    # Callers treat None as cancellation, so wrapped operations must return
    # non-None values.
    task: asyncio.Task[Any] = asyncio.create_task(operation)
    try:
        while True:
            done, _ = await asyncio.wait(
                {task},
                timeout=RUN_LEASE_HEARTBEAT_INTERVAL.total_seconds(),
            )
            if task in done:
                return await task
            if not await _ensure_run_can_continue(run_id, lease_token):
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    # Task was just cancelled via task.cancel(); ignore the expected
                    # CancelledError from awaiting it so the outer logic can proceed.
                    pass
                return None
    except Exception:
        if not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                # Task was cancelled as part of cleanup; suppress the expected CancelledError.
                pass
        raise


async def _set_run_stage(
    run_id: int,
    lease_token: str,
    stage: schemas.LectureSlideProcessingStage,
) -> bool:
    async with config.db.driver.async_session() as session:
        run = await models.LectureSlideProcessingRun.get_by_id(session, run_id)
        if run is None:
            return False
        if (
            run.status != schemas.LectureSlideProcessingRunStatus.RUNNING
            or run.lease_token != lease_token
        ):
            return False
        run.stage = stage
        run.lease_expires_at = utcnow() + RUN_LEASE_DURATION
        session.add(run)
        await session.commit()
        return True


async def _ensure_run_can_continue(run_id: int, lease_token: str) -> bool:
    async with config.db.driver.async_session() as session:
        run = await models.LectureSlideProcessingRun.get_by_id(session, run_id)
        if run is None:
            return False
        if (
            run.status != schemas.LectureSlideProcessingRunStatus.RUNNING
            or run.lease_token != lease_token
        ):
            return False
        if run.lecture_slide_deck_id is None:
            await _mark_run_cancelled(
                session,
                run,
                schemas.LectureSlideProcessingCancelReason.LECTURE_SLIDE_DECK_DELETED,
            )
            await session.commit()
            return False
        run.lease_expires_at = utcnow() + RUN_LEASE_DURATION
        session.add(run)
        await session.commit()
        return True


async def _mark_run_cancelled(
    session: AsyncSession,
    run: models.LectureSlideProcessingRun,
    cancel_reason: schemas.LectureSlideProcessingCancelReason,
) -> None:
    run.status = schemas.LectureSlideProcessingRunStatus.CANCELLED
    run.cancel_reason = cancel_reason
    run.finished_at = utcnow()
    run.lease_token = None
    run.leased_by = None
    run.lease_expires_at = None
    session.add(run)
    await session.flush()


async def _mark_run_completed(run_id: int, lease_token: str) -> None:
    async with config.db.driver.async_session() as session:
        run = await models.LectureSlideProcessingRun.get_by_id(session, run_id)
        if run is None:
            return
        if (
            run.status != schemas.LectureSlideProcessingRunStatus.RUNNING
            or run.lease_token != lease_token
        ):
            return
        if run.lecture_slide_deck_id is not None:
            deck = await models.LectureSlideDeck.get_by_id_with_processing_context(
                session, run.lecture_slide_deck_id
            )
            if deck is not None:
                deck.status = schemas.LectureSlideDeckStatus.READY
                deck.error_message = None
                session.add(deck)
        run.status = schemas.LectureSlideProcessingRunStatus.COMPLETED
        run.error_message = None
        run.finished_at = utcnow()
        run.lease_token = None
        run.leased_by = None
        run.lease_expires_at = None
        session.add(run)
        await session.commit()


async def _download_source_pdf(
    run_id: int,
    lease_token: str,
    deck_id: int,
    temp_dir: str,
) -> str | None:
    async with config.db.driver.async_session() as session:
        deck = await models.LectureSlideDeck.get_by_id_with_processing_context(
            session, deck_id
        )
        if deck is None:
            run = await models.LectureSlideProcessingRun.get_by_id(session, run_id)
            if run is not None and run.lease_token == lease_token:
                await _mark_run_cancelled(
                    session,
                    run,
                    schemas.LectureSlideProcessingCancelReason.LECTURE_SLIDE_DECK_DELETED,
                )
                await session.commit()
            return None
        if deck.source_stored_object is None:
            raise RuntimeError("Lecture slide source object is not loaded.")
        if not config.video_store:
            raise RuntimeError("Video store not configured or unavailable.")
        source_key = deck.source_stored_object.key

    pdf_path = os.path.join(temp_dir, f"lecture_slide_deck_{deck_id}.pdf")
    with open(pdf_path, "wb") as output:
        async for chunk in config.video_store.store.stream_video(source_key):
            await asyncio.to_thread(output.write, chunk)
    return pdf_path


async def _get_responses_model_for_run(
    session: AsyncSession,
    run_id: int,
    deck_id: int,
) -> str:
    run = await models.LectureSlideProcessingRun.get_by_id(session, run_id)
    if run is not None and run.assistant_id_at_start is not None:
        model = await session.scalar(
            select(models.Assistant.model).where(
                models.Assistant.id == run.assistant_id_at_start
            )
        )
        if model:
            return str(model)

    model = await session.scalar(
        select(models.Assistant.model)
        .where(models.Assistant.lecture_slide_deck_id == deck_id)
        .order_by(models.Assistant.id.asc())
        .limit(1)
    )
    if model:
        return str(model)

    raise RuntimeError("Lecture slide processing requires an assistant model.")


async def _extract_and_store_slide_assets(
    run_id: int,
    lease_token: str,
    deck_id: int,
    pdf_path: str,
) -> None:
    assets = await _await_with_run_lease_heartbeat(
        run_id,
        lease_token,
        asyncio.to_thread(extract_slide_assets_from_pdf, pdf_path),
    )
    if assets is None:
        return
    try:
        async with config.db.driver.async_session() as session:
            run = await models.LectureSlideProcessingRun.get_by_id(session, run_id)
            deck = await models.LectureSlideDeck.get_by_id_with_processing_context(
                session, deck_id
            )
            if (
                run is None
                or deck is None
                or run.status != schemas.LectureSlideProcessingRunStatus.RUNNING
                or run.lease_token != lease_token
            ):
                return

            existing_user_notes = {
                page.position: page.user_notes for page in deck.pages if page.user_notes
            }
            await session.execute(
                delete(models.LectureSlidePage).where(
                    models.LectureSlidePage.lecture_slide_deck_id == deck.id
                )
            )
            await session.flush()

            for asset in assets:
                image_bytes = Path(asset.image_path).read_bytes()
                image_key = generate_slide_image_store_key()
                if not config.video_store:
                    raise RuntimeError("Video store not configured or unavailable.")
                await config.video_store.store.put(
                    image_key,
                    io.BytesIO(image_bytes),
                    "image/png",
                )
                image_stored_object = models.LectureSlideImageStoredObject(
                    key=image_key,
                    content_type="image/png",
                    content_length=len(image_bytes),
                    width_px=asset.width_px,
                    height_px=asset.height_px,
                )
                session.add(image_stored_object)
                await session.flush()
                session.add(
                    models.LectureSlidePage(
                        lecture_slide_deck_id=deck.id,
                        position=asset.position,
                        image_stored_object_id=image_stored_object.id,
                        extracted_text=asset.extracted_text,
                        user_notes=existing_user_notes.get(asset.position),
                    )
                )
            deck.slide_count = len(assets)
            await session.commit()
    finally:
        cleanup_extracted_slide_assets(assets)


def extract_slide_assets_from_pdf(pdf_path: str) -> list[ExtractedSlideAsset]:
    output_dir = tempfile.mkdtemp(prefix="pingpong_ls_extract_")
    try:
        assets: list[ExtractedSlideAsset] = []
        output_prefix = os.path.join(output_dir, "page")
        try:
            subprocess.run(
                ["pdftoppm", "-png", "-r", "144", pdf_path, output_prefix],
                check=True,
                capture_output=True,
                text=True,
            )
        except FileNotFoundError as exc:
            raise RuntimeError(
                "pdftoppm is required to render lecture slide PDF pages."
            ) from exc
        except subprocess.CalledProcessError as exc:
            raise RuntimeError(
                f"pdftoppm failed while rendering lecture slide PDF: {exc.stderr.strip()}"
            ) from exc

        reader = PdfReader(pdf_path)
        image_paths = _list_rendered_pdf_page_images(output_dir, len(reader.pages))
        for page_index, page in enumerate(reader.pages):
            image_path = image_paths[page_index]
            width_px, height_px = _read_png_dimensions(image_path)
            text = (page.extract_text() or "").strip()
            assets.append(
                ExtractedSlideAsset(
                    position=page_index,
                    image_path=image_path,
                    width_px=width_px,
                    height_px=height_px,
                    extracted_text=text or None,
                )
            )
        if not assets:
            shutil.rmtree(output_dir, ignore_errors=True)
        return assets
    except Exception:
        shutil.rmtree(output_dir, ignore_errors=True)
        raise


def _list_rendered_pdf_page_images(output_dir: str, expected_count: int) -> list[str]:
    image_paths = sorted(
        Path(output_dir).glob("page-*.png"),
        key=lambda path: int(path.stem.removeprefix("page-")),
    )
    if len(image_paths) != expected_count:
        raise RuntimeError(
            f"pdftoppm rendered {len(image_paths)} slide images; expected {expected_count}."
        )
    return [str(path) for path in image_paths]


def _read_png_dimensions(image_path: str) -> tuple[int, int]:
    with open(image_path, "rb") as image_file:
        header = image_file.read(24)
    if len(header) < 24 or header[:8] != b"\x89PNG\r\n\x1a\n":
        raise RuntimeError(f"Rendered slide image is not a valid PNG: {image_path}")
    width = int.from_bytes(header[16:20], "big")
    height = int.from_bytes(header[20:24], "big")
    return width, height


def cleanup_extracted_slide_assets(assets: Sequence[ExtractedSlideAsset]) -> None:
    output_dirs = {Path(asset.image_path).parent for asset in assets}
    for output_dir in output_dirs:
        shutil.rmtree(output_dir, ignore_errors=True)


async def _get_or_upload_openai_input_pdf(
    run_id: int,
    lease_token: str,
    deck_id: int,
    pdf_path: str,
) -> str | None:
    async def _openai_file_exists(
        session: AsyncSession, class_id: int, file_id: str
    ) -> bool:
        openai_client = await get_openai_client_by_class_id(session, class_id)
        try:
            await openai_client.files.retrieve(file_id)
        except openai.NotFoundError:
            return False
        return True

    async def _resolve() -> str | None:
        async with config.db.driver.async_session() as session:
            deck = await models.LectureSlideDeck.get_by_id_with_processing_context(
                session, deck_id
            )
            if deck is None:
                run = await models.LectureSlideProcessingRun.get_by_id(session, run_id)
                if run is not None and run.lease_token == lease_token:
                    await _mark_run_cancelled(
                        session,
                        run,
                        schemas.LectureSlideProcessingCancelReason.LECTURE_SLIDE_DECK_DELETED,
                    )
                    await session.commit()
                return None
            source = deck.source_stored_object
            if source is None:
                raise RuntimeError("Lecture slide source object is not loaded.")
            if source.openai_file_object_id is not None:
                file = await models.File.get_by_id(
                    session, source.openai_file_object_id
                )
                if file is None or not file.file_id:
                    logger.warning(
                        "Lecture slide source has stale OpenAI file object pointer. "
                        "deck_id=%s source_id=%s file_object_id=%s has_file=%s",
                        deck.id,
                        source.id,
                        source.openai_file_object_id,
                        file is not None,
                    )
                else:
                    file_id = str(file.file_id)
                    if await _openai_file_exists(session, deck.class_id, file_id):
                        return file_id
                    logger.warning(
                        "Cached lecture slide OpenAI file is missing upstream; "
                        "re-uploading source PDF. deck_id=%s source_id=%s file_id=%s",
                        deck.id,
                        source.id,
                        file_id,
                    )
                    source.openai_file_object_id = None
                    session.add(source)

            source_bytes = await asyncio.to_thread(Path(pdf_path).read_bytes)
            file = await upload_lecture_slide_source_to_openai(
                session,
                source,
                class_id=deck.class_id,
                uploader_id=deck.uploader_id,
                source_bytes=source_bytes,
            )
            await session.commit()
            return str(file.file_id)

    return await _await_with_run_lease_heartbeat(
        run_id,
        lease_token,
        _resolve(),
    )


async def _generate_narration_text(
    run_id: int,
    lease_token: str,
    deck_id: int,
    file_id: str,
    responses_model: str,
    openai_client: openai.AsyncClient | openai.AsyncAzureOpenAI,
) -> GeneratedSlideNarrationSet | None:
    async with config.db.driver.async_session() as session:
        deck = await models.LectureSlideDeck.get_by_id_with_processing_context(
            session, deck_id
        )
        if deck is None:
            return None
        prompt = deck.narration_prompt or DEFAULT_NARRATION_PROMPT
        slide_count = deck.slide_count
        author_comments_guidance = _slide_author_comments_guidance_text(deck.pages)
        response_model = _generated_slide_narration_set_model(slide_count)
        additional_context_file_ids = _additional_context_file_ids(deck)

    return await _await_with_run_lease_heartbeat(
        run_id,
        lease_token,
        _parse_responses_output(
            openai_client,
            model=responses_model,
            instructions=prompt,
            response_model=response_model,
            input_messages=_append_additional_context_message(
                [
                    {
                        "role": "user",
                        "content": [
                            {"type": "input_file", "file_id": file_id},
                            {
                                "type": "input_text",
                                "text": _build_narration_generation_user_message(
                                    slide_count,
                                    author_comments_guidance,
                                ),
                            },
                        ],
                    }
                ],
                additional_context_file_ids,
            ),
        ),
    )


def _slide_author_comments_guidance_text(
    pages: Sequence[models.LectureSlidePage],
) -> str | None:
    comments: list[dict[str, object]] = []
    for page in sorted(pages, key=lambda item: item.position):
        user_notes = (page.user_notes or "").strip()
        if not user_notes:
            continue
        comments.append(
            {
                "slide_position": page.position,
                "author_comments": user_notes,
            }
        )
    if not comments:
        return None
    return (
        "AUTHOR COMMENTS BY SLIDE:\n"
        "Use these as additional per-slide guidance when writing narration. "
        "They may include instructor intent, emphasis, or clarification, but "
        "do not quote them mechanically unless that is natural for spoken "
        "lecture narration.\n\n"
        f"{json.dumps(comments, indent=2)}"
    )


def _additional_context_file_ids(deck: models.LectureSlideDeck) -> list[str]:
    file_ids: list[str] = []
    for context_file in sorted(
        deck.additional_context_files, key=lambda item: item.position
    ):
        if context_file.file is None or not context_file.file.file_id:
            logger.warning(
                "Skipping lecture slide additional context file without OpenAI file id. "
                "deck_id=%s context_file_id=%s file_object_id=%s",
                deck.id,
                context_file.id,
                context_file.file_object_id,
            )
            continue
        file_ids.append(str(context_file.file.file_id))
    return file_ids


def _build_narration_generation_user_message(
    slide_count: int,
    author_comments_guidance: str | None,
) -> str:
    message = (
        f"Generate narration for exactly {slide_count} slides. Use zero-based "
        "slide_position values."
    )
    if author_comments_guidance:
        message = f"{message}\n\n{author_comments_guidance}"
    return message


async def _persist_narration_text(
    run_id: int,
    lease_token: str,
    deck_id: int,
    narration_set: GeneratedSlideNarrationSet,
) -> None:
    narration_by_position = {item.slide_position: item for item in narration_set.slides}
    async with config.db.driver.async_session() as session:
        run = await models.LectureSlideProcessingRun.get_by_id(session, run_id)
        deck = await models.LectureSlideDeck.get_by_id_with_processing_context(
            session, deck_id
        )
        if (
            run is None
            or deck is None
            or run.status != schemas.LectureSlideProcessingRunStatus.RUNNING
            or run.lease_token != lease_token
        ):
            return
        for page in deck.pages:
            generated = narration_by_position.get(page.position)
            if generated is None:
                raise ValueError(f"Missing narration for slide {page.position}.")
            page.title = generated.title
            page.narration_text = generated.narration_text
            page.narration_id = None
            page.start_offset_ms = None
            page.end_offset_ms = None
            session.add(page)
        await session.commit()


async def _synthesize_slide_audio(
    run_id: int,
    lease_token: str,
    deck_id: int,
) -> list[SlideAudioArtifact] | None:
    async with config.db.driver.async_session() as session:
        deck = await models.LectureSlideDeck.get_by_id_with_processing_context(
            session, deck_id
        )
        if deck is None:
            return None
        class_id = deck.class_id
        voice_id = deck.voice_id
        pages = [
            (page.id, page.position, page.narration_text or "")
            for page in sorted(deck.pages, key=lambda item: item.position)
            if page.narration_id is None and text_needs_audio(page.narration_text or "")
        ]
    if not pages:
        return []
    if not voice_id:
        raise RuntimeError("Lecture slide deck voice_id is required for narration.")
    api_key = await _get_elevenlabs_api_key(class_id)
    artifacts: list[SlideAudioArtifact] = []
    for page_id, page_position, narration_text in pages:
        synthesis_result = await _await_with_run_lease_heartbeat(
            run_id,
            lease_token,
            synthesize_elevenlabs_speech(api_key, voice_id, narration_text),
        )
        if synthesis_result is None:
            # Existing stored slide audio is retained on mid-run cancellation,
            # matching lecture-video retry behavior.
            return None
        _, audio = synthesis_result
        content_type = LECTURE_SLIDE_AUDIO_CONTENT_TYPE
        duration_ms = audio_duration_ms(audio, content_type)
        store_key, content_length = await _store_audio(
            generate_slide_narration_store_key(),
            content_type,
            audio,
        )
        try:
            async with config.db.driver.async_session() as session:
                run = await models.LectureSlideProcessingRun.get_by_id(session, run_id)
                page = await session.get(models.LectureSlidePage, page_id)
                if (
                    run is None
                    or page is None
                    or run.status != schemas.LectureSlideProcessingRunStatus.RUNNING
                    or run.lease_token != lease_token
                ):
                    await _delete_audio_key_quietly(store_key)
                    return None
                stored_object = models.LectureSlideNarrationStoredObject(
                    key=store_key,
                    content_type=content_type,
                    content_length=content_length,
                    duration_ms=duration_ms,
                )
                session.add(stored_object)
                await session.flush()
                narration = models.LectureSlideNarration(
                    stored_object_id=stored_object.id,
                    status=schemas.LectureSlideNarrationStatus.READY,
                )
                session.add(narration)
                await session.flush()
                page.narration_id = narration.id
                session.add(page)
                await session.commit()
        except Exception:
            await _delete_audio_key_quietly(store_key)
            raise
        artifacts.append(
            SlideAudioArtifact(
                page_id=page_id,
                page_position=page_position,
                content_type=content_type,
                audio=audio,
                duration_ms=duration_ms,
                store_key=store_key,
                stored_object_id=stored_object.id,
            )
        )
    return artifacts


async def _get_elevenlabs_api_key(class_id: int) -> str:
    async with config.db.driver.async_session() as session:
        credential = await models.ClassCredential.get_by_class_id_and_purpose(
            session,
            class_id,
            schemas.ClassCredentialPurpose.LECTURE_VIDEO_NARRATION_TTS,
        )
        if credential is None or credential.api_key_obj is None:
            raise RuntimeError(
                "An ElevenLabs credential is required before lecture slide narration can be generated."
            )
        return credential.api_key_obj.api_key


async def _store_audio(
    store_key: str,
    content_type: str,
    audio: bytes,
) -> tuple[str, int]:
    if not config.lecture_video_audio_store:
        raise RuntimeError("Lecture video audio store is not configured.")
    upload = await config.lecture_video_audio_store.store.create_upload(
        name=store_key,
        content_type=content_type,
    )
    try:
        await upload.upload_part(io.BytesIO(audio))
        await upload.complete_upload()
    except Exception:
        with contextlib.suppress(Exception):
            await upload.delete_file()
        raise
    return store_key, len(audio)


async def _transcribe_and_persist_slide_audio(
    run_id: int,
    lease_token: str,
    deck_id: int,
    slide_audio: list[SlideAudioArtifact],
    openai_client: openai.AsyncClient | openai.AsyncAzureOpenAI,
    temp_dir: str,
) -> list[schemas.LectureVideoManifestWordV3] | None:
    artifacts_by_page_id = {artifact.page_id: artifact for artifact in slide_audio}
    transcribed_words_by_page_id: dict[
        int, list[schemas.LectureVideoManifestWordV3]
    ] = {}
    for artifact in sorted(slide_audio, key=lambda item: item.page_position):
        slide_path = os.path.join(temp_dir, f"slide-{artifact.page_position}.ogg")
        Path(slide_path).write_bytes(artifact.audio)
        slide_words = await _await_with_run_lease_heartbeat(
            run_id,
            lease_token,
            transcribe_audio_words(slide_path, openai_client),
        )
        if slide_words is None:
            return None
        transcribed_words_by_page_id[artifact.page_id] = slide_words

    async with config.db.driver.async_session() as session:
        run = await models.LectureSlideProcessingRun.get_by_id(session, run_id)
        deck = await models.LectureSlideDeck.get_by_id_with_processing_context(
            session, deck_id
        )
        if (
            run is None
            or deck is None
            or run.status != schemas.LectureSlideProcessingRunStatus.RUNNING
            or run.lease_token != lease_token
        ):
            return None
        old_transcript = []
        if deck.transcript_data is not None:
            raw_words = deck.transcript_data.get("word_level_transcription")
            if isinstance(raw_words, list):
                old_transcript = [
                    schemas.LectureVideoManifestWordV3.model_validate(word)
                    for word in raw_words
                ]

        words: list[schemas.LectureVideoManifestWordV3] = []
        current_offset_ms = 0
        for page in sorted(deck.pages, key=lambda item: item.position):
            page_artifact = artifacts_by_page_id.get(page.id)
            if page_artifact is not None:
                duration_ms = page_artifact.duration_ms
            elif (
                page.narration is not None and page.narration.stored_object is not None
            ):
                duration_ms = page.narration.stored_object.duration_ms or 0
            else:
                duration_ms = 0

            old_start_offset_ms = page.start_offset_ms
            old_end_offset_ms = page.end_offset_ms
            start_offset_ms = current_offset_ms if duration_ms > 0 else None
            end_offset_ms = current_offset_ms + duration_ms if duration_ms > 0 else None

            if page_artifact is not None and start_offset_ms is not None:
                for word_index, word in enumerate(
                    transcribed_words_by_page_id.get(page.id, [])
                ):
                    words.append(
                        schemas.LectureVideoManifestWordV3(
                            id=f"slide-{page_artifact.page_position}-word-{word_index}",
                            word=word.word,
                            start_offset_ms=word.start_offset_ms + start_offset_ms,
                            end_offset_ms=word.end_offset_ms + start_offset_ms,
                        )
                    )
            elif (
                old_start_offset_ms is not None
                and old_end_offset_ms is not None
                and start_offset_ms is not None
            ):
                offset_delta_ms = start_offset_ms - old_start_offset_ms
                for word in _transcript_for_slide_window(
                    old_transcript,
                    start_offset_ms=old_start_offset_ms,
                    end_offset_ms=old_end_offset_ms,
                ):
                    words.append(
                        word.model_copy(
                            update={
                                "start_offset_ms": word.start_offset_ms
                                + offset_delta_ms,
                                "end_offset_ms": word.end_offset_ms + offset_delta_ms,
                            }
                        )
                    )

            page.start_offset_ms = start_offset_ms
            page.end_offset_ms = end_offset_ms
            session.add(page)
            current_offset_ms += duration_ms

        deck.total_duration_ms = current_offset_ms
        deck.transcript_data = transcript_data_from_words(words)
        session.add(deck)
        await models.LectureSlideQuestion.retime_for_deck(session, deck)
        await session.commit()
    return words


async def transcribe_audio_words(
    audio_path: str,
    openai_client: openai.AsyncClient | openai.AsyncAzureOpenAI,
) -> list[schemas.LectureVideoManifestWordV3]:
    with open(audio_path, "rb") as audio_file:
        transcription = await openai_client.audio.transcriptions.create(
            file=audio_file,
            model="whisper-1",
            response_format="verbose_json",
            timestamp_granularities=["word", "segment"],
            timeout=60 * 20,
        )
    raw_words = getattr(transcription, "words", None)
    if raw_words is None and isinstance(transcription, dict):
        raw_words = transcription.get("words")
    segments = getattr(transcription, "segments", None)
    if segments is None and isinstance(transcription, dict):
        segments = transcription.get("segments")
    if not raw_words:
        raise ValueError("OpenAI transcription returned no word-level timestamps.")
    manifest_words: list[dict[str, object]] = []
    for index, word in enumerate(raw_words):
        raw_word_value = _get_attr_or_key(word, "word")
        if raw_word_value is None:
            continue
        raw_word = str(raw_word_value).strip()
        if not raw_word:
            continue
        start_value = _get_attr_or_key(word, "start")
        end_value = _get_attr_or_key(word, "end")
        start = _seconds_to_ms(start_value or 0)
        end = _seconds_to_ms(end_value or 0)
        manifest_words.append(
            {
                "id": f"word-{index}",
                "word": raw_word,
                "start_offset_ms": start,
                "end_offset_ms": end,
            }
        )
    if not manifest_words:
        raise ValueError("OpenAI transcription returned no non-empty words.")
    return [
        schemas.LectureVideoManifestWordV3.model_validate(word)
        for word in _augment_manifest_words_with_segment_text(manifest_words, segments)
    ]


def _slide_manifest_total_duration_ms(
    *,
    deck_total_duration_ms: int | None,
    page_ranges: list[SlidePageRange],
    transcript: list[schemas.LectureVideoManifestWordV3],
) -> int | None:
    candidates = [
        value
        for value in [
            deck_total_duration_ms,
            *(page_range["end_offset_ms"] for page_range in page_ranges),
            *(word.end_offset_ms for word in transcript),
        ]
        if value is not None
    ]
    return max(candidates) if candidates else None


def _transcript_for_slide_window(
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


def _page_ranges_for_slide_window(
    page_ranges: list[SlidePageRange],
    *,
    start_offset_ms: int,
    end_offset_ms: int,
) -> list[SlidePageRange]:
    return [
        page_range
        for page_range in page_ranges
        if page_range["end_offset_ms"] is None
        or page_range["start_offset_ms"] is None
        or (
            page_range["end_offset_ms"] >= start_offset_ms
            and page_range["start_offset_ms"] <= end_offset_ms
        )
    ]


def _timed_slide_page_ranges(page_ranges: list[SlidePageRange]) -> list[SlidePageRange]:
    return [
        page_range
        for page_range in page_ranges
        if page_range["start_offset_ms"] is not None
        and page_range["end_offset_ms"] is not None
    ]


@cache
def _slide_manifest_tokenizer() -> tiktoken.Encoding:
    try:
        return tiktoken.encoding_for_model(SLIDE_MANIFEST_TOKENIZER_MODEL)
    except KeyError:
        return tiktoken.get_encoding(SLIDE_MANIFEST_TOKENIZER_FALLBACK_ENCODING)


def _count_text_tokens(text: str) -> int:
    return len(_slide_manifest_tokenizer().encode(text))


def _slide_manifest_request_token_estimate(
    *,
    generation_prompt: str,
    page_ranges: list[SlidePageRange],
    transcript: list[schemas.LectureVideoManifestWordV3],
    total_duration_ms: int | None,
    manual_questions: list[GeneratedSlideQuestion] | None = None,
    question_requests: list[schemas.LectureSlideQuestionInput] | None = None,
    chunk: SlideManifestGenerationChunk | None = None,
) -> int:
    generation_start_ms = chunk.generation_start_ms if chunk is not None else None
    generation_end_ms = chunk.generation_end_ms if chunk is not None else None
    context_start_ms = chunk.context_start_ms if chunk is not None else None
    context_end_ms = chunk.context_end_ms if chunk is not None else None
    request_text = "\n\n".join(
        [
            _build_slide_manifest_generation_instructions(
                generation_prompt,
                total_duration_ms=total_duration_ms,
                manual_questions=manual_questions,
                question_requests=question_requests,
                generation_start_ms=generation_start_ms,
                generation_end_ms=generation_end_ms,
                context_start_ms=context_start_ms,
                context_end_ms=context_end_ms,
            ),
            _slide_timing_source_text(page_ranges),
            _generation_transcript_source_text(transcript, compact=False),
            _manual_slide_questions_source_text(
                manual_questions or [], question_requests
            )
            or "",
            _slide_generation_final_task_text(),
        ]
    )
    return _count_text_tokens(request_text)


def _slide_manifest_source_token_estimate(
    page_ranges: list[SlidePageRange],
    transcript: list[schemas.LectureVideoManifestWordV3],
) -> int:
    return _count_text_tokens(
        "\n\n".join(
            [
                _slide_timing_source_text(page_ranges),
                _generation_transcript_source_text(transcript, compact=False),
            ]
        )
    )


def _slide_manifest_chunk_source_token_budget(
    *,
    generation_prompt: str,
    total_duration_ms: int,
    manual_questions: list[GeneratedSlideQuestion] | None = None,
    question_requests: list[schemas.LectureSlideQuestionInput] | None = None,
) -> int:
    fixed_request_tokens = _slide_manifest_request_token_estimate(
        generation_prompt=generation_prompt,
        page_ranges=[],
        transcript=[],
        total_duration_ms=total_duration_ms,
        manual_questions=manual_questions,
        question_requests=question_requests,
    )
    return max(0, SLIDE_MANIFEST_INPUT_TOKEN_BUDGET - fixed_request_tokens)


def _word_token_estimate(word: schemas.LectureVideoManifestWordV3) -> int:
    return _count_text_tokens(
        json.dumps(
            {
                "id": word.id,
                "word": word.word,
                "start": word.start_offset_ms / 1000,
                "end": word.end_offset_ms / 1000,
            }
        )
    )


def _slide_manifest_context_window_for_token_overlap(
    transcript: list[schemas.LectureVideoManifestWordV3],
    *,
    generation_start_ms: int,
    generation_end_ms: int,
    total_duration_ms: int,
) -> tuple[int, int]:
    if SLIDE_MANIFEST_CHUNK_CONTEXT_OVERLAP_TOKENS <= 0:
        return generation_start_ms, generation_end_ms

    context_start_ms = generation_start_ms
    tokens_so_far = 0
    for word in reversed(transcript):
        if word.end_offset_ms > generation_start_ms:
            continue
        tokens_so_far += _word_token_estimate(word)
        context_start_ms = word.start_offset_ms
        if tokens_so_far >= SLIDE_MANIFEST_CHUNK_CONTEXT_OVERLAP_TOKENS:
            break

    context_end_ms = generation_end_ms
    tokens_so_far = 0
    for word in transcript:
        if word.start_offset_ms < generation_end_ms:
            continue
        tokens_so_far += _word_token_estimate(word)
        context_end_ms = word.end_offset_ms
        if tokens_so_far >= SLIDE_MANIFEST_CHUNK_CONTEXT_OVERLAP_TOKENS:
            break

    return max(0, context_start_ms), min(total_duration_ms, context_end_ms)


def _plan_slide_manifest_generation_chunks(
    total_duration_ms: int,
    *,
    generation_prompt: str,
    page_ranges: list[SlidePageRange],
    transcript: list[schemas.LectureVideoManifestWordV3],
    manual_questions: list[GeneratedSlideQuestion] | None = None,
    question_requests: list[schemas.LectureSlideQuestionInput] | None = None,
) -> list[SlideManifestGenerationChunk]:
    full_request_tokens = _slide_manifest_request_token_estimate(
        generation_prompt=generation_prompt,
        page_ranges=page_ranges,
        transcript=transcript,
        total_duration_ms=total_duration_ms,
        manual_questions=manual_questions,
        question_requests=question_requests,
    )
    if full_request_tokens <= SLIDE_MANIFEST_INPUT_TOKEN_BUDGET:
        return [
            SlideManifestGenerationChunk(
                generation_start_ms=0,
                generation_end_ms=total_duration_ms,
                context_start_ms=0,
                context_end_ms=total_duration_ms,
            )
        ]

    timed_page_ranges = [
        page_range
        for page_range in sorted(page_ranges, key=lambda item: item["slide_position"])
        if page_range["start_offset_ms"] is not None
        and page_range["end_offset_ms"] is not None
    ]
    if not timed_page_ranges:
        return [
            SlideManifestGenerationChunk(
                generation_start_ms=0,
                generation_end_ms=total_duration_ms,
                context_start_ms=0,
                context_end_ms=total_duration_ms,
            )
        ]

    source_budget = _slide_manifest_chunk_source_token_budget(
        generation_prompt=generation_prompt,
        total_duration_ms=total_duration_ms,
        manual_questions=manual_questions,
        question_requests=question_requests,
    )
    chunk_source_budget = max(
        SLIDE_MANIFEST_MIN_CHUNK_SOURCE_TOKENS,
        source_budget - (SLIDE_MANIFEST_CHUNK_CONTEXT_OVERLAP_TOKENS * 2),
    )
    chunks: list[SlideManifestGenerationChunk] = []
    current_page_ranges: list[SlidePageRange] = []
    current_token_estimate = 0

    def append_chunk(chunk_page_ranges: list[SlidePageRange]) -> None:
        generation_start_ms = cast(int, chunk_page_ranges[0]["start_offset_ms"])
        generation_end_ms = cast(int, chunk_page_ranges[-1]["end_offset_ms"])
        context_start_ms, context_end_ms = (
            _slide_manifest_context_window_for_token_overlap(
                transcript,
                generation_start_ms=generation_start_ms,
                generation_end_ms=generation_end_ms,
                total_duration_ms=total_duration_ms,
            )
        )
        chunks.append(
            SlideManifestGenerationChunk(
                generation_start_ms=generation_start_ms,
                generation_end_ms=generation_end_ms,
                context_start_ms=context_start_ms,
                context_end_ms=context_end_ms,
            )
        )

    for page_range in timed_page_ranges:
        start_offset_ms = cast(int, page_range["start_offset_ms"])
        end_offset_ms = cast(int, page_range["end_offset_ms"])
        page_transcript = _transcript_for_slide_window(
            transcript,
            start_offset_ms=start_offset_ms,
            end_offset_ms=end_offset_ms,
        )
        page_token_estimate = _slide_manifest_source_token_estimate(
            [page_range], page_transcript
        )
        if (
            current_page_ranges
            and current_token_estimate + page_token_estimate > chunk_source_budget
        ):
            append_chunk(current_page_ranges)
            current_page_ranges = []
            current_token_estimate = 0
        current_page_ranges.append(page_range)
        current_token_estimate += page_token_estimate
    if current_page_ranges:
        append_chunk(current_page_ranges)
    return chunks


def _split_slide_manifest_generation_chunk(
    chunk: SlideManifestGenerationChunk,
    *,
    total_duration_ms: int,
    transcript: list[schemas.LectureVideoManifestWordV3] | None = None,
) -> list[SlideManifestGenerationChunk]:
    split_ms = chunk.generation_start_ms + chunk.generation_duration_ms // 2
    if transcript:
        chunk_words = [
            word
            for word in transcript
            if word.end_offset_ms >= chunk.generation_start_ms
            and word.start_offset_ms <= chunk.generation_end_ms
        ]
        total_tokens = sum(_word_token_estimate(word) for word in chunk_words)
        if total_tokens > 0:
            midpoint_tokens = total_tokens / 2
            tokens_so_far = 0
            for word in chunk_words:
                tokens_so_far += _word_token_estimate(word)
                if tokens_so_far >= midpoint_tokens:
                    split_ms = word.end_offset_ms
                    break
    if split_ms <= chunk.generation_start_ms or split_ms >= chunk.generation_end_ms:
        split_ms = chunk.generation_start_ms + chunk.generation_duration_ms // 2
    first_context_start_ms, first_context_end_ms = (
        _slide_manifest_context_window_for_token_overlap(
            transcript or [],
            generation_start_ms=chunk.generation_start_ms,
            generation_end_ms=split_ms,
            total_duration_ms=total_duration_ms,
        )
    )
    second_context_start_ms, second_context_end_ms = (
        _slide_manifest_context_window_for_token_overlap(
            transcript or [],
            generation_start_ms=split_ms,
            generation_end_ms=chunk.generation_end_ms,
            total_duration_ms=total_duration_ms,
        )
    )
    return [
        SlideManifestGenerationChunk(
            generation_start_ms=chunk.generation_start_ms,
            generation_end_ms=split_ms,
            context_start_ms=min(chunk.context_start_ms, first_context_start_ms),
            context_end_ms=max(split_ms, first_context_end_ms),
        ),
        SlideManifestGenerationChunk(
            generation_start_ms=split_ms,
            generation_end_ms=chunk.generation_end_ms,
            context_start_ms=min(split_ms, second_context_start_ms),
            context_end_ms=max(chunk.context_end_ms, second_context_end_ms),
        ),
    ]


def _offset_is_in_window(
    offset_ms: int, start_offset_ms: int, end_offset_ms: int
) -> bool:
    return (
        (start_offset_ms == 0 and offset_ms >= start_offset_ms)
        or offset_ms > start_offset_ms
    ) and offset_ms <= end_offset_ms


def _filter_slide_questions_for_window(
    questions: list[GeneratedSlideQuestion],
    *,
    page_ranges: list[SlidePageRange],
    start_offset_ms: int,
    end_offset_ms: int,
) -> list[GeneratedSlideQuestion]:
    page_range_by_position = {
        int(page_range["slide_position"]): page_range for page_range in page_ranges
    }
    filtered: list[GeneratedSlideQuestion] = []
    for question in questions:
        pause_offsets = _slide_question_pause_offsets(
            question,
            page_range_by_position=page_range_by_position,
        )
        if pause_offsets is None:
            continue
        stop_offset_ms = pause_offsets["stop_offset_ms"]
        if _offset_is_in_window(stop_offset_ms, start_offset_ms, end_offset_ms):
            filtered.append(question)
    return filtered


def _filter_slide_context_for_window(
    manifest: GeneratedSlideManifest,
    *,
    page_ranges: list[SlidePageRange],
    start_offset_ms: int,
    end_offset_ms: int,
) -> GeneratedSlideManifest:
    window_slide_positions = {
        int(page_range["slide_position"])
        for page_range in page_ranges
        if page_range["start_offset_ms"] is not None
        and page_range["end_offset_ms"] is not None
        and _offset_is_in_window(
            page_range["end_offset_ms"], start_offset_ms, end_offset_ms
        )
        and page_range["start_offset_ms"] <= end_offset_ms
    }
    return manifest.model_copy(
        update={
            "slides": [
                slide
                for slide in manifest.slides
                if slide.slide_position in window_slide_positions
            ],
            "summary_checkpoints": [
                checkpoint
                for checkpoint in manifest.summary_checkpoints
                if _offset_is_in_window(
                    checkpoint.end_offset_ms, start_offset_ms, end_offset_ms
                )
            ],
            "moment_contexts": [
                moment
                for moment in manifest.moment_contexts
                if _offset_is_in_window(
                    moment.center_offset_ms, start_offset_ms, end_offset_ms
                )
            ],
        }
    )


def _slide_question_pause_offsets(
    question: GeneratedSlideQuestion,
    *,
    page_range_by_position: Mapping[int, SlidePageRange],
) -> OptionalSlideQuestionPauseOffsets:
    page_range = page_range_by_position.get(question.slide_position)
    if page_range is None:
        raise ValueError(
            f"Generated slide question references unknown slide_position "
            f"{question.slide_position}."
        )
    page_start_ms = page_range["start_offset_ms"]
    page_end_ms = page_range["end_offset_ms"]
    if page_start_ms is None or page_end_ms is None:
        return None
    return {
        "slide_offset_ms": max(page_end_ms - page_start_ms, 0),
        "stop_offset_ms": page_end_ms,
    }


def _validate_generated_slide_manifest(
    manifest: GeneratedSlideManifest,
    *,
    page_ranges: list[SlidePageRange],
    total_duration_ms: int | None,
) -> GeneratedSlideManifest:
    page_range_by_position = {
        int(page_range["slide_position"]): page_range for page_range in page_ranges
    }
    valid_questions: list[GeneratedSlideQuestion] = []
    for question in manifest.questions:
        pause_offsets = _slide_question_pause_offsets(
            question,
            page_range_by_position=page_range_by_position,
        )
        if pause_offsets is None:
            continue
        if (
            total_duration_ms is not None
            and pause_offsets["stop_offset_ms"] > total_duration_ms
        ):
            raise ValueError("Generated slide question pause point exceeds duration.")
        correct_count = sum(1 for option in question.options if option.correct)
        if correct_count != 1:
            raise ValueError(
                "Generated slide question must have exactly one correct option."
            )
        valid_questions.append(question)
    return manifest.model_copy(update={"questions": valid_questions})


def _validated_slide_context_v5(
    manifest: GeneratedSlideManifest,
) -> schemas.LectureSlideContextV5 | None:
    if (
        not manifest.deck_summary.strip()
        or not manifest.slides
        or not manifest.summary_checkpoints
        or not manifest.moment_contexts
    ):
        return None
    return schemas.LectureSlideContextV5.model_validate(
        {
            "version": 5,
            "deck_summary": manifest.deck_summary,
            "slides": [slide.model_dump() for slide in manifest.slides],
            "summary_checkpoints": [
                checkpoint.model_dump() for checkpoint in manifest.summary_checkpoints
            ],
            "moment_contexts": [
                moment.model_dump() for moment in manifest.moment_contexts
            ],
        }
    )


def _validated_existing_slide_context_v5(
    deck: models.LectureSlideDeck,
) -> schemas.LectureSlideContextV5 | None:
    if deck.context_version != 5 or deck.context_data is None:
        return None
    return schemas.LectureSlideContextV5.model_validate(deck.context_data)


def _is_context_limit_error(exc: Exception) -> bool:
    error_text = str(exc).lower()
    return any(
        marker in error_text
        for marker in (
            "input token count exceeds",
            "context_length_exceeded",
            "maximum context length",
            "too many tokens",
        )
    )


def _is_retryable_openai_generation_error(exc: Exception) -> bool:
    if _is_context_limit_error(exc):
        return False
    error_text = str(exc).lower()
    return any(
        marker in error_text
        for marker in (
            "429",
            "500",
            "502",
            "503",
            "504",
            "rate_limit",
            "timeout",
            "temporarily unavailable",
            "connection error",
        )
    )


async def _generate_slide_manifest(
    run_id: int,
    lease_token: str,
    deck_id: int,
    file_id: str,
    transcript: list[schemas.LectureVideoManifestWordV3],
    responses_model: str,
    openai_client: openai.AsyncClient | openai.AsyncAzureOpenAI,
) -> GeneratedSlideManifest | None:
    async with config.db.driver.async_session() as session:
        deck = await models.LectureSlideDeck.get_by_id_with_processing_context(
            session, deck_id
        )
        if deck is None:
            return None
        prompt = deck.generation_prompt or DEFAULT_GENERATION_PROMPT_CONTENT
        total_duration_ms = deck.total_duration_ms
        question_requests = _manual_slide_question_inputs_from_context(
            deck.context_data
        )
        manual_questions = _manual_slide_questions_from_context(deck.context_data)
        additional_context_file_ids = _additional_context_file_ids(deck)
        page_ranges: list[SlidePageRange] = [
            {
                "slide_position": page.position,
                "start_offset_ms": page.start_offset_ms,
                "end_offset_ms": page.end_offset_ms,
            }
            for page in sorted(deck.pages, key=lambda item: item.position)
        ]
    total_duration_ms = _slide_manifest_total_duration_ms(
        deck_total_duration_ms=total_duration_ms,
        page_ranges=page_ranges,
        transcript=transcript,
    )

    return await _await_with_run_lease_heartbeat(
        run_id,
        lease_token,
        _generate_slide_manifest_with_optional_chunks(
            openai_client=openai_client,
            model=responses_model,
            file_id=file_id,
            generation_prompt=prompt,
            page_ranges=page_ranges,
            transcript=transcript,
            total_duration_ms=total_duration_ms,
            manual_questions=manual_questions,
            question_requests=question_requests,
            additional_context_file_ids=additional_context_file_ids,
        ),
    )


async def generate_slide_context_v5(
    *,
    openai_client: openai.AsyncClient | openai.AsyncAzureOpenAI,
    model: str,
    file_id: str,
    generation_prompt: str | None,
    page_ranges: list[SlidePageRange],
    transcript: list[schemas.LectureVideoManifestWordV3],
    total_duration_ms: int | None,
    additional_context_file_ids: Sequence[str] = (),
) -> schemas.LectureSlideContextV5:
    prompt = generation_prompt or DEFAULT_GENERATION_PROMPT_CONTENT
    resolved_total_duration_ms = _slide_manifest_total_duration_ms(
        deck_total_duration_ms=total_duration_ms,
        page_ranges=page_ranges,
        transcript=transcript,
    )
    context = await _generate_slide_context_v5_with_optional_chunks(
        openai_client=openai_client,
        model=model,
        file_id=file_id,
        generation_prompt=prompt,
        page_ranges=page_ranges,
        transcript=transcript,
        total_duration_ms=resolved_total_duration_ms,
        additional_context_file_ids=additional_context_file_ids,
    )
    return schemas.LectureSlideContextV5.model_validate(
        {
            "version": 5,
            "deck_summary": context.deck_summary,
            "slides": [slide.model_dump() for slide in context.slides],
            "summary_checkpoints": [
                checkpoint.model_dump() for checkpoint in context.summary_checkpoints
            ],
            "moment_contexts": [
                moment.model_dump() for moment in context.moment_contexts
            ],
        }
    )


async def _generate_slide_context_v5_with_optional_chunks(
    *,
    openai_client: openai.AsyncClient | openai.AsyncAzureOpenAI,
    model: str,
    file_id: str,
    generation_prompt: str,
    page_ranges: list[SlidePageRange],
    transcript: list[schemas.LectureVideoManifestWordV3],
    total_duration_ms: int | None,
    additional_context_file_ids: Sequence[str] = (),
) -> GeneratedSlideContext:
    if total_duration_ms is None:
        context = await _generate_slide_context_v5_for_window(
            openai_client=openai_client,
            model=model,
            file_id=file_id,
            generation_prompt=generation_prompt,
            page_ranges=page_ranges,
            transcript=transcript,
            total_duration_ms=None,
            additional_context_file_ids=additional_context_file_ids,
        )
        if context is None:
            raise ValueError("Generated full lecture slide v5 context was empty.")
        return context
    chunks = _plan_slide_manifest_generation_chunks(
        total_duration_ms,
        generation_prompt=generation_prompt,
        page_ranges=page_ranges,
        transcript=transcript,
        manual_questions=[],
        question_requests=[],
    )
    if len(chunks) == 1:
        try:
            context = await _generate_slide_context_v5_for_window(
                openai_client=openai_client,
                model=model,
                file_id=file_id,
                generation_prompt=generation_prompt,
                page_ranges=page_ranges,
                transcript=transcript,
                total_duration_ms=total_duration_ms,
                additional_context_file_ids=additional_context_file_ids,
            )
            if context is None:
                raise ValueError("Generated full lecture slide v5 context was empty.")
            return context
        except Exception as exc:
            if (
                not _is_context_limit_error(exc)
                or chunks[0].generation_duration_ms <= SLIDE_MANIFEST_CHUNK_MIN_SPLIT_MS
            ):
                raise
            chunks = _split_slide_manifest_generation_chunk(
                chunks[0],
                total_duration_ms=total_duration_ms,
                transcript=transcript,
            )
    if len(chunks) == 1:
        raise RuntimeError("Slide context chunk planning did not split.")

    logger.info(
        "Generating lecture slide v5 context in chunks. total_duration_ms=%s "
        "chunk_count=%s",
        total_duration_ms,
        len(chunks),
    )
    chunk_contexts: list[GeneratedSlideContext] = []
    for chunk in chunks:
        chunk_contexts.extend(
            await _generate_slide_context_v5_chunks(
                openai_client=openai_client,
                model=model,
                file_id=file_id,
                generation_prompt=generation_prompt,
                page_ranges=page_ranges,
                transcript=transcript,
                total_duration_ms=total_duration_ms,
                chunk=chunk,
                additional_context_file_ids=additional_context_file_ids,
            )
        )
    return _merge_slide_context_chunks(chunk_contexts)


async def _generate_slide_context_v5_chunks(
    *,
    openai_client: openai.AsyncClient | openai.AsyncAzureOpenAI,
    model: str,
    file_id: str,
    generation_prompt: str,
    page_ranges: list[SlidePageRange],
    transcript: list[schemas.LectureVideoManifestWordV3],
    total_duration_ms: int,
    chunk: SlideManifestGenerationChunk,
    additional_context_file_ids: Sequence[str] = (),
) -> list[GeneratedSlideContext]:
    try:
        context = await _generate_slide_context_v5_for_window(
            openai_client=openai_client,
            model=model,
            file_id=file_id,
            generation_prompt=generation_prompt,
            page_ranges=page_ranges,
            transcript=transcript,
            total_duration_ms=total_duration_ms,
            chunk=chunk,
            additional_context_file_ids=additional_context_file_ids,
        )
        return [context] if context is not None else []
    except Exception as exc:
        if (
            not _is_context_limit_error(exc)
            or chunk.generation_duration_ms <= SLIDE_MANIFEST_CHUNK_MIN_SPLIT_MS
        ):
            raise
        child_chunks = _split_slide_manifest_generation_chunk(
            chunk,
            total_duration_ms=total_duration_ms,
            transcript=transcript,
        )
        logger.info(
            "Splitting lecture slide v5 context chunk after context limit. "
            "generation_start_ms=%s generation_end_ms=%s split_ms=%s",
            chunk.generation_start_ms,
            chunk.generation_end_ms,
            child_chunks[0].generation_end_ms,
        )
        contexts: list[GeneratedSlideContext] = []
        for child_chunk in child_chunks:
            contexts.extend(
                await _generate_slide_context_v5_chunks(
                    openai_client=openai_client,
                    model=model,
                    file_id=file_id,
                    generation_prompt=generation_prompt,
                    page_ranges=page_ranges,
                    transcript=transcript,
                    total_duration_ms=total_duration_ms,
                    chunk=child_chunk,
                    additional_context_file_ids=additional_context_file_ids,
                )
            )
        return contexts


async def _generate_slide_manifest_with_optional_chunks(
    *,
    openai_client: openai.AsyncClient | openai.AsyncAzureOpenAI,
    model: str,
    file_id: str,
    generation_prompt: str,
    page_ranges: list[SlidePageRange],
    transcript: list[schemas.LectureVideoManifestWordV3],
    total_duration_ms: int | None,
    manual_questions: list[GeneratedSlideQuestion] | None = None,
    question_requests: list[schemas.LectureSlideQuestionInput] | None = None,
    additional_context_file_ids: Sequence[str] = (),
) -> GeneratedSlideManifest:
    if total_duration_ms is None:
        return await _generate_slide_manifest_for_window(
            openai_client=openai_client,
            model=model,
            file_id=file_id,
            generation_prompt=generation_prompt,
            page_ranges=page_ranges,
            transcript=transcript,
            total_duration_ms=None,
            manual_questions=manual_questions,
            question_requests=question_requests,
            additional_context_file_ids=additional_context_file_ids,
        )
    chunks = _plan_slide_manifest_generation_chunks(
        total_duration_ms,
        generation_prompt=generation_prompt,
        page_ranges=page_ranges,
        transcript=transcript,
        manual_questions=manual_questions,
        question_requests=question_requests,
    )
    if len(chunks) == 1:
        try:
            return await _generate_slide_manifest_for_window(
                openai_client=openai_client,
                model=model,
                file_id=file_id,
                generation_prompt=generation_prompt,
                page_ranges=page_ranges,
                transcript=transcript,
                total_duration_ms=total_duration_ms,
                manual_questions=manual_questions,
                question_requests=question_requests,
                additional_context_file_ids=additional_context_file_ids,
            )
        except Exception as exc:
            if (
                not _is_context_limit_error(exc)
                or chunks[0].generation_duration_ms <= SLIDE_MANIFEST_CHUNK_MIN_SPLIT_MS
            ):
                raise
            chunks = _split_slide_manifest_generation_chunk(
                chunks[0],
                total_duration_ms=total_duration_ms,
                transcript=transcript,
            )
    if len(chunks) == 1:
        raise RuntimeError("Slide manifest chunk planning did not split.")

    logger.info(
        "Generating lecture slide manifest in chunks. total_duration_ms=%s "
        "chunk_count=%s",
        total_duration_ms,
        len(chunks),
    )
    chunk_manifests: list[GeneratedSlideManifest] = []
    for chunk in chunks:
        chunk_manifests.extend(
            await _generate_slide_manifest_chunks(
                openai_client=openai_client,
                model=model,
                file_id=file_id,
                generation_prompt=generation_prompt,
                page_ranges=page_ranges,
                transcript=transcript,
                total_duration_ms=total_duration_ms,
                chunk=chunk,
                manual_questions=manual_questions,
                question_requests=question_requests,
                additional_context_file_ids=additional_context_file_ids,
            )
        )
    return _merge_slide_chunk_manifests(chunk_manifests)


async def _generate_slide_manifest_chunks(
    *,
    openai_client: openai.AsyncClient | openai.AsyncAzureOpenAI,
    model: str,
    file_id: str,
    generation_prompt: str,
    page_ranges: list[SlidePageRange],
    transcript: list[schemas.LectureVideoManifestWordV3],
    total_duration_ms: int,
    chunk: SlideManifestGenerationChunk,
    manual_questions: list[GeneratedSlideQuestion] | None = None,
    question_requests: list[schemas.LectureSlideQuestionInput] | None = None,
    additional_context_file_ids: Sequence[str] = (),
) -> list[GeneratedSlideManifest]:
    try:
        manifest = await _generate_slide_manifest_for_window(
            openai_client=openai_client,
            model=model,
            file_id=file_id,
            generation_prompt=generation_prompt,
            page_ranges=page_ranges,
            transcript=transcript,
            total_duration_ms=total_duration_ms,
            chunk=chunk,
            manual_questions=manual_questions,
            question_requests=question_requests,
            additional_context_file_ids=additional_context_file_ids,
        )
        return [manifest]
    except Exception as exc:
        if (
            not _is_context_limit_error(exc)
            or chunk.generation_duration_ms <= SLIDE_MANIFEST_CHUNK_MIN_SPLIT_MS
        ):
            raise
        child_chunks = _split_slide_manifest_generation_chunk(
            chunk,
            total_duration_ms=total_duration_ms,
            transcript=transcript,
        )
        logger.info(
            "Splitting lecture slide manifest chunk after context limit. "
            "generation_start_ms=%s generation_end_ms=%s split_ms=%s",
            chunk.generation_start_ms,
            chunk.generation_end_ms,
            child_chunks[0].generation_end_ms,
        )
        manifests: list[GeneratedSlideManifest] = []
        for child_chunk in child_chunks:
            manifests.extend(
                await _generate_slide_manifest_chunks(
                    openai_client=openai_client,
                    model=model,
                    file_id=file_id,
                    generation_prompt=generation_prompt,
                    page_ranges=page_ranges,
                    transcript=transcript,
                    total_duration_ms=total_duration_ms,
                    chunk=child_chunk,
                    manual_questions=manual_questions,
                    question_requests=question_requests,
                    additional_context_file_ids=additional_context_file_ids,
                )
            )
        return manifests


async def _generate_slide_context_v5_for_window(
    *,
    openai_client: openai.AsyncClient | openai.AsyncAzureOpenAI,
    model: str,
    file_id: str,
    generation_prompt: str,
    page_ranges: list[SlidePageRange],
    transcript: list[schemas.LectureVideoManifestWordV3],
    total_duration_ms: int | None,
    chunk: SlideManifestGenerationChunk | None = None,
    additional_context_file_ids: Sequence[str] = (),
) -> GeneratedSlideContext | None:
    chunk_transcript = transcript
    chunk_page_ranges = page_ranges
    generation_start_ms = None
    generation_end_ms = None
    context_start_ms = None
    context_end_ms = None
    if chunk is not None:
        generation_start_ms = chunk.generation_start_ms
        generation_end_ms = chunk.generation_end_ms
        context_start_ms = chunk.context_start_ms
        context_end_ms = chunk.context_end_ms
        chunk_transcript = _transcript_for_slide_window(
            transcript,
            start_offset_ms=chunk.context_start_ms,
            end_offset_ms=chunk.context_end_ms,
        )
        chunk_page_ranges = _page_ranges_for_slide_window(
            page_ranges,
            start_offset_ms=chunk.context_start_ms,
            end_offset_ms=chunk.context_end_ms,
        )
    chunk_page_ranges = _timed_slide_page_ranges(chunk_page_ranges)
    context = await _parse_responses_output(
        openai_client,
        model=model,
        instructions=_build_slide_context_generation_instructions(
            generation_prompt,
            total_duration_ms=total_duration_ms,
            generation_start_ms=generation_start_ms,
            generation_end_ms=generation_end_ms,
            context_start_ms=context_start_ms,
            context_end_ms=context_end_ms,
        ),
        response_model=GeneratedSlideContext,
        input_messages=_append_additional_context_message(
            [
                {
                    "role": "user",
                    "content": [
                        {"type": "input_file", "file_id": file_id},
                        {
                            "type": "input_text",
                            "text": _slide_timing_source_text(chunk_page_ranges),
                        },
                        {
                            "type": "input_text",
                            "text": _generation_transcript_source_text(
                                chunk_transcript,
                                compact=False,
                            ),
                        },
                        {
                            "type": "input_text",
                            "text": _slide_context_generation_final_task_text(),
                        },
                    ],
                }
            ],
            additional_context_file_ids,
        ),
    )
    if chunk is not None:
        manifest = _filter_slide_context_for_window(
            GeneratedSlideManifest(
                deck_summary=context.deck_summary,
                slides=context.slides,
                summary_checkpoints=context.summary_checkpoints,
                moment_contexts=context.moment_contexts,
            ),
            page_ranges=page_ranges,
            start_offset_ms=chunk.generation_start_ms,
            end_offset_ms=chunk.generation_end_ms,
        )
        if (
            not manifest.slides
            or not manifest.summary_checkpoints
            or not manifest.moment_contexts
        ):
            logger.warning(
                "Skipping empty filtered lecture slide v5 context chunk. "
                "generation_start_ms=%s generation_end_ms=%s",
                chunk.generation_start_ms,
                chunk.generation_end_ms,
            )
            return None
        return GeneratedSlideContext(
            deck_summary=manifest.deck_summary,
            slides=manifest.slides,
            summary_checkpoints=manifest.summary_checkpoints,
            moment_contexts=manifest.moment_contexts,
        )
    return context


async def _generate_slide_manifest_for_window(
    *,
    openai_client: openai.AsyncClient | openai.AsyncAzureOpenAI,
    model: str,
    file_id: str,
    generation_prompt: str,
    page_ranges: list[SlidePageRange],
    transcript: list[schemas.LectureVideoManifestWordV3],
    total_duration_ms: int | None,
    manual_questions: list[GeneratedSlideQuestion] | None = None,
    question_requests: list[schemas.LectureSlideQuestionInput] | None = None,
    chunk: SlideManifestGenerationChunk | None = None,
    additional_context_file_ids: Sequence[str] = (),
) -> GeneratedSlideManifest:
    chunk_transcript = transcript
    chunk_page_ranges = page_ranges
    generation_start_ms = None
    generation_end_ms = None
    context_start_ms = None
    context_end_ms = None
    if chunk is not None:
        generation_start_ms = chunk.generation_start_ms
        generation_end_ms = chunk.generation_end_ms
        context_start_ms = chunk.context_start_ms
        context_end_ms = chunk.context_end_ms
        chunk_transcript = _transcript_for_slide_window(
            transcript,
            start_offset_ms=chunk.context_start_ms,
            end_offset_ms=chunk.context_end_ms,
        )
        chunk_page_ranges = _page_ranges_for_slide_window(
            page_ranges,
            start_offset_ms=chunk.context_start_ms,
            end_offset_ms=chunk.context_end_ms,
        )
    chunk_page_ranges = _timed_slide_page_ranges(chunk_page_ranges)
    manifest = await _parse_responses_output(
        openai_client,
        model=model,
        instructions=_build_slide_manifest_generation_instructions(
            generation_prompt,
            total_duration_ms=total_duration_ms,
            manual_questions=manual_questions,
            question_requests=question_requests,
            generation_start_ms=generation_start_ms,
            generation_end_ms=generation_end_ms,
            context_start_ms=context_start_ms,
            context_end_ms=context_end_ms,
        ),
        response_model=GeneratedSlideManifest,
        input_messages=_append_additional_context_message(
            [
                {
                    "role": "user",
                    "content": [
                        {"type": "input_file", "file_id": file_id},
                        {
                            "type": "input_text",
                            "text": _slide_timing_source_text(chunk_page_ranges),
                        },
                        {
                            "type": "input_text",
                            "text": _generation_transcript_source_text(
                                chunk_transcript,
                                compact=False,
                            ),
                        },
                        *(
                            [
                                {
                                    "type": "input_text",
                                    "text": manual_question_source_text,
                                }
                            ]
                            if (
                                manual_question_source_text
                                := _manual_slide_questions_source_text(
                                    manual_questions or [], question_requests
                                )
                            )
                            else []
                        ),
                        {
                            "type": "input_text",
                            "text": _slide_generation_final_task_text(),
                        },
                    ],
                }
            ],
            additional_context_file_ids,
        ),
    )
    if chunk is not None:
        manifest = manifest.model_copy(
            update={
                "questions": _filter_slide_questions_for_window(
                    manifest.questions,
                    page_ranges=page_ranges,
                    start_offset_ms=chunk.generation_start_ms,
                    end_offset_ms=chunk.generation_end_ms,
                )
            }
        )
        manifest = _filter_slide_context_for_window(
            manifest,
            page_ranges=page_ranges,
            start_offset_ms=chunk.generation_start_ms,
            end_offset_ms=chunk.generation_end_ms,
        )
    return _validate_generated_slide_manifest(
        manifest,
        page_ranges=page_ranges,
        total_duration_ms=total_duration_ms,
    )


def _merge_slide_context_chunks(
    chunk_contexts: list[GeneratedSlideContext],
) -> GeneratedSlideContext:
    if not chunk_contexts:
        raise ValueError("Generated slide context chunks were empty.")
    merged_manifest = _merge_slide_chunk_manifests(
        [
            GeneratedSlideManifest(
                deck_summary=context.deck_summary,
                slides=context.slides,
                summary_checkpoints=context.summary_checkpoints,
                moment_contexts=context.moment_contexts,
            )
            for context in chunk_contexts
        ]
    )
    return GeneratedSlideContext(
        deck_summary=merged_manifest.deck_summary,
        slides=merged_manifest.slides,
        summary_checkpoints=merged_manifest.summary_checkpoints,
        moment_contexts=merged_manifest.moment_contexts,
    )


def _merge_slide_chunk_manifests(
    chunk_manifests: list[GeneratedSlideManifest],
) -> GeneratedSlideManifest:
    def append_unique_summary(parts: list[str], summary: str) -> None:
        summary = summary.strip()
        if summary and summary not in parts:
            parts.append(summary)

    slides = sorted(
        {
            slide.slide_position: slide
            for manifest in chunk_manifests
            for slide in manifest.slides
        }.values(),
        key=lambda item: item.slide_position,
    )
    sorted_summary_checkpoints = sorted(
        {
            checkpoint.end_offset_ms: checkpoint
            for manifest in chunk_manifests
            for checkpoint in manifest.summary_checkpoints
        }.values(),
        key=lambda item: item.end_offset_ms,
    )
    cumulative_summary_parts: list[str] = []
    summary_checkpoints = []
    for checkpoint in sorted_summary_checkpoints:
        append_unique_summary(cumulative_summary_parts, checkpoint.summary)
        summary_checkpoints.append(
            checkpoint.model_copy(
                update={"summary": " ".join(cumulative_summary_parts)}
            )
        )
    moment_contexts = sorted(
        {
            moment.center_offset_ms: moment
            for manifest in chunk_manifests
            for moment in manifest.moment_contexts
        }.values(),
        key=lambda item: item.center_offset_ms,
    )
    deck_summary = (
        summary_checkpoints[-1].summary
        if summary_checkpoints
        else " ".join(
            manifest.deck_summary.strip()
            for manifest in chunk_manifests
            if manifest.deck_summary.strip()
        )
    )
    return GeneratedSlideManifest(
        deck_summary=deck_summary,
        slides=slides,
        summary_checkpoints=summary_checkpoints,
        moment_contexts=moment_contexts,
        questions=[
            question for manifest in chunk_manifests for question in manifest.questions
        ],
    )


def _generated_slide_question_to_input(
    question: GeneratedSlideQuestion,
) -> schemas.LectureSlideQuestionInput:
    return schemas.LectureSlideQuestionInput(
        mode=schemas.LectureSlideQuestionDraftMode.COMPLETE,
        slide_position=question.slide_position,
        question_text=question.question_text,
        intro_text=question.intro_text,
        options=[
            schemas.LectureSlideQuestionOptionInput(
                option_text=option.option_text,
                post_answer_text=option.post_answer_text,
                correct=option.correct,
            )
            for option in question.options
        ],
    )


async def _persist_slide_manifest(
    run_id: int,
    lease_token: str,
    deck_id: int,
    manifest: GeneratedSlideManifest,
    transcript: list[schemas.LectureVideoManifestWordV3],
) -> None:
    async with config.db.driver.async_session() as session:
        run = await models.LectureSlideProcessingRun.get_by_id(session, run_id)
        deck = await models.LectureSlideDeck.get_by_id_with_processing_context(
            session, deck_id
        )
        if (
            run is None
            or deck is None
            or run.status != schemas.LectureSlideProcessingRunStatus.RUNNING
            or run.lease_token != lease_token
        ):
            return
        manual_questions = _manual_slide_questions_from_context(deck.context_data)
        manual_question_positions = {
            question.slide_position for question in manual_questions
        }
        manifest_questions = [
            *manual_questions,
            *[
                question
                for question in manifest.questions
                if question.slide_position not in manual_question_positions
            ],
        ]

        await lecture_slide_service.apply_lecture_slide_question_drafts(
            session,
            deck,
            [
                _generated_slide_question_to_input(question)
                for question in sorted(
                    manifest_questions, key=lambda item: item.slide_position
                )
            ],
        )

        try:
            context_v5 = _validated_slide_context_v5(manifest)
        except (ValidationError, ValueError):
            logger.warning(
                "Generated lecture slide v5 context is invalid. "
                "lecture_slide_deck_id=%s",
                deck.id,
                exc_info=True,
            )
            context_v5 = None

        existing_context_v5 = None
        if context_v5 is None:
            try:
                existing_context_v5 = _validated_existing_slide_context_v5(deck)
            except (ValidationError, ValueError):
                existing_context_v5 = None

        if context_v5 is not None:
            deck.context_data = context_v5.model_dump()
            deck.context_version = 5
            deck.lecture_slide_chat_available = True
        elif existing_context_v5 is not None:
            deck.context_data = existing_context_v5.model_dump()
            deck.context_version = 5
            deck.lecture_slide_chat_available = True
        else:
            context_data = dict(deck.context_data or {})
            context_data.pop(schemas.LECTURE_SLIDE_MANUAL_QUESTIONS_CONTEXT_KEY, None)
            deck.context_data = context_data
            if transcript:
                deck.context_version = 4
                deck.lecture_slide_chat_available = True
            else:
                deck.context_version = None
                deck.lecture_slide_chat_available = False
        deck.transcript_data = transcript_data_from_words(transcript)
        await session.commit()


async def _synthesize_knowledge_check_audio(
    run_id: int,
    lease_token: str,
    deck_id: int,
) -> None:
    async with config.db.driver.async_session() as session:
        deck = await models.LectureSlideDeck.get_by_id_with_processing_context(
            session, deck_id
        )
        if deck is None:
            return
        voice_id = deck.voice_id
        class_id = deck.class_id
        narration_items: list[tuple[int, str]] = []
        for question in deck.questions:
            if (
                question.intro_narration
                and text_needs_audio(question.intro_text)
                and question.intro_narration.status
                != schemas.LectureSlideNarrationStatus.READY
            ):
                narration_items.append(
                    (question.intro_narration.id, question.intro_text)
                )
            for option in question.options:
                if (
                    option.post_narration
                    and text_needs_audio(option.post_answer_text)
                    and option.post_narration.status
                    != schemas.LectureSlideNarrationStatus.READY
                ):
                    narration_items.append(
                        (option.post_narration.id, option.post_answer_text)
                    )
    if not narration_items:
        return
    if not voice_id:
        raise RuntimeError("Lecture slide deck voice_id is required for narration.")
    api_key = await _get_elevenlabs_api_key(class_id)
    for narration_id, text in narration_items:
        synthesis_result = await _await_with_run_lease_heartbeat(
            run_id,
            lease_token,
            synthesize_elevenlabs_speech(api_key, voice_id, text),
        )
        if synthesis_result is None:
            return
        _, audio = synthesis_result
        content_type = LECTURE_SLIDE_AUDIO_CONTENT_TYPE
        store_key, content_length = await _store_audio(
            generate_slide_narration_store_key(),
            content_type,
            audio,
        )
        duration_ms = audio_duration_ms(audio, content_type)
        try:
            async with config.db.driver.async_session() as session:
                run = await models.LectureSlideProcessingRun.get_by_id(session, run_id)
                narration = await models.LectureSlideNarration.get_by_id(
                    session, narration_id
                )
                if (
                    run is None
                    or narration is None
                    or run.status != schemas.LectureSlideProcessingRunStatus.RUNNING
                    or run.lease_token != lease_token
                ):
                    await _delete_audio_key_quietly(store_key)
                    return
                stored_object = models.LectureSlideNarrationStoredObject(
                    key=store_key,
                    content_type=content_type,
                    content_length=content_length,
                    duration_ms=duration_ms,
                )
                session.add(stored_object)
                await session.flush()
                narration.stored_object_id = stored_object.id
                narration.status = schemas.LectureSlideNarrationStatus.READY
                narration.error_message = None
                session.add(narration)
                await session.commit()
        except Exception:
            await _delete_audio_key_quietly(store_key)
            raise


async def _persist_composite_artifacts(
    run_id: int,
    lease_token: str,
    deck_id: int,
    transcript: list[schemas.LectureVideoManifestWordV3],
) -> None:
    async with config.db.driver.async_session() as session:
        deck = await models.LectureSlideDeck.get_by_id_with_processing_context(
            session, deck_id
        )
        if deck is None:
            return
        fingerprint = deck.compute_continuous_narration_fingerprint()
        if (
            deck.continuous_narration_fingerprint == fingerprint
            and deck.continuous_narration_stored_object_id is not None
            and deck.caption_stored_object_id is not None
        ):
            return
        stored_objects = deck.validated_composite_page_audio_objects()
        duration_ms = _total_stored_audio_duration_ms(stored_objects)
    combined_audio = await _combine_audio_objects(stored_objects)
    content_type = LECTURE_SLIDE_CONTINUOUS_AUDIO_CONTENT_TYPE
    audio_key, audio_length = await _store_audio(
        generate_slide_continuous_narration_store_key(),
        content_type,
        combined_audio,
    )
    caption_text = lecture_video_words_to_webvtt(transcript)
    caption_bytes = caption_text.encode("utf-8")
    caption_key = generate_slide_caption_store_key()
    if not config.video_store:
        raise RuntimeError("Video store not configured or unavailable.")
    await config.video_store.store.put(
        caption_key, io.BytesIO(caption_bytes), "text/vtt"
    )

    try:
        async with config.db.driver.async_session() as session:
            run = await models.LectureSlideProcessingRun.get_by_id(session, run_id)
            deck = await models.LectureSlideDeck.get_by_id_with_processing_context(
                session, deck_id
            )
            if (
                run is None
                or deck is None
                or run.status != schemas.LectureSlideProcessingRunStatus.RUNNING
                or run.lease_token != lease_token
            ):
                await _delete_audio_key_quietly(audio_key)
                if config.video_store:
                    with contextlib.suppress(Exception):
                        await config.video_store.store.delete(caption_key)
                return
            audio_stored_object = models.LectureSlideNarrationStoredObject(
                key=audio_key,
                content_type=content_type,
                content_length=audio_length,
                duration_ms=duration_ms,
            )
            caption_stored_object = models.LectureSlideCaptionStoredObject(
                key=caption_key,
                content_type="text/vtt",
                content_length=len(caption_bytes),
            )
            session.add_all([audio_stored_object, caption_stored_object])
            await session.flush()
            deck.continuous_narration_stored_object_id = audio_stored_object.id
            deck.caption_stored_object_id = caption_stored_object.id
            deck.continuous_narration_fingerprint = (
                deck.compute_continuous_narration_fingerprint()
            )
            session.add(deck)
            await session.commit()
    except Exception:
        await _delete_audio_key_quietly(audio_key)
        if config.video_store:
            with contextlib.suppress(Exception):
                await config.video_store.store.delete(caption_key)
        raise


async def _combine_audio_objects(
    stored_objects: Sequence[models.LectureSlideNarrationStoredObject],
) -> bytes:
    """Combine stored Ogg/Opus narration objects without decoding them in Python."""
    if not stored_objects:
        return b""
    if not config.lecture_video_audio_store:
        raise RuntimeError("Lecture video audio store is not configured.")
    ffmpeg_path = shutil.which("ffmpeg")
    if ffmpeg_path is None:
        raise RuntimeError("ffmpeg is required for lecture slide audio concatenation.")

    with tempfile.TemporaryDirectory() as temp_dir_name:
        temp_dir = Path(temp_dir_name)
        input_paths: list[Path] = []
        for index, stored_object in enumerate(stored_objects):
            input_path = temp_dir / f"input-{index}.audio"
            with input_path.open("wb") as file:
                async for chunk in config.lecture_video_audio_store.store.get_file(
                    stored_object.key
                ):
                    file.write(chunk)
            input_paths.append(input_path)

        output_path = temp_dir / "combined.webm"
        try:
            await asyncio.to_thread(
                _run_ffmpeg_concat,
                ffmpeg_path,
                input_paths,
                output_path,
                stream_copy=True,
            )
        except RuntimeError:
            logger.warning(
                "ffmpeg stream-copy concat failed; retrying with Opus re-encode.",
                exc_info=True,
            )
            await asyncio.to_thread(
                _run_ffmpeg_concat,
                ffmpeg_path,
                input_paths,
                output_path,
                stream_copy=False,
            )
        return output_path.read_bytes()


async def remux_continuous_narration_to_webm(ogg_audio: bytes) -> bytes:
    """Losslessly remux an Opus-in-Ogg continuous narration into WebM."""
    ffmpeg_path = shutil.which("ffmpeg")
    if ffmpeg_path is None:
        raise RuntimeError("ffmpeg is required for lecture slide audio remuxing.")

    with tempfile.TemporaryDirectory() as temp_dir_name:
        temp_dir = Path(temp_dir_name)
        input_path = temp_dir / "input.ogg"
        input_path.write_bytes(ogg_audio)
        output_path = temp_dir / "combined.webm"
        try:
            await asyncio.to_thread(
                _run_ffmpeg_remux,
                ffmpeg_path,
                input_path,
                output_path,
                stream_copy=True,
            )
        except RuntimeError:
            logger.warning(
                "ffmpeg stream-copy remux failed; retrying with Opus re-encode.",
                exc_info=True,
            )
            await asyncio.to_thread(
                _run_ffmpeg_remux,
                ffmpeg_path,
                input_path,
                output_path,
                stream_copy=False,
            )
        return output_path.read_bytes()


def _total_stored_audio_duration_ms(
    stored_objects: Sequence[models.LectureSlideNarrationStoredObject],
) -> int:
    """Return the sum of required stored narration durations."""
    missing_duration_keys = [
        stored_object.key
        for stored_object in stored_objects
        if stored_object.duration_ms is None
    ]
    if missing_duration_keys:
        raise RuntimeError(
            "Lecture slide narration duration is missing for stored object(s): "
            + ", ".join(missing_duration_keys)
        )
    return sum(cast(int, stored_object.duration_ms) for stored_object in stored_objects)


def _run_ffmpeg_concat(
    ffmpeg_path: str,
    input_paths: Sequence[Path],
    output_path: Path,
    *,
    stream_copy: bool,
) -> None:
    """Run ffmpeg concat, preferring stream-copy unless re-encode is requested."""
    concat_path = output_path.with_suffix(".txt")
    concat_path.write_text(
        "".join(f"file '{_escape_ffmpeg_concat_path(path)}'\n" for path in input_paths)
    )
    codec_args = (
        ["-c", "copy"]
        if stream_copy
        else ["-c:a", "libopus", "-b:a", "64k", "-application", "voip"]
    )
    command = [
        ffmpeg_path,
        "-y",
        "-nostdin",
        "-hide_banner",
        "-loglevel",
        "error",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(concat_path),
        *codec_args,
        str(output_path),
    ]
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=FFMPEG_CONCAT_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        output = _subprocess_timeout_output(exc)
        raise RuntimeError(
            f"ffmpeg concat timed out after {FFMPEG_CONCAT_TIMEOUT_SECONDS} seconds"
            f"{output}"
        ) from exc
    if completed.returncode != 0:
        stderr = completed.stderr.strip()
        raise RuntimeError(f"ffmpeg concat failed: {stderr or completed.returncode}")


def _run_ffmpeg_remux(
    ffmpeg_path: str,
    input_path: Path,
    output_path: Path,
    *,
    stream_copy: bool,
) -> None:
    """Run ffmpeg for a single-file container remux."""
    codec_args = (
        ["-c", "copy"]
        if stream_copy
        else ["-c:a", "libopus", "-b:a", "64k", "-application", "voip"]
    )
    command = [
        ffmpeg_path,
        "-y",
        "-nostdin",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        str(input_path),
        *codec_args,
        str(output_path),
    ]
    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=FFMPEG_CONCAT_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        output = _subprocess_timeout_output(exc)
        raise RuntimeError(
            f"ffmpeg remux timed out after {FFMPEG_CONCAT_TIMEOUT_SECONDS} seconds"
            f"{output}"
        ) from exc
    if completed.returncode != 0:
        stderr = completed.stderr.strip()
        raise RuntimeError(f"ffmpeg remux failed: {stderr or completed.returncode}")


def _subprocess_timeout_output(exc: subprocess.TimeoutExpired) -> str:
    """Format captured subprocess output for timeout errors."""
    output_parts: list[str] = []
    if exc.stdout:
        stdout = exc.stdout.decode() if isinstance(exc.stdout, bytes) else exc.stdout
        output_parts.append(f"stdout={stdout.strip()}")
    if exc.stderr:
        stderr = exc.stderr.decode() if isinstance(exc.stderr, bytes) else exc.stderr
        output_parts.append(f"stderr={stderr.strip()}")
    return f" ({'; '.join(output_parts)})" if output_parts else ""


def _escape_ffmpeg_concat_path(path: Path) -> str:
    """Escape a path for ffmpeg's single-quoted concat demuxer syntax."""
    return path.as_posix().replace("\\", "\\\\").replace("'", "'\\''")


async def _parse_responses_output(
    openai_client: openai.AsyncClient | openai.AsyncAzureOpenAI,
    *,
    model: str,
    instructions: str,
    response_model: type[_ResponseModelT],
    input_messages: ResponseInputParam,
) -> _ResponseModelT:
    for attempt in range(1, OPENAI_GENERATION_MAX_ATTEMPTS + 1):
        try:
            response = await openai_client.responses.parse(
                model=model,
                instructions=instructions,
                input=input_messages,
                text_format=response_model,
                reasoning=Reasoning(effort="medium", summary=None),
                store=False,
            )
            if response.output_parsed is None:
                raise RuntimeError("OpenAI Responses parse returned no parsed output.")
            return cast(_ResponseModelT, response.output_parsed)
        except Exception as exc:
            if (
                attempt >= OPENAI_GENERATION_MAX_ATTEMPTS
                or not _is_retryable_openai_generation_error(exc)
            ):
                raise
            delay_seconds = OPENAI_GENERATION_RETRY_DELAY_SECONDS * attempt
            logger.warning(
                "Retrying OpenAI Responses generation after transient failure. "
                "attempt=%s max_attempts=%s delay_seconds=%.1f error=%s",
                attempt,
                OPENAI_GENERATION_MAX_ATTEMPTS,
                delay_seconds,
                exc,
            )
            await asyncio.sleep(delay_seconds)
    raise RuntimeError("OpenAI Responses retry loop exited unexpectedly.")


def transcript_data_from_words(
    words: list[schemas.LectureVideoManifestWordV3],
) -> dict[str, Any]:
    return {
        "version": TRANSCRIPT_DATA_VERSION,
        "word_level_transcription": [word.model_dump() for word in words],
    }


def text_needs_audio(text: str) -> bool:
    return bool(text.strip())


def audio_duration_ms(audio: bytes, content_type: str | None = None) -> int:
    try:
        segment = AudioSegment.from_file(io.BytesIO(audio))
        return int(len(segment))
    except Exception:
        logger.warning(
            "Unable to determine lecture slide audio duration from content_type=%s; using 0.",
            content_type,
            exc_info=True,
        )
        return 0


def _seconds_to_ms(value: _TranscriptionWordValue) -> int:
    return max(0, int(round(float(value) * 1000)))


def _get_attr_or_key(
    value: TranscriptionWord | Mapping[str, object],
    key: _TranscriptionWordField,
) -> _TranscriptionWordValue | None:
    raw_value = value.get(key) if isinstance(value, Mapping) else getattr(value, key)
    if isinstance(raw_value, str | int | float):
        return raw_value
    return None


def generate_slide_image_store_key() -> str:
    return f"ls_page_{uuid.uuid7()}.png"


def generate_slide_narration_store_key() -> str:
    return f"ls_narration_{uuid.uuid7()}.ogg"


def generate_slide_continuous_narration_store_key() -> str:
    return f"ls_continuous_narration_{uuid.uuid7()}.webm"


def generate_slide_caption_store_key() -> str:
    return f"ls_caption_{uuid.uuid7()}.vtt"


async def _delete_audio_key_quietly(key: str) -> None:
    if not config.lecture_video_audio_store:
        return
    try:
        await config.lecture_video_audio_store.store.delete_file(key)
    except Exception:
        logger.exception("Failed to clean up lecture slide audio key=%s", key)


def _user_safe_processing_error_message(exc: Exception) -> str:
    if isinstance(
        exc,
        (
            ClassCredentialValidationSSLError,
            ClassCredentialValidationUnavailableError,
            ClassCredentialVoiceValidationError,
        ),
    ):
        return "Unable to synthesize lecture slide narration audio right now. Please retry."
    return "Unable to process the lecture slide deck right now. Please retry."
