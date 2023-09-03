import json
import logging
import dbm

from chat import ChatTurn


logger = logging.getLogger(__name__)


# TODO - write this to non-local storage!
# And keep a local copy of it until it's written to protect against races!

_META_CACHE = 'meta'


async def save_metadata(mdid: str, turns: list[ChatTurn]):
    """Save metadata to a file.

    Args:
        mdid: Metadata ID
        turns: List of ChatTurns
    """
    with dbm.open(_META_CACHE, 'c') as db:
        db[mdid] = json.dumps([turn._asdict() for turn in turns])


async def load_metadata(mdid: str) -> list[ChatTurn]:
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
        return [ChatTurn(msg['role'], msg['content']) for msg in data]
