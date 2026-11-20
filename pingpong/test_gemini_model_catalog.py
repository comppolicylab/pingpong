import importlib
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from google import genai
from google.genai import types

from . import gemini_model_catalog as google_catalog, model_catalog, models, schemas
from .test_model_catalog import install_memory_cache, provider_client
from .testutil import with_authz, with_institution, with_user

server = importlib.import_module("pingpong.server")


@pytest.fixture
def provider(monkeypatch):
    calls = []
    credentials = SimpleNamespace(
        api_key_obj=SimpleNamespace(id=21, api_key="synthetic-google-secret")
    )
    monkeypatch.setattr(
        models.ClassCredential,
        "get_by_class_id_and_purpose",
        AsyncMock(return_value=credentials),
    )
    items = [
        types.Model(
            name="models/gemini-4-hydrogen", supported_actions=["generateContent"]
        ),
        types.Model(
            name="models/gemini-4-carbon", supported_actions=["generateContent"]
        ),
        types.Model(name="models/gemini-3.8-flash", supported_actions=["embedContent"]),
        types.Model(name="models/unknown-model", supported_actions=["generateContent"]),
        types.Model(name=None, supported_actions=["generateContent"]),
    ]

    class FakeModels:
        async def list(self):
            calls.append(credentials.api_key_obj.id)

            async def pages():
                for item in items:
                    yield item

            return pages()

    class FakeClient:
        def __init__(self, **kwargs):
            self.aio = self
            self.models = FakeModels()

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

    monkeypatch.setattr(google_catalog.genai, "Client", FakeClient)
    return calls, credentials


async def test_google_catalog_uses_provider_inventory_and_normalizes_names(provider):
    calls, _ = provider
    result = await google_catalog.list_class_generation_models(object(), 1)
    assert [model.id for model in result.models] == [
        "gemini-4-hydrogen",
        "gemini-4-carbon",
    ]
    assert result.models[0].name == "Gemini 4 Hydrogen"
    assert result.default_model.id == "gemini-4-hydrogen"
    assert calls == [21]


async def test_missing_google_credential_does_not_query_provider(provider, monkeypatch):
    calls, _ = provider
    monkeypatch.setattr(
        models.ClassCredential,
        "get_by_class_id_and_purpose",
        AsyncMock(return_value=None),
    )
    result = await google_catalog.list_class_generation_models(object(), 1)
    assert result.models == []
    assert result.default_model.id == "gemini-4-hydrogen"
    assert calls == []


async def test_google_catalog_reuses_cache_and_isolates_credentials(
    provider, config, monkeypatch
):
    calls, credential = provider
    redis = install_memory_cache(config, monkeypatch)
    first = await google_catalog.list_class_generation_models(object(), 1)
    second = await google_catalog.list_class_generation_models(object(), 2)
    assert first == second
    assert calls == [21]
    credential.api_key_obj.id = 22
    await google_catalog.list_class_generation_models(object(), 2)
    assert calls == [21, 22]
    # Even matching credential IDs cannot collide with OpenAI inventories.
    openai_inventory = await model_catalog.get_model_catalog(
        provider_client("gpt-test", key_id=22)
    )
    assert [item.id for item in openai_inventory.models] == ["gpt-test"]
    assert "synthetic-google-secret" not in str(redis.values)
    await model_catalog.reset_model_catalog_cache()
    await google_catalog.list_class_generation_models(object(), 2)
    assert calls == [21, 22, 22]


async def test_google_provider_errors_do_not_cache_invented_availability(
    provider, monkeypatch
):
    async def fail(_self):
        raise genai.errors.ClientError(403, {"error": {"message": "private details"}})

    monkeypatch.setattr(google_catalog._GeminiCatalogModels, "list", fail)
    with pytest.raises(HTTPException) as exc:
        await google_catalog.list_class_generation_models(object(), 1)
    assert exc.value.status_code == 502
    assert "private details" not in exc.value.detail


