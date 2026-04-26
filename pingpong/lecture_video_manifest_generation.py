import asyncio
import json
import logging
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import openai
from google.genai.client import AsyncClient
from google.genai import types
from pydantic import BaseModel, ConfigDict, Field

import pingpong.schemas as schemas
from pingpong import gemini as gemini_helpers
from pingpong.transcription import _prepare_audio_file_for_transcription_async

logger = logging.getLogger(__name__)

DEFAULT_LECTURE_VIDEO_INSTRUCTIONS = """You are a friendly, clear tutor helping a learner during an interactive video lesson.

Your responses will be **spoken aloud**, so they must sound natural, simple, and easy to follow.

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

**1. Be clear and easy to follow**

* Use plain language and match the level of the lecture
* Avoid jargon, or define it briefly the first time it appears

**2. Keep it short and focused**

* Answer as directly as possible
* One or two key ideas is usually enough

**3. Make it sound natural when spoken**

* Write like you're talking, not like a textbook
* Read symbols and notation aloud (e.g. "x squared", "one over two") rather than using characters
* Avoid long or complex sentences

**4. Use the lecture context when helpful**

* Ground your answer in what the lecturer just said (Recent Transcript) and what's on screen (Relevant Video Descriptions)
  (e.g., "In the example the lecturer just worked through…")
* Don't reference offsets, milliseconds, or section names from the developer message — translate them into natural phrases like "just now" or "in a moment"

**5. Respect the upcoming Knowledge Check**

* If the question is heading toward an Upcoming Knowledge Check, help them think — don't give away the answer
* If they're asking after answering one (Status says *Just answered Knowledge Check #N*), build on the feedback they already saw

**6. Prioritise helping over completeness**

* Give the simplest explanation that moves the learner forward
* Don't unfold long derivations or background unless asked

**7. If the question is unclear or off-track**

* Gently steer back, or ask one brief clarifying question
* Don't guess wildly

**8. Default to direct answers**

* Only ask a question back if it's needed to help them

**9. Keep the tone of a friendly teacher**

* Supportive, calm, and encouraging
* Not overly excited or overly formal

---

### Output

Respond with **only the answer**, written as a short, spoken explanation."""

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

_GEMINI_MODEL = "gemini-3.1-pro"


@dataclass(frozen=True)
class GeminiFileRef:
    name: str
    uri: str | None = None
    mime_type: str | None = None


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


def _timestamp_to_ms(value: float | int) -> int:
    return int(round(float(value) * 1000))


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


