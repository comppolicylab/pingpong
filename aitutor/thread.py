import os
import json
import logging
from typing import NamedTuple

from slack_sdk.socket_mode.aiohttp import SocketModeClient

from .config import config
from .reaction import Reaction
from .meta import load_metadata


logger = logging.getLogger(__name__)


class Role:
    """Roles for chat participants."""

    USER = "user"
    AI = "assistant"
    TOOL = "tool"
    SYSTEM = "system"


ChatTurn = NamedTuple('ChatTurn', [('role', str), ('content', str)])


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


class SlackThread:

    @classmethod
    def load_from_event(cls,
                        client: SocketModeClient,
                        payload: dict,
                        **kwargs) -> 'SlackThread':
        """Get the history of a thread.

        Args:
            client: SocketModeClient instance
            payload: Event payload dictionary
            **kwargs: Additional keyword args for the constructor

        Returns:
            Slack thread with all message history
        """
        event = payload['event']
        bot_id = await client_user_id(client)
        chat = cls(bot_id, payload, **kwargs)

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

            meta = await load_metadata(payload)
            if 'error' in meta:
                logger.warning("Ignoring an error message we sent: %s",
                               meta['error'])
            else:
                for turn in meta.get('turns', []):
                    chat.add_message(turn.role, turn.content)

            chat.add_message(role, message['text'])

        # Add the new message to the chat
        chat.add_message(Role.USER, event['text'])

        return chat

    def __init__(self,
                 bot_id: str,
                 source_event: dict,
                 directory: str = os.path.join(config.tutor.db_dir, 'threads'),
                 ):
        self.bot_id = bot_id
        self.source_event = source_event
        event = source_event['event']
        self.team_id = source_event['team_id']
        self.channel = event['channel']
        self.channel_type = event.get('channel_type')
        self.ts = event['ts']
        self.thread_ts = event.get('thread_ts', self.ts)
        self.history = list[ChatTurn]()
        self.directory = directory

    def __iter__(self):
        """Iterate over the chat history."""
        return iter(self.history)

    def is_relevant(self) -> bool:
        """Check if the chat is relevant to the bot.

        Returns:
            True if the chat is relevant, False otherwise.
        """
        # DMs are always relevant
        if self.channel_type == 'im':
            return True

        at_mention = f"<@{self.bot_id}>"
        for turn in self.history:
            if turn.role == Role.USER and at_mention in turn.content:
                return True
        return False

    def add_message(self, role: str, text: str):
        """Add a message to the chat history.

        Args:
            role: The role of the message sender.
            text: The message text.
        """
        last_message = self.history[-1] if self.history else None
        # Append to the last message if it was sent by the same role.
        # The language model seems to focus on the most recent USER message,
        # so make sure it has full context.
        # TODO(jnu): There might be multiple parties in the conversation, and
        # I'm not sure whether to try to model this here or not.
        if last_message and last_message.role == role:
            new_text = last_message.content + '\n' + text
            self.history[-1] = ChatTurn(role, new_text)
        else:
            self.history.append(ChatTurn(role, text))

    async def save(self):
        """Persist the chat history."""
        os.makedirs(self.directory, exist_ok=True)
        fn = f"{self.team_id}-{self.channel}-{self.thread_ts}.json"
        thread_path = os.path.join(self.directory, fn) 
        with open(thread_path, 'w') as f:
            json.dump(self.history, f)
