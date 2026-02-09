from datetime import datetime, timezone
import importlib
from types import SimpleNamespace
from unittest.mock import AsyncMock

from sqlalchemy import select
from sqlalchemy.orm import selectinload
from starlette.datastructures import State

from pingpong.ai_models import KNOWN_MODELS
from pingpong import models
import pingpong.schemas as schemas
from pingpong.realtime import add_message_to_thread
from pingpong.testutil import with_authz, with_user


@with_user(123)
@with_authz(grants=[("user:123", "can_create_thread", "class:1")])
async def test_create_audio_thread_supports_version_3_assistant(
    api, db, valid_user_token
):
    async with db.async_session() as session:
        class_ = models.Class(
            id=1,
            name="Voice Class",
            term="Spring 2026",
            api_key="sk-test",
            private=False,
        )
        assistant = models.Assistant(
            id=11,
            name="Voice V3 Assistant",
            version=3,
            instructions="You are a voice assistant.",
            interaction_mode=schemas.InteractionMode.VOICE,
            description="Voice assistant",
            tools="[]",
            model="gpt-4o-mini",
            class_id=class_.id,
            creator_id=123,
            use_latex=False,
            use_image_descriptions=False,
            should_record_user_information=False,
        )
        session.add_all([class_, assistant])
        await session.commit()

    response = api.post(
        "/api/v1/class/1/thread/audio",
        json={"assistant_id": 11},
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )
    assert response.status_code == 200
    response_data = response.json()
    assert response_data["thread"]["version"] == 3
    assert response_data["thread"]["interaction_mode"] == "voice"

    async with db.async_session() as session:
        created_thread = await models.Thread.get_by_id(
            session, int(response_data["thread"]["id"])
        )
        assert created_thread is not None
        assert created_thread.version == 3
        assert created_thread.thread_id is None
        assert created_thread.interaction_mode == schemas.InteractionMode.VOICE


@with_user(123)
async def test_add_message_to_thread_persists_version_3_voice_messages(db, user):
    mock_threads_messages_create = AsyncMock()
    openai_client = SimpleNamespace(
        beta=SimpleNamespace(
            threads=SimpleNamespace(
                messages=SimpleNamespace(create=mock_threads_messages_create)
            )
        )
    )

    async with db.async_session() as session:
        class_ = models.Class(
            id=1,
            name="Voice Class",
            term="Spring 2026",
            api_key="sk-test",
            private=False,
        )
        assistant = models.Assistant(
            id=11,
            name="Voice V3 Assistant",
            version=3,
            instructions="You are a voice assistant.",
            interaction_mode=schemas.InteractionMode.VOICE,
            description="Voice assistant",
            tools="[]",
            model="gpt-4o-mini",
            class_id=class_.id,
            creator_id=123,
            use_latex=False,
            use_image_descriptions=False,
        )
        thread = models.Thread(
            id=21,
            class_id=class_.id,
            assistant_id=assistant.id,
            version=3,
            interaction_mode=schemas.InteractionMode.VOICE,
            tools_available="[]",
            private=False,
            user_message_ct=0,
            instructions="voice instructions",
        )

        session.add_all([class_, assistant, thread])
        await session.flush()

        browser_connection = SimpleNamespace(
            state=State(
                {
                    "db": session,
                    "session": SimpleNamespace(user=SimpleNamespace(id=123)),
                    "assistant": assistant,
                    "conversation_instructions": "voice instructions with timestamp",
                }
            )
        )

        await add_message_to_thread(
            openai_client,  # type: ignore[arg-type]
            browser_connection,  # type: ignore[arg-type]
            thread,
            item_id="item-user-1",
            transcript_text="hello from user",
            role="user",
            output_index="0",
        )
        await add_message_to_thread(
            openai_client,  # type: ignore[arg-type]
            browser_connection,  # type: ignore[arg-type]
            thread,
            item_id="item-assistant-1",
            transcript_text="hello from assistant",
            role="assistant",
            output_index="1",
        )

        runs = (
            (
                await session.execute(
                    select(models.Run).where(models.Run.thread_id == thread.id)
                )
            )
            .scalars()
            .all()
        )
        assert len(runs) == 1
        assert runs[0].status == schemas.RunStatus.COMPLETED
        assert browser_connection.state["voice_mode_run_id"] == runs[0].id

        messages = (
            (
                await session.execute(
                    select(models.Message)
                    .where(models.Message.thread_id == thread.id)
                    .order_by(models.Message.output_index.asc())
                    .options(selectinload(models.Message.content))
                )
            )
            .scalars()
            .all()
        )
        assert len(messages) == 2
        assert [message.output_index for message in messages] == [0, 1]
        assert [message.message_id for message in messages] == [
            "item-user-1",
            "item-assistant-1",
        ]
        assert [message.role for message in messages] == [
            schemas.MessageRole.USER,
            schemas.MessageRole.ASSISTANT,
        ]
        assert messages[0].run_id == runs[0].id
        assert messages[1].run_id == runs[0].id
        assert thread.user_message_ct == 1

        assert len(messages[0].content) == 1
        assert messages[0].content[0].type == schemas.MessagePartType.INPUT_TEXT
        assert messages[0].content[0].text == "hello from user"
        assert len(messages[1].content) == 1
        assert messages[1].content[0].type == schemas.MessagePartType.OUTPUT_TEXT
        assert messages[1].content[0].text == "hello from assistant"

    mock_threads_messages_create.assert_not_awaited()


