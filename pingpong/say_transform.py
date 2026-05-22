import json
import logging
from typing import Literal


SAY_MARKER_START = "\ue200"
SAY_MARKER_SEPARATOR = "\ue202"
SAY_MARKER_END = "\ue201"

SayTransformTarget = Literal["display", "speech"]
logger = logging.getLogger(__name__)


class SayTransformer:
    """Streaming transformer for PUA-delimited `say` snippets."""

    def __init__(self, target: SayTransformTarget, *, max_buffer_chars: int = 4096):
        self.target = target
        self._buffer_parts: list[str] = []
        self.max_buffer_chars = max_buffer_chars

    def add(self, text: str) -> str:
        if not text:
            return ""
        self._buffer_parts.append(text)
        buffer = "".join(self._buffer_parts)
        output_parts: list[str] = []
        cursor = 0

        while cursor < len(buffer):
            start_index = buffer.find(SAY_MARKER_START, cursor)
            if start_index < 0:
                output_parts.append(buffer[cursor:])
                cursor = len(buffer)
                break

            if start_index > cursor:
                output_parts.append(buffer[cursor:start_index])
                cursor = start_index

            separator_index = buffer.find(SAY_MARKER_SEPARATOR, start_index + 1)
            if separator_index < 0:
                break

            end_index = buffer.find(SAY_MARKER_END, separator_index + 1)
            if end_index < 0:
                break

            marker_name = buffer[start_index + 1 : separator_index].strip()
            payload = buffer[separator_index + 1 : end_index]
            if marker_name == "say":
                transformed = _transform_payload(payload, self.target)
                if transformed is not None:
                    output_parts.append(transformed)
            cursor = end_index + 1

        if cursor >= len(buffer):
            self._buffer_parts = []
        else:
            self._buffer_parts = [buffer[cursor:]]
            if len(self._buffer_parts[0]) > self.max_buffer_chars:
                logger.warning(
                    "Emitting oversized incomplete say snippet buffer as raw text"
                )
                output_parts.append(self._buffer_parts[0])
                self._buffer_parts = []

        return "".join(output_parts)

    def flush(self) -> str:
        output = ""
        buffer = "".join(self._buffer_parts)
        if buffer:
            if SAY_MARKER_START in buffer:
                logger.warning("Emitting incomplete say snippet buffer as raw text")
            output = buffer
        self._buffer_parts = []
        return output


def transform_say_text(text: str, target: SayTransformTarget) -> str:
    transformer = SayTransformer(target)
    return transformer.add(text) + transformer.flush()


def _transform_payload(payload: str, target: SayTransformTarget) -> str | None:
    try:
        data = json.loads(payload)
    except json.JSONDecodeError:
        logger.debug("Dropping malformed say snippet with invalid JSON")
        return None

    if not isinstance(data, dict):
        logger.debug("Dropping malformed say snippet with non-object payload")
        return None

    speech = data.get("speech")
    if not isinstance(speech, str):
        logger.debug("Dropping malformed say snippet with missing speech string")
        return None

    if target == "speech":
        return speech

    display = data.get("display")
    if not isinstance(display, str):
        logger.debug("Dropping malformed say snippet with missing display string")
        return None
    return display
