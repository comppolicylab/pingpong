import logging

from slack_sdk.socket_mode.aiohttp import SocketModeClient
from slack_sdk.socket_mode.response import SocketModeResponse
from slack_sdk.socket_mode.request import SocketModeRequest

from chat import Chat, Role
from config import config
from meta import load_metadata, save_metadata
from claim import claim_message


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


async def get_thread_history(client: SocketModeClient, event) -> Chat:
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

        turns = await load_metadata(message['ts'])
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
    claimed = await claim_message(event['channel'], event['ts'])
    if not claimed:
        logger.debug("Message %s already claimed", event['ts'])
        return

    # Show "loading" status
    await client.web_client.reactions_add(
            name=config.tutor.loading_reaction,
            channel=event['channel'],
            timestamp=event['ts'],
            )

    # Get the response from the chatbot
    new_turns = await chat.chat(event['text'])

    # Post the response in the thread.
    result = await client.web_client.chat_postMessage(
            channel=event['channel'],
            thread_ts=event['ts'],
            text=new_turns[-1].content,
            )

    # Remove the "loading" status
    await client.web_client.reactions_remove(
            name=config.tutor.loading_reaction,
            channel=event['channel'],
            timestamp=event['ts'],
            )

    # Save metadata
    if len(new_turns) > 1:
        await save_metadata(result['ts'], new_turns[:-1])


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

                    chat = await get_thread_history(client, event)
                    await reply(client, event, chat)

                case _:
                    logger.debug("Ignoring event %s of type %s",
                                 req.payload['event_id'], event['type'])

