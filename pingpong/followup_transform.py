import logging

from pingpong.say_transform import (
    FOLLOWUP_MARKER_NAME,
    MAX_FOLLOWUP_SUGGESTIONS,
    PuaStreamTransformer,
    SAY_MARKER_END,
    SAY_MARKER_SEPARATOR,
    SAY_MARKER_START,
)

__all__ = [
    "FOLLOWUP_MARKER_NAME",
    "MAX_FOLLOWUP_SUGGESTIONS",
    "extract_followup_suggestions",
    "strip_followup_snippets",
]


logger = logging.getLogger(__name__)


def strip_followup_snippets(text: str) -> str:
    """Remove followup snippets from `text`, preserving all other content.

    Unlike the streaming transformer used in the live response pipeline,
    this leaves say/svg/mermaid snippets intact so callers can apply
    further display- or speech-target transforms afterward.
    """

    if not text:
        return ""
    output_parts: list[str] = []
    cursor = 0
    while cursor < len(text):
        start_index = text.find(SAY_MARKER_START, cursor)
        if start_index < 0:
            output_parts.append(text[cursor:])
            break

        if start_index > cursor:
            output_parts.append(text[cursor:start_index])

        separator_index = text.find(SAY_MARKER_SEPARATOR, start_index + 1)
        if separator_index < 0:
            marker_prefix = text[start_index + 1 :].strip()
            if marker_prefix and FOLLOWUP_MARKER_NAME.startswith(marker_prefix):
                break
            output_parts.append(text[start_index:])
            break

        marker_name = text[start_index + 1 : separator_index].strip()
        end_index = text.find(SAY_MARKER_END, separator_index + 1)
        if end_index < 0:
            if marker_name == FOLLOWUP_MARKER_NAME:
                break
            output_parts.append(text[start_index:])
            break

        if marker_name == FOLLOWUP_MARKER_NAME:
            cursor = end_index + 1
            continue

        output_parts.append(text[start_index : end_index + 1])
        cursor = end_index + 1

    return "".join(output_parts)


def extract_followup_suggestions(text: str) -> list[str]:
    if not text:
        return []
    transformer = PuaStreamTransformer("display")
    transformer.add(text)
    transformer.flush()
    return transformer.consume_followup_suggestions()
