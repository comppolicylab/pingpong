import shutil
import subprocess
from types import SimpleNamespace
from typing import cast

from google.genai import types
import pytest

import pingpong.lecture_video_manifest_generation as manifest_generation
import pingpong.schemas as schemas


def _generated_question() -> manifest_generation.GeneratedQuestion:
    return manifest_generation.GeneratedQuestion(
        id=1,
        question_source="generated",
        pause_after_word_id="w1",
        pause_after_word="expression",
        pause_at=1.0,
        voice_over_intro="Try this.",
        question_text="What should happen next?",
        choices=[
            manifest_generation.GeneratedChoice(
                text="Combine like terms", misconception=None
            ),
            manifest_generation.GeneratedChoice(
                text="Change every variable",
                misconception="Confuses simplification with substitution.",
            ),
        ],
        correct_answer="Combine like terms",
        choice_feedback={
            "Combine like terms": manifest_generation.GeneratedChoiceFeedback(
                voice_over="Right.",
                resume_at_word_id="w2",
                resume_at_word="Next",
                resume_at=1.5,
            ),
            "Change every variable": manifest_generation.GeneratedChoiceFeedback(
                voice_over="Not quite.",
                resume_at_word_id="w2",
                resume_at_word="Next",
                resume_at=1.5,
            ),
        },
    )


def _transcript() -> list[schemas.LectureVideoManifestWordV3]:
    return [
        schemas.LectureVideoManifestWordV3(
            id="w1",
            word="expression",
            start_offset_ms=0,
            end_offset_ms=1000,
        ),
        schemas.LectureVideoManifestWordV3(
            id="w2",
            word="Next",
            start_offset_ms=1500,
            end_offset_ms=2000,
        ),
    ]


