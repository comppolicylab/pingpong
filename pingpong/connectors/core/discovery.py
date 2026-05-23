from __future__ import annotations

import asyncio
from typing import Any

import httpx

from .exceptions import ConnectorError


class DiscoveryDocumentCache:
    def __init__(self, *, timeout: float) -> None:
        self._timeout = timeout
        self._cache: dict[str, dict[str, Any]] = {}
        self._lock = asyncio.Lock()

    async def get(self, url: str, *, label: str = "Discovery") -> dict[str, Any]:
        if url in self._cache:
            return self._cache[url]
        async with self._lock:
            if url in self._cache:
                return self._cache[url]
            payload = await self._fetch(url, label=label)
            self._cache[url] = payload
            return payload

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
