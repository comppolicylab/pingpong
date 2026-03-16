import importlib
import io
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from typing import Literal
from unittest.mock import AsyncMock

import pytest
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
    lecture_video_runtime,
    lecture_video_service,
    models,
)
from pingpong.animal_hash import pseudonym
from pingpong.authz.openfga import OpenFgaAuthzClient
from pingpong.config import LocalAudioStoreSettings, LocalVideoStoreSettings

from .testutil import with_authz, with_institution, with_user

DEFAULT_LECTURE_VIDEO_VOICE_ID = "voice-test-id"
server_module = importlib.import_module("pingpong.server")


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


async def attach_ready_narration(
    session,
    narration: models.LectureVideoNarration,
    *,
    key: str,
    content_type: str = "audio/mpeg",
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
    assert [item["event_index"] for item in history] == [1, 2, 3, 4]
    assert [item["event_type"] for item in history] == [
        "session_initialized",
        "question_presented",
        "answer_submitted",
        "video_resumed",
    ]
    assert history[1]["actor_name"] == "Me"
    assert history[2]["question_text"] == questions[0].question_text
    assert history[2]["option_text"] == options[questions[0].id][0].option_text


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
    completed_session = resume_response.json()["lecture_video_session"]
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
    assert [item["event_type"] for item in history_response.json()["interactions"]] == [
        "session_initialized",
        "question_presented",
        "answer_submitted",
        "video_resumed",
        "session_completed",
    ]


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

    seek_response = api.post(
        f"/api/v1/class/{class_.id}/thread/{thread_id}/lecture-video/interactions",
        json={
            "type": "video_seeked",
            "controller_session_id": controller_session_id,
            "expected_state_version": state_version,
            "idempotency_key": "seek-forward",
            "from_offset_ms": 250,
            "to_offset_ms": 1250,
        },
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )
    assert seek_response.status_code == 200
    assert seek_response.json()["lecture_video_session"]["last_known_offset_ms"] == 1250

    end_response = api.post(
        f"/api/v1/class/{class_.id}/thread/{thread_id}/lecture-video/interactions",
        json={
            "type": "video_ended",
            "controller_session_id": controller_session_id,
            "expected_state_version": seek_response.json()["lecture_video_session"][
                "state_version"
            ],
            "idempotency_key": "ended-once",
            "offset_ms": 9000,
        },
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )
    assert end_response.status_code == 200
    ended_session = end_response.json()["lecture_video_session"]
    assert ended_session["last_known_offset_ms"] == 9000
    assert ended_session["state"] == "playing"

    history_response = api.get(
        f"/api/v1/class/{class_.id}/thread/{thread_id}/lecture-video/history",
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )
    assert history_response.status_code == 200
    history = history_response.json()["interactions"]
    assert [item["event_type"] for item in history] == [
        "session_initialized",
        "video_seeked",
        "video_ended",
    ]
    assert history[1]["from_offset_ms"] == 250
    assert history[1]["to_offset_ms"] == 1250
    assert history[2]["offset_ms"] == 9000


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

    async with db.async_session() as session:
        class_, _lecture_video, _assistant = await create_ready_lecture_video_assistant(
            session,
            institution,
        )
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

    my_pause = api.post(
        f"/api/v1/class/{class_.id}/thread/{thread_id}/lecture-video/interactions",
        json={
            "type": "video_paused",
            "controller_session_id": my_controller_session_id,
            "expected_state_version": my_state_version,
            "idempotency_key": "my-pause",
            "offset_ms": 500,
        },
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )
    assert my_pause.status_code == 200

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

    other_pause = api.post(
        f"/api/v1/class/{class_.id}/thread/{thread_id}/lecture-video/interactions",
        json={
            "type": "video_paused",
            "controller_session_id": other_controller_session_id,
            "expected_state_version": other_state_version,
            "idempotency_key": "other-pause",
            "offset_ms": 750,
        },
        headers={"Authorization": f"Bearer {other_user_token}"},
    )
    assert other_pause.status_code == 200

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
        "session_initialized",
        "video_paused",
        "video_paused",
    ]
    assert history[1]["actor_name"] == "Me"
    assert history[2]["actor_name"] == pseudonym(thread, users[456])


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
    assert body["lecture_video"]["status"] == schemas.LectureVideoStatus.READY.value
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

    assert refreshed_video is not None
    assert refreshed_video.status == schemas.LectureVideoStatus.READY.value
    assert refreshed_video.voice_id == DEFAULT_LECTURE_VIDEO_VOICE_ID
    assert question_count == 1
    assert option_count == 2
    assert single_select_correct_option_count == 1
    assert narration_count == 0


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
@with_authz(grants=[("user:123", "can_create_assistants", "class:1")])
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
    assert updated_video.voice_id == "voice-updated"
    assert original_video.voice_id == DEFAULT_LECTURE_VIDEO_VOICE_ID
    assert original_question == "Original question?"
    assert updated_question == "Updated question?"


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

    async def fake_get_openai_client_for_class():
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
        api.app.dependency_overrides.clear()

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

    async def fake_get_openai_client_for_class():
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
        api.app.dependency_overrides.clear()

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
    assert response.headers["content-type"].startswith("audio/mpeg")

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
