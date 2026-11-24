import asyncio
import os
from contextlib import asynccontextmanager, contextmanager

import sentry_sdk
from sentry_sdk.integrations.aiohttp import AioHttpIntegration

from .config import config

_sentry_pid: int | None = None

OPEN_ACCESS_TAG = "open_access"
_OPEN_ACCESS_SAFE_HEADERS = {"user-agent", "content-type", "content-length", "host"}


def scrub_open_access_event(event, _hint):
    if event.get("tags", {}).get(OPEN_ACCESS_TAG) != "true":
        return event
    request = event.get("request")
    if request:
        for field in ("data", "query_string", "cookies"):
            request.pop(field, None)
        request["headers"] = {
            name: value
            for name, value in (request.get("headers") or {}).items()
            if name.lower() in _OPEN_ACCESS_SAFE_HEADERS
        }
    return event


def mark_open_access_request() -> None:
    sentry_sdk.get_isolation_scope().set_tag(OPEN_ACCESS_TAG, "true")


def init_sentry() -> None:
    """Initialize Sentry once in the current process."""
    global _sentry_pid

    if not config.sentry.dsn:
        return

    current_pid = os.getpid()
    if _sentry_pid == current_pid:
        return

    sentry_sdk.init(
        dsn=config.sentry.dsn,
        integrations=[AioHttpIntegration()],
        traces_sample_rate=1.0,
        profiles_sample_rate=1.0,
        profile_lifecycle="trace",
        enable_logs=True,
        max_request_body_size="always",
        before_send=scrub_open_access_event,
        before_send_transaction=scrub_open_access_event,
    )
    # codeql[py/unused-global-variable]
    _sentry_pid = current_pid


@contextmanager
def sentry():
    init_sentry()
    try:
        yield
    finally:
        if config.sentry.dsn:
            sentry_sdk.flush(timeout=2.0)


@asynccontextmanager
async def async_sentry():
    init_sentry()
    try:
        yield
    finally:
        if config.sentry.dsn:
            await asyncio.to_thread(sentry_sdk.flush, timeout=2.0)