async def test_google_model_save_validation_uses_inventory(provider):
    request = SimpleNamespace(state={"db": object()})
    await server._validate_lecture_gemini_model(request, "1", "gemini-4-carbon")
    with pytest.raises(HTTPException) as exc:
        await server._validate_lecture_gemini_model(request, "1", "gemini-3.8-flash")
    assert exc.value.status_code == 400


@with_user(123)
@with_institution(11, "Test Institution")
@with_authz(grants=[("user:123", "can_view", "class:1")])
async def test_google_model_endpoint(api, db, provider, institution, valid_user_token):
    async with db.async_session() as session:
        session.add(
            models.Class(id=1, name="Google Models", institution_id=institution.id)
        )
        await session.commit()
    response = api.get(
        "/api/v1/class/1/gemini/models",
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )
    assert response.status_code == 200
    assert response.headers["cache-control"] == "private, no-store"
    body = response.json()
    assert body["default_model"]["id"] == "gemini-4-hydrogen"
    assert [item["id"] for item in body["models"]] == [
        "gemini-4-hydrogen",
        "gemini-4-carbon",
    ]


@with_user(123)
@with_institution(11, "Test Institution")
@with_authz(grants=[])
async def test_google_model_endpoint_requires_class_access(
    api, db, provider, institution, valid_user_token
):
    async with db.async_session() as session:
        session.add(
            models.Class(id=1, name="Google Models", institution_id=institution.id)
        )
        await session.commit()
    response = api.get(
        "/api/v1/class/1/gemini/models",
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )
    assert response.status_code == 403
    assert provider[0] == []


