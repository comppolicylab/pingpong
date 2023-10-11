import asyncio
import logging
import signal
from contextlib import asynccontextmanager
from functools import partial

from slack_sdk.socket_mode.aiohttp import SocketModeClient
from slack_sdk.web.async_client import AsyncWebClient

from .agent import handle_message
from .config import config

logger = logging.getLogger(__name__)


@asynccontextmanager
async def run_slack_bot():
    """Connect to Slack and handle events."""
    apps = config.slack if isinstance(config.slack, list) else [config.slack]

    clients = list[SocketModeClient]()
    logger.info("Starting client(s) ...")
    for app in apps:
        client = SocketModeClient(
            app_token=app.socket_token,
            web_client=AsyncWebClient(token=app.web_token),
        )
        handler = partial(handle_message, app)
        client.socket_mode_request_listeners.append(handler)
        clients.append(client)
        logger.debug(f"Starting client for {app.app_id}...")
        await client.connect()

    # Yield control until we're done.
    yield

    logger.info("Stopping client(s) ...")
    for i, client in enumerate(clients):
        logger.debug(f"Stopping client {apps[i].app_id}...")
        await client.disconnect()
        await client.close()


async def _run_until_done(event: asyncio.Event):
    """Run the agent until it's done."""
    async with run_slack_bot():
        await event.wait()


def handle_sig(event: asyncio.Event):
    """Handle signals."""
    event.set()


def main():
    """Run the agent service.

    Keeps the agent running until it's explicitly stopped with a signal or
    keyboard interrupt.
    """
    loop = asyncio.new_event_loop()

    event = asyncio.Event()
    for sig in [signal.SIGINT, signal.SIGTERM]:
        loop.add_signal_handler(sig, handle_sig, event)

    while not event.is_set():
        try:
            task = loop.create_task(_run_until_done(event))
            loop.run_until_complete(task)
        except Exception:
            logger.exception("Agent encountered an exception!")
            logger.warning("Agent restarting...")
            continue
        except (KeyboardInterrupt, SystemExit):
            logger.info("Agent received an exit signal!")
            event.set()

    logger.info("Agent shutting down...")
    try:
        if not loop.is_closed():
            loop.close()
    except Exception:
        logger.exception("Agent encountered an exception while shutting down!")
        logger.warning("Agent shutting down anyway...")

    logger.info("Bye! 👋")