def _fake_class_models_response(
    model_id: str = "gpt-4o-mini", model_type: str = "chat"
) -> dict:
    return {
        "models": [
            {
                "id": model_id,
                "created": datetime(2024, 1, 1, tzinfo=timezone.utc),
                "owner": "openai",
                "name": "GPT-4o mini",
                "description": "Test model",
                "type": model_type,
                "is_latest": True,
                "is_new": False,
                "highlight": False,
                "supports_classic_assistants": True,
                "supports_next_gen_assistants": True,
                "supports_minimal_reasoning_effort": False,
                "supports_none_reasoning_effort": False,
                "supports_verbosity": True,
                "supports_web_search": True,
                "supports_mcp_server": True,
                "supports_vision": True,
                "supports_file_search": True,
                "supports_code_interpreter": True,
                "supports_temperature": True,
                "supports_reasoning": False,
            }
        ],
        "default_prompts": [],
        "enforce_classic_assistants": False,
    }


def test_voice_model_capabilities_support_next_gen():
    voice_models = [
        model_name
        for model_name, model_info in KNOWN_MODELS.items()
        if model_info["type"] == "voice"
    ]
    assert voice_models
    assert all(
        KNOWN_MODELS[model_name]["supports_next_gen_assistants"]
        for model_name in voice_models
    )


@with_user(123)
@with_authz(grants=[("user:123", "can_edit", "assistant:11")])
async def test_update_assistant_keeps_classic_v2_by_default(
    api, db, valid_user_token, monkeypatch
):
    async def fake_list_class_models(class_id: str, request, openai_client):  # type: ignore[no-untyped-def]
        return _fake_class_models_response()

    server_module = importlib.import_module("pingpong.server")
    monkeypatch.setattr(server_module, "list_class_models", fake_list_class_models)

    async with db.async_session() as session:
        class_ = models.Class(
            id=1,
            name="Voice Class",
            term="Spring 2026",
            api_key="sk-test",
            private=False,
        )
        assistant = models.Assistant(
            id=11,
            name="Classic Assistant",
            version=2,
            instructions="You are a classic assistant.",
            interaction_mode=schemas.InteractionMode.CHAT,
            description="Classic assistant",
            tools="[]",
            model="gpt-4o-mini",
            class_id=class_.id,
            creator_id=123,
            use_latex=False,
            use_image_descriptions=False,
            locked=False,
        )
        session.add_all([class_, assistant])
        await session.commit()

    response = api.put(
        "/api/v1/class/1/assistant/11",
        json={"notes": "edited notes", "tools": None},
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )
    assert response.status_code == 200
    assert response.json()["version"] == 2

    async with db.async_session() as session:
        updated = await models.Assistant.get_by_id(session, 11)
        assert updated.version == 2


