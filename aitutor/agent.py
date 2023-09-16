import logging
import time

from slack_sdk.socket_mode.aiohttp import SocketModeClient
from slack_sdk.socket_mode.response import SocketModeResponse
from slack_sdk.socket_mode.request import SocketModeRequest

from .thread import SlackThread, client_user_id
from .chat import AiChat
from .claim import claim_message
from .reaction import react
from .config import config
import aitutor.metrics as metrics


logger = logging.getLogger(__name__)


async def reply(client: SocketModeClient, payload: dict) -> bool:
    """Reply to a message described by event.

    Args:
        client: SocketModeClient instance
        payload: Event payload

    Returns:
        True if the message was processed, False otherwise
    """
    try:
        thread = await SlackThread.load_from_event(client, payload)
        if not thread.is_relevant():
            logger.debug("Ignoring event %s (%s), bot was not tagged",
                         payload['event_id'], payload['event']['type'])
            return False

        metrics.inbound_messages.labels(
                workspace=thread.team_id,
                channel=thread.channel,
                user=thread.user_id,
                ).inc()

        await AiChat(thread).reply(client)

        metrics.replies.labels(
                workspace=thread.team_id,
                channel=thread.channel,
                user=thread.user_id,
                ).inc()
    except Exception as e:
        logger.exception(e)
        pass

    return True



async def handle_message_impl(client: SocketModeClient, req: SocketModeRequest):
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

            t0 = time.monotonic()
            did_process = False

            match event.get('type'):
                case 'message':
                    claimed = await claim_message(req.payload)
                    if not claimed:
                        logger.debug("Message %s (%s) already claimed",
                                     event_id, event_type)
                        return

                    did_process = await reply(client, req.payload)

                case 'app_mention':
                    # If the bot hasn't responded yet, send a wave reaction
                    await react(client, event, "wave")
                    claimed = await claim_message(req.payload)
                    if not claimed:
                        logger.debug("Message %s (%s) already claimed",
                                     event_id, event_type)
                        return

                    did_process = await reply(client, req.payload)

                case _:
                    logger.debug("Ignoring event %s (%s)",
                                 event_id, event_type)

            # Log request duration
            t1 = time.monotonic()
            metrics.reply_duration.labels(
                    relevant=did_process,
                    workspace=event.get('team_id', ''),
                    channel=event.get('event', {}).get('channel', ''),
                    ).observe(t1 - t0)


async def handle_message(client: SocketModeClient, req: SocketModeRequest):
    """Process incoming messages.

    Args:
        See `handle_message_impl`

    Returns:
        See `handle_message_impl`
    """
    req_metric = metrics.in_flight.labels(app=config.slack.app_id)
    req_metric.inc()
    evt = req.payload.get('event', {})
    evt_type = evt.get('type', req.payload.get('type', ''))
    team_id = req.payload.get('team_id', '')
    channel = evt.get('channel', '')
    channel_type = evt.get('channel_type', '')
    success = True

    try:
        await handle_message_impl(client, req)
    except Exception as e:
        logger.exception(e)
        success = False
        pass
    finally:
        req_metric.dec()
        metrics.event_count.labels(
                app=config.slack.app_id,
                event_type=evt_type,
                success=success,
                workspace=team_id,
                channel_type=channel_type,
                channel=channel,
                ).inc()
