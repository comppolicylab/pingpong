import asyncio
import importlib
import io
import logging
import queue as queue_module
import signal
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Literal
from unittest.mock import AsyncMock

import pytest
from click.testing import CliRunner
from fastapi import HTTPException, UploadFile
from pydantic import ValidationError
from sqlalchemy import delete, func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

import pingpong.schemas as schemas
from pingpong import (
    class_credentials as class_credentials_module,
    elevenlabs as elevenlabs_module,
    lecture_video_processing,
    lecture_video_runtime,
    lecture_video_service,
    models,
    worker_pool as worker_pool_module,
)
from pingpong.animal_hash import pseudonym
from pingpong.authz.openfga import OpenFgaAuthzClient
from pingpong.class_credential_validation import (
    ClassCredentialValidationUnavailableError,
)
from pingpong.config import LocalAudioStoreSettings, LocalVideoStoreSettings

from .testutil import with_authz, with_institution, with_user

DEFAULT_LECTURE_VIDEO_VOICE_ID = "voice-test-id"
server_module = importlib.import_module("pingpong.server")
cli_module = importlib.import_module("pingpong.__main__")


class FakeQueue:
    def __init__(self) -> None:
        self.items: list[object] = []
        self.puts: list[object] = []
        self.closed = False
        self.join_thread_called = False

    def put(self, item: object) -> None:
        self.items.append(item)
        self.puts.append(item)

    def get(self) -> object:
        return self.get_nowait()

    def get_nowait(self) -> object:
        if not self.items:
            raise queue_module.Empty
        return self.items.pop(0)

    def close(self) -> None:
        self.closed = True

    def join_thread(self) -> None:
        self.join_thread_called = True


class FakeProcess:
    next_pid = 5000

    def __init__(self, target=None, args=(), daemon=None) -> None:  # type: ignore[no-untyped-def]
        self.target = target
        self.args = args
        self.daemon = daemon
        self.pid: int | None = None
        self.exitcode: int | None = None
        self.join_calls: list[float | None] = []
        self.terminate_called = False
        self.exit_after_join: int | None = None

    def start(self) -> None:
        self.pid = FakeProcess.next_pid
        FakeProcess.next_pid += 1

    def join(self, timeout: float | None = None) -> None:
        self.join_calls.append(timeout)
        if self.exitcode is None and self.exit_after_join is not None:
            self.exitcode = self.exit_after_join

    def terminate(self) -> None:
        self.terminate_called = True
        self.exitcode = -15


class FakeProcessContext:
    def __init__(self) -> None:
        self.queues: list[FakeQueue] = []
        self.processes: list[FakeProcess] = []

    def Queue(self) -> FakeQueue:  # noqa: N802
        queue = FakeQueue()
        self.queues.append(queue)
        return queue

    def Process(self, target=None, args=(), daemon=None) -> FakeProcess:  # noqa: N802
        process = FakeProcess(target=target, args=args, daemon=daemon)
        self.processes.append(process)
        return process


@pytest.fixture(autouse=True)
def mock_lecture_video_voice_validation(monkeypatch):
    monkeypatch.setattr(
        server_module,
        "synthesize_elevenlabs_voice_sample",
        AsyncMock(return_value=("Sample phrase", "audio/ogg", b"fake-audio")),
    )


def _parse_timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def make_lecture_video(
    class_id: int,
    key: str,
    *,
    filename: str | None = None,
    status: str = schemas.LectureVideoStatus.READY.value,
    content_length: int = 0,
    uploader_id: int | None = None,
    voice_id: str | None = None,
) -> models.LectureVideo:
    effective_filename = filename or key
    content_type = "video/webm" if key.endswith(".webm") else "video/mp4"
    return models.LectureVideo(
        class_id=class_id,
        stored_object=models.LectureVideoStoredObject(
            key=key,
            original_filename=effective_filename,
            content_type=content_type,
            content_length=content_length,
        ),
        status=status,
        uploader_id=uploader_id,
        voice_id=voice_id,
    )


def lecture_video_manifest(
    *,
    question_text: str = "What is the right answer?",
    question_type: str = "single_select",
    stop_offset_ms: int = 1000,
    continue_offset_ms: int = 1500,
    intro_text: str = "Intro narration",
    post_answer_texts: tuple[str, str] = ("Correct answer", "Try again"),
    correct_flags: tuple[bool, bool] = (True, False),
) -> dict:
    return {
        "version": 1,
        "questions": [
            {
                "type": question_type,
                "question_text": question_text,
                "intro_text": intro_text,
                "stop_offset_ms": stop_offset_ms,
                "options": [
                    {
                        "option_text": "Option A",
                        "post_answer_text": post_answer_texts[0],
                        "continue_offset_ms": continue_offset_ms,
                        "correct": correct_flags[0],
                    },
                    {
                        "option_text": "Option B",
                        "post_answer_text": post_answer_texts[1],
                        "continue_offset_ms": continue_offset_ms + 500,
                        "correct": correct_flags[1],
                    },
                ],
            }
        ],
    }


async def create_lecture_video_copy_credentials(
    session: AsyncSession,
    class_id: int,
    *,
    gemini_key: str = "shared-gemini-key",
    elevenlabs_key: str = "shared-elevenlabs-key",
) -> None:
    await models.ClassCredential.create(
        session,
        class_id,
        schemas.ClassCredentialPurpose.LECTURE_VIDEO_MANIFEST_GENERATION,
        gemini_key,
        schemas.ClassCredentialProvider.GEMINI,
    )
    await models.ClassCredential.create(
        session,
        class_id,
        schemas.ClassCredentialPurpose.LECTURE_VIDEO_NARRATION_TTS,
        elevenlabs_key,
        schemas.ClassCredentialProvider.ELEVENLABS,
    )


def fake_class_models_response(model_id: str = "gpt-4o-mini") -> dict:
    return {
        "models": [
            {
                "id": model_id,
                "created": datetime(2024, 1, 1, tzinfo=UTC),
                "owner": "openai",
                "name": "Test model",
                "sort_order": 1.0,
                "description": "Test model",
                "type": "chat",
                "is_latest": True,
                "is_new": False,
                "highlight": False,
                "supports_classic_assistants": True,
                "supports_next_gen_assistants": True,
                "supports_minimal_reasoning_effort": False,
                "supports_none_reasoning_effort": False,
                "supports_tools_with_none_reasoning_effort": False,
                "supports_verbosity": True,
                "supports_web_search": True,
                "supports_mcp_server": True,
                "supports_vision": True,
                "supports_file_search": True,
                "supports_code_interpreter": True,
                "supports_temperature": True,
                "supports_temperature_with_reasoning_none": False,
                "supports_reasoning": False,
            }
        ],
        "default_prompts": [],
        "enforce_classic_assistants": False,
        "lecture_video": {
            "show_mode_in_assistant_editor": True,
            "can_select_mode_in_assistant_editor": True,
            "message": "Lecture Video mode is in active development.",
        },
    }


def patch_lecture_video_model_list(monkeypatch, model_id: str = "gpt-4o-mini") -> None:
    async def fake_list_class_models(class_id: str, request, openai_client):  # type: ignore[no-untyped-def]
        return fake_class_models_response(model_id=model_id)

    server_module = importlib.import_module("pingpong.server")
    monkeypatch.setattr(server_module, "list_class_models", fake_list_class_models)


async def grant_thread_permissions(config, thread_id: int, *user_ids: int) -> None:  # type: ignore[no-untyped-def]
    async with config.authz.driver.get_client() as authz_client:
        await authz_client.write(
            grant=[
                (f"user:{user_id}", relation, f"thread:{thread_id}")
                for user_id in user_ids
                for relation in ("can_view", "can_participate")
            ]
        )


async def create_ready_lecture_video_assistant(
    session,
    institution,
    *,
    class_id: int = 1,
    assistant_id: int = 1,
    lecture_video_id: int = 1,
    video_key: str = "lecture-runtime.mp4",
    manifest: dict | None = None,
):
    class_ = models.Class(
        id=class_id,
        name="Test Class",
        institution_id=institution.id,
        api_key="test-key",
    )
    session.add(class_)
    await session.flush()

    lecture_video = make_lecture_video(
        class_.id,
        video_key,
        filename=video_key,
        content_length=128,
    )
    lecture_video.id = lecture_video_id
    session.add(lecture_video)
    await session.flush()

    await lecture_video_service.persist_manifest(
        session,
        lecture_video,
        schemas.LectureVideoManifestV1.model_validate(
            manifest or lecture_video_manifest()
        ),
        voice_id=DEFAULT_LECTURE_VIDEO_VOICE_ID,
        create_narration_placeholders=True,
    )
    loaded_lecture_video = await models.LectureVideo.get_by_id_with_copy_context(
        session, lecture_video.id
    )
    assert loaded_lecture_video is not None
    narration_index = 0
    for question in loaded_lecture_video.questions:
        if question.intro_narration is not None:
            await attach_ready_narration(
                session,
                question.intro_narration,
                key=f"ready-intro-{lecture_video.id}-{narration_index}.ogg",
            )
            narration_index += 1
        for option in question.options:
            if option.post_narration is not None:
                await attach_ready_narration(
                    session,
                    option.post_narration,
                    key=f"ready-option-{lecture_video.id}-{narration_index}.ogg",
                )
                narration_index += 1
    loaded_lecture_video.status = schemas.LectureVideoStatus.READY
    loaded_lecture_video.error_message = None
    session.add(loaded_lecture_video)
    await session.flush()

    assistant = models.Assistant(
        id=assistant_id,
        name="Lecture Assistant",
        class_id=class_.id,
        interaction_mode=schemas.InteractionMode.LECTURE_VIDEO,
        version=3,
        lecture_video_id=lecture_video.id,
        instructions="You are a lecture assistant.",
        model="gpt-4o-mini",
        tools="[]",
        use_latex=False,
        use_image_descriptions=False,
        hide_prompt=False,
    )
    session.add(assistant)
    await session.commit()
    return class_, lecture_video, assistant


async def create_processing_lecture_video_assistant(
    session,
    institution,
    *,
    class_id: int = 1,
    assistant_id: int = 1,
    lecture_video_id: int = 1,
    video_key: str = "lecture-processing.mp4",
    manifest: dict | None = None,
):
    class_ = models.Class(
        id=class_id,
        name="Processing Lecture Class",
        institution_id=institution.id,
        api_key="test-key",
    )
    session.add(class_)
    await session.flush()

    lecture_video = make_lecture_video(
        class_.id,
        video_key,
        filename=video_key,
        content_length=128,
        status=schemas.LectureVideoStatus.UPLOADED.value,
    )
    lecture_video.id = lecture_video_id
    session.add(lecture_video)
    await create_lecture_video_copy_credentials(session, class_.id)
    await session.flush()

    assistant = models.Assistant(
        id=assistant_id,
        name="Lecture Assistant",
        class_id=class_.id,
        interaction_mode=schemas.InteractionMode.LECTURE_VIDEO,
        version=3,
        lecture_video_id=lecture_video.id,
        instructions="You are a lecture assistant.",
        model="gpt-4o-mini",
        tools="[]",
        use_latex=False,
        use_image_descriptions=False,
        hide_prompt=False,
    )
    session.add(assistant)
    await session.flush()

    await lecture_video_service.persist_manifest(
        session,
        lecture_video,
        schemas.LectureVideoManifestV1.model_validate(
            manifest or lecture_video_manifest()
        ),
        voice_id=DEFAULT_LECTURE_VIDEO_VOICE_ID,
    )
    run = await lecture_video_processing.queue_narration_processing_run(
        session,
        lecture_video,
        assistant_id_at_start=assistant.id,
    )

    await session.commit()
    return class_, lecture_video, assistant, run


async def attach_ready_narration(
    session,
    narration: models.LectureVideoNarration,
    *,
    key: str,
    content_type: str = "audio/ogg",
    content_length: int = 16,
):
    stored_object = models.LectureVideoNarrationStoredObject(
        key=key,
        content_type=content_type,
        content_length=content_length,
    )
    session.add(stored_object)
    await session.flush()
    narration.stored_object_id = stored_object.id
    narration.stored_object = stored_object
    narration.status = schemas.LectureVideoNarrationStatus.READY
    await session.flush()


@pytest.mark.parametrize(
    ("content_type", "suffix"),
    [
        ("video/mp4", ".mp4"),
        ("video/webm", ".webm"),
    ],
)
def test_generate_store_key_uses_lv_prefix(content_type: str, suffix: str):
    key = lecture_video_service.generate_store_key(content_type)

    assert key.startswith("lv_")
    assert key.endswith(suffix)


def test_get_upload_size_requires_known_size():
    upload = UploadFile(
        file=io.BytesIO(b"video-bytes"),
        filename="lecture.mp4",
        size=None,
    )

    with pytest.raises(HTTPException) as exc_info:
        lecture_video_service.get_upload_size(upload)

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail == "Lecture video upload size could not be determined."


def test_lecture_video_question_prompt_requires_options_for_single_select():
    with pytest.raises(ValidationError) as exc_info:
        schemas.LectureVideoQuestionPrompt(
            id=1,
            type=schemas.LectureVideoQuestionType.SINGLE_SELECT,
            question_text="What is the right answer?",
            intro_text="Intro narration",
            stop_offset_ms=1000,
        )

    assert "options" in str(exc_info.value)


def test_lecture_video_session_rejects_negative_furthest_offset_ms():
    with pytest.raises(ValidationError) as exc_info:
        schemas.LectureVideoSession(
            state=schemas.LectureVideoSessionState.PLAYING,
            furthest_offset_ms=-1,
            state_version=1,
            controller=schemas.LectureVideoSessionController(),
        )

    assert "furthest_offset_ms" in str(exc_info.value)


