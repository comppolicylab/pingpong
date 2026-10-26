import asyncio
import importlib
import json
from contextlib import asynccontextmanager
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

from fastapi import HTTPException
import httpx
import openai
import pytest
from redis.crc import key_slot
from redis.exceptions import ConnectionError, LockError, LockNotOwnedError

from pingpong import model_catalog as catalog
from pingpong.login_exchange import cache as login_cache
from pingpong.login_exchange.settings import LoginExchangeSettings
from pingpong.redis import client as redis_connections
from pingpong.redis.settings import RedisSettings


class MemoryPipeline:
    def __init__(self, redis):
        self.redis = redis
        self.commands = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    def set(self, *args, **kwargs):
        self.commands.append(("set", args, kwargs))
        return self

    def get(self, *args, **kwargs):
        self.commands.append(("get", args, kwargs))
        return self

    async def execute(self):
        return [
            await getattr(self.redis, command)(*args, **kwargs)
            for command, args, kwargs in self.commands
        ]


class MemoryRedis:
    """Redis contract double with expiry and atomic generation publication."""

    def __init__(self):
        self.values = {}
        self.expiry = {}
        self.clock = 0
        self.locks = {}

    async def get(self, key):
        if self.expiry.get(key, float("inf")) <= self.clock:
            self.values.pop(key, None)
        return self.values.get(key)

    async def mget(self, *keys):
        return [await self.get(key) for key in keys]

    def pipeline(self, *, transaction):
        assert transaction is False
        return MemoryPipeline(self)

    async def set(self, key, value, *, nx=False, ex=None):
        if nx and await self.get(key) is not None:
            return False
        self.values[key] = value
        self.expiry[key] = self.clock + ex if ex else float("inf")
        return True

    @asynccontextmanager
    async def lock(self, key, **kwargs):
        async with self.locks.setdefault(key, asyncio.Lock()):
            yield

    async def eval(self, script, numkeys, generation_key, snapshot_key, *args):
        assert numkeys == 2
        if script == catalog.INVALIDATE:
            await self.set(generation_key, args[0], ex=int(args[1]))
            self.values.pop(snapshot_key, None)
            return 1
        assert script == catalog.PUBLISH
        generation, payload, ttl, generation_ttl = args
        if await self.get(generation_key) != generation:
            return 0
        await self.set(snapshot_key, payload, ex=int(ttl))
        self.expiry[generation_key] = self.clock + int(generation_ttl)
        return 1


def provider_response(*ids):
    return SimpleNamespace(
        data=[SimpleNamespace(id=id, created=1, owned_by="provider") for id in ids]
    )


def provider_client(*ids, key_id=17):
    client = SimpleNamespace(
        models=SimpleNamespace(list=AsyncMock(return_value=provider_response(*ids))),
        base_url="https://provider.example/v1/",
        api_key="synthetic-secret-that-must-not-be-cached",
    )
    if key_id is not None:
        catalog.attach_credential_scope(
            client, api_key_id=key_id, provider="openai", api_version=None
        )
    return client


def install_memory_cache(config, monkeypatch):
    redis = MemoryRedis()
    monkeypatch.setattr(config.model_cache, "build_revision", "test-build-a")
    monkeypatch.setattr(
        config.model_cache, "redis", RedisSettings(redis_url="redis://localhost:6379/0")
    )

    @asynccontextmanager
    async def connect():
        yield redis

    monkeypatch.setattr(catalog, "catalog_redis", connect)
    return redis


@pytest.fixture
def memory_cache(config, monkeypatch):
    return install_memory_cache(config, monkeypatch)


