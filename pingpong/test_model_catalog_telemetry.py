from contextlib import contextmanager, nullcontext
import asyncio
import json
from unittest.mock import AsyncMock, Mock

from fastapi import HTTPException
import httpx
import openai
import pytest
from redis.exceptions import ConnectionError, LockError
import sentry_sdk
from sentry_sdk.transport import Transport

from pingpong import model_catalog as catalog, model_catalog_telemetry as telemetry
from pingpong.test_model_catalog import (
    install_memory_cache,
    provider_client,
    provider_response,
)


@pytest.fixture
def observations(config, monkeypatch):
    redis = install_memory_cache(config, monkeypatch)
    spans = []

    @contextmanager
    def start_span(**kwargs):
        span = Mock()
        span.name = kwargs["name"]
        span.finished = False
        spans.append(span)
        try:
            yield span
        finally:
            span.finished = True

    count = Mock()
    distribution = Mock()
    monkeypatch.setattr(telemetry.sentry_sdk, "get_current_span", lambda: object())
    monkeypatch.setattr(telemetry.sentry_sdk, "start_span", start_span)
    monkeypatch.setattr(telemetry.metrics, "count", count)
    monkeypatch.setattr(telemetry.metrics, "distribution", distribution)
    return redis, spans, count, distribution


async def test_refresh_and_hit_have_separate_metrics_and_lock_wait_span(observations):
    redis, spans, count, distribution = observations
    client = provider_client("sensitive-model-name")

    async def fetch():
        wait = next(span for span in spans if span.name == "model_catalog.lock_wait")
        assert wait.finished
        return provider_response("sensitive-model-name")

    client.models.list.side_effect = fetch
    await catalog.get_model_catalog(client)
    await catalog.ensure_model_available(client, "sensitive-model-name")
    with pytest.raises(HTTPException):
        await catalog.ensure_model_available(client, "another-sensitive-model")

    lookups = [
        call.kwargs["attributes"] for call in count.call_args_list
        if call.args[0] == "model_catalog.lookups"
    ]
    assert [attrs["catalog.outcome"] for attrs in lookups] == ["refresh", "hit", "hit"]
    assert [attrs["catalog.operation"] for attrs in lookups] == [
        "listing", "runtime", "runtime"
    ]
    decisions = [
        call.kwargs["attributes"]["catalog.decision"] for call in count.call_args_list
        if call.args[0] == "model_catalog.runtime.decisions"
    ]
    assert decisions == ["allowed", "rejected"]
    assert all(call.args[1] >= 0 for call in distribution.call_args_list)
    assert all(
        call.kwargs["unit"] == "millisecond" for call in distribution.call_args_list
    )
    assert "model_catalog.provider_fetch.duration" in {
        call.args[0] for call in distribution.call_args_list
    }
    # Keep identifying values out of the feature's explicit telemetry.
    attributes = json.dumps([
        call.kwargs["attributes"] for call in count.call_args_list
    ])
    for value in [
        client.api_key, client.base_url,
        "sensitive-model-name", "another-sensitive-model", "17"
    ]:
        assert value not in attributes
    client.models.list.assert_awaited_once()


@pytest.mark.parametrize("failure", ["redis_error", "lock_timeout", "provider_error"])
async def test_runtime_fail_open_has_a_reason_and_keeps_execution_available(
    observations, monkeypatch, failure
):
    redis, spans, count, distribution = observations
    client = provider_client("available")
    if failure == "redis_error":
        monkeypatch.setattr(
            redis, "get", AsyncMock(side_effect=ConnectionError("offline"))
        )
    elif failure == "lock_timeout":
        lock = AsyncMock()
        lock.__aenter__.side_effect = LockError("busy")
        monkeypatch.setattr(redis, "lock", Mock(return_value=lock))
    else:
        client.models.list.side_effect = openai.PermissionDeniedError(
            "restricted",
            response=httpx.Response(
                403, request=httpx.Request("GET", "https://example.test/models")
            ),
            body=None,
        )

    await catalog.ensure_model_available(client, "available")

    decisions = [
        call for call in count.call_args_list
        if call.args[0] == "model_catalog.runtime.decisions"
    ]
    assert len(decisions) == 1
    assert decisions[0].kwargs["attributes"] == {
        "catalog.operation": "runtime",
        "catalog.provider": "openai",
        "catalog.decision": "fail_open",
        "catalog.reason": failure,
    }
    if failure == "lock_timeout":
        assert any(
            call.args[0] == "model_catalog.lock_timeout" for call in count.call_args_list
        )
    if failure != "provider_error":
        client.models.list.assert_not_awaited()


