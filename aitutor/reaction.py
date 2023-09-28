import logging

from slack_sdk.socket_mode.aiohttp import SocketModeClient

logger = logging.getLogger(__name__)


class Reaction:
    def __init__(self, name: str, skin_tone: str | None = None):
        self.name = name
        self.skin_tone = skin_tone

    @classmethod
    def parse_emoji(cls, emoji: str) -> "Reaction":
        name, _, skin_tone = emoji.partition("::")
        return cls(name, skin_tone or None)

    def __str__(self) -> str:
        if self.skin_tone:
            return f"{self.name}::{self.skin_tone}"
        else:
            return self.name


async def react(client: SocketModeClient, event: dict, reaction: Reaction | str):
    """React to a message described by event.

    Args:
        client: SocketModeClient instance
        event: Event dictionary
        reaction: Reaction emoji
    """
    try:
        await client.web_client.reactions_add(
            name=str(reaction),
            channel=event["channel"],
            timestamp=event["ts"],
        )
    except Exception as e:
        # This is not a critical error, so we can continue
        logger.error(
            "Failed to add reaction %s to %s/%s: %s",
            reaction,
            event["channel"],
            event["ts"],
            e,
        )


async def unreact(client: SocketModeClient, event: dict, reaction: Reaction | str):
    """Remove reaction to a message described by event.

    Args:
        client: SocketModeClient instance
        event: Event dictionary
        reaction: Reaction emoji
    """
    try:
        await client.web_client.reactions_remove(
            name=str(reaction),
            channel=event["channel"],
            timestamp=event["ts"],
        )
    except Exception as e:
        # This is not a critical error, so we can continue
        logger.error(
            "Failed to remove reaction %s from %s/%s: %s",
            reaction,
            event["channel"],
            event["ts"],
            e,
        )
