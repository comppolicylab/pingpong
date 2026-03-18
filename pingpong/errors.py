from contextlib import contextmanager

import sentry_sdk
from sentry_sdk.integrations.aiohttp import AioHttpIntegration

from .config import config


def capture_exception_to_sentry(exc: Exception, **tags: object) -> None:
    if not config.sentry.dsn:
        return

    with sentry_sdk.push_scope() as scope:
        for key, value in tags.items():
            if value is not None:
                scope.set_tag(key, str(value))
        sentry_sdk.capture_exception(exc)
        sentry_sdk.flush(timeout=2.0)


@contextmanager
def sentry():
    if config.sentry.dsn:
        sentry_sdk.init(
            dsn=config.sentry.dsn,
            integrations=[AioHttpIntegration()],
            traces_sample_rate=1.0,
            profiles_sample_rate=1.0,
            profile_lifecycle="trace",
            enable_logs=True,
            max_request_body_size="always",
        )
    yield
