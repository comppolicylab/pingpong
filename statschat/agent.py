import logging

from slack_sdk.socket_mode.aiohttp import SocketModeClient
from slack_sdk.socket_mode.response import SocketModeResponse
from slack_sdk.socket_mode.request import SocketModeRequest

from chat import Chat
from config import config


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
