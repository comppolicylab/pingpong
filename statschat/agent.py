import logging

from slack_sdk.socket_mode.aiohttp import SocketModeClient
from slack_sdk.socket_mode.response import SocketModeResponse
from slack_sdk.socket_mode.request import SocketModeRequest

from chat import Chat, Role
from config import config
from meta import load_metadata, save_metadata


logger = logging.getLogger(__name__)


# Load the system prompt from the file
with open(config.tutor.prompt_file, "r") as f:
    prompt = f.read()


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
    chat = Chat(prompt)
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
    bot_id = await client_user_id(client)

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

        last_message = chat.last_message()
        if last_message and last_message.role == role:
            # If the last message was from the same role, add the message to
            # the last message
            last_message.content += '\n\n' + message['text']
        else:
            # Otherwise, create a new message
            chat.add_message(role, message['text'])

    return chat


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
            if event.get('user') == await client_user_id(client):
                logger.debug("Ignoring event %s from self",
                             req.payload['event_id'])
                return

            if event.get("type") == "message" and event.get("subtype") is None:
                chat = await get_thread_history(client, event)
                if Role.AI not in [turn.role for turn in chat.history]:
                    # If the bot hasn't responded yet, send a wave reaction
                    await client.web_client.reactions_add(
                            name="wave",
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

                # Save metadata
                if len(new_turns) > 1:
                    await save_metadata(result['ts'], new_turns[:-1])
