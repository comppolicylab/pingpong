import sentry_sdk
from sentry_sdk.integrations.aiohttp import AioHttpIntegration

from .app import main
from .config import config

if __name__ == "__main__":
    if config.sentry.dsn:
        sentry_sdk.init(
            dsn=config.sentry.dsn,
            integrations=[AioHttpIntegration()],
            traces_sample_rate=1.0,
            profiles_sample_rate=1.0,
        )
    main()