async def transcribe_video_words(
    video_path: str,
    openai_client: openai.AsyncClient | openai.AsyncAzureOpenAI,
    *,
    temp_dir: str,
) -> list[schemas.LectureVideoManifestWordV3]:
    path_to_send, speed_factor, _ = await _prepare_audio_file_for_transcription_async(
        input_path=video_path,
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
    if speed_factor > 1.0:
        for word in manifest_words:
            word["start_offset_ms"] = _timestamp_to_ms(
                word["start_offset_ms"] * speed_factor / 1000
            )
            word["end_offset_ms"] = _timestamp_to_ms(
                word["end_offset_ms"] * speed_factor / 1000
            )
    return [
        schemas.LectureVideoManifestWordV3.model_validate(word)
        for word in manifest_words
    ]


async def _ffprobe_duration_ms(video_path: str) -> int | None:
    def run_ffprobe() -> int | None:
        try:
            result = subprocess.run(
                [
                    "ffprobe",
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
            )
        except Exception:
            logger.warning("Failed to determine lecture video duration.", exc_info=True)
            return None
        return _timestamp_to_ms(float(result.stdout.strip()))

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


def build_generation_prompt(
    content_section: str,
    transcript: list[schemas.LectureVideoManifestWordV3],
    *,
    compact: bool = False,
    video_duration_ms: int | None = None,
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

    return f"""You are an expert educational content designer specializing in interactive video lessons. You speak as the teacher in first person, directly to the student.

You will be given a lecture video and a word-level transcript. {transcript_description}{duration_text}

Here's the WORD-LEVEL TRANSCRIPT:
{transcript_text}

TO-DO's FOR SUCCESSFUL QUIZ-GENERATION:
To ensure high confidence in analyzing the lesson, watch the video along with the transcript. Don't make up anything or assume based on your preconceived idea of the lecture - always remember you have the transcript.

YOUR TASK:
Analyze the provided lesson materials to identify natural pause points where a multiple-choice comprehension check can be inserted. At each pause point, the video will stop, a question will be displayed as text on screen, and a voice clone of the teacher will introduce the question out loud. After the student selects an answer, the voice clone will give spoken feedback, and the video will resume. The resume point may differ depending on which answer the student chose.

Also create a top-level "video_descriptions" array that describes what is visibly happening in fixed 30-second windows across the whole video.

VISUAL DESCRIPTION GUIDELINES:
- Use consecutive millisecond ranges starting at 0: 0-30000, 30000-60000, 60000-90000, and so on through the full video.
- Every segment except the final segment must be exactly 30 seconds long.
- The final segment must end exactly at the video duration. It may be shorter than 30 seconds. Never set the final end_offset_ms after the end of the video.
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
- The top-level "video_descriptions" array is REQUIRED for video-based generation. It must be non-empty and must use contiguous millisecond windows starting at 0. The final segment must end exactly at the video duration, not after it.

REDUNDANCY CHECK:
- Before finalizing each voice_over, read it concatenated with the teacher's words starting at the resume point. If any fact, number, or concept appears in both your feedback AND the teacher's next sentence, remove it from your feedback. The combined audio must never say the same thing twice.

Now analyze the provided lesson materials and generate the interactive question layer.

"""


def _is_context_limit_error(exc: Exception) -> bool:
    return (
        "input token count exceeds the maximum number of tokens allowed"
        in str(exc).lower()
    )


def _question_to_manifest_question(
    question: GeneratedQuestion,
) -> schemas.LectureVideoManifestQuestionV1:
    choices = question.choices
    feedback_by_choice = question.choice_feedback
    correct_answer = question.correct_answer

    options = []
    correct_count = 0
    for choice in choices:
        choice_text = choice.text
        feedback = feedback_by_choice[choice_text]
        is_correct = choice_text == correct_answer
        correct_count += 1 if is_correct else 0
        options.append(
            schemas.LectureVideoManifestQuestionV1(
                option_text=choice_text,
                post_answer_text=feedback.voice_over,
                continue_offset_ms=_timestamp_to_ms(feedback.resume_at),
                correct=is_correct,
            )
        )
    if correct_count != 1:
        raise ValueError("Generated question must have exactly one correct answer.")
    return schemas.LectureVideoManifestQuestionV1(
        type=schemas.LectureVideoQuestionType.SINGLE_SELECT,
        question_text=question.question_text,
        intro_text=question.voice_over_intro,
        stop_offset_ms=_timestamp_to_ms(question.pause_at),
        options=options,
    )


def _fallback_video_descriptions(
    video_duration_ms: int | None,
) -> list[schemas.LectureVideoManifestVideoDescriptionV3]:
    end_offset_ms = max(video_duration_ms or 1, 1)
    return [
        schemas.LectureVideoManifestVideoDescriptionV3(
            start_offset_ms=0,
            end_offset_ms=end_offset_ms,
            description="Visual descriptions were unavailable for this transcript-only generation pass.",
        )
    ]


def _quiz_to_manifest(
    quiz: GeneratedQuizWithVideo,
    transcript: list[schemas.LectureVideoManifestWordV3],
    *,
    video_duration_ms: int | None,
) -> schemas.LectureVideoManifestV3:
    video_descriptions = quiz.video_descriptions
    if len(video_descriptions) == 0:
        video_descriptions = _fallback_video_descriptions(video_duration_ms)
    return schemas.LectureVideoManifestV3(
        word_level_transcription=transcript,
        video_descriptions=video_descriptions,
        questions=[
            _question_to_manifest_question(question) for question in quiz.questions
        ],
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
    prompt = build_generation_prompt(
        generation_prompt_content,
        transcript,
        video_duration_ms=video_duration_ms,
    )
    contents: types.ContentListUnion = [
        await gemini_client.files.get(name=gemini_file.name)
    ]
    try:
        quiz = await gemini_helpers.generate_manifest_quiz(
            gemini_client,
            model=model,
            prompt=prompt,
            contents=contents,
            response_model=GeneratedQuizWithVideo,
        )
    except Exception as exc:
        if not _is_context_limit_error(exc):
            raise
        compact_prompt = build_generation_prompt(
            generation_prompt_content,
            transcript,
            compact=True,
            video_duration_ms=video_duration_ms,
        )
        quiz = await gemini_helpers.generate_manifest_quiz(
            gemini_client,
            model=model,
            prompt=compact_prompt,
            contents=contents,
            response_model=GeneratedQuizWithVideo,
        )
    return _quiz_to_manifest(quiz, transcript, video_duration_ms=video_duration_ms)


def video_suffix_for_content_type(content_type: str | None) -> str:
    if content_type == "video/webm":
        return ".webm"
    suffix = Path(str(content_type or "")).suffix
    return suffix or ".mp4"
