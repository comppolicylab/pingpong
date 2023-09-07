import logging

from slack_sdk.socket_mode.aiohttp import SocketModeClient
from slack_sdk.socket_mode.response import SocketModeResponse
from slack_sdk.socket_mode.request import SocketModeRequest

from .chat import Chat, Role
from .config import config
from .meta import load_metadata, save_metadata, save_error, get_mdid
from .claim import claim_message


logger = logging.getLogger(__name__)


# Load the system prompt from the file
with open(config.tutor.prompt_file, "r") as f:
    prompt = f.read()


# Cached bot client user ID.
_user_id: str | None = None


async def client_user_id(client: SocketModeClient) -> str:
    """Get the user ID of the bot.

    Args:
        client: SocketModeClient instance

    Returns:
        User ID of the bot
    """
    # TODO - functools.cache doesn't work with async functions
    global _user_id
    if _user_id:
        return _user_id
    # Get the user ID of the bot
    auth = await client.web_client.auth_test()
    _user_id = auth['user_id'].strip()
    return _user_id


async def get_thread_history(client: SocketModeClient, event: dict) -> Chat:
    """Get the history of a thread.

    Args:
        client: SocketModeClient instance
        channel: Channel ID
        ts: Timestamp of the thread

    Returns:
        List of messages in the thread
    """
    bot_id = await client_user_id(client)
    chat = Chat(bot_id, prompt)
    thread_ts = event.get('thread_ts')
    if not thread_ts:
        chat.add_message(Role.USER, event['text'])
        return chat

    # Get the thread history
    history = await client.web_client.conversations_replies(
            channel=event['channel'],
            ts=thread_ts,
            include_all_metadata=True,
            )

    # Get the messages from the history
    messages = history['messages']

    # Add messages to the chat
    for message in messages:
        if message.get('type') != 'message':
            logger.debug("Ignoring message %s of type %s",
                         message['ts'], message['type'])
            continue

        if message['ts'] == event['ts']:
            # Ignore the message that triggered this function
            continue

        role = Role.AI if message['user'] == bot_id else Role.USER

        turns = await load_metadata(get_mdid(event['channel'], message['ts']))
        if isinstance(turns, dict) and 'error' in turns:
            logger.warning("Ignoring an error message we sent: %s",
                           turns['error'])
        else:
            for turn in turns:
                chat.add_message(turn.role, turn.content)

        chat.add_message(role, message['text'])

    return chat


async def reply(client: SocketModeClient, event: dict, chat: Chat):
    """Reply to a message described by event.

    Args:
        client: SocketModeClient instance
        event: Event description
        chat: Chat instance
    """

    try:
        # Show "loading" status
        await client.web_client.reactions_add(
                name=config.tutor.loading_reaction,
                channel=event['channel'],
                timestamp=event['ts'],
                )
    except Exception as e:
        logger.error("Failed to add reaction: %s", e)
        # This is not a critical error, so we can continue

    # Get the response from the chatbot
    try:
        new_turns = await chat.reply()

        # Post the response in the thread.
        result = await client.web_client.chat_postMessage(
                channel=event['channel'],
                thread_ts=event['ts'],
                text=new_turns[-1].content,
                )

        # Save metadata
        if len(new_turns) > 1:
            await save_metadata(get_mdid(event['channel'], result['ts']), new_turns[:-1])
    except Exception as e:
        logger.error("Failed to generate reply: %s", e)
        # Send an error message to the channel, and store some metadata that
        # flags that this new message is an error, so that we can exclude it
        # from the conversation thread in the future.
        # TODO(jnu): may be more robust to use Slack's built-in metadata for
        # this, so that we can simplify our own meta store.
        result = await client.web_client.chat_postMessage(
                channel=event['channel'],
                thread_ts=event['ts'],
                text="Sorry, an error occurred while generating a reply. You can try to repeat the question, or contact my maintainer if the problem persists.",
                )

        await save_error(get_mdid(event['channel'], result['ts']), str(e))
    finally:
        try:
            # Remove the "loading" status
            await client.web_client.reactions_remove(
                    name=config.tutor.loading_reaction,
                    channel=event['channel'],
                    timestamp=event['ts'],
                    )
        except Exception as e:
            logger.error("Failed to remove reaction: %s", e)
            # This is not a critical error, so we can continue


async def handle_message(client: SocketModeClient, req: SocketModeRequest):
    """Process incoming messages.

    Args:
        client: SocketModeClient instance
        req: SocketModeRequest instance
    """
    logger.info("Handling message %s", req.payload['event_id'])

    match req.type:
        case "events_api":
            response = SocketModeResponse(envelope_id=req.envelope_id)
            await client.send_socket_mode_response(response)

            event = req.payload["event"]

            # Filter events from self
            bot_id = await client_user_id(client)
            if event.get('user') == bot_id:
                logger.debug("Ignoring event %s from self",
                             req.payload['event_id'])
                return

            match event.get('type'):
                case 'message':
                    claimed = await claim_message(event['channel'], event['ts'])
                    if not claimed:
                        logger.debug("Message %s already claimed", event['ts'])
                        return

                    chat = await get_thread_history(client, event)
                    if chat.is_relevant():
                        await reply(client, event, chat)
                    else:
                        logger.debug("Ignoring event %s, bot was not tagged",
                                     req.payload['event_id'])

                case 'app_mention':
                    # If the bot hasn't responded yet, send a wave reaction
                    await client.web_client.reactions_add(
                            name="wave",
                            channel=event['channel'],
                            timestamp=event['ts'],
                            )

                    claimed = await claim_message(event['channel'], event['ts'])
                    if not claimed:
                        logger.debug("Message %s already claimed", event['ts'])
                        return

                    chat = await get_thread_history(client, event)
                    await reply(client, event, chat)

                case _:
                    logger.debug("Ignoring event %s of type %s",
                                 req.payload['event_id'], event['type'])