@pytest.mark.parametrize("login_exchange_enabled", [False, True])
async def test_model_availability_without_cache_does_not_borrow_login_redis(
    config, monkeypatch, login_exchange_enabled
):
    monkeypatch.setattr(config.model_cache, "redis", None)
    monkeypatch.setattr(config.model_cache, "build_revision", "test-build")
    monkeypatch.setattr(
        config.auth,
        "login_exchange",
        LoginExchangeSettings(
            redis_url="redis://localhost:6379/0",
            target_origin="https://target.example",
            source_origins=[],
        )
        if login_exchange_enabled
        else None,
    )
    model_pool, login_pool = AsyncMock(), AsyncMock()
    monkeypatch.setattr(catalog, "_pool", model_pool)
    monkeypatch.setattr(login_cache, "_pool", login_pool)
    client = provider_client("available")
    assert (await catalog.get_model_catalog(client)).cache_mode == "direct"
    assert (await catalog.get_model_catalog(client)).cache_mode == "direct"
    assert client.models.list.await_count == 2
    client.models.list.reset_mock()
    await catalog.ensure_model_available(client, "available")
    await catalog.ensure_model_available(client, "missing")
    await catalog.invalidate_model_catalog(client)
    client.models.list.assert_not_awaited()
    model_pool.client.assert_not_called()
    login_pool.client.assert_not_called()


async def test_feature_users_and_pools_are_independent_on_the_same_deployment(
    config, monkeypatch
):
    connection = {
        "redis_url": "rediss://cache.example:6379",
        "cache_name": "pingpong-cache",
        "region": "us-east-1",
    }
    model_settings = RedisSettings(
        **connection, elasticache_user="pingpong-model-catalog"
    )
    login_settings = LoginExchangeSettings(
        **connection,
        elasticache_user="pingpong-login-exchange",
        target_origin="https://target.example",
        source_origins=[],
    )
    monkeypatch.setattr(config.model_cache, "redis", model_settings)
    monkeypatch.setattr(config.auth, "login_exchange", login_settings)
    clients = [AsyncMock(), AsyncMock()]
    factory = AsyncMock(side_effect=clients)
    monkeypatch.setattr(redis_connections, "create_redis_client", factory)
    try:
        async with catalog.catalog_redis() as model_client:
            async with login_cache.redis_client() as login_client:
                assert model_client is clients[0]
                assert login_client is clients[1]
        assert [call.args[0].elasticache_user for call in factory.await_args_list] == [
            "pingpong-model-catalog",
            "pingpong-login-exchange",
        ]
        await catalog.close_model_catalog_cache()
        model_client.aclose.assert_awaited_once()
        login_client.aclose.assert_not_awaited()
        async with login_cache.redis_client() as same_login_client:
            assert same_login_client is login_client
        assert factory.await_count == 2
    finally:
        await catalog.close_model_catalog_cache()
        await login_cache.close_redis_clients()
    login_client.aclose.assert_awaited_once()


async def test_inventory_shared_by_id_without_secret_and_permissions_not_cached(
    memory_cache,
):
    first = provider_client("supported", "not-yet-supported")
    second = provider_client("different", key_id=17)
    one = await catalog.get_model_catalog(first)
    two = await catalog.get_model_catalog(second)
    assert one == two
    assert one.cache_mode == "redis"
    first.models.list.assert_awaited_once()
    second.models.list.assert_not_awaited()
    assert [model.id for model in two.models] == ["supported", "not-yet-supported"]
    assert first.api_key not in repr(memory_cache.values)
    assert "api_key" not in one.model_dump()


async def test_shared_catalog_keeps_per_request_model_permissions(
    memory_cache, monkeypatch
):
    server = importlib.import_module("pingpong.server")
    monkeypatch.setattr(server, "ADMIN_ONLY_MODELS", ["gpt-5.6-terra"])
    client = provider_client("gpt-5.6-terra")
    request = SimpleNamespace(
        state={
            "authz": SimpleNamespace(check=AsyncMock(return_value=[True])),
            "session": SimpleNamespace(user=SimpleNamespace(id=123)),
        }
    )
    admin = await server.list_class_models("1", request, client)
    request.state["authz"].check.return_value = [False]
    member = await server.list_class_models("1", request, client)
    admin_model = next(m for m in admin["models"] if m["id"] == "gpt-5.6-terra")
    member_model = next(m for m in member["models"] if m["id"] == "gpt-5.6-terra")
    assert not admin_model.get("hide_in_model_selector")
    assert member_model["hide_in_model_selector"] is True
    assert admin["cache_mode"] == member["cache_mode"] == "redis"
    client.models.list.assert_awaited_once()


