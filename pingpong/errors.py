from contextlib import contextmanager

import sentry_sdk
from sentry_sdk.integrations.aiohttp import AioHttpIntegration

from .config import config


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