@pytest.mark.parametrize(
    "saved_google,saved_generation,updates,expected",
    [
        (None, None, {}, (False, False)),
        (
            "gemini-3.6-flash",
            None,
            {"lecture_gemini_model": "gemini-3.6-flash"},
            (False, False),
        ),
        (
            "gemini-3.6-flash",
            None,
            {"lecture_gemini_model": "gemini-4-hydrogen"},
            (True, False),
        ),
        (
            "gemini-4-hydrogen",
            None,
            {"lecture_gemini_model": "gemini-4-hydrogen"},
            (False, False),
        ),
        (None, None, {"lecture_generation_model": "chat-b"}, (False, True)),
        (None, None, {"model": "chat-b"}, (False, True)),
        (None, "chat-a", {"model": "chat-b"}, (False, False)),
        (None, None, {"lecture_generation_model": "chat-a"}, (False, False)),
    ],
)
def test_only_effective_material_model_changes_trigger_regeneration(
    saved_google, saved_generation, updates, expected
):
    assistant = SimpleNamespace(
        model="chat-a",
        lecture_gemini_model=saved_google,
        lecture_generation_model=saved_generation,
    )
    assert (
        server._lecture_material_model_changes(
            assistant, schemas.UpdateAssistant(**updates)
        )
        == expected
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
@pytest.mark.parametrize(
    "selected_model,should_regenerate",
    [
        ("gemini-3.6-flash", False),
        ("gemini-4-hydrogen", True),
    ],
)
async def test_model_only_video_save_preserves_legacy_or_regenerates(
    api,
    db,
    institution,
    valid_user_token,
    monkeypatch,
    selected_model,
    should_regenerate,
):
    from sqlalchemy import select
    from .test_lecture_video_server import (
        DEFAULT_LECTURE_VIDEO_VOICE_ID,
        create_lecture_video_copy_credentials,
        lecture_video_manifest,
        make_lecture_video,
        patch_lecture_video_model_list,
    )

    patch_lecture_video_model_list(monkeypatch)
    monkeypatch.setattr(server, "_validate_lecture_gemini_model", AsyncMock())
    monkeypatch.setattr(
        server,
        "synthesize_elevenlabs_voice_sample",
        AsyncMock(return_value=("Sample phrase", "audio/ogg", b"fake-audio")),
    )
    async with db.async_session() as session:
        class_ = models.Class(
            id=1,
            name="Material Models",
            institution_id=institution.id,
            api_key="sk-test",
        )
        video = make_lecture_video(
            1, "model-selection.mp4", status=schemas.LectureVideoStatus.UPLOADED.value
        )
        session.add_all([class_, video])
        await create_lecture_video_copy_credentials(session, 1)
        await session.commit()
        await session.refresh(video)
        video_id = video.id

    headers = {"Authorization": f"Bearer {valid_user_token}"}
    created = api.post(
        "/api/v1/class/1/assistant",
        json={
            "name": "Lecture Assistant",
            "instructions": "Guide the learner through the lecture.",
            "description": "Lecture presentation assistant",
            "interaction_mode": "lecture_video",
            "model": "gpt-4o-mini",
            "tools": [],
            "lecture_video_id": video_id,
            "lecture_video_manifest": lecture_video_manifest(),
            "voice_id": DEFAULT_LECTURE_VIDEO_VOICE_ID,
            "overwrite_manifest": True,
        },
        headers=headers,
    )
    assert created.status_code == 200
    assert created.json()["lecture_gemini_model"] == "gemini-4-hydrogen"
    async with db.async_session() as session:
        assistant = await session.get(models.Assistant, 1)
        assistant.lecture_gemini_model = "gemini-3.6-flash"
        video = await session.get(models.LectureVideo, video_id)
        video.manual_manifest = False
        video.status = schemas.LectureVideoStatus.READY
        await session.commit()

    updated = api.put(
        "/api/v1/class/1/assistant/1",
        json={
            "lecture_gemini_model": selected_model,
        },
        headers=headers,
    )
    assert updated.status_code == 200, updated.text
    new_video_id = updated.json()["lecture_video"]["id"]
    assert (new_video_id != video_id) is should_regenerate
    if should_regenerate:
        async with db.async_session() as session:
            run = await session.scalar(
                select(models.LectureVideoProcessingRun).where(
                    models.LectureVideoProcessingRun.lecture_video_id == new_video_id,
                    models.LectureVideoProcessingRun.stage
                    == schemas.LectureVideoProcessingStage.MANIFEST_GENERATION,
                )
            )
            assert run is not None
            assert run.status == schemas.LectureVideoProcessingRunStatus.QUEUED


def test_migration_pins_existing_video_material_to_gemini_36():
    from pathlib import Path
    import sqlalchemy as sa
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    path = (
        Path(__file__).parents[1]
        / "alembic/versions/a7c942e31b08_add_lecture_generation_models.py"
    )
    spec = importlib.util.spec_from_file_location("lecture_model_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = sa.create_engine("sqlite://")
    with engine.begin() as connection:
        connection.execute(
            sa.text("CREATE TABLE assistants (id INTEGER, interaction_mode VARCHAR)")
        )
        connection.execute(
            sa.text("INSERT INTO assistants VALUES (1, 'LECTURE_VIDEO'), (2, 'CHAT')")
        )
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
        assert connection.execute(
            sa.text("SELECT lecture_gemini_model FROM assistants ORDER BY id")
        ).scalars().all() == ["gemini-3.6-flash", None]


@pytest.mark.parametrize(
    "current_model,available,allowed",
    [
        ("saved-model", True, True),
        (None, True, False),
        ("saved-model", False, False),
    ],
)
async def test_material_model_validation_matches_retained_model_policy(
    current_model, available, allowed
):
    record = SimpleNamespace(
        id="saved-model",
        is_available=available,
        hide_in_model_selector=True,
        type=schemas.InteractionMode.CHAT,
        supports_next_gen_assistants=True,
    )

    async def validate():
        await server._validate_lecture_generation_model(
            SimpleNamespace(state={}),
            "1",
            "saved-model",
            [record],
            current_model=current_model,
        )

    if allowed:
        await validate()
    else:
        with pytest.raises(HTTPException) as exc:
            await validate()
        assert exc.value.status_code == 400