async def test_catalog_stores_only_normalized_provider_fields(memory_cache):
    client = provider_client()
    client.models.list.return_value = SimpleNamespace(
        data=[
            openai.types.Model(
                id="available",
                created=123,
                owned_by="provider",
                object="model",
                unused_provider_field="ignored",
            )
        ]
    )
    result = await catalog.get_model_catalog(client)
    assert result.cache_mode == "redis"
    prefix = catalog.cache_prefix(
        client, await memory_cache.get(catalog.cache_generation_key())
    )
    payload = json.loads(await memory_cache.get(f"{prefix}:snapshot"))
    assert payload == {
        "generation": result.generation,
        "models": [
            {
                "id": "available",
                "created": 123,
                "created_at": None,
                "owned_by": "provider",
            }
        ],
    }
    cached = await catalog.get_model_catalog(client)
    assert cached.cache_mode == "redis"
    assert cached.models == result.models
    client.models.list.assert_awaited_once()


@pytest.mark.parametrize(
    "field,value",
    [
        ("api_key_id", 18),
        ("endpoint", "https://other.example/"),
        ("api_version", "new-version"),
        ("provider", "azure"),
    ],
)
async def test_connection_changes_use_separate_inventories(memory_cache, field, value):
    first = provider_client("old")
    second = provider_client("new")
    second._pingpong_model_catalog_scope = replace(
        catalog.credential_scope(first), **{field: value}
    )
    await catalog.get_model_catalog(first)
    assert (await catalog.get_model_catalog(second)).models[0].id == "new"
    second.models.list.assert_awaited_once()


async def test_build_and_environment_changes_refresh_but_same_build_reuses(
    memory_cache, config, monkeypatch
):
    client = provider_client("first")
    await catalog.get_model_catalog(client)
    client.models.list.return_value = provider_response("new")
    assert (await catalog.get_model_catalog(client)).models[0].id == "first"
    monkeypatch.setattr(config.model_cache, "build_revision", "test-build-b")
    assert (await catalog.get_model_catalog(client)).models[0].id == "new"
    monkeypatch.setattr(config, "deployment_identifier", "another-environment")
    await catalog.get_model_catalog(client)
    assert client.models.list.await_count == 3


async def test_expiry_refreshes_inventory(memory_cache, config):
    client = provider_client("old")
    await catalog.get_model_catalog(client)
    memory_cache.clock += config.model_cache.ttl_seconds + 1
    client.models.list.return_value = provider_response("new")
    fresh = await catalog.get_model_catalog(client)
    assert fresh.models[0].id == "new"
    assert client.models.list.await_count == 2


async def test_concurrent_misses_make_one_provider_request(memory_cache):
    client = provider_client("available")
    responses = await asyncio.gather(
        *(catalog.get_model_catalog(client) for _ in range(12))
    )
    assert all(
        [model.id for model in result.models] == ["available"] for result in responses
    )
    client.models.list.assert_awaited_once()


@pytest.mark.parametrize("existing_generation", [None, "existing-generation"])
async def test_generation_initialization_is_batched_without_overwriting(
    memory_cache, monkeypatch, existing_generation
):
    client = provider_client("available")
    prefix = catalog.cache_prefix(
        client, await catalog._global_generation(memory_cache)
    )
    if existing_generation is not None:
        await memory_cache.set(f"{prefix}:generation", existing_generation, ex=50)
    pipeline = Mock(wraps=memory_cache.pipeline)
    monkeypatch.setattr(memory_cache, "pipeline", pipeline)

    result = await catalog.get_model_catalog(client)

    pipeline.assert_called_once_with(transaction=False)
    assert result.cache_mode == "redis"
    assert result.generation == await memory_cache.get(f"{prefix}:generation")
    if existing_generation is not None:
        assert result.generation == existing_generation
    client.models.list.assert_awaited_once()


