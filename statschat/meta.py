import os
import json
import logging

from chat import ChatTurn


logger = logging.getLogger(__name__)


# TODO - write this to non-local storage!
# And keep a local copy of it until it's written to protect against races!

async def save_metadata(mdid: str, turns: list[ChatTurn]):
    """Save metadata to a file.

    Args:
        mdid: Metadata ID
        turns: List of ChatTurns
    """
    # Create the metadata cache directory if it doesn't exist
    if not os.path.exists('.metacache'):
        os.makedirs('.metacache')

    # Save metadata to the file
    with open(f'.metacache/{mdid}.json', 'w') as f:
        json.dump([turn._asdict() for turn in turns], f)


async def load_metadata(mdid: str) -> list[ChatTurn]:
    # Load metadata from the message
    if os.path.exists(f'.metacache/{mdid}.json'):
        with open(f'.metacache/{mdid}.json', 'r') as f:
            metadata = json.load(f)
            return [ChatTurn(msg['role'], msg['content']) for msg in metadata]
    else:
        logger.debug("Metadata file %s does not exist", mdid)

    return []