async def test_disabled_and_legacy_paths_emit_no_catalog_telemetry(
    observations, config, monkeypatch
):
    redis, spans, count, distribution = observations
    legacy = provider_client("available", key_id=None)
    await catalog.get_model_catalog(legacy)
    await catalog.ensure_model_available(legacy, "missing")
    monkeypatch.setattr(config.model_cache, "redis", None)
    scoped = provider_client("available")
    await catalog.get_model_catalog(scoped)
    await catalog.ensure_model_available(scoped, "missing")
    assert spans == []
    count.assert_not_called()
    distribution.assert_not_called()


async def test_standalone_lookup_creates_only_a_bounded_transaction(
    observations, monkeypatch
):
    redis, spans, count, distribution = observations
    start = Mock(wraps=telemetry.sentry_sdk.start_span)
    monkeypatch.setattr(telemetry.sentry_sdk, "get_current_span", lambda: None)
    monkeypatch.setattr(telemetry.sentry_sdk, "start_transaction", start)

    await catalog.get_runtime_model_catalog(provider_client("available"))

    start.assert_called_once_with(
        op="model_catalog.lookup", name="model_catalog.lookup"
    )
    assert spans[0].finished
    assert telemetry._current.get() is None


async def test_concurrent_lookup_attributes_remain_isolated(observations):
    redis, spans, count, distribution = observations
    first = provider_client("one")
    second = provider_client("two", key_id=18)
    catalog.attach_credential_scope(
        second, api_key_id=18, provider="azure", api_version=None
    )

    async def fetch(model):
        await asyncio.sleep(0)
        return provider_response(model)

    async def first_fetch():
        return await fetch("one")

    async def second_fetch():
        return await fetch("two")

    first.models.list.side_effect = first_fetch
    second.models.list.side_effect = second_fetch
    await asyncio.gather(
        catalog.get_model_catalog(first), catalog.get_runtime_model_catalog(second)
    )
    attributes = [
        call.kwargs["attributes"] for call in count.call_args_list
        if call.args[0] == "model_catalog.lookups"
    ]
    assert {
        (attrs["catalog.operation"], attrs["catalog.provider"])
        for attrs in attributes
    } == {("listing", "openai"), ("runtime", "azure")}
    assert telemetry._current.get() is None


@pytest.mark.parametrize("has_parent", [False, True])
async def test_real_sdk_serializes_catalog_spans_and_metrics(
    config, monkeypatch, has_parent
):
    install_memory_cache(config, monkeypatch)
    envelopes = []

    class RecordingTransport(Transport):
        def capture_envelope(self, envelope):
            envelopes.append(envelope)

    # Exercise the SDK transport without making any network requests.
    client = sentry_sdk.Client(
        dsn="https://public@example.invalid/1",
        transport=RecordingTransport(),
        traces_sample_rate=1.0,
        default_integrations=False,
        auto_enabling_integrations=False,
        enable_metrics=True,
    )
    try:
        with sentry_sdk.new_scope() as scope:
            scope.set_client(client)
            parent = (
                sentry_sdk.start_transaction(op="http.server", name="POST /synthetic")
                if has_parent else nullcontext()
            )
            with parent:
                await catalog.get_model_catalog(provider_client("available"))
            client.flush()
    finally:
        client.close()

    serialized = b"\n".join(envelope.serialize() for envelope in envelopes)
    assert b'"transaction"' in serialized
    assert b"model_catalog.lookup" in serialized
    assert b"model_catalog.provider_fetch" in serialized
    assert b"model_catalog.lookup.duration" in serialized
    assert b"model_catalog.lookups" in serialized
    transactions = [
        item.payload.json
        for envelope in envelopes for item in envelope.items
        if item.type == "transaction"
    ]
    assert len(transactions) == 1
    assert transactions[0]["transaction"] == (
        "POST /synthetic" if has_parent else "model_catalog.lookup"
    )
