import signal
import logging
import asyncio

import sentry_sdk
from sentry_sdk.integrations.aiohttp import AioHttpIntegration
from slack_sdk.web.async_client import AsyncWebClient
from slack_sdk.socket_mode.aiohttp import SocketModeClient

from .config import config
from .agent import handle_message


logging.basicConfig(level=config.log_level)
logger = logging.getLogger(__name__)


# Flag for signaling when to shut down event loop.
_done = False


async def run():
    """Connect to Slack and handle events."""
    global _done
    client = SocketModeClient(
            app_token=config.slack.socket_token,
            web_client=AsyncWebClient(token=config.slack.web_token),
            )
    client.socket_mode_request_listeners.append(handle_message)
    await client.connect()
    # Wait until a signal is received to shut down
    while not _done:
        await asyncio.sleep(1)
    logger.debug("Stopping client...")
    await client.disconnect()
    await client.close()


def handle_sig():
    """Handle signals."""
    global _done
    _done = True


def main():
    """Run the agent service.

    Keeps the agent running until it's explicitly stopped with a signal or
    keyboard interrupt.
    """
    global _done
    loop = asyncio.new_event_loop()
    
    for sig in [signal.SIGINT, signal.SIGTERM]:
        loop.add_signal_handler(sig, handle_sig)

    while not _done:
        try:
            task = loop.create_task(run())
            loop.run_until_complete(task)
        except Exception:
            logger.exception("Agent encountered an exception!")
            logger.warning("Agent restarting...")
            continue
        except (KeyboardInterrupt, SystemExit):
            _done = True

    logger.info("Agent shutting down...")
    try:
        if not loop.is_closed():
            loop.close()
    except Exception:
        logger.exception("Agent encountered an exception while shutting down!")
        logger.warning("Agent shutting down anyway...")

    logger.info("Bye! 👋")


if __name__ == "__main__":
    if config.sentry.dsn:
        sentry_sdk.init(
                dsn=config.sentry.dsn,
                integrations=[AioHttpIntegration()],
                traces_sample_rate=1.0,
                profiles_sample_rate=1.0,
                )
    main()
