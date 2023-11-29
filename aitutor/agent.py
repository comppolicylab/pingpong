import logging
import time

from slack_sdk.socket_mode.aiohttp import SocketModeClient
from slack_sdk.socket_mode.request import SocketModeRequest
from slack_sdk.socket_mode.response import SocketModeResponse

from .claim import claim_message
from .metrics import event_count, in_flight, inbound_messages, replies, reply_duration
from .reaction import react
from .thread import SlackThread, client_user_id

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
            logger.debug(
                "Ignoring event %s (%s), bot was not tagged",
                payload["event_id"],
                payload["event"]["type"],
            )
            return False

        inbound_messages.labels(
            workspace=thread.team_id,
            channel=thread.channel,
            user=thread.user_id,
        ).inc()

        # TODO(jnu): generate response
        # Used to call AiChat.reply here ... need to call new assistants api

        replies.labels(
            workspace=thread.team_id,
            channel=thread.channel,
            user=thread.user_id,
        ).inc()
    except Exception as e:
        logger.exception(e)
        pass

    return True


async def handle_message_impl(client: SocketModeClient, req: SocketModeRequest) -> bool:
    """Process incoming messages.

    Args:
        client: SocketModeClient instance
        req: SocketModeRequest instance

    Returns:
        True if the message was processed, False otherwise
    """
    event_id = req.payload["event_id"]
    event = req.payload["event"]
    event_type = event.get("type", req.payload["type"])
    did_process = False
    logger.info("Handling message %s (%s)", event_id, event_type)

    match req.type:
        case "events_api":
            response = SocketModeResponse(envelope_id=req.envelope_id)
            await client.send_socket_mode_response(response)

            # Filter events from self
            bot_id = await client_user_id(client)
            if event.get("user") == bot_id:
                logger.debug("Ignoring event %s (%s) from self", event_id, event_type)
                return False

            match event.get("type"):
                case "message":
                    claimed = await claim_message(req.payload)
                    if not claimed:
                        logger.debug(
                            "Message %s (%s) already claimed", event_id, event_type
                        )
                        return False

                    did_process = await reply(client, req.payload)

                case "app_mention":
                    # If the bot hasn't responded yet, send a wave reaction
                    await react(client, event, "wave")
                    claimed = await claim_message(req.payload)
                    if not claimed:
                        logger.debug(
                            "Message %s (%s) already claimed", event_id, event_type
                        )
                        return False

                    did_process = await reply(client, req.payload)

                case _:
                    logger.debug("Ignoring event %s (%s)", event_id, event_type)

    return did_process


async def handle_message(
    slack_app, client: SocketModeClient, req: SocketModeRequest
):
    """Process incoming messages.

    Args:
        See `handle_message_impl`

    Returns:
        See `handle_message_impl`
    """
    req_metric = in_flight.labels(app=slack_app.app_id)
    req_metric.inc()
    evt = req.payload.get("event", {})
    evt_type = evt.get("type", req.payload.get("type", ""))
    team_id = req.payload.get("team_id", "")
    channel = evt.get("channel", "")
    channel_type = evt.get("channel_type", "")
    success = True
    did_process = True
    t0 = time.monotonic()

    try:
        did_process = await handle_message_impl(client, req)
    except Exception as e:
        logger.exception(e)
        success = False
        pass
    finally:
        req_metric.dec()
        event_count.labels(
            app=slack_app.app_id,
            event_type=evt_type,
            success=success,
            workspace=team_id,
            channel_type=channel_type,
            channel=channel,
        ).inc()

        # Log request duration
        t1 = time.monotonic()
        reply_duration.labels(
            relevant=did_process,
            success=success,
            workspace=team_id,
            channel=channel,
        ).observe(t1 - t0)
