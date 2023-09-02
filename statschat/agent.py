import asyncio
import logging
import signal

from slack_sdk.web.async_client import AsyncWebClient
from slack_sdk.socket_mode.aiohttp import SocketModeClient
from slack_sdk.socket_mode.response import SocketModeResponse
from slack_sdk.socket_mode.request import SocketModeRequest

from chat import Chat
from config import config


logging.basicConfig(level=config.log_level)
logger = logging.getLogger(__name__)


# Load the system prompt from the file
with open(config.tutor.prompt_file, "r") as f:
    prompt = f.read()


async def handle_message(client: SocketModeClient, req: SocketModeRequest):
    """Process incoming messages.

    Args:
        client: SocketModeClient instance
        req: SocketModeRequest instance
    """
    logger.info("Received message: %s", req.payload)
    match req.type:
        case "events_api":
            response = SocketModeResponse(envelope_id=req.envelope_id)
            await client.send_socket_mode_response(response)

            event = req.payload["event"]

            # Filter events from self
            if event.get('app_id') == config.slack.app_id:
                logger.debug("Ignoring event %s from self",
                             req.payload['event_id'])
                return

            if event.get("type") == "message" and event.get("subtype") is None:
                chat = Chat(prompt)
                text = await chat.chat(event['text'])

                await client.web_client.reactions_add(
                        name="wave",
                        channel=event['channel'],
                        timestamp=event['ts'],
                        )
                await client.web_client.chat_postMessage(
                        channel=event['channel'],
                        thread_ts=event['ts'],
                        text=text,
                        )


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
    main()
