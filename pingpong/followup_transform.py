import json
import logging

from pingpong.say_transform import (
    SAY_MARKER_END,
    SAY_MARKER_SEPARATOR,
    SAY_MARKER_START,
)


FOLLOWUP_MARKER_NAME = "followups"
MAX_FOLLOWUP_SUGGESTIONS = 3

logger = logging.getLogger(__name__)


class FollowupTransformer:
    """Streaming transformer for PUA-delimited follow-up suggestion snippets."""

    def __init__(self, *, max_buffer_chars: int = 4096):
        self._buffer_parts: list[str] = []
        self.max_buffer_chars = max_buffer_chars
        self.suggestions: list[str] = []

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
            if marker_name == FOLLOWUP_MARKER_NAME:
                self._add_suggestions(_extract_payload(payload))
            else:
                output_parts.append(buffer[start_index : end_index + 1])
            cursor = end_index + 1

        if cursor >= len(buffer):
            self._buffer_parts = []
        else:
            self._buffer_parts = [buffer[cursor:]]
            if len(self._buffer_parts[0]) > self.max_buffer_chars:
                if _is_incomplete_followup_marker(self._buffer_parts[0]):
                    logger.warning(
                        "Dropping oversized incomplete followups snippet buffer"
                    )
                else:
                    logger.warning(
                        "Emitting oversized incomplete non-followups snippet buffer as raw text"
                    )
                    output_parts.append(self._buffer_parts[0])
                self._buffer_parts = []

        return "".join(output_parts)

    def flush(self) -> str:
        output = ""
        buffer = "".join(self._buffer_parts)
        if buffer:
            if _is_incomplete_followup_marker(buffer):
                logger.warning("Dropping incomplete followups snippet buffer")
            else:
                output = buffer
        self._buffer_parts = []
        return output

    def _add_suggestions(self, suggestions: list[str]) -> None:
        for suggestion in suggestions:
            if suggestion in self.suggestions:
                continue
            if len(self.suggestions) >= MAX_FOLLOWUP_SUGGESTIONS:
                break
            self.suggestions.append(suggestion)

    def consume_suggestions(self) -> list[str]:
        suggestions = list(self.suggestions)
        self.suggestions.clear()
        return suggestions


def strip_followup_snippets(text: str) -> str:
    transformer = FollowupTransformer()
    return transformer.add(text) + transformer.flush()


def extract_followup_suggestions(text: str) -> list[str]:
    transformer = FollowupTransformer()
    transformer.add(text)
    transformer.flush()
    return transformer.suggestions


def _extract_payload(payload: str) -> list[str]:
    try:
        data = json.loads(payload)
    except json.JSONDecodeError:
        logger.debug("Dropping malformed followups snippet with invalid JSON")
        return []

    if not isinstance(data, dict):
        logger.debug("Dropping malformed followups snippet with non-object payload")
        return []

    responses = data.get("responses")
    if not isinstance(responses, list):
        logger.debug("Dropping malformed followups snippet with missing responses list")
        return []

    suggestions: list[str] = []
    for response in responses:
        if not isinstance(response, str):
            logger.debug("Dropping non-string followups response")
            continue
        suggestion = response.strip()
        if not suggestion or suggestion in suggestions:
            continue
        suggestions.append(suggestion)
    return suggestions


def _is_incomplete_followup_marker(buffer: str) -> bool:
    if buffer.startswith(f"{SAY_MARKER_START}{FOLLOWUP_MARKER_NAME}"):
        return True
    if not buffer.startswith(SAY_MARKER_START):
        return False
    marker_prefix = buffer[1:].strip()
    return bool(marker_prefix) and FOLLOWUP_MARKER_NAME.startswith(marker_prefix)
