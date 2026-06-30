import importlib
from types import SimpleNamespace
from unittest.mock import AsyncMock

import openai

server_module = importlib.import_module("pingpong.server")


class _AllowingAuthz:
    async def check(self, _tuples):
        return [True]


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
