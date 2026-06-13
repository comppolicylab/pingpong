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


def _is_marker_name_char(ch: str) -> bool:
    return ch.isalnum() or ch == "_"


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

        marker_start = start_index + 1
        separator_index = text.find(SAY_MARKER_SEPARATOR, marker_start)
        next_start_index = text.find(SAY_MARKER_START, marker_start)
        if separator_index < 0 or (
            next_start_index >= 0 and next_start_index < separator_index
        ):
            marker_end = marker_start
            while marker_end < len(text):
                ch = text[marker_end]
                if ch == SAY_MARKER_START or not _is_marker_name_char(ch):
                    break
                marker_end += 1
            marker_name = text[marker_start:marker_end]
            if marker_name and FOLLOWUP_MARKER_NAME.startswith(marker_name):
                break
            if next_start_index >= 0:
                output_parts.append(text[start_index:next_start_index])
                cursor = next_start_index
                continue
            output_parts.append(text[start_index:])
            break

        marker_name = text[marker_start:separator_index].strip()
        end_index = text.find(SAY_MARKER_END, separator_index + 1)
        next_start_index = text.find(SAY_MARKER_START, separator_index + 1)
        if end_index < 0 or (next_start_index >= 0 and next_start_index < end_index):
            if marker_name == FOLLOWUP_MARKER_NAME:
                break
            if next_start_index >= 0:
                output_parts.append(text[start_index:next_start_index])
                cursor = next_start_index
                continue
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
