import dbm
import json
import logging
import os
from functools import cache, wraps
from typing import Any, Callable, NamedTuple

from .config import config

logger = logging.getLogger(__name__)


class Role:
    """Roles for chat participants."""

    USER = "user"
    AI = "assistant"
    TOOL = "tool"
    SYSTEM = "system"


ChatTurn = NamedTuple("ChatTurn", [("role", str), ("content", str)])


# TODO - write this to non-local storage!
# And keep a local copy of it until it's written to protect against races!


@cache
def _get_local_db(name: str) -> str:
    os.makedirs(config.tutor.db_dir, exist_ok=True)
    return os.path.join(config.tutor.db_dir, name)


def local_db(name: str):
    """Decorator to set up a local database and return a path to it.

    Args:
        name - name of local db file
    """

    def dec(f: Callable) -> Callable:
        @wraps(f)
        def wrapper(*args, **kwargs):
            return f(*args, local_db_path=_get_local_db(name), **kwargs)

        return wrapper

    return dec


def get_mdid(payload: dict) -> str:
    """Get the metadata ID for a message event.

    Args:
        payload: Event payload dictionary

    Returns:
        Metadata ID
    """
    team_id = payload["team_id"]
    channel_id = payload["event"]["channel"]
    msg_ts = payload["event"]["ts"]
    return f"{team_id}:{channel_id}:{msg_ts}"


def get_channel_mdid(payload: dict) -> str:
    """Get the metadata ID for a channel.

    Args:
        payload: Event payload dictionary

    Returns:
        Metadata ID
    """
    team_id = payload["team_id"]
    channel_id = payload["event"]["channel"]
    return f"channel.{team_id}:{channel_id}"


@local_db("meta")
async def save_channel_metadata(payload: dict, meta: dict, *, local_db_path: str):
    """Save metadata to a file.

    Args:
        payload: Event payload dictionary
        meta: Metadata to save
    """
    mdid = get_channel_mdid(payload)
    with dbm.open(local_db_path, "c") as db:
        db[mdid] = json.dumps(meta)


@local_db("meta")
async def load_channel_metadata(payload: dict, *, local_db_path: str) -> dict:
    """Load metadata from a file.

    Args:
        payload: Event payload dictionary

    Returns:
        Metadata dictionary
    """
    mdid = get_channel_mdid(payload)
    with dbm.open(local_db_path, "c") as db:
        if mdid not in db:
            logger.debug("Metadata file %s does not exist", mdid)
            return {}
        return json.loads(db[mdid])


@local_db("meta")
async def save_metadata(payload: dict, meta: Any, *, local_db_path: str):
    """Save metadata to a file.

    Args:
        payload: Event payload dictionary
        meta: Metadata to save
    """
    mdid = get_mdid(payload)
    with dbm.open(local_db_path, "c") as db:
        db[mdid] = json.dumps(meta)


@local_db("meta")
async def load_metadata(payload: dict, *, local_db_path: str) -> dict:
    """Load metadata from a file.

    Args:
        payload: Event payload dictionary

    Returns:
        Metadata dictionary
    """
    mdid = get_mdid(payload)
    with dbm.open(local_db_path, "c") as db:
        if mdid not in db:
            logger.debug("Metadata file %s does not exist", mdid)
            return {}
        data = json.loads(db[mdid])
        if "turns" in data:
            data["turns"] = [ChatTurn(*msg) for msg in data["turns"]]
        return data