def test_prepare_lecture_video_audio_for_whisper_retries_until_under_target(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    sizes_by_bitrate = {"32k": 101, "24k": 90}
    calls: list[list[str]] = []

    monkeypatch.setattr(manifest_generation.shutil, "which", lambda _name: "/ffmpeg")
    monkeypatch.setattr(manifest_generation, "_WHISPER_UPLOAD_TARGET_BYTES", 100)
    monkeypatch.setattr(
        manifest_generation, "_TRANSCRIPTION_AUDIO_BITRATES", ("32k", "24k")
    )

    def fake_run(args: list[str], **_kwargs):
        calls.append(args)
        bitrate = args[args.index("-b:a") + 1]
        output_path = args[-1]
        with open(output_path, "wb") as output_file:
            output_file.write(b"x" * sizes_by_bitrate[bitrate])
        return subprocess.CompletedProcess(args, 0)

    monkeypatch.setattr(manifest_generation.subprocess, "run", fake_run)

    prepared_path = manifest_generation._prepare_lecture_video_audio_for_whisper(
        video_path="/tmp/lecture.mp4",
        temp_dir=str(tmp_path),
    )

    assert prepared_path.endswith("lecture-video-transcription-24k.webm")
    assert [call[call.index("-b:a") + 1] for call in calls] == ["32k", "24k"]
    assert not (tmp_path / "lecture-video-transcription-32k.webm").exists()
    assert (tmp_path / "lecture-video-transcription-24k.webm").stat().st_size == 90


def test_prepare_lecture_video_audio_for_whisper_accepts_under_hard_limit(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    sizes_by_bitrate = {"32k": 104, "24k": 103}

    monkeypatch.setattr(manifest_generation.shutil, "which", lambda _name: "/ffmpeg")
    monkeypatch.setattr(manifest_generation, "_WHISPER_UPLOAD_TARGET_BYTES", 100)
    monkeypatch.setattr(manifest_generation, "_WHISPER_UPLOAD_MAX_BYTES", 105)
    monkeypatch.setattr(
        manifest_generation, "_TRANSCRIPTION_AUDIO_BITRATES", ("32k", "24k")
    )

    def fake_run(args: list[str], **_kwargs):
        bitrate = args[args.index("-b:a") + 1]
        output_path = args[-1]
        with open(output_path, "wb") as output_file:
            output_file.write(b"x" * sizes_by_bitrate[bitrate])
        return subprocess.CompletedProcess(args, 0)

    monkeypatch.setattr(manifest_generation.subprocess, "run", fake_run)

    prepared_path = manifest_generation._prepare_lecture_video_audio_for_whisper(
        video_path="/tmp/lecture.mp4",
        temp_dir=str(tmp_path),
    )

    assert prepared_path.endswith("lecture-video-transcription-24k.webm")
    assert not (tmp_path / "lecture-video-transcription-32k.webm").exists()
    assert (tmp_path / "lecture-video-transcription-24k.webm").stat().st_size == 103


@pytest.mark.asyncio
async def test_transcribe_video_words_uses_prepared_audio_without_timestamp_rescale(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    prepared_audio_path = tmp_path / "prepared.webm"
    prepared_audio_path.write_bytes(b"audio")
    calls: list[dict] = []

    async def fake_prepare(*, video_path: str, temp_dir: str) -> str:
        assert video_path == "/tmp/lecture.mp4"
        assert temp_dir == str(tmp_path)
        return str(prepared_audio_path)

    class FakeTranscriptions:
        async def create(self, **kwargs):
            calls.append(kwargs)
            assert kwargs["file"].name == str(prepared_audio_path)
            return SimpleNamespace(
                words=[
                    SimpleNamespace(
                        id="w1",
                        word="Hello",
                        start=1.25,
                        end=2.5,
                    )
                ]
            )

    fake_client = SimpleNamespace(
        audio=SimpleNamespace(transcriptions=FakeTranscriptions())
    )
    monkeypatch.setattr(
        manifest_generation,
        "_prepare_lecture_video_audio_for_whisper_async",
        fake_prepare,
    )

    words = await manifest_generation.transcribe_video_words(
        "/tmp/lecture.mp4",
        fake_client,
        temp_dir=str(tmp_path),
    )

    assert calls[0]["model"] == "whisper-1"
    assert words == [
        schemas.LectureVideoManifestWordV3(
            id="w1",
            word="Hello",
            start_offset_ms=1250,
            end_offset_ms=2500,
        )
    ]


@pytest.mark.asyncio
async def test_transcribe_video_words_skips_empty_words_with_context_warning(
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    prepared_audio_path = tmp_path / "prepared.webm"
    prepared_audio_path.write_bytes(b"audio")

    async def fake_prepare(*, video_path: str, temp_dir: str) -> str:
        return str(prepared_audio_path)

    class FakeTranscriptions:
        async def create(self, **_kwargs):
            return SimpleNamespace(
                words=[
                    SimpleNamespace(id="w1", word="Fifteen", start=1.0, end=1.2),
                    SimpleNamespace(id="w2", word="", start=1.2, end=1.3),
                    SimpleNamespace(id="w3", word="increase", start=1.3, end=1.7),
                ]
            )

    fake_client = SimpleNamespace(
        audio=SimpleNamespace(transcriptions=FakeTranscriptions())
    )
    monkeypatch.setattr(
        manifest_generation,
        "_prepare_lecture_video_audio_for_whisper_async",
        fake_prepare,
    )

    with caplog.at_level("WARNING", logger=manifest_generation.logger.name):
        words = await manifest_generation.transcribe_video_words(
            "/tmp/lecture.mp4",
            fake_client,
            temp_dir=str(tmp_path),
        )

    assert words == [
        schemas.LectureVideoManifestWordV3(
            id="w1",
            word="Fifteen",
            start_offset_ms=1000,
            end_offset_ms=1200,
        ),
        schemas.LectureVideoManifestWordV3(
            id="w3",
            word="increase",
            start_offset_ms=1300,
            end_offset_ms=1700,
        ),
    ]
    assert (
        "Skipping empty OpenAI transcription word. index=1 "
        "start_offset_ms=1200 end_offset_ms=1300 previous_word='Fifteen' "
        "next_word='increase'"
    ) in caplog.text


def _quiz_with_video_descriptions(
    video_descriptions: list[manifest_generation.GeneratedVideoDescription],
) -> manifest_generation.GeneratedQuizWithVideo:
    return manifest_generation.GeneratedQuizWithVideo(
        video_summary="A short algebra lesson.",
        video_descriptions=video_descriptions,
        questions=[_generated_question()],
    )


def test_quiz_to_manifest_converts_generated_video_descriptions() -> None:
    quiz = _quiz_with_video_descriptions(
        [
            manifest_generation.GeneratedVideoDescription(
                start_offset_ms=0,
                end_offset_ms=30000,
                description="The teacher writes an expression on the board.",
            )
        ]
    )

    manifest = manifest_generation._quiz_to_manifest(
        quiz,
        _transcript(),
        video_duration_ms=30000,
    )

    assert isinstance(
        manifest.video_descriptions[0],
        schemas.LectureVideoManifestVideoDescriptionV3,
    )
    assert manifest.video_descriptions[0].description == (
        "The teacher writes an expression on the board."
    )


@pytest.mark.parametrize(
    ("video_descriptions", "video_duration_ms", "expected_log"),
    [
        (
            [
                manifest_generation.GeneratedVideoDescription(
                    start_offset_ms=1000,
                    end_offset_ms=30000,
                    description="The teacher writes on the board.",
                )
            ],
            30000,
            "starts at 1000ms; expected 0ms",
        ),
        (
            [
                manifest_generation.GeneratedVideoDescription(
                    start_offset_ms=0,
                    end_offset_ms=30000,
                    description="The teacher writes on the board.",
                ),
                manifest_generation.GeneratedVideoDescription(
                    start_offset_ms=31000,
                    end_offset_ms=60000,
                    description="The teacher points at the board.",
                ),
            ],
            60000,
            "starts at 31000ms; expected 30000ms",
        ),
        (
            [
                manifest_generation.GeneratedVideoDescription(
                    start_offset_ms=0,
                    end_offset_ms=31000,
                    description="The teacher writes on the board.",
                ),
                manifest_generation.GeneratedVideoDescription(
                    start_offset_ms=31000,
                    end_offset_ms=60000,
                    description="The teacher points at the board.",
                ),
            ],
            60000,
            "duration is 31000ms; expected 30000ms",
        ),
        (
            [
                manifest_generation.GeneratedVideoDescription(
                    start_offset_ms=0,
                    end_offset_ms=30000,
                    description="The teacher writes on the board.",
                )
            ],
            45000,
            "final video description ends at 30000ms; expected video duration 45000ms",
        ),
        (
            [
                manifest_generation.GeneratedVideoDescription(
                    start_offset_ms=0,
                    end_offset_ms=45000,
                    description="The teacher writes on the board.",
                )
            ],
            45000,
            "final video description duration is 45000ms; expected at most 30000ms",
        ),
    ],
)
def test_quiz_to_manifest_falls_back_for_invalid_video_description_structure(
    caplog,
    video_descriptions: list[manifest_generation.GeneratedVideoDescription],
    video_duration_ms: int,
    expected_log: str,
) -> None:
    quiz = _quiz_with_video_descriptions(video_descriptions)

    with caplog.at_level("WARNING"):
        manifest = manifest_generation._quiz_to_manifest(
            quiz,
            _transcript(),
            video_duration_ms=video_duration_ms,
        )

    assert (
        manifest.video_descriptions
        == manifest_generation._fallback_video_descriptions(video_duration_ms)
    )
    assert expected_log in caplog.text


def test_quiz_to_manifest_accepts_final_video_description_shorter_than_window() -> None:
    quiz = _quiz_with_video_descriptions(
        [
            manifest_generation.GeneratedVideoDescription(
                start_offset_ms=0,
                end_offset_ms=30000,
                description="The teacher writes on the board.",
            ),
            manifest_generation.GeneratedVideoDescription(
                start_offset_ms=30000,
                end_offset_ms=45000,
                description="The teacher points at the board.",
            ),
        ]
    )

    manifest = manifest_generation._quiz_to_manifest(
        quiz,
        _transcript(),
        video_duration_ms=45000,
    )

    assert [
        description.end_offset_ms for description in manifest.video_descriptions
    ] == [
        30000,
        45000,
    ]


def test_plan_manifest_generation_chunks_rebalances_short_tail() -> None:
    chunks = manifest_generation._plan_manifest_generation_chunks(3_664_600)

    assert [
        (chunk.generation_start_ms, chunk.generation_end_ms) for chunk in chunks
    ] == [
        (0, 300_000),
        (300_000, 600_000),
        (600_000, 900_000),
        (900_000, 1_200_000),
        (1_200_000, 1_500_000),
        (1_500_000, 1_800_000),
        (1_800_000, 2_100_000),
        (2_100_000, 2_400_000),
        (2_400_000, 2_700_000),
        (2_700_000, 3_000_000),
        (3_000_000, 3_300_000),
        (3_300_000, 3_480_000),
        (3_480_000, 3_664_600),
    ]
    assert [(chunk.context_start_ms, chunk.context_end_ms) for chunk in chunks] == [
        (0, 330_000),
        (270_000, 630_000),
        (570_000, 930_000),
        (870_000, 1_230_000),
        (1_170_000, 1_530_000),
        (1_470_000, 1_830_000),
        (1_770_000, 2_130_000),
        (2_070_000, 2_430_000),
        (2_370_000, 2_730_000),
        (2_670_000, 3_030_000),
        (2_970_000, 3_330_000),
        (3_270_000, 3_510_000),
        (3_450_000, 3_664_600),
    ]


def test_plan_manifest_generation_chunks_uses_single_chunk_under_limit() -> None:
    chunks = manifest_generation._plan_manifest_generation_chunks(240_000)

    assert chunks == [
        manifest_generation.ManifestGenerationChunk(
            generation_start_ms=0,
            generation_end_ms=240_000,
            context_start_ms=0,
            context_end_ms=240_000,
        )
    ]


def test_split_manifest_generation_chunk_adds_context_overlap() -> None:
    chunks = manifest_generation._split_manifest_generation_chunk(
        manifest_generation.ManifestGenerationChunk(
            generation_start_ms=1_200_000,
            generation_end_ms=2_400_000,
            context_start_ms=1_170_000,
            context_end_ms=2_430_000,
        ),
        video_duration_ms=3_000_000,
    )

    assert [
        (chunk.generation_start_ms, chunk.generation_end_ms) for chunk in chunks
    ] == [
        (1_200_000, 1_800_000),
        (1_800_000, 2_400_000),
    ]
    assert [(chunk.context_start_ms, chunk.context_end_ms) for chunk in chunks] == [
        (1_170_000, 1_830_000),
        (1_770_000, 2_430_000),
    ]


def test_should_split_manifest_chunk_error_accepts_provider_deadline() -> None:
    exc = RuntimeError(
        "503 UNAVAILABLE. Deadline expired before operation could complete."
    )

    assert manifest_generation._should_split_manifest_chunk_error(exc)


async def test_generate_manifest_quiz_with_retries_handles_transient_provider_error(
    monkeypatch,
) -> None:
    calls = 0
    sleeps: list[float] = []

    async def fake_generate_manifest_quiz(
        _client,
        *,
        model,
        prompt,
        contents,
        response_model,
    ):  # type: ignore[no-untyped-def]
        nonlocal calls
        calls += 1
        if calls < 3:
            raise RuntimeError("500 INTERNAL. Internal error encountered.")
        return response_model(questions=[_generated_question()])

    async def fake_sleep(delay_seconds: float) -> None:
        sleeps.append(delay_seconds)

    monkeypatch.setattr(
        manifest_generation.gemini_helpers,
        "generate_manifest_quiz",
        fake_generate_manifest_quiz,
    )
    monkeypatch.setattr(manifest_generation.asyncio, "sleep", fake_sleep)

    quiz = await manifest_generation._generate_manifest_quiz_with_retries(
        object(),  # type: ignore[arg-type]
        model="gemini-test",
        prompt="reconcile",
        contents=[],
        response_model=manifest_generation.ReconciledGeneratedQuiz,
        request_label="test",
    )

    assert calls == 3
    assert sleeps == [5.0, 10.0]
    assert quiz.questions[0].question_text == "What should happen next?"


def test_transcript_for_window_includes_context_overlap_words() -> None:
    transcript = [
        schemas.LectureVideoManifestWordV3(
            id="before",
            word="before",
            start_offset_ms=990,
            end_offset_ms=1000,
        ),
        schemas.LectureVideoManifestWordV3(
            id="inside",
            word="inside",
            start_offset_ms=1500,
            end_offset_ms=1600,
        ),
        schemas.LectureVideoManifestWordV3(
            id="after",
            word="after",
            start_offset_ms=2500,
            end_offset_ms=2600,
        ),
    ]

    window = manifest_generation._transcript_for_window(
        transcript,
        start_offset_ms=1000,
        end_offset_ms=2500,
    )

    assert [word.id for word in window] == ["before", "inside", "after"]


async def test_merge_chunk_manifests_reconciles_questions_with_gemini(
    monkeypatch,
) -> None:
    captured: dict[str, object] = {}
    chunk_one = schemas.LectureVideoManifestV3(
        word_level_transcription=_transcript(),
        video_descriptions=[
            schemas.LectureVideoManifestVideoDescriptionV3(
                start_offset_ms=0,
                end_offset_ms=30000,
                description="The teacher writes an expression.",
            )
        ],
        questions=[
            schemas.LectureVideoManifestQuestionV1(
                type=schemas.LectureVideoQuestionType.SINGLE_SELECT,
                question_text="Candidate one?",
                intro_text="Try this.",
                stop_offset_ms=1000,
                options=[
                    schemas.LectureVideoManifestOptionV1(
                        option_text="Combine like terms",
                        post_answer_text="Right.",
                        continue_offset_ms=1500,
                        correct=True,
                    ),
                    schemas.LectureVideoManifestOptionV1(
                        option_text="Change every variable",
                        post_answer_text="Not quite.",
                        continue_offset_ms=1500,
                        correct=False,
                    ),
                ],
            )
        ],
    )
    chunk_two = schemas.LectureVideoManifestV3(
        word_level_transcription=_transcript(),
        video_descriptions=[
            schemas.LectureVideoManifestVideoDescriptionV3(
                start_offset_ms=30000,
                end_offset_ms=60000,
                description="The teacher points at the next step.",
            )
        ],
        questions=[
            schemas.LectureVideoManifestQuestionV1(
                type=schemas.LectureVideoQuestionType.SINGLE_SELECT,
                question_text="Candidate two?",
                intro_text="Try this too.",
                stop_offset_ms=1000,
                options=[
                    schemas.LectureVideoManifestOptionV1(
                        option_text="Combine like terms",
                        post_answer_text="Right.",
                        continue_offset_ms=1500,
                        correct=True,
                    ),
                    schemas.LectureVideoManifestOptionV1(
                        option_text="Change every variable",
                        post_answer_text="Not quite.",
                        continue_offset_ms=1500,
                        correct=False,
                    ),
                ],
            )
        ],
    )

    async def fake_generate_manifest_quiz(
        _client,
        *,
        model,
        prompt,
        contents,
        response_model,
    ):  # type: ignore[no-untyped-def]
        captured["model"] = model
        captured["prompt"] = prompt
        captured["contents"] = contents
        captured["response_model"] = response_model
        return manifest_generation.ReconciledGeneratedQuiz(
            questions=[
                manifest_generation.GeneratedQuestion(
                    **{
                        **_generated_question().model_dump(),
                        "question_text": "Final reconciled question?",
                    }
                )
            ]
        )

    monkeypatch.setattr(
        manifest_generation.gemini_helpers,
        "generate_manifest_quiz",
        fake_generate_manifest_quiz,
    )

    manifest = await manifest_generation._merge_chunk_manifests(
        gemini_client=object(),  # type: ignore[arg-type]
        generation_prompt_content="Ask only 1 question.",
        model="gemini-test",
        chunk_manifests=[chunk_one, chunk_two],
        full_transcript=_transcript(),
        video_duration_ms=60000,
    )

    assert captured["response_model"] is manifest_generation.ReconciledGeneratedQuiz
    assert "Ask only 1 question." in str(captured["prompt"])
    contents = cast(list[types.Part], captured["contents"])
    payload = contents[0].text
    assert payload is not None
    assert '"Candidate one?"' in payload
    assert '"Candidate two?"' in payload
    assert [question.question_text for question in manifest.questions] == [
        "Final reconciled question?"
    ]
    assert [
        description.end_offset_ms for description in manifest.video_descriptions
    ] == [30000, 60000]


async def test_merge_chunk_manifests_falls_back_only_for_invalid_chunk(
    monkeypatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    candidate_question = schemas.LectureVideoManifestQuestionV1(
        type=schemas.LectureVideoQuestionType.SINGLE_SELECT,
        question_text="Candidate?",
        intro_text="Try this.",
        stop_offset_ms=1000,
        options=[
            schemas.LectureVideoManifestOptionV1(
                option_text="Combine like terms",
                post_answer_text="Right.",
                continue_offset_ms=1500,
                correct=True,
            ),
            schemas.LectureVideoManifestOptionV1(
                option_text="Change every variable",
                post_answer_text="Not quite.",
                continue_offset_ms=1500,
                correct=False,
            ),
        ],
    )
    chunk_one = schemas.LectureVideoManifestV3(
        word_level_transcription=_transcript(),
        video_descriptions=[
            schemas.LectureVideoManifestVideoDescriptionV3(
                start_offset_ms=0,
                end_offset_ms=30000,
                description="The teacher writes an expression.",
            )
        ],
        questions=[candidate_question],
    )
    chunk_two = schemas.LectureVideoManifestV3(
        word_level_transcription=_transcript(),
        video_descriptions=[
            schemas.LectureVideoManifestVideoDescriptionV3(
                start_offset_ms=31000,
                end_offset_ms=60000,
                description="The teacher points at the next step.",
            )
        ],
        questions=[candidate_question],
    )

    async def fake_generate_manifest_quiz(
        _client,
        *,
        model,
        prompt,
        contents,
        response_model,
    ):  # type: ignore[no-untyped-def]
        return manifest_generation.ReconciledGeneratedQuiz(
            questions=[_generated_question()]
        )

    monkeypatch.setattr(
        manifest_generation.gemini_helpers,
        "generate_manifest_quiz",
        fake_generate_manifest_quiz,
    )

    with caplog.at_level("WARNING", logger=manifest_generation.logger.name):
        manifest = await manifest_generation._merge_chunk_manifests(
            gemini_client=object(),  # type: ignore[arg-type]
            generation_prompt_content="Ask only 1 question.",
            model="gemini-test",
            chunk_manifests=[chunk_one, chunk_two],
            full_transcript=_transcript(),
            video_duration_ms=60000,
        )

    assert [
        description.start_offset_ms for description in manifest.video_descriptions
    ] == [
        0,
        30000,
    ]
    assert [
        description.end_offset_ms for description in manifest.video_descriptions
    ] == [
        30000,
        60000,
    ]
    assert manifest.video_descriptions[0].description == (
        "The teacher writes an expression."
    )
    assert manifest.video_descriptions[1].description == (
        "Visual descriptions were unavailable for this transcript-only generation pass."
    )
    assert "Falling back for this chunk only" in caplog.text


def test_quiz_to_manifest_reports_missing_choice_feedback() -> None:
    quiz = manifest_generation.GeneratedQuizWithVideo(
        video_summary="A short algebra lesson.",
        video_descriptions=[
            manifest_generation.GeneratedVideoDescription(
                start_offset_ms=0,
                end_offset_ms=30000,
                description="The teacher writes an expression on the board.",
            )
        ],
        questions=[
            manifest_generation.GeneratedQuestion(
                id=1,
                question_source="generated",
                pause_after_word_id="w1",
                pause_after_word="expression",
                pause_at=1.0,
                voice_over_intro="Try this.",
                question_text="What should happen next?",
                choices=[
                    manifest_generation.GeneratedChoice(
                        text="Combine like terms", misconception=None
                    ),
                    manifest_generation.GeneratedChoice(
                        text="Change every variable",
                        misconception="Confuses simplification with substitution.",
                    ),
                ],
                correct_answer="Combine like terms",
                choice_feedback={
                    "Combine like terms": manifest_generation.GeneratedChoiceFeedback(
                        voice_over="Right.",
                        resume_at_word_id="w2",
                        resume_at_word="Next",
                        resume_at=1.5,
                    ),
                    "Change every variable ": manifest_generation.GeneratedChoiceFeedback(
                        voice_over="Not quite.",
                        resume_at_word_id="w2",
                        resume_at_word="Next",
                        resume_at=1.5,
                    ),
                },
            )
        ],
    )

    with pytest.raises(ValueError, match="feedback is missing"):
        manifest_generation._quiz_to_manifest(
            quiz,
            [
                schemas.LectureVideoManifestWordV3(
                    id="w1",
                    word="expression",
                    start_offset_ms=0,
                    end_offset_ms=1000,
                ),
                schemas.LectureVideoManifestWordV3(
                    id="w2",
                    word="Next",
                    start_offset_ms=1500,
                    end_offset_ms=2000,
                ),
            ],
            video_duration_ms=30000,
        )


def test_quiz_to_manifest_uses_transcript_timestamps_for_question_offsets() -> None:
    quiz = manifest_generation.GeneratedQuizWithVideo(
        video_summary="A short algebra lesson.",
        video_descriptions=[
            manifest_generation.GeneratedVideoDescription(
                start_offset_ms=0,
                end_offset_ms=30000,
                description="The teacher writes an expression on the board.",
            )
        ],
        questions=[
            manifest_generation.GeneratedQuestion(
                id=1,
                question_source="generated",
                pause_after_word_id="w1",
                pause_after_word="expression",
                pause_at=1.0,
                voice_over_intro="Try this.",
                question_text="What should happen next?",
                choices=[
                    manifest_generation.GeneratedChoice(
                        text="Combine like terms", misconception=None
                    ),
                    manifest_generation.GeneratedChoice(
                        text="Change every variable",
                        misconception="Confuses simplification with substitution.",
                    ),
                ],
                correct_answer="Combine like terms",
                choice_feedback={
                    "Combine like terms": manifest_generation.GeneratedChoiceFeedback(
                        voice_over="Right.",
                        resume_at_word_id="w2",
                        resume_at_word="Next",
                        resume_at=1.5,
                    ),
                    "Change every variable": manifest_generation.GeneratedChoiceFeedback(
                        voice_over="Not quite.",
                        resume_at_word_id="w2",
                        resume_at_word="Next",
                        resume_at=1.5,
                    ),
                },
            )
        ],
    )

    manifest = manifest_generation._quiz_to_manifest(
        quiz,
        [
            schemas.LectureVideoManifestWordV3(
                id="w1",
                word="expression",
                start_offset_ms=100,
                end_offset_ms=1000,
            ),
            schemas.LectureVideoManifestWordV3(
                id="w2",
                word="Next",
                start_offset_ms=1500,
                end_offset_ms=2000,
            ),
        ],
        video_duration_ms=30000,
    )

    question = manifest.questions[0]
    assert question.stop_offset_ms == 1000
    assert [option.continue_offset_ms for option in question.options] == [1500, 1500]


def test_quiz_to_manifest_ignores_mismatched_model_timestamp(
    caplog: pytest.LogCaptureFixture,
) -> None:
    quiz = manifest_generation.GeneratedQuizWithVideo(
        video_summary="A short algebra lesson.",
        video_descriptions=[
            manifest_generation.GeneratedVideoDescription(
                start_offset_ms=0,
                end_offset_ms=30000,
                description="The teacher writes an expression on the board.",
            )
        ],
        questions=[
            manifest_generation.GeneratedQuestion(
                id=1,
                question_source="generated",
                pause_after_word_id="w1",
                pause_after_word="expression",
                pause_at=1.1,
                voice_over_intro="Try this.",
                question_text="What should happen next?",
                choices=[
                    manifest_generation.GeneratedChoice(
                        text="Combine like terms", misconception=None
                    ),
                    manifest_generation.GeneratedChoice(
                        text="Change every variable",
                        misconception="Confuses simplification with substitution.",
                    ),
                ],
                correct_answer="Combine like terms",
                choice_feedback={
                    "Combine like terms": manifest_generation.GeneratedChoiceFeedback(
                        voice_over="Right.",
                        resume_at_word_id="w2",
                        resume_at_word="Next",
                        resume_at=1.5,
                    ),
                    "Change every variable": manifest_generation.GeneratedChoiceFeedback(
                        voice_over="Not quite.",
                        resume_at_word_id="w2",
                        resume_at_word="Next",
                        resume_at=1.5,
                    ),
                },
            )
        ],
    )

    with caplog.at_level("WARNING", logger=manifest_generation.logger.name):
        manifest = manifest_generation._quiz_to_manifest(
            quiz,
            [
                schemas.LectureVideoManifestWordV3(
                    id="w1",
                    word="expression",
                    start_offset_ms=100,
                    end_offset_ms=1000,
                ),
                schemas.LectureVideoManifestWordV3(
                    id="w2",
                    word="Next",
                    start_offset_ms=1500,
                    end_offset_ms=2000,
                ),
            ],
            video_duration_ms=30000,
        )

    assert manifest.questions[0].stop_offset_ms == 1000
    assert "matched transcript with one mismatched field" in caplog.text


def test_quiz_to_manifest_accepts_word_and_timestamp_when_id_is_wrong(
    caplog: pytest.LogCaptureFixture,
) -> None:
    question = _generated_question()
    question.pause_after_word_id = "wrong-id"
    question.pause_at = 1.0
    quiz = _quiz_with_video_descriptions(
        [
            manifest_generation.GeneratedVideoDescription(
                start_offset_ms=0,
                end_offset_ms=30000,
                description="The teacher writes an expression on the board.",
            )
        ]
    )
    quiz.questions = [question]

    with caplog.at_level("WARNING", logger=manifest_generation.logger.name):
        manifest = manifest_generation._quiz_to_manifest(
            quiz,
            _transcript(),
            video_duration_ms=30000,
        )

    assert manifest.questions[0].stop_offset_ms == 1000
    assert "matched transcript with one mismatched field" in caplog.text


def test_quiz_to_manifest_rejects_word_reference_with_fewer_than_two_matches() -> None:
    question = _generated_question()
    question.pause_after_word_id = "wrong-id"
    question.pause_after_word = "wrong-word"
    question.pause_at = 1.0
    quiz = _quiz_with_video_descriptions(
        [
            manifest_generation.GeneratedVideoDescription(
                start_offset_ms=0,
                end_offset_ms=30000,
                description="The teacher writes an expression on the board.",
            )
        ]
    )
    quiz.questions = [question]

    with pytest.raises(ValueError, match="did not match at least two"):
        manifest_generation._quiz_to_manifest(
            quiz,
            _transcript(),
            video_duration_ms=30000,
        )


async def test_ffprobe_duration_ms_logs_missing_binary_once(
    monkeypatch, caplog
) -> None:
    def fake_run(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise FileNotFoundError("ffprobe")

    manifest_generation._log_missing_ffprobe_once.cache_clear()
    monkeypatch.setattr(shutil, "which", lambda _name: None)
    monkeypatch.setattr(subprocess, "run", fake_run)

    with caplog.at_level("WARNING"):
        assert await manifest_generation._ffprobe_duration_ms("lecture.mp4") is None
        assert await manifest_generation._ffprobe_duration_ms("lecture.mp4") is None

    assert caplog.text.count("ffprobe is unavailable") == 1


async def test_ffprobe_duration_ms_returns_none_on_probe_failure(monkeypatch) -> None:
    def fake_run(*args, **kwargs):  # type: ignore[no-untyped-def]
        assert args[0][0] == "/usr/local/bin/ffprobe"
        assert kwargs["timeout"] == 30
        raise subprocess.CalledProcessError(1, args[0], stderr="bad video")

    monkeypatch.setattr(shutil, "which", lambda _name: "/usr/local/bin/ffprobe")
    monkeypatch.setattr(subprocess, "run", fake_run)

    assert await manifest_generation._ffprobe_duration_ms("lecture.mp4") is None


async def test_upload_and_generate_manifest_requires_video_duration(
    monkeypatch,
) -> None:
    async def fake_ffprobe_duration_ms(_video_path: str) -> None:
        return None

    async def fail_upload_video_to_gemini(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise AssertionError("Gemini upload should not run without video duration.")

    monkeypatch.setattr(
        manifest_generation,
        "_ffprobe_duration_ms",
        fake_ffprobe_duration_ms,
    )
    monkeypatch.setattr(
        manifest_generation,
        "upload_video_to_gemini",
        fail_upload_video_to_gemini,
    )

    with pytest.raises(RuntimeError, match="valid video duration"):
        await manifest_generation.upload_and_generate_manifest(
            video_path="lecture.mp4",
            gemini_client=object(),  # type: ignore[arg-type]
            generation_prompt_content="Generate checks.",
            transcript=_transcript(),
            temp_dir="/tmp",
        )


async def test_generate_manifest_uses_uploaded_file_uri_without_refetch(
    monkeypatch,
) -> None:
    class Files:
        async def get(self, *args, **kwargs):  # type: ignore[no-untyped-def]
            raise AssertionError("generate_manifest should not refetch Gemini files")

    class GeminiClient:
        files = Files()

    captured_contents = None

    async def fake_ffprobe_duration_ms(_video_path: str) -> int:
        return 30000

    async def fake_generate_manifest_quiz(
        _client,
        *,
        model,
        prompt,
        contents,
        response_model,
    ):  # type: ignore[no-untyped-def]
        nonlocal captured_contents
        captured_contents = contents
        return response_model(
            video_summary="A short algebra lesson.",
            video_descriptions=[
                manifest_generation.GeneratedVideoDescription(
                    start_offset_ms=0,
                    end_offset_ms=30000,
                    description="The teacher writes an expression on the board.",
                )
            ],
            questions=[
                manifest_generation.GeneratedQuestion(
                    id=1,
                    question_source="generated",
                    pause_after_word_id="w1",
                    pause_after_word="expression",
                    pause_at=1.0,
                    voice_over_intro="Try this.",
                    question_text="What should happen next?",
                    choices=[
                        manifest_generation.GeneratedChoice(
                            text="Combine like terms", misconception=None
                        ),
                        manifest_generation.GeneratedChoice(
                            text="Change every variable",
                            misconception="Confuses simplification with substitution.",
                        ),
                    ],
                    correct_answer="Combine like terms",
                    choice_feedback={
                        "Combine like terms": manifest_generation.GeneratedChoiceFeedback(
                            voice_over="Right.",
                            resume_at_word_id="w2",
                            resume_at_word="Next",
                            resume_at=1.5,
                        ),
                        "Change every variable": manifest_generation.GeneratedChoiceFeedback(
                            voice_over="Not quite.",
                            resume_at_word_id="w2",
                            resume_at_word="Next",
                            resume_at=1.5,
                        ),
                    },
                )
            ],
        )

    monkeypatch.setattr(
        manifest_generation,
        "_ffprobe_duration_ms",
        fake_ffprobe_duration_ms,
    )
    monkeypatch.setattr(
        manifest_generation.gemini_helpers,
        "generate_manifest_quiz",
        fake_generate_manifest_quiz,
    )

    await manifest_generation.generate_manifest(
        video_path="lecture.mp4",
        gemini_client=GeminiClient(),  # type: ignore[arg-type]
        gemini_file=manifest_generation.GeminiFileRef(
            name="files/abc",
            uri="https://generativelanguage.googleapis.com/v1beta/files/abc",
            mime_type="video/mp4",
        ),
        generation_prompt_content="Generate a quiz.",
        transcript=[
            schemas.LectureVideoManifestWordV3(
                id="w1",
                word="expression",
                start_offset_ms=0,
                end_offset_ms=1000,
            ),
            schemas.LectureVideoManifestWordV3(
                id="w2",
                word="Next",
                start_offset_ms=1500,
                end_offset_ms=2000,
            ),
        ],
    )

    assert captured_contents is not None
    file_data = captured_contents[0].file_data
    assert (
        file_data.file_uri
        == "https://generativelanguage.googleapis.com/v1beta/files/abc"
    )
    assert file_data.mime_type == "video/mp4"


async def test_upload_and_generate_whole_manifest_deletes_gemini_upload_on_failure(
    monkeypatch,
) -> None:
    calls: list[tuple[str, object]] = []

    async def fake_upload_video_to_gemini(
        video_path: str,
        _client,
    ) -> manifest_generation.GeminiFileRef:  # type: ignore[no-untyped-def]
        calls.append(("upload", video_path))
        return manifest_generation.GeminiFileRef(
            name="files/test",
            uri="https://generativelanguage.googleapis.com/v1beta/files/test",
            mime_type="video/mp4",
        )

    async def fake_generate_manifest_from_gemini_file(
        **kwargs: object,
    ) -> schemas.LectureVideoManifestV3:
        calls.append(("generate", kwargs["gemini_file"]))
        raise RuntimeError("generation failed")

    async def fake_delete_gemini_file(
        name: str | None,
        _client,
    ) -> None:  # type: ignore[no-untyped-def]
        calls.append(("delete", name))

    monkeypatch.setattr(
        manifest_generation,
        "upload_video_to_gemini",
        fake_upload_video_to_gemini,
    )
    monkeypatch.setattr(
        manifest_generation,
        "_generate_manifest_from_gemini_file",
        fake_generate_manifest_from_gemini_file,
    )
    monkeypatch.setattr(
        manifest_generation,
        "delete_gemini_file",
        fake_delete_gemini_file,
    )

    with pytest.raises(RuntimeError, match="generation failed"):
        await manifest_generation._upload_and_generate_whole_manifest(
            video_path="lecture.mp4",
            gemini_client=object(),  # type: ignore[arg-type]
            generation_prompt_content="Generate checks.",
            transcript=_transcript(),
            video_duration_ms=30000,
            model="gemini-test",
        )

    assert [call[0] for call in calls] == ["upload", "generate", "delete"]
    assert calls[-1] == ("delete", "files/test")