async def test_generation_batch_failure_falls_back_without_extra_runtime_lookup(
    memory_cache, monkeypatch
):
    pipeline = memory_cache.pipeline(transaction=False)
    monkeypatch.setattr(
        pipeline, "execute", AsyncMock(side_effect=ConnectionError("offline"))
    )
    monkeypatch.setattr(memory_cache, "pipeline", Mock(return_value=pipeline))
    client = provider_client("available")

    await catalog.ensure_model_available(client, "missing")
    client.models.list.assert_not_awaited()
    result = await catalog.get_model_catalog(client)

    assert result.cache_mode == "direct"
    assert result.models[0].id == "available"
    client.models.list.assert_awaited_once()


async def test_cache_hit_reads_snapshot_and_generation_together(
    memory_cache, monkeypatch
):
    client = provider_client("available")
    expected = await catalog.get_model_catalog(client)
    global_key = catalog.cache_generation_key()
    prefix = catalog.cache_prefix(client, memory_cache.values[global_key])
    keys = (f"{prefix}:snapshot", f"{prefix}:generation")
    assert key_slot(keys[0].encode()) == key_slot(keys[1].encode())
    mget = AsyncMock(return_value=[memory_cache.values[key] for key in keys])
    get = AsyncMock(wraps=memory_cache.get)
    monkeypatch.setattr(memory_cache, "mget", mget)
    monkeypatch.setattr(memory_cache, "get", get)

    result = await catalog.get_model_catalog(client)

    assert result == expected
    mget.assert_awaited_once_with(*keys)
    assert [call.args for call in get.await_args_list] == [(global_key,), (global_key,)]
    client.models.list.assert_awaited_once()


async def test_global_reset_during_cache_read_rejects_old_snapshot(
    memory_cache, monkeypatch
):
    client = provider_client("old")
    await catalog.get_model_catalog(client)
    client.models.list.return_value = provider_response("new")
    read = memory_cache.mget

    async def read_then_reset(*keys):
        result = await read(*keys)
        monkeypatch.setattr(memory_cache, "mget", read)
        await catalog.reset_model_catalog_cache()
        return result

    monkeypatch.setattr(memory_cache, "mget", read_then_reset)

    result = await catalog.get_model_catalog(client)

    assert result.cache_mode == "redis"
    assert result.models[0].id == "new"
    assert client.models.list.await_count == 2


@pytest.mark.parametrize("reset_scope", ["credential", "global"])
async def test_reset_during_fetch_prevents_stale_publication_or_return(
    memory_cache, reset_scope
):
    client = provider_client()
    started = asyncio.Event()
    finish = asyncio.Event()

    async def fetch():
        if client.models.list.await_count == 1:
            started.set()
            await finish.wait()
            return provider_response("old")
        return provider_response("new")

    client.models.list.side_effect = fetch
    pending = asyncio.create_task(catalog.get_model_catalog(client))
    await started.wait()
    if reset_scope == "global":
        await catalog.reset_model_catalog_cache()
    else:
        await catalog.invalidate_model_catalog(client)
    finish.set()
    result = await pending
    assert result.models[0].id == "new"
    assert (await catalog.get_model_catalog(client)).models[0].id == "new"
    assert client.models.list.await_count == 2


async def test_global_reset_does_not_wait_for_an_old_lookup(memory_cache):
    client = provider_client()
    started, finish = asyncio.Event(), asyncio.Event()

    async def fetch():
        if client.models.list.await_count == 1:
            started.set()
            await finish.wait()
            return provider_response("old")
        return provider_response("new")

    client.models.list.side_effect = fetch
    pending = asyncio.create_task(catalog.get_model_catalog(client))
    await started.wait()
    try:
        await catalog.reset_model_catalog_cache()
        fresh = await asyncio.wait_for(catalog.get_model_catalog(client), timeout=2)
    finally:
        finish.set()
    assert (await pending).models == fresh.models
    assert fresh.models[0].id == "new"
    client.models.list.assert_awaited()
    assert client.models.list.await_count == 2


