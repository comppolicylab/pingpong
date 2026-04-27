import shutil
import subprocess

import pytest

import pingpong.lecture_video_manifest_generation as manifest_generation
import pingpong.schemas as schemas


def test_quiz_to_manifest_converts_generated_video_descriptions() -> None:
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
                )
            ],
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
