import importlib.util
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

import pingpong.schemas as schemas
from pingpong import lecture_video_processing, lecture_video_service, models

from .test_lecture_video_server import (
    DEFAULT_LECTURE_VIDEO_VOICE_ID,
    lecture_video_manifest,
    lecture_video_manifest_v3,
    lecture_video_manifest_v4,
    make_lecture_video,
)
from .testutil import with_institution


def _load_transcript_data_migration_module():
    migration_path = (
        Path(__file__).resolve().parents[1]
        / "alembic"
        / "versions"
        / "df25d20d0f3a_add_lecture_video_transcript_data.py"
    )
    spec = importlib.util.spec_from_file_location(
        "transcript_data_migration", migration_path
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


transcript_data_migration = _load_transcript_data_migration_module()


def test_create_assistant_rejects_overlong_generation_prompt() -> None:
    with pytest.raises(ValidationError):
        schemas.CreateAssistant.model_validate(
            {
                "name": "Lecture Assistant",
                "instructions": "Guide the learner through the lecture.",
                "description": "Lecture presentation assistant",
                "interaction_mode": "lecture_video",
                "model": "gpt-4o-mini",
                "tools": [],
                "lecture_video_id": 1,
                "lecture_video_manifest": lecture_video_manifest(),
                "voice_id": DEFAULT_LECTURE_VIDEO_VOICE_ID,
                "overwrite_manifest": True,
                "generation_prompt": "x" * 20001,
            }
        )


def test_update_assistant_rejects_overlong_generation_prompt() -> None:
    with pytest.raises(ValidationError):
        schemas.UpdateAssistant.model_validate(
            {
                "lecture_video_id": 1,
                "lecture_video_manifest": lecture_video_manifest(),
                "voice_id": DEFAULT_LECTURE_VIDEO_VOICE_ID,
                "overwrite_manifest": True,
                "generation_prompt": "x" * 20001,
            }
        )


@pytest.mark.parametrize("duration", [4999, 300001])
def test_create_assistant_rejects_video_description_duration_out_of_range(
    duration: int,
) -> None:
    with pytest.raises(ValidationError):
        schemas.CreateAssistant.model_validate(
            {
                "name": "Lecture Assistant",
                "instructions": "Guide the learner through the lecture.",
                "description": "Lecture presentation assistant",
                "interaction_mode": "lecture_video",
                "model": "gpt-4o-mini",
                "tools": [],
                "lecture_video_id": 1,
                "voice_id": DEFAULT_LECTURE_VIDEO_VOICE_ID,
                "video_description_duration_ms": duration,
            }
        )


def test_update_assistant_allows_non_step_video_description_duration() -> None:
    assistant = schemas.UpdateAssistant.model_validate(
        {
            "lecture_video_id": 1,
            "voice_id": DEFAULT_LECTURE_VIDEO_VOICE_ID,
            "video_description_duration_ms": 7000,
        }
    )

    assert assistant.video_description_duration_ms == 7000


def test_create_assistant_rejects_manifest_when_generation_mode_requested() -> None:
    with pytest.raises(ValidationError) as exc_info:
        schemas.CreateAssistant.model_validate(
            {
                "name": "Lecture Assistant",
                "instructions": "Guide the learner through the lecture.",
                "description": "Lecture presentation assistant",
                "interaction_mode": "lecture_video",
                "model": "gpt-4o-mini",
                "tools": [],
                "lecture_video_id": 1,
                "lecture_video_manifest": lecture_video_manifest(),
                "voice_id": DEFAULT_LECTURE_VIDEO_VOICE_ID,
                "overwrite_manifest": False,
            }
        )

    assert (
        "lecture_video_manifest cannot be supplied when overwrite_manifest is false"
        in str(exc_info.value)
    )


def test_create_assistant_defaults_to_generation_when_overwrite_manifest_omitted() -> (
    None
):
    assistant = schemas.CreateAssistant.model_validate(
        {
            "name": "Lecture Assistant",
            "instructions": "Guide the learner through the lecture.",
            "description": "Lecture presentation assistant",
            "interaction_mode": "lecture_video",
            "model": "gpt-4o-mini",
            "tools": [],
            "lecture_video_id": 1,
            "voice_id": DEFAULT_LECTURE_VIDEO_VOICE_ID,
        }
    )

    assert assistant.overwrite_manifest is None
    assert "overwrite_manifest" not in assistant.model_fields_set


def test_update_assistant_rejects_manifest_when_generation_mode_requested() -> None:
    with pytest.raises(ValidationError) as exc_info:
        schemas.UpdateAssistant.model_validate(
            {
                "lecture_video_id": 1,
                "lecture_video_manifest": lecture_video_manifest(),
                "voice_id": DEFAULT_LECTURE_VIDEO_VOICE_ID,
                "overwrite_manifest": False,
            }
        )

    assert (
        "lecture_video_manifest cannot be supplied when overwrite_manifest is false"
        in str(exc_info.value)
    )


def test_update_assistant_defaults_to_generation_when_overwrite_manifest_omitted() -> (
    None
):
    assistant = schemas.UpdateAssistant.model_validate(
        {
            "lecture_video_id": 1,
            "voice_id": DEFAULT_LECTURE_VIDEO_VOICE_ID,
        }
    )

    assert assistant.overwrite_manifest is None
    assert "overwrite_manifest" not in assistant.model_fields_set


@with_institution(11, "Test Institution")
@pytest.mark.parametrize(
    (
        "manifest_data",
        "incoming_generation_prompt",
        "generation_prompt_present",
        "latest_run_status",
        "expected",
    ),
    [
        pytest.param(None, None, False, None, True, id="missing-manifest"),
        pytest.param(
            lecture_video_manifest(),
            "Updated prompt",
            True,
            None,
            True,
            id="prompt-changed",
        ),
        pytest.param(
            lecture_video_manifest(),
            "Original prompt",
            True,
            None,
            False,
            id="prompt-unchanged",
        ),
        pytest.param(
            lecture_video_manifest(),
            None,
            False,
            schemas.LectureVideoProcessingRunStatus.FAILED,
            True,
            id="latest-run-failed",
        ),
        pytest.param(
            lecture_video_manifest(),
            None,
            False,
            schemas.LectureVideoProcessingRunStatus.COMPLETED,
            False,
            id="latest-run-completed",
        ),
    ],
)
async def test_should_regenerate_manifest_matrix(
    db,
    institution,
    manifest_data,
    incoming_generation_prompt,
    generation_prompt_present,
    latest_run_status,
    expected,
):
    async with db.async_session() as session:
        class_ = models.Class(
            name="Lecture Class",
            institution_id=institution.id,
            api_key="sk-test",
        )
        session.add(class_)
        await session.flush()
        lecture_video = make_lecture_video(
            class_.id,
            f"regenerate-{expected}.mp4",
            status=schemas.LectureVideoStatus.READY.value,
        )
        lecture_video.generation_prompt = "Original prompt"
        lecture_video.manifest_data = None
        if manifest_data is not None:
            validated_manifest = schemas.validate_lecture_video_manifest(manifest_data)
            assert validated_manifest is not None
            lecture_video.manifest_data = validated_manifest.model_dump(mode="json")
        session.add(lecture_video)
        await session.flush()
        if latest_run_status is not None:
            await models.LectureVideoProcessingRun.create(
                session,
                lecture_video_id=lecture_video.id,
                lecture_video_id_snapshot=lecture_video.id,
                class_id=class_.id,
                assistant_id_at_start=None,
                stage=schemas.LectureVideoProcessingStage.MANIFEST_GENERATION,
                attempt_number=1,
                status=latest_run_status,
            )
        await session.flush()

        assert (
            await lecture_video_service.should_regenerate_manifest(
                session,
                lecture_video,
                incoming_generation_prompt=incoming_generation_prompt,
                generation_prompt_present=generation_prompt_present,
            )
            is expected
        )


@with_institution(11, "Test Institution")
async def test_should_regenerate_manifest_ignores_null_video_description_duration(
    db, institution
):
    async with db.async_session() as session:
        class_ = models.Class(
            name="Lecture Class",
            institution_id=institution.id,
            api_key="sk-test",
        )
        session.add(class_)
        await session.flush()
        lecture_video = make_lecture_video(
            class_.id,
            "null-duration-regenerate.mp4",
            status=schemas.LectureVideoStatus.READY.value,
        )
        validated_manifest = schemas.validate_lecture_video_manifest(
            lecture_video_manifest()
        )
        assert validated_manifest is not None
        lecture_video.manifest_data = validated_manifest.model_dump(mode="json")
        lecture_video.video_description_duration_ms = 30_000
        session.add(lecture_video)
        await session.flush()

        assert (
            await lecture_video_service.should_regenerate_manifest(
                session,
                lecture_video,
                incoming_generation_prompt=None,
                generation_prompt_present=False,
                incoming_video_description_duration_ms=None,
                video_description_duration_ms_present=True,
            )
            is False
        )


@with_institution(11, "Test Institution")
async def test_should_regenerate_manifest_when_video_description_duration_changes(
    db, institution
):
    async with db.async_session() as session:
        class_ = models.Class(
            name="Lecture Class",
            institution_id=institution.id,
            api_key="sk-test",
        )
        session.add(class_)
        await session.flush()
        lecture_video = make_lecture_video(
            class_.id,
            "duration-change-regenerate.mp4",
            status=schemas.LectureVideoStatus.READY.value,
        )
        validated_manifest = schemas.validate_lecture_video_manifest(
            lecture_video_manifest()
        )
        assert validated_manifest is not None
        lecture_video.manifest_data = validated_manifest.model_dump(mode="json")
        lecture_video.video_description_duration_ms = 30_000
        session.add(lecture_video)
        await session.flush()

        assert (
            await lecture_video_service.should_regenerate_manifest(
                session,
                lecture_video,
                incoming_generation_prompt=None,
                generation_prompt_present=False,
                incoming_video_description_duration_ms=35_000,
                video_description_duration_ms_present=True,
            )
            is True
        )


@with_institution(11, "Test Institution")
async def test_load_manifest_generation_context_defaults_null_video_description_duration(
    db,
    institution,
    monkeypatch,
):
    async with db.async_session() as session:
        class_ = models.Class(
            name="Lecture Class",
            institution_id=institution.id,
            api_key="sk-test",
        )
        session.add(class_)
        await session.flush()
        lecture_video = make_lecture_video(
            class_.id,
            "null-duration-context.mp4",
            status=schemas.LectureVideoStatus.PROCESSING.value,
        )
        session.add(lecture_video)
        await session.flush()
        run = await models.LectureVideoProcessingRun.create(
            session,
            lecture_video_id=lecture_video.id,
            lecture_video_id_snapshot=lecture_video.id,
            class_id=class_.id,
            assistant_id_at_start=None,
            stage=schemas.LectureVideoProcessingStage.MANIFEST_GENERATION,
            attempt_number=1,
            status=schemas.LectureVideoProcessingRunStatus.RUNNING,
        )
        run.lease_token = "lease-token"
        run_id = run.id
        lecture_video_id = lecture_video.id
        await session.commit()

    monkeypatch.setattr(
        models.LectureVideo,
        "get_by_id_with_transcript_data",
        AsyncMock(
            return_value=SimpleNamespace(
                id=lecture_video_id,
                transcript_data=None,
                manifest_data=None,
                generation_prompt=None,
                video_description_duration_ms=None,
            )
        ),
    )
    monkeypatch.setattr(
        lecture_video_processing,
        "get_openai_client_by_class_id",
        AsyncMock(return_value="openai-client"),
    )
    monkeypatch.setattr(
        lecture_video_processing.gemini,
        "get_gemini_client_by_class_id",
        AsyncMock(return_value="gemini-client"),
    )

    context = await lecture_video_processing._load_manifest_generation_run_context(
        run_id,
        "lease-token",
    )

    assert context is not None
    assert context.video_description_duration_ms == 30_000


@with_institution(11, "Test Institution")
async def test_latest_processing_run_uses_attempt_number_when_created_ties(
    db, institution
):
    async with db.async_session() as session:
        class_ = models.Class(
            name="Lecture Class",
            institution_id=institution.id,
            api_key="sk-test",
        )
        session.add(class_)
        await session.flush()
        lecture_video = make_lecture_video(
            class_.id,
            "same-created-runs.mp4",
            status=schemas.LectureVideoStatus.READY.value,
        )
        lecture_video.manifest_data = lecture_video_manifest()
        lecture_video.generation_prompt = "Original prompt"
        session.add(lecture_video)
        await session.flush()

        created = datetime(2026, 4, 27, 12, 0, tzinfo=timezone.utc)
        failed_run = await models.LectureVideoProcessingRun.create(
            session,
            lecture_video_id=lecture_video.id,
            lecture_video_id_snapshot=lecture_video.id,
            class_id=class_.id,
            assistant_id_at_start=None,
            stage=schemas.LectureVideoProcessingStage.MANIFEST_GENERATION,
            attempt_number=1,
            status=schemas.LectureVideoProcessingRunStatus.FAILED,
        )
        completed_run = await models.LectureVideoProcessingRun.create(
            session,
            lecture_video_id=lecture_video.id,
            lecture_video_id_snapshot=lecture_video.id,
            class_id=class_.id,
            assistant_id_at_start=None,
            stage=schemas.LectureVideoProcessingStage.MANIFEST_GENERATION,
            attempt_number=2,
            status=schemas.LectureVideoProcessingRunStatus.COMPLETED,
        )
        failed_run.created = created
        completed_run.created = created
        await session.flush()

        summary = await lecture_video_service.latest_processing_run_summary(
            session,
            lecture_video.id,
            schemas.LectureVideoProcessingStage.MANIFEST_GENERATION,
        )

        assert summary is not None
        assert summary.state == schemas.LectureVideoProcessingRunStatus.COMPLETED
        assert (
            await lecture_video_service.should_regenerate_manifest(
                session,
                lecture_video,
                incoming_generation_prompt=None,
                generation_prompt_present=False,
            )
            is False
        )


@with_institution(11, "Test Institution")
async def test_process_claimed_run_dispatches_by_stage(db, institution, monkeypatch):
    async with db.async_session() as session:
        class_ = models.Class(
            id=1,
            name="Lecture Class",
            institution_id=institution.id,
            api_key="sk-test",
        )
        session.add(class_)
        await session.flush()
        manifest_run = await models.LectureVideoProcessingRun.create(
            session,
            lecture_video_id=None,
            lecture_video_id_snapshot=1,
            class_id=class_.id,
            assistant_id_at_start=None,
            stage=schemas.LectureVideoProcessingStage.MANIFEST_GENERATION,
            attempt_number=1,
            status=schemas.LectureVideoProcessingRunStatus.RUNNING,
        )
        narration_run = await models.LectureVideoProcessingRun.create(
            session,
            lecture_video_id=None,
            lecture_video_id_snapshot=2,
            class_id=class_.id,
            assistant_id_at_start=None,
            stage=schemas.LectureVideoProcessingStage.NARRATION,
            attempt_number=1,
            status=schemas.LectureVideoProcessingRunStatus.RUNNING,
        )
        manifest_run_id = manifest_run.id
        narration_run_id = narration_run.id
        await session.commit()

    manifest_handler = AsyncMock()
    narration_handler = AsyncMock()
    monkeypatch.setattr(
        lecture_video_processing,
        "_process_claimed_manifest_run",
        manifest_handler,
    )
    monkeypatch.setattr(
        lecture_video_processing,
        "_process_claimed_narration_run",
        narration_handler,
    )

    await lecture_video_processing._process_claimed_run(manifest_run_id, "lease-a")
    await lecture_video_processing._process_claimed_run(narration_run_id, "lease-b")

    manifest_handler.assert_awaited_once_with(manifest_run_id, "lease-a")
    narration_handler.assert_awaited_once_with(narration_run_id, "lease-b")


@with_institution(11, "Test Institution")
async def test_write_manifest_generation_temp_video_cancels_when_video_deleted(
    db, institution
):
    lease_token = "lease-token"
    async with db.async_session() as session:
        class_ = models.Class(
            id=1,
            name="Lecture Class",
            institution_id=institution.id,
            api_key="sk-test",
        )
        lecture_video = make_lecture_video(
            1,
            "deleted-before-temp-write.mp4",
            status=schemas.LectureVideoStatus.PROCESSING.value,
        )
        session.add_all([class_, lecture_video])
        await session.flush()
        run = await models.LectureVideoProcessingRun.create(
            session,
            lecture_video_id=lecture_video.id,
            lecture_video_id_snapshot=lecture_video.id,
            class_id=class_.id,
            assistant_id_at_start=None,
            stage=schemas.LectureVideoProcessingStage.MANIFEST_GENERATION,
            attempt_number=1,
            status=schemas.LectureVideoProcessingRunStatus.RUNNING,
        )
        run.lease_token = lease_token
        run_id = run.id
        lecture_video_id = lecture_video.id
        await session.delete(lecture_video)
        await session.commit()

    video_path = await lecture_video_processing._write_manifest_generation_temp_video(
        run_id,
        lease_token,
        lecture_video_id,
        "/tmp",
    )

    async with db.async_session() as session:
        refreshed_run = await models.LectureVideoProcessingRun.get_by_id(
            session,
            run_id,
        )

    assert video_path is None
    assert refreshed_run is not None
    assert refreshed_run.status == schemas.LectureVideoProcessingRunStatus.CANCELLED
    assert (
        refreshed_run.cancel_reason
        == schemas.LectureVideoProcessingCancelReason.LECTURE_VIDEO_DELETED
    )
    assert refreshed_run.lease_token is None
    assert refreshed_run.lease_expires_at is None


@with_institution(11, "Test Institution")
async def test_complete_manifest_generation_run_cancels_when_assistant_detached(
    db, institution
):
    lease_token = "lease-token"
    async with db.async_session() as session:
        class_ = models.Class(
            id=1,
            name="Lecture Class",
            institution_id=institution.id,
            api_key="sk-test",
        )
        lecture_video = make_lecture_video(
            1,
            "detached-manifest.mp4",
            status=schemas.LectureVideoStatus.PROCESSING.value,
        )
        assistant = models.Assistant(
            name="Lecture Assistant",
            class_id=1,
            interaction_mode=schemas.InteractionMode.LECTURE_VIDEO,
            version=3,
            lecture_video=lecture_video,
            instructions="You are a lecture assistant.",
            model="gpt-4o-mini",
            tools="[]",
            use_latex=False,
            use_image_descriptions=False,
            hide_prompt=False,
        )
        session.add_all([class_, lecture_video, assistant])
        await session.flush()
        run = await models.LectureVideoProcessingRun.create(
            session,
            lecture_video_id=lecture_video.id,
            lecture_video_id_snapshot=lecture_video.id,
            class_id=class_.id,
            assistant_id_at_start=assistant.id,
            stage=schemas.LectureVideoProcessingStage.MANIFEST_GENERATION,
            attempt_number=1,
            status=schemas.LectureVideoProcessingRunStatus.RUNNING,
        )
        run.lease_token = lease_token
        assistant.lecture_video_id = None
        session.add_all([run, assistant])
        run_id = run.id
        await session.commit()

    await lecture_video_processing._complete_manifest_generation_run(
        run_id,
        lease_token,
        schemas.LectureVideoManifestV4.model_validate(lecture_video_manifest_v4()),
    )

    async with db.async_session() as session:
        refreshed_run = await models.LectureVideoProcessingRun.get_by_id(
            session,
            run_id,
        )

    assert refreshed_run is not None
    assert refreshed_run.status == schemas.LectureVideoProcessingRunStatus.CANCELLED
    assert (
        refreshed_run.cancel_reason
        == schemas.LectureVideoProcessingCancelReason.ASSISTANT_DETACHED
    )


@with_institution(11, "Test Institution")
async def test_process_claimed_manifest_run_persists_generated_manifest(
    db, institution, monkeypatch
):
    lease_token = "lease-token"
    manifest = schemas.LectureVideoManifestV4.model_validate(
        lecture_video_manifest_v4()
    )
    transcript = manifest.word_level_transcription
    calls: list[tuple[str, object]] = []

    class FakeGeminiAio:
        async def __aenter__(self) -> SimpleNamespace:
            return SimpleNamespace(name="fake-gemini-client")

        async def __aexit__(self, *args: object) -> None:
            return None

    class FakeGeminiClient:
        def __init__(self, *, api_key: str) -> None:
            calls.append(("gemini-client", api_key))
            self.aio = FakeGeminiAio()

    async def fake_transcribe_video_words(
        video_path: str,
        openai_client: SimpleNamespace,
        *,
        temp_dir: str,
    ) -> list[schemas.LectureVideoManifestWordV3]:
        calls.append(("transcribe", (video_path, openai_client, temp_dir)))
        return transcript

    async def fake_upload_and_generate_manifest(
        **kwargs: object,
    ) -> schemas.LectureVideoManifestV4:
        calls.append(("generate", kwargs))
        return manifest

    async def fake_get_gemini_client_by_class_id(
        session: AsyncSession,
        class_id: int,
    ) -> FakeGeminiClient:
        return FakeGeminiClient(api_key=f"fake-gemini-key-{class_id}")

    monkeypatch.setattr(
        lecture_video_processing,
        "get_openai_client_by_class_id",
        AsyncMock(return_value=SimpleNamespace(name="fake-openai-client")),
    )
    monkeypatch.setattr(
        lecture_video_processing.gemini,
        "get_gemini_client_by_class_id",
        fake_get_gemini_client_by_class_id,
    )
    monkeypatch.setattr(
        lecture_video_processing,
        "_write_video_to_temp_path",
        AsyncMock(return_value="/tmp/fake-video.mp4"),
    )
    monkeypatch.setattr(
        lecture_video_processing.lecture_video_manifest_generation,
        "transcribe_video_words",
        fake_transcribe_video_words,
    )
    monkeypatch.setattr(
        lecture_video_processing.lecture_video_manifest_generation,
        "upload_and_generate_manifest",
        fake_upload_and_generate_manifest,
    )

    async with db.async_session() as session:
        class_ = models.Class(
            id=1,
            name="Lecture Class",
            institution_id=institution.id,
            api_key="sk-test",
        )
        lecture_video = make_lecture_video(
            1,
            "generated-manifest.mp4",
            status=schemas.LectureVideoStatus.PROCESSING.value,
        )
        assistant = models.Assistant(
            name="Lecture Assistant",
            class_id=1,
            interaction_mode=schemas.InteractionMode.LECTURE_VIDEO,
            version=3,
            lecture_video=lecture_video,
            instructions="You are a lecture assistant.",
            model="gpt-4o-mini",
            tools="[]",
            use_latex=False,
            use_image_descriptions=False,
            hide_prompt=False,
        )
        session.add_all([class_, lecture_video, assistant])
        await session.flush()
        run = await models.LectureVideoProcessingRun.create(
            session,
            lecture_video_id=lecture_video.id,
            lecture_video_id_snapshot=lecture_video.id,
            class_id=class_.id,
            assistant_id_at_start=None,
            stage=schemas.LectureVideoProcessingStage.MANIFEST_GENERATION,
            attempt_number=1,
            status=schemas.LectureVideoProcessingRunStatus.RUNNING,
        )
        run.lease_token = lease_token
        run_id = run.id
        lecture_video_id = lecture_video.id
        await session.commit()

    await lecture_video_processing._process_claimed_manifest_run(run_id, lease_token)

    async with db.async_session() as session:
        refreshed_run = await models.LectureVideoProcessingRun.get_by_id(
            session, run_id
        )
        refreshed_video = await models.LectureVideo.get_by_id_with_copy_context(
            session, lecture_video_id
        )

    assert refreshed_run is not None
    assert refreshed_run.status == schemas.LectureVideoProcessingRunStatus.COMPLETED
    assert refreshed_run.lease_token is None
    assert refreshed_video is not None
    assert refreshed_video.manual_manifest is False
    assert refreshed_video.manifest_version == 4
    assert [call[0] for call in calls] == [
        "gemini-client",
        "transcribe",
        "generate",
    ]


@with_institution(11, "Test Institution")
async def test_process_claimed_manifest_run_marks_video_failed_on_context_load_error(
    db,
    institution,
    monkeypatch,
):
    lease_token = "lease-token"
    error_message = "OpenAI credentials unavailable"
    monkeypatch.setattr(
        lecture_video_processing,
        "get_openai_client_by_class_id",
        AsyncMock(side_effect=RuntimeError(error_message)),
    )

    async with db.async_session() as session:
        class_ = models.Class(
            id=1,
            name="Lecture Class",
            institution_id=institution.id,
            api_key="sk-test",
        )
        lecture_video = make_lecture_video(
            1,
            "context-load-failure.mp4",
            status=schemas.LectureVideoStatus.PROCESSING.value,
        )
        session.add_all([class_, lecture_video])
        await session.flush()
        run = await models.LectureVideoProcessingRun.create(
            session,
            lecture_video_id=lecture_video.id,
            lecture_video_id_snapshot=lecture_video.id,
            class_id=class_.id,
            assistant_id_at_start=None,
            stage=schemas.LectureVideoProcessingStage.MANIFEST_GENERATION,
            attempt_number=1,
            status=schemas.LectureVideoProcessingRunStatus.RUNNING,
        )
        run.lease_token = lease_token
        run_id = run.id
        lecture_video_id = lecture_video.id
        await session.commit()

    await lecture_video_processing._process_claimed_manifest_run(run_id, lease_token)

    async with db.async_session() as session:
        refreshed_run = await models.LectureVideoProcessingRun.get_by_id(
            session, run_id
        )
        refreshed_video = await models.LectureVideo.get_by_id_with_copy_context(
            session, lecture_video_id
        )

    assert refreshed_run is not None
    assert refreshed_run.status == schemas.LectureVideoProcessingRunStatus.FAILED
    assert refreshed_run.error_message == error_message
    assert refreshed_run.lease_token is None
    assert refreshed_video is not None
    assert refreshed_video.status == schemas.LectureVideoStatus.FAILED
    assert refreshed_video.error_message == error_message


async def test_upload_and_generate_manifest_propagates_generation_failure(
    monkeypatch,
):
    calls: list[tuple[str, object]] = []
    transcript = schemas.LectureVideoManifestV4.model_validate(
        lecture_video_manifest_v4()
    ).word_level_transcription

    class FakeGeminiAio:
        async def __aenter__(self) -> SimpleNamespace:
            return SimpleNamespace(name="fake-gemini-client")

        async def __aexit__(self, *args: object) -> None:
            return None

    class FakeGeminiClient:
        def __init__(self, *, api_key: str) -> None:
            calls.append(("gemini-client", api_key))
            self.aio = FakeGeminiAio()

    async def fake_upload_and_generate_manifest(
        **kwargs: object,
    ) -> schemas.LectureVideoManifestV4:
        calls.append(("generate", kwargs))
        raise RuntimeError("generation failed")

    monkeypatch.setattr(
        lecture_video_processing.lecture_video_manifest_generation,
        "upload_and_generate_manifest",
        fake_upload_and_generate_manifest,
    )

    with pytest.raises(RuntimeError, match="generation failed"):
        await lecture_video_processing._upload_and_generate_manifest(
            run_id=1,
            lease_token="lease-token",
            lecture_video_id=2,
            video_path="/tmp/fake-video.mp4",
            gemini_client=FakeGeminiClient(api_key="fake-gemini-key"),
            generation_prompt="Generate checks.",
            transcript=transcript,
            temp_dir="/tmp",
            video_description_duration_ms=30_000,
        )

    assert [call[0] for call in calls] == [
        "gemini-client",
        "generate",
    ]
    assert calls[1][1]["video_description_duration_ms"] == 30_000


@with_institution(11, "Test Institution")
async def test_transcript_reuse_only_requires_loaded_transcript_data(db, institution):
    async with db.async_session() as session:
        class_ = models.Class(
            id=1,
            name="Lecture Class",
            institution_id=institution.id,
            api_key="sk-test",
        )
        lecture_video = make_lecture_video(
            class_.id,
            "deferred-manifest.mp4",
            filename="deferred-manifest.mp4",
        )
        session.add_all([class_, lecture_video])
        await session.flush()
        manifest = schemas.validate_lecture_video_manifest(lecture_video_manifest_v3())
        assert manifest is not None
        await lecture_video_service.persist_manifest(
            session,
            lecture_video,
            manifest,
            voice_id=DEFAULT_LECTURE_VIDEO_VOICE_ID,
            manual_manifest=True,
        )
        lecture_video_id = lecture_video.id
        await session.commit()

    async with db.async_session() as session:
        loaded_video = await models.LectureVideo.get_by_id_with_transcript_data(
            session, lecture_video_id
        )
        assert loaded_video is not None

        transcript = lecture_video_processing._existing_manifest_transcript(
            loaded_video
        )

    assert transcript is not None
    assert [word.model_dump(mode="json") for word in transcript] == (
        manifest.model_dump(mode="json")["word_level_transcription"]
    )


@with_institution(11, "Test Institution")
async def test_persist_manifest_normalizes_transcript_out_of_manifest_data(
    db, institution
):
    manifest = schemas.LectureVideoManifestV3.model_validate(
        lecture_video_manifest_v3()
    )

    async with db.async_session() as session:
        class_ = models.Class(
            id=1,
            name="Lecture Class",
            institution_id=institution.id,
            api_key="sk-test",
        )
        lecture_video = make_lecture_video(
            class_.id,
            "normalized-transcript.mp4",
            filename="normalized-transcript.mp4",
        )
        session.add_all([class_, lecture_video])
        await session.flush()

        await lecture_video_service.persist_manifest(
            session,
            lecture_video,
            manifest,
            voice_id=DEFAULT_LECTURE_VIDEO_VOICE_ID,
            manual_manifest=True,
        )
        lecture_video_id = lecture_video.id
        await session.commit()

    async with db.async_session() as session:
        loaded_video = await models.LectureVideo.get_by_id_with_copy_context(
            session, lecture_video_id
        )

    assert loaded_video is not None
    assert loaded_video.manifest_data is not None
    assert loaded_video.manifest_data == {
        "version": 3,
        "video_descriptions": [
            description.model_dump(mode="json")
            for description in manifest.video_descriptions
        ],
    }
    assert "questions" not in loaded_video.manifest_data
    assert "word_level_transcription" not in loaded_video.manifest_data
    assert loaded_video.transcript_data is not None
    assert loaded_video.transcript_data["word_level_transcription"] == [
        word.model_dump(mode="json") for word in manifest.word_level_transcription
    ]

    hydrated_manifest = lecture_video_service.lecture_video_manifest_from_model(
        loaded_video
    )
    assert isinstance(hydrated_manifest, schemas.LectureVideoManifestV3)
    assert (
        hydrated_manifest.word_level_transcription == manifest.word_level_transcription
    )
    assert hydrated_manifest.video_descriptions == manifest.video_descriptions


def test_transcript_data_migration_preserves_versionless_v2_manifest_version() -> None:
    manifest_data = {
        "questions": [
            {
                "type": "single_select",
                "question_text": "Pick one.",
                "intro_text": "",
                "stop_offset_ms": 1000,
                "options": [
                    {
                        "option_text": "Yes",
                        "post_answer_text": "",
                        "continue_offset_ms": 1000,
                        "correct": True,
                    },
                    {
                        "option_text": "No",
                        "post_answer_text": "",
                        "continue_offset_ms": 1000,
                        "correct": False,
                    },
                ],
            }
        ],
        "word_level_transcription": [
            {"id": "w1", "word": "Hello", "start": 0, "end": 1}
        ],
    }

    assert (
        transcript_data_migration._manifest_version_for_split_transcript(manifest_data)
        == 2
    )


def test_transcript_data_migration_preserves_versionless_v3_manifest_version() -> None:
    manifest_data = {
        "questions": [
            {
                "type": "single_select",
                "question_text": "Pick one.",
                "intro_text": "",
                "stop_offset_ms": 1000,
                "options": [
                    {
                        "option_text": "Yes",
                        "post_answer_text": "",
                        "continue_offset_ms": 1000,
                        "correct": True,
                    },
                    {
                        "option_text": "No",
                        "post_answer_text": "",
                        "continue_offset_ms": 1000,
                        "correct": False,
                    },
                ],
            }
        ],
        "word_level_transcription": [
            {
                "id": "w1",
                "word": "Hello",
                "start_offset_ms": 0,
                "end_offset_ms": 1000,
            }
        ],
        "video_descriptions": [
            {
                "start_offset_ms": 0,
                "end_offset_ms": 1000,
                "description": "The teacher is on screen.",
            }
        ],
    }

    assert (
        transcript_data_migration._manifest_version_for_split_transcript(manifest_data)
        == 3
    )


def test_transcript_data_migration_stores_only_v3_manifest_extras() -> None:
    manifest_data = lecture_video_manifest_v3()

    stored_manifest = transcript_data_migration._manifest_extras_for_storage(
        manifest_data
    )

    assert stored_manifest == {
        "version": 3,
        "video_descriptions": manifest_data["video_descriptions"],
    }


def test_transcript_data_migration_stores_only_v2_manifest_extras() -> None:
    manifest_data = {
        "version": 2,
        "questions": [
            {
                "type": "single_select",
                "question_text": "Pick one.",
                "intro_text": "",
                "stop_offset_ms": 1000,
                "options": [
                    {
                        "option_text": "Yes",
                        "post_answer_text": "",
                        "continue_offset_ms": 1000,
                        "correct": True,
                    },
                    {
                        "option_text": "No",
                        "post_answer_text": "",
                        "continue_offset_ms": 1000,
                        "correct": False,
                    },
                ],
            }
        ],
        "word_level_transcription": [
            {"id": "w1", "word": "Hello", "start": 0, "end": 1}
        ],
    }

    assert transcript_data_migration._manifest_extras_for_storage(manifest_data) == {
        "version": 2
    }


@with_institution(11, "Test Institution")
async def test_process_claimed_manifest_run_reuses_transcript_data(
    db, institution, monkeypatch
):
    lease_token = "lease-token"
    existing_manifest = schemas.LectureVideoManifestV4.model_validate(
        lecture_video_manifest_v4()
    )
    generated_manifest = existing_manifest.model_copy(
        update={
            "questions": [
                existing_manifest.questions[0].model_copy(
                    update={"question_text": "Generated replacement?"}
                )
            ]
        }
    )
    calls: list[tuple[str, object]] = []

    class FakeGeminiAio:
        async def __aenter__(self) -> SimpleNamespace:
            return SimpleNamespace(name="fake-gemini-client")

        async def __aexit__(self, *args: object) -> None:
            return None

    class FakeGeminiClient:
        def __init__(self, *, api_key: str) -> None:
            calls.append(("gemini-client", api_key))
            self.aio = FakeGeminiAio()

    async def fail_transcribe_video_words(
        video_path: str,
        openai_client: SimpleNamespace,
        *,
        temp_dir: str,
    ) -> list[schemas.LectureVideoManifestWordV3]:
        raise AssertionError("Whisper should not run when transcript_data exists.")

    async def fake_upload_and_generate_manifest(
        **kwargs: object,
    ) -> schemas.LectureVideoManifestV4:
        calls.append(("generate", kwargs))
        assert kwargs["transcript"] == existing_manifest.word_level_transcription
        return generated_manifest

    async def fake_get_gemini_client_by_class_id(
        session: AsyncSession,
        class_id: int,
    ) -> FakeGeminiClient:
        return FakeGeminiClient(api_key=f"fake-gemini-key-{class_id}")

    monkeypatch.setattr(
        lecture_video_processing,
        "get_openai_client_by_class_id",
        AsyncMock(return_value=SimpleNamespace(name="fake-openai-client")),
    )
    monkeypatch.setattr(
        lecture_video_processing.gemini,
        "get_gemini_client_by_class_id",
        fake_get_gemini_client_by_class_id,
    )
    monkeypatch.setattr(
        lecture_video_processing,
        "_write_video_to_temp_path",
        AsyncMock(return_value="/tmp/fake-video.mp4"),
    )
    monkeypatch.setattr(
        lecture_video_processing.lecture_video_manifest_generation,
        "transcribe_video_words",
        fail_transcribe_video_words,
    )
    monkeypatch.setattr(
        lecture_video_processing.lecture_video_manifest_generation,
        "upload_and_generate_manifest",
        fake_upload_and_generate_manifest,
    )

    async with db.async_session() as session:
        class_ = models.Class(
            id=1,
            name="Lecture Class",
            institution_id=institution.id,
            api_key="sk-test",
        )
        lecture_video = make_lecture_video(
            1,
            "retry-with-transcript-data.mp4",
            status=schemas.LectureVideoStatus.PROCESSING.value,
        )
        assistant = models.Assistant(
            name="Lecture Assistant",
            class_id=1,
            interaction_mode=schemas.InteractionMode.LECTURE_VIDEO,
            version=3,
            lecture_video=lecture_video,
            instructions="You are a lecture assistant.",
            model="gpt-4o-mini",
            tools="[]",
            use_latex=False,
            use_image_descriptions=False,
            hide_prompt=False,
        )
        session.add_all([class_, lecture_video, assistant])
        await session.flush()
        await lecture_video_service.persist_manifest(
            session,
            lecture_video,
            existing_manifest,
            create_narration_placeholders=False,
        )
        lecture_video.status = schemas.LectureVideoStatus.PROCESSING
        run = await models.LectureVideoProcessingRun.create(
            session,
            lecture_video_id=lecture_video.id,
            lecture_video_id_snapshot=lecture_video.id,
            class_id=class_.id,
            assistant_id_at_start=None,
            stage=schemas.LectureVideoProcessingStage.MANIFEST_GENERATION,
            attempt_number=1,
            status=schemas.LectureVideoProcessingRunStatus.RUNNING,
        )
        run.lease_token = lease_token
        run_id = run.id
        await session.commit()

    await lecture_video_processing._process_claimed_manifest_run(run_id, lease_token)

    assert [call[0] for call in calls] == [
        "gemini-client",
        "generate",
    ]
