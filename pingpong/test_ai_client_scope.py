from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from pingpong import ai, model_catalog as catalog


@pytest.fixture
async def client_factory():
    ai.get_openai_client.cache_clear()
    clients = []

    def create(*args, **kwargs):
        client = ai.get_openai_client(*args, **kwargs)
        if all(existing is not client for existing in clients):
            clients.append(client)
        return client

    yield create

    for client in clients:
        await client.close()
    ai.get_openai_client.cache_clear()


@pytest.mark.parametrize("provider", ["openai", "azure"])
async def test_credential_ids_isolate_clients_with_identical_connection_settings(
    client_factory, monkeypatch, provider
):
    options = {"provider": provider}
    if provider == "azure":
        options.update(
            endpoint="https://example.openai.azure.com",
            api_version="2025-03-01-preview",
        )
    attach = Mock(wraps=ai.attach_credential_scope)
    monkeypatch.setattr(ai, "attach_credential_scope", attach)

    first = client_factory("synthetic-key", **options, credential_id=17)
    second = client_factory("synthetic-key", **options, credential_id=18)
    reused = client_factory("synthetic-key", **options, credential_id=17)

    assert first is not second
    assert reused is first
    assert attach.call_count == 2
    first_scope = catalog.credential_scope(first)
    second_scope = catalog.credential_scope(second)
    assert first_scope.api_key_id == 17
    assert second_scope.api_key_id == 18
    assert first_scope.provider == second_scope.provider == provider
    assert first_scope.endpoint == second_scope.endpoint == str(first.base_url)
    assert first_scope.api_version == options.get("api_version")
    assert second_scope.api_version == options.get("api_version")
    monkeypatch.setattr(catalog.config.model_cache, "build_revision", "test-build")
    assert catalog.cache_prefix(first) != catalog.cache_prefix(second)


@pytest.mark.parametrize("provider", ["openai", "azure"])
async def test_credential_factory_reuses_scoped_clients_without_scoping_validation(
    client_factory, monkeypatch, provider
):
    credential = SimpleNamespace(
        id=17,
        api_key="synthetic-key",
        provider=provider,
        endpoint="https://example.openai.azure.com",
        api_version="2025-03-01-preview",
    )
    options = {"provider": provider}
    if provider == "azure":
        options.update(endpoint=credential.endpoint, api_version=credential.api_version)
    validation = client_factory(api_key=credential.api_key, **options)
    scoped = ai.get_openai_client_from_api_key(credential)
    # Register this client for cleanup without creating an additional cache entry.
    assert scoped is client_factory(
        credential.api_key, **options, credential_id=credential.id
    )
    assert ai.get_openai_client_from_api_key(credential) is scoped
    validation.models.list = AsyncMock()
    validation.models.with_raw_response.list = AsyncMock(
        return_value=SimpleNamespace(headers={"x-ms-region": "test-region"}, parse=Mock())
    )

    result = await ai.validate_api_key(credential.api_key, **options)

    assert result.valid
    assert scoped is not validation
    assert catalog.credential_scope(validation) is None
    assert catalog.credential_scope(scoped).api_key_id == credential.id
    if provider == "azure":
        validation.models.with_raw_response.list.assert_awaited_once()
    else:
        validation.models.list.assert_awaited_once()
        legacy = client_factory(credential.api_key)
        assert catalog.credential_scope(legacy) is None
        assert legacy is not scoped