@with_user(123)
@with_institution(11, "Test Institution")
@with_authz(
    grants=[
        ("user:123", "can_create_thread", "class:1"),
    ]
)
async def test_create_lecture_thread_success(api, db, institution, valid_user_token):
    async with db.async_session() as session:
        class_ = models.Class(
            id=1,
            name="Test Class",
            institution_id=institution.id,
            api_key="test-key",
        )
        session.add(class_)
        await session.commit()
        await session.refresh(class_)

        lecture_video = make_lecture_video(
            class_.id,
            "test-video-key.mp4",
            filename="Test Video.mp4",
        )
        session.add(lecture_video)
        await session.flush()

        assistant = models.Assistant(
            id=1,
            name="Lecture Assistant",
            class_id=class_.id,
            interaction_mode=schemas.InteractionMode.LECTURE_VIDEO,
            version=3,
            lecture_video_id=lecture_video.id,
            instructions="You are a lecture assistant.",
        )
        session.add(assistant)
        await session.commit()

    response = api.post(
        f"/api/v1/class/{class_.id}/thread/lecture",
        json={"assistant_id": 1},
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["thread"]["class_id"] == class_.id
    assert data["thread"]["assistant_id"] == 1
    assert data["thread"]["interaction_mode"] == "lecture_video"
    assert data["thread"]["lecture_video_id"] == lecture_video.id
    assert data["thread"]["name"] == "Lecture Presentation"
    assert data["thread"]["private"] is True
    assert data["session_token"] is None


@with_user(123)
@with_institution(11, "Test Institution")
@with_authz(
    grants=[
        ("user:123", "can_create_thread", "class:1"),
        ("user:123", "student", "class:1"),
    ]
)
async def test_get_thread_returns_lecture_video_session(
    api, authz, config, db, institution, valid_user_token
):
    async with db.async_session() as session:
        class_, _lecture_video, _assistant = await create_ready_lecture_video_assistant(
            session,
            institution,
        )

    create_response = api.post(
        f"/api/v1/class/{class_.id}/thread/lecture",
        json={"assistant_id": 1, "parties": [123]},
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )
    assert create_response.status_code == 200
    thread_id = create_response.json()["thread"]["id"]
    await grant_thread_permissions(config, thread_id, 123)

    response = api.get(
        f"/api/v1/class/{class_.id}/thread/{thread_id}",
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )
    assert response.status_code == 200
    session_data = response.json()["lecture_video_session"]
    assert session_data["state"] == "playing"
    assert session_data["last_known_offset_ms"] == 0
    assert session_data["furthest_offset_ms"] == 0
    assert session_data["latest_interaction_at"] is not None
    assert session_data["state_version"] == 1
    assert session_data["current_question"] is None
    assert session_data["current_continuation"] is None
    assert session_data["controller"]["has_control"] is False
    assert session_data["controller"]["has_active_controller"] is False
    assert session_data["controller"]["lease_expires_at"] is None
    assert response.json()["thread"]["is_current_user_participant"] is True


@with_user(123)
@with_institution(11, "Test Institution")
@with_authz(
    grants=[
        ("user:123", "can_view", "thread:1"),
        ("user:123", "supervisor", "class:1"),
    ]
)
async def test_get_thread_skips_lecture_video_checks_for_chat_threads(
    api, db, institution, user, valid_user_token, monkeypatch
):
    async with db.async_session() as session:
        db_user = await session.get(models.User, user.id)
        assert db_user is not None
        class_ = models.Class(
            id=1,
            name="Test Class",
            institution_id=institution.id,
            api_key="test-key",
        )
        assistant = models.Assistant(
            id=1,
            name="Chat Assistant",
            class_id=class_.id,
            creator_id=db_user.id,
            interaction_mode=schemas.InteractionMode.CHAT,
            version=3,
            model="gpt-4o-mini",
            instructions="Teach the lecture.",
            tools="[]",
        )
        thread = models.Thread(
            id=1,
            thread_id="chat-thread-1",
            class_id=class_.id,
            assistant_id=assistant.id,
            interaction_mode=schemas.InteractionMode.CHAT,
            version=3,
            private=False,
            display_user_info=False,
            tools_available="[]",
        )
        thread.users.append(db_user)
        session.add_all([class_, assistant, thread])
        await session.commit()

    async def fail_can_participate(request):  # type: ignore[no-untyped-def]
        raise AssertionError(
            "can_participate_thread should not be called for chat threads"
        )

    async def fail_get_thread_session(*args, **kwargs):  # type: ignore[no-untyped-def]
        raise AssertionError(
            "lecture_video_runtime.get_thread_session should not be called for chat threads"
        )

    server_module = importlib.import_module("pingpong.server")
    monkeypatch.setattr(server_module, "can_participate_thread", fail_can_participate)
    monkeypatch.setattr(
        server_module.lecture_video_runtime,
        "get_thread_session",
        fail_get_thread_session,
    )

    response = api.get(
        "/api/v1/class/1/thread/1",
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )

    assert response.status_code == 200
    assert response.json()["lecture_video_session"] is None
    assert response.json()["thread"]["is_current_user_participant"] is False


@with_user(123)
@with_institution(11, "Test Institution")
@with_authz(
    grants=[
        ("user:123", "can_create_thread", "class:1"),
        ("user:123", "student", "class:1"),
    ]
)
async def test_get_thread_lazily_initializes_legacy_lecture_video_runtime_state(
    api, authz, config, db, institution, valid_user_token
):
    async with db.async_session() as session:
        class_, _lecture_video, _assistant = await create_ready_lecture_video_assistant(
            session,
            institution,
        )

    create_response = api.post(
        f"/api/v1/class/{class_.id}/thread/lecture",
        json={"assistant_id": 1, "parties": [123]},
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )
    assert create_response.status_code == 200
    thread_id = create_response.json()["thread"]["id"]
    await grant_thread_permissions(config, thread_id, 123)

    async with db.async_session() as session:
        await session.execute(
            delete(models.LectureVideoInteraction).where(
                models.LectureVideoInteraction.thread_id == thread_id
            )
        )
        await session.execute(
            delete(models.LectureVideoThreadState).where(
                models.LectureVideoThreadState.thread_id == thread_id
            )
        )
        await session.commit()

    response = api.get(
        f"/api/v1/class/{class_.id}/thread/{thread_id}",
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )
    assert response.status_code == 200
    session_data = response.json()["lecture_video_session"]
    assert session_data["state"] == "playing"
    assert session_data["latest_interaction_at"] is not None

    async with db.async_session() as session:
        state = await models.LectureVideoThreadState.get_by_thread_id_with_context(
            session, thread_id
        )
        assert state is not None
        assert state.state == schemas.LectureVideoSessionState.PLAYING
        interactions = await models.LectureVideoInteraction.list_by_thread_id(
            session, thread_id
        )
        assert [interaction.event_type for interaction in interactions] == [
            schemas.LectureVideoInteractionEventType.SESSION_INITIALIZED
        ]


@with_user(123)
@with_institution(11, "Test Institution")
@with_authz(
    grants=[
        ("user:123", "can_create_thread", "class:1"),
        ("user:123", "student", "class:1"),
    ]
)
async def test_lecture_video_control_reacquire_invalidates_old_controller(
    api, authz, config, db, institution, valid_user_token
):
    async with db.async_session() as session:
        class_, _lecture_video, _assistant = await create_ready_lecture_video_assistant(
            session,
            institution,
        )

    create_response = api.post(
        f"/api/v1/class/{class_.id}/thread/lecture",
        json={"assistant_id": 1, "parties": [123]},
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )
    thread_id = create_response.json()["thread"]["id"]
    await grant_thread_permissions(config, thread_id, 123)

    acquire_one = api.post(
        f"/api/v1/class/{class_.id}/thread/{thread_id}/lecture-video/control/acquire",
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )
    assert acquire_one.status_code == 200
    controller_one = acquire_one.json()["controller_session_id"]
    version_one = acquire_one.json()["lecture_video_session"]["state_version"]

    acquire_two = api.post(
        f"/api/v1/class/{class_.id}/thread/{thread_id}/lecture-video/control/acquire",
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )
    assert acquire_two.status_code == 200
    controller_two = acquire_two.json()["controller_session_id"]
    assert controller_two != controller_one
    assert (
        acquire_two.json()["lecture_video_session"]["controller"]["has_control"] is True
    )

    response = api.post(
        f"/api/v1/class/{class_.id}/thread/{thread_id}/lecture-video/interactions",
        json={
            "type": "video_paused",
            "controller_session_id": controller_one,
            "expected_state_version": version_one,
            "idempotency_key": "stale-window",
            "offset_ms": 500,
        },
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )
    assert response.status_code == 409
    assert "no longer controls" in response.json()["detail"]


@with_user(123)
@with_institution(11, "Test Institution")
@with_authz(
    grants=[
        ("user:123", "can_create_thread", "class:1"),
        ("user:123", "student", "class:1"),
    ]
)
async def test_lecture_video_duplicate_idempotent_request_from_old_controller_is_rejected(
    api, authz, config, db, institution, valid_user_token
):
    async with db.async_session() as session:
        class_, _lecture_video, _assistant = await create_ready_lecture_video_assistant(
            session,
            institution,
        )

    create_response = api.post(
        f"/api/v1/class/{class_.id}/thread/lecture",
        json={"assistant_id": 1, "parties": [123]},
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )
    thread_id = create_response.json()["thread"]["id"]
    await grant_thread_permissions(config, thread_id, 123)

    acquire_one = api.post(
        f"/api/v1/class/{class_.id}/thread/{thread_id}/lecture-video/control/acquire",
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )
    assert acquire_one.status_code == 200
    controller_one = acquire_one.json()["controller_session_id"]
    version_one = acquire_one.json()["lecture_video_session"]["state_version"]

    initial_interaction = api.post(
        f"/api/v1/class/{class_.id}/thread/{thread_id}/lecture-video/interactions",
        json={
            "type": "video_paused",
            "controller_session_id": controller_one,
            "expected_state_version": version_one,
            "idempotency_key": "pause-once",
            "offset_ms": 500,
        },
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )
    assert initial_interaction.status_code == 200

    acquire_two = api.post(
        f"/api/v1/class/{class_.id}/thread/{thread_id}/lecture-video/control/acquire",
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )
    assert acquire_two.status_code == 200
    assert acquire_two.json()["controller_session_id"] != controller_one

    replay_from_old_controller = api.post(
        f"/api/v1/class/{class_.id}/thread/{thread_id}/lecture-video/interactions",
        json={
            "type": "video_paused",
            "controller_session_id": controller_one,
            "expected_state_version": initial_interaction.json()[
                "lecture_video_session"
            ]["state_version"],
            "idempotency_key": "pause-once",
            "offset_ms": 500,
        },
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )
    assert replay_from_old_controller.status_code == 409
    assert "no longer controls" in replay_from_old_controller.json()["detail"]


@with_user(123)
@with_institution(11, "Test Institution")
@with_authz(
    grants=[
        ("user:123", "can_create_thread", "class:1"),
        ("user:123", "student", "class:1"),
    ]
)
async def test_process_interaction_rejects_unhandled_request_subclass(
    api, authz, config, db, institution, valid_user_token
):
    class UnhandledPausedRequest(schemas.LectureVideoInteractionRequestBase):
        type: Literal["video_paused"]
        offset_ms: int

    async with db.async_session() as session:
        class_, _lecture_video, _assistant = await create_ready_lecture_video_assistant(
            session,
            institution,
        )

    create_response = api.post(
        f"/api/v1/class/{class_.id}/thread/lecture",
        json={"assistant_id": 1, "parties": [123]},
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )
    assert create_response.status_code == 200
    thread_id = create_response.json()["thread"]["id"]
    await grant_thread_permissions(config, thread_id, 123)

    acquire = api.post(
        f"/api/v1/class/{class_.id}/thread/{thread_id}/lecture-video/control/acquire",
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )
    assert acquire.status_code == 200
    lease_expires_at = _parse_timestamp(
        acquire.json()["lecture_video_session"]["controller"]["lease_expires_at"]
    )

    request_data = UnhandledPausedRequest(
        type="video_paused",
        controller_session_id=acquire.json()["controller_session_id"],
        expected_state_version=acquire.json()["lecture_video_session"]["state_version"],
        idempotency_key="unhandled-subclass",
        offset_ms=500,
    )

    async with db.async_session() as session:
        with pytest.raises(TypeError, match="Unhandled lecture video interaction"):
            await lecture_video_runtime.process_interaction(
                session,
                thread_id,
                123,
                request_data,
                nowfn=lambda: lease_expires_at - timedelta(seconds=1),
            )


@with_user(123)
@with_institution(11, "Test Institution")
@with_authz(
    grants=[
        ("user:123", "can_create_thread", "class:1"),
        ("user:123", "student", "class:1"),
    ]
)
async def test_lecture_video_interactions_derive_continuation_and_history(
    api, authz, config, db, institution, valid_user_token
):
    manifest = {
        "version": 1,
        "questions": [
            lecture_video_manifest()["questions"][0],
            {
                "type": "single_select",
                "question_text": "What comes next?",
                "intro_text": "Second intro",
                "stop_offset_ms": 2500,
                "options": [
                    {
                        "option_text": "Continue",
                        "post_answer_text": "Nice work",
                        "continue_offset_ms": 3000,
                        "correct": True,
                    },
                    {
                        "option_text": "Stop",
                        "post_answer_text": "Not this one",
                        "continue_offset_ms": 3200,
                        "correct": False,
                    },
                ],
            },
        ],
    }

    async with db.async_session() as session:
        class_, lecture_video, _assistant = await create_ready_lecture_video_assistant(
            session,
            institution,
            manifest=manifest,
        )
        questions = list(
            (
                await session.scalars(
                    select(models.LectureVideoQuestion)
                    .where(
                        models.LectureVideoQuestion.lecture_video_id == lecture_video.id
                    )
                    .order_by(models.LectureVideoQuestion.position)
                )
            ).all()
        )
        options = {
            question.id: list(
                (
                    await session.scalars(
                        select(models.LectureVideoQuestionOption)
                        .where(
                            models.LectureVideoQuestionOption.question_id == question.id
                        )
                        .order_by(models.LectureVideoQuestionOption.position)
                    )
                ).all()
            )
            for question in questions
        }

    create_response = api.post(
        f"/api/v1/class/{class_.id}/thread/lecture",
        json={"assistant_id": 1, "parties": [123]},
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )
    thread_id = create_response.json()["thread"]["id"]
    await grant_thread_permissions(config, thread_id, 123)

    acquire = api.post(
        f"/api/v1/class/{class_.id}/thread/{thread_id}/lecture-video/control/acquire",
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )
    assert acquire.status_code == 200
    controller_session_id = acquire.json()["controller_session_id"]
    state_version = acquire.json()["lecture_video_session"]["state_version"]

    present_response = api.post(
        f"/api/v1/class/{class_.id}/thread/{thread_id}/lecture-video/interactions",
        json={
            "type": "question_presented",
            "controller_session_id": controller_session_id,
            "expected_state_version": state_version,
            "idempotency_key": "question-1-presented",
            "question_id": questions[0].id,
            "offset_ms": questions[0].stop_offset_ms,
        },
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )
    assert present_response.status_code == 200
    current_question = present_response.json()["lecture_video_session"][
        "current_question"
    ]
    assert current_question["options"][0]["post_answer_text"] is None
    assert current_question["options"][1]["post_answer_text"] is None

    answer_response = api.post(
        f"/api/v1/class/{class_.id}/thread/{thread_id}/lecture-video/interactions",
        json={
            "type": "answer_submitted",
            "controller_session_id": controller_session_id,
            "expected_state_version": present_response.json()["lecture_video_session"][
                "state_version"
            ],
            "idempotency_key": "question-1-answer",
            "question_id": questions[0].id,
            "option_id": options[questions[0].id][0].id,
        },
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )
    assert answer_response.status_code == 200
    continuation = answer_response.json()["lecture_video_session"][
        "current_continuation"
    ]
    assert (
        continuation["resume_offset_ms"]
        == options[questions[0].id][0].continue_offset_ms
    )
    assert "post_answer_narration_id" in continuation
    assert continuation["next_question"]["id"] == questions[1].id

    duplicate_answer = api.post(
        f"/api/v1/class/{class_.id}/thread/{thread_id}/lecture-video/interactions",
        json={
            "type": "answer_submitted",
            "controller_session_id": controller_session_id,
            "expected_state_version": answer_response.json()["lecture_video_session"][
                "state_version"
            ],
            "idempotency_key": "question-1-answer",
            "question_id": questions[0].id,
            "option_id": options[questions[0].id][0].id,
        },
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )
    assert duplicate_answer.status_code == 200
    assert (
        duplicate_answer.json()["lecture_video_session"]["state_version"]
        == answer_response.json()["lecture_video_session"]["state_version"]
    )

    refreshed_thread = api.get(
        f"/api/v1/class/{class_.id}/thread/{thread_id}",
        headers={
            "Authorization": f"Bearer {valid_user_token}",
            "X-Lecture-Video-Controller-Session": controller_session_id,
        },
    )
    assert refreshed_thread.status_code == 200
    refreshed_continuation = refreshed_thread.json()["lecture_video_session"][
        "current_continuation"
    ]
    assert refreshed_continuation == continuation
    assert (
        refreshed_thread.json()["lecture_video_session"]["controller"]["has_control"]
        is True
    )

    resume_response = api.post(
        f"/api/v1/class/{class_.id}/thread/{thread_id}/lecture-video/interactions",
        json={
            "type": "video_resumed",
            "controller_session_id": controller_session_id,
            "expected_state_version": answer_response.json()["lecture_video_session"][
                "state_version"
            ],
            "idempotency_key": "question-1-resume",
            "offset_ms": options[questions[0].id][0].continue_offset_ms,
        },
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )
    assert resume_response.status_code == 200
    resumed_session = resume_response.json()["lecture_video_session"]
    assert resumed_session["state"] == "playing"
    assert resumed_session["current_question"]["id"] == questions[1].id
    assert resumed_session["current_continuation"] is None

    second_present_response = api.post(
        f"/api/v1/class/{class_.id}/thread/{thread_id}/lecture-video/interactions",
        json={
            "type": "question_presented",
            "controller_session_id": controller_session_id,
            "expected_state_version": resumed_session["state_version"],
            "idempotency_key": "question-2-presented",
            "question_id": questions[1].id,
            "offset_ms": questions[1].stop_offset_ms,
        },
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )
    assert second_present_response.status_code == 200

    stale_version = api.post(
        f"/api/v1/class/{class_.id}/thread/{thread_id}/lecture-video/interactions",
        json={
            "type": "video_paused",
            "controller_session_id": controller_session_id,
            "expected_state_version": 1,
            "idempotency_key": "stale-version",
            "offset_ms": 1234,
        },
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )
    assert stale_version.status_code == 409
    assert "out of date" in stale_version.json()["detail"]

    history_response = api.get(
        f"/api/v1/class/{class_.id}/thread/{thread_id}/lecture-video/history",
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )
    assert history_response.status_code == 200
    history = history_response.json()["interactions"]
    assert [item["event_index"] for item in history] == [2, 3, 5]
    assert [item["event_type"] for item in history] == [
        "question_presented",
        "answer_submitted",
        "question_presented",
    ]
    assert history[0]["actor_name"] == "Me"
    assert history[0]["question_text"] == questions[0].question_text
    assert history[0]["offset_ms"] == questions[0].stop_offset_ms
    assert history[0]["correct_option_id"] == options[questions[0].id][0].id
    assert history[0]["question_options"][0]["post_answer_text"] is None
    assert history[0]["question_options"][1]["post_answer_text"] is None
    assert history[1]["actor_name"] == "Me"
    assert history[1]["question_text"] == questions[0].question_text
    assert history[1]["correct_option_id"] == options[questions[0].id][0].id
    assert history[1]["option_text"] == options[questions[0].id][0].option_text
    assert history[1]["question_options"][0]["post_answer_text"] == "Correct answer"
    assert history[1]["question_options"][1]["post_answer_text"] is None
    assert history[2]["actor_name"] == "Me"
    assert history[2]["question_text"] == questions[1].question_text
    assert history[2]["offset_ms"] == questions[1].stop_offset_ms
    assert history[2]["correct_option_id"] is None
    assert history[2]["question_options"][0]["post_answer_text"] is None
    assert history[2]["question_options"][1]["post_answer_text"] is None


@with_user(123)
@with_institution(11, "Test Institution")
@with_authz(
    grants=[
        ("user:123", "can_create_thread", "class:1"),
        ("user:123", "student", "class:1"),
    ]
)
async def test_lecture_video_playback_events_are_rejected_while_awaiting_answer(
    api, authz, config, db, institution, valid_user_token
):
    async with db.async_session() as session:
        class_, lecture_video, _assistant = await create_ready_lecture_video_assistant(
            session,
            institution,
        )
        lecture_video = await models.LectureVideo.get_by_id_with_copy_context(
            session, lecture_video.id
        )
        question = lecture_video.questions[0]

    create_response = api.post(
        f"/api/v1/class/{class_.id}/thread/lecture",
        json={"assistant_id": 1, "parties": [123]},
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )
    assert create_response.status_code == 200
    thread_id = create_response.json()["thread"]["id"]
    await grant_thread_permissions(config, thread_id, 123)

    acquire = api.post(
        f"/api/v1/class/{class_.id}/thread/{thread_id}/lecture-video/control/acquire",
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )
    assert acquire.status_code == 200
    controller_session_id = acquire.json()["controller_session_id"]

    question_presented = api.post(
        f"/api/v1/class/{class_.id}/thread/{thread_id}/lecture-video/interactions",
        json={
            "type": "question_presented",
            "controller_session_id": controller_session_id,
            "expected_state_version": acquire.json()["lecture_video_session"][
                "state_version"
            ],
            "idempotency_key": "question-presented",
            "question_id": question.id,
            "offset_ms": question.stop_offset_ms,
        },
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )
    assert question_presented.status_code == 200
    awaiting_answer_session = question_presented.json()["lecture_video_session"]
    assert awaiting_answer_session["state"] == "awaiting_answer"

    for payload in [
        {
            "type": "video_paused",
            "controller_session_id": controller_session_id,
            "expected_state_version": awaiting_answer_session["state_version"],
            "idempotency_key": "pause-during-question",
            "offset_ms": question.stop_offset_ms,
        },
        {
            "type": "video_seeked",
            "controller_session_id": controller_session_id,
            "expected_state_version": awaiting_answer_session["state_version"],
            "idempotency_key": "seek-during-question",
            "from_offset_ms": question.stop_offset_ms,
            "to_offset_ms": question.stop_offset_ms,
        },
        {
            "type": "video_ended",
            "controller_session_id": controller_session_id,
            "expected_state_version": awaiting_answer_session["state_version"],
            "idempotency_key": "end-during-question",
            "offset_ms": question.stop_offset_ms,
        },
    ]:
        response = api.post(
            f"/api/v1/class/{class_.id}/thread/{thread_id}/lecture-video/interactions",
            json=payload,
            headers={"Authorization": f"Bearer {valid_user_token}"},
        )
        assert response.status_code == 409
        assert (
            response.json()["detail"]
            == "The lecture video cannot process playback events right now."
        )

    async with db.async_session() as session:
        state = await models.LectureVideoThreadState.get_by_thread_id_with_context(
            session, thread_id
        )
        assert state is not None
        assert state.state == schemas.LectureVideoSessionState.AWAITING_ANSWER
        assert state.last_known_offset_ms == question.stop_offset_ms
        assert state.furthest_offset_ms == question.stop_offset_ms
        interactions = await models.LectureVideoInteraction.list_by_thread_id(
            session, thread_id
        )
        assert [interaction.event_type for interaction in interactions] == [
            schemas.LectureVideoInteractionEventType.SESSION_INITIALIZED,
            schemas.LectureVideoInteractionEventType.QUESTION_PRESENTED,
        ]


@with_user(123)
@with_institution(11, "Test Institution")
@with_authz(
    grants=[
        ("user:123", "can_create_thread", "class:1"),
        ("user:123", "student", "class:1"),
    ]
)
async def test_lecture_video_interactions_reject_post_completion_playback_events(
    api, authz, config, db, institution, valid_user_token
):
    async with db.async_session() as session:
        class_, lecture_video, _assistant = await create_ready_lecture_video_assistant(
            session,
            institution,
        )
        lecture_video = await models.LectureVideo.get_by_id_with_copy_context(
            session, lecture_video.id
        )
        question = lecture_video.questions[0]
        option = question.options[0]

    create_response = api.post(
        f"/api/v1/class/{class_.id}/thread/lecture",
        json={"assistant_id": 1, "parties": [123]},
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )
    thread_id = create_response.json()["thread"]["id"]
    await grant_thread_permissions(config, thread_id, 123)

    acquire = api.post(
        f"/api/v1/class/{class_.id}/thread/{thread_id}/lecture-video/control/acquire",
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )
    assert acquire.status_code == 200
    controller_session_id = acquire.json()["controller_session_id"]
    state_version = acquire.json()["lecture_video_session"]["state_version"]

    present_response = api.post(
        f"/api/v1/class/{class_.id}/thread/{thread_id}/lecture-video/interactions",
        json={
            "type": "question_presented",
            "controller_session_id": controller_session_id,
            "expected_state_version": state_version,
            "idempotency_key": "only-question-presented",
            "question_id": question.id,
            "offset_ms": question.stop_offset_ms,
        },
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )
    assert present_response.status_code == 200

    answer_response = api.post(
        f"/api/v1/class/{class_.id}/thread/{thread_id}/lecture-video/interactions",
        json={
            "type": "answer_submitted",
            "controller_session_id": controller_session_id,
            "expected_state_version": present_response.json()["lecture_video_session"][
                "state_version"
            ],
            "idempotency_key": "only-question-answer",
            "question_id": question.id,
            "option_id": option.id,
        },
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )
    assert answer_response.status_code == 200

    resume_response = api.post(
        f"/api/v1/class/{class_.id}/thread/{thread_id}/lecture-video/interactions",
        json={
            "type": "video_resumed",
            "controller_session_id": controller_session_id,
            "expected_state_version": answer_response.json()["lecture_video_session"][
                "state_version"
            ],
            "idempotency_key": "only-question-resume",
            "offset_ms": option.continue_offset_ms,
        },
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )
    assert resume_response.status_code == 200
    playing_session = resume_response.json()["lecture_video_session"]
    assert playing_session["state"] == "playing"

    # Video must play to end before session completes
    ended_response = api.post(
        f"/api/v1/class/{class_.id}/thread/{thread_id}/lecture-video/interactions",
        json={
            "type": "video_ended",
            "controller_session_id": controller_session_id,
            "expected_state_version": playing_session["state_version"],
            "idempotency_key": "video-ended",
            "offset_ms": option.continue_offset_ms + 1000,
        },
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )
    assert ended_response.status_code == 200
    completed_session = ended_response.json()["lecture_video_session"]
    assert completed_session["state"] == "completed"

    invalid_pause = api.post(
        f"/api/v1/class/{class_.id}/thread/{thread_id}/lecture-video/interactions",
        json={
            "type": "video_paused",
            "controller_session_id": controller_session_id,
            "expected_state_version": completed_session["state_version"],
            "idempotency_key": "post-completion-pause",
            "offset_ms": option.continue_offset_ms + 250,
        },
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )
    assert invalid_pause.status_code == 409
    assert invalid_pause.json()["detail"] == "Session is already completed."

    invalid_seek = api.post(
        f"/api/v1/class/{class_.id}/thread/{thread_id}/lecture-video/interactions",
        json={
            "type": "video_seeked",
            "controller_session_id": controller_session_id,
            "expected_state_version": completed_session["state_version"],
            "idempotency_key": "post-completion-seek",
            "from_offset_ms": option.continue_offset_ms,
            "to_offset_ms": option.continue_offset_ms + 500,
        },
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )
    assert invalid_seek.status_code == 409
    assert invalid_seek.json()["detail"] == "Session is already completed."

    invalid_end = api.post(
        f"/api/v1/class/{class_.id}/thread/{thread_id}/lecture-video/interactions",
        json={
            "type": "video_ended",
            "controller_session_id": controller_session_id,
            "expected_state_version": completed_session["state_version"],
            "idempotency_key": "post-completion-ended",
            "offset_ms": option.continue_offset_ms + 750,
        },
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )
    assert invalid_end.status_code == 409
    assert invalid_end.json()["detail"] == "Session is already completed."

    invalid_answer = api.post(
        f"/api/v1/class/{class_.id}/thread/{thread_id}/lecture-video/interactions",
        json={
            "type": "answer_submitted",
            "controller_session_id": controller_session_id,
            "expected_state_version": completed_session["state_version"],
            "idempotency_key": "post-completion-answer",
            "question_id": question.id,
            "option_id": option.id,
        },
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )
    assert invalid_answer.status_code == 409
    assert (
        invalid_answer.json()["detail"]
        == "This question is no longer accepting answers."
    )

    refreshed_thread = api.get(
        f"/api/v1/class/{class_.id}/thread/{thread_id}",
        headers={
            "Authorization": f"Bearer {valid_user_token}",
            "X-Lecture-Video-Controller-Session": controller_session_id,
        },
    )
    assert refreshed_thread.status_code == 200
    refreshed_session = refreshed_thread.json()["lecture_video_session"]
    assert refreshed_session["state"] == "completed"
    assert refreshed_session["state_version"] == completed_session["state_version"]
    assert (
        refreshed_session["last_known_offset_ms"]
        == completed_session["last_known_offset_ms"]
    )

    history_response = api.get(
        f"/api/v1/class/{class_.id}/thread/{thread_id}/lecture-video/history",
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )
    assert history_response.status_code == 200
    history = history_response.json()["interactions"]
    assert [item["event_type"] for item in history] == [
        "question_presented",
        "answer_submitted",
    ]
    assert history[0]["correct_option_id"] == option.id
    assert history[1]["correct_option_id"] == option.id


@with_user(123)
@with_institution(11, "Test Institution")
@with_authz(
    grants=[
        ("user:123", "can_create_thread", "class:1"),
        ("user:123", "student", "class:1"),
    ]
)
async def test_lecture_video_interactions_record_seek_and_end_events(
    api, authz, config, db, institution, valid_user_token
):
    async with db.async_session() as session:
        class_, _lecture_video, _assistant = await create_ready_lecture_video_assistant(
            session,
            institution,
        )

    create_response = api.post(
        f"/api/v1/class/{class_.id}/thread/lecture",
        json={"assistant_id": 1, "parties": [123]},
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )
    assert create_response.status_code == 200
    thread_id = create_response.json()["thread"]["id"]
    await grant_thread_permissions(config, thread_id, 123)

    acquire = api.post(
        f"/api/v1/class/{class_.id}/thread/{thread_id}/lecture-video/control/acquire",
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )
    assert acquire.status_code == 200
    controller_session_id = acquire.json()["controller_session_id"]
    state_version = acquire.json()["lecture_video_session"]["state_version"]

    progress_response = api.post(
        f"/api/v1/class/{class_.id}/thread/{thread_id}/lecture-video/interactions",
        json={
            "type": "video_resumed",
            "controller_session_id": controller_session_id,
            "expected_state_version": state_version,
            "idempotency_key": "resume-progress",
            "offset_ms": 1250,
        },
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )
    assert progress_response.status_code == 200

    seek_response = api.post(
        f"/api/v1/class/{class_.id}/thread/{thread_id}/lecture-video/interactions",
        json={
            "type": "video_seeked",
            "controller_session_id": controller_session_id,
            "expected_state_version": progress_response.json()["lecture_video_session"][
                "state_version"
            ],
            "idempotency_key": "seek-forward",
            "from_offset_ms": 1250,
            "to_offset_ms": 250,
        },
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )
    assert seek_response.status_code == 200
    seek_session = seek_response.json()["lecture_video_session"]
    assert seek_session["last_known_offset_ms"] == 250
    assert seek_session["furthest_offset_ms"] == 1250

    end_response = api.post(
        f"/api/v1/class/{class_.id}/thread/{thread_id}/lecture-video/interactions",
        json={
            "type": "video_ended",
            "controller_session_id": controller_session_id,
            "expected_state_version": seek_response.json()["lecture_video_session"][
                "state_version"
            ],
            "idempotency_key": "ended-once",
            "offset_ms": 1500,
        },
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )
    assert end_response.status_code == 200
    ended_session = end_response.json()["lecture_video_session"]
    assert ended_session["last_known_offset_ms"] == 1500
    assert ended_session["furthest_offset_ms"] == 1500
    assert ended_session["state"] == "playing"

    history_response = api.get(
        f"/api/v1/class/{class_.id}/thread/{thread_id}/lecture-video/history",
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )
    assert history_response.status_code == 200
    assert history_response.json()["interactions"] == []

    async with db.async_session() as session:
        interactions = await models.LectureVideoInteraction.list_by_thread_id(
            session, thread_id
        )
        state = await models.LectureVideoThreadState.get_by_thread_id_with_context(
            session, thread_id
        )

    assert [interaction.event_type for interaction in interactions] == [
        schemas.LectureVideoInteractionEventType.SESSION_INITIALIZED,
        schemas.LectureVideoInteractionEventType.VIDEO_RESUMED,
        schemas.LectureVideoInteractionEventType.VIDEO_SEEKED,
        schemas.LectureVideoInteractionEventType.VIDEO_ENDED,
    ]
    assert interactions[2].from_offset_ms == 1250
    assert interactions[2].to_offset_ms == 250
    assert interactions[3].offset_ms == 1500
    assert state is not None
    assert state.last_known_offset_ms == 1500
    assert state.furthest_offset_ms == 1500


@with_user(123)
@with_institution(11, "Test Institution")
@with_authz(
    grants=[
        ("user:123", "can_create_thread", "class:1"),
        ("user:123", "student", "class:1"),
    ]
)
async def test_lecture_video_interactions_reject_resume_past_unlocked_progress(
    api, authz, config, db, institution, valid_user_token
):
    async with db.async_session() as session:
        class_, _lecture_video, _assistant = await create_ready_lecture_video_assistant(
            session,
            institution,
        )

    create_response = api.post(
        f"/api/v1/class/{class_.id}/thread/lecture",
        json={"assistant_id": 1, "parties": [123]},
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )
    assert create_response.status_code == 200
    thread_id = create_response.json()["thread"]["id"]
    await grant_thread_permissions(config, thread_id, 123)

    acquire = api.post(
        f"/api/v1/class/{class_.id}/thread/{thread_id}/lecture-video/control/acquire",
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )
    assert acquire.status_code == 200

    response = api.post(
        f"/api/v1/class/{class_.id}/thread/{thread_id}/lecture-video/interactions",
        json={
            "type": "video_resumed",
            "controller_session_id": acquire.json()["controller_session_id"],
            "expected_state_version": acquire.json()["lecture_video_session"][
                "state_version"
            ],
            "idempotency_key": "forged-resume",
            "offset_ms": 9000,
        },
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )
    assert response.status_code == 422
    assert (
        response.json()["detail"]
        == "Resuming past your unlocked progress is not allowed in this lecture video."
    )


@with_user(123)
@with_institution(11, "Test Institution")
@with_authz(
    grants=[
        ("user:123", "can_create_thread", "class:1"),
        ("user:123", "student", "class:1"),
    ]
)
async def test_lecture_video_interactions_reject_question_presented_past_unlocked_progress(
    api, authz, config, db, institution, valid_user_token
):
    async with db.async_session() as session:
        class_, lecture_video, _assistant = await create_ready_lecture_video_assistant(
            session,
            institution,
            manifest=lecture_video_manifest(
                stop_offset_ms=5_000,
                continue_offset_ms=5_500,
            ),
        )
        lecture_video = await models.LectureVideo.get_by_id_with_copy_context(
            session, lecture_video.id
        )
        question = lecture_video.questions[0]

    create_response = api.post(
        f"/api/v1/class/{class_.id}/thread/lecture",
        json={"assistant_id": 1, "parties": [123]},
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )
    assert create_response.status_code == 200
    thread_id = create_response.json()["thread"]["id"]
    await grant_thread_permissions(config, thread_id, 123)

    acquire = api.post(
        f"/api/v1/class/{class_.id}/thread/{thread_id}/lecture-video/control/acquire",
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )
    assert acquire.status_code == 200

    response = api.post(
        f"/api/v1/class/{class_.id}/thread/{thread_id}/lecture-video/interactions",
        json={
            "type": "question_presented",
            "controller_session_id": acquire.json()["controller_session_id"],
            "expected_state_version": acquire.json()["lecture_video_session"][
                "state_version"
            ],
            "idempotency_key": "forged-question-presented",
            "question_id": question.id,
            "offset_ms": question.stop_offset_ms,
        },
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )
    assert response.status_code == 422
    assert (
        response.json()["detail"]
        == "Presenting a question past your unlocked progress is not allowed in this lecture video."
    )


@with_user(123)
@with_institution(11, "Test Institution")
@with_authz(
    grants=[
        ("user:123", "can_create_thread", "class:1"),
        ("user:123", "student", "class:1"),
    ]
)
async def test_lecture_video_interactions_reject_seek_with_forged_from_offset(
    api, authz, config, db, institution, valid_user_token
):
    async with db.async_session() as session:
        class_, _lecture_video, _assistant = await create_ready_lecture_video_assistant(
            session,
            institution,
        )

    create_response = api.post(
        f"/api/v1/class/{class_.id}/thread/lecture",
        json={"assistant_id": 1, "parties": [123]},
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )
    assert create_response.status_code == 200
    thread_id = create_response.json()["thread"]["id"]
    await grant_thread_permissions(config, thread_id, 123)

    acquire = api.post(
        f"/api/v1/class/{class_.id}/thread/{thread_id}/lecture-video/control/acquire",
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )
    assert acquire.status_code == 200

    response = api.post(
        f"/api/v1/class/{class_.id}/thread/{thread_id}/lecture-video/interactions",
        json={
            "type": "video_seeked",
            "controller_session_id": acquire.json()["controller_session_id"],
            "expected_state_version": acquire.json()["lecture_video_session"][
                "state_version"
            ],
            "idempotency_key": "forged-seek",
            "from_offset_ms": 9000,
            "to_offset_ms": 9000,
        },
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )
    assert response.status_code == 422
    assert (
        response.json()["detail"]
        == "Seeking past your unlocked progress is not allowed in this lecture video."
    )


@with_user(123)
@with_institution(11, "Test Institution")
@with_authz(
    grants=[
        ("user:123", "can_create_thread", "class:1"),
        ("user:123", "student", "class:1"),
    ]
)
async def test_lecture_video_interactions_ignore_forged_seek_from_offset_for_unlock_progress(
    api, authz, config, db, institution, valid_user_token
):
    async with db.async_session() as session:
        class_, _lecture_video, _assistant = await create_ready_lecture_video_assistant(
            session,
            institution,
        )

    create_response = api.post(
        f"/api/v1/class/{class_.id}/thread/lecture",
        json={"assistant_id": 1, "parties": [123]},
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )
    assert create_response.status_code == 200
    thread_id = create_response.json()["thread"]["id"]
    await grant_thread_permissions(config, thread_id, 123)

    acquire = api.post(
        f"/api/v1/class/{class_.id}/thread/{thread_id}/lecture-video/control/acquire",
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )
    assert acquire.status_code == 200
    controller_session_id = acquire.json()["controller_session_id"]

    seek_response = api.post(
        f"/api/v1/class/{class_.id}/thread/{thread_id}/lecture-video/interactions",
        json={
            "type": "video_seeked",
            "controller_session_id": controller_session_id,
            "expected_state_version": acquire.json()["lecture_video_session"][
                "state_version"
            ],
            "idempotency_key": "forged-backward-seek",
            "from_offset_ms": 900000,
            "to_offset_ms": 0,
        },
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )
    assert seek_response.status_code == 200
    seek_session = seek_response.json()["lecture_video_session"]
    assert seek_session["last_known_offset_ms"] == 0
    assert seek_session["furthest_offset_ms"] == 0

    resume_response = api.post(
        f"/api/v1/class/{class_.id}/thread/{thread_id}/lecture-video/interactions",
        json={
            "type": "video_resumed",
            "controller_session_id": controller_session_id,
            "expected_state_version": seek_session["state_version"],
            "idempotency_key": "resume-past-forged-progress",
            "offset_ms": 900000,
        },
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )
    assert resume_response.status_code == 422
    assert (
        resume_response.json()["detail"]
        == "Resuming past your unlocked progress is not allowed in this lecture video."
    )

    async with db.async_session() as session:
        state = await models.LectureVideoThreadState.get_by_thread_id_with_context(
            session, thread_id
        )

    assert state is not None
    assert state.last_known_offset_ms == 0
    assert state.furthest_offset_ms == 0


@with_user(123)
@with_institution(11, "Test Institution")
@with_authz(
    grants=[
        ("user:123", "can_create_thread", "class:1"),
        ("user:123", "student", "class:1"),
    ]
)
async def test_lecture_video_interactions_reject_stale_playing_resume_version(
    api, authz, config, db, institution, valid_user_token
):
    async with db.async_session() as session:
        class_, _lecture_video, _assistant = await create_ready_lecture_video_assistant(
            session,
            institution,
        )

    create_response = api.post(
        f"/api/v1/class/{class_.id}/thread/lecture",
        json={"assistant_id": 1, "parties": [123]},
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )
    assert create_response.status_code == 200
    thread_id = create_response.json()["thread"]["id"]
    await grant_thread_permissions(config, thread_id, 123)

    acquire = api.post(
        f"/api/v1/class/{class_.id}/thread/{thread_id}/lecture-video/control/acquire",
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )
    assert acquire.status_code == 200
    controller_session_id = acquire.json()["controller_session_id"]
    original_state_version = acquire.json()["lecture_video_session"]["state_version"]

    pause_response = api.post(
        f"/api/v1/class/{class_.id}/thread/{thread_id}/lecture-video/interactions",
        json={
            "type": "video_paused",
            "controller_session_id": controller_session_id,
            "expected_state_version": original_state_version,
            "idempotency_key": "pause-before-stale-resume",
            "offset_ms": 500,
        },
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )
    assert pause_response.status_code == 200

    stale_resume = api.post(
        f"/api/v1/class/{class_.id}/thread/{thread_id}/lecture-video/interactions",
        json={
            "type": "video_resumed",
            "controller_session_id": controller_session_id,
            "expected_state_version": original_state_version,
            "idempotency_key": "stale-playing-resume",
            "offset_ms": 250,
        },
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )
    assert stale_resume.status_code == 409
    assert "out of date" in stale_resume.json()["detail"]

    refreshed_thread = api.get(
        f"/api/v1/class/{class_.id}/thread/{thread_id}",
        headers={
            "Authorization": f"Bearer {valid_user_token}",
            "X-Lecture-Video-Controller-Session": controller_session_id,
        },
    )
    assert refreshed_thread.status_code == 200
    refreshed_session = refreshed_thread.json()["lecture_video_session"]
    assert (
        refreshed_session["state_version"]
        == pause_response.json()["lecture_video_session"]["state_version"]
    )
    assert refreshed_session["last_known_offset_ms"] == 500


@with_user(123)
@with_institution(11, "Test Institution")
@with_authz(
    grants=[
        ("user:123", "can_create_thread", "class:1"),
        ("user:123", "student", "class:1"),
    ]
)
async def test_lecture_video_answer_submitted_rejects_option_from_another_question(
    api, authz, config, db, institution, valid_user_token
):
    manifest = {
        "version": 1,
        "questions": [
            lecture_video_manifest()["questions"][0],
            {
                "type": "single_select",
                "question_text": "Second question?",
                "intro_text": "Second intro",
                "stop_offset_ms": 2500,
                "options": [
                    {
                        "option_text": "Wrong question option",
                        "post_answer_text": "Nope",
                        "continue_offset_ms": 3000,
                        "correct": True,
                    },
                    {
                        "option_text": "Another wrong question option",
                        "post_answer_text": "Still nope",
                        "continue_offset_ms": 3250,
                        "correct": False,
                    },
                ],
            },
        ],
    }

    async with db.async_session() as session:
        class_, lecture_video, _assistant = await create_ready_lecture_video_assistant(
            session,
            institution,
            manifest=manifest,
        )
        questions = list(
            (
                await session.scalars(
                    select(models.LectureVideoQuestion)
                    .where(
                        models.LectureVideoQuestion.lecture_video_id == lecture_video.id
                    )
                    .order_by(models.LectureVideoQuestion.position)
                )
            ).all()
        )
        second_question_option = (
            await session.scalars(
                select(models.LectureVideoQuestionOption)
                .where(models.LectureVideoQuestionOption.question_id == questions[1].id)
                .order_by(models.LectureVideoQuestionOption.position)
            )
        ).first()
        assert second_question_option is not None

    create_response = api.post(
        f"/api/v1/class/{class_.id}/thread/lecture",
        json={"assistant_id": 1, "parties": [123]},
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )
    assert create_response.status_code == 200
    thread_id = create_response.json()["thread"]["id"]
    await grant_thread_permissions(config, thread_id, 123)

    acquire = api.post(
        f"/api/v1/class/{class_.id}/thread/{thread_id}/lecture-video/control/acquire",
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )
    assert acquire.status_code == 200
    controller_session_id = acquire.json()["controller_session_id"]
    state_version = acquire.json()["lecture_video_session"]["state_version"]

    present_response = api.post(
        f"/api/v1/class/{class_.id}/thread/{thread_id}/lecture-video/interactions",
        json={
            "type": "question_presented",
            "controller_session_id": controller_session_id,
            "expected_state_version": state_version,
            "idempotency_key": "question-presented",
            "question_id": questions[0].id,
            "offset_ms": questions[0].stop_offset_ms,
        },
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )
    assert present_response.status_code == 200

    invalid_option_response = api.post(
        f"/api/v1/class/{class_.id}/thread/{thread_id}/lecture-video/interactions",
        json={
            "type": "answer_submitted",
            "controller_session_id": controller_session_id,
            "expected_state_version": present_response.json()["lecture_video_session"][
                "state_version"
            ],
            "idempotency_key": "invalid-option-id",
            "question_id": questions[0].id,
            "option_id": second_question_option.id,
        },
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )
    assert invalid_option_response.status_code == 422
    assert (
        invalid_option_response.json()["detail"]
        == "That option does not belong to this question."
    )


@with_institution(11, "Test Institution")
async def test_initialize_thread_state_completes_when_lecture_video_has_no_questions(
    db, institution
):
    async with db.async_session() as session:
        class_ = models.Class(
            id=1,
            name="Test Class",
            institution_id=institution.id,
            api_key="test-key",
        )
        session.add(class_)
        await session.flush()

        lecture_video = make_lecture_video(
            class_.id,
            "questionless-lecture.mp4",
            filename="questionless-lecture.mp4",
            content_length=128,
        )
        session.add(lecture_video)
        await session.flush()

        assistant = models.Assistant(
            id=1,
            name="Lecture Assistant",
            class_id=class_.id,
            interaction_mode=schemas.InteractionMode.LECTURE_VIDEO,
            version=3,
            lecture_video_id=lecture_video.id,
            instructions="You are a lecture assistant.",
            model="gpt-4o-mini",
            tools="[]",
            use_latex=False,
            use_image_descriptions=False,
            hide_prompt=False,
        )
        session.add(assistant)
        await session.flush()

        thread = models.Thread(
            id=1,
            name="Lecture Presentation",
            version=3,
            thread_id="thread-no-questions",
            class_id=class_.id,
            assistant_id=assistant.id,
            interaction_mode=schemas.InteractionMode.LECTURE_VIDEO,
            lecture_video_id=lecture_video.id,
            private=False,
            display_user_info=False,
            tools_available="[]",
        )
        session.add(thread)
        await session.flush()

        state = await lecture_video_runtime.initialize_thread_state(session, thread.id)
        interactions = await models.LectureVideoInteraction.list_by_thread_id(
            session, thread.id
        )

    assert state.state == schemas.LectureVideoSessionState.COMPLETED
    assert state.current_question_id is None
    assert state.last_known_offset_ms == 0
    assert state.version == 1
    assert [interaction.event_type for interaction in interactions] == [
        schemas.LectureVideoInteractionEventType.SESSION_INITIALIZED
    ]


@pytest.mark.parametrize(
    ("session_state", "expected_offset_ms"),
    [
        (
            schemas.LectureVideoSessionState.PLAYING,
            1000 + 120000 + lecture_video_runtime.PLAYBACK_PROGRESS_TOLERANCE_MS,
        ),
        (schemas.LectureVideoSessionState.AWAITING_ANSWER, 1000),
        (schemas.LectureVideoSessionState.AWAITING_POST_ANSWER_RESUME, 1000),
    ],
)
@with_institution(11, "Test Institution")
async def test_get_plausible_playback_offset_ms_only_advances_while_playing(
    db, institution, session_state, expected_offset_ms
):
    base_time = datetime(2024, 1, 1, tzinfo=UTC)
    current_time = base_time + timedelta(minutes=2)

    async with db.async_session() as session:
        class_, lecture_video, assistant = await create_ready_lecture_video_assistant(
            session,
            institution,
        )

        thread = models.Thread(
            id=1,
            name="Lecture Presentation",
            version=3,
            thread_id=f"thread-plausible-offset-{session_state.value}",
            class_id=class_.id,
            assistant_id=assistant.id,
            interaction_mode=schemas.InteractionMode.LECTURE_VIDEO,
            lecture_video_id=lecture_video.id,
            private=False,
            display_user_info=False,
            tools_available="[]",
        )
        session.add(thread)
        await session.flush()

        state = models.LectureVideoThreadState(
            thread_id=thread.id,
            state=session_state,
            last_known_offset_ms=1000,
            furthest_offset_ms=1000,
            version=1,
        )
        session.add(state)
        session.add(
            models.LectureVideoInteraction(
                thread_id=thread.id,
                event_index=1,
                event_type=schemas.LectureVideoInteractionEventType.VIDEO_PAUSED,
                offset_ms=1000,
                created=base_time,
            )
        )
        await session.flush()

        plausible_offset_ms = (
            await lecture_video_runtime._get_plausible_playback_offset_ms(
                session,
                state,
                current_time=current_time,
            )
        )

    assert plausible_offset_ms == expected_offset_ms


@with_institution(11, "Test Institution")
async def test_append_interaction_requires_for_update_locked_state(db, institution):
    async with db.async_session() as session:
        class_, lecture_video, assistant = await create_ready_lecture_video_assistant(
            session,
            institution,
        )

        thread = models.Thread(
            id=1,
            name="Lecture Presentation",
            version=3,
            thread_id="thread-append-lock",
            class_id=class_.id,
            assistant_id=assistant.id,
            interaction_mode=schemas.InteractionMode.LECTURE_VIDEO,
            lecture_video_id=lecture_video.id,
            private=False,
            display_user_info=False,
            tools_available="[]",
        )
        session.add(thread)
        await session.flush()

        await lecture_video_runtime.initialize_thread_state(session, thread.id)
        unlocked_state = await lecture_video_runtime.get_or_initialize_thread_state(
            session,
            thread.id,
        )

        with pytest.raises(RuntimeError, match="FOR UPDATE before appending"):
            await lecture_video_runtime._append_interaction(
                session,
                unlocked_state,
                actor_user_id=None,
                event_type=schemas.LectureVideoInteractionEventType.VIDEO_PAUSED,
                offset_ms=500,
            )


@with_user(123)
@with_institution(11, "Test Institution")
@with_authz(
    grants=[
        ("user:123", "can_create_thread", "class:1"),
        ("user:123", "student", "class:1"),
    ]
)
async def test_lecture_video_history_uses_pseudonyms_for_other_participants(
    api, authz, config, db, institution, valid_user_token
):
    from pingpong.auth import encode_session_token

    manifest = {
        "version": 1,
        "questions": [
            lecture_video_manifest()["questions"][0],
            {
                "type": "single_select",
                "question_text": "What comes next?",
                "intro_text": "Second intro",
                "stop_offset_ms": 2500,
                "options": [
                    {
                        "option_text": "Continue",
                        "post_answer_text": "Nice work",
                        "continue_offset_ms": 3000,
                        "correct": True,
                    },
                    {
                        "option_text": "Stop",
                        "post_answer_text": "Not this one",
                        "continue_offset_ms": 3200,
                        "correct": False,
                    },
                ],
            },
        ],
    }

    async with db.async_session() as session:
        class_, lecture_video, _assistant = await create_ready_lecture_video_assistant(
            session,
            institution,
            manifest=manifest,
        )
        questions = list(
            (
                await session.scalars(
                    select(models.LectureVideoQuestion)
                    .where(
                        models.LectureVideoQuestion.lecture_video_id == lecture_video.id
                    )
                    .order_by(models.LectureVideoQuestion.position)
                )
            ).all()
        )
        options = {
            question.id: list(
                (
                    await session.scalars(
                        select(models.LectureVideoQuestionOption)
                        .where(
                            models.LectureVideoQuestionOption.question_id == question.id
                        )
                        .order_by(models.LectureVideoQuestionOption.position)
                    )
                ).all()
            )
            for question in questions
        }
        other_user = models.User(
            id=456,
            email="other-user@test.org",
            created=datetime(2024, 1, 2, tzinfo=UTC),
        )
        session.add(other_user)
        await session.commit()

    other_user_token = encode_session_token(456)

    create_response = api.post(
        f"/api/v1/class/{class_.id}/thread/lecture",
        json={"assistant_id": 1, "parties": [123, 456]},
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )
    assert create_response.status_code == 200
    thread_id = create_response.json()["thread"]["id"]
    await grant_thread_permissions(config, thread_id, 123, 456)

    async with db.async_session() as session:
        thread = await session.get(models.Thread, thread_id)
        assert thread is not None
        thread.private = False
        thread.display_user_info = False
        await session.commit()

    acquire_me = api.post(
        f"/api/v1/class/{class_.id}/thread/{thread_id}/lecture-video/control/acquire",
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )
    assert acquire_me.status_code == 200
    my_controller_session_id = acquire_me.json()["controller_session_id"]
    my_state_version = acquire_me.json()["lecture_video_session"]["state_version"]

    my_present = api.post(
        f"/api/v1/class/{class_.id}/thread/{thread_id}/lecture-video/interactions",
        json={
            "type": "question_presented",
            "controller_session_id": my_controller_session_id,
            "expected_state_version": my_state_version,
            "idempotency_key": "my-question-presented",
            "question_id": questions[0].id,
            "offset_ms": questions[0].stop_offset_ms,
        },
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )
    assert my_present.status_code == 200

    my_answer = api.post(
        f"/api/v1/class/{class_.id}/thread/{thread_id}/lecture-video/interactions",
        json={
            "type": "answer_submitted",
            "controller_session_id": my_controller_session_id,
            "expected_state_version": my_present.json()["lecture_video_session"][
                "state_version"
            ],
            "idempotency_key": "my-answer",
            "question_id": questions[0].id,
            "option_id": options[questions[0].id][0].id,
        },
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )
    assert my_answer.status_code == 200

    my_resume = api.post(
        f"/api/v1/class/{class_.id}/thread/{thread_id}/lecture-video/interactions",
        json={
            "type": "video_resumed",
            "controller_session_id": my_controller_session_id,
            "expected_state_version": my_answer.json()["lecture_video_session"][
                "state_version"
            ],
            "idempotency_key": "my-resume",
            "offset_ms": options[questions[0].id][0].continue_offset_ms,
        },
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )
    assert my_resume.status_code == 200

    release = api.post(
        f"/api/v1/class/{class_.id}/thread/{thread_id}/lecture-video/control/release",
        json={"controller_session_id": my_controller_session_id},
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )
    assert release.status_code == 200

    acquire_other = api.post(
        f"/api/v1/class/{class_.id}/thread/{thread_id}/lecture-video/control/acquire",
        headers={"Authorization": f"Bearer {other_user_token}"},
    )
    assert acquire_other.status_code == 200
    other_controller_session_id = acquire_other.json()["controller_session_id"]
    other_state_version = acquire_other.json()["lecture_video_session"]["state_version"]

    other_present = api.post(
        f"/api/v1/class/{class_.id}/thread/{thread_id}/lecture-video/interactions",
        json={
            "type": "question_presented",
            "controller_session_id": other_controller_session_id,
            "expected_state_version": other_state_version,
            "idempotency_key": "other-question-presented",
            "question_id": questions[1].id,
            "offset_ms": questions[1].stop_offset_ms,
        },
        headers={"Authorization": f"Bearer {other_user_token}"},
    )
    assert other_present.status_code == 200

    other_answer = api.post(
        f"/api/v1/class/{class_.id}/thread/{thread_id}/lecture-video/interactions",
        json={
            "type": "answer_submitted",
            "controller_session_id": other_controller_session_id,
            "expected_state_version": other_present.json()["lecture_video_session"][
                "state_version"
            ],
            "idempotency_key": "other-answer",
            "question_id": questions[1].id,
            "option_id": options[questions[1].id][0].id,
        },
        headers={"Authorization": f"Bearer {other_user_token}"},
    )
    assert other_answer.status_code == 200

    history_response = api.get(
        f"/api/v1/class/{class_.id}/thread/{thread_id}/lecture-video/history",
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )
    assert history_response.status_code == 200

    async with db.async_session() as session:
        thread = await models.Thread.get_by_id_with_lecture_video_context(
            session, thread_id
        )
        assert thread is not None
        users = {user.id: user for user in thread.users}

    history = history_response.json()["interactions"]
    assert [item["event_type"] for item in history] == [
        "question_presented",
        "answer_submitted",
        "question_presented",
        "answer_submitted",
    ]
    assert history[0]["actor_name"] == "Me"
    assert history[0]["question_id"] == questions[0].id
    assert history[0]["offset_ms"] == questions[0].stop_offset_ms
    assert history[1]["actor_name"] == "Me"
    assert history[1]["question_id"] == questions[0].id
    assert history[1]["option_id"] == options[questions[0].id][0].id
    assert history[2]["actor_name"] == pseudonym(thread, users[456])
    assert history[2]["question_id"] == questions[1].id
    assert history[2]["offset_ms"] == questions[1].stop_offset_ms
    assert history[3]["actor_name"] == pseudonym(thread, users[456])
    assert history[3]["question_id"] == questions[1].id
    assert history[3]["option_id"] == options[questions[1].id][0].id


@with_user(123)
@with_institution(11, "Test Institution")
@with_authz(
    grants=[
        ("user:123", "can_create_thread", "class:1"),
        ("user:123", "student", "class:1"),
    ]
)
async def test_lecture_video_control_lease_is_short_and_renewable(
    api, authz, config, db, institution, valid_user_token, monkeypatch
):
    server_module = importlib.import_module("pingpong.server")
    current_now = {"value": datetime(2024, 1, 1, 0, 0, tzinfo=UTC)}
    monkeypatch.setattr(
        server_module, "get_now_fn", lambda request: lambda: current_now["value"]
    )

    async with db.async_session() as session:
        class_, _lecture_video, _assistant = await create_ready_lecture_video_assistant(
            session,
            institution,
        )

    create_response = api.post(
        f"/api/v1/class/{class_.id}/thread/lecture",
        json={"assistant_id": 1, "parties": [123]},
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )
    thread_id = create_response.json()["thread"]["id"]
    await grant_thread_permissions(config, thread_id, 123)

    acquire = api.post(
        f"/api/v1/class/{class_.id}/thread/{thread_id}/lecture-video/control/acquire",
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )
    assert acquire.status_code == 200
    controller_session_id = acquire.json()["controller_session_id"]
    acquired_session = acquire.json()["lecture_video_session"]
    assert acquired_session["state_version"] == 2
    assert _parse_timestamp(
        acquired_session["controller"]["lease_expires_at"]
    ) == current_now["value"] + timedelta(seconds=30)

    current_now["value"] = current_now["value"] + timedelta(seconds=15)
    renew = api.post(
        f"/api/v1/class/{class_.id}/thread/{thread_id}/lecture-video/control/renew",
        json={"controller_session_id": controller_session_id},
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )
    assert renew.status_code == 200
    assert _parse_timestamp(renew.json()["lease_expires_at"]) == current_now[
        "value"
    ] + timedelta(seconds=30)

    refreshed_thread = api.get(
        f"/api/v1/class/{class_.id}/thread/{thread_id}",
        headers={
            "Authorization": f"Bearer {valid_user_token}",
            "X-Lecture-Video-Controller-Session": controller_session_id,
        },
    )
    assert refreshed_thread.status_code == 200
    renewed_session = refreshed_thread.json()["lecture_video_session"]
    assert renewed_session["state_version"] == acquired_session["state_version"]
    assert renewed_session["controller"]["has_control"] is True
    assert renewed_session["controller"]["has_active_controller"] is True
    assert _parse_timestamp(
        renewed_session["controller"]["lease_expires_at"]
    ) == current_now["value"] + timedelta(seconds=30)

    release = api.post(
        f"/api/v1/class/{class_.id}/thread/{thread_id}/lecture-video/control/release",
        json={"controller_session_id": controller_session_id},
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )
    assert release.status_code == 200


@with_user(123)
@with_institution(11, "Test Institution")
@with_authz(
    grants=[
        ("user:123", "can_create_thread", "class:1"),
        ("user:123", "student", "class:1"),
    ]
)
async def test_lecture_video_control_release_and_interaction_fail_after_expiry(
    api, authz, config, db, institution, valid_user_token, monkeypatch
):
    server_module = importlib.import_module("pingpong.server")
    current_now = {"value": datetime(2024, 1, 1, 0, 0, tzinfo=UTC)}
    monkeypatch.setattr(
        server_module, "get_now_fn", lambda request: lambda: current_now["value"]
    )

    async with db.async_session() as session:
        class_, _lecture_video, _assistant = await create_ready_lecture_video_assistant(
            session,
            institution,
        )

    create_response = api.post(
        f"/api/v1/class/{class_.id}/thread/lecture",
        json={"assistant_id": 1, "parties": [123]},
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )
    thread_id = create_response.json()["thread"]["id"]
    await grant_thread_permissions(config, thread_id, 123)

    acquire = api.post(
        f"/api/v1/class/{class_.id}/thread/{thread_id}/lecture-video/control/acquire",
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )
    assert acquire.status_code == 200
    controller_session_id = acquire.json()["controller_session_id"]
    state_version = acquire.json()["lecture_video_session"]["state_version"]

    current_now["value"] = current_now["value"] + timedelta(seconds=31)

    release = api.post(
        f"/api/v1/class/{class_.id}/thread/{thread_id}/lecture-video/control/release",
        json={"controller_session_id": controller_session_id},
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )
    assert release.status_code == 409
    assert "expired" in release.json()["detail"]

    interaction = api.post(
        f"/api/v1/class/{class_.id}/thread/{thread_id}/lecture-video/interactions",
        json={
            "type": "video_paused",
            "controller_session_id": controller_session_id,
            "expected_state_version": state_version,
            "idempotency_key": "expired-pause",
            "offset_ms": 500,
        },
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )
    assert interaction.status_code == 409
    assert "expired" in interaction.json()["detail"]


@with_user(123)
@with_institution(11, "Test Institution")
@with_authz(
    grants=[
        ("user:123", "can_create_thread", "class:1"),
        ("user:123", "student", "class:1"),
    ]
)
async def test_lecture_video_control_blocks_other_users_until_expiry_then_allows_acquire(
    api, authz, config, db, institution, valid_user_token, monkeypatch
):
    from pingpong.auth import encode_session_token
    from pingpong.now import offset

    server_module = importlib.import_module("pingpong.server")
    current_now = {"value": datetime(2024, 1, 1, 0, 0, tzinfo=UTC)}
    monkeypatch.setattr(
        server_module, "get_now_fn", lambda request: lambda: current_now["value"]
    )

    async with db.async_session() as session:
        class_, _lecture_video, _assistant = await create_ready_lecture_video_assistant(
            session,
            institution,
        )
        other_user = models.User(
            id=456,
            email="user_456@domain.org",
            created=datetime(2024, 1, 1, 0, 0, 0),
        )
        session.add(other_user)
        await session.commit()

    other_user_token = encode_session_token(
        456, nowfn=offset(lambda: current_now["value"], seconds=-60)
    )

    create_response = api.post(
        f"/api/v1/class/{class_.id}/thread/lecture",
        json={"assistant_id": 1, "parties": [123]},
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )
    thread_id = create_response.json()["thread"]["id"]
    await grant_thread_permissions(config, thread_id, 123, 456)

    acquire = api.post(
        f"/api/v1/class/{class_.id}/thread/{thread_id}/lecture-video/control/acquire",
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )
    assert acquire.status_code == 200
    acquired_state_version = acquire.json()["lecture_video_session"]["state_version"]

    blocked = api.post(
        f"/api/v1/class/{class_.id}/thread/{thread_id}/lecture-video/control/acquire",
        headers={"Authorization": f"Bearer {other_user_token}"},
    )
    assert blocked.status_code == 409
    assert "Another participant" in blocked.json()["detail"]

    other_thread = api.get(
        f"/api/v1/class/{class_.id}/thread/{thread_id}",
        headers={"Authorization": f"Bearer {other_user_token}"},
    )
    assert other_thread.status_code == 200
    other_session = other_thread.json()["lecture_video_session"]
    assert other_session["controller"]["has_control"] is False
    assert other_session["controller"]["has_active_controller"] is True
    assert other_session["state_version"] == acquired_state_version
    assert other_session["current_question"] is None

    current_now["value"] = current_now["value"] + timedelta(seconds=31)

    acquired_after_expiry = api.post(
        f"/api/v1/class/{class_.id}/thread/{thread_id}/lecture-video/control/acquire",
        headers={"Authorization": f"Bearer {other_user_token}"},
    )
    assert acquired_after_expiry.status_code == 200
    assert (
        acquired_after_expiry.json()["lecture_video_session"]["controller"][
            "has_control"
        ]
        is True
    )


@with_user(123)
@with_institution(11, "Test Institution")
@with_authz(
    grants=[
        ("user:123", "can_create_thread", "class:1"),
        ("user:123", "student", "class:1"),
    ]
)
async def test_get_thread_does_not_grant_control_from_leaked_controller_session_id(
    api, authz, config, db, institution, valid_user_token
):
    from pingpong.auth import encode_session_token

    async with db.async_session() as session:
        class_, _lecture_video, _assistant = await create_ready_lecture_video_assistant(
            session,
            institution,
        )
        other_user = models.User(
            id=456,
            email="user_456@domain.org",
            created=datetime(2024, 1, 1, 0, 0, 0),
        )
        session.add(other_user)
        await session.commit()

    other_user_token = encode_session_token(456)

    create_response = api.post(
        f"/api/v1/class/{class_.id}/thread/lecture",
        json={"assistant_id": 1, "parties": [123, 456]},
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )
    thread_id = create_response.json()["thread"]["id"]
    await grant_thread_permissions(config, thread_id, 123, 456)

    acquire = api.post(
        f"/api/v1/class/{class_.id}/thread/{thread_id}/lecture-video/control/acquire",
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )
    assert acquire.status_code == 200
    controller_session_id = acquire.json()["controller_session_id"]
    acquired_state_version = acquire.json()["lecture_video_session"]["state_version"]

    leaked_session_response = api.get(
        f"/api/v1/class/{class_.id}/thread/{thread_id}",
        headers={
            "Authorization": f"Bearer {other_user_token}",
            "X-Lecture-Video-Controller-Session": controller_session_id,
        },
    )
    assert leaked_session_response.status_code == 200
    leaked_session = leaked_session_response.json()["lecture_video_session"]
    assert leaked_session["controller"]["has_control"] is False
    assert leaked_session["state_version"] == acquired_state_version
    assert leaked_session["current_question"] is None
    assert leaked_session["current_continuation"] is None
    assert leaked_session["controller"]["has_active_controller"] is True


@with_user(123)
@with_institution(11, "Test Institution")
@with_authz(
    grants=[
        ("user:123", "can_create_thread", "class:1"),
        ("user:123", "student", "class:1"),
    ]
)
async def test_get_thread_hides_expired_controller_state(
    api, authz, config, db, institution, valid_user_token, monkeypatch
):
    server_module = importlib.import_module("pingpong.server")
    current_now = {"value": datetime(2024, 1, 1, 0, 0, tzinfo=UTC)}
    monkeypatch.setattr(
        server_module, "get_now_fn", lambda request: lambda: current_now["value"]
    )

    async with db.async_session() as session:
        class_, _lecture_video, _assistant = await create_ready_lecture_video_assistant(
            session,
            institution,
        )

    create_response = api.post(
        f"/api/v1/class/{class_.id}/thread/lecture",
        json={"assistant_id": 1, "parties": [123]},
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )
    thread_id = create_response.json()["thread"]["id"]
    await grant_thread_permissions(config, thread_id, 123)

    acquire = api.post(
        f"/api/v1/class/{class_.id}/thread/{thread_id}/lecture-video/control/acquire",
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )
    assert acquire.status_code == 200
    controller_session_id = acquire.json()["controller_session_id"]

    current_now["value"] = current_now["value"] + timedelta(seconds=31)

    response = api.get(
        f"/api/v1/class/{class_.id}/thread/{thread_id}",
        headers={
            "Authorization": f"Bearer {valid_user_token}",
            "X-Lecture-Video-Controller-Session": controller_session_id,
        },
    )
    assert response.status_code == 200
    controller = response.json()["lecture_video_session"]["controller"]
    assert controller["has_control"] is False
    assert controller["has_active_controller"] is False
    assert controller["lease_expires_at"] is None


@with_user(123)
@with_institution(11, "Test Institution")
@with_authz(
    grants=[
        ("user:123", "can_edit", "assistant:1"),
        ("user:123", "can_share_assistants", "class:1"),
    ]
)
async def test_share_lecture_video_assistant_allowed(
    api, db, institution, valid_user_token, now
):
    async with db.async_session() as session:
        class_ = models.Class(
            id=1,
            name="Test Class",
            institution_id=institution.id,
            api_key="test-key",
        )
        session.add(class_)
        await session.commit()
        await session.refresh(class_)

        assistant = models.Assistant(
            id=1,
            name="Lecture Assistant",
            class_id=class_.id,
            interaction_mode=schemas.InteractionMode.LECTURE_VIDEO,
            version=3,
            published=now(),
        )
        session.add(assistant)
        await session.commit()

    response = api.post(
        f"/api/v1/class/{class_.id}/assistant/1/share",
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


@with_user(123)
@with_institution(11, "Test Institution")
@with_authz(
    grants=[
        ("user:123", "can_create_thread", "class:1"),
    ]
)
async def test_create_thread_rejects_lecture_video_assistant(
    api, db, institution, valid_user_token
):
    async with db.async_session() as session:
        class_ = models.Class(
            id=1,
            name="Test Class",
            institution_id=institution.id,
            api_key="test-key",
        )
        session.add(class_)
        await session.commit()
        await session.refresh(class_)

        assistant = models.Assistant(
            id=1,
            name="Lecture Assistant",
            class_id=class_.id,
            interaction_mode=schemas.InteractionMode.LECTURE_VIDEO,
            version=3,
        )
        session.add(assistant)
        await session.commit()

    response = api.post(
        f"/api/v1/class/{class_.id}/thread",
        json={"assistant_id": 1, "message": "hello"},
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )
    assert response.status_code == 400
    assert (
        response.json()["detail"]
        == "This assistant requires a dedicated thread creation endpoint."
    )


@with_user(123)
@with_institution(11, "Test Institution")
@with_authz(
    grants=[
        ("anonymous_link:anon-share-token", "can_create_thread", "class:1"),
    ]
)
async def test_anonymous_can_create_lecture_thread(api, db, institution):
    async with db.async_session() as session:
        class_ = models.Class(
            id=1,
            name="Test Class",
            institution_id=institution.id,
        )
        session.add(class_)
        await session.commit()
        await session.refresh(class_)

        link = models.AnonymousLink(
            id=1,
            share_token="anon-share-token",
            active=True,
        )
        session.add(link)
        await session.flush()

        anon_user = models.User(
            id=999,
            email="anon@test.org",
            anonymous_link_id=link.id,
        )
        session.add(anon_user)
        await session.commit()

        lecture_video = make_lecture_video(
            class_.id,
            "anon-test-video-key.mp4",
            filename="Anonymous Test Video.mp4",
        )
        session.add(lecture_video)
        await session.flush()

        assistant = models.Assistant(
            id=1,
            name="Lecture Assistant",
            class_id=class_.id,
            interaction_mode=schemas.InteractionMode.LECTURE_VIDEO,
            version=3,
            lecture_video_id=lecture_video.id,
            instructions="You are a lecture assistant.",
        )
        session.add(assistant)
        await session.commit()

    response = api.post(
        f"/api/v1/class/{class_.id}/thread/lecture",
        json={"assistant_id": 1},
        headers={"X-Anonymous-Link-Share": "anon-share-token"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["thread"]["class_id"] == class_.id
    assert data["thread"]["assistant_id"] == 1
    assert data["thread"]["interaction_mode"] == "lecture_video"
    assert data["thread"]["lecture_video_id"] == lecture_video.id
    assert data["thread"]["private"] is True
    assert data["session_token"] is not None


@with_user(123)
@with_institution(11, "Test Institution")
@with_authz(
    grants=[
        ("user:123", "can_create_thread", "class:1"),
    ]
)
async def test_non_v3_assistants_rejected(api, db, institution, valid_user_token):
    async with db.async_session() as session:
        class_ = models.Class(
            id=1,
            name="Test Class",
            institution_id=institution.id,
        )
        session.add(class_)
        await session.commit()
        await session.refresh(class_)

        lecture_video = make_lecture_video(
            class_.id,
            "test-video-key.mp4",
            filename="Test Video.mp4",
        )
        session.add(lecture_video)
        await session.flush()

        assistant = models.Assistant(
            id=1,
            name="Lecture Assistant",
            class_id=class_.id,
            interaction_mode=schemas.InteractionMode.LECTURE_VIDEO,
            version=2,
            lecture_video_id=lecture_video.id,
        )
        session.add(assistant)
        await session.commit()

    response = api.post(
        f"/api/v1/class/{class_.id}/thread/lecture",
        json={"assistant_id": 1},
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )
    assert response.status_code == 400
    assert (
        response.json()["detail"]
        == "Lecture presentation can only be created using v3 assistants."
    )


@with_user(123)
@with_institution(11, "Test Institution")
@with_authz(
    grants=[
        ("user:123", "can_create_thread", "class:1"),
    ]
)
async def test_lecture_thread_rejected_without_attached_video(
    api, db, institution, valid_user_token
):
    async with db.async_session() as session:
        class_ = models.Class(
            id=1,
            name="Test Class",
            institution_id=institution.id,
        )
        session.add(class_)
        await session.commit()
        await session.refresh(class_)

        assistant = models.Assistant(
            id=1,
            name="Lecture Assistant",
            class_id=class_.id,
            interaction_mode=schemas.InteractionMode.LECTURE_VIDEO,
            version=3,
            lecture_video_id=None,
        )
        session.add(assistant)
        await session.commit()

    response = api.post(
        f"/api/v1/class/{class_.id}/thread/lecture",
        json={"assistant_id": 1},
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )
    assert response.status_code == 400
    assert (
        response.json()["detail"]
        == "This assistant does not have a lecture video attached. Unable to create Lecture Presentation"
    )


@with_user(123)
@with_institution(11, "Test Institution")
@with_authz(
    grants=[
        ("user:123", "can_create_thread", "class:1"),
    ]
)
async def test_lecture_endpoint_rejects_non_lecture_video_assistant(
    api, db, institution, valid_user_token
):
    async with db.async_session() as session:
        class_ = models.Class(
            id=1,
            name="Test Class",
            institution_id=institution.id,
        )
        session.add(class_)
        await session.commit()
        await session.refresh(class_)

        assistant = models.Assistant(
            id=1,
            name="Chat Assistant",
            class_id=class_.id,
            interaction_mode=schemas.InteractionMode.VOICE,
            version=3,
        )
        session.add(assistant)
        await session.commit()

    response = api.post(
        f"/api/v1/class/{class_.id}/thread/lecture",
        json={"assistant_id": 1},
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )
    assert response.status_code == 400
    assert (
        response.json()["detail"]
        == "This assistant is not compatible with this thread creation endpoint. Provide a lecture_video assistant."
    )


@with_user(123)
@with_institution(11, "Test Institution")
@with_authz(grants=[("user:123", "admin", "class:1")])
async def test_uploading_same_video_twice_creates_distinct_rows(
    api, authz, db, institution, valid_user_token, config, monkeypatch, tmp_path
):
    monkeypatch.setattr(
        config,
        "video_store",
        LocalVideoStoreSettings(type="local", save_target=str(tmp_path)),
    )

    async with db.async_session() as session:
        session.add(
            models.Class(
                id=1,
                name="Test Class",
                institution_id=institution.id,
                api_key="test-key",
            )
        )
        await session.commit()

    upload = ("lecture.mp4", b"same-video-bytes", "video/mp4")
    response_one = api.post(
        "/api/v1/class/1/lecture-video",
        files={"upload": upload},
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )
    response_two = api.post(
        "/api/v1/class/1/lecture-video",
        files={"upload": upload},
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )

    assert response_one.status_code == 200
    assert response_two.status_code == 200
    body_one = response_one.json()
    body_two = response_two.json()
    assert body_one["id"] != body_two["id"]
    assert body_one["status"] == schemas.LectureVideoStatus.UPLOADED.value
    assert body_two["status"] == schemas.LectureVideoStatus.UPLOADED.value
    assert body_one["filename"] == "lecture.mp4"
    assert body_one["size"] == len(upload[1])

    async with db.async_session() as session:
        lecture_videos = (
            (
                await session.execute(
                    select(models.LectureVideo)
                    .options(selectinload(models.LectureVideo.stored_object))
                    .order_by(models.LectureVideo.id.asc())
                )
            )
            .scalars()
            .all()
        )

    assert len(lecture_videos) == 2
    assert lecture_videos[0].stored_object_id != lecture_videos[1].stored_object_id
    assert lecture_videos[0].stored_object.key != lecture_videos[1].stored_object.key
    assert {lecture_video.class_id for lecture_video in lecture_videos} == {1}
    assert await authz.get_all_calls() == [
        ("grant", "class:1", "parent", f"lecture_video:{body_one['id']}"),
        ("grant", "user:123", "owner", f"lecture_video:{body_one['id']}"),
        ("grant", "class:1", "parent", f"lecture_video:{body_two['id']}"),
        ("grant", "user:123", "owner", f"lecture_video:{body_two['id']}"),
    ]


@with_user(123)
@with_institution(11, "Test Institution")
@with_authz(grants=[("user:123", "admin", "class:1")])
async def test_create_lecture_video_cleans_up_upload_when_authz_grant_fails(
    api, authz, db, institution, valid_user_token, config, monkeypatch, tmp_path
):
    monkeypatch.setattr(
        config,
        "video_store",
        LocalVideoStoreSettings(type="local", save_target=str(tmp_path)),
    )

    async def fail_write_safe(self, grant=None, revoke=None):
        raise HTTPException(status_code=503, detail="Authz unavailable")

    monkeypatch.setattr(OpenFgaAuthzClient, "write_safe", fail_write_safe)

    async with db.async_session() as session:
        session.add(
            models.Class(
                id=1,
                name="Test Class",
                institution_id=institution.id,
                api_key="test-key",
            )
        )
        await session.commit()

    response = api.post(
        "/api/v1/class/1/lecture-video",
        files={"upload": ("grant-failure.mp4", b"video-bytes", "video/mp4")},
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )

    assert response.status_code == 503
    assert response.json()["detail"] == "Authz unavailable"

    async with db.async_session() as session:
        lecture_video_count = await session.scalar(
            select(func.count()).select_from(models.LectureVideo)
        )
        stored_object_count = await session.scalar(
            select(func.count()).select_from(models.LectureVideoStoredObject)
        )

    assert lecture_video_count == 0
    assert stored_object_count == 0
    assert list(tmp_path.iterdir()) == []
    assert await authz.get_all_calls() == []


@pytest.mark.asyncio
async def test_lecture_video_summary_backfills_zero_content_length_from_store(
    db, config, monkeypatch, tmp_path
):
    monkeypatch.setattr(
        config,
        "video_store",
        LocalVideoStoreSettings(type="local", save_target=str(tmp_path)),
    )
    video_bytes = b"legacy-video-bytes"

    async with db.async_session() as session:
        class_ = models.Class(
            id=1, name="Test Class", institution_id=1, api_key="test-key"
        )
        lecture_video = make_lecture_video(
            class_id=1,
            key="legacy-video.mp4",
            filename="legacy-video.mp4",
            content_length=0,
        )
        session.add(models.Institution(id=1, name="Test Institution"))
        session.add(class_)
        session.add(lecture_video)
        await session.commit()
        lecture_video_id = lecture_video.id
        stored_object_id = lecture_video.stored_object.id

    (tmp_path / "legacy-video.mp4").write_bytes(video_bytes)

    async with db.async_session() as session:
        lecture_video = await models.LectureVideo.get_by_id(session, lecture_video_id)
        assert lecture_video is not None
        summary = await lecture_video_service.lecture_video_summary_from_model(
            session, lecture_video
        )
        await session.commit()

    assert summary is not None
    assert summary.size == len(video_bytes)

    async with db.async_session() as session:
        stored_object = await session.get(
            models.LectureVideoStoredObject, stored_object_id
        )

    assert stored_object is not None
    assert stored_object.content_length == len(video_bytes)


@pytest.mark.asyncio
async def test_lecture_video_summary_logs_warning_when_store_returns_zero_content_length(
    db, config, monkeypatch, caplog, tmp_path
):
    monkeypatch.setattr(
        config,
        "video_store",
        LocalVideoStoreSettings(type="local", save_target=str(tmp_path)),
    )

    async def fake_get_video_metadata(key: str) -> schemas.VideoMetadata:
        return schemas.VideoMetadata(
            key=key,
            content_type="video/mp4",
            content_length=0,
        )

    monkeypatch.setattr(
        config.video_store.store, "get_video_metadata", fake_get_video_metadata
    )

    async with db.async_session() as session:
        class_ = models.Class(
            id=1, name="Test Class", institution_id=1, api_key="test-key"
        )
        lecture_video = make_lecture_video(
            class_id=1,
            key="legacy-video.mp4",
            filename="legacy-video.mp4",
            content_length=0,
        )
        session.add(models.Institution(id=1, name="Test Institution"))
        session.add(class_)
        session.add(lecture_video)
        await session.commit()
        lecture_video_id = lecture_video.id
        stored_object_id = lecture_video.stored_object.id

    async with db.async_session() as session:
        lecture_video = await models.LectureVideo.get_by_id(session, lecture_video_id)
        assert lecture_video is not None
        with caplog.at_level("WARNING"):
            summary = await lecture_video_service.lecture_video_summary_from_model(
                session, lecture_video
            )
        await session.commit()

    assert summary is not None
    assert summary.size == 0
    assert (
        "Video store returned content_length=0 during on-demand lecture video backfill"
        in caplog.text
    )

    async with db.async_session() as session:
        stored_object = await session.get(
            models.LectureVideoStoredObject, stored_object_id
        )

    assert stored_object is not None
    assert stored_object.content_length == 0


@with_user(123)
@with_institution(11, "Test Institution")
@with_authz(
    grants=[
        ("user:123", "admin", "class:1"),
        ("class:1", "parent", "lecture_video:1"),
        ("user:123", "owner", "lecture_video:1"),
        ("user:123", "can_delete", "lecture_video:1"),
    ]
)
async def test_delete_unused_lecture_video_endpoint_deletes_row_and_file(
    api, authz, db, institution, valid_user_token, config, monkeypatch, tmp_path
):
    monkeypatch.setattr(
        config,
        "video_store",
        LocalVideoStoreSettings(type="local", save_target=str(tmp_path)),
    )

    async with db.async_session() as session:
        class_ = models.Class(
            id=1,
            name="Test Class",
            institution_id=institution.id,
            api_key="test-key",
        )
        lecture_video = make_lecture_video(
            class_.id,
            "delete-endpoint.mp4",
            filename="delete-endpoint.mp4",
            uploader_id=123,
        )
        session.add_all([class_, lecture_video])
        await session.commit()
        await session.refresh(lecture_video)

    (tmp_path / "delete-endpoint.mp4").write_bytes(b"video-bytes")

    response = api.delete(
        f"/api/v1/class/1/lecture-video/{lecture_video.id}",
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}

    async with db.async_session() as session:
        deleted_video = await session.get(models.LectureVideo, lecture_video.id)
        deleted_stored_object = await session.scalar(
            select(models.LectureVideoStoredObject.id).where(
                models.LectureVideoStoredObject.key == "delete-endpoint.mp4"
            )
        )

    assert deleted_video is None
    assert deleted_stored_object is None
    assert not (tmp_path / "delete-endpoint.mp4").exists()
    assert await authz.get_all_calls() == [
        ("revoke", "class:1", "parent", "lecture_video:1"),
        ("revoke", "user:123", "owner", "lecture_video:1"),
    ]


@with_user(123)
@with_institution(11, "Test Institution")
@with_authz(grants=[("user:123", "admin", "class:1")])
async def test_delete_lecture_video_endpoint_requires_entry_can_delete(
    api, db, institution, valid_user_token, config, monkeypatch, tmp_path
):
    monkeypatch.setattr(
        config,
        "video_store",
        LocalVideoStoreSettings(type="local", save_target=str(tmp_path)),
    )

    async with db.async_session() as session:
        class_ = models.Class(
            id=1,
            name="Test Class",
            institution_id=institution.id,
            api_key="test-key",
        )
        lecture_video = make_lecture_video(
            class_.id,
            "delete-missing-entry-perm.mp4",
            filename="delete-missing-entry-perm.mp4",
            uploader_id=123,
        )
        session.add_all([class_, lecture_video])
        await session.commit()
        await session.refresh(lecture_video)

    (tmp_path / "delete-missing-entry-perm.mp4").write_bytes(b"video-bytes")

    response = api.delete(
        f"/api/v1/class/1/lecture-video/{lecture_video.id}",
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "Missing required role"
    assert (tmp_path / "delete-missing-entry-perm.mp4").exists()

    async with db.async_session() as session:
        existing_video = await session.get(models.LectureVideo, lecture_video.id)

    assert existing_video is not None


@with_user(123)
@with_institution(11, "Test Institution")
@with_authz(
    grants=[
        ("user:123", "admin", "class:1"),
        ("class:1", "parent", "lecture_video:1"),
        ("user:123", "owner", "lecture_video:1"),
        ("user:123", "can_delete", "lecture_video:1"),
    ]
)
async def test_delete_lecture_video_endpoint_returns_409_when_attached(
    api, db, institution, valid_user_token, config, monkeypatch, tmp_path
):
    monkeypatch.setattr(
        config,
        "video_store",
        LocalVideoStoreSettings(type="local", save_target=str(tmp_path)),
    )

    async with db.async_session() as session:
        class_ = models.Class(
            id=1,
            name="Test Class",
            institution_id=institution.id,
            api_key="test-key",
        )
        lecture_video = make_lecture_video(
            class_.id,
            "delete-conflict.mp4",
            filename="delete-conflict.mp4",
            uploader_id=123,
        )
        session.add_all([class_, lecture_video])
        await session.flush()
        session.add(
            models.Assistant(
                id=1,
                name="Lecture Assistant",
                class_id=class_.id,
                creator_id=123,
                interaction_mode=schemas.InteractionMode.LECTURE_VIDEO,
                version=3,
                model="gpt-4o-mini",
                lecture_video_id=lecture_video.id,
                instructions="Teach the lecture.",
                tools="[]",
            )
        )
        await session.commit()
        await session.refresh(lecture_video)

    (tmp_path / "delete-conflict.mp4").write_bytes(b"video-bytes")

    response = api.delete(
        f"/api/v1/class/1/lecture-video/{lecture_video.id}",
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )

    assert response.status_code == 409
    assert "attached to an assistant" in response.json()["detail"]
    assert (tmp_path / "delete-conflict.mp4").exists()

    async with db.async_session() as session:
        existing_video = await session.get(models.LectureVideo, lecture_video.id)

    assert existing_video is not None


@with_user(123)
@with_institution(11, "Test Institution")
@with_authz(grants=[("user:123", "can_edit", "assistant:1")])
async def test_upload_assistant_lecture_video_endpoint_allows_editor(
    api, authz, db, institution, valid_user_token, config, monkeypatch, tmp_path
):
    monkeypatch.setattr(
        config,
        "video_store",
        LocalVideoStoreSettings(type="local", save_target=str(tmp_path)),
    )

    async with db.async_session() as session:
        class_ = models.Class(
            id=1,
            name="Test Class",
            institution_id=institution.id,
            api_key="test-key",
        )
        session.add(class_)
        await session.flush()
        session.add(
            models.Assistant(
                id=1,
                name="Lecture Assistant",
                class_id=class_.id,
                creator_id=123,
                interaction_mode=schemas.InteractionMode.LECTURE_VIDEO,
                version=3,
                model="gpt-4o-mini",
                instructions="Teach the lecture.",
                tools="[]",
            )
        )
        await session.commit()

    response = api.post(
        "/api/v1/class/1/assistant/1/lecture-video/upload",
        files={"upload": ("assistant-upload.mp4", b"video-bytes", "video/mp4")},
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["filename"] == "assistant-upload.mp4"
    assert body["size"] == len(b"video-bytes")
    assert body["status"] == schemas.LectureVideoStatus.UPLOADED.value

    async with db.async_session() as session:
        lecture_videos = (
            (
                await session.execute(
                    select(models.LectureVideo)
                    .options(selectinload(models.LectureVideo.stored_object))
                    .order_by(models.LectureVideo.id.asc())
                )
            )
            .scalars()
            .all()
        )

    assert len(lecture_videos) == 1
    assert lecture_videos[0].class_id == 1
    assert lecture_videos[0].stored_object.original_filename == "assistant-upload.mp4"
    assert (tmp_path / lecture_videos[0].stored_object.key).exists()
    assert await authz.get_all_calls() == [
        ("grant", "class:1", "parent", f"lecture_video:{body['id']}"),
        ("grant", "user:123", "owner", f"lecture_video:{body['id']}"),
    ]


@with_user(123)
@with_institution(11, "Test Institution")
@with_authz(grants=[("user:123", "can_edit", "assistant:1")])
async def test_upload_assistant_lecture_video_cleans_up_upload_when_authz_grant_fails(
    api, authz, db, institution, valid_user_token, config, monkeypatch, tmp_path
):
    monkeypatch.setattr(
        config,
        "video_store",
        LocalVideoStoreSettings(type="local", save_target=str(tmp_path)),
    )

    async def fail_write_safe(self, grant=None, revoke=None):
        raise HTTPException(status_code=503, detail="Authz unavailable")

    monkeypatch.setattr(OpenFgaAuthzClient, "write_safe", fail_write_safe)

    async with db.async_session() as session:
        class_ = models.Class(
            id=1,
            name="Test Class",
            institution_id=institution.id,
            api_key="test-key",
        )
        session.add(class_)
        await session.flush()
        session.add(
            models.Assistant(
                id=1,
                name="Lecture Assistant",
                class_id=class_.id,
                creator_id=123,
                interaction_mode=schemas.InteractionMode.LECTURE_VIDEO,
                version=3,
                model="gpt-4o-mini",
                instructions="Teach the lecture.",
                tools="[]",
            )
        )
        await session.commit()

    response = api.post(
        "/api/v1/class/1/assistant/1/lecture-video/upload",
        files={"upload": ("assistant-grant-failure.mp4", b"video-bytes", "video/mp4")},
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )

    assert response.status_code == 503
    assert response.json()["detail"] == "Authz unavailable"

    async with db.async_session() as session:
        lecture_video_count = await session.scalar(
            select(func.count()).select_from(models.LectureVideo)
        )
        stored_object_count = await session.scalar(
            select(func.count()).select_from(models.LectureVideoStoredObject)
        )

    assert lecture_video_count == 0
    assert stored_object_count == 0
    assert list(tmp_path.iterdir()) == []
    assert await authz.get_all_calls() == []


@with_user(123)
@with_institution(11, "Test Institution")
@with_authz(grants=[("user:123", "can_edit", "assistant:1")])
async def test_upload_assistant_lecture_video_endpoint_rejects_non_lecture_assistant(
    api, db, institution, valid_user_token, config, monkeypatch, tmp_path
):
    monkeypatch.setattr(
        config,
        "video_store",
        LocalVideoStoreSettings(type="local", save_target=str(tmp_path)),
    )

    async with db.async_session() as session:
        class_ = models.Class(
            id=1,
            name="Test Class",
            institution_id=institution.id,
            api_key="test-key",
        )
        session.add(class_)
        await session.flush()
        session.add(
            models.Assistant(
                id=1,
                name="Chat Assistant",
                class_id=class_.id,
                creator_id=123,
                interaction_mode=schemas.InteractionMode.CHAT,
                version=3,
                model="gpt-4o-mini",
                instructions="Teach the lecture.",
                tools="[]",
            )
        )
        await session.commit()

    response = api.post(
        "/api/v1/class/1/assistant/1/lecture-video/upload",
        files={"upload": ("assistant-upload.mp4", b"video-bytes", "video/mp4")},
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )

    assert response.status_code == 400
    assert "only supports assistants in Lecture Video mode" in response.json()["detail"]

    async with db.async_session() as session:
        lecture_video_count = await session.scalar(
            select(func.count()).select_from(models.LectureVideo)
        )

    assert lecture_video_count == 0


@with_user(123)
@with_institution(11, "Test Institution")
@with_authz(
    grants=[
        ("user:123", "admin", "class:1"),
        ("class:1", "parent", "lecture_video:1"),
        ("user:123", "owner", "lecture_video:1"),
        ("user:123", "can_delete", "lecture_video:1"),
    ]
)
async def test_delete_lecture_video_endpoint_requires_uploader(
    api, db, institution, valid_user_token, config, monkeypatch, tmp_path
):
    monkeypatch.setattr(
        config,
        "video_store",
        LocalVideoStoreSettings(type="local", save_target=str(tmp_path)),
    )

    async with db.async_session() as session:
        session.add(models.User(id=456, email="other@example.com"))
        class_ = models.Class(
            id=1,
            name="Test Class",
            institution_id=institution.id,
            api_key="test-key",
        )
        lecture_video = make_lecture_video(
            class_.id,
            "delete-non-owner.mp4",
            filename="delete-non-owner.mp4",
            uploader_id=456,
        )
        session.add_all([class_, lecture_video])
        await session.commit()
        await session.refresh(lecture_video)

    (tmp_path / "delete-non-owner.mp4").write_bytes(b"video-bytes")

    response = api.delete(
        f"/api/v1/class/1/lecture-video/{lecture_video.id}",
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )

    assert response.status_code == 403
    assert "uploaded this lecture video" in response.json()["detail"]
    assert (tmp_path / "delete-non-owner.mp4").exists()

    async with db.async_session() as session:
        existing_video = await session.get(models.LectureVideo, lecture_video.id)

    assert existing_video is not None


@with_user(123)
@with_institution(11, "Test Institution")
@with_authz(
    grants=[
        ("user:123", "can_delete", "class:1"),
        ("class:1", "parent", "lecture_video:1"),
        ("user:123", "owner", "lecture_video:1"),
    ]
)
async def test_delete_class_deletes_unattached_lecture_videos(
    api, authz, db, institution, valid_user_token, config, monkeypatch, tmp_path
):
    monkeypatch.setattr(
        config,
        "video_store",
        LocalVideoStoreSettings(type="local", save_target=str(tmp_path)),
    )

    async with db.async_session() as session:
        class_ = models.Class(
            id=1,
            name="Test Class",
            institution_id=institution.id,
        )
        lecture_video = make_lecture_video(
            class_.id,
            "class-delete-unattached.mp4",
            filename="class-delete-unattached.mp4",
            uploader_id=123,
            content_length=3,
        )
        session.add_all([class_, lecture_video])
        await session.flush()
        stored_object_id = lecture_video.stored_object.id
        await session.commit()
        await session.refresh(lecture_video)
        lecture_video_id = lecture_video.id

    (tmp_path / "class-delete-unattached.mp4").write_bytes(b"vid")

    response = api.delete(
        "/api/v1/class/1",
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}

    async with db.async_session() as session:
        assert await session.get(models.Class, 1) is None
        assert await session.get(models.LectureVideo, lecture_video_id) is None
        assert (
            await session.get(models.LectureVideoStoredObject, stored_object_id) is None
        )

    assert not (tmp_path / "class-delete-unattached.mp4").exists()
    assert ("revoke", "class:1", "parent", f"lecture_video:{lecture_video_id}") in (
        await authz.get_all_calls()
    )
    assert ("revoke", "user:123", "owner", f"lecture_video:{lecture_video_id}") in (
        await authz.get_all_calls()
    )


@with_user(123)
@with_institution(11, "Test Institution")
@with_authz(
    grants=[
        ("user:123", "can_delete", "class:1"),
        ("class:1", "parent", "lecture_video:1"),
        ("user:123", "owner", "lecture_video:1"),
    ]
)
async def test_delete_class_deletes_assistant_attached_lecture_videos(
    api, authz, db, institution, valid_user_token, config, monkeypatch, tmp_path
):
    monkeypatch.setattr(
        config,
        "video_store",
        LocalVideoStoreSettings(type="local", save_target=str(tmp_path)),
    )

    server_module = importlib.import_module("pingpong.server")

    async def fake_get_openai_client_for_class(_request):
        return SimpleNamespace()

    monkeypatch.setattr(
        server_module,
        "get_openai_client_for_class",
        fake_get_openai_client_for_class,
    )

    async with db.async_session() as session:
        class_ = models.Class(
            id=1,
            name="Test Class",
            institution_id=institution.id,
            api_key="test-key",
        )
        lecture_video = make_lecture_video(
            class_.id,
            "class-delete-attached.mp4",
            filename="class-delete-attached.mp4",
            uploader_id=123,
            content_length=4,
        )
        session.add_all([class_, lecture_video])
        await session.flush()
        stored_object_id = lecture_video.stored_object.id
        session.add(
            models.Assistant(
                id=1,
                name="Lecture Assistant",
                class_id=class_.id,
                interaction_mode=schemas.InteractionMode.LECTURE_VIDEO,
                version=3,
                lecture_video_id=lecture_video.id,
                creator_id=123,
            )
        )
        await session.commit()
        await session.refresh(lecture_video)
        lecture_video_id = lecture_video.id

    (tmp_path / "class-delete-attached.mp4").write_bytes(b"vid2")

    response = api.delete(
        "/api/v1/class/1",
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}

    async with db.async_session() as session:
        assert await session.get(models.Class, 1) is None
        assert await session.get(models.Assistant, 1) is None
        assert await session.get(models.LectureVideo, lecture_video_id) is None
        assert (
            await session.get(models.LectureVideoStoredObject, stored_object_id) is None
        )

    assert not (tmp_path / "class-delete-attached.mp4").exists()
    assert ("revoke", "class:1", "parent", f"lecture_video:{lecture_video_id}") in (
        await authz.get_all_calls()
    )
    assert ("revoke", "user:123", "owner", f"lecture_video:{lecture_video_id}") in (
        await authz.get_all_calls()
    )


@with_user(123)
@with_institution(11, "Test Institution")
@with_authz(
    grants=[
        ("user:123", "can_edit", "assistant:1"),
        ("class:1", "parent", "lecture_video:1"),
        ("user:123", "owner", "lecture_video:1"),
        ("user:123", "can_delete", "lecture_video:1"),
    ]
)
async def test_delete_assistant_lecture_video_endpoint_allows_editor(
    api, authz, db, institution, valid_user_token, config, monkeypatch, tmp_path
):
    monkeypatch.setattr(
        config,
        "video_store",
        LocalVideoStoreSettings(type="local", save_target=str(tmp_path)),
    )

    async with db.async_session() as session:
        class_ = models.Class(
            id=1,
            name="Test Class",
            institution_id=institution.id,
            api_key="test-key",
        )
        lecture_video = make_lecture_video(
            class_.id,
            "assistant-delete.mp4",
            filename="assistant-delete.mp4",
            uploader_id=123,
        )
        session.add_all([class_, lecture_video])
        await session.flush()
        session.add(
            models.Assistant(
                id=1,
                name="Lecture Assistant",
                class_id=class_.id,
                creator_id=123,
                interaction_mode=schemas.InteractionMode.LECTURE_VIDEO,
                version=3,
                model="gpt-4o-mini",
                instructions="Teach the lecture.",
                tools="[]",
            )
        )
        await session.commit()
        await session.refresh(lecture_video)

    (tmp_path / "assistant-delete.mp4").write_bytes(b"video-bytes")

    response = api.delete(
        f"/api/v1/class/1/assistant/1/lecture-video/{lecture_video.id}",
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}

    async with db.async_session() as session:
        deleted_video = await session.get(models.LectureVideo, lecture_video.id)

    assert deleted_video is None
    assert not (tmp_path / "assistant-delete.mp4").exists()
    assert await authz.get_all_calls() == [
        ("revoke", "class:1", "parent", "lecture_video:1"),
        ("revoke", "user:123", "owner", "lecture_video:1"),
    ]


@with_user(123)
@with_institution(11, "Test Institution")
@with_authz(grants=[("user:123", "can_edit", "assistant:1")])
async def test_delete_assistant_lecture_video_endpoint_requires_entry_can_delete(
    api, db, institution, valid_user_token, config, monkeypatch, tmp_path
):
    monkeypatch.setattr(
        config,
        "video_store",
        LocalVideoStoreSettings(type="local", save_target=str(tmp_path)),
    )

    async with db.async_session() as session:
        class_ = models.Class(
            id=1,
            name="Test Class",
            institution_id=institution.id,
            api_key="test-key",
        )
        lecture_video = make_lecture_video(
            class_.id,
            "assistant-delete-missing-entry-perm.mp4",
            filename="assistant-delete-missing-entry-perm.mp4",
            uploader_id=123,
        )
        session.add_all([class_, lecture_video])
        await session.flush()
        session.add(
            models.Assistant(
                id=1,
                name="Lecture Assistant",
                class_id=class_.id,
                creator_id=123,
                interaction_mode=schemas.InteractionMode.LECTURE_VIDEO,
                version=3,
                model="gpt-4o-mini",
                instructions="Teach the lecture.",
                tools="[]",
            )
        )
        await session.commit()
        await session.refresh(lecture_video)

    (tmp_path / "assistant-delete-missing-entry-perm.mp4").write_bytes(b"video-bytes")

    response = api.delete(
        f"/api/v1/class/1/assistant/1/lecture-video/{lecture_video.id}",
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "Missing required role"
    assert (tmp_path / "assistant-delete-missing-entry-perm.mp4").exists()

    async with db.async_session() as session:
        existing_video = await session.get(models.LectureVideo, lecture_video.id)

    assert existing_video is not None


@with_user(123)
@with_institution(11, "Test Institution")
@with_authz(
    grants=[
        ("user:123", "can_edit", "assistant:1"),
        ("class:1", "parent", "lecture_video:1"),
        ("user:123", "owner", "lecture_video:1"),
        ("user:123", "can_delete", "lecture_video:1"),
    ]
)
async def test_delete_assistant_lecture_video_endpoint_rejects_non_lecture_assistant(
    api, db, institution, valid_user_token, config, monkeypatch, tmp_path
):
    monkeypatch.setattr(
        config,
        "video_store",
        LocalVideoStoreSettings(type="local", save_target=str(tmp_path)),
    )

    async with db.async_session() as session:
        class_ = models.Class(
            id=1,
            name="Test Class",
            institution_id=institution.id,
            api_key="test-key",
        )
        lecture_video = make_lecture_video(
            class_.id,
            "chat-assistant-delete.mp4",
            filename="chat-assistant-delete.mp4",
        )
        session.add_all([class_, lecture_video])
        await session.flush()
        session.add(
            models.Assistant(
                id=1,
                name="Chat Assistant",
                class_id=class_.id,
                creator_id=123,
                interaction_mode=schemas.InteractionMode.CHAT,
                version=3,
                model="gpt-4o-mini",
                instructions="Teach the lecture.",
                tools="[]",
            )
        )
        await session.commit()
        await session.refresh(lecture_video)

    (tmp_path / "chat-assistant-delete.mp4").write_bytes(b"video-bytes")

    response = api.delete(
        f"/api/v1/class/1/assistant/1/lecture-video/{lecture_video.id}",
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )

    assert response.status_code == 400
    assert "only supports assistants in Lecture Video mode" in response.json()["detail"]
    assert (tmp_path / "chat-assistant-delete.mp4").exists()


@with_user(123)
@with_institution(11, "Test Institution")
@with_authz(
    grants=[
        ("user:123", "can_edit", "assistant:1"),
        ("class:1", "parent", "lecture_video:1"),
        ("user:123", "owner", "lecture_video:1"),
        ("user:123", "can_delete", "lecture_video:1"),
    ]
)
async def test_delete_assistant_lecture_video_endpoint_requires_uploader(
    api, db, institution, valid_user_token, config, monkeypatch, tmp_path
):
    monkeypatch.setattr(
        config,
        "video_store",
        LocalVideoStoreSettings(type="local", save_target=str(tmp_path)),
    )

    async with db.async_session() as session:
        session.add(models.User(id=456, email="other@example.com"))
        class_ = models.Class(
            id=1,
            name="Test Class",
            institution_id=institution.id,
            api_key="test-key",
        )
        lecture_video = make_lecture_video(
            class_.id,
            "assistant-unrelated-delete.mp4",
            filename="assistant-unrelated-delete.mp4",
            uploader_id=456,
        )
        session.add_all([class_, lecture_video])
        await session.flush()
        session.add(
            models.Assistant(
                id=1,
                name="Lecture Assistant",
                class_id=class_.id,
                creator_id=123,
                interaction_mode=schemas.InteractionMode.LECTURE_VIDEO,
                version=3,
                model="gpt-4o-mini",
                instructions="Teach the lecture.",
                tools="[]",
            )
        )
        await session.commit()
        await session.refresh(lecture_video)

    (tmp_path / "assistant-unrelated-delete.mp4").write_bytes(b"video-bytes")

    response = api.delete(
        f"/api/v1/class/1/assistant/1/lecture-video/{lecture_video.id}",
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )

    assert response.status_code == 403
    assert "uploaded this lecture video" in response.json()["detail"]
    assert (tmp_path / "assistant-unrelated-delete.mp4").exists()


@with_user(123)
@with_institution(11, "Test Institution")
@with_authz(
    grants=[
        ("user:123", "admin", "class:1"),
        ("user:123", "can_create_assistants", "class:1"),
    ]
)
async def test_create_lecture_video_assistant_persists_normalized_manifest(
    api, db, institution, valid_user_token, monkeypatch
):
    patch_lecture_video_model_list(monkeypatch)

    async with db.async_session() as session:
        class_ = models.Class(
            id=1,
            name="Lecture Class",
            institution_id=institution.id,
            api_key="sk-test",
        )
        lecture_video = make_lecture_video(
            class_.id,
            "uploaded-lecture.mp4",
            filename="uploaded-lecture.mp4",
            status=schemas.LectureVideoStatus.UPLOADED.value,
        )
        session.add(class_)
        session.add(lecture_video)
        await create_lecture_video_copy_credentials(session, class_.id)
        await session.commit()
        await session.refresh(lecture_video)

    manifest = lecture_video_manifest()
    response = api.post(
        "/api/v1/class/1/assistant",
        json={
            "name": "Lecture Assistant",
            "instructions": "Guide the learner through the lecture.",
            "description": "Lecture presentation assistant",
            "interaction_mode": "lecture_video",
            "model": "gpt-4o-mini",
            "tools": [],
            "lecture_video_id": lecture_video.id,
            "lecture_video_manifest": manifest,
            "voice_id": DEFAULT_LECTURE_VIDEO_VOICE_ID,
        },
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["lecture_video"]["id"] == lecture_video.id
    assert (
        body["lecture_video"]["status"] == schemas.LectureVideoStatus.PROCESSING.value
    )
    assert "lecture_video_manifest" not in body

    async with db.async_session() as session:
        refreshed_video = await session.get(models.LectureVideo, lecture_video.id)
        question_count = await session.scalar(
            select(func.count())
            .select_from(models.LectureVideoQuestion)
            .where(models.LectureVideoQuestion.lecture_video_id == lecture_video.id)
        )
        option_count = await session.scalar(
            select(func.count())
            .select_from(models.LectureVideoQuestionOption)
            .join(
                models.LectureVideoQuestion,
                models.LectureVideoQuestion.id
                == models.LectureVideoQuestionOption.question_id,
            )
            .where(models.LectureVideoQuestion.lecture_video_id == lecture_video.id)
        )
        single_select_correct_option_count = await session.scalar(
            select(func.count()).select_from(
                models.lecture_video_question_single_select_correct_option_association
            )
        )
        narration_count = await session.scalar(
            select(func.count()).select_from(models.LectureVideoNarration)
        )
        processing_run_count = await session.scalar(
            select(func.count()).select_from(models.LectureVideoProcessingRun)
        )

    assert refreshed_video is not None
    assert refreshed_video.status == schemas.LectureVideoStatus.PROCESSING.value
    assert refreshed_video.voice_id == DEFAULT_LECTURE_VIDEO_VOICE_ID
    assert question_count == 1
    assert option_count == 2
    assert single_select_correct_option_count == 1
    assert narration_count == 3
    assert processing_run_count == 1


@with_user(123)
@with_institution(11, "Test Institution")
@with_authz(
    grants=[
        ("user:123", "admin", "class:1"),
        ("user:123", "can_create_assistants", "class:1"),
    ]
)
async def test_create_lecture_video_assistant_requires_provider_credentials(
    api, db, institution, valid_user_token, monkeypatch
):
    patch_lecture_video_model_list(monkeypatch)

    async with db.async_session() as session:
        class_ = models.Class(
            id=1,
            name="Lecture Class",
            institution_id=institution.id,
            api_key="sk-test",
        )
        lecture_video = make_lecture_video(
            class_.id,
            "missing-providers.mp4",
            filename="missing-providers.mp4",
            status=schemas.LectureVideoStatus.UPLOADED.value,
        )
        session.add_all([class_, lecture_video])
        await session.commit()
        await session.refresh(lecture_video)

    response = api.post(
        "/api/v1/class/1/assistant",
        json={
            "name": "Lecture Assistant",
            "instructions": "Guide the learner through the lecture.",
            "description": "Lecture presentation assistant",
            "interaction_mode": "lecture_video",
            "model": "gpt-4o-mini",
            "tools": [],
            "lecture_video_id": lecture_video.id,
            "lecture_video_manifest": lecture_video_manifest(),
            "voice_id": DEFAULT_LECTURE_VIDEO_VOICE_ID,
        },
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )

    assert response.status_code == 400
    assert (
        response.json()["detail"]
        == "Configure Gemini and ElevenLabs credentials in Manage Group to enable Lecture Video mode."
    )

    async with db.async_session() as session:
        assistant_count = await session.scalar(
            select(func.count()).select_from(models.Assistant)
        )
        refreshed_video = await session.get(models.LectureVideo, lecture_video.id)

    assert assistant_count == 0
    assert refreshed_video is not None
    assert refreshed_video.status == schemas.LectureVideoStatus.UPLOADED.value


@with_institution(11, "Test Institution")
async def test_process_claimed_narration_run_marks_lecture_video_ready_and_stores_audio(
    db, institution, config, monkeypatch, tmp_path
):
    narration_dir = tmp_path / "narration-audio"
    monkeypatch.setattr(
        config,
        "lecture_video_audio_store",
        LocalAudioStoreSettings(save_target=str(narration_dir)),
    )
    monkeypatch.setattr(
        lecture_video_processing,
        "synthesize_elevenlabs_speech",
        AsyncMock(return_value=("audio/ogg", b"fake-opus-audio")),
    )

    async with db.async_session() as session:
        (
            _class_,
            lecture_video,
            _assistant,
            run,
        ) = await create_processing_lecture_video_assistant(session, institution)
        assert run is not None

    claim = await lecture_video_processing._claim_next_narration_run(
        leased_by="test-runner"
    )
    assert claim is not None
    run_id, lease_token = claim
    await lecture_video_processing._process_claimed_narration_run(run_id, lease_token)

    async with db.async_session() as session:
        refreshed_video = await models.LectureVideo.get_by_id_with_copy_context(
            session, lecture_video.id
        )
        refreshed_run = await models.LectureVideoProcessingRun.get_by_id(
            session, run.id
        )
        narrations = list(
            (
                await session.scalars(
                    select(models.LectureVideoNarration)
                    .options(selectinload(models.LectureVideoNarration.stored_object))
                    .order_by(models.LectureVideoNarration.id.asc())
                )
            ).all()
        )

    assert refreshed_video is not None
    assert refreshed_video.status == schemas.LectureVideoStatus.READY
    assert refreshed_video.error_message is None
    assert refreshed_run is not None
    assert refreshed_run.status == schemas.LectureVideoProcessingRunStatus.COMPLETED
    assert len(narrations) == 3
    assert all(
        narration.status == schemas.LectureVideoNarrationStatus.READY
        and narration.stored_object is not None
        and narration.stored_object.content_type == "audio/ogg"
        for narration in narrations
    )
    for narration in narrations:
        assert (narration_dir / narration.stored_object.key).exists()


@with_institution(11, "Test Institution")
async def test_process_claimed_narration_run_marks_failed_on_provider_error(
    db, institution, monkeypatch
):
    monkeypatch.setattr(
        lecture_video_processing,
        "synthesize_elevenlabs_speech",
        AsyncMock(
            side_effect=ClassCredentialValidationUnavailableError(
                provider=schemas.ClassCredentialProvider.ELEVENLABS,
                message="ElevenLabs is temporarily unavailable.",
            )
        ),
    )

    async with db.async_session() as session:
        (
            _class_,
            lecture_video,
            _assistant,
            run,
        ) = await create_processing_lecture_video_assistant(session, institution)
        assert run is not None

    claim = await lecture_video_processing._claim_next_narration_run(
        leased_by="test-runner"
    )
    assert claim is not None
    run_id, lease_token = claim
    await lecture_video_processing._process_claimed_narration_run(run_id, lease_token)

    async with db.async_session() as session:
        refreshed_video = await models.LectureVideo.get_by_id(session, lecture_video.id)
        refreshed_run = await models.LectureVideoProcessingRun.get_by_id(
            session, run.id
        )
        narrations = list(
            (
                await session.scalars(
                    select(models.LectureVideoNarration).order_by(
                        models.LectureVideoNarration.id.asc()
                    )
                )
            ).all()
        )

    assert refreshed_video is not None
    assert refreshed_video.status == schemas.LectureVideoStatus.FAILED
    assert refreshed_video.error_message == "ElevenLabs is temporarily unavailable."
    assert refreshed_run is not None
    assert refreshed_run.status == schemas.LectureVideoProcessingRunStatus.FAILED
    assert refreshed_run.error_message == "ElevenLabs is temporarily unavailable."
    assert narrations[0].status == schemas.LectureVideoNarrationStatus.FAILED
    assert narrations[1].status == schemas.LectureVideoNarrationStatus.PENDING
    assert narrations[2].status == schemas.LectureVideoNarrationStatus.PENDING


async def test_process_claimed_narration_run_raises_type_error_for_unexpected_work_item(
    monkeypatch,
):
    prepare_next_work_item = AsyncMock(return_value=("work", object()))
    synthesize = AsyncMock()

    monkeypatch.setattr(
        lecture_video_processing,
        "_prepare_next_work_item",
        prepare_next_work_item,
    )
    monkeypatch.setattr(
        lecture_video_processing,
        "synthesize_elevenlabs_speech",
        synthesize,
    )

    with pytest.raises(TypeError, match="Expected NarrationWorkItem, got object"):
        await lecture_video_processing._process_claimed_narration_run(1, "lease-token")

    synthesize.assert_not_awaited()


def test_get_forkserver_context_requires_forkserver(monkeypatch):
    monkeypatch.setattr(
        lecture_video_processing.multiprocessing,
        "get_all_start_methods",
        lambda: ["spawn", "fork"],
    )

    with pytest.raises(RuntimeError):
        lecture_video_processing.get_forkserver_context()


def test_get_forkserver_context_requests_forkserver(monkeypatch):
    seen: dict[str, object] = {}
    expected_context = object()

    monkeypatch.setattr(
        lecture_video_processing.multiprocessing,
        "get_all_start_methods",
        lambda: ["spawn", "forkserver"],
    )
    monkeypatch.setattr(
        lecture_video_processing.multiprocessing,
        "get_context",
        lambda start_method: seen.__setitem__("start_method", start_method)
        or expected_context,
    )

    context = lecture_video_processing.get_forkserver_context()

    assert seen["start_method"] == "forkserver"
    assert context is expected_context


def test_build_runner_id_uses_worker_slot_and_pid():
    runner_id = lecture_video_processing.build_runner_id(worker_slot=3, pid=4242)
    fallback_runner_id = lecture_video_processing.build_runner_id(worker_slot=4, pid=7)

    assert runner_id.endswith(":4242:worker-3")
    assert fallback_runner_id.endswith(":7:worker-4")
    assert runner_id != fallback_runner_id


def test_worker_process_main_ignores_sigint_before_waiting_for_assignments(
    monkeypatch,
):
    fake_assignment_queue = FakeQueue()
    fake_result_queue = FakeQueue()
    fake_assignment_queue.put(None)
    seen: dict[str, bool] = {}

    @contextmanager
    def fake_sentry():
        yield

    monkeypatch.setattr(lecture_video_processing, "sentry", fake_sentry)
    monkeypatch.setattr(
        lecture_video_processing,
        "ignore_sigint_in_worker",
        lambda: seen.setdefault("ignored", True),
    )
    monkeypatch.setattr(lecture_video_processing.os, "getpid", lambda: 4242)

    lecture_video_processing._worker_process_main(
        2,
        fake_assignment_queue,
        fake_result_queue,
    )

    assert seen == {"ignored": True}
    assert fake_result_queue.puts == [
        lecture_video_processing.WorkerReady(worker_slot=2, pid=4242)
    ]


def test_worker_process_main_raises_type_error_for_unexpected_assignment(
    monkeypatch,
):
    fake_assignment_queue = FakeQueue()
    fake_result_queue = FakeQueue()
    fake_assignment_queue.put(object())

    @contextmanager
    def fake_sentry():
        yield

    monkeypatch.setattr(lecture_video_processing, "sentry", fake_sentry)
    monkeypatch.setattr(
        lecture_video_processing,
        "ignore_sigint_in_worker",
        lambda: None,
    )
    monkeypatch.setattr(lecture_video_processing.os, "getpid", lambda: 4242)

    with pytest.raises(TypeError, match="Expected RunAssignment, got object"):
        lecture_video_processing._worker_process_main(
            2,
            fake_assignment_queue,
            fake_result_queue,
        )


def test_worker_pool_manager_uses_generic_labels_and_recovery(caplog):
    fake_context = FakeProcessContext()
    recoveries: list[tuple[int, str, str]] = []
    claims = iter([(41, "lease-41"), None])

    manager = lecture_video_processing.WorkerPoolManager(
        workers=1,
        worker_target=lambda *_args: None,
        process_context=fake_context,
        claim_run_fn=lambda _runner_id: next(claims),
        recover_run_fn=lambda run_id, lease_token, error_message: recoveries.append(
            (run_id, lease_token, error_message)
        )
        or True,
        build_runner_id_fn=lambda worker_slot, pid: f"custom:{worker_slot}:{pid}",
        worker_label="custom worker",
        unexpected_exit_error_message="custom exit",
        poll_interval_seconds=0.25,
    )

    with caplog.at_level(logging.INFO):
        manager.start()
        progress = manager.run_one_iteration()
        manager.results_queue.put(
            lecture_video_processing.WorkerJobException(
                worker_slot=0,
                run_id=41,
                lease_token="lease-41",
                error_message="",
            )
        )
        recovery_progress = manager.run_one_iteration()

    assert progress is True
    assert recovery_progress is True
    assert isinstance(
        manager.worker_slots[0].assignment_queue.puts[0],
        lecture_video_processing.RunAssignment,
    )
    assert recoveries == [(41, "lease-41", "custom exit")]
    assert manager.worker_slots[0].idle is True
    assert manager.worker_slots[0].run_id is None
    assert manager.worker_slots[0].lease_token is None
    assert "Started custom worker process." in caplog.text
    assert "Custom worker reported job exception." in caplog.text
    assert "Lecture video worker" not in caplog.text


def test_narration_worker_pool_manager_assigns_runs_to_idle_workers():
    fake_context = FakeProcessContext()
    claims = iter([(11, "lease-11"), (12, "lease-12"), None])

    manager = lecture_video_processing.NarrationWorkerPoolManager(
        workers=3,
        poll_interval_seconds=0.25,
        process_context=fake_context,
        claim_run_fn=lambda _runner_id: next(claims),
        recover_run_fn=lambda *_args: True,
    )

    manager.start()
    progress = manager.run_one_iteration()

    assert progress is True
    assert len(fake_context.processes) == 3
    assert isinstance(
        manager.worker_slots[0].assignment_queue.puts[0],
        lecture_video_processing.RunAssignment,
    )
    assert manager.worker_slots[0].run_id == 11
    assert manager.worker_slots[1].run_id == 12
    assert manager.worker_slots[2].idle is True


def test_narration_worker_pool_manager_recovers_job_exception_and_keeps_worker_idle():
    fake_context = FakeProcessContext()
    recoveries: list[tuple[int, str, str]] = []
    claims = iter([(21, "lease-21"), None])

    manager = lecture_video_processing.NarrationWorkerPoolManager(
        workers=1,
        poll_interval_seconds=0.25,
        process_context=fake_context,
        claim_run_fn=lambda _runner_id: next(claims),
        recover_run_fn=lambda run_id, lease_token, error_message: recoveries.append(
            (run_id, lease_token, error_message)
        )
        or True,
    )

    manager.start()
    manager.run_one_iteration()
    manager.results_queue.put(
        lecture_video_processing.WorkerJobException(
            worker_slot=0,
            run_id=21,
            lease_token="lease-21",
            error_message="boom",
        )
    )

    progress = manager.run_one_iteration()

    assert progress is True
    assert recoveries == [(21, "lease-21", "boom")]
    assert manager.worker_slots[0].idle is True
    assert manager.worker_slots[0].run_id is None
    assert manager.worker_slots[0].lease_token is None


def test_narration_worker_pool_manager_clears_assignment_if_job_recovery_raises():
    fake_context = FakeProcessContext()
    claims = iter([(22, "lease-22"), None])

    manager = lecture_video_processing.NarrationWorkerPoolManager(
        workers=1,
        poll_interval_seconds=0.25,
        process_context=fake_context,
        claim_run_fn=lambda _runner_id: next(claims),
        recover_run_fn=lambda *_args: (_ for _ in ()).throw(RuntimeError("db down")),
    )

    manager.start()
    manager.run_one_iteration()
    manager.results_queue.put(
        lecture_video_processing.WorkerJobException(
            worker_slot=0,
            run_id=22,
            lease_token="lease-22",
            error_message="boom",
        )
    )

    with pytest.raises(RuntimeError, match="db down"):
        manager.run_one_iteration()

    assert manager.worker_slots[0].idle is True
    assert manager.worker_slots[0].run_id is None
    assert manager.worker_slots[0].lease_token is None


def test_narration_worker_pool_manager_recovers_dead_worker_and_respawns():
    fake_context = FakeProcessContext()
    recoveries: list[tuple[int, str, str]] = []
    claims = iter([(31, "lease-31"), None, None])

    manager = lecture_video_processing.NarrationWorkerPoolManager(
        workers=1,
        poll_interval_seconds=0.25,
        process_context=fake_context,
        claim_run_fn=lambda _runner_id: next(claims),
        recover_run_fn=lambda run_id, lease_token, error_message: recoveries.append(
            (run_id, lease_token, error_message)
        )
        or True,
    )

    manager.start()
    original_pid = manager.worker_slots[0].pid
    manager.run_one_iteration()
    manager.worker_slots[0].process.exitcode = 1

    progress = manager.run_one_iteration()

    assert progress is True
    assert recoveries == [
        (
            31,
            "lease-31",
            lecture_video_processing.UNEXPECTED_WORKER_EXIT_ERROR_MESSAGE,
        )
    ]
    assert len(fake_context.processes) == 2
    assert manager.worker_slots[0].pid != original_pid
    assert manager.worker_slots[0].idle is True


def test_narration_worker_pool_manager_clears_assignment_if_dead_worker_recovery_raises():
    fake_context = FakeProcessContext()
    claims = iter([(32, "lease-32"), None])

    manager = lecture_video_processing.NarrationWorkerPoolManager(
        workers=1,
        poll_interval_seconds=0.25,
        process_context=fake_context,
        claim_run_fn=lambda _runner_id: next(claims),
        recover_run_fn=lambda *_args: (_ for _ in ()).throw(RuntimeError("db down")),
    )

    manager.start()
    manager.run_one_iteration()
    manager.worker_slots[0].process.exitcode = 1

    with pytest.raises(RuntimeError, match="db down"):
        manager.run_one_iteration()

    assert manager.worker_slots[0].idle is True
    assert manager.worker_slots[0].run_id is None
    assert manager.worker_slots[0].lease_token is None


def test_narration_worker_pool_manager_shutdown_terminates_only_stuck_workers():
    fake_context = FakeProcessContext()
    manager = lecture_video_processing.NarrationWorkerPoolManager(
        workers=2,
        poll_interval_seconds=0.25,
        process_context=fake_context,
        claim_run_fn=lambda _runner_id: None,
        recover_run_fn=lambda *_args: True,
        shutdown_grace_seconds=1.0,
    )

    manager.start()
    first_slot = manager.worker_slots[0]
    second_slot = manager.worker_slots[1]
    first_slot.process.exit_after_join = 0

    manager.shutdown()

    assert first_slot.assignment_queue.puts[-1] is None
    assert second_slot.assignment_queue.puts[-1] is None
    assert first_slot.process.terminate_called is False
    assert second_slot.process.terminate_called is True


def test_narration_worker_pool_manager_shutdown_recovers_busy_assignments_before_terminate():
    fake_context = FakeProcessContext()
    recoveries: list[tuple[int, str, str]] = []
    claims = iter([(41, "lease-41"), None])
    manager = lecture_video_processing.NarrationWorkerPoolManager(
        workers=1,
        poll_interval_seconds=0.25,
        process_context=fake_context,
        claim_run_fn=lambda _runner_id: next(claims),
        recover_run_fn=lambda run_id, lease_token, error_message: recoveries.append(
            (run_id, lease_token, error_message)
        )
        or True,
        shutdown_grace_seconds=1.0,
    )

    manager.start()
    progress = manager.run_one_iteration()
    slot = manager.worker_slots[0]

    manager.shutdown()

    assert progress is True
    assert isinstance(
        slot.assignment_queue.puts[0], lecture_video_processing.RunAssignment
    )
    assert slot.assignment_queue.puts[-1] is None
    assert slot.process.terminate_called is True
    assert slot.idle is True
    assert slot.run_id is None
    assert slot.lease_token is None
    assert recoveries == [
        (
            41,
            "lease-41",
            lecture_video_processing.UNEXPECTED_WORKER_EXIT_ERROR_MESSAGE,
        )
    ]


def test_narration_worker_pool_manager_shutdown_drains_queued_worker_job_exception():
    fake_context = FakeProcessContext()
    recoveries: list[tuple[int, str, str]] = []
    claims = iter([(51, "lease-51"), None])
    manager = lecture_video_processing.NarrationWorkerPoolManager(
        workers=1,
        poll_interval_seconds=0.25,
        process_context=fake_context,
        claim_run_fn=lambda _runner_id: next(claims),
        recover_run_fn=lambda run_id, lease_token, error_message: recoveries.append(
            (run_id, lease_token, error_message)
        )
        or True,
        shutdown_grace_seconds=1.0,
    )

    manager.start()
    progress = manager.run_one_iteration()
    slot = manager.worker_slots[0]
    slot.process.exit_after_join = 0
    manager.results_queue.put(
        lecture_video_processing.WorkerJobException(
            worker_slot=0,
            run_id=51,
            lease_token="lease-51",
            error_message="boom",
        )
    )

    manager.shutdown()

    assert progress is True
    assert slot.process.terminate_called is False
    assert slot.idle is True
    assert slot.run_id is None
    assert slot.lease_token is None
    assert recoveries == [(51, "lease-51", "boom")]


def test_worker_pool_manager_run_shuts_down_if_signal_setup_fails(monkeypatch):
    fake_context = FakeProcessContext()
    manager = lecture_video_processing.NarrationWorkerPoolManager(
        workers=1,
        poll_interval_seconds=0.25,
        process_context=fake_context,
        claim_run_fn=lambda _runner_id: None,
        recover_run_fn=lambda *_args: True,
        shutdown_grace_seconds=1.0,
    )
    previous_sigint_handler = "previous-sigint"
    previous_sigterm_handler = "previous-sigterm"
    signal_calls: list[tuple[int, object]] = []

    def fake_getsignal(signum: int) -> object:
        if signum == signal.SIGINT:
            return previous_sigint_handler
        if signum == signal.SIGTERM:
            return previous_sigterm_handler
        raise AssertionError(f"Unexpected signal: {signum}")

    def fake_signal(signum: int, handler: object) -> object:
        signal_calls.append((signum, handler))
        if signum == signal.SIGTERM and handler not in {
            previous_sigint_handler,
            previous_sigterm_handler,
        }:
            raise RuntimeError("install failed")
        return handler

    monkeypatch.setattr(worker_pool_module.signal, "getsignal", fake_getsignal)
    monkeypatch.setattr(worker_pool_module.signal, "signal", fake_signal)

    with pytest.raises(RuntimeError, match="install failed"):
        manager.run()

    slot = manager.worker_slots[0]
    assert len(fake_context.processes) == 1
    assert slot.assignment_queue.puts[-1] is None
    assert slot.process.terminate_called is True
    assert signal_calls[0][0] == signal.SIGINT
    assert callable(signal_calls[0][1])
    assert signal_calls[1][0] == signal.SIGTERM
    assert callable(signal_calls[1][1])
    assert signal_calls[2] == (signal.SIGINT, previous_sigint_handler)
    assert signal_calls[3] == (signal.SIGTERM, previous_sigterm_handler)


def test_worker_pool_manager_run_skips_restoring_unknown_signal_handlers(monkeypatch):
    fake_context = FakeProcessContext()
    manager = lecture_video_processing.NarrationWorkerPoolManager(
        workers=1,
        poll_interval_seconds=0.25,
        process_context=fake_context,
        claim_run_fn=lambda _runner_id: None,
        recover_run_fn=lambda *_args: True,
        shutdown_grace_seconds=1.0,
    )
    signal_calls: list[tuple[int, object]] = []

    monkeypatch.setattr(worker_pool_module.signal, "getsignal", lambda _signum: None)

    def fake_signal(signum: int, handler: object) -> object:
        assert handler is not None
        signal_calls.append((signum, handler))
        return handler

    def fake_run_one_iteration() -> bool:
        manager.request_stop()
        return True

    monkeypatch.setattr(worker_pool_module.signal, "signal", fake_signal)
    monkeypatch.setattr(manager, "run_one_iteration", fake_run_one_iteration)

    manager.run()

    assert len(fake_context.processes) == 1
    assert len(signal_calls) == 2
    assert signal_calls[0][0] == signal.SIGINT
    assert callable(signal_calls[0][1])
    assert signal_calls[1][0] == signal.SIGTERM
    assert callable(signal_calls[1][1])


def test_run_lecture_video_worker_cli_starts_health_server_and_passes_pool_settings(
    monkeypatch,
):
    runner = CliRunner()
    seen: dict[str, object] = {}

    class FakeServer:
        @contextmanager
        def run_in_thread(self):
            seen["server_started"] = True
            yield

    def fake_get_server(host="localhost", port=8001):
        seen["host"] = host
        seen["port"] = port
        return FakeServer()

    def fake_worker_pool(*, poll_interval_seconds: float, workers: int) -> None:
        seen["poll_interval_seconds"] = poll_interval_seconds
        seen["workers"] = workers

    monkeypatch.setattr(cli_module, "get_server", fake_get_server)
    monkeypatch.setattr(
        lecture_video_processing,
        "run_narration_processing_worker_pool",
        fake_worker_pool,
    )

    result = runner.invoke(
        cli_module.cli,
        [
            "lecture-video",
            "run-worker",
            "--host",
            "0.0.0.0",
            "--port",
            "8123",
            "--poll-interval",
            "0.25",
            "--workers",
            "3",
        ],
    )

    assert result.exit_code == 0
    assert seen == {
        "host": "0.0.0.0",
        "port": 8123,
        "poll_interval_seconds": 0.25,
        "workers": 3,
        "server_started": True,
    }


@with_institution(11, "Test Institution")
async def test_recover_failed_narration_run_marks_run_video_and_processing_narration_failed(
    db, institution
):
    async with db.async_session() as session:
        (
            _class_,
            lecture_video,
            _assistant,
            run,
        ) = await create_processing_lecture_video_assistant(session, institution)
        assert run is not None

    claim = await lecture_video_processing._claim_next_narration_run(
        leased_by="test-runner"
    )
    assert claim is not None
    run_id, lease_token = claim
    assert run_id == run.id

    state, payload = await lecture_video_processing._prepare_next_work_item(
        run_id,
        lease_token,
    )
    assert state == "work"
    assert isinstance(payload, lecture_video_processing.NarrationWorkItem)

    recovered = await lecture_video_processing.recover_failed_narration_run(
        run_id,
        lease_token,
        error_message=lecture_video_processing.UNEXPECTED_WORKER_EXIT_ERROR_MESSAGE,
    )

    assert recovered is True

    async with db.async_session() as session:
        refreshed_video = await models.LectureVideo.get_by_id_with_copy_context(
            session, lecture_video.id
        )
        refreshed_run = await models.LectureVideoProcessingRun.get_by_id(
            session, run.id
        )
        narrations = list(
            (
                await session.scalars(
                    select(models.LectureVideoNarration).order_by(
                        models.LectureVideoNarration.id.asc()
                    )
                )
            ).all()
        )

    assert refreshed_video is not None
    assert refreshed_video.status == schemas.LectureVideoStatus.FAILED
    assert (
        refreshed_video.error_message
        == lecture_video_processing.UNEXPECTED_WORKER_EXIT_ERROR_MESSAGE
    )
    assert refreshed_run is not None
    assert refreshed_run.status == schemas.LectureVideoProcessingRunStatus.FAILED
    assert (
        refreshed_run.error_message
        == lecture_video_processing.UNEXPECTED_WORKER_EXIT_ERROR_MESSAGE
    )
    assert refreshed_run.lease_token is None
    assert refreshed_run.leased_by is None
    assert refreshed_run.lease_expires_at is None
    assert narrations[0].status == schemas.LectureVideoNarrationStatus.FAILED
    assert (
        narrations[0].error_message
        == lecture_video_processing.UNEXPECTED_WORKER_EXIT_ERROR_MESSAGE
    )
    assert narrations[1].status == schemas.LectureVideoNarrationStatus.PENDING
    assert narrations[2].status == schemas.LectureVideoNarrationStatus.PENDING


@with_institution(11, "Test Institution")
async def test_recover_failed_narration_run_ignores_stale_lease_token(db, institution):
    async with db.async_session() as session:
        (
            _class_,
            _lecture_video,
            _assistant,
            run,
        ) = await create_processing_lecture_video_assistant(session, institution)
        assert run is not None

    claim = await lecture_video_processing._claim_next_narration_run(
        leased_by="test-runner"
    )
    assert claim is not None
    run_id, lease_token = claim

    recovered = await lecture_video_processing.recover_failed_narration_run(
        run_id,
        "stale-token",
        error_message=lecture_video_processing.UNEXPECTED_WORKER_EXIT_ERROR_MESSAGE,
    )

    assert recovered is False

    async with db.async_session() as session:
        refreshed_run = await models.LectureVideoProcessingRun.get_by_id(
            session, run.id
        )

    assert refreshed_run is not None
    assert refreshed_run.status == schemas.LectureVideoProcessingRunStatus.RUNNING
    assert refreshed_run.lease_token == lease_token


@with_institution(11, "Test Institution")
async def test_recover_failed_narration_run_completes_when_final_narration_was_already_attached(
    db, institution
):
    async with db.async_session() as session:
        (
            _class_,
            lecture_video,
            _assistant,
            run,
        ) = await create_processing_lecture_video_assistant(
            session,
            institution,
            manifest=lecture_video_manifest(
                intro_text="Only narration",
                post_answer_texts=("", ""),
            ),
        )
        assert run is not None

    claim = await lecture_video_processing._claim_next_narration_run(
        leased_by="test-runner"
    )
    assert claim is not None
    run_id, lease_token = claim
    assert run_id == run.id

    state, payload = await lecture_video_processing._prepare_next_work_item(
        run_id,
        lease_token,
    )
    assert state == "work"
    assert isinstance(payload, lecture_video_processing.NarrationWorkItem)

    attached = await lecture_video_processing._attach_stored_audio_to_narration(
        run_id,
        lease_token,
        payload.narration_id,
        "audio/ogg",
        len(b"final-audio"),
        "recover-final-ready.ogg",
    )
    assert attached is True

    recovered = await lecture_video_processing.recover_failed_narration_run(
        run_id,
        lease_token,
        error_message=lecture_video_processing.UNEXPECTED_WORKER_EXIT_ERROR_MESSAGE,
    )

    assert recovered is True

    async with db.async_session() as session:
        refreshed_video = await models.LectureVideo.get_by_id_with_copy_context(
            session, lecture_video.id
        )
        refreshed_run = await models.LectureVideoProcessingRun.get_by_id(
            session, run.id
        )

    assert refreshed_video is not None
    assert refreshed_video.status == schemas.LectureVideoStatus.READY
    assert refreshed_video.error_message is None
    assert refreshed_run is not None
    assert refreshed_run.status == schemas.LectureVideoProcessingRunStatus.COMPLETED
    assert refreshed_run.error_message is None
    assert refreshed_video.questions[0].intro_narration is not None
    assert refreshed_video.questions[0].intro_narration.status == (
        schemas.LectureVideoNarrationStatus.READY
    )
    assert refreshed_video.questions[0].intro_narration.error_message is None
    assert refreshed_video.questions[0].intro_narration.stored_object is not None


@with_institution(11, "Test Institution")
async def test_mark_run_failed_ignores_stale_lease_token(db, institution):
    async with db.async_session() as session:
        (
            _class_,
            lecture_video,
            _assistant,
            run,
        ) = await create_processing_lecture_video_assistant(session, institution)
        assert run is not None
        loaded_lecture_video = await models.LectureVideo.get_by_id_with_copy_context(
            session, lecture_video.id
        )
        assert loaded_lecture_video is not None
        intro_narration = loaded_lecture_video.questions[0].intro_narration
        assert intro_narration is not None
        narration_id = intro_narration.id

    first_claim = await lecture_video_processing._claim_next_narration_run(
        leased_by="test-runner-1"
    )
    assert first_claim is not None
    run_id, original_lease_token = first_claim

    async with db.async_session() as session:
        refreshed_run = await models.LectureVideoProcessingRun.get_by_id(
            session, run.id
        )
        assert refreshed_run is not None
        refreshed_run.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
        session.add(refreshed_run)
        await session.commit()

    second_claim = await lecture_video_processing._claim_next_narration_run(
        leased_by="test-runner-2"
    )
    assert second_claim is not None
    reclaimed_run_id, reclaimed_lease_token = second_claim
    assert reclaimed_run_id == run_id
    assert reclaimed_lease_token != original_lease_token

    await lecture_video_processing._mark_run_failed(
        run_id,
        original_lease_token,
        narration_id,
        "stale failure",
    )

    async with db.async_session() as session:
        refreshed_run = await models.LectureVideoProcessingRun.get_by_id(
            session, run.id
        )
        refreshed_lecture_video = await models.LectureVideo.get_by_id(
            session, lecture_video.id
        )
        refreshed_narration = await models.LectureVideoNarration.get_by_id(
            session, narration_id
        )

    assert refreshed_run is not None
    assert refreshed_run.status == schemas.LectureVideoProcessingRunStatus.RUNNING
    assert refreshed_run.lease_token == reclaimed_lease_token
    assert refreshed_lecture_video is not None
    assert refreshed_lecture_video.status == schemas.LectureVideoStatus.PROCESSING
    assert refreshed_lecture_video.error_message is None
    assert refreshed_narration is not None
    assert refreshed_narration.status == schemas.LectureVideoNarrationStatus.PENDING
    assert refreshed_narration.error_message is None


@with_institution(11, "Test Institution")
async def test_process_claimed_narration_run_renews_lease_during_synthesis(
    db, institution, config, monkeypatch, tmp_path
):
    narration_dir = tmp_path / "narration-audio"
    monkeypatch.setattr(
        config,
        "lecture_video_audio_store",
        LocalAudioStoreSettings(save_target=str(narration_dir)),
    )
    monkeypatch.setattr(
        lecture_video_processing,
        "RUN_LEASE_HEARTBEAT_INTERVAL",
        timedelta(milliseconds=10),
    )

    synthesis_started = asyncio.Event()
    release_synthesis = asyncio.Event()

    async def slow_synthesis(*_args, **_kwargs):
        synthesis_started.set()
        await release_synthesis.wait()
        return ("audio/ogg", b"fake-opus-audio")

    monkeypatch.setattr(
        lecture_video_processing,
        "synthesize_elevenlabs_speech",
        slow_synthesis,
    )

    async with db.async_session() as session:
        (
            _class_,
            lecture_video,
            _assistant,
            run,
        ) = await create_processing_lecture_video_assistant(session, institution)
        assert run is not None

    claim = await lecture_video_processing._claim_next_narration_run(
        leased_by="test-runner-1"
    )
    assert claim is not None
    run_id, lease_token = claim

    process_task = asyncio.create_task(
        lecture_video_processing._process_claimed_narration_run(run_id, lease_token)
    )
    try:
        await synthesis_started.wait()

        async with db.async_session() as session:
            refreshed_run = await models.LectureVideoProcessingRun.get_by_id(
                session, run.id
            )
            assert refreshed_run is not None
            refreshed_run.lease_expires_at = datetime.now(UTC) - timedelta(seconds=1)
            session.add(refreshed_run)
            await session.commit()

        for _ in range(20):
            await asyncio.sleep(0.01)
            async with db.async_session() as session:
                refreshed_run = await models.LectureVideoProcessingRun.get_by_id(
                    session, run.id
                )
            lease_expires_at = (
                refreshed_run.lease_expires_at if refreshed_run is not None else None
            )
            if lease_expires_at is not None and lease_expires_at.tzinfo is None:
                lease_expires_at = lease_expires_at.replace(tzinfo=UTC)
            if (
                refreshed_run is not None
                and refreshed_run.lease_token == lease_token
                and lease_expires_at is not None
                and lease_expires_at > datetime.now(UTC)
            ):
                break
        else:
            pytest.fail("Expected the in-flight synthesis to renew the run lease.")

        second_claim = await lecture_video_processing._claim_next_narration_run(
            leased_by="test-runner-2"
        )
        assert second_claim is None
    finally:
        release_synthesis.set()
        await asyncio.wait_for(process_task, timeout=1)

    async with db.async_session() as session:
        refreshed_run = await models.LectureVideoProcessingRun.get_by_id(
            session, run.id
        )
        refreshed_video = await models.LectureVideo.get_by_id(session, lecture_video.id)

    assert refreshed_run is not None
    assert refreshed_run.status == schemas.LectureVideoProcessingRunStatus.COMPLETED
    assert refreshed_video is not None
    assert refreshed_video.status == schemas.LectureVideoStatus.READY


@with_institution(11, "Test Institution")
async def test_prepare_next_work_item_returns_none_narration_id_when_voice_configuration_missing(
    db, institution
):
    async with db.async_session() as session:
        (
            _class_,
            lecture_video,
            _assistant,
            run,
        ) = await create_processing_lecture_video_assistant(session, institution)
        assert run is not None
        lecture_video.voice_id = None
        session.add(lecture_video)
        await session.commit()

    claim = await lecture_video_processing._claim_next_narration_run(
        leased_by="test-runner"
    )
    assert claim is not None
    run_id, lease_token = claim

    state, payload = await lecture_video_processing._prepare_next_work_item(
        run_id,
        lease_token,
    )

    assert state == "failed"
    assert payload == (None, "Lecture video voice configuration is missing.")


@with_institution(11, "Test Institution")
async def test_delete_lecture_video_cancels_processing_run_and_preserves_history(
    db, institution
):
    async with db.async_session() as session:
        (
            class_,
            lecture_video,
            assistant,
            run,
        ) = await create_processing_lecture_video_assistant(session, institution)
        assert run is not None
        assistant = await session.get(models.Assistant, assistant.id)
        assert assistant is not None
        assistant.lecture_video_id = None
        session.add(assistant)
        await session.flush()

        await lecture_video_service.delete_lecture_video(session, lecture_video.id)
        await session.commit()

    async with db.async_session() as session:
        deleted_video = await session.get(models.LectureVideo, lecture_video.id)
        refreshed_run = await models.LectureVideoProcessingRun.get_by_id(
            session, run.id
        )

    assert deleted_video is None
    assert refreshed_run is not None
    assert refreshed_run.lecture_video_id is None
    assert refreshed_run.lecture_video_id_snapshot == lecture_video.id
    assert refreshed_run.status == schemas.LectureVideoProcessingRunStatus.CANCELLED
    assert (
        refreshed_run.cancel_reason
        == schemas.LectureVideoProcessingCancelReason.LECTURE_VIDEO_DELETED
    )


def test_lecture_video_config_matches_logs_invalid_current_manifest(
    monkeypatch, caplog
):
    try:
        schemas.LectureVideoManifestV1.model_validate({"questions": []})
    except ValidationError as exc:
        validation_error = exc
    else:
        pytest.fail("Expected invalid manifest to raise ValidationError")

    def raise_validation_error(_lecture_video):  # type: ignore[no-untyped-def]
        raise validation_error

    current_lecture_video = make_lecture_video(1, "current.mp4")
    current_lecture_video.id = 123
    requested_lecture_video = make_lecture_video(1, "requested.mp4")
    requested_lecture_video.id = 456
    requested_manifest = schemas.LectureVideoManifestV1.model_validate(
        lecture_video_manifest()
    )

    monkeypatch.setattr(
        lecture_video_service,
        "lecture_video_manifest_from_model",
        raise_validation_error,
    )

    with caplog.at_level("WARNING"):
        matches = lecture_video_service.lecture_video_config_matches(
            current_lecture_video,
            requested_lecture_video,
            requested_manifest,
            DEFAULT_LECTURE_VIDEO_VOICE_ID,
        )

    assert matches is False
    assert (
        "Failed to serialize current lecture video manifest for comparison."
        in caplog.text
    )


@pytest.mark.parametrize(
    "manifest",
    [
        pytest.param(
            {
                **lecture_video_manifest(),
                "version": 2,
            },
            id="unexpected-version",
        ),
        pytest.param(
            {
                **lecture_video_manifest(),
                "questions": [
                    {
                        **lecture_video_manifest()["questions"][0],
                        "type": "essay",
                    }
                ],
            },
            id="unsupported-type",
        ),
        pytest.param(lecture_video_manifest(stop_offset_ms=-1), id="negative-stop"),
        pytest.param(
            {
                "version": 1,
                "questions": [
                    {
                        "type": "single_select",
                        "question_text": "Only one option?",
                        "intro_text": "Intro",
                        "stop_offset_ms": 1000,
                        "options": [
                            {
                                "option_text": "Only option",
                                "post_answer_text": "Nope",
                                "continue_offset_ms": 1500,
                                "correct": True,
                            }
                        ],
                    }
                ],
            },
            id="too-few-options",
        ),
        pytest.param(
            lecture_video_manifest(correct_flags=(True, True)),
            id="wrong-single-select-correct-count",
        ),
    ],
)
@with_user(123)
@with_institution(11, "Test Institution")
@with_authz(
    grants=[
        ("user:123", "admin", "class:1"),
        ("user:123", "can_create_assistants", "class:1"),
    ]
)
async def test_invalid_lecture_video_manifest_returns_422_and_preserves_uploaded_status(
    api, db, institution, valid_user_token, monkeypatch, manifest
):
    patch_lecture_video_model_list(monkeypatch)

    async with db.async_session() as session:
        class_ = models.Class(
            id=1,
            name="Lecture Class",
            institution_id=institution.id,
            api_key="sk-test",
        )
        lecture_video = make_lecture_video(
            class_.id,
            "invalid-manifest.mp4",
            filename="invalid-manifest.mp4",
            status=schemas.LectureVideoStatus.UPLOADED.value,
        )
        session.add(class_)
        session.add(lecture_video)
        await create_lecture_video_copy_credentials(session, class_.id)
        await session.commit()
        await session.refresh(lecture_video)

    response = api.post(
        "/api/v1/class/1/assistant",
        json={
            "name": "Lecture Assistant",
            "instructions": "Guide the learner through the lecture.",
            "description": "Lecture presentation assistant",
            "interaction_mode": "lecture_video",
            "model": "gpt-4o-mini",
            "tools": [],
            "lecture_video_id": lecture_video.id,
            "lecture_video_manifest": manifest,
            "voice_id": DEFAULT_LECTURE_VIDEO_VOICE_ID,
        },
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )

    assert response.status_code == 422
    assert "Invalid lecture video manifest" in response.json()["detail"][0]["msg"]

    async with db.async_session() as session:
        refreshed_video = await session.get(models.LectureVideo, lecture_video.id)
        question_count = await session.scalar(
            select(func.count())
            .select_from(models.LectureVideoQuestion)
            .where(models.LectureVideoQuestion.lecture_video_id == lecture_video.id)
        )

    assert refreshed_video is not None
    assert refreshed_video.status == schemas.LectureVideoStatus.UPLOADED.value
    assert question_count == 0


@with_user(123)
@with_institution(11, "Test Institution")
@with_authz(
    grants=[
        ("user:123", "admin", "class:1"),
        ("user:123", "can_create_assistants", "class:1"),
    ]
)
async def test_create_lecture_video_assistant_without_manifest_returns_422(
    api, db, institution, valid_user_token
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
            "missing-manifest.mp4",
            filename="missing-manifest.mp4",
            status=schemas.LectureVideoStatus.UPLOADED.value,
        )
        session.add(class_)
        session.add(lecture_video)
        await create_lecture_video_copy_credentials(session, class_.id)
        await session.commit()
        await session.refresh(lecture_video)

    response = api.post(
        "/api/v1/class/1/assistant",
        json={
            "name": "Lecture Assistant",
            "instructions": "Guide the learner through the lecture.",
            "description": "Lecture presentation assistant",
            "interaction_mode": "lecture_video",
            "model": "gpt-4o-mini",
            "tools": [],
            "lecture_video_id": lecture_video.id,
            "voice_id": DEFAULT_LECTURE_VIDEO_VOICE_ID,
        },
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )

    assert response.status_code == 422
    assert (
        "Specifying a lecture_video_manifest is required"
        in response.json()["detail"][0]["msg"]
    )


@with_user(123)
@with_institution(11, "Test Institution")
@with_authz(grants=[("user:123", "can_edit", "assistant:1")])
async def test_get_assistant_lecture_video_config_returns_manifest_and_voice_id(
    api, db, institution, valid_user_token
):
    async with db.async_session() as session:
        class_, _lecture_video, _assistant = await create_ready_lecture_video_assistant(
            session,
            institution,
            manifest=lecture_video_manifest(question_text="Config question?"),
        )

    response = api.get(
        f"/api/v1/class/{class_.id}/assistant/1/lecture-video/config",
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "lecture_video": {
            "id": 1,
            "filename": "lecture-runtime.mp4",
            "size": 128,
            "content_type": "video/mp4",
            "status": "ready",
            "error_message": None,
        },
        "lecture_video_manifest": lecture_video_manifest(
            question_text="Config question?"
        ),
        "voice_id": DEFAULT_LECTURE_VIDEO_VOICE_ID,
    }


@with_user(123)
@with_institution(11, "Test Institution")
@with_authz(grants=[("user:123", "can_edit", "assistant:1")])
async def test_get_assistant_lecture_video_config_returns_409_for_invalid_stored_manifest(
    api, db, institution, valid_user_token
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
            "invalid-manifest.mp4",
            filename="invalid-manifest.mp4",
            content_length=128,
        )
        lecture_video.id = 1
        session.add_all([class_, lecture_video])
        await session.flush()

        question = models.LectureVideoQuestion(
            lecture_video_id=lecture_video.id,
            position=0,
            question_type=schemas.LectureVideoQuestionType.SINGLE_SELECT,
            question_text="Broken question",
            intro_text="Broken intro",
            stop_offset_ms=1000,
        )
        session.add(question)
        await session.flush()
        session.add(
            models.LectureVideoQuestionOption(
                question_id=question.id,
                position=0,
                option_text="Only option",
                post_answer_text="Nope",
                continue_offset_ms=1500,
            )
        )

        assistant = models.Assistant(
            id=1,
            name="Lecture Assistant",
            class_id=class_.id,
            interaction_mode=schemas.InteractionMode.LECTURE_VIDEO,
            version=3,
            lecture_video_id=lecture_video.id,
            instructions="You are a lecture assistant.",
            model="gpt-4o-mini",
            tools="[]",
            use_latex=False,
            use_image_descriptions=False,
            hide_prompt=False,
        )
        session.add(assistant)
        await session.commit()

    response = api.get(
        "/api/v1/class/1/assistant/1/lecture-video/config",
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )

    assert response.status_code == 409
    assert response.json()["detail"] == "Stored lecture video manifest is invalid."


@with_user(123)
@with_institution(11, "Test Institution")
@with_authz(
    grants=[
        ("user:123", "admin", "class:1"),
        ("user:123", "can_create_assistants", "class:1"),
    ]
)
async def test_validate_class_lecture_video_voice_returns_audio_sample(
    api, db, institution, valid_user_token, monkeypatch
):
    async with db.async_session() as session:
        session.add(
            models.Class(
                id=1,
                name="Lecture Class",
                institution_id=institution.id,
                api_key="sk-test",
            )
        )
        await session.flush()
        await models.ClassCredential.create(
            session,
            1,
            schemas.ClassCredentialPurpose.LECTURE_VIDEO_NARRATION_TTS,
            "elevenlabs-key-1234",
            schemas.ClassCredentialProvider.ELEVENLABS,
        )
        await session.commit()

    monkeypatch.setattr(
        server_module,
        "synthesize_elevenlabs_voice_sample",
        AsyncMock(return_value=("Sample phrase", "audio/ogg", b"fake-audio")),
    )

    response = api.post(
        "/api/v1/class/1/lecture-video/voice/validate",
        json={"voice_id": "voice-123"},
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )

    assert response.status_code == 200
    assert response.content == b"fake-audio"
    assert response.headers["content-type"] == "audio/ogg"
    assert (
        response.headers[elevenlabs_module.ELEVENLABS_VOICE_SAMPLE_TEXT_HEADER]
        == "Sample phrase"
    )


@with_user(123)
@with_institution(11, "Test Institution")
@with_authz(grants=[("user:123", "can_create_assistants", "class:1")])
async def test_validate_class_lecture_video_voice_requires_admin(
    api, db, institution, valid_user_token, monkeypatch
):
    async with db.async_session() as session:
        session.add(
            models.Class(
                id=1,
                name="Lecture Class",
                institution_id=institution.id,
                api_key="sk-test",
            )
        )
        await session.flush()
        await models.ClassCredential.create(
            session,
            1,
            schemas.ClassCredentialPurpose.LECTURE_VIDEO_NARRATION_TTS,
            "elevenlabs-key-1234",
            schemas.ClassCredentialProvider.ELEVENLABS,
        )
        await session.commit()

    synthesize_mock = AsyncMock(
        return_value=("Sample phrase", "audio/ogg", b"fake-audio")
    )
    monkeypatch.setattr(
        server_module, "synthesize_elevenlabs_voice_sample", synthesize_mock
    )

    response = api.post(
        "/api/v1/class/1/lecture-video/voice/validate",
        json={"voice_id": "voice-123"},
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )

    assert response.status_code == 403
    synthesize_mock.assert_not_awaited()


@with_user(123)
@with_institution(11, "Test Institution")
@with_authz(
    grants=[
        ("user:123", "can_edit", "assistant:1"),
        ("user:123", "can_create_assistants", "class:1"),
    ]
)
async def test_validate_assistant_lecture_video_voice_returns_audio_sample(
    api, db, institution, valid_user_token, monkeypatch
):
    async with db.async_session() as session:
        class_, _lecture_video, _assistant = await create_ready_lecture_video_assistant(
            session,
            institution,
        )
        await models.ClassCredential.create(
            session,
            class_.id,
            schemas.ClassCredentialPurpose.LECTURE_VIDEO_NARRATION_TTS,
            "elevenlabs-key-1234",
            schemas.ClassCredentialProvider.ELEVENLABS,
        )
        await session.commit()

    monkeypatch.setattr(
        server_module,
        "synthesize_elevenlabs_voice_sample",
        AsyncMock(return_value=("Assistant phrase", "audio/ogg", b"assistant-audio")),
    )

    response = api.post(
        "/api/v1/class/1/assistant/1/lecture-video/voice/validate",
        json={"voice_id": "voice-123"},
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )

    assert response.status_code == 200
    assert response.content == b"assistant-audio"
    assert response.headers["content-type"] == "audio/ogg"
    assert (
        response.headers[elevenlabs_module.ELEVENLABS_VOICE_SAMPLE_TEXT_HEADER]
        == "Assistant phrase"
    )


@with_user(123)
@with_institution(11, "Test Institution")
@with_authz(
    grants=[
        ("user:123", "can_edit", "assistant:1"),
        ("user:123", "can_create_assistants", "class:1"),
    ]
)
async def test_validate_assistant_lecture_video_voice_rejects_invalid_voice_id(
    api, db, institution, valid_user_token, monkeypatch
):
    async with db.async_session() as session:
        class_, _lecture_video, _assistant = await create_ready_lecture_video_assistant(
            session,
            institution,
        )
        await models.ClassCredential.create(
            session,
            class_.id,
            schemas.ClassCredentialPurpose.LECTURE_VIDEO_NARRATION_TTS,
            "elevenlabs-key-1234",
            schemas.ClassCredentialProvider.ELEVENLABS,
        )
        await session.commit()

    monkeypatch.setattr(
        server_module,
        "synthesize_elevenlabs_voice_sample",
        AsyncMock(
            side_effect=class_credentials_module.ClassCredentialVoiceValidationError(
                "Invalid voice ID provided. Please choose a different voice."
            )
        ),
    )

    response = api.post(
        "/api/v1/class/1/assistant/1/lecture-video/voice/validate",
        json={"voice_id": "bad-voice"},
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )

    assert response.status_code == 400
    assert response.json() == {
        "detail": "Invalid voice ID provided. Please choose a different voice."
    }


@with_user(123)
@with_institution(11, "Test Institution")
@with_authz(
    grants=[
        ("user:123", "can_create_assistants", "class:1"),
        ("user:123", "admin", "class:1"),
    ]
)
async def test_create_lecture_video_assistant_rejects_invalid_voice_id(
    api, db, institution, valid_user_token, monkeypatch
):
    patch_lecture_video_model_list(monkeypatch)

    async with db.async_session() as session:
        class_ = models.Class(
            id=1,
            name="Lecture Class",
            institution_id=institution.id,
            api_key="sk-test",
        )
        lecture_video = make_lecture_video(
            class_.id,
            "invalid-create.mp4",
            filename="invalid-create.mp4",
            status=schemas.LectureVideoStatus.UPLOADED.value,
        )
        session.add_all([class_, lecture_video])
        await session.flush()
        await create_lecture_video_copy_credentials(session, class_.id)
        await session.commit()
        await session.refresh(lecture_video)

    monkeypatch.setattr(
        server_module,
        "synthesize_elevenlabs_voice_sample",
        AsyncMock(
            side_effect=class_credentials_module.ClassCredentialVoiceValidationError(
                "Invalid voice ID provided. Please choose a different voice."
            )
        ),
    )

    response = api.post(
        "/api/v1/class/1/assistant",
        json={
            "name": "Lecture Assistant",
            "instructions": "Guide the learner through the lecture.",
            "description": "Lecture presentation assistant",
            "interaction_mode": "lecture_video",
            "model": "gpt-4o-mini",
            "tools": [],
            "lecture_video_id": lecture_video.id,
            "lecture_video_manifest": lecture_video_manifest(),
            "voice_id": "bad-voice",
        },
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )

    assert response.status_code == 400
    assert response.json() == {
        "detail": "Invalid voice ID provided. Please choose a different voice."
    }

    async with db.async_session() as session:
        assistant_count = await session.scalar(
            select(func.count()).select_from(models.Assistant)
        )
        refreshed_video = await session.get(models.LectureVideo, lecture_video.id)

    assert assistant_count == 0
    assert refreshed_video is not None
    assert refreshed_video.voice_id is None


@with_user(123)
@with_institution(11, "Test Institution")
@with_authz(
    grants=[
        ("user:123", "can_create_assistants", "class:1"),
        ("user:123", "can_edit", "assistant:1"),
        ("user:123", "admin", "class:1"),
    ]
)
async def test_update_assistant_with_new_lecture_video_id_deletes_prior_video_when_unused(
    api, db, institution, valid_user_token, monkeypatch
):
    patch_lecture_video_model_list(monkeypatch)

    async with db.async_session() as session:
        class_ = models.Class(
            id=1,
            name="Lecture Class",
            institution_id=institution.id,
            api_key="sk-test",
        )
        first_video = make_lecture_video(
            class_.id,
            "first-lecture.mp4",
            filename="first-lecture.mp4",
            status=schemas.LectureVideoStatus.UPLOADED.value,
        )
        second_video = make_lecture_video(
            class_.id,
            "second-lecture.mp4",
            filename="second-lecture.mp4",
            status=schemas.LectureVideoStatus.UPLOADED.value,
        )
        session.add(class_)
        session.add(first_video)
        session.add(second_video)
        await create_lecture_video_copy_credentials(session, class_.id)
        await session.commit()
        await session.refresh(first_video)
        await session.refresh(second_video)

    create_response = api.post(
        "/api/v1/class/1/assistant",
        json={
            "name": "Lecture Assistant",
            "instructions": "Guide the learner through the lecture.",
            "description": "Lecture presentation assistant",
            "interaction_mode": "lecture_video",
            "model": "gpt-4o-mini",
            "tools": [],
            "lecture_video_id": first_video.id,
            "lecture_video_manifest": lecture_video_manifest(
                question_text="First question?"
            ),
            "voice_id": DEFAULT_LECTURE_VIDEO_VOICE_ID,
        },
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )
    assert create_response.status_code == 200

    update_response = api.put(
        "/api/v1/class/1/assistant/1",
        json={
            "lecture_video_id": second_video.id,
            "lecture_video_manifest": lecture_video_manifest(
                question_text="Second question?"
            ),
            "voice_id": DEFAULT_LECTURE_VIDEO_VOICE_ID,
        },
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )
    assert update_response.status_code == 200
    assert update_response.json()["lecture_video"]["id"] == second_video.id

    async with db.async_session() as session:
        assistant = await session.get(models.Assistant, 1)
        first_video_row = await session.get(models.LectureVideo, first_video.id)
        second_question = await session.scalar(
            select(models.LectureVideoQuestion.question_text).where(
                models.LectureVideoQuestion.lecture_video_id == second_video.id
            )
        )

    assert assistant is not None
    assert assistant.lecture_video_id == second_video.id
    assert first_video_row is None
    assert second_question == "Second question?"


@with_user(123)
@with_institution(11, "Test Institution")
@with_authz(
    grants=[
        ("user:123", "can_create_assistants", "class:1"),
        ("user:123", "can_edit", "assistant:1"),
        ("user:123", "admin", "class:1"),
    ]
)
async def test_update_assistant_with_new_lecture_video_id_ignores_cleanup_delete_failures(
    api, db, institution, valid_user_token, monkeypatch, config, tmp_path
):
    patch_lecture_video_model_list(monkeypatch)
    monkeypatch.setattr(
        config,
        "video_store",
        LocalVideoStoreSettings(type="local", save_target=str(tmp_path)),
    )

    async with db.async_session() as session:
        class_ = models.Class(
            id=1,
            name="Lecture Class",
            institution_id=institution.id,
            api_key="sk-test",
        )
        first_video = make_lecture_video(
            class_.id,
            "cleanup-fail-first.mp4",
            filename="cleanup-fail-first.mp4",
            status=schemas.LectureVideoStatus.UPLOADED.value,
        )
        second_video = make_lecture_video(
            class_.id,
            "cleanup-fail-second.mp4",
            filename="cleanup-fail-second.mp4",
            status=schemas.LectureVideoStatus.UPLOADED.value,
        )
        session.add_all([class_, first_video, second_video])
        await create_lecture_video_copy_credentials(session, class_.id)
        await session.commit()
        await session.refresh(first_video)
        await session.refresh(second_video)

    async def fail_delete(key: str) -> None:
        raise RuntimeError(f"transient delete failure for {key}")

    monkeypatch.setattr(config.video_store.store, "delete", fail_delete)

    create_response = api.post(
        "/api/v1/class/1/assistant",
        json={
            "name": "Lecture Assistant",
            "instructions": "Guide the learner through the lecture.",
            "description": "Lecture presentation assistant",
            "interaction_mode": "lecture_video",
            "model": "gpt-4o-mini",
            "tools": [],
            "lecture_video_id": first_video.id,
            "lecture_video_manifest": lecture_video_manifest(
                question_text="First question?"
            ),
            "voice_id": DEFAULT_LECTURE_VIDEO_VOICE_ID,
        },
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )
    assert create_response.status_code == 200

    update_response = api.put(
        "/api/v1/class/1/assistant/1",
        json={
            "lecture_video_id": second_video.id,
            "lecture_video_manifest": lecture_video_manifest(
                question_text="Second question?"
            ),
            "voice_id": DEFAULT_LECTURE_VIDEO_VOICE_ID,
        },
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )

    assert update_response.status_code == 200
    assert update_response.json()["lecture_video"]["id"] == second_video.id

    async with db.async_session() as session:
        assistant = await session.get(models.Assistant, 1)
        first_video_row = await session.get(models.LectureVideo, first_video.id)
        second_question = await session.scalar(
            select(models.LectureVideoQuestion.question_text).where(
                models.LectureVideoQuestion.lecture_video_id == second_video.id
            )
        )

    assert assistant is not None
    assert assistant.lecture_video_id == second_video.id
    assert first_video_row is None
    assert second_question == "Second question?"


@with_user(123)
@with_institution(11, "Test Institution")
@with_authz(
    grants=[
        ("user:123", "can_create_assistants", "class:1"),
        ("user:123", "can_edit", "assistant:1"),
        ("user:123", "admin", "class:1"),
    ]
)
async def test_update_assistant_with_new_lecture_video_id_without_manifest_returns_422(
    api, db, institution, valid_user_token, monkeypatch
):
    patch_lecture_video_model_list(monkeypatch)

    async with db.async_session() as session:
        class_ = models.Class(
            id=1,
            name="Lecture Class",
            institution_id=institution.id,
            api_key="sk-test",
        )
        first_video = make_lecture_video(
            class_.id,
            "first-lecture.mp4",
            filename="first-lecture.mp4",
            status=schemas.LectureVideoStatus.UPLOADED.value,
        )
        second_video = make_lecture_video(
            class_.id,
            "second-lecture.mp4",
            filename="second-lecture.mp4",
            status=schemas.LectureVideoStatus.UPLOADED.value,
        )
        session.add(class_)
        session.add(first_video)
        session.add(second_video)
        await create_lecture_video_copy_credentials(session, class_.id)
        await session.commit()
        await session.refresh(first_video)
        await session.refresh(second_video)

    create_response = api.post(
        "/api/v1/class/1/assistant",
        json={
            "name": "Lecture Assistant",
            "instructions": "Guide the learner through the lecture.",
            "description": "Lecture presentation assistant",
            "interaction_mode": "lecture_video",
            "model": "gpt-4o-mini",
            "tools": [],
            "lecture_video_id": first_video.id,
            "lecture_video_manifest": lecture_video_manifest(
                question_text="First question?"
            ),
            "voice_id": DEFAULT_LECTURE_VIDEO_VOICE_ID,
        },
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )
    assert create_response.status_code == 200

    response = api.put(
        "/api/v1/class/1/assistant/1",
        json={
            "lecture_video_id": second_video.id,
            "voice_id": DEFAULT_LECTURE_VIDEO_VOICE_ID,
        },
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )

    assert response.status_code == 422
    assert (
        "Specifying a lecture_video_manifest is required"
        in response.json()["detail"][0]["msg"]
    )


@with_user(123)
@with_institution(11, "Test Institution")
@with_authz(grants=[("user:123", "can_edit", "assistant:1")])
async def test_update_assistant_with_whitespace_voice_id_returns_422(
    api, db, institution, valid_user_token
):
    async with db.async_session() as session:
        class_, lecture_video, _assistant = await create_ready_lecture_video_assistant(
            session,
            institution,
        )

    response = api.put(
        f"/api/v1/class/{class_.id}/assistant/1",
        json={
            "lecture_video_id": lecture_video.id,
            "lecture_video_manifest": lecture_video_manifest(
                question_text="Updated question?"
            ),
            "voice_id": "   ",
        },
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )

    assert response.status_code == 422
    assert (
        "Specifying a voice_id is required when updating lecture video data."
        in response.json()["detail"][0]["msg"]
    )


@with_user(123)
@with_institution(11, "Test Institution")
@with_authz(
    grants=[
        ("user:123", "can_edit", "assistant:1"),
        ("user:123", "can_create_assistants", "class:1"),
        ("user:123", "admin", "class:1"),
    ]
)
async def test_update_assistant_rejects_invalid_voice_id(
    api, db, institution, valid_user_token, monkeypatch
):
    async with db.async_session() as session:
        class_, lecture_video, _assistant = await create_ready_lecture_video_assistant(
            session,
            institution,
        )
        await create_lecture_video_copy_credentials(session, class_.id)
        await session.commit()

    monkeypatch.setattr(
        server_module,
        "synthesize_elevenlabs_voice_sample",
        AsyncMock(
            side_effect=class_credentials_module.ClassCredentialVoiceValidationError(
                "Invalid voice ID provided. Please choose a different voice."
            )
        ),
    )

    response = api.put(
        f"/api/v1/class/{class_.id}/assistant/1",
        json={
            "lecture_video_id": lecture_video.id,
            "lecture_video_manifest": lecture_video_manifest(
                question_text="Updated question?"
            ),
            "voice_id": "bad-voice",
        },
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )

    assert response.status_code == 400
    assert response.json() == {
        "detail": "Invalid voice ID provided. Please choose a different voice."
    }

    async with db.async_session() as session:
        assistant = await session.get(models.Assistant, 1)
        refreshed_video = await session.get(models.LectureVideo, lecture_video.id)
        question = await session.scalar(
            select(models.LectureVideoQuestion.question_text).where(
                models.LectureVideoQuestion.lecture_video_id == lecture_video.id
            )
        )

    assert assistant is not None
    assert refreshed_video is not None
    assert assistant.lecture_video_id == lecture_video.id
    assert refreshed_video.voice_id == DEFAULT_LECTURE_VIDEO_VOICE_ID
    assert question == "What is the right answer?"


@with_user(123)
@with_institution(11, "Test Institution")
@with_authz(
    grants=[
        ("user:123", "can_create_assistants", "class:1"),
        ("user:123", "can_edit", "assistant:1"),
        ("user:123", "admin", "class:1"),
    ]
)
async def test_update_assistant_with_new_lecture_video_id_preserves_prior_video_when_thread_uses_it(
    api, db, institution, valid_user_token, monkeypatch
):
    patch_lecture_video_model_list(monkeypatch)

    async with db.async_session() as session:
        class_ = models.Class(
            id=1,
            name="Lecture Class",
            institution_id=institution.id,
            api_key="sk-test",
        )
        first_video = make_lecture_video(
            class_.id,
            "first-threaded.mp4",
            filename="first-threaded.mp4",
            status=schemas.LectureVideoStatus.UPLOADED.value,
        )
        second_video = make_lecture_video(
            class_.id,
            "second-threaded.mp4",
            filename="second-threaded.mp4",
            status=schemas.LectureVideoStatus.UPLOADED.value,
        )
        session.add(class_)
        session.add(first_video)
        session.add(second_video)
        await create_lecture_video_copy_credentials(session, class_.id)
        await session.commit()
        await session.refresh(first_video)
        await session.refresh(second_video)

    create_response = api.post(
        "/api/v1/class/1/assistant",
        json={
            "name": "Lecture Assistant",
            "instructions": "Guide the learner through the lecture.",
            "description": "Lecture presentation assistant",
            "interaction_mode": "lecture_video",
            "model": "gpt-4o-mini",
            "tools": [],
            "lecture_video_id": first_video.id,
            "lecture_video_manifest": lecture_video_manifest(
                question_text="First question?"
            ),
            "voice_id": DEFAULT_LECTURE_VIDEO_VOICE_ID,
        },
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )
    assert create_response.status_code == 200

    async with db.async_session() as session:
        session.add(
            models.Thread(
                id=1,
                name="Lecture Thread",
                version=3,
                thread_id="thread-preserve-old-video",
                class_id=1,
                assistant_id=1,
                interaction_mode=schemas.InteractionMode.LECTURE_VIDEO,
                lecture_video_id=first_video.id,
                private=True,
                tools_available="[]",
            )
        )
        await session.commit()

    update_response = api.put(
        "/api/v1/class/1/assistant/1",
        json={
            "lecture_video_id": second_video.id,
            "lecture_video_manifest": lecture_video_manifest(
                question_text="Second question?"
            ),
            "voice_id": DEFAULT_LECTURE_VIDEO_VOICE_ID,
        },
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )
    assert update_response.status_code == 200
    assert update_response.json()["lecture_video"]["id"] == second_video.id

    async with db.async_session() as session:
        assistant = await session.get(models.Assistant, 1)
        first_video_row = await session.get(models.LectureVideo, first_video.id)
        first_question = await session.scalar(
            select(models.LectureVideoQuestion.question_text).where(
                models.LectureVideoQuestion.lecture_video_id == first_video.id
            )
        )
        second_question = await session.scalar(
            select(models.LectureVideoQuestion.question_text).where(
                models.LectureVideoQuestion.lecture_video_id == second_video.id
            )
        )

    assert assistant is not None
    assert assistant.lecture_video_id == second_video.id
    assert first_video_row is not None
    assert first_question == "First question?"
    assert second_question == "Second question?"


@with_user(123)
@with_institution(11, "Test Institution")
@with_authz(
    grants=[
        ("user:123", "can_create_assistants", "class:1"),
        ("user:123", "can_edit", "assistant:1"),
        ("user:123", "admin", "class:1"),
    ]
)
async def test_update_assistant_with_same_lecture_video_id_clones_snapshot_and_preserves_thread_history(
    api, db, institution, valid_user_token, monkeypatch
):
    patch_lecture_video_model_list(monkeypatch)

    async with db.async_session() as session:
        class_ = models.Class(
            id=1,
            name="Lecture Class",
            institution_id=institution.id,
            api_key="sk-test",
        )
        lecture_video = make_lecture_video(
            class_.id,
            "same-video.mp4",
            filename="same-video.mp4",
            status=schemas.LectureVideoStatus.UPLOADED.value,
        )
        session.add_all([class_, lecture_video])
        await create_lecture_video_copy_credentials(session, class_.id)
        await session.commit()
        await session.refresh(lecture_video)

    create_response = api.post(
        "/api/v1/class/1/assistant",
        json={
            "name": "Lecture Assistant",
            "instructions": "Guide the learner through the lecture.",
            "description": "Lecture presentation assistant",
            "interaction_mode": "lecture_video",
            "model": "gpt-4o-mini",
            "tools": [],
            "lecture_video_id": lecture_video.id,
            "lecture_video_manifest": lecture_video_manifest(
                question_text="Original question?"
            ),
            "voice_id": DEFAULT_LECTURE_VIDEO_VOICE_ID,
        },
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )
    assert create_response.status_code == 200

    async with db.async_session() as session:
        session.add(
            models.Thread(
                id=1,
                name="Lecture Thread",
                version=3,
                thread_id="thread-preserve-same-video",
                class_id=1,
                assistant_id=1,
                interaction_mode=schemas.InteractionMode.LECTURE_VIDEO,
                lecture_video_id=lecture_video.id,
                private=True,
                tools_available="[]",
            )
        )
        await session.commit()

    update_response = api.put(
        "/api/v1/class/1/assistant/1",
        json={
            "lecture_video_id": lecture_video.id,
            "lecture_video_manifest": lecture_video_manifest(
                question_text="Updated question?"
            ),
            "voice_id": "voice-updated",
        },
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )
    assert update_response.status_code == 200
    assert update_response.json()["lecture_video"]["id"] != lecture_video.id

    async with db.async_session() as session:
        assistant = await session.get(models.Assistant, 1)
        original_video = await session.get(models.LectureVideo, lecture_video.id)
        updated_video = await session.get(
            models.LectureVideo, assistant.lecture_video_id
        )
        processing_runs = list(
            (
                await session.scalars(
                    select(models.LectureVideoProcessingRun).order_by(
                        models.LectureVideoProcessingRun.id.asc()
                    )
                )
            ).all()
        )
        original_question = await session.scalar(
            select(models.LectureVideoQuestion.question_text).where(
                models.LectureVideoQuestion.lecture_video_id == lecture_video.id
            )
        )
        updated_question = await session.scalar(
            select(models.LectureVideoQuestion.question_text).where(
                models.LectureVideoQuestion.lecture_video_id == updated_video.id
            )
        )

    assert assistant is not None
    assert original_video is not None
    assert updated_video is not None
    assert updated_video.id != original_video.id
    assert updated_video.stored_object_id == original_video.stored_object_id
    assert updated_video.source_lecture_video_id_snapshot == original_video.id
    assert original_video.source_lecture_video_id_snapshot is None
    assert updated_video.voice_id == "voice-updated"
    assert original_video.voice_id == DEFAULT_LECTURE_VIDEO_VOICE_ID
    assert original_question == "Original question?"
    assert updated_question == "Updated question?"
    assert len(processing_runs) == 2
    assert processing_runs[0].lecture_video_id_snapshot == original_video.id
    assert (
        processing_runs[0].status == schemas.LectureVideoProcessingRunStatus.CANCELLED
    )
    assert processing_runs[1].lecture_video_id_snapshot == updated_video.id
    assert processing_runs[1].status == schemas.LectureVideoProcessingRunStatus.QUEUED


@with_user(123)
@with_institution(11, "Test Institution")
@with_authz(
    grants=[
        ("user:123", "can_create_assistants", "class:1"),
        ("user:123", "can_edit", "assistant:1"),
        ("user:123", "admin", "class:1"),
    ]
)
async def test_update_assistant_with_same_lecture_video_config_is_a_no_op(
    api, db, institution, valid_user_token, monkeypatch
):
    patch_lecture_video_model_list(monkeypatch)

    async with db.async_session() as session:
        class_ = models.Class(
            id=1,
            name="Lecture Class",
            institution_id=institution.id,
            api_key="sk-test",
        )
        lecture_video = make_lecture_video(
            class_.id,
            "no-op-video.mp4",
            filename="no-op-video.mp4",
            status=schemas.LectureVideoStatus.UPLOADED.value,
        )
        session.add_all([class_, lecture_video])
        await create_lecture_video_copy_credentials(session, class_.id)
        await session.commit()
        await session.refresh(lecture_video)

    create_response = api.post(
        "/api/v1/class/1/assistant",
        json={
            "name": "Lecture Assistant",
            "instructions": "Guide the learner through the lecture.",
            "description": "Lecture presentation assistant",
            "interaction_mode": "lecture_video",
            "model": "gpt-4o-mini",
            "tools": [],
            "lecture_video_id": lecture_video.id,
            "lecture_video_manifest": lecture_video_manifest(
                question_text="No-op question?"
            ),
            "voice_id": DEFAULT_LECTURE_VIDEO_VOICE_ID,
        },
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )
    assert create_response.status_code == 200

    update_response = api.put(
        "/api/v1/class/1/assistant/1",
        json={
            "voice_id": f"  {DEFAULT_LECTURE_VIDEO_VOICE_ID}  ",
            "lecture_video_id": lecture_video.id,
            "lecture_video_manifest": {
                "questions": [
                    {
                        "options": [
                            {
                                "continue_offset_ms": 1500,
                                "correct": True,
                                "post_answer_text": "Correct answer",
                                "option_text": "Option A",
                            },
                            {
                                "correct": False,
                                "option_text": "Option B",
                                "continue_offset_ms": 2000,
                                "post_answer_text": "Try again",
                            },
                        ],
                        "stop_offset_ms": 1000,
                        "intro_text": "Intro narration",
                        "question_text": "No-op question?",
                        "type": "single_select",
                    }
                ]
            },
        },
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )
    assert update_response.status_code == 200
    assert update_response.json()["lecture_video"]["id"] == lecture_video.id

    async with db.async_session() as session:
        assistant = await session.get(models.Assistant, 1)
        lecture_video_count = await session.scalar(
            select(func.count()).select_from(models.LectureVideo)
        )
        refreshed_video = await session.get(models.LectureVideo, lecture_video.id)
        question = await session.scalar(
            select(models.LectureVideoQuestion.question_text).where(
                models.LectureVideoQuestion.lecture_video_id == lecture_video.id
            )
        )

    assert assistant is not None
    assert assistant.lecture_video_id == lecture_video.id
    assert lecture_video_count == 1
    assert refreshed_video is not None
    assert refreshed_video.voice_id == DEFAULT_LECTURE_VIDEO_VOICE_ID
    assert question == "No-op question?"


@with_user(123)
@with_institution(11, "Test Institution")
@with_authz(grants=[("user:123", "can_delete", "assistant:1")])
async def test_delete_assistant_deletes_attached_lecture_video_when_unused(
    api, db, institution, valid_user_token, config, monkeypatch
):
    monkeypatch.setattr(config, "video_store", None)

    async with db.async_session() as session:
        class_, lecture_video, _assistant = await create_ready_lecture_video_assistant(
            session,
            institution,
        )

    async def fake_get_openai_client_for_class() -> SimpleNamespace:
        return SimpleNamespace(
            beta=SimpleNamespace(
                assistants=SimpleNamespace(delete=AsyncMock(return_value=None))
            )
        )

    api.app.dependency_overrides[server_module.get_openai_client_for_class] = (
        fake_get_openai_client_for_class
    )
    try:
        response = api.delete(
            f"/api/v1/class/{class_.id}/assistant/1",
            headers={"Authorization": f"Bearer {valid_user_token}"},
        )
    finally:
        api.app.dependency_overrides.pop(
            server_module.get_openai_client_for_class, None
        )

    assert response.status_code == 200

    async with db.async_session() as session:
        assert await session.get(models.Assistant, 1) is None
        assert await session.get(models.LectureVideo, lecture_video.id) is None


@with_user(123)
@with_institution(11, "Test Institution")
@with_authz(grants=[("user:123", "can_delete", "assistant:1")])
async def test_delete_assistant_preserves_attached_lecture_video_when_thread_uses_it(
    api, db, institution, valid_user_token, config, monkeypatch
):
    monkeypatch.setattr(config, "video_store", None)

    async with db.async_session() as session:
        class_, lecture_video, _assistant = await create_ready_lecture_video_assistant(
            session,
            institution,
        )
        session.add(
            models.Thread(
                id=1,
                name="Lecture Thread",
                version=3,
                thread_id="thread-keep-video-on-delete",
                class_id=class_.id,
                assistant_id=1,
                interaction_mode=schemas.InteractionMode.LECTURE_VIDEO,
                lecture_video_id=lecture_video.id,
                private=True,
                tools_available="[]",
            )
        )
        await session.commit()

    async def fake_get_openai_client_for_class() -> SimpleNamespace:
        return SimpleNamespace(
            beta=SimpleNamespace(
                assistants=SimpleNamespace(delete=AsyncMock(return_value=None))
            )
        )

    api.app.dependency_overrides[server_module.get_openai_client_for_class] = (
        fake_get_openai_client_for_class
    )
    try:
        response = api.delete(
            f"/api/v1/class/{class_.id}/assistant/1",
            headers={"Authorization": f"Bearer {valid_user_token}"},
        )
    finally:
        api.app.dependency_overrides.pop(
            server_module.get_openai_client_for_class, None
        )

    assert response.status_code == 200

    async with db.async_session() as session:
        assert await session.get(models.Assistant, 1) is None
        assert await session.get(models.LectureVideo, lecture_video.id) is not None


@with_user(123)
@with_institution(11, "Test Institution")
@with_authz(
    grants=[
        ("user:123", "admin", "class:1"),
        ("user:123", "can_create_assistants", "class:1"),
        ("user:123", "can_edit", "assistant:2"),
    ]
)
async def test_update_lecture_video_assistant_rejects_assigned_lecture_video(
    api, db, institution, valid_user_token, monkeypatch
):
    patch_lecture_video_model_list(monkeypatch)

    async with db.async_session() as session:
        class_ = models.Class(
            id=1,
            name="Lecture Class",
            institution_id=institution.id,
            api_key="sk-test",
        )
        first_video = make_lecture_video(
            class_.id,
            "first-owned.mp4",
            filename="first-owned.mp4",
            status=schemas.LectureVideoStatus.READY.value,
        )
        second_video = make_lecture_video(
            class_.id,
            "second-owned.mp4",
            filename="second-owned.mp4",
            status=schemas.LectureVideoStatus.READY.value,
        )
        session.add(class_)
        session.add(first_video)
        session.add(second_video)
        await session.flush()
        session.add(
            models.Assistant(
                id=1,
                name="Existing Lecture Assistant",
                class_id=class_.id,
                creator_id=123,
                interaction_mode=schemas.InteractionMode.LECTURE_VIDEO,
                version=3,
                model="gpt-4o-mini",
                lecture_video_id=first_video.id,
                instructions="Existing lecture assistant.",
                tools="[]",
            )
        )
        session.add(
            models.Assistant(
                id=2,
                name="Second Lecture Assistant",
                class_id=class_.id,
                creator_id=123,
                interaction_mode=schemas.InteractionMode.LECTURE_VIDEO,
                version=3,
                model="gpt-4o-mini",
                lecture_video_id=second_video.id,
                instructions="Second lecture assistant.",
                tools="[]",
            )
        )
        await session.commit()

    response = api.put(
        "/api/v1/class/1/assistant/2",
        json={
            "lecture_video_id": first_video.id,
            "lecture_video_manifest": lecture_video_manifest(),
            "voice_id": DEFAULT_LECTURE_VIDEO_VOICE_ID,
        },
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )

    assert response.status_code == 400
    assert "already attached to another assistant" in response.json()["detail"]


@with_user(123)
@with_institution(11, "Test Institution")
@with_authz(
    grants=[
        ("user:123", "admin", "class:1"),
        ("user:123", "can_create_assistants", "class:1"),
        ("user:123", "can_edit", "assistant:1"),
    ]
)
async def test_retry_lecture_video_endpoint_resets_non_ready_narrations_and_queues_new_attempt(
    api, db, institution, valid_user_token, config, monkeypatch, tmp_path
):
    narration_dir = tmp_path / "retry-narrations"
    monkeypatch.setattr(
        config,
        "lecture_video_audio_store",
        LocalAudioStoreSettings(save_target=str(narration_dir)),
    )

    async with db.async_session() as session:
        class_, lecture_video, assistant = await create_ready_lecture_video_assistant(
            session,
            institution,
        )
        lecture_video = await models.LectureVideo.get_by_id_with_copy_context(
            session, lecture_video.id
        )
        assert lecture_video is not None
        ready_narration = lecture_video.questions[0].intro_narration
        failed_narration = lecture_video.questions[0].options[0].post_narration
        other_ready = lecture_video.questions[0].options[1].post_narration
        assert ready_narration is not None
        assert failed_narration is not None
        assert other_ready is not None
        assert ready_narration.stored_object is not None
        assert failed_narration.stored_object is not None
        assert other_ready.stored_object is not None
        (narration_dir / ready_narration.stored_object.key).parent.mkdir(
            parents=True, exist_ok=True
        )
        (narration_dir / ready_narration.stored_object.key).write_bytes(b"ready-audio")
        (narration_dir / failed_narration.stored_object.key).write_bytes(
            b"failed-audio"
        )

        preserved_ready_stored_object_id = ready_narration.stored_object.id
        preserved_other_ready_stored_object_id = other_ready.stored_object.id
        failed_audio_key = failed_narration.stored_object.key

        failed_narration.status = schemas.LectureVideoNarrationStatus.FAILED
        failed_narration.error_message = "Server Error from ElevenLabs"
        lecture_video.status = schemas.LectureVideoStatus.FAILED
        lecture_video.error_message = "Server Error from ElevenLabs"
        session.add(failed_narration)
        session.add(lecture_video)
        await models.LectureVideoProcessingRun.create(
            session,
            lecture_video_id=lecture_video.id,
            lecture_video_id_snapshot=lecture_video.id,
            class_id=class_.id,
            assistant_id_at_start=assistant.id,
            stage=schemas.LectureVideoProcessingStage.NARRATION,
            attempt_number=1,
            status=schemas.LectureVideoProcessingRunStatus.FAILED,
        )
        await session.commit()

    response = api.post(
        "/api/v1/class/1/assistant/1/lecture-video/retry",
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == schemas.LectureVideoStatus.PROCESSING.value
    assert response.json()["error_message"] is None

    async with db.async_session() as session:
        refreshed_video = await models.LectureVideo.get_by_id_with_copy_context(
            session, lecture_video.id
        )
        refreshed_runs = list(
            (
                await session.scalars(
                    select(models.LectureVideoProcessingRun)
                    .where(
                        models.LectureVideoProcessingRun.lecture_video_id_snapshot
                        == lecture_video.id
                    )
                    .order_by(models.LectureVideoProcessingRun.attempt_number.asc())
                )
            ).all()
        )

    assert refreshed_video is not None
    assert refreshed_video.status == schemas.LectureVideoStatus.PROCESSING
    assert refreshed_video.error_message is None
    assert refreshed_video.questions[0].intro_narration is not None
    assert refreshed_video.questions[0].intro_narration.status == (
        schemas.LectureVideoNarrationStatus.READY
    )
    assert (
        refreshed_video.questions[0].intro_narration.stored_object_id
        == preserved_ready_stored_object_id
    )
    assert refreshed_video.questions[0].options[1].post_narration is not None
    assert (
        refreshed_video.questions[0].options[1].post_narration.stored_object_id
        == preserved_other_ready_stored_object_id
    )
    assert refreshed_video.questions[0].options[0].post_narration is not None
    assert refreshed_video.questions[0].options[0].post_narration.status == (
        schemas.LectureVideoNarrationStatus.PENDING
    )
    assert (
        refreshed_video.questions[0].options[0].post_narration.stored_object_id is None
    )
    assert refreshed_runs[0].status == schemas.LectureVideoProcessingRunStatus.FAILED
    assert refreshed_runs[1].status == schemas.LectureVideoProcessingRunStatus.QUEUED
    assert refreshed_runs[1].attempt_number == 2
    assert not (narration_dir / failed_audio_key).exists()


@with_institution(11, "Test Institution")
async def test_queue_narration_processing_run_retries_integrity_error_with_new_attempt_number(
    db, institution, monkeypatch
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
            "retry-attempt.webm",
            filename="retry-attempt.webm",
            status=schemas.LectureVideoStatus.PROCESSING.value,
        )
        assistant = models.Assistant(
            id=1,
            name="Lecture Assistant",
            class_id=class_.id,
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

        original_create = models.LectureVideoProcessingRun.create
        create_attempt_numbers: list[int] = []
        latest_attempt_numbers = iter([1, 2])

        async def fake_get_latest_attempt_number(
            session_, lecture_video_id_snapshot, stage
        ):
            assert session_ is session
            assert lecture_video_id_snapshot == lecture_video.id
            assert stage == schemas.LectureVideoProcessingStage.NARRATION
            return next(latest_attempt_numbers)

        async def fake_create(session_, **kwargs):
            assert session_ is session
            create_attempt_numbers.append(kwargs["attempt_number"])
            if len(create_attempt_numbers) == 1:
                raise IntegrityError(
                    "INSERT INTO lecture_video_processing_runs (...) VALUES (...)",
                    {},
                    Exception(
                        "UNIQUE constraint failed: "
                        "lecture_video_processing_runs.lecture_video_id_snapshot, "
                        "lecture_video_processing_runs.stage, "
                        "lecture_video_processing_runs.attempt_number"
                    ),
                )
            return await original_create(session_, **kwargs)

        monkeypatch.setattr(
            models.LectureVideoProcessingRun,
            "get_latest_attempt_number",
            fake_get_latest_attempt_number,
        )
        monkeypatch.setattr(models.LectureVideoProcessingRun, "create", fake_create)

        run = await lecture_video_processing.queue_narration_processing_run(
            session,
            lecture_video,
            assistant_id_at_start=assistant.id,
        )
        await session.commit()

    assert create_attempt_numbers == [2, 3]
    assert run.attempt_number == 3

    async with db.async_session() as session:
        persisted_assistant = await models.Assistant.get_by_id(session, assistant.id)
        persisted_run = await models.LectureVideoProcessingRun.get_by_id(
            session, run.id
        )

    assert persisted_assistant is not None
    assert persisted_run is not None
    assert persisted_run.attempt_number == 3


@with_institution(11, "Test Institution")
async def test_queue_narration_processing_run_returns_existing_run_after_concurrent_queue_conflict(
    db, institution, monkeypatch
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
            "retry-existing-run.webm",
            filename="retry-existing-run.webm",
            status=schemas.LectureVideoStatus.PROCESSING.value,
        )
        assistant = models.Assistant(
            id=1,
            name="Lecture Assistant",
            class_id=class_.id,
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

        existing_run = models.LectureVideoProcessingRun(
            id=99,
            lecture_video_id=lecture_video.id,
            lecture_video_id_snapshot=lecture_video.id,
            class_id=class_.id,
            assistant_id_at_start=assistant.id,
            stage=schemas.LectureVideoProcessingStage.NARRATION,
            attempt_number=2,
            status=schemas.LectureVideoProcessingRunStatus.QUEUED,
        )

        create_calls = 0
        non_terminal_calls = 0

        async def fake_create(session_, **kwargs):
            nonlocal create_calls
            assert session_ is session
            create_calls += 1
            raise IntegrityError(
                "INSERT INTO lecture_video_processing_runs (...) VALUES (...)",
                {},
                Exception(
                    "UNIQUE constraint failed: "
                    "lecture_video_processing_runs.lecture_video_id_snapshot, "
                    "lecture_video_processing_runs.stage"
                ),
            )

        async def fake_get_non_terminal_by_snapshot_stage(
            session_, lecture_video_id_snapshot, stage
        ):
            nonlocal non_terminal_calls
            assert session_ is session
            assert lecture_video_id_snapshot == lecture_video.id
            assert stage == schemas.LectureVideoProcessingStage.NARRATION
            non_terminal_calls += 1
            if non_terminal_calls == 1:
                return None
            return existing_run

        latest_attempt_number = AsyncMock(return_value=1)

        monkeypatch.setattr(models.LectureVideoProcessingRun, "create", fake_create)
        monkeypatch.setattr(
            models.LectureVideoProcessingRun,
            "get_non_terminal_by_snapshot_stage",
            fake_get_non_terminal_by_snapshot_stage,
        )
        monkeypatch.setattr(
            models.LectureVideoProcessingRun,
            "get_latest_attempt_number",
            latest_attempt_number,
        )

        run = await lecture_video_processing.queue_narration_processing_run(
            session,
            lecture_video,
            assistant_id_at_start=assistant.id,
        )

    assert run is existing_run
    assert create_calls == 1
    assert non_terminal_calls == 2
    latest_attempt_number.assert_awaited_once()


@with_user(123)
@with_institution(11, "Test Institution")
@with_authz(
    grants=[
        ("user:123", "admin", "class:1"),
        ("user:123", "can_create_assistants", "class:1"),
        ("user:123", "can_edit", "assistant:1"),
    ]
)
async def test_retry_lecture_video_endpoint_returns_conflict_when_requeue_fails(
    api, db, institution, valid_user_token, monkeypatch
):
    async with db.async_session() as session:
        class_, lecture_video, assistant = await create_ready_lecture_video_assistant(
            session,
            institution,
        )
        lecture_video = await models.LectureVideo.get_by_id_with_copy_context(
            session, lecture_video.id
        )
        assert lecture_video is not None
        ready_narration = lecture_video.questions[0].intro_narration
        failed_narration = lecture_video.questions[0].options[0].post_narration
        other_ready = lecture_video.questions[0].options[1].post_narration
        assert ready_narration is not None
        assert failed_narration is not None
        assert other_ready is not None
        assert ready_narration.stored_object is not None
        assert failed_narration.stored_object is not None
        assert other_ready.stored_object is not None

        preserved_ready_stored_object_id = ready_narration.stored_object.id
        preserved_other_ready_stored_object_id = other_ready.stored_object.id
        failed_stored_object_id = failed_narration.stored_object.id
        failed_narration.status = schemas.LectureVideoNarrationStatus.FAILED
        failed_narration.error_message = "Server Error from ElevenLabs"
        lecture_video.status = schemas.LectureVideoStatus.FAILED
        lecture_video.error_message = "Server Error from ElevenLabs"
        session.add(failed_narration)
        session.add(lecture_video)
        await models.LectureVideoProcessingRun.create(
            session,
            lecture_video_id=lecture_video.id,
            lecture_video_id_snapshot=lecture_video.id,
            class_id=class_.id,
            assistant_id_at_start=assistant.id,
            stage=schemas.LectureVideoProcessingStage.NARRATION,
            attempt_number=1,
            status=schemas.LectureVideoProcessingRunStatus.FAILED,
        )
        await session.commit()

    monkeypatch.setattr(
        lecture_video_processing,
        "queue_narration_processing_run",
        AsyncMock(return_value=None),
    )

    response = api.post(
        "/api/v1/class/1/assistant/1/lecture-video/retry",
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )

    assert response.status_code == 409
    assert (
        response.json()["detail"]
        == "Lecture video retry is no longer available because the assistant or lecture video configuration changed."
    )

    async with db.async_session() as session:
        refreshed_video = await models.LectureVideo.get_by_id_with_copy_context(
            session, lecture_video.id
        )
        refreshed_runs = list(
            (
                await session.scalars(
                    select(models.LectureVideoProcessingRun)
                    .where(
                        models.LectureVideoProcessingRun.lecture_video_id_snapshot
                        == lecture_video.id
                    )
                    .order_by(models.LectureVideoProcessingRun.attempt_number.asc())
                )
            ).all()
        )

    assert refreshed_video is not None
    assert refreshed_video.status == schemas.LectureVideoStatus.FAILED
    assert refreshed_video.error_message == "Server Error from ElevenLabs"
    assert refreshed_video.questions[0].intro_narration is not None
    assert (
        refreshed_video.questions[0].intro_narration.stored_object_id
        == preserved_ready_stored_object_id
    )
    assert refreshed_video.questions[0].options[1].post_narration is not None
    assert (
        refreshed_video.questions[0].options[1].post_narration.stored_object_id
        == preserved_other_ready_stored_object_id
    )
    assert refreshed_video.questions[0].options[0].post_narration is not None
    assert refreshed_video.questions[0].options[0].post_narration.status == (
        schemas.LectureVideoNarrationStatus.FAILED
    )
    assert refreshed_video.questions[0].options[0].post_narration.error_message == (
        "Server Error from ElevenLabs"
    )
    assert (
        refreshed_video.questions[0].options[0].post_narration.stored_object_id
        == failed_stored_object_id
    )
    assert len(refreshed_runs) == 1
    assert refreshed_runs[0].status == schemas.LectureVideoProcessingRunStatus.FAILED
    assert refreshed_runs[0].attempt_number == 1


@with_user(123)
@with_institution(11, "Test Institution")
@with_authz(
    grants=[
        ("user:123", "can_create_assistants", "class:1"),
        ("user:123", "can_edit", "assistant:1"),
    ]
)
async def test_copy_lecture_video_assistant_rejects_non_ready_source(
    api, db, institution, valid_user_token
):
    async with db.async_session() as session:
        await create_processing_lecture_video_assistant(session, institution)

    response = api.post(
        "/api/v1/class/1/assistant/1/copy",
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )

    assert response.status_code == 409
    assert (
        response.json()["detail"]
        == "Lecture video assistants can only be copied after narration processing is ready."
    )


@with_user(123)
@with_institution(11, "Test Institution")
@with_authz(
    grants=[
        ("user:123", "can_create_assistants", "class:1"),
        ("user:123", "can_edit", "assistant:1"),
    ]
)
async def test_copy_lecture_video_assistant_within_class_clones_lecture_video_row(
    api, db, institution, valid_user_token
):
    async with db.async_session() as session:
        class_ = models.Class(
            id=1,
            name="Lecture Class",
            institution_id=institution.id,
            api_key="shared-key",
        )
        lecture_video = make_lecture_video(
            class_.id,
            "copy-same-class.mp4",
            filename="copy-same-class.mp4",
            status=schemas.LectureVideoStatus.READY.value,
        )
        session.add(class_)
        session.add(lecture_video)
        await session.flush()
        await create_lecture_video_copy_credentials(session, class_.id)

        session.add(
            models.Assistant(
                id=1,
                name="Lecture Assistant",
                class_id=class_.id,
                creator_id=123,
                interaction_mode=schemas.InteractionMode.LECTURE_VIDEO,
                version=3,
                model="gpt-4o-mini",
                lecture_video_id=lecture_video.id,
                instructions="Teach the lecture.",
                tools="[]",
            )
        )
        await session.commit()

    response = api.post(
        "/api/v1/class/1/assistant/1/copy",
        json={},
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )

    assert response.status_code == 200
    copied = response.json()
    assert copied["class_id"] == 1
    assert copied["lecture_video"]["filename"] == "copy-same-class.mp4"

    async with db.async_session() as session:
        copied_assistant = await session.get(models.Assistant, copied["id"])
        copied_video = await session.get(
            models.LectureVideo, copied_assistant.lecture_video_id
        )

    assert copied_assistant is not None
    assert copied_assistant.lecture_video_id != lecture_video.id
    assert copied_video is not None
    assert copied_video.class_id == 1
    assert copied_video.stored_object_id == lecture_video.stored_object_id
    assert copied_video.source_lecture_video_id_snapshot == lecture_video.id


@with_user(123)
@with_institution(11, "Test Institution")
@with_authz(
    grants=[
        ("user:123", "can_edit", "assistant:1"),
        ("user:123", "can_create_assistants", "class:2"),
    ]
)
async def test_copy_lecture_video_assistant_to_other_class_clones_lecture_video_row(
    api, db, institution, valid_user_token
):
    async with db.async_session() as session:
        source_class = models.Class(
            id=1,
            name="Source Class",
            institution_id=institution.id,
            api_key="shared-key",
        )
        target_class = models.Class(
            id=2,
            name="Target Class",
            institution_id=institution.id,
            api_key="shared-key",
        )
        lecture_video = make_lecture_video(
            source_class.id,
            "copy-source.mp4",
            filename="copy-source.mp4",
            status=schemas.LectureVideoStatus.READY.value,
            uploader_id=123,
        )
        session.add(source_class)
        session.add(target_class)
        session.add(lecture_video)
        await session.flush()
        await create_lecture_video_copy_credentials(session, source_class.id)
        await create_lecture_video_copy_credentials(session, target_class.id)

        question = models.LectureVideoQuestion(
            lecture_video_id=lecture_video.id,
            position=0,
            question_type=schemas.LectureVideoQuestionType.SINGLE_SELECT,
            question_text="Copied question?",
            intro_text="Copied intro",
            stop_offset_ms=1000,
        )
        session.add(question)
        await session.flush()

        intro_narration = models.LectureVideoNarration(
            status=schemas.LectureVideoNarrationStatus.PENDING.value,
        )
        session.add(intro_narration)
        await session.flush()
        question.intro_narration_id = intro_narration.id
        session.add(question)

        option = models.LectureVideoQuestionOption(
            question_id=question.id,
            position=0,
            option_text="Copied option",
            post_answer_text="Copied feedback",
            continue_offset_ms=1500,
        )
        session.add(option)
        await session.flush()

        await session.execute(
            models.lecture_video_question_single_select_correct_option_association.insert().values(
                question_id=question.id,
                option_id=option.id,
            )
        )
        session.add(
            models.Assistant(
                id=1,
                name="Lecture Assistant",
                class_id=source_class.id,
                creator_id=123,
                interaction_mode=schemas.InteractionMode.LECTURE_VIDEO,
                version=3,
                model="gpt-4o-mini",
                lecture_video_id=lecture_video.id,
                instructions="Teach the lecture.",
                tools="[]",
            )
        )
        await session.commit()

    response = api.post(
        "/api/v1/class/1/assistant/1/copy",
        json={"target_class_id": 2},
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )

    assert response.status_code == 200
    copied = response.json()
    assert copied["class_id"] == 2
    assert copied["lecture_video"]["filename"] == "copy-source.mp4"

    async with db.async_session() as session:
        copied_assistant = await session.get(models.Assistant, copied["id"])
        source_video = await session.get(models.LectureVideo, lecture_video.id)
        copied_video = await session.get(
            models.LectureVideo, copied_assistant.lecture_video_id
        )
        copied_question = await session.scalar(
            select(models.LectureVideoQuestion.question_text).where(
                models.LectureVideoQuestion.lecture_video_id == copied_video.id
            )
        )

    assert copied_assistant is not None
    assert source_video is not None
    assert copied_video is not None
    assert copied_assistant.lecture_video_id != lecture_video.id
    assert copied_video.class_id == 2
    assert copied_video.stored_object_id == lecture_video.stored_object_id
    assert copied_video.source_lecture_video_id_snapshot == lecture_video.id
    assert copied_question == "Copied question?"


@with_user(123)
@with_institution(11, "Test Institution")
@with_authz(
    grants=[
        ("user:123", "can_edit", "assistant:1"),
        ("user:123", "can_create_assistants", "class:2"),
    ]
)
async def test_copy_lecture_video_assistant_writes_authz_grants_for_cloned_video(
    api, authz, db, institution, valid_user_token
):
    async with db.async_session() as session:
        source_class = models.Class(
            id=1,
            name="Source Class",
            institution_id=institution.id,
            api_key="shared-key",
        )
        target_class = models.Class(
            id=2,
            name="Target Class",
            institution_id=institution.id,
            api_key="shared-key",
        )
        lecture_video = make_lecture_video(
            source_class.id,
            "copy-source.mp4",
            filename="copy-source.mp4",
            status=schemas.LectureVideoStatus.READY.value,
            uploader_id=123,
        )
        session.add(source_class)
        session.add(target_class)
        session.add(lecture_video)
        await session.flush()
        await create_lecture_video_copy_credentials(session, source_class.id)
        await create_lecture_video_copy_credentials(session, target_class.id)

        session.add(
            models.Assistant(
                id=1,
                name="Lecture Assistant",
                class_id=source_class.id,
                creator_id=123,
                interaction_mode=schemas.InteractionMode.LECTURE_VIDEO,
                version=3,
                model="gpt-4o-mini",
                lecture_video_id=lecture_video.id,
                instructions="Teach the lecture.",
                tools="[]",
            )
        )
        await session.commit()

    response = api.post(
        "/api/v1/class/1/assistant/1/copy",
        json={"target_class_id": 2},
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )

    assert response.status_code == 200
    copied = response.json()

    async with db.async_session() as session:
        copied_assistant = await session.get(models.Assistant, copied["id"])

    assert copied_assistant is not None
    copied_video_id = copied_assistant.lecture_video_id
    assert copied_video_id is not None

    authz_calls = await authz.get_all_calls()
    assert (
        "grant",
        "class:2",
        "parent",
        f"lecture_video:{copied_video_id}",
    ) in authz_calls
    assert (
        "grant",
        "user:123",
        "owner",
        f"lecture_video:{copied_video_id}",
    ) in authz_calls


@with_user(123)
@with_institution(11, "Test Institution")
@with_authz(
    grants=[
        ("user:123", "can_edit", "assistant:1"),
        ("user:123", "can_create_assistants", "class:2"),
    ]
)
async def test_copy_lecture_video_assistant_requires_matching_class_credentials(
    api, db, institution, valid_user_token
):
    async with db.async_session() as session:
        source_class = models.Class(
            id=1,
            name="Source Class",
            institution_id=institution.id,
            api_key="shared-key",
        )
        target_class = models.Class(
            id=2,
            name="Target Class",
            institution_id=institution.id,
            api_key="shared-key",
        )
        lecture_video = make_lecture_video(
            source_class.id,
            "copy-source.mp4",
            filename="copy-source.mp4",
            status=schemas.LectureVideoStatus.READY.value,
            uploader_id=123,
        )
        session.add_all([source_class, target_class, lecture_video])
        await session.flush()
        await create_lecture_video_copy_credentials(session, source_class.id)
        await create_lecture_video_copy_credentials(
            session,
            target_class.id,
            elevenlabs_key="different-elevenlabs-key",
        )

        session.add(
            models.Assistant(
                id=1,
                name="Lecture Assistant",
                class_id=source_class.id,
                creator_id=123,
                interaction_mode=schemas.InteractionMode.LECTURE_VIDEO,
                version=3,
                model="gpt-4o-mini",
                lecture_video_id=lecture_video.id,
                instructions="Teach the lecture.",
                tools="[]",
            )
        )
        await session.commit()

    response = api.post(
        "/api/v1/class/1/assistant/1/copy",
        json={"target_class_id": 2},
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )

    assert response.status_code == 400
    assert response.json() == {
        "detail": (
            "Source and target classes must both have matching Gemini and ElevenLabs "
            "credentials to copy lecture video assistants."
        )
    }


@with_user(123)
@with_institution(11, "Test Institution")
@with_authz(
    grants=[
        ("user:123", "can_edit", "assistant:1"),
        ("user:123", "can_create_assistants", "class:2"),
    ]
)
async def test_copy_lecture_video_assistant_check_requires_matching_class_credentials(
    api, db, institution, valid_user_token
):
    async with db.async_session() as session:
        source_class = models.Class(
            id=1,
            name="Source Class",
            institution_id=institution.id,
            api_key="shared-key",
        )
        target_class = models.Class(
            id=2,
            name="Target Class",
            institution_id=institution.id,
            api_key="shared-key",
        )
        lecture_video = make_lecture_video(
            source_class.id,
            "copy-source.mp4",
            filename="copy-source.mp4",
            status=schemas.LectureVideoStatus.READY.value,
            uploader_id=123,
        )
        session.add_all([source_class, target_class, lecture_video])
        await session.flush()
        await create_lecture_video_copy_credentials(session, source_class.id)

        session.add(
            models.Assistant(
                id=1,
                name="Lecture Assistant",
                class_id=source_class.id,
                creator_id=123,
                interaction_mode=schemas.InteractionMode.LECTURE_VIDEO,
                version=3,
                model="gpt-4o-mini",
                lecture_video_id=lecture_video.id,
                instructions="Teach the lecture.",
                tools="[]",
            )
        )
        await session.commit()

    response = api.post(
        "/api/v1/class/1/assistant/1/copy/check",
        json={"target_class_id": 2},
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )

    assert response.status_code == 400
    assert response.json() == {
        "detail": (
            "Source and target classes must both have matching Gemini and ElevenLabs "
            "credentials to copy lecture video assistants."
        )
    }


@with_user(123)
@with_institution(11, "Test Institution")
@with_authz(
    grants=[
        ("user:123", "admin", "class:1"),
        ("user:123", "can_create_assistants", "class:1"),
    ]
)
async def test_create_lecture_video_assistant_rejects_assigned_lecture_video(
    api, db, institution, valid_user_token, monkeypatch
):
    patch_lecture_video_model_list(monkeypatch)

    async with db.async_session() as session:
        class_ = models.Class(
            id=1,
            name="Lecture Class",
            institution_id=institution.id,
            api_key="sk-test",
        )
        lecture_video = make_lecture_video(
            class_.id,
            "already-attached.mp4",
            filename="already-attached.mp4",
            status=schemas.LectureVideoStatus.READY.value,
        )
        session.add(class_)
        session.add(lecture_video)
        await session.flush()
        await create_lecture_video_copy_credentials(session, class_.id)
        session.add(
            models.Assistant(
                id=1,
                name="Existing Lecture Assistant",
                class_id=class_.id,
                creator_id=123,
                interaction_mode=schemas.InteractionMode.LECTURE_VIDEO,
                version=3,
                model="gpt-4o-mini",
                lecture_video_id=lecture_video.id,
                instructions="Existing lecture assistant.",
                tools="[]",
            )
        )
        await session.commit()

    response = api.post(
        "/api/v1/class/1/assistant",
        json={
            "name": "Another Lecture Assistant",
            "instructions": "Guide the learner through the lecture.",
            "description": "Lecture presentation assistant",
            "interaction_mode": "lecture_video",
            "model": "gpt-4o-mini",
            "tools": [],
            "lecture_video_id": lecture_video.id,
            "lecture_video_manifest": lecture_video_manifest(),
            "voice_id": DEFAULT_LECTURE_VIDEO_VOICE_ID,
        },
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )

    assert response.status_code == 400
    assert "already attached to another assistant" in response.json()["detail"]


@with_user(123)
@with_institution(11, "Test Institution")
@with_authz(
    grants=[
        ("user:123", "admin", "class:1"),
        ("user:123", "can_create_assistants", "class:1"),
    ]
)
async def test_create_assistant_handles_lecture_video_unique_conflict(
    api, db, institution, valid_user_token, monkeypatch
):
    patch_lecture_video_model_list(monkeypatch)

    async with db.async_session() as session:
        class_ = models.Class(
            id=1,
            name="Lecture Class",
            institution_id=institution.id,
            api_key="sk-test",
        )
        lecture_video = make_lecture_video(
            class_.id,
            "race-create.mp4",
            filename="race-create.mp4",
            status=schemas.LectureVideoStatus.UPLOADED.value,
        )
        session.add(class_)
        session.add(lecture_video)
        await create_lecture_video_copy_credentials(session, class_.id)
        await session.commit()
        await session.refresh(lecture_video)

    async def fail_create(*args, **kwargs):
        raise IntegrityError(
            "INSERT INTO assistants (lecture_video_id) VALUES (?)",
            {},
            Exception("UNIQUE constraint failed: assistants.lecture_video_id"),
        )

    monkeypatch.setattr(models.Assistant, "create", fail_create)

    response = api.post(
        "/api/v1/class/1/assistant",
        json={
            "name": "Another Lecture Assistant",
            "instructions": "Guide the learner through the lecture.",
            "description": "Lecture presentation assistant",
            "interaction_mode": "lecture_video",
            "model": "gpt-4o-mini",
            "tools": [],
            "lecture_video_id": lecture_video.id,
            "lecture_video_manifest": lecture_video_manifest(),
            "voice_id": DEFAULT_LECTURE_VIDEO_VOICE_ID,
        },
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )

    assert response.status_code == 400
    assert "already attached to another assistant" in response.json()["detail"]


@with_user(123)
@with_institution(11, "Test Institution")
@with_authz(
    grants=[
        ("user:123", "admin", "class:1"),
        ("user:123", "can_create_assistants", "class:1"),
        ("user:123", "can_edit", "assistant:1"),
    ]
)
async def test_update_assistant_handles_lecture_video_unique_conflict(
    api, db, institution, valid_user_token, monkeypatch
):
    patch_lecture_video_model_list(monkeypatch)

    async with db.async_session() as session:
        class_ = models.Class(
            id=1,
            name="Lecture Class",
            institution_id=institution.id,
            api_key="sk-test",
        )
        first_video = make_lecture_video(
            class_.id,
            "race-update-first.mp4",
            filename="race-update-first.mp4",
            status=schemas.LectureVideoStatus.UPLOADED.value,
        )
        second_video = make_lecture_video(
            class_.id,
            "race-update-second.mp4",
            filename="race-update-second.mp4",
            status=schemas.LectureVideoStatus.UPLOADED.value,
        )
        session.add_all([class_, first_video, second_video])
        await session.flush()
        await create_lecture_video_copy_credentials(session, class_.id)
        session.add(
            models.Assistant(
                id=1,
                name="Existing Lecture Assistant",
                class_id=class_.id,
                creator_id=123,
                interaction_mode=schemas.InteractionMode.LECTURE_VIDEO,
                version=3,
                model="gpt-4o-mini",
                lecture_video_id=first_video.id,
                instructions="Existing lecture assistant.",
                tools="[]",
            )
        )
        await session.commit()
        await session.refresh(second_video)

    async def fail_persist_manifest(*args, **kwargs):
        raise IntegrityError(
            "UPDATE assistants SET lecture_video_id=? WHERE assistants.id = ?",
            {},
            Exception("UNIQUE constraint failed: assistants.lecture_video_id"),
        )

    monkeypatch.setattr(
        lecture_video_service, "persist_manifest", fail_persist_manifest
    )

    response = api.put(
        "/api/v1/class/1/assistant/1",
        json={
            "lecture_video_id": second_video.id,
            "lecture_video_manifest": lecture_video_manifest(),
            "voice_id": DEFAULT_LECTURE_VIDEO_VOICE_ID,
        },
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )

    assert response.status_code == 400
    assert "already attached to another assistant" in response.json()["detail"]


@with_institution(11, "Test Institution")
async def test_clear_normalized_content_deletes_unused_narration_stored_objects(
    db, institution, config, monkeypatch, tmp_path
):
    narration_dir = tmp_path / "narrations"
    monkeypatch.setattr(
        config,
        "lecture_video_audio_store",
        LocalAudioStoreSettings(save_target=str(narration_dir)),
    )

    async with db.async_session() as session:
        class_ = models.Class(
            id=1,
            name="Lecture Class",
            institution_id=institution.id,
            api_key="sk-test",
        )
        lecture_video = make_lecture_video(class_.id, "cleanup-narration.mp4")
        session.add_all([class_, lecture_video])
        await session.flush()

        intro_stored_object = models.LectureVideoNarrationStoredObject(
            key="intro-audio.mp3",
            content_type="audio/mpeg",
            content_length=100,
        )
        post_stored_object = models.LectureVideoNarrationStoredObject(
            key="post-audio.mp3",
            content_type="audio/mpeg",
            content_length=120,
        )
        session.add_all([intro_stored_object, post_stored_object])
        await session.flush()
        (narration_dir / intro_stored_object.key).parent.mkdir(
            parents=True, exist_ok=True
        )
        (narration_dir / intro_stored_object.key).write_bytes(b"intro-audio")
        (narration_dir / post_stored_object.key).write_bytes(b"post-audio")

        intro_narration = models.LectureVideoNarration(
            stored_object_id=intro_stored_object.id,
            status=schemas.LectureVideoNarrationStatus.READY.value,
        )
        post_narration = models.LectureVideoNarration(
            stored_object_id=post_stored_object.id,
            status=schemas.LectureVideoNarrationStatus.READY.value,
        )
        session.add_all([intro_narration, post_narration])
        await session.flush()

        question = models.LectureVideoQuestion(
            lecture_video_id=lecture_video.id,
            position=0,
            question_type=schemas.LectureVideoQuestionType.SINGLE_SELECT,
            question_text="Question?",
            intro_text="Intro",
            stop_offset_ms=1000,
            intro_narration_id=intro_narration.id,
        )
        session.add(question)
        await session.flush()

        option = models.LectureVideoQuestionOption(
            question_id=question.id,
            position=0,
            option_text="Option",
            post_answer_text="Feedback",
            continue_offset_ms=1500,
            post_narration_id=post_narration.id,
        )
        session.add(option)
        await session.commit()

        await lecture_video_service.clear_normalized_content(session, lecture_video.id)
        await session.commit()

        narration_count = await session.scalar(
            select(func.count()).select_from(models.LectureVideoNarration)
        )
        narration_stored_object_count = await session.scalar(
            select(func.count()).select_from(models.LectureVideoNarrationStoredObject)
        )

    assert narration_count == 0
    assert narration_stored_object_count == 0
    assert not (narration_dir / "intro-audio.mp3").exists()
    assert not (narration_dir / "post-audio.mp3").exists()


@with_institution(11, "Test Institution")
async def test_clear_normalized_content_preserves_shared_narration_stored_object(
    db, institution, config, monkeypatch, tmp_path
):
    narration_dir = tmp_path / "narrations"
    monkeypatch.setattr(
        config,
        "lecture_video_audio_store",
        LocalAudioStoreSettings(save_target=str(narration_dir)),
    )

    async with db.async_session() as session:
        class_ = models.Class(
            id=1,
            name="Lecture Class",
            institution_id=institution.id,
            api_key="sk-test",
        )
        first_video = make_lecture_video(class_.id, "first-shared.mp4")
        second_video = make_lecture_video(class_.id, "second-shared.mp4")
        session.add_all([class_, first_video, second_video])
        await session.flush()

        shared_stored_object = models.LectureVideoNarrationStoredObject(
            key="shared-audio.mp3",
            content_type="audio/mpeg",
            content_length=100,
        )
        session.add(shared_stored_object)
        await session.flush()
        (narration_dir / shared_stored_object.key).parent.mkdir(
            parents=True, exist_ok=True
        )
        (narration_dir / shared_stored_object.key).write_bytes(b"shared-audio")

        first_narration = models.LectureVideoNarration(
            stored_object_id=shared_stored_object.id,
            status=schemas.LectureVideoNarrationStatus.READY.value,
        )
        second_narration = models.LectureVideoNarration(
            stored_object_id=shared_stored_object.id,
            status=schemas.LectureVideoNarrationStatus.READY.value,
        )
        session.add_all([first_narration, second_narration])
        await session.flush()

        first_question = models.LectureVideoQuestion(
            lecture_video_id=first_video.id,
            position=0,
            question_type=schemas.LectureVideoQuestionType.SINGLE_SELECT,
            question_text="First question?",
            intro_text="Intro",
            stop_offset_ms=1000,
            intro_narration_id=first_narration.id,
        )
        second_question = models.LectureVideoQuestion(
            lecture_video_id=second_video.id,
            position=0,
            question_type=schemas.LectureVideoQuestionType.SINGLE_SELECT,
            question_text="Second question?",
            intro_text="Intro",
            stop_offset_ms=1000,
            intro_narration_id=second_narration.id,
        )
        session.add_all([first_question, second_question])
        await session.commit()

        await lecture_video_service.clear_normalized_content(session, first_video.id)
        await session.commit()

        remaining_narration_count = await session.scalar(
            select(func.count()).select_from(models.LectureVideoNarration)
        )
        remaining_stored_object_count = await session.scalar(
            select(func.count()).select_from(models.LectureVideoNarrationStoredObject)
        )
        second_question_exists = await session.get(
            models.LectureVideoQuestion, second_question.id
        )

    assert remaining_narration_count == 1
    assert remaining_stored_object_count == 1
    assert second_question_exists is not None
    assert (narration_dir / "shared-audio.mp3").exists()


@with_institution(11, "Test Institution")
async def test_correct_option_association_requires_option_belongs_to_question(
    db, institution
):
    async with db.async_session() as session:
        await session.execute(text("PRAGMA foreign_keys=ON"))
        class_ = models.Class(
            id=1,
            name="Lecture Class",
            institution_id=institution.id,
            api_key="sk-test",
        )
        lecture_video = make_lecture_video(class_.id, "constraint-check.mp4")
        session.add_all([class_, lecture_video])
        await session.flush()

        first_question = models.LectureVideoQuestion(
            lecture_video_id=lecture_video.id,
            position=0,
            question_type=schemas.LectureVideoQuestionType.SINGLE_SELECT,
            question_text="First question?",
            intro_text="Intro",
            stop_offset_ms=1000,
        )
        second_question = models.LectureVideoQuestion(
            lecture_video_id=lecture_video.id,
            position=1,
            question_type=schemas.LectureVideoQuestionType.SINGLE_SELECT,
            question_text="Second question?",
            intro_text="Intro",
            stop_offset_ms=2000,
        )
        session.add_all([first_question, second_question])
        await session.flush()

        second_question_option = models.LectureVideoQuestionOption(
            question_id=second_question.id,
            position=0,
            option_text="Second option",
            post_answer_text="Feedback",
            continue_offset_ms=2500,
        )
        session.add(second_question_option)
        await session.flush()

        with pytest.raises(IntegrityError):
            await session.execute(
                models.lecture_video_question_single_select_correct_option_association.insert().values(
                    question_id=first_question.id,
                    option_id=second_question_option.id,
                )
            )
            await session.flush()


@with_institution(11, "Test Institution")
async def test_single_select_correct_option_association_allows_only_one_option_per_question(
    db, institution
):
    async with db.async_session() as session:
        await session.execute(text("PRAGMA foreign_keys=ON"))
        class_ = models.Class(
            id=1,
            name="Lecture Class",
            institution_id=institution.id,
            api_key="sk-test",
        )
        lecture_video = make_lecture_video(class_.id, "single-select-limit.mp4")
        session.add_all([class_, lecture_video])
        await session.flush()

        question = models.LectureVideoQuestion(
            lecture_video_id=lecture_video.id,
            position=0,
            question_type=schemas.LectureVideoQuestionType.SINGLE_SELECT,
            question_text="Question?",
            intro_text="Intro",
            stop_offset_ms=1000,
        )
        session.add(question)
        await session.flush()

        first_option = models.LectureVideoQuestionOption(
            question_id=question.id,
            position=0,
            option_text="First option",
            post_answer_text="First feedback",
            continue_offset_ms=1500,
        )
        second_option = models.LectureVideoQuestionOption(
            question_id=question.id,
            position=1,
            option_text="Second option",
            post_answer_text="Second feedback",
            continue_offset_ms=2000,
        )
        session.add_all([first_option, second_option])
        await session.flush()

        await session.execute(
            models.lecture_video_question_single_select_correct_option_association.insert().values(
                question_id=question.id,
                option_id=first_option.id,
            )
        )

        with pytest.raises(IntegrityError):
            await session.execute(
                models.lecture_video_question_single_select_correct_option_association.insert().values(
                    question_id=question.id,
                    option_id=second_option.id,
                )
            )
            await session.flush()


@with_institution(11, "Test Institution")
async def test_clear_normalized_content_deletes_stored_object_shared_within_same_video(
    db, institution, config, monkeypatch, tmp_path
):
    narration_dir = tmp_path / "narrations"
    monkeypatch.setattr(
        config,
        "lecture_video_audio_store",
        LocalAudioStoreSettings(save_target=str(narration_dir)),
    )

    async with db.async_session() as session:
        class_ = models.Class(
            id=1,
            name="Lecture Class",
            institution_id=institution.id,
            api_key="sk-test",
        )
        lecture_video = make_lecture_video(class_.id, "shared-within-video.mp4")
        session.add_all([class_, lecture_video])
        await session.flush()

        shared_stored_object = models.LectureVideoNarrationStoredObject(
            key="shared-within-video.mp3",
            content_type="audio/mpeg",
            content_length=100,
        )
        session.add(shared_stored_object)
        await session.flush()
        (narration_dir / shared_stored_object.key).parent.mkdir(
            parents=True, exist_ok=True
        )
        (narration_dir / shared_stored_object.key).write_bytes(b"shared-audio")

        intro_narration = models.LectureVideoNarration(
            stored_object_id=shared_stored_object.id,
            status=schemas.LectureVideoNarrationStatus.READY.value,
        )
        post_narration = models.LectureVideoNarration(
            stored_object_id=shared_stored_object.id,
            status=schemas.LectureVideoNarrationStatus.READY.value,
        )
        session.add_all([intro_narration, post_narration])
        await session.flush()

        question = models.LectureVideoQuestion(
            lecture_video_id=lecture_video.id,
            position=0,
            question_type=schemas.LectureVideoQuestionType.SINGLE_SELECT,
            question_text="Question?",
            intro_text="Intro",
            stop_offset_ms=1000,
            intro_narration_id=intro_narration.id,
        )
        session.add(question)
        await session.flush()

        option = models.LectureVideoQuestionOption(
            question_id=question.id,
            position=0,
            option_text="Option",
            post_answer_text="Feedback",
            continue_offset_ms=1500,
            post_narration_id=post_narration.id,
        )
        session.add(option)
        await session.commit()

        await lecture_video_service.clear_normalized_content(session, lecture_video.id)
        await session.commit()

        narration_count = await session.scalar(
            select(func.count()).select_from(models.LectureVideoNarration)
        )
        narration_stored_object_count = await session.scalar(
            select(func.count()).select_from(models.LectureVideoNarrationStoredObject)
        )

    assert narration_count == 0
    assert narration_stored_object_count == 0
    assert not (narration_dir / "shared-within-video.mp3").exists()


@with_institution(11, "Test Institution")
async def test_lecture_video_delete_deletes_unused_video_stored_object(
    db, institution, config, monkeypatch, tmp_path
):
    video_dir = tmp_path / "videos"
    monkeypatch.setattr(
        config,
        "video_store",
        LocalVideoStoreSettings(type="local", save_target=str(video_dir)),
    )

    async with db.async_session() as session:
        class_ = models.Class(
            id=1,
            name="Lecture Class",
            institution_id=institution.id,
            api_key="sk-test",
        )
        stored_object = models.LectureVideoStoredObject(
            key="shared-video.mp4",
            original_filename="shared-video.mp4",
            content_type="video/mp4",
            content_length=1000,
        )
        session.add_all([class_, stored_object])
        await session.flush()
        video_dir.mkdir(parents=True, exist_ok=True)
        (video_dir / stored_object.key).write_bytes(b"shared-video")

        first_video = await models.LectureVideo.create(
            session,
            class_id=class_.id,
            stored_object_id=stored_object.id,
            user_id=None,
        )
        second_video = await models.LectureVideo.create(
            session,
            class_id=class_.id,
            stored_object_id=stored_object.id,
            user_id=None,
        )
        await session.commit()

        await lecture_video_service.delete_lecture_video(session, first_video.id)
        await session.commit()
        stored_object_after_first_delete = await session.get(
            models.LectureVideoStoredObject, stored_object.id
        )

        await lecture_video_service.delete_lecture_video(session, second_video.id)
        await session.commit()
        stored_object_after_second_delete = await session.get(
            models.LectureVideoStoredObject, stored_object.id
        )

    assert stored_object_after_first_delete is not None
    assert stored_object_after_second_delete is None
    assert not (video_dir / "shared-video.mp4").exists()


@with_institution(11, "Test Institution")
async def test_lecture_video_delete_deletes_unused_stored_object_without_video_store(
    db, institution, config, monkeypatch
):
    monkeypatch.setattr(config, "video_store", None)

    async with db.async_session() as session:
        class_ = models.Class(
            id=1,
            name="Lecture Class",
            institution_id=institution.id,
            api_key="sk-test",
        )
        stored_object = models.LectureVideoStoredObject(
            key="legacy-video.mp4",
            original_filename="legacy-video.mp4",
            content_type="video/mp4",
            content_length=1000,
        )
        session.add_all([class_, stored_object])
        await session.flush()

        lecture_video = await models.LectureVideo.create(
            session,
            class_id=class_.id,
            stored_object_id=stored_object.id,
            user_id=None,
        )
        await session.commit()

        await lecture_video_service.delete_lecture_video(session, lecture_video.id)
        await session.commit()
        stored_object_after_delete = await session.get(
            models.LectureVideoStoredObject, stored_object.id
        )

    assert stored_object_after_delete is None


@with_institution(11, "Test Institution")
async def test_delete_lecture_video_deletes_manifest_and_audio_assets(
    db, institution, config, monkeypatch, tmp_path
):
    video_dir = tmp_path / "videos"
    narration_dir = tmp_path / "narrations"
    monkeypatch.setattr(
        config,
        "video_store",
        LocalVideoStoreSettings(type="local", save_target=str(video_dir)),
    )
    monkeypatch.setattr(
        config,
        "lecture_video_audio_store",
        LocalAudioStoreSettings(save_target=str(narration_dir)),
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
            "full-delete.mp4",
            filename="full-delete.mp4",
        )
        session.add_all([class_, lecture_video])
        await session.flush()

        intro_stored_object = models.LectureVideoNarrationStoredObject(
            key="full-delete-intro.mp3",
            content_type="audio/mpeg",
            content_length=100,
        )
        post_stored_object = models.LectureVideoNarrationStoredObject(
            key="full-delete-post.mp3",
            content_type="audio/mpeg",
            content_length=120,
        )
        session.add_all([intro_stored_object, post_stored_object])
        await session.flush()

        video_dir.mkdir(parents=True, exist_ok=True)
        narration_dir.mkdir(parents=True, exist_ok=True)
        (video_dir / lecture_video.stored_object.key).write_bytes(b"video-bytes")
        (narration_dir / intro_stored_object.key).write_bytes(b"intro-bytes")
        (narration_dir / post_stored_object.key).write_bytes(b"post-bytes")

        intro_narration = models.LectureVideoNarration(
            stored_object_id=intro_stored_object.id,
            status=schemas.LectureVideoNarrationStatus.READY.value,
        )
        post_narration = models.LectureVideoNarration(
            stored_object_id=post_stored_object.id,
            status=schemas.LectureVideoNarrationStatus.READY.value,
        )
        session.add_all([intro_narration, post_narration])
        await session.flush()

        question = models.LectureVideoQuestion(
            lecture_video_id=lecture_video.id,
            position=0,
            question_type=schemas.LectureVideoQuestionType.SINGLE_SELECT,
            question_text="Question?",
            intro_text="Intro",
            stop_offset_ms=1000,
            intro_narration_id=intro_narration.id,
        )
        session.add(question)
        await session.flush()

        option = models.LectureVideoQuestionOption(
            question_id=question.id,
            position=0,
            option_text="Option",
            post_answer_text="Feedback",
            continue_offset_ms=1500,
            post_narration_id=post_narration.id,
        )
        session.add(option)
        await session.commit()

        await lecture_video_service.delete_lecture_video(session, lecture_video.id)
        await session.commit()

        deleted_video = await session.get(models.LectureVideo, lecture_video.id)
        remaining_questions = await session.scalar(
            select(func.count()).select_from(models.LectureVideoQuestion)
        )
        remaining_narrations = await session.scalar(
            select(func.count()).select_from(models.LectureVideoNarration)
        )
        remaining_narration_stored_objects = await session.scalar(
            select(func.count()).select_from(models.LectureVideoNarrationStoredObject)
        )

    assert deleted_video is None
    assert remaining_questions == 0
    assert remaining_narrations == 0
    assert remaining_narration_stored_objects == 0
    assert not (video_dir / "full-delete.mp4").exists()
    assert not (narration_dir / "full-delete-intro.mp3").exists()
    assert not (narration_dir / "full-delete-post.mp3").exists()


@with_user(123)
@with_institution(11, "Test Institution")
@with_authz(grants=[("user:123", "can_create_thread", "class:1")])
async def test_lecture_thread_returns_409_when_lecture_video_not_ready(
    api, db, institution, valid_user_token
):
    async with db.async_session() as session:
        class_ = models.Class(
            id=1,
            name="Test Class",
            institution_id=institution.id,
            api_key="test-key",
        )
        lecture_video = make_lecture_video(
            class_.id,
            "not-ready.mp4",
            filename="not-ready.mp4",
            status=schemas.LectureVideoStatus.UPLOADED.value,
        )
        assistant = models.Assistant(
            id=1,
            name="Lecture Assistant",
            class_id=class_.id,
            interaction_mode=schemas.InteractionMode.LECTURE_VIDEO,
            version=3,
            lecture_video_id=1,
            instructions="You are a lecture assistant.",
        )
        session.add(class_)
        session.add(lecture_video)
        await session.flush()
        assistant.lecture_video_id = lecture_video.id
        session.add(assistant)
        await session.commit()

    response = api.post(
        "/api/v1/class/1/thread/lecture",
        json={"assistant_id": 1},
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )
    assert response.status_code == 409
    assert (
        response.json()["detail"] == "This assistant's lecture video is not ready yet."
    )


@with_user(123)
@with_institution(11, "Test Institution")
@with_authz(grants=[("user:123", "can_create_thread", "class:1")])
async def test_lecture_thread_returns_failed_specific_message_when_lecture_video_failed(
    api, db, institution, valid_user_token
):
    async with db.async_session() as session:
        class_ = models.Class(
            id=1,
            name="Test Class",
            institution_id=institution.id,
            api_key="test-key",
        )
        lecture_video = make_lecture_video(
            class_.id,
            "failed.mp4",
            filename="failed.mp4",
            status=schemas.LectureVideoStatus.FAILED.value,
        )
        lecture_video.error_message = "Server Error from ElevenLabs"
        assistant = models.Assistant(
            id=1,
            name="Lecture Assistant",
            class_id=class_.id,
            interaction_mode=schemas.InteractionMode.LECTURE_VIDEO,
            version=3,
            lecture_video_id=1,
            instructions="You are a lecture assistant.",
        )
        session.add(class_)
        session.add(lecture_video)
        await session.flush()
        assistant.lecture_video_id = lecture_video.id
        session.add(assistant)
        await session.commit()

    response = api.post(
        "/api/v1/class/1/thread/lecture",
        json={"assistant_id": 1},
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )
    assert response.status_code == 409
    assert (
        response.json()["detail"]
        == "This assistant's lecture video narration processing failed. Edit the assistant and retry."
    )


@with_user(123)
@with_institution(11, "Test Institution")
@with_authz(
    grants=[
        ("user:123", "can_view", "thread:109"),
    ]
)
async def test_get_thread_video_stream_and_range(
    api, db, institution, valid_user_token, config, monkeypatch, tmp_path
):
    video_key = "lecture-video.mp4"
    video_bytes = b"0123456789abcdef"
    (tmp_path / video_key).write_bytes(video_bytes)
    monkeypatch.setattr(
        config,
        "video_store",
        LocalVideoStoreSettings(type="local", save_target=str(tmp_path)),
    )

    async with db.async_session() as session:
        class_ = models.Class(
            id=1,
            name="Test Class",
            institution_id=institution.id,
        )
        session.add(class_)
        await session.flush()

        lecture_video = make_lecture_video(
            class_.id,
            video_key,
            filename="Test Video.mp4",
            content_length=len(video_bytes),
        )
        session.add(lecture_video)
        await session.flush()

        assistant = models.Assistant(
            id=1,
            name="Lecture Assistant",
            class_id=class_.id,
            interaction_mode=schemas.InteractionMode.LECTURE_VIDEO,
            version=3,
            lecture_video_id=lecture_video.id,
        )
        session.add(assistant)
        await session.flush()

        thread = models.Thread(
            id=109,
            name="Lecture Presentation",
            version=3,
            thread_id="thread-video-109",
            class_id=class_.id,
            assistant_id=assistant.id,
            interaction_mode=schemas.InteractionMode.LECTURE_VIDEO,
            lecture_video_id=lecture_video.id,
            private=True,
            tools_available="[]",
        )
        session.add(thread)
        await session.commit()

    response = api.get(
        "/api/v1/class/1/thread/109/video",
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )
    assert response.status_code == 200
    assert response.headers["accept-ranges"] == "bytes"
    assert response.headers["content-length"] == str(len(video_bytes))
    assert response.headers["content-type"].startswith("video/mp4")
    assert response.content == video_bytes

    partial = api.get(
        "/api/v1/class/1/thread/109/video",
        headers={"Authorization": f"Bearer {valid_user_token}", "Range": "bytes=2-5"},
    )
    assert partial.status_code == 206
    assert partial.headers["accept-ranges"] == "bytes"
    assert partial.headers["content-range"] == f"bytes 2-5/{len(video_bytes)}"
    assert partial.headers["content-length"] == "4"
    assert partial.content == video_bytes[2:6]


@with_user(123)
@with_institution(11, "Test Institution")
@with_authz(
    grants=[
        ("user:123", "can_view", "thread:109"),
    ]
)
async def test_get_thread_video_invalid_range_returns_416(
    api, db, institution, valid_user_token, config, monkeypatch, tmp_path
):
    video_key = "lecture-video.mp4"
    video_bytes = b"0123456789"
    (tmp_path / video_key).write_bytes(video_bytes)
    monkeypatch.setattr(
        config,
        "video_store",
        LocalVideoStoreSettings(type="local", save_target=str(tmp_path)),
    )

    async with db.async_session() as session:
        class_ = models.Class(
            id=1,
            name="Test Class",
            institution_id=institution.id,
        )
        session.add(class_)
        await session.flush()

        lecture_video = make_lecture_video(
            class_.id,
            video_key,
            filename="Test Video.mp4",
            content_length=len(video_bytes),
        )
        session.add(lecture_video)
        await session.flush()

        assistant = models.Assistant(
            id=1,
            name="Lecture Assistant",
            class_id=class_.id,
            interaction_mode=schemas.InteractionMode.LECTURE_VIDEO,
            version=3,
            lecture_video_id=lecture_video.id,
        )
        session.add(assistant)
        await session.flush()

        thread = models.Thread(
            id=109,
            name="Lecture Presentation",
            version=3,
            thread_id="thread-video-109",
            class_id=class_.id,
            assistant_id=assistant.id,
            interaction_mode=schemas.InteractionMode.LECTURE_VIDEO,
            lecture_video_id=lecture_video.id,
            private=True,
            tools_available="[]",
        )
        session.add(thread)
        await session.commit()

    response = api.get(
        "/api/v1/class/1/thread/109/video",
        headers={
            "Authorization": f"Bearer {valid_user_token}",
            "Range": "bytes=100-200",
        },
    )
    assert response.status_code == 416
    assert response.headers["accept-ranges"] == "bytes"
    assert response.headers["content-range"] == f"bytes */{len(video_bytes)}"


@with_user(123)
@with_institution(11, "Test Institution")
@with_authz(
    grants=[
        ("user:123", "can_create_thread", "class:1"),
        ("user:123", "student", "class:1"),
    ]
)
async def test_get_thread_lecture_video_narration_streams_audio(
    api, authz, db, institution, valid_user_token, config, monkeypatch, tmp_path
):
    narration_key = "intro-ready.mp3"
    narration_bytes = b"intro-audio"
    (tmp_path / narration_key).write_bytes(narration_bytes)
    monkeypatch.setattr(
        config,
        "lecture_video_audio_store",
        LocalAudioStoreSettings(type="local", save_target=str(tmp_path)),
    )

    async with db.async_session() as session:
        class_, lecture_video, _assistant = await create_ready_lecture_video_assistant(
            session,
            institution,
        )
        lecture_video = await models.LectureVideo.get_by_id_with_copy_context(
            session, lecture_video.id
        )
        question = lecture_video.questions[0]
        option = question.options[0]
        assert question.intro_narration is not None
        assert option.post_narration is not None
        await attach_ready_narration(
            session,
            question.intro_narration,
            key=narration_key,
            content_length=len(narration_bytes),
        )
        await attach_ready_narration(
            session,
            option.post_narration,
            key="lecture-post.mp3",
            content_length=8,
        )
        await session.commit()

    create_response = api.post(
        f"/api/v1/class/{class_.id}/thread/lecture",
        json={"assistant_id": 1, "parties": [123]},
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )
    assert create_response.status_code == 200
    thread_id = create_response.json()["thread"]["id"]
    await grant_thread_permissions(config, thread_id, 123)

    response = api.get(
        f"/api/v1/class/{class_.id}/thread/{thread_id}/lecture-video/narration/{question.intro_narration.id}",
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )
    assert response.status_code == 200
    assert response.content == narration_bytes
    assert response.headers["content-type"].startswith("audio/ogg")

    missing = api.get(
        f"/api/v1/class/{class_.id}/thread/{thread_id}/lecture-video/narration/99999",
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )
    assert missing.status_code == 404

    out_of_order = api.get(
        f"/api/v1/class/{class_.id}/thread/{thread_id}/lecture-video/narration/{option.post_narration.id}",
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )
    assert out_of_order.status_code == 404


@with_user(123)
@with_institution(11, "Test Institution")
@with_authz(
    grants=[
        ("user:123", "can_create_thread", "class:1"),
        ("user:123", "student", "class:1"),
    ]
)
async def test_get_thread_lecture_video_narration_rejects_non_numeric_id(
    api, authz, db, institution, valid_user_token, config, monkeypatch, tmp_path
):
    narration_key = "intro-ready.mp3"
    (tmp_path / narration_key).write_bytes(b"intro-audio")
    monkeypatch.setattr(
        config,
        "lecture_video_audio_store",
        LocalAudioStoreSettings(type="local", save_target=str(tmp_path)),
    )

    async with db.async_session() as session:
        class_, lecture_video, _assistant = await create_ready_lecture_video_assistant(
            session,
            institution,
        )
        lecture_video = await models.LectureVideo.get_by_id_with_copy_context(
            session, lecture_video.id
        )
        question = lecture_video.questions[0]
        assert question.intro_narration is not None
        await attach_ready_narration(
            session,
            question.intro_narration,
            key=narration_key,
            content_length=len(b"intro-audio"),
        )
        await session.commit()

    create_response = api.post(
        f"/api/v1/class/{class_.id}/thread/lecture",
        json={"assistant_id": 1, "parties": [123]},
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )
    assert create_response.status_code == 200
    thread_id = create_response.json()["thread"]["id"]
    await grant_thread_permissions(config, thread_id, 123)

    response = api.get(
        f"/api/v1/class/{class_.id}/thread/{thread_id}/lecture-video/narration/not-a-number",
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )
    assert response.status_code == 422


@with_user(123)
@with_institution(11, "Test Institution")
@with_authz(
    grants=[
        ("user:123", "can_create_thread", "class:1"),
        ("user:123", "student", "class:1"),
    ]
)
async def test_get_thread_lecture_video_narration_lazily_initializes_legacy_runtime_state(
    api, authz, db, institution, valid_user_token, config, monkeypatch, tmp_path
):
    narration_key = "legacy-intro-ready.mp3"
    narration_bytes = b"legacy-intro-audio"
    (tmp_path / narration_key).write_bytes(narration_bytes)
    monkeypatch.setattr(
        config,
        "lecture_video_audio_store",
        LocalAudioStoreSettings(type="local", save_target=str(tmp_path)),
    )

    async with db.async_session() as session:
        class_, lecture_video, _assistant = await create_ready_lecture_video_assistant(
            session,
            institution,
        )
        lecture_video = await models.LectureVideo.get_by_id_with_copy_context(
            session, lecture_video.id
        )
        question = lecture_video.questions[0]
        assert question.intro_narration is not None
        await attach_ready_narration(
            session,
            question.intro_narration,
            key=narration_key,
            content_length=len(narration_bytes),
        )
        await session.commit()

    create_response = api.post(
        f"/api/v1/class/{class_.id}/thread/lecture",
        json={"assistant_id": 1, "parties": [123]},
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )
    assert create_response.status_code == 200
    thread_id = create_response.json()["thread"]["id"]
    await grant_thread_permissions(config, thread_id, 123)

    async with db.async_session() as session:
        await session.execute(
            delete(models.LectureVideoInteraction).where(
                models.LectureVideoInteraction.thread_id == thread_id
            )
        )
        await session.execute(
            delete(models.LectureVideoThreadState).where(
                models.LectureVideoThreadState.thread_id == thread_id
            )
        )
        await session.commit()

    response = api.get(
        f"/api/v1/class/{class_.id}/thread/{thread_id}/lecture-video/narration/{question.intro_narration.id}",
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )
    assert response.status_code == 200
    assert response.content == narration_bytes


@with_user(123)
@with_institution(11, "Test Institution")
@with_authz(
    grants=[
        ("user:123", "can_create_thread", "class:1"),
        ("user:123", "student", "class:1"),
    ]
)
async def test_get_thread_lecture_video_narration_requires_can_participate(
    api, db, institution, valid_user_token, config, monkeypatch, tmp_path
):
    narration_key = "intro-ready.mp3"
    (tmp_path / narration_key).write_bytes(b"intro-audio")
    monkeypatch.setattr(
        config,
        "lecture_video_audio_store",
        LocalAudioStoreSettings(type="local", save_target=str(tmp_path)),
    )

    async with db.async_session() as session:
        class_, lecture_video, _assistant = await create_ready_lecture_video_assistant(
            session,
            institution,
        )
        lecture_video = await models.LectureVideo.get_by_id_with_copy_context(
            session, lecture_video.id
        )
        question = lecture_video.questions[0]
        assert question.intro_narration is not None
        await attach_ready_narration(
            session,
            question.intro_narration,
            key=narration_key,
            content_length=len(b"intro-audio"),
        )
        await session.commit()

    create_response = api.post(
        f"/api/v1/class/{class_.id}/thread/lecture",
        json={"assistant_id": 1, "parties": [123]},
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )
    assert create_response.status_code == 200
    thread_id = create_response.json()["thread"]["id"]

    response = api.get(
        f"/api/v1/class/{class_.id}/thread/{thread_id}/lecture-video/narration/{question.intro_narration.id}",
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )
    assert response.status_code == 403


@with_user(123)
@with_institution(11, "Test Institution")
@with_authz(
    grants=[
        ("user:123", "can_create_thread", "class:1"),
        ("user:123", "student", "class:1"),
    ]
)
async def test_get_thread_lecture_video_narration_requires_ready_status(
    api, authz, db, institution, valid_user_token, config, monkeypatch, tmp_path
):
    narration_key = "intro-pending.mp3"
    (tmp_path / narration_key).write_bytes(b"intro-audio")
    monkeypatch.setattr(
        config,
        "lecture_video_audio_store",
        LocalAudioStoreSettings(type="local", save_target=str(tmp_path)),
    )

    async with db.async_session() as session:
        class_, lecture_video, _assistant = await create_ready_lecture_video_assistant(
            session,
            institution,
        )
        lecture_video = await models.LectureVideo.get_by_id_with_copy_context(
            session, lecture_video.id
        )
        question = lecture_video.questions[0]
        assert question.intro_narration is not None
        stored_object = models.LectureVideoNarrationStoredObject(
            key=narration_key,
            content_type="audio/mpeg",
            content_length=len(b"intro-audio"),
        )
        session.add(stored_object)
        await session.flush()
        question.intro_narration.stored_object_id = stored_object.id
        question.intro_narration.stored_object = stored_object
        question.intro_narration.status = schemas.LectureVideoNarrationStatus.PENDING
        await session.commit()

    create_response = api.post(
        f"/api/v1/class/{class_.id}/thread/lecture",
        json={"assistant_id": 1, "parties": [123]},
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )
    assert create_response.status_code == 200
    thread_id = create_response.json()["thread"]["id"]
    await grant_thread_permissions(config, thread_id, 123)

    response = api.get(
        f"/api/v1/class/{class_.id}/thread/{thread_id}/lecture-video/narration/{question.intro_narration.id}",
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )
    assert response.status_code == 404


@with_institution(11, "Test Institution")
@with_authz(
    grants=[
        ("anonymous_user:anon-session-token", "can_view", "thread:109"),
        ("anonymous_user:anon-session-token", "can_participate", "thread:109"),
    ]
)
async def test_get_thread_video_with_anonymous_query_token(
    api, db, institution, config, monkeypatch, tmp_path
):
    video_key = "lecture-video.mp4"
    video_bytes = b"anonymous-video-bytes"
    (tmp_path / video_key).write_bytes(video_bytes)
    monkeypatch.setattr(
        config,
        "video_store",
        LocalVideoStoreSettings(type="local", save_target=str(tmp_path)),
    )

    async with db.async_session() as session:
        class_ = models.Class(
            id=1,
            name="Test Class",
            institution_id=institution.id,
        )
        session.add(class_)
        await session.flush()

        lecture_video = make_lecture_video(
            class_.id,
            video_key,
            filename="Test Video.mp4",
            content_length=len(video_bytes),
        )
        session.add(lecture_video)
        await session.flush()

        assistant = models.Assistant(
            id=1,
            name="Lecture Assistant",
            class_id=class_.id,
            interaction_mode=schemas.InteractionMode.LECTURE_VIDEO,
            version=3,
            lecture_video_id=lecture_video.id,
        )
        session.add(assistant)
        await session.flush()

        thread = models.Thread(
            id=109,
            name="Lecture Presentation",
            version=3,
            thread_id="thread-video-109",
            class_id=class_.id,
            assistant_id=assistant.id,
            interaction_mode=schemas.InteractionMode.LECTURE_VIDEO,
            lecture_video_id=lecture_video.id,
            private=True,
            tools_available="[]",
        )
        session.add(thread)
        await session.flush()

        anon_link = models.AnonymousLink(
            id=1,
            share_token="anon-share-token",
            active=True,
        )
        session.add(anon_link)
        await session.flush()

        anon_user = models.User(
            id=999,
            email="anon-user@test.org",
            anonymous_link_id=anon_link.id,
        )
        session.add(anon_user)
        await session.flush()

        anon_session = models.AnonymousSession(
            session_token="anon-session-token",
            thread_id=thread.id,
            user_id=anon_user.id,
        )
        session.add(anon_session)
        await session.commit()

    response = api.get(
        "/api/v1/class/1/thread/109/video?anonymous_session_token=anon-session-token",
    )
    assert response.status_code == 200
    assert response.content == video_bytes


@with_institution(11, "Test Institution")
@with_authz(
    grants=[
        ("anonymous_user:anon-session-token", "can_participate", "thread:109"),
    ]
)
async def test_get_thread_lecture_video_narration_with_anonymous_query_token(
    api, db, institution, config, monkeypatch, tmp_path
):
    narration_key = "intro-ready.mp3"
    narration_bytes = b"anonymous-intro-audio"
    (tmp_path / narration_key).write_bytes(narration_bytes)
    monkeypatch.setattr(
        config,
        "lecture_video_audio_store",
        LocalAudioStoreSettings(type="local", save_target=str(tmp_path)),
    )

    async with db.async_session() as session:
        class_, lecture_video, assistant = await create_ready_lecture_video_assistant(
            session,
            institution,
        )
        lecture_video = await models.LectureVideo.get_by_id_with_copy_context(
            session, lecture_video.id
        )
        question = lecture_video.questions[0]
        assert question.intro_narration is not None
        await attach_ready_narration(
            session,
            question.intro_narration,
            key=narration_key,
            content_length=len(narration_bytes),
        )

        thread = models.Thread(
            id=109,
            name="Lecture Presentation",
            version=assistant.version,
            thread_id="thread-video-109",
            class_id=class_.id,
            assistant_id=assistant.id,
            interaction_mode=schemas.InteractionMode.LECTURE_VIDEO,
            lecture_video_id=lecture_video.id,
            private=True,
            tools_available="[]",
        )
        session.add(thread)
        await session.flush()

        anon_link = models.AnonymousLink(
            id=1,
            share_token="anon-share-token",
            active=True,
        )
        session.add(anon_link)
        await session.flush()

        anon_user = models.User(
            id=999,
            email="anon-user@test.org",
            anonymous_link_id=anon_link.id,
        )
        session.add(anon_user)
        await session.flush()

        anon_session = models.AnonymousSession(
            session_token="anon-session-token",
            thread_id=thread.id,
            user_id=anon_user.id,
        )
        session.add(anon_session)
        await session.commit()

    response = api.get(
        f"/api/v1/class/1/thread/109/lecture-video/narration/{question.intro_narration.id}?anonymous_session_token=anon-session-token",
    )
    assert response.status_code == 200
    assert response.content == narration_bytes


@with_user(123)
@with_institution(11, "Test Institution")
@with_authz(
    grants=[
        ("user:123", "can_view", "thread:109"),
    ]
)
async def test_get_thread_video_with_lti_session_query_token(
    api, db, institution, valid_user_token, config, monkeypatch, tmp_path
):
    video_key = "lecture-video.mp4"
    video_bytes = b"lti-video-bytes"
    (tmp_path / video_key).write_bytes(video_bytes)
    monkeypatch.setattr(
        config,
        "video_store",
        LocalVideoStoreSettings(type="local", save_target=str(tmp_path)),
    )

    async with db.async_session() as session:
        class_ = models.Class(
            id=1,
            name="Test Class",
            institution_id=institution.id,
        )
        session.add(class_)
        await session.flush()

        lecture_video = make_lecture_video(
            class_.id,
            video_key,
            filename="Test Video.mp4",
            content_length=len(video_bytes),
        )
        session.add(lecture_video)
        await session.flush()

        assistant = models.Assistant(
            id=1,
            name="Lecture Assistant",
            class_id=class_.id,
            interaction_mode=schemas.InteractionMode.LECTURE_VIDEO,
            version=3,
            lecture_video_id=lecture_video.id,
        )
        session.add(assistant)
        await session.flush()

        thread = models.Thread(
            id=109,
            name="Lecture Presentation",
            version=3,
            thread_id="thread-video-109",
            class_id=class_.id,
            assistant_id=assistant.id,
            interaction_mode=schemas.InteractionMode.LECTURE_VIDEO,
            lecture_video_id=lecture_video.id,
            private=True,
            tools_available="[]",
        )
        session.add(thread)
        await session.commit()

    response = api.get(
        f"/api/v1/class/1/thread/109/video?lti_session={valid_user_token}",
    )
    assert response.status_code == 200
    assert response.content == video_bytes


@with_user(123)
@with_institution(11, "Test Institution")
@with_authz(
    grants=[
        ("user:123", "can_participate", "thread:109"),
    ]
)
async def test_get_thread_lecture_video_narration_with_lti_session_query_token(
    api, db, institution, valid_user_token, config, monkeypatch, tmp_path
):
    narration_key = "intro-ready.mp3"
    narration_bytes = b"lti-intro-audio"
    (tmp_path / narration_key).write_bytes(narration_bytes)
    monkeypatch.setattr(
        config,
        "lecture_video_audio_store",
        LocalAudioStoreSettings(type="local", save_target=str(tmp_path)),
    )

    async with db.async_session() as session:
        class_, lecture_video, assistant = await create_ready_lecture_video_assistant(
            session,
            institution,
        )
        lecture_video = await models.LectureVideo.get_by_id_with_copy_context(
            session, lecture_video.id
        )
        question = lecture_video.questions[0]
        assert question.intro_narration is not None
        await attach_ready_narration(
            session,
            question.intro_narration,
            key=narration_key,
            content_length=len(narration_bytes),
        )

        thread = models.Thread(
            id=109,
            name="Lecture Presentation",
            version=assistant.version,
            thread_id="thread-video-109",
            class_id=class_.id,
            assistant_id=assistant.id,
            interaction_mode=schemas.InteractionMode.LECTURE_VIDEO,
            lecture_video_id=lecture_video.id,
            private=True,
            tools_available="[]",
        )
        session.add(thread)
        await session.commit()

    response = api.get(
        f"/api/v1/class/1/thread/109/lecture-video/narration/{question.intro_narration.id}?lti_session={valid_user_token}",
    )
    assert response.status_code == 200
    assert response.content == narration_bytes


@with_user(123)
@with_institution(11, "Test Institution")
@with_authz(
    grants=[
        ("user:123", "can_view", "thread:109"),
    ]
)
async def test_get_thread_video_rejects_assistant_mismatch(
    api, db, institution, valid_user_token, config, monkeypatch, tmp_path
):
    (tmp_path / "thread-video.mp4").write_bytes(b"thread-video")
    (tmp_path / "assistant-video.mp4").write_bytes(b"assistant-video")
    monkeypatch.setattr(
        config,
        "video_store",
        LocalVideoStoreSettings(type="local", save_target=str(tmp_path)),
    )

    async with db.async_session() as session:
        class_ = models.Class(
            id=1,
            name="Test Class",
            institution_id=institution.id,
            api_key="test-key",
        )
        session.add(class_)
        await session.flush()

        thread_video = make_lecture_video(
            class_.id,
            "thread-video.mp4",
            filename="Thread Video.mp4",
        )
        assistant_video = make_lecture_video(
            class_.id,
            "assistant-video.mp4",
            filename="Assistant Video.mp4",
        )
        session.add(thread_video)
        session.add(assistant_video)
        await session.flush()

        assistant = models.Assistant(
            id=1,
            name="Lecture Assistant",
            class_id=class_.id,
            interaction_mode=schemas.InteractionMode.LECTURE_VIDEO,
            version=3,
            model="gpt-4o",
            lecture_video_id=assistant_video.id,
        )
        session.add(assistant)
        await session.flush()

        thread = models.Thread(
            id=109,
            name="Lecture Presentation",
            version=3,
            thread_id="thread-video-109",
            class_id=class_.id,
            assistant_id=assistant.id,
            interaction_mode=schemas.InteractionMode.LECTURE_VIDEO,
            lecture_video_id=thread_video.id,
            private=True,
            tools_available="[]",
        )
        session.add(thread)
        await session.commit()

    video_response = api.get(
        "/api/v1/class/1/thread/109/video",
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )
    assert video_response.status_code == 409
    assert (
        video_response.json()["detail"]
        == "This thread's lecture video no longer matches the assistant configuration."
    )

    thread_response = api.get(
        "/api/v1/class/1/thread/109",
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )
    assert thread_response.status_code == 200
    assert thread_response.json()["lecture_video_matches_assistant"] is False