async def test_reset_is_scoped_to_the_environment(memory_cache, config, monkeypatch):
    environment = config.deployment_identifier
    client = provider_client("old")
    await catalog.get_model_catalog(client)
    client.models.list.return_value = provider_response("new")
    monkeypatch.setattr(config, "deployment_identifier", "other-environment")
    await catalog.reset_model_catalog_cache()
    monkeypatch.setattr(config, "deployment_identifier", environment)
    assert (await catalog.get_model_catalog(client)).models[0].id == "old"
    client.models.list.assert_awaited_once()


async def test_losing_global_generation_does_not_revive_previous_catalogs(memory_cache):
    client = provider_client("old")
    await catalog.get_model_catalog(client)
    memory_cache.values.pop(catalog.cache_generation_key())
    client.models.list.return_value = provider_response("new")
    fresh = await catalog.get_model_catalog(client)
    assert fresh.models[0].id == "new"
    assert client.models.list.await_count == 2


@pytest.mark.parametrize("code", ["model_not_found", "DeploymentNotFound"])
async def test_provider_rejection_invalidates_and_fresh_list_remains_authoritative(
    memory_cache, code
):
    client = provider_client("selected")
    await catalog.get_model_catalog(client)
    await catalog.record_model_error(client, SimpleNamespace(code=code))
    fresh = await catalog.get_model_catalog(client)
    assert fresh.models[0].id == "selected"
    assert client.models.list.await_count == 2
    await catalog.ensure_model_available(client, "selected")
    # Removing access is observed after invalidation, without rejection tombstones.
    client.models.list.return_value = provider_response()
    await catalog.record_model_error(client, SimpleNamespace(code=code))
    with pytest.raises(HTTPException, match="selected model") as raised:
        await catalog.ensure_model_available(client, "selected")
    assert raised.value.status_code == 400
    with pytest.raises(HTTPException):
        await catalog.ensure_model_available(client, "selected")
    assert client.models.list.await_count == 3


async def test_other_errors_do_not_invalidate(memory_cache):
    client = provider_client("selected")
    await catalog.get_model_catalog(client)
    client.models.list.return_value = provider_response("new")
    await catalog.record_model_error(
        client, SimpleNamespace(code="rate_limit_exceeded")
    )
    assert (await catalog.get_model_catalog(client)).models[0].id == "selected"
    client.models.list.assert_awaited_once()


async def test_legacy_credentials_never_use_cache_or_new_runtime_guards(memory_cache):
    client = provider_client("legacy", key_id=None)
    await catalog.get_model_catalog(client)
    await catalog.get_model_catalog(client)
    await catalog.ensure_model_available(client, "not-listed")
    await catalog.invalidate_model_catalog(client)
    assert client.models.list.await_count == 2
    assert not memory_cache.values


async def test_missing_build_identity_disables_sharing(
    memory_cache, config, monkeypatch
):
    monkeypatch.setattr(config.model_cache, "build_revision", None)
    monkeypatch.delenv("SENTRY_RELEASE", raising=False)
    client = provider_client("available")
    await catalog.get_model_catalog(client)
    await catalog.get_model_catalog(client)
    await catalog.ensure_model_available(client, "missing")
    assert client.models.list.await_count == 2
    assert not memory_cache.values


async def test_redis_outage_skips_runtime_checks_and_invalidation_is_best_effort(
    memory_cache, monkeypatch
):
    monkeypatch.setattr(
        memory_cache, "get", AsyncMock(side_effect=ConnectionError("offline"))
    )
    monkeypatch.setattr(
        memory_cache, "eval", AsyncMock(side_effect=ConnectionError("offline"))
    )
    client = provider_client("available")
    await catalog.ensure_model_available(client, "available")
    await catalog.ensure_model_available(client, "missing")
    client.models.list.assert_not_awaited()
    assert (await catalog.get_model_catalog(client)).cache_mode == "direct"
    client.models.list.assert_awaited_once()
    await catalog.invalidate_model_catalog(client)
    await catalog.record_model_error(client, SimpleNamespace(code="model_not_found"))


