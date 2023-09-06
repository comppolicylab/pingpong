import dbm

from .meta import _DB_DIR


_CLAIM_CACHE = os.path.join(_DB_DIR, 'claim')


async def claim_message(channel: str, ts: str) -> bool:
    """Claim a message.

    Currently claims are persisted in a local database. To scale this bot,
    this should be swapped out for a distributed cache like redis.

    Args:
        channel: Channel ID
        ts: Timestamp of the message

    Returns:
        True if the message was claimed, False otherwise
    """
    id_ = f"{channel}:{ts}"
    with dbm.open(_CLAIM_CACHE, 'c') as cache:
        if id_ in cache:
            return False
        cache[id_] = b''
    return True
