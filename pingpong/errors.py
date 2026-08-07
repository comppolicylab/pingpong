import asyncio
import os
from contextlib import asynccontextmanager, contextmanager

import sentry_sdk
from sentry_sdk.integrations.aiohttp import AioHttpIntegration

from .config import config

_sentry_pid: int | None = None  # codeql[py/unused-global-variable]


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
    )
    _sentry_pid = current_pid


def capture_exception_to_sentry(exc: Exception, **tags: object) -> None:
    if not config.sentry.dsn:
        return

    init_sentry()
    with sentry_sdk.push_scope() as scope:
        for key, value in tags.items():
            if value is not None:
                scope.set_tag(key, str(value))
        sentry_sdk.capture_exception(exc)
        sentry_sdk.flush(timeout=2.0)


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