@pytest.mark.parametrize("stage", ["connection", "lock"])
async def test_runtime_redis_failure_does_not_trigger_a_provider_lookup(
    memory_cache, monkeypatch, stage
):
    @asynccontextmanager
    async def unavailable(*args, **kwargs):
        raise ConnectionError("offline")
        yield

    if stage == "connection":
        monkeypatch.setattr(catalog, "catalog_redis", unavailable)
    else:
        monkeypatch.setattr(memory_cache, "lock", unavailable)
    client = provider_client()
    await catalog.ensure_model_available(client, "missing")
    client.models.list.assert_not_awaited()


@pytest.mark.parametrize("operation", ["listing", "runtime"])
async def test_lock_timeout_waiters_do_not_fetch_directly(
    memory_cache, monkeypatch, operation
):
    lock = AsyncMock()

    async def timeout():
        await asyncio.sleep(0)
        raise LockError("Unable to acquire lock within the time specified")

    lock.__aenter__.side_effect = timeout
    monkeypatch.setattr(memory_cache, "lock", Mock(return_value=lock))
    client = provider_client()

    results = await asyncio.gather(
        *(
            catalog.get_model_catalog(client)
            if operation == "listing"
            else catalog.ensure_model_available(client, "missing")
            for _ in range(10)
        ),
        return_exceptions=True,
    )

    if operation == "listing":
        assert all(isinstance(result, HTTPException) for result in results)
        assert all(result.status_code == 503 for result in results)
        assert all("being refreshed" in result.detail for result in results)
    else:
        assert results == [None] * 10
    client.models.list.assert_not_awaited()
    assert lock.__aenter__.await_count == 10
    lock.__aexit__.assert_not_awaited()


@pytest.mark.parametrize(
    "publication", ["current", "global-reset", "stale-credential", "reset-during-read"]
)
async def test_lock_timeout_rereads_only_valid_current_snapshots(
    memory_cache, monkeypatch, publication
):
    client = provider_client()
    lock = AsyncMock()

    async def publish_then_timeout():
        if publication == "global-reset":
            await catalog.reset_model_catalog_cache()
        global_generation = await catalog._global_generation(memory_cache)
        prefix = catalog.cache_prefix(client, global_generation)
        snapshot = catalog.ModelCatalog(
            generation="published",
            models=[catalog.ProviderModel(id="available")],
        )
        await memory_cache.set(
            f"{prefix}:generation",
            "invalidated" if publication == "stale-credential" else "published",
        )
        await memory_cache.set(f"{prefix}:snapshot", snapshot.model_dump_json())
        raise LockError("Unable to acquire lock within the time specified")

    lock.__aenter__.side_effect = publish_then_timeout
    monkeypatch.setattr(memory_cache, "lock", Mock(return_value=lock))
    original_read = catalog._read

    async def read(redis, prefix):
        snapshot = await original_read(redis, prefix)
        if snapshot is not None and publication == "reset-during-read":
            await catalog.reset_model_catalog_cache()
        return snapshot

    monkeypatch.setattr(catalog, "_read", read)

    if publication in {"current", "global-reset"}:
        result = await catalog.get_model_catalog(client)
        assert result.cache_mode == "redis"
        assert [model.id for model in result.models] == ["available"]
    else:
        with pytest.raises(HTTPException) as raised:
            await catalog.get_model_catalog(client)
        assert raised.value.status_code == 503
    client.models.list.assert_not_awaited()
    lock.__aenter__.assert_awaited_once()
    lock.__aexit__.assert_not_awaited()


