import importlib
from types import SimpleNamespace

from fastapi import Response

from pingpong import (
    lecture_slide_processing,
    lecture_video_manifest_generation,
    models,
)
from .testutil import with_authz, with_institution, with_user

server_module = importlib.import_module("pingpong.server")


async def _create_class(db, institution_id: int) -> None:
    async with db.async_session() as session:
        session.add(
            models.Class(
                id=1,
                name="Lecture Lesson Editor Config",
                institution_id=institution_id,
            )
        )
        await session.commit()


async def test_lecture_lesson_editor_config_returns_current_defaults(monkeypatch):
    async def fake_lecture_video_provider_flags(_session, _class_id):
        return {
            "has_gemini_credential": True,
            "has_elevenlabs_credential": True,
            "lecture_video_enabled": True,
        }

    monkeypatch.setattr(
        server_module,
        "_get_class_lecture_video_provider_flags",
        fake_lecture_video_provider_flags,
    )
    request = SimpleNamespace(state={"db": object()})

    response = await server_module.get_class_lecture_lesson_editor_config(
        class_id="1",
        request=request,
        response=Response(),
    )

    assert response is not None
    assert response.lecture_lesson_available is True
    assert (
        response.instructions
        == lecture_video_manifest_generation.DEFAULT_LECTURE_VIDEO_INSTRUCTIONS
    )
    assert (
        response.generation_prompt
        == lecture_video_manifest_generation.DEFAULT_GENERATION_PROMPT_CONTENT
    )
    assert response.can_generate_manifest is True
    assert (
        response.lecture_slides_instructions
        == lecture_slide_processing.DEFAULT_LECTURE_SLIDE_INSTRUCTIONS
    )
    assert (
        response.lecture_slide_generation_prompt
        == lecture_slide_processing.DEFAULT_GENERATION_PROMPT_CONTENT
    )
    assert (
        response.lecture_slide_narration_prompt
        == lecture_slide_processing.DEFAULT_NARRATION_PROMPT
    )


async def test_lecture_lesson_editor_config_reports_when_providers_are_not_ready(
    monkeypatch,
):
    async def fake_lecture_video_provider_flags(_session, _class_id):
        return {
            "has_gemini_credential": False,
            "has_elevenlabs_credential": False,
            "lecture_video_enabled": False,
        }

    monkeypatch.setattr(
        server_module,
        "_get_class_lecture_video_provider_flags",
        fake_lecture_video_provider_flags,
    )
    request = SimpleNamespace(state={"db": object()})

    response = await server_module.get_class_lecture_lesson_editor_config(
        class_id="1",
        request=request,
        response=Response(),
    )

    assert response.lecture_lesson_available is False
    assert (
        response.instructions
        == lecture_video_manifest_generation.DEFAULT_LECTURE_VIDEO_INSTRUCTIONS
    )
    assert response.can_generate_manifest is False


@with_user(123)
@with_institution(11, "Test Institution")
@with_authz(grants=[("user:123", "can_view", "class:1")])
async def test_lecture_lesson_editor_config_endpoint_serializes_config(
    api,
    db,
    institution,
    valid_user_token,
):
    await _create_class(db, institution.id)

    response = api.get(
        "/api/v1/class/1/lecture-lesson/editor-config",
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )

    assert response.status_code == 200
    assert response.headers["cache-control"] == "private, no-store"
    assert response.json() == {
        "lecture_lesson_available": False,
        "instructions": (
            lecture_video_manifest_generation.DEFAULT_LECTURE_VIDEO_INSTRUCTIONS
        ),
        "generation_prompt": (
            lecture_video_manifest_generation.DEFAULT_GENERATION_PROMPT_CONTENT
        ),
        "can_generate_manifest": False,
        "lecture_slides_instructions": (
            lecture_slide_processing.DEFAULT_LECTURE_SLIDE_INSTRUCTIONS
        ),
        "lecture_slide_generation_prompt": (
            lecture_slide_processing.DEFAULT_GENERATION_PROMPT_CONTENT
        ),
        "lecture_slide_narration_prompt": (
            lecture_slide_processing.DEFAULT_NARRATION_PROMPT
        ),
    }
