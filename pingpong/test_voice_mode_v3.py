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


@with_user(123)
async def test_add_message_to_thread_skips_empty_transcript_for_version_3(db, user):
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
            transcript_text="   ",
            role="user",
            output_index="0",
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
        messages = (
            (
                await session.execute(
                    select(models.Message).where(models.Message.thread_id == thread.id)
                )
            )
            .scalars()
            .all()
        )

        assert runs == []
        assert messages == []
        assert thread.user_message_ct == 0

    mock_threads_messages_create.assert_not_awaited()


@with_user(123)
async def test_add_message_to_thread_skips_empty_transcript_for_classic_thread(
    db, user
):
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
            name="Voice V2 Assistant",
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
        )
        thread = models.Thread(
            id=21,
            class_id=class_.id,
            assistant_id=assistant.id,
            version=2,
            thread_id="thread-legacy-voice",
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
                    "anonymous_share_token": None,
                    "anonymous_session_token": None,
                }
            )
        )

        await add_message_to_thread(
            openai_client,  # type: ignore[arg-type]
            browser_connection,  # type: ignore[arg-type]
            thread,
            item_id="item-user-1",
            transcript_text="",
            role="user",
            output_index="0",
        )

        assert thread.user_message_ct == 0

    mock_threads_messages_create.assert_not_awaited()


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
@with_authz(grants=[("user:123", "can_create_assistants", "class:1")])
async def test_create_assistant_allows_gpt_5_4_temperature_with_reasoning_none(
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
        session.add(
            models.Class(
                id=1,
                name="Chat Class",
                term="Spring 2026",
                api_key="sk-test",
                private=False,
            )
        )
        await session.commit()

    response = api.post(
        "/api/v1/class/1/assistant",
        json={
            "name": "GPT-5.4 Assistant",
            "instructions": "You are helpful.",
            "description": "Test assistant",
            "interaction_mode": "chat",
            "model": "gpt-5.4",
            "reasoning_effort": -1,
            "temperature": 0.7,
            "tools": [],
        },
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )
    assert response.status_code == 200
    assert response.json()["temperature"] == 0.7
    assert response.json()["reasoning_effort"] == -1


@with_user(123)
@with_authz(grants=[("user:123", "can_create_assistants", "class:1")])
async def test_create_assistant_rejects_gpt_5_4_temperature_without_reasoning_none(
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
        session.add(
            models.Class(
                id=1,
                name="Chat Class",
                term="Spring 2026",
                api_key="sk-test",
                private=False,
            )
        )
        await session.commit()

    response = api.post(
        "/api/v1/class/1/assistant",
        json={
            "name": "GPT-5.4 Assistant",
            "instructions": "You are helpful.",
            "description": "Test assistant",
            "interaction_mode": "chat",
            "model": "gpt-5.4",
            "reasoning_effort": 0,
            "temperature": 0.7,
            "tools": [],
        },
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )
    assert response.status_code == 400
    assert response.json()["detail"] == (
        "Temperature is only available for GPT-5.4 when reasoning effort is set to 'None'."
    )


@with_user(123)
@with_authz(grants=[("user:123", "can_create_assistants", "class:1")])
async def test_create_assistant_rejects_unauthorized_deleted_private_files(
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
        session.add(
            models.Class(
                id=1,
                name="Chat Class",
                term="Spring 2026",
                api_key="sk-test",
                private=False,
            )
        )
        await session.commit()

    response = api.post(
        "/api/v1/class/1/assistant",
        json={
            "name": "GPT-5.4 Assistant",
            "instructions": "You are helpful.",
            "description": "Test assistant",
            "interaction_mode": "chat",
            "model": "gpt-5.4",
            "reasoning_effort": -1,
            "tools": [],
            "deleted_private_files": [999],
        },
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )
    assert response.status_code == 403
    assert response.json()["detail"] == (
        "You do not have permission to delete one or more private files."
    )


@with_user(123)
@with_authz(grants=[("user:123", "can_edit", "assistant:11")])
async def test_update_assistant_clears_gpt_5_4_temperature_without_reasoning_none(
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
        class_ = models.Class(
            id=1,
            name="Chat Class",
            term="Spring 2026",
            api_key="sk-test",
            private=False,
        )
        assistant = models.Assistant(
            id=11,
            name="GPT-5.4 Assistant",
            version=3,
            instructions="You are helpful.",
            interaction_mode=schemas.InteractionMode.CHAT,
            description="Test assistant",
            tools="[]",
            model="gpt-5.4",
            reasoning_effort=-1,
            temperature=0.9,
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
        json={"reasoning_effort": 0, "tools": None},
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )
    assert response.status_code == 200
    assert response.json()["temperature"] is None
    assert response.json()["reasoning_effort"] == 0

    async with db.async_session() as session:
        updated = await models.Assistant.get_by_id(session, 11)
        assert updated.temperature is None
        assert updated.reasoning_effort == 0


@with_user(123)
@with_authz(grants=[("user:123", "can_edit", "assistant:11")])
async def test_update_assistant_rejects_unauthorized_deleted_private_files(
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
        session.add_all([class_, assistant])
        await session.commit()

    response = api.put(
        "/api/v1/class/1/assistant/11",
        json={
            "name": "Updated Assistant",
            "tools": [],
            "deleted_private_files": [999],
        },
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )
    assert response.status_code == 403
    assert response.json()["detail"] == (
        "You do not have permission to delete one or more private files."
    )


@with_user(123)
@with_authz(grants=[("user:123", "can_edit", "assistant:11")])
async def test_update_assistant_allows_deleting_private_class_files(
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
                "name": "Private upload",
                "content_type": "text/plain",
                "file_id": "file-123",
                "private": True,
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
    assert response.status_code == 200

    async with db.async_session() as session:
        deleted_file = await models.File.get_by_id(session, file.id)
        assert deleted_file is None


@with_user(123)
@with_authz(
    grants=[
        ("user:123", "can_edit", "assistant:11"),
        ("user:123", "can_edit", "assistant:12"),
    ]
)
async def test_update_assistant_allows_tools_with_none_reasoning_effort(
    api, db, valid_user_token, monkeypatch
):
    model_52 = _fake_class_models_response(
        model_id="gpt-5.2",
        model_name="GPT-5.2",
        supports_temperature=False,
        supports_reasoning=True,
        supports_none_reasoning_effort=True,
        supports_tools_with_none_reasoning_effort=True,
        supports_classic_assistants=False,
    )["models"][0]
    model_54 = _fake_class_models_response(
        model_id="gpt-5.4",
        model_name="GPT-5.4",
        supports_temperature=False,
        supports_reasoning=True,
        supports_none_reasoning_effort=True,
        supports_tools_with_none_reasoning_effort=True,
        supports_temperature_with_reasoning_none=True,
        supports_classic_assistants=False,
    )["models"][0]

    async def fake_list_class_models(class_id: str, request, openai_client):  # type: ignore[no-untyped-def]
        return {
            "models": [model_52, model_54],
            "default_prompts": [],
            "enforce_classic_assistants": False,
        }

    server_module = importlib.import_module("pingpong.server")
    monkeypatch.setattr(server_module, "list_class_models", fake_list_class_models)

    async with db.async_session() as session:
        class_ = models.Class(
            id=1,
            name="Chat Class",
            term="Spring 2026",
            api_key="sk-test",
            private=False,
        )
        assistant_52 = models.Assistant(
            id=11,
            name="GPT-5.2 Assistant",
            version=3,
            instructions="You are helpful.",
            interaction_mode=schemas.InteractionMode.CHAT,
            description="Test assistant",
            tools='[{"type":"web_search"}]',
            model="gpt-5.2",
            reasoning_effort=0,
            class_id=class_.id,
            creator_id=123,
            use_latex=False,
            use_image_descriptions=False,
            locked=False,
        )
        assistant_54 = models.Assistant(
            id=12,
            name="GPT-5.4 Assistant",
            version=3,
            instructions="You are helpful.",
            interaction_mode=schemas.InteractionMode.CHAT,
            description="Test assistant",
            tools='[{"type":"web_search"}]',
            model="gpt-5.4",
            reasoning_effort=0,
            class_id=class_.id,
            creator_id=123,
            use_latex=False,
            use_image_descriptions=False,
            locked=False,
        )
        session.add_all([class_, assistant_52, assistant_54])
        await session.commit()

    for assistant_id in (11, 12):
        response = api.put(
            f"/api/v1/class/1/assistant/{assistant_id}",
            json={"reasoning_effort": -1, "tools": [{"type": "web_search"}]},
            headers={"Authorization": f"Bearer {valid_user_token}"},
        )
        assert response.status_code == 200
        assert response.json()["reasoning_effort"] == -1

    async with db.async_session() as session:
        updated_52 = await models.Assistant.get_by_id(session, 11)
        updated_54 = await models.Assistant.get_by_id(session, 12)
        assert updated_52.reasoning_effort == -1
        assert updated_54.reasoning_effort == -1
        assert updated_52.tools == '[{"type": "web_search"}]'
        assert updated_54.tools == '[{"type": "web_search"}]'


@with_user(123)
@with_authz(grants=[("user:123", "can_edit", "assistant:11")])
async def test_update_assistant_rejects_tools_with_none_reasoning_without_model_support(
    api, db, valid_user_token, monkeypatch
):
    async def fake_list_class_models(class_id: str, request, openai_client):  # type: ignore[no-untyped-def]
        return _fake_class_models_response(
            model_id="gpt-5.1",
            model_name="GPT-5.1",
            supports_temperature=False,
            supports_reasoning=True,
            supports_none_reasoning_effort=True,
            supports_tools_with_none_reasoning_effort=False,
            supports_classic_assistants=False,
        )

    server_module = importlib.import_module("pingpong.server")
    monkeypatch.setattr(server_module, "list_class_models", fake_list_class_models)

    async with db.async_session() as session:
        class_ = models.Class(
            id=1,
            name="Chat Class",
            term="Spring 2026",
            api_key="sk-test",
            private=False,
        )
        assistant = models.Assistant(
            id=11,
            name="GPT-5.1 Assistant",
            version=3,
            instructions="You are helpful.",
            interaction_mode=schemas.InteractionMode.CHAT,
            description="Test assistant",
            tools='[{"type":"web_search"}]',
            model="gpt-5.1",
            reasoning_effort=0,
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
        json={"reasoning_effort": -1, "tools": [{"type": "web_search"}]},
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )
    assert response.status_code == 400
    assert response.json()["detail"] == (
        "You cannot use tools when the reasoning effort is set to 'None'. Please select a higher reasoning effort level."
    )


@with_user(123)
@with_authz(grants=[("user:123", "can_edit", "assistant:11")])
async def test_update_assistant_without_tools_field_handles_persisted_web_search_tools(
    api, db, valid_user_token, monkeypatch
):
    async def fake_list_class_models(class_id: str, request, openai_client):  # type: ignore[no-untyped-def]
        return _fake_class_models_response(
            model_id="gpt-5.4",
            model_name="GPT-5.4",
            supports_temperature=True,
            supports_reasoning=True,
            supports_none_reasoning_effort=True,
            supports_tools_with_none_reasoning_effort=True,
            supports_classic_assistants=False,
        )

    server_module = importlib.import_module("pingpong.server")
    monkeypatch.setattr(server_module, "list_class_models", fake_list_class_models)

    async with db.async_session() as session:
        class_ = models.Class(
            id=1,
            name="Chat Class",
            term="Spring 2026",
            api_key="sk-test",
            private=False,
        )
        assistant = models.Assistant(
            id=11,
            name="GPT-5.4 Assistant",
            version=3,
            instructions="You are helpful.",
            interaction_mode=schemas.InteractionMode.CHAT,
            description="Test assistant",
            tools='[{"type":"web_search"}]',
            model="gpt-5.4",
            reasoning_effort=0,
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
        json={"reasoning_effort": 1},
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )
    assert response.status_code == 200
    assert response.json()["reasoning_effort"] == 1

    async with db.async_session() as session:
        updated = await models.Assistant.get_by_id(session, 11)

    assert updated is not None
    assert updated.tools == '[{"type":"web_search"}]'


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
