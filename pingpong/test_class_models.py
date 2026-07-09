import importlib
from types import SimpleNamespace
from unittest.mock import AsyncMock

import openai

from pingpong import ai_models

server_module = importlib.import_module("pingpong.server")


class _AllowingAuthz:
    async def check(self, _tuples):
        return [True]


async def test_openai_class_models_include_latest_gpt_5_models(monkeypatch):
    openai_client = openai.AsyncOpenAI(api_key="test-key")
    openai_client.models = SimpleNamespace(
        list=AsyncMock(
            return_value=SimpleNamespace(
                data=[
                    SimpleNamespace(
                        id="gpt-5.5",
                        created=0,
                        created_at=0,
                        owned_by="openai",
                    ),
                    SimpleNamespace(
                        id="gpt-5.6-sol",
                        created=0,
                        created_at=0,
                        owned_by="openai",
                    ),
                    SimpleNamespace(
                        id="gpt-5.6-terra",
                        created=0,
                        created_at=0,
                        owned_by="openai",
                    ),
                    SimpleNamespace(
                        id="gpt-5.6-luna",
                        created=0,
                        created_at=0,
                        owned_by="openai",
                    ),
                    SimpleNamespace(
                        id="chat-latest",
                        created=0,
                        created_at=0,
                        owned_by="openai",
                    ),
                ]
            )
        )
    )
    request = SimpleNamespace(
        state={
            "authz": _AllowingAuthz(),
            "db": object(),
            "session": SimpleNamespace(user=SimpleNamespace(id=123)),
        }
    )

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

    response = await server_module.list_class_models(
        class_id="1",
        request=request,
        openai_client=openai_client,
    )

    assert [model["id"] for model in response["models"]] == [
        "gpt-5.6-sol",
        "gpt-5.6-terra",
        "gpt-5.6-luna",
        "chat-latest",
        "gpt-5.5",
    ]
    reasoning_models = [
        model for model in response["models"] if model["id"] != "chat-latest"
    ]
    for model in reasoning_models:
        assert model["is_latest"] is True
        assert model["supports_next_gen_assistants"] is True
        assert model["supports_none_reasoning_effort"] is True
        assert model["supports_tools_with_none_reasoning_effort"] is True
        assert model["supports_verbosity"] is True
        assert model["supports_web_search"] is True
        assert model["supports_mcp_server"] is True

    chat_latest = next(
        model for model in response["models"] if model["id"] == "chat-latest"
    )
    assert chat_latest["is_latest"] is True
    assert chat_latest["supports_vision"] is True
    assert chat_latest["supports_reasoning"] is True
    assert chat_latest["reasoning_effort_levels"] == [1]
    assert ai_models.get_reasoning_effort_map("chat-latest") == {1: "medium"}
    assert chat_latest["supports_next_gen_assistants"] is True
    assert chat_latest["supports_file_search"] is True
    assert chat_latest["supports_code_interpreter"] is True
    assert chat_latest["supports_web_search"] is True
    assert chat_latest["supports_mcp_server"] is True


async def test_azure_class_models_do_not_force_classic_assistants(monkeypatch):
    azure_client = openai.AsyncAzureOpenAI(
        api_key="test-key",
        azure_endpoint="https://example.openai.azure.com",
        api_version="2025-03-01-preview",
    )
    azure_client.models = SimpleNamespace(
        list=AsyncMock(
            return_value=SimpleNamespace(
                data=[
                    SimpleNamespace(
                        id="gpt-5.4-2026-03-05",
                        created=0,
                        created_at=0,
                        owned_by="azure",
                    )
                ]
            )
        )
    )
    request = SimpleNamespace(
        state={
            "authz": _AllowingAuthz(),
            "db": object(),
            "session": SimpleNamespace(user=SimpleNamespace(id=123)),
        }
    )

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

    response = await server_module.list_class_models(
        class_id="1",
        request=request,
        openai_client=azure_client,
    )

    assert response["enforce_classic_assistants"] is False
    assert response["models"][0]["id"] == "gpt-5.4"
    assert response["models"][0]["is_latest"] is True
    assert response["models"][0]["supports_next_gen_assistants"] is True
