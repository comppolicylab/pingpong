import dbm

from .cache import local_db
from .meta import get_mdid


@local_db("claim")
async def claim_message(payload: dict, *, local_db_path: str) -> bool:
    """Claim a message.

    Currently claims are persisted in a local database. To scale this bot,
    this should be swapped out for a distributed cache like redis.

    Args:
        payload: The payload of the received event

    Returns:
        True if the message was claimed, False otherwise
    """
    id_ = get_mdid(payload)
    with dbm.open(local_db_path, "c") as cache:
        if id_ in cache:
            return False
        cache[id_] = b""
    return True
