import logging

from slack_sdk.socket_mode.aiohttp import SocketModeClient
from slack_sdk.socket_mode.response import SocketModeResponse
from slack_sdk.socket_mode.request import SocketModeRequest

from .thread import SlackThread, client_user_id
from .chat import AiChat
from .claim import claim_message
from .reaction import react


logger = logging.getLogger(__name__)


async def reply(client: SocketModeClient, payload: dict):
    """Reply to a message described by event.

    Args:
        client: SocketModeClient instance
        payload: Event payload
    """
    try:
        thread = await SlackThread.load_from_event(client, payload)
        if not thread.is_relevant():
            logger.debug("Ignoring event %s (%s), bot was not tagged",
                         payload['event_id'], payload['event']['type'])
            return

        await AiChat(thread).reply(client)
    except Exception as e:
        logger.exception(e)
        pass


async def handle_message(client: SocketModeClient, req: SocketModeRequest):
    """Process incoming messages.

    Args:
        client: SocketModeClient instance
        req: SocketModeRequest instance
    """
    event_id = req.payload['event_id']
    event = req.payload["event"]
    event_type = event.get('type', req.payload['type'])
    logger.info("Handling message %s (%s)", event_id, event_type)

    match req.type:
        case "events_api":
            response = SocketModeResponse(envelope_id=req.envelope_id)
            await client.send_socket_mode_response(response)

            # Filter events from self
            bot_id = await client_user_id(client)
            if event.get('user') == bot_id:
                logger.debug("Ignoring event %s (%s) from self",
                             event_id, event_type)
                return

            match event.get('type'):
                case 'message':
                    claimed = await claim_message(req.payload)
                    if not claimed:
                        logger.debug("Message %s (%s) already claimed",
                                     event_id, event_type)
                        return

                    await reply(client, req.payload)

                case 'app_mention':
                    # If the bot hasn't responded yet, send a wave reaction
                    await react(client, event, "wave")
                    claimed = await claim_message(req.payload)
                    if not claimed:
                        logger.debug("Message %s (%s) already claimed",
                                     event_id, event_type)
                        return

                    await reply(client, req.payload)

                case _:
                    logger.debug("Ignoring event %s (%s)",
                                 event_id, event_type)