@with_user(123)
@with_authz(grants=[("user:123", "can_edit", "assistant:11")])
async def test_update_assistant_converts_to_next_gen_when_requested(
    api, db, valid_user_token, monkeypatch
):
    async def fake_list_class_models(class_id: str, request, openai_client):  # type: ignore[no-untyped-def]
        return _fake_class_models_response()

    server_module = importlib.import_module("pingpong.server")
    monkeypatch.setattr(server_module, "list_class_models", fake_list_class_models)

    async with db.async_session() as session:
        class_ = models.Class(
            id=1,
            name="Voice Class",
            term="Spring 2026",
            api_key="sk-test",
            private=False,
        )
        assistant = models.Assistant(
            id=11,
            name="Classic Assistant",
            version=2,
            instructions="You are a classic assistant.",
            interaction_mode=schemas.InteractionMode.CHAT,
            description="Classic assistant",
            tools="[]",
            model="gpt-4o-mini",
            class_id=class_.id,
            creator_id=123,
            use_latex=False,
            use_image_descriptions=False,
            locked=False,
        )
        session.add_all([class_, assistant])
        await session.commit()

    response = api.put(
        "/api/v1/class/1/assistant/11",
        json={"notes": "edited notes", "tools": None, "convert_to_next_gen": True},
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )
    assert response.status_code == 200
    assert response.json()["version"] == 3

    async with db.async_session() as session:
        updated = await models.Assistant.get_by_id(session, 11)
        assert updated.version == 3


@with_user(123)
@with_authz(grants=[("user:123", "can_edit", "assistant:11")])
async def test_update_voice_assistant_converts_to_next_gen_when_requested(
    api, db, valid_user_token, monkeypatch
):
    async def fake_list_class_models(class_id: str, request, openai_client):  # type: ignore[no-untyped-def]
        return _fake_class_models_response(model_type="voice")

    server_module = importlib.import_module("pingpong.server")
    monkeypatch.setattr(server_module, "list_class_models", fake_list_class_models)

    async with db.async_session() as session:
        class_ = models.Class(
            id=1,
            name="Voice Class",
            term="Spring 2026",
            api_key="sk-test",
            private=False,
        )
        assistant = models.Assistant(
            id=11,
            name="Voice Assistant",
            version=2,
            instructions="You are a voice assistant.",
            interaction_mode=schemas.InteractionMode.VOICE,
            description="Voice assistant",
            tools="[]",
            model="gpt-4o-mini",
            class_id=class_.id,
            creator_id=123,
            use_latex=False,
            use_image_descriptions=False,
            locked=False,
        )
        session.add_all([class_, assistant])
        await session.commit()

    response = api.put(
        "/api/v1/class/1/assistant/11",
        json={"notes": "edited notes", "tools": None, "convert_to_next_gen": True},
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )
    assert response.status_code == 200
    assert response.json()["version"] == 3

    async with db.async_session() as session:
        updated = await models.Assistant.get_by_id(session, 11)
        assert updated.version == 3


@with_user(123)
@with_authz(grants=[("user:123", "can_edit", "assistant:11")])
async def test_update_voice_assistant_switches_back_to_classic_when_requested(
    api, db, valid_user_token, monkeypatch
):
    async def fake_list_class_models(class_id: str, request, openai_client):  # type: ignore[no-untyped-def]
        return _fake_class_models_response(model_type="voice")

    server_module = importlib.import_module("pingpong.server")
    monkeypatch.setattr(server_module, "list_class_models", fake_list_class_models)

    async with db.async_session() as session:
        class_ = models.Class(
            id=1,
            name="Voice Class",
            term="Spring 2026",
            api_key="sk-test",
            private=False,
        )
        assistant = models.Assistant(
            id=11,
            name="Voice Assistant",
            version=3,
            instructions="You are a voice assistant.",
            interaction_mode=schemas.InteractionMode.VOICE,
            description="Voice assistant",
            tools="[]",
            model="gpt-4o-mini",
            class_id=class_.id,
            creator_id=123,
            use_latex=False,
            use_image_descriptions=False,
            locked=False,
        )
        session.add_all([class_, assistant])
        await session.commit()

    response = api.put(
        "/api/v1/class/1/assistant/11",
        json={"notes": "edited notes", "tools": None, "convert_to_next_gen": False},
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )
    assert response.status_code == 200
    assert response.json()["version"] == 2

    async with db.async_session() as session:
        updated = await models.Assistant.get_by_id(session, 11)
        assert updated.version == 2
