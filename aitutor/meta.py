import json
import logging
import dbm
import os
from typing import NamedTuple

from .config import config


logger = logging.getLogger(__name__)


class Role:
    """Roles for chat participants."""

    USER = "user"
    AI = "assistant"
    TOOL = "tool"
    SYSTEM = "system"


ChatTurn = NamedTuple('ChatTurn', [('role', str), ('content', str)])


# TODO - write this to non-local storage!
# And keep a local copy of it until it's written to protect against races!

_DB_DIR = config.tutor.db_dir
os.makedirs(_DB_DIR, exist_ok=True)
_META_CACHE = os.path.join(_DB_DIR, 'meta')


def get_mdid(payload: dict) -> str:
    """Get the metadata ID for a message event.

    Args:
        payload: Event payload dictionary
    
    Returns:
        Metadata ID
    """
    team_id = payload['team_id']
    channel_id = payload['event']['channel']
    msg_ts = payload['event']['ts']
    return f"{team_id}:{channel_id}:{msg_ts}"


def get_channel_mdid(payload: dict) -> str:
    """Get the metadata ID for a channel.

    Args:
        payload: Event payload dictionary
    
    Returns:
        Metadata ID
    """
    team_id = payload['team_id']
    channel_id = payload['event']['channel']
    return f"channel.{team_id}:{channel_id}"


async def save_channel_metadata(payload: dict, meta: dict):
    """Save metadata to a file.

    Args:
        payload: Event payload dictionary
        meta: Metadata to save
    """
    mdid = get_channel_mdid(payload)
    with dbm.open(_META_CACHE, 'c') as db:
        db[mdid] = json.dumps(meta)


async def load_channel_metadata(payload: dict) -> dict:
    """Load metadata from a file.

    Args:
        payload: Event payload dictionary
    
    Returns:
        Metadata dictionary
    """
    mdid = get_channel_mdid(payload)
    with dbm.open(_META_CACHE, 'c') as db:
        if mdid not in db:
            logger.debug("Metadata file %s does not exist", mdid)
            return {}
        return json.loads(db[mdid])


async def save_metadata(payload: dict, meta: dict):
    """Save metadata to a file.

    Args:
        payload: Event payload dictionary
        meta: Metadata to save
    """
    mdid = get_mdid(payload)
    with dbm.open(_META_CACHE, 'c') as db:
        db[mdid] = json.dumps(meta)


async def load_metadata(payload: dict) -> dict:
    """Load metadata from a file.

    Args:
        payload: Event payload dictionary

    Returns:
        Metadata dictionary
    """
    mdid = get_mdid(payload)
    with dbm.open(_META_CACHE, 'c') as db:
        if mdid not in db:
            logger.debug("Metadata file %s does not exist", mdid)
            return {}
        data = json.loads(db[mdid])
        if 'turns' in data:
            data['turns'] = [ChatTurn(*msg) for msg in data['turns']]
        return data
