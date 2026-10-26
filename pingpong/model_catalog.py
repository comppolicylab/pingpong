"""Versioned, credential-ID-scoped provider inventories shared through Redis."""

import asyncio
from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import dataclass
import hashlib
import json
import logging
import os
from typing import Any, Literal
from uuid import uuid4

from fastapi import HTTPException
import openai
from pydantic import BaseModel, Field, ValidationError
from redis.exceptions import LockError, RedisError

from . import model_catalog_telemetry as telemetry
from .ai_error import MODEL_NOT_AVAILABLE_MESSAGE, is_model_unavailable_error
from .config import config
from .redis.client import RedisPool

logger = logging.getLogger(__name__)
_pool = RedisPool()

# All script keys share a Redis Cluster hash slot. Publishing only into the
# observed generation prevents a slow provider request from undoing a reset.
PUBLISH = """
if redis.call('GET', KEYS[1]) ~= ARGV[1] then return 0 end
redis.call('SET', KEYS[2], ARGV[2], 'EX', ARGV[3])
redis.call('EXPIRE', KEYS[1], ARGV[4])
return 1
"""
INVALIDATE = """
redis.call('SET', KEYS[1], ARGV[1], 'EX', ARGV[2])
redis.call('DEL', KEYS[2])
return 1
"""


@dataclass(frozen=True)
class CredentialScope:
    api_key_id: int
    provider: str
    endpoint: str | None
    api_version: str | None


class ProviderModel(BaseModel):
    id: str
    created: int | None = None
    created_at: int | None = None
    owned_by: str | None = None


class ModelCatalog(BaseModel):
    cache_mode: Literal["redis", "direct"] = Field("direct", exclude=True)
    generation: str
    models: list[ProviderModel]


def credential_scope(client: Any) -> CredentialScope | None:
    value = getattr(client, "_pingpong_model_catalog_scope", None)
    return value if isinstance(value, CredentialScope) else None


def attach_credential_scope(
    client: Any, *, api_key_id: int, provider: str, api_version: str | None
) -> None:
    client._pingpong_model_catalog_scope = CredentialScope(
        api_key_id=api_key_id,
        provider=provider,
        endpoint=str(client.base_url),
        api_version=api_version,
    )


def build_revision() -> str | None:
    # Never use a process start time or deployment timestamp. If no immutable
    # build identity is available, use direct lookups instead of stale sharing.
    return config.model_cache.build_revision or os.environ.get("SENTRY_RELEASE") or None


def runtime_model_cache_enabled() -> bool:
    return config.model_cache.redis is not None and build_revision() is not None


def cache_generation_key() -> str:
    environment = hashlib.sha256(config.deployment_identifier.encode()).hexdigest()
    return f"pingpong:model-catalog:{environment}:generation"


