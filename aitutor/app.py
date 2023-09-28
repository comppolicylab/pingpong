import asyncio
import logging
import signal
from functools import partial

from azure.monitor.opentelemetry import configure_azure_monitor
from slack_sdk.socket_mode.aiohttp import SocketModeClient
from slack_sdk.web.async_client import AsyncWebClient

from .agent import handle_message
from .config import config

logging.basicConfig(level=config.log_level)
logger = logging.getLogger(__name__)


# Flag for signaling when to shut down event loop.
_done = False


async def run():
    """Connect to Slack and handle events."""
    global _done

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

    # Wait until a signal is received to shut down
    while not _done:
        await asyncio.sleep(1)

    logger.info("Stopping client(s) ...")
    for i, client in enumerate(clients):
        logger.debug(f"Stopping client {apps[i].app_id}...")
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

    if config.metrics.connection_string:
        configure_azure_monitor(
            connection_string=config.metrics.connection_string,
        )

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
    main()
