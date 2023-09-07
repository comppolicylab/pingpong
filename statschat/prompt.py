from functools import cache
import json

from .config import config, Channel


class WrongChannelError(Exception):
    pass


def get_channel_config(team_id: str, channel_id: str) -> Channel:
    """Get the config for a channel.

    Args:
        team_id: Team (workspace) ID
        channel_id: Channel ID

    Returns:
        Config for the channel
    """
    for channel in config.tutor.channels:
        if channel.channel_id == channel_id and channel.team_id == team_id:
            return channel

    raise WrongChannelError(f"config not found for {team_id}/{channel_id}")


@cache
def get_loading_reaction_for_channel(team_id: str, channel_id: str) -> str:
    """Get the loading reaction for a channel.

    Args:
        team_id: Team (workspace) ID
        channel_id: Channel ID

    Returns:
        Loading reaction for the channel
    """
    channel_config = get_channel_config(team_id, channel_id)
    return channel_config.loading_reaction


@cache
def get_prompt_for_channel(team_id: str, channel_id: str) -> str:
    """Get the prompt for a channel.

    Args:
        team_id: Team (workspace) ID
        channel_id: Channel ID

    Returns:
        Prompt for the channel
    """
    channel_config = get_channel_config(team_id, channel_id)
    with open(channel_config.prompt_file, "r") as f:
        prompt = f.read()
        return prompt.strip()


@cache
def get_examples_for_channel(team_id: str, channel_id: str) -> list[dict]:
    """Get few-shot prompt examples for a channel.
    
    Args:
        team_id: Team (workspace) ID
        channel_id: Channel ID

    Returns:
        Few-shot examples for the channel
    """
    channel_config = get_channel_config(team_id, channel_id)
    if not channel_config.examples_file:
        return []

    with open(channel_config.examples_file, "r") as f:
        examples = []
        for line in f:
            if line.strip():
                examples.append(json.loads(line))

    return examples