def cache_prefix(client: Any, generation: str | None = None) -> str | None:
    scope = credential_scope(client)
    revision = build_revision()
    if scope is None or revision is None:
        return None
    identity = {
        **vars(scope),
        "environment": config.deployment_identifier,
        "build_revision": revision,
    }
    # This contains only internal IDs and connection configuration, never the
    # API key. An ordinary digest keeps the Redis key short; no secret needed.
    digest = hashlib.sha256(
        json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    prefix = f"pingpong:model-catalog:v1:{{{digest}}}"
    return f"{prefix}:{generation}" if generation is not None else prefix


async def _global_generation(redis: Any) -> str:
    key = cache_generation_key()
    generation = await redis.get(key)
    if generation is None:
        await redis.set(key, uuid4().hex, nx=True)
        generation = await redis.get(key)
    if generation is None:
        raise RedisError("Model cache generation unavailable")
    return generation


async def reset_model_catalog_cache() -> None:
    try:
        async with catalog_redis() as redis:
            if redis is None:
                raise HTTPException(503, "Model caching is not configured.")
            await redis.set(cache_generation_key(), uuid4().hex)
    except RedisError as exc:
        raise HTTPException(
            503, "Could not reset the model cache. Please try again."
        ) from exc


@asynccontextmanager
async def catalog_redis():
    settings = config.model_cache.redis
    if settings is None:
        yield None
        return
    async with _pool.client(settings) as client:
        yield client


async def close_model_catalog_cache() -> None:
    await _pool.close()


async def _fetch(client: Any, generation: str = "") -> ModelCatalog:
    with telemetry.step("provider_fetch"):
        try:
            async with asyncio.timeout(15):
                response = await client.models.list()
        except TimeoutError as exc:
            telemetry.outcome("error", "provider_error")
            raise HTTPException(
                503, "We couldn't verify available models. Please try again."
            ) from exc
        except openai.APIError:
            telemetry.outcome("error", "provider_error")
            raise
        return ModelCatalog(
            cache_mode="redis" if generation else "direct",
            generation=generation,
            models=[
                ProviderModel.model_validate(model, from_attributes=True)
                for model in response.data
            ],
        )


async def _read(redis: Any, prefix: str) -> ModelCatalog | None:
    with telemetry.step("redis_read"):
        payload, generation = await redis.mget(f"{prefix}:snapshot", f"{prefix}:generation")
        if payload is None:
            return None
        try:
            catalog = ModelCatalog.model_validate_json(payload)
        except (ValidationError, ValueError, TypeError):
            return None
        if catalog.generation != generation:
            return None
        catalog.cache_mode = "redis"
        return catalog


async def _get_cached_model_catalog(client: Any) -> ModelCatalog | None:
    if not runtime_model_cache_enabled() or cache_prefix(client) is None:
        return None
    fetched: ModelCatalog | None = None
    try:
        async with catalog_redis() as redis:
            if redis is None:
                return None
            for _ in range(3):
                global_generation = await _global_generation(redis)
                prefix = cache_prefix(client, global_generation)
                assert prefix is not None
                cached = await _read(redis, prefix)
                if cached is not None and (
                    await redis.get(cache_generation_key()) == global_generation
                ):
                    telemetry.outcome("hit")
                    return cached
                lock_acquired = False
                try:
                    # Single flight across workers, with a finite lock lease and wait.
                    async with AsyncExitStack() as stack:
                        with telemetry.step("lock_wait"):
                            await stack.enter_async_context(
                                redis.lock(f"{prefix}:lock", timeout=90, blocking_timeout=20)
                            )
                        lock_acquired = True
                        if await redis.get(cache_generation_key()) != global_generation:
                            continue
                        cached = await _read(redis, prefix)
                        if cached is not None and (
                            await redis.get(cache_generation_key()) == global_generation
                        ):
                            telemetry.outcome("hit")
                            return cached
                        ttl = config.model_cache.ttl_seconds
                        async with redis.pipeline(transaction=False) as pipeline:
                            pipeline.set(
                                f"{prefix}:generation", uuid4().hex, nx=True, ex=ttl * 2
                            )
                            pipeline.get(f"{prefix}:generation")
                            _, generation = await pipeline.execute()
                        if generation is None:
                            continue
                        fetched = await _fetch(client, generation)
                        published = await redis.eval(
                            PUBLISH,
                            2,
                            f"{prefix}:generation",
                            f"{prefix}:snapshot",
                            generation,
                            fetched.model_dump_json(),
                            ttl,
                            ttl * 2,
                        )
                        if published and (
                            await redis.get(cache_generation_key()) == global_generation
                        ):
                            telemetry.outcome("refresh")
                            return fetched
                        # A reset made this result obsolete; do not reuse it if
                        # releasing the lock or the next Redis operation fails.
                        fetched = None
                except LockError:
                    if lock_acquired:
                        # Preserve fallback/reuse behavior for lock release failures.
                        raise
                    telemetry.outcome("unavailable", "lock_timeout")
                    telemetry.event("lock_timeout")
                    # A timeout does not mean Redis is down. The lock holder may
                    # have published just as our wait expired; read the current
                    # generation once more without starting another provider fetch.
                    current_generation = await _global_generation(redis)
                    current_prefix = cache_prefix(client, current_generation)
                    assert current_prefix is not None
                    cached = await _read(redis, current_prefix)
                    if cached is not None and (
                        await redis.get(cache_generation_key()) == current_generation
                    ):
                        telemetry.outcome("hit", "lock_timeout")
                        return cached
                    raise HTTPException(
                        503, "Available models are being refreshed. Please try again."
                    )
            telemetry.outcome("unavailable", "reset_race")
            raise HTTPException(
                503, "Available models are being refreshed. Please try again."
            )
    except RedisError:
        telemetry.outcome("unavailable", "redis_error")
        logger.warning("Model catalog cache unavailable.")
        if fetched is not None:
            fetched.cache_mode = "direct"
            return fetched
    return None


def _telemetry_provider(client: Any) -> str:
    scope = credential_scope(client)
    return scope.provider if scope and scope.provider in {"openai", "azure"} else "other"


async def get_model_catalog(client: Any) -> ModelCatalog:
    if not runtime_model_cache_enabled() or credential_scope(client) is None:
        return await _fetch(client)
    with telemetry.lookup("listing", _telemetry_provider(client)):
        cached = await _get_cached_model_catalog(client)
        if cached is not None:
            if cached.cache_mode == "direct":
                telemetry.outcome("direct_fallback", "redis_error")
            return cached
        telemetry.outcome("direct_fallback", "redis_error")
        return await _fetch(client)


async def invalidate_model_catalog(client: Any) -> None:
    if cache_prefix(client) is None:
        return
    try:
        async with catalog_redis() as redis:
            if redis is not None:
                prefix = cache_prefix(client, await _global_generation(redis))
                await redis.eval(
                    INVALIDATE,
                    2,
                    f"{prefix}:generation",
                    f"{prefix}:snapshot",
                    uuid4().hex,
                    config.model_cache.ttl_seconds * 2,
                )
    except RedisError:
        logger.warning("Could not invalidate the model catalog cache.")


async def record_model_error(client: Any, error: Any) -> None:
    if is_model_unavailable_error(error):
        await invalidate_model_catalog(client)


def _canonical_model(client: Any, model_id: str) -> str:
    if isinstance(client, openai.AsyncAzureOpenAI):
        # Import lazily: ai attaches scopes while constructing these clients.
        from .ai import get_original_model_name_by_azure_equivalent

        return get_original_model_name_by_azure_equivalent(model_id)
    return model_id


async def get_runtime_model_catalog(client: Any) -> ModelCatalog | None:
    """Fetch optional runtime verification metadata before taking database locks."""
    # Runtime guards are introduced only for newer APIKey-ID credentials.
    if credential_scope(client) is None:
        return
    if not runtime_model_cache_enabled():
        return
    with telemetry.lookup("runtime", _telemetry_provider(client)) as observation:
        try:
            catalog = await _get_cached_model_catalog(client)
        except (openai.APIError, HTTPException) as exc:
            if isinstance(exc, HTTPException) and exc.status_code != 503:
                raise
            logger.warning(
                "Could not verify model availability (%s); deferring to provider execution.",
                type(exc).__name__,
            )
            reason = observation.reason if observation.reason != "none" else "provider_error"
            telemetry.outcome("unavailable", reason)
            telemetry.decision(_telemetry_provider(client), "fail_open", reason)
            return
        if catalog is None or catalog.cache_mode != "redis":
            reason = observation.reason if observation.reason != "none" else "redis_error"
            telemetry.outcome("unavailable", reason)
            telemetry.decision(_telemetry_provider(client), "fail_open", reason)
            return
        return catalog


def validate_model_available(
    client: Any, model_id: str, catalog: ModelCatalog | None
) -> None:
    """Check an execution model against prefetched metadata without network I/O."""
    if catalog is None:
        return
    selected = _canonical_model(client, model_id)
    if not any(
        _canonical_model(client, model.id) == selected for model in catalog.models
    ):
        telemetry.decision(_telemetry_provider(client), "rejected", "model_missing")
        raise HTTPException(400, MODEL_NOT_AVAILABLE_MESSAGE)
    telemetry.decision(_telemetry_provider(client), "allowed")


async def ensure_model_available(client: Any, model_id: str) -> None:
    catalog = await get_runtime_model_catalog(client)
    validate_model_available(client, model_id, catalog)
