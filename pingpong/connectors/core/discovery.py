from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

from .exceptions import ConnectorError


@dataclass(frozen=True)
class DiscoveryCacheEntry:
    payload: dict[str, Any]
    fetched_at: datetime


class DiscoveryDocumentCache:
    def __init__(
        self,
        *,
        timeout: float,
        ttl_seconds: float = 3600.0,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        if ttl_seconds <= 0:
            raise ValueError("Discovery cache TTL must be positive")
        self._timeout = timeout
        self._ttl = timedelta(seconds=ttl_seconds)
        self._now = now or (lambda: datetime.now(UTC))
        self._cache: dict[str, DiscoveryCacheEntry] = {}
        self._lock = asyncio.Lock()

    async def get(self, url: str, *, label: str = "Discovery") -> dict[str, Any]:
        entry = self._cache.get(url)
        if entry is not None and self._is_fresh(entry):
            return entry.payload
        async with self._lock:
            entry = self._cache.get(url)
            if entry is not None and self._is_fresh(entry):
                return entry.payload
            payload = await self._fetch(url, label=label)
            self._cache[url] = DiscoveryCacheEntry(
                payload=payload, fetched_at=self._now()
            )
            return payload

    def _is_fresh(self, entry: DiscoveryCacheEntry) -> bool:
        return self._now() - entry.fetched_at < self._ttl

    async def _fetch(self, url: str, *, label: str) -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.get(url)
        except httpx.HTTPError as e:
            raise ConnectorError(f"{label} failed for {url}: {e}") from e
        if response.status_code >= 400:
            raise ConnectorError(f"{label} for {url} returned {response.status_code}")
        try:
            payload = response.json()
        except ValueError as e:
            raise ConnectorError(f"{label} for {url} returned non-JSON") from e
        if not isinstance(payload, dict):
            raise ConnectorError(f"{label} for {url} returned non-object")
        return payload


def require_string_field(payload: dict[str, Any], key: str, *, label: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise ConnectorError(f"{label} missing {key}")
    return value


def optional_string_field(payload: dict[str, Any], key: str) -> str | None:
    value = payload.get(key)
    return value if isinstance(value, str) and value else None
