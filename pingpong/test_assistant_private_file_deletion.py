from datetime import datetime, timezone
import importlib

from sqlalchemy import insert

from pingpong import models
import pingpong.schemas as schemas
from pingpong.testutil import with_authz, with_user


def _fake_class_models_response(
    model_id: str = "gpt-4o-mini",
    model_type: str = "chat",
    *,
    model_name: str = "GPT-4o mini",
    sort_order: float = 1.0,
    supports_temperature: bool = True,
    supports_reasoning: bool = False,
    supports_none_reasoning_effort: bool = False,
    supports_tools_with_none_reasoning_effort: bool = False,
    supports_temperature_with_reasoning_none: bool = False,
    supports_classic_assistants: bool = True,
    supports_next_gen_assistants: bool = True,
) -> dict:
    return {
        "models": [
            {
                "id": model_id,
                "created": datetime(2024, 1, 1, tzinfo=timezone.utc),
                "owner": "openai",
                "name": model_name,
                "sort_order": sort_order,
                "description": "Test model",
                "type": model_type,
                "is_latest": True,
                "is_new": False,
                "highlight": False,
                "supports_classic_assistants": supports_classic_assistants,
                "supports_next_gen_assistants": supports_next_gen_assistants,
                "supports_minimal_reasoning_effort": False,
                "supports_none_reasoning_effort": supports_none_reasoning_effort,
                "supports_tools_with_none_reasoning_effort": supports_tools_with_none_reasoning_effort,
                "supports_verbosity": True,
                "supports_web_search": True,
                "supports_mcp_server": True,
                "supports_vision": True,
                "supports_file_search": True,
                "supports_code_interpreter": True,
                "supports_temperature": supports_temperature,
                "supports_temperature_with_reasoning_none": supports_temperature_with_reasoning_none,
                "supports_reasoning": supports_reasoning,
            }
        ],
        "default_prompts": [],
        "enforce_classic_assistants": False,
    }


@with_user(123)
@with_authz(grants=[("user:123", "can_edit", "assistant:11")])
async def test_update_assistant_rejects_deleting_file_used_by_other_assistant(
    api, db, valid_user_token, monkeypatch
):
    async def fake_list_class_models(class_id: str, request, openai_client):  # type: ignore[no-untyped-def]
        return _fake_class_models_response(
            model_id="gpt-5.4",
            model_name="GPT-5.4",
            supports_temperature=False,
            supports_reasoning=True,
            supports_none_reasoning_effort=True,
            supports_tools_with_none_reasoning_effort=True,
            supports_temperature_with_reasoning_none=True,
            supports_classic_assistants=False,
        )

    server_module = importlib.import_module("pingpong.server")
    monkeypatch.setattr(server_module, "list_class_models", fake_list_class_models)

    async with db.async_session() as session:
        uploader = models.User(id=999, email="uploader999@example.com")
        other_creator = models.User(id=456, email="creator456@example.com")
        class_ = models.Class(
            id=1,
            name="Chat Class",
            term="Spring 2026",
            api_key="sk-test",
            private=False,
        )
        assistant_to_update = models.Assistant(
            id=11,
            name="Assistant",
            instructions="You are helpful.",
            description="Assistant description",
            interaction_mode=schemas.InteractionMode.CHAT,
            model="gpt-5.4",
            class_id=class_.id,
            tools="[]",
            creator_id=123,
            published=None,
            version=3,
            locked=False,
        )
        other_assistant = models.Assistant(
            id=12,
            name="Other Assistant",
            instructions="You are helpful.",
            description="Assistant description",
            interaction_mode=schemas.InteractionMode.CHAT,
            model="gpt-5.4",
            class_id=class_.id,
            tools="[]",
            creator_id=456,
            published=None,
            version=3,
            locked=False,
        )
        session.add_all(
            [uploader, other_creator, class_, assistant_to_update, other_assistant]
        )
        await session.flush()
        file = await models.File.create(
            session,
            {
                "name": "Shared private upload",
                "content_type": "text/plain",
                "file_id": "file-used-elsewhere",
                "private": True,
                "uploader_id": 999,
                "class_id": class_.id,
            },
            class_.id,
        )
        await session.execute(
            insert(models.code_interpreter_file_assistant_association).values(
                assistant_id=other_assistant.id, file_id=file.id
            )
        )
        await session.commit()

    response = api.put(
        "/api/v1/class/1/assistant/11",
        json={
            "name": "Updated Assistant",
            "tools": [],
            "deleted_private_files": [file.id],
        },
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )
    assert response.status_code == 403
    assert "in use by assistants" in response.json()["detail"]

    async with db.async_session() as session:
        existing_file = await models.File.get_by_id(session, file.id)
        assert existing_file is not None


@with_user(123)
@with_authz(grants=[("user:123", "can_edit", "assistant:11")])
async def test_update_assistant_rejects_non_private_deleted_private_file(
    api, db, valid_user_token, monkeypatch
):
    async def fake_list_class_models(class_id: str, request, openai_client):  # type: ignore[no-untyped-def]
        return _fake_class_models_response(
            model_id="gpt-5.4",
            model_name="GPT-5.4",
            supports_temperature=False,
            supports_reasoning=True,
            supports_none_reasoning_effort=True,
            supports_tools_with_none_reasoning_effort=True,
            supports_temperature_with_reasoning_none=True,
            supports_classic_assistants=False,
        )

    server_module = importlib.import_module("pingpong.server")
    monkeypatch.setattr(server_module, "list_class_models", fake_list_class_models)

    async with db.async_session() as session:
        uploader = models.User(id=999, email="uploader999@example.com")
        class_ = models.Class(
            id=1,
            name="Chat Class",
            term="Spring 2026",
            api_key="sk-test",
            private=False,
        )
        assistant = models.Assistant(
            id=11,
            name="Assistant",
            instructions="You are helpful.",
            description="Assistant description",
            interaction_mode=schemas.InteractionMode.CHAT,
            model="gpt-5.4",
            class_id=class_.id,
            tools="[]",
            creator_id=123,
            published=None,
            version=3,
            locked=False,
        )
        session.add_all([uploader, class_, assistant])
        await session.flush()
        file = await models.File.create(
            session,
            {
                "name": "Class file",
                "content_type": "text/plain",
                "file_id": "public-file-123",
                "private": False,
                "uploader_id": 999,
                "class_id": class_.id,
            },
            class_.id,
        )
        await session.commit()

    response = api.put(
        "/api/v1/class/1/assistant/11",
        json={
            "name": "Updated Assistant",
            "tools": [],
            "deleted_private_files": [file.id],
        },
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )
    assert response.status_code == 400
    assert response.json()["detail"] == (
        f"File {file.id} is not a private file and cannot be deleted via this field."
    )
