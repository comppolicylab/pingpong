import logging
from datetime import datetime

from slack_sdk.socket_mode.aiohttp import SocketModeClient
from slack_sdk.socket_mode.response import SocketModeResponse
from slack_sdk.socket_mode.request import SocketModeRequest

from .chat import Chat, Role
from .meta import load_metadata, save_metadata, save_error
from .claim import claim_message
from .prompt import (
        get_prompt_for_channel,
        get_examples_for_channel,
        get_channel_config,
        WrongChannelError,
        )
from .reaction import Reaction, react, unreact


logger = logging.getLogger(__name__)


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


async def get_thread_history(client: SocketModeClient, payload: dict) -> Chat:
    """Get the history of a thread.

    Args:
        client: SocketModeClient instance
        payload: Event payload dictionary

    Returns:
        List of messages in the thread
    """
    event = payload['event']
    bot_id = await client_user_id(client)
    # Today's date as a string like Wednesday, December 4, 2019.
    today = datetime.today().strftime("%A, %B %d, %Y")
    prompt = get_prompt_for_channel(payload['team_id'], event['channel'])
    examples = get_examples_for_channel(payload['team_id'], event['channel'])
    channel_config = get_channel_config(payload['team_id'], event['channel'])
    index_name = channel_config.cs_index_name
    chat = Chat(bot_id,
                prompt.format(date=today),
                index_name,
                examples=examples)

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

    # Add historical messages to the chat
    for message in messages:
        if message.get('type') != 'message':
            logger.debug("Ignoring message %s of type %s",
                         message['ts'], message['type'])
            continue

        if message['ts'] == event['ts']:
            # Ignore the message that triggered this function
            continue

        # Looking for reactions like:
        # [{'count': 1, 'name': '-1', 'users': ['WXYZ']}]
        # The -1 (thumbs-down) means we should ignore this message.
        for reaction in message.get('reactions', []):
            # Use the `Reaction` class to ignore skin tone
            if Reaction.parse_emoji(reaction['name']).name == '-1':
                logger.warning("Ignoring message %s due to downvotes",
                               message['ts'])
                continue

        role = Role.AI if message['user'] == bot_id else Role.USER

        turns = await load_metadata(payload)
        if isinstance(turns, dict) and 'error' in turns:
            logger.warning("Ignoring an error message we sent: %s",
                           turns['error'])
        else:
            for turn in turns:
                chat.add_message(turn.role, turn.content)

        chat.add_message(role, message['text'])

    # Add the new message to the chat
    chat.add_message(Role.USER, event['text'])

    return chat


async def reply(client: SocketModeClient, payload: dict):
    """Reply to a message described by event.

    Args:
        client: SocketModeClient instance
        payload: Event payload
    """
    event = payload['event']
    send_error = False
    loading_reaction = "thinking_face"

    try:
        chat = await get_thread_history(client, payload)
        if not chat.is_relevant():
            return
        else:
            logger.debug("Ignoring event %s (%s), bot was not tagged",
                         payload['event_id'], event['type'])

        # Make sure that the bot is configured to work with this channel.
        channel_config = get_channel_config(payload['team_id'], event['channel'])
        loading_reaction = channel_config.loading_reaction

        # From here on out, if we hit some error generating a response we
        # should send some message to the channel.
        send_error = True

        await react(client, event, loading_reaction)

        new_turns = await chat.reply()

        # Post the response in the thread.
        result = await client.web_client.chat_postMessage(
                channel=event['channel'],
                thread_ts=event['ts'],
                text=new_turns[-1].content,
                )

        # Save metadata
        if len(new_turns) > 1:
            await save_metadata(payload, new_turns[:-1])
    except WrongChannelError as e:
        logger.warning("Ignoring message in wrong channel: %s", e)
        result = await client.web_client.chat_postMessage(
                channel=event['channel'],
                thread_ts=event['ts'],
                text="Sorry, I have not been configured to respond in this channel. Contact the app maintainer and tell them I said: `{}`.".format(str(e)),
                )

        await save_error({
            'team_id': payload['team_id'],
            'event': {
                'channel': event['channel'],
                'ts': result['ts'],
                },
            }, str(e))
    except Exception as e:
        logger.error("Failed to generate reply: %s", e)
        # Send an error message to the channel, and store some metadata that
        # flags that this new message is an error, so that we can exclude it
        # from the conversation thread in the future.
        # TODO(jnu): may be more robust to use Slack's built-in metadata for
        # this, so that we can simplify our own meta store.
        if send_error:
            result = await client.web_client.chat_postMessage(
                    channel=event['channel'],
                    thread_ts=event['ts'],
                    text="Sorry, an error occurred while generating a reply. You can try to repeat the question, or contact my maintainer if the problem persists.",
                    )

            await save_error({
                'team_id': payload['team_id'],
                'event': {
                    'channel': event['channel'],
                    'ts': result['ts'],
                    },
            }, str(e))
    finally:
        await unreact(client, event, loading_reaction)


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