@pytest.mark.parametrize(
    "stage", ["publish", "generation_check", "lock_release", "pool_release"]
)
async def test_redis_failure_after_fetch_reuses_provider_result(
    memory_cache, monkeypatch, stage
):
    if stage == "publish":
        monkeypatch.setattr(
            memory_cache, "eval", AsyncMock(side_effect=ConnectionError("offline"))
        )
    elif stage == "generation_check":
        publish = memory_cache.eval

        async def fail_after_publish(*args):
            result = await publish(*args)
            monkeypatch.setattr(
                memory_cache, "get", AsyncMock(side_effect=ConnectionError("offline"))
            )
            return result

        monkeypatch.setattr(memory_cache, "eval", fail_after_publish)
    elif stage == "lock_release":
        lock = memory_cache.lock

        @asynccontextmanager
        async def fail_on_unlock(*args, **kwargs):
            async with lock(*args, **kwargs):
                yield
                raise LockNotOwnedError("Lock ownership lost")

        monkeypatch.setattr(memory_cache, "lock", fail_on_unlock)
    else:

        @asynccontextmanager
        async def fail_on_pool_release():
            yield memory_cache
            raise ConnectionError("offline")

        monkeypatch.setattr(catalog, "catalog_redis", fail_on_pool_release)

    client = provider_client("available")
    client.models.list.side_effect = [
        provider_response("available"),
        AssertionError("Duplicate provider call"),
    ]

    result = await catalog.get_model_catalog(client)

    assert result.cache_mode == "direct"
    assert [model.id for model in result.models] == ["available"]
    client.models.list.assert_awaited_once()


@pytest.mark.parametrize("reset_scope", ["credential", "global"])
async def test_observed_reset_discards_fetched_result_before_redis_failure(
    memory_cache, monkeypatch, reset_scope
):
    publish = memory_cache.eval

    async def reset_during_publish(*args):
        if args[0] == catalog.PUBLISH:
            if reset_scope == "global":
                await catalog.reset_model_catalog_cache()
            else:
                await catalog.invalidate_model_catalog(client)
        return await publish(*args)

    monkeypatch.setattr(memory_cache, "eval", reset_during_publish)
    lock = memory_cache.lock

    @asynccontextmanager
    async def fail_on_unlock(*args, **kwargs):
        async with lock(*args, **kwargs):
            yield
            raise LockNotOwnedError("Lock ownership lost")

    monkeypatch.setattr(memory_cache, "lock", fail_on_unlock)
    client = provider_client()
    client.models.list.side_effect = [
        provider_response("old"),
        provider_response("new"),
    ]

    result = await catalog.get_model_catalog(client)

    assert result.cache_mode == "direct"
    assert result.models[0].id == "new"
    assert client.models.list.await_count == 2


async def test_runtime_publish_failure_skips_model_guard(memory_cache, monkeypatch):
    monkeypatch.setattr(
        memory_cache, "eval", AsyncMock(side_effect=ConnectionError("offline"))
    )
    client = provider_client("available")

    await catalog.ensure_model_available(client, "missing")

    client.models.list.assert_awaited_once()


@pytest.mark.parametrize(
    ("error_type", "status_code"),
    [
        (openai.AuthenticationError, 401),
        (openai.PermissionDeniedError, 403),
        (openai.RateLimitError, 429),
        (openai.InternalServerError, 500),
        (openai.APIConnectionError, None),
        (openai.APITimeoutError, None),
        (TimeoutError, None),
    ],
)
async def test_provider_errors_are_not_cached_and_guards_fail_open(
    memory_cache, error_type, status_code
):
    client = provider_client("available")
    request = httpx.Request("GET", "https://example.test/models")
    if status_code is not None:
        error = error_type(
            "Synthetic failure",
            response=httpx.Response(status_code, request=request),
            body=None,
        )
    elif error_type is TimeoutError:
        error = TimeoutError()
    else:
        error = error_type(request=request)
    client.models.list.side_effect = error

    await catalog.ensure_model_available(client, "available")

    # Listing still reports provider failures instead of returning an empty catalog.
    with pytest.raises(HTTPException if error_type is TimeoutError else error_type):
        await catalog.get_model_catalog(client)
    client.models.list.side_effect = None
    await catalog.ensure_model_available(client, "available")
    assert client.models.list.await_count == 3
    with pytest.raises(HTTPException) as raised:
        await catalog.ensure_model_available(client, "missing")
    assert raised.value.status_code == 400
    assert client.models.list.await_count == 3


async def test_corrupt_cache_is_refetched(memory_cache):
    client = provider_client("available")
    prefix = catalog.cache_prefix(
        client, await catalog._global_generation(memory_cache)
    )
    await memory_cache.set(f"{prefix}:snapshot", "invalid JSON", ex=50)
    await catalog.ensure_model_available(client, "available")
    client.models.list.assert_awaited_once()
