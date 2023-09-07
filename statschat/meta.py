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


def get_mdid(channel: str, ts: str) -> str:
    """Get the metadata ID for an event.

    Args:
        channel: Slack channel ID
        ts: Message timestamp
    
    Returns:
        Metadata ID
    """
    return f"{channel}:{ts}"


async def save_error(mdid: str, error: str):
    """Save error metadata to a file.

    Args:
        mdid: Metadata ID
        error: Error message
    """
    # TODO - consolidate this with the other save_metadata
    with dbm.open(_META_CACHE, 'c') as db:
        db[mdid] = json.dumps({'error': error})


async def save_metadata(mdid: str, turns: list[ChatTurn]):
    """Save metadata to a file.

    Args:
        mdid: Metadata ID
        turns: List of ChatTurns
    """
    with dbm.open(_META_CACHE, 'c') as db:
        db[mdid] = json.dumps([turn._asdict() for turn in turns])


async def load_metadata(mdid: str) -> list[ChatTurn] | dict:
    """Load metadata from a file.

    Args:
        mdid: Metadata ID

    Returns:
        List of ChatTurns
    """
    with dbm.open(_META_CACHE, 'c') as db:
        if mdid not in db:
            logger.debug("Metadata file %s does not exist", mdid)
            return []
        data = json.loads(db[mdid])
        if isinstance(data, dict):
            return data

        return [ChatTurn(msg['role'], msg['content']) for msg in data]
