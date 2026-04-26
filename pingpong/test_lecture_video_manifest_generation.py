import subprocess

import pytest

import pingpong.lecture_video_manifest_generation as manifest_generation
import pingpong.schemas as schemas
from pingpong.lecture_video_manifest_generation import (
    GeneratedChoice,
    GeneratedChoiceFeedback,
    GeneratedQuestion,
    GeneratedQuizWithVideo,
    GeneratedVideoDescription,
    _quiz_to_manifest,
)


def test_quiz_to_manifest_converts_generated_video_descriptions() -> None:
    quiz = GeneratedQuizWithVideo(
        video_summary="A short algebra lesson.",
        video_descriptions=[
            GeneratedVideoDescription(
                start_offset_ms=0,
                end_offset_ms=30000,
                description="The teacher writes an expression on the board.",
            )
        ],
        questions=[
            GeneratedQuestion(
                id=1,
                question_source="generated",
                pause_after_word_id="w1",
                pause_after_word="expression",
                pause_at=1.0,
                voice_over_intro="Try this.",
                question_text="What should happen next?",
                choices=[
                    GeneratedChoice(text="Combine like terms", misconception=None),
                    GeneratedChoice(
                        text="Change every variable",
                        misconception="Confuses simplification with substitution.",
                    ),
                ],
                correct_answer="Combine like terms",
                choice_feedback={
                    "Combine like terms": GeneratedChoiceFeedback(
                        voice_over="Right.",
                        resume_at_word_id="w2",
                        resume_at_word="Next",
                        resume_at=1.5,
                    ),
                    "Change every variable": GeneratedChoiceFeedback(
                        voice_over="Not quite.",
                        resume_at_word_id="w2",
                        resume_at_word="Next",
                        resume_at=1.5,
                    ),
                },
            )
        ],
    )

    manifest = _quiz_to_manifest(
        quiz,
        [
            schemas.LectureVideoManifestWordV3(
                id="w1",
                word="expression",
                start_offset_ms=0,
                end_offset_ms=1000,
            )
        ],
        video_duration_ms=30000,
    )

    assert isinstance(
        manifest.video_descriptions[0],
        schemas.LectureVideoManifestVideoDescriptionV3,
    )
    assert manifest.video_descriptions[0].description == (
        "The teacher writes an expression on the board."
    )


def test_quiz_to_manifest_reports_missing_choice_feedback() -> None:
    quiz = GeneratedQuizWithVideo(
        video_summary="A short algebra lesson.",
        video_descriptions=[
            GeneratedVideoDescription(
                start_offset_ms=0,
                end_offset_ms=30000,
                description="The teacher writes an expression on the board.",
            )
        ],
        questions=[
            GeneratedQuestion(
                id=1,
                question_source="generated",
                pause_after_word_id="w1",
                pause_after_word="expression",
                pause_at=1.0,
                voice_over_intro="Try this.",
                question_text="What should happen next?",
                choices=[
                    GeneratedChoice(text="Combine like terms", misconception=None),
                    GeneratedChoice(
                        text="Change every variable",
                        misconception="Confuses simplification with substitution.",
                    ),
                ],
                correct_answer="Combine like terms",
                choice_feedback={
                    "Combine like terms": GeneratedChoiceFeedback(
                        voice_over="Right.",
                        resume_at_word_id="w2",
                        resume_at_word="Next",
                        resume_at=1.5,
                    ),
                    "Change every variable ": GeneratedChoiceFeedback(
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
        _quiz_to_manifest(
            quiz,
            [
                schemas.LectureVideoManifestWordV3(
                    id="w1",
                    word="expression",
                    start_offset_ms=0,
                    end_offset_ms=1000,
                )
            ],
            video_duration_ms=30000,
        )


async def test_ffprobe_duration_ms_logs_missing_binary_once(
    monkeypatch, caplog
) -> None:
    def fake_run(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise FileNotFoundError("ffprobe")

    monkeypatch.setattr(manifest_generation, "_FFPROBE_MISSING_LOGGED", False)
    monkeypatch.setattr(subprocess, "run", fake_run)

    with caplog.at_level("WARNING"):
        assert await manifest_generation._ffprobe_duration_ms("lecture.mp4") is None
        assert await manifest_generation._ffprobe_duration_ms("lecture.mp4") is None

    assert caplog.text.count("ffprobe is unavailable") == 1


async def test_ffprobe_duration_ms_returns_none_on_probe_failure(monkeypatch) -> None:
    def fake_run(*args, **kwargs):  # type: ignore[no-untyped-def]
        assert kwargs["timeout"] == 30
        raise subprocess.CalledProcessError(1, args[0], stderr="bad video")

    monkeypatch.setattr(subprocess, "run", fake_run)

    assert await manifest_generation._ffprobe_duration_ms("lecture.mp4") is None
