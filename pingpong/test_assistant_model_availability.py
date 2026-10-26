import importlib
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from pingpong import models, schemas

server = importlib.import_module("pingpong.server")

UNAVAILABLE_MESSAGE = "The selected model is not available. Select an available model before saving the assistant."


def provider_client(model_ids):
    return SimpleNamespace(
        models=SimpleNamespace(
            list=AsyncMock(
                return_value=SimpleNamespace(
                    data=[
                        SimpleNamespace(id=model_id, created=1, owned_by="openai")
                        for model_id in model_ids
                    ]
                )
            )
        )
    )


def editor_request(session):
    return SimpleNamespace(
        state={
            "db": session,
            "session": SimpleNamespace(user=SimpleNamespace(id=123)),
            "authz": SimpleNamespace(
                test=AsyncMock(return_value=True),
                check=AsyncMock(return_value=[True]),
                write=AsyncMock(),
                write_safe=AsyncMock(),
            ),
        }
    )


@pytest.mark.parametrize("mode", list(schemas.InteractionMode))
@pytest.mark.parametrize("model_field", ["same", "omitted", "null", "replacement"])
@pytest.mark.parametrize("available", [False, True])
async def test_save_checks_current_model_even_when_unchanged(
    db, mode, model_field, available
):
    model_id = (
        "gpt-4o-realtime-preview" if mode == schemas.InteractionMode.VOICE else "gpt-4o"
    )
    replacement = (
        "gpt-realtime-2.1" if mode == schemas.InteractionMode.VOICE else "gpt-5.6-terra"
    )
    selected_model = replacement if model_field == "replacement" else model_id
    client = provider_client([selected_model] if available else [])
    async with db.async_session() as session:
        user = models.User(
            id=123, email="editor@example.test", state=schemas.UserState.VERIFIED
        )
        group = models.Class(id=1, name="Model availability")
        assistant = models.Assistant(
            id=1,
            name="Existing assistant",
            instructions="Be helpful.",
            description="Test assistant",
            model=model_id,
            interaction_mode=mode,
            class_id=1,
            creator_id=123,
            tools="[]",
            version=3,
        )
        session.add_all([user, group, assistant])
        await session.commit()

    payload = {"name": "Updated assistant"}
    if model_field != "omitted":
        payload["model"] = selected_model if model_field != "null" else None
    async with db.async_session() as session:
        request = editor_request(session)
        assistant = await server.get_bound_assistant_for_edit(request, "1", "1")
        if available:
            await server.update_assistant(
                "1",
                "1",
                schemas.UpdateAssistant.model_validate(payload),
                request,
                assistant,
                client,
            )
            await session.commit()
        else:
            with pytest.raises(HTTPException) as raised:
                await server.update_assistant(
                    "1",
                    "1",
                    schemas.UpdateAssistant.model_validate(payload),
                    request,
                    assistant,
                    client,
                )
            assert raised.value.status_code == 400
            assert raised.value.detail == UNAVAILABLE_MESSAGE
            await session.rollback()
    client.models.list.assert_awaited_once()
    async with db.async_session() as session:
        saved = await session.get(models.Assistant, 1)
        assert saved.name == (
            "Updated assistant" if available else "Existing assistant"
        )
        assert saved.model == (selected_model if available else model_id)


@pytest.mark.parametrize("model_id", ["gpt-4o", "gpt-4o-mini", "unknown-model"])
async def test_create_rejects_models_missing_from_provider(db, model_id):
    client = provider_client([])
    async with db.async_session() as session:
        with pytest.raises(HTTPException) as raised:
            await server.create_assistant(
                "1",
                schemas.CreateAssistant(
                    name="New assistant",
                    description="Test assistant",
                    instructions="Be helpful.",
                    model=model_id,
                ),
                editor_request(session),
                client,
            )
        assert raised.value.status_code == 400
        assert raised.value.detail == UNAVAILABLE_MESSAGE
        assert await session.scalar(select(models.Assistant.id)) is None
    client.models.list.assert_awaited_once()
