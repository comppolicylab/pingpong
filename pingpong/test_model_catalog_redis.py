"""Opt-in Redis integration checks; use a disposable Redis instance."""

import asyncio
import os
from uuid import uuid4

import pytest
from redis.asyncio import Redis

from pingpong import model_catalog as catalog
from pingpong.redis.settings import RedisSettings
from pingpong.test_model_catalog import provider_client, provider_response


@pytest.fixture
async def real_catalog_cache(config, monkeypatch):
    url = os.environ.get("MODEL_CATALOG_TEST_REDIS_URL")
    if not url:
        pytest.skip("Set MODEL_CATALOG_TEST_REDIS_URL to a disposable Redis instance")
    monkeypatch.setattr(
        config.model_cache, "build_revision", f"integration-{uuid4().hex}"
    )
    monkeypatch.setattr(config.model_cache, "redis", RedisSettings(redis_url=url))
    monkeypatch.setattr(config, "deployment_identifier", f"integration-{uuid4().hex}")
    prefixes = set()
    original_prefix = catalog.cache_prefix

    def track_prefix(client, generation=None):
        prefix = original_prefix(client, generation)
        if prefix is not None:
            prefixes.add(prefix)
        return prefix

    monkeypatch.setattr(catalog, "cache_prefix", track_prefix)
    async with Redis.from_url(url, decode_responses=True) as redis:
        await redis.ping()

        try:
            yield redis
        finally:
            await catalog.close_model_catalog_cache()
            await redis.delete(catalog.cache_generation_key())
            for prefix in prefixes:
                await redis.delete(
                    *(
                        f"{prefix}:{suffix}"
                        for suffix in ("snapshot", "generation", "lock")
                    )
                )


async def test_real_redis_single_flight_ttl_and_shared_catalog(
    real_catalog_cache, config
):
    first = provider_client("one")
    second = provider_client("two")

    async def fetch():
        await asyncio.sleep(0.05)
        return provider_response("one")

    first.models.list.side_effect = fetch
    second.models.list.side_effect = fetch
    results = await asyncio.gather(
        *(
            catalog.get_model_catalog(first if index % 2 else second)
            for index in range(10)
        )
    )
    assert first.models.list.await_count + second.models.list.await_count == 1
    assert all([model.id for model in result.models] == ["one"] for result in results)
    prefix = catalog.cache_prefix(
        first, await real_catalog_cache.get(catalog.cache_generation_key())
    )
    assert (
        0
        < await real_catalog_cache.ttl(f"{prefix}:snapshot")
        <= config.model_cache.ttl_seconds
    )
    assert await real_catalog_cache.get(f"{prefix}:lock") is None


@pytest.mark.parametrize("reset_scope", ["credential", "global"])
async def test_real_redis_reset_during_fetch_cannot_restore_old_snapshot(
    real_catalog_cache, reset_scope
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
    fresh = await pending
    assert fresh.models[0].id == "new"
    assert (await catalog.get_model_catalog(client)).models == fresh.models
    assert client.models.list.await_count == 2


async def test_real_redis_expiry_and_cache_generation_eviction(real_catalog_cache):
    client = provider_client("old")
    await catalog.get_model_catalog(client)
    prefix = catalog.cache_prefix(
        client, await real_catalog_cache.get(catalog.cache_generation_key())
    )
    await real_catalog_cache.pexpire(f"{prefix}:snapshot", 1)
    await asyncio.sleep(0.02)
    client.models.list.return_value = provider_response("new")
    fresh = await catalog.get_model_catalog(client)
    assert fresh.models[0].id == "new"
    # Losing the generation key must also invalidate an otherwise present snapshot.
    await real_catalog_cache.delete(f"{prefix}:generation")
    client.models.list.return_value = provider_response("newer")
    assert (await catalog.get_model_catalog(client)).models[0].id == "newer"
    assert client.models.list.await_count == 3
    await real_catalog_cache.delete(catalog.cache_generation_key())
    client.models.list.return_value = provider_response("newest")
    assert (await catalog.get_model_catalog(client)).models[0].id == "newest"


async def test_real_redis_global_reset_covers_all_credentials_and_builds(
    real_catalog_cache, config, monkeypatch
):
    inventories = []
    for build in ("build-a", "build-b"):
        monkeypatch.setattr(config.model_cache, "build_revision", build)
        for key_id in (17, 18):
            client = provider_client("old", key_id=key_id)
            await catalog.get_model_catalog(client)
            client.models.list.return_value = provider_response("new")
            inventories.append((build, client))
    old_generation = await real_catalog_cache.get(catalog.cache_generation_key())
    await catalog.reset_model_catalog_cache()
    assert (
        await real_catalog_cache.get(catalog.cache_generation_key()) != old_generation
    )
    assert await real_catalog_cache.ttl(catalog.cache_generation_key()) == -1
    for build, client in inventories:
        client.models.list.assert_awaited_once()
        monkeypatch.setattr(config.model_cache, "build_revision", build)
        fresh = await catalog.get_model_catalog(client)
        assert fresh.models[0].id == "new"
        assert client.models.list.await_count == 2
