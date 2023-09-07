import json
import logging
import dbm
import os

from .chat import ChatTurn
from .config import config


logger = logging.getLogger(__name__)


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


async def save_error(payload: dict, error: str):
    """Save error metadata to a file.

    Args:
        payload: Event payload dictionary
        error: Error message
    """
    # TODO - consolidate this with the other save_metadata
    mdid = get_mdid(payload)
    with dbm.open(_META_CACHE, 'c') as db:
        db[mdid] = json.dumps({'error': error})


async def save_metadata(payload: dict, turns: list[ChatTurn]):
    """Save metadata to a file.

    Args:
        payload: Event payload dictionary
        turns: List of ChatTurns
    """
    mdid = get_mdid(payload)
    with dbm.open(_META_CACHE, 'c') as db:
        db[mdid] = json.dumps([turn._asdict() for turn in turns])


async def load_metadata(payload: dict) -> list[ChatTurn] | dict:
    """Load metadata from a file.

    Args:
        payload: Event payload dictionary

    Returns:
        List of ChatTurns
    """
    mdid = get_mdid(payload)
    with dbm.open(_META_CACHE, 'c') as db:
        if mdid not in db:
            logger.debug("Metadata file %s does not exist", mdid)
            return []
        data = json.loads(db[mdid])
        if isinstance(data, dict):
            return data

        return [ChatTurn(msg['role'], msg['content']) for msg in data]
