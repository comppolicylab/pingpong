import importlib
from types import SimpleNamespace
from unittest.mock import AsyncMock

import openai
import pytest

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

    monkeypatch.setattr(
        server_module,
        "_get_class_lecture_video_provider_flags",
        AsyncMock(
            side_effect=AssertionError(
                "Listing models must not load lecture lesson provider state"
            )
        ),
    )

    response = await server_module.list_class_models(
        class_id="1",
        request=request,
        openai_client=openai_client,
    )
    assert response["cache_mode"] == "direct"
    assert set(response) == {
        "cache_mode",
        "models",
        "default_prompts",
        "enforce_classic_assistants",
    }

    provider_model_ids = {
        model.id for model in (await openai_client.models.list()).data
    }
    assert [
        model["id"] for model in response["models"] if model["id"] in provider_model_ids
    ] == [
        "gpt-5.6-sol",
        "gpt-5.6-terra",
        "gpt-5.6-luna",
        "chat-latest",
        "gpt-5.5",
    ]
    highlighted_models = [
        model["id"] for model in response["models"] if model["highlight"]
    ]
    assert highlighted_models == ["gpt-5.6-terra"]
    reasoning_models = [
        model
        for model in response["models"]
        if model["id"] in provider_model_ids and model["id"] != "chat-latest"
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

    monkeypatch.setattr(
        server_module,
        "_get_class_lecture_video_provider_flags",
        AsyncMock(
            side_effect=AssertionError(
                "Listing models must not load lecture lesson provider state"
            )
        ),
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


@pytest.mark.parametrize("provider_lists_legacy_model", [False, True])
async def test_class_models_retain_legacy_metadata_for_existing_assistants(
    provider_lists_legacy_model,
):
    legacy_ids = ["gpt-4o-realtime-preview", "gpt-4o"]
    provider_ids = ["gpt-realtime-2.1"]
    if provider_lists_legacy_model:
        provider_ids.extend(legacy_ids)
    client = openai.AsyncOpenAI(api_key="test-key")
    client.models = SimpleNamespace(
        list=AsyncMock(
            return_value=SimpleNamespace(
                data=[
                    SimpleNamespace(id=model_id, created=123, owned_by="openai")
                    for model_id in provider_ids
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

    response = await server_module.list_class_models("1", request, client)
    for model_id in legacy_ids:
        matches = [model for model in response["models"] if model["id"] == model_id]
        assert len(matches) == 1
        model = matches[0]
        assert model["hide_in_model_selector"] is True
        assert model["is_available"] is provider_lists_legacy_model
        assert model["name"] == ai_models.KNOWN_MODELS[model_id]["name"]
        assert model["type"] == ai_models.KNOWN_MODELS[model_id]["type"]
        assert model["is_latest"] == ai_models.KNOWN_MODELS[model_id]["is_latest"]
        if provider_lists_legacy_model:
            assert model["owner"] == "openai"
            assert model["created"].timestamp() == 123

    # Missing current models must not become available merely because they are known.
    assert "gpt-realtime-2.1-mini" not in {model["id"] for model in response["models"]}
    latest = next(
        model for model in response["models"] if model["id"] == "gpt-realtime-2.1"
    )
    assert latest["highlight"] is True
    assert latest["is_available"] is True
    assert not latest["hide_in_model_selector"]
