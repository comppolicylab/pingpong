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
    make_lecture_video,
)
from .testutil import with_institution


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
        schemas.LectureVideoManifestV3.model_validate(lecture_video_manifest_v3()),
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
    manifest = schemas.LectureVideoManifestV3.model_validate(
        lecture_video_manifest_v3()
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

    async def fake_upload_video_to_gemini(
        video_path: str,
        gemini_client: SimpleNamespace,
    ) -> SimpleNamespace:
        calls.append(("upload", (video_path, gemini_client)))
        return SimpleNamespace(name="gemini-files/test")

    async def fake_generate_manifest(
        **kwargs: object,
    ) -> schemas.LectureVideoManifestV3:
        calls.append(("generate", kwargs))
        return manifest

    async def fake_delete_gemini_file(
        name: str | None,
        gemini_client: SimpleNamespace,
    ) -> None:
        calls.append(("delete", (name, gemini_client)))

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
        "upload_video_to_gemini",
        fake_upload_video_to_gemini,
    )
    monkeypatch.setattr(
        lecture_video_processing.lecture_video_manifest_generation,
        "generate_manifest",
        fake_generate_manifest,
    )
    monkeypatch.setattr(
        lecture_video_processing.lecture_video_manifest_generation,
        "delete_gemini_file",
        fake_delete_gemini_file,
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
    assert refreshed_video.manifest_version == 3
    assert [call[0] for call in calls] == [
        "gemini-client",
        "transcribe",
        "upload",
        "generate",
        "delete",
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


async def test_upload_and_generate_manifest_deletes_gemini_upload_on_failure(
    monkeypatch,
):
    calls: list[tuple[str, object]] = []
    transcript = schemas.LectureVideoManifestV3.model_validate(
        lecture_video_manifest_v3()
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

    async def fake_upload_video_to_gemini(
        video_path: str,
        gemini_client: SimpleNamespace,
    ) -> SimpleNamespace:
        calls.append(("upload", (video_path, gemini_client)))
        return SimpleNamespace(name="gemini-files/test")

    async def fake_generate_manifest(
        **kwargs: object,
    ) -> schemas.LectureVideoManifestV3:
        calls.append(("generate", kwargs))
        raise RuntimeError("generation failed")

    async def fake_delete_gemini_file(
        name: str | None,
        gemini_client: SimpleNamespace,
    ) -> None:
        calls.append(("delete", (name, gemini_client)))

    monkeypatch.setattr(
        lecture_video_processing.lecture_video_manifest_generation,
        "upload_video_to_gemini",
        fake_upload_video_to_gemini,
    )
    monkeypatch.setattr(
        lecture_video_processing.lecture_video_manifest_generation,
        "generate_manifest",
        fake_generate_manifest,
    )
    monkeypatch.setattr(
        lecture_video_processing.lecture_video_manifest_generation,
        "delete_gemini_file",
        fake_delete_gemini_file,
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
        )

    assert [call[0] for call in calls] == [
        "gemini-client",
        "upload",
        "generate",
        "delete",
    ]
    delete_args = calls[-1][1]
    assert isinstance(delete_args, tuple)
    assert delete_args[0] == "gemini-files/test"


@with_institution(11, "Test Institution")
async def test_existing_manifest_transcript_requires_loaded_manifest_data(
    db, institution
):
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
        loaded_video = await models.LectureVideo.get_by_id(session, lecture_video_id)
        assert loaded_video is not None

        with pytest.raises(RuntimeError, match="manifest_data must be loaded"):
            lecture_video_processing._existing_manifest_transcript(loaded_video)
