import dbm
import os

from .meta import _DB_DIR, get_mdid

_CLAIM_CACHE = os.path.join(_DB_DIR, "claim")


async def claim_message(payload: dict) -> bool:
    """Claim a message.

    Currently claims are persisted in a local database. To scale this bot,
    this should be swapped out for a distributed cache like redis.

    Args:
        payload: The payload of the received event

    Returns:
        True if the message was claimed, False otherwise
    """
    id_ = get_mdid(payload)
    with dbm.open(_CLAIM_CACHE, "c") as cache:
        if id_ in cache:
            return False
        cache[id_] = b""
    return True
