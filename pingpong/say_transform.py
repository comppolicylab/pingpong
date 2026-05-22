import json
from typing import Literal


SAY_MARKER_START = "\ue200"
SAY_MARKER_SEPARATOR = "\ue202"
SAY_MARKER_END = "\ue201"

SayTransformTarget = Literal["display", "speech"]


class SayTransformer:
    """Streaming transformer for PUA-delimited `say` snippets."""

    def __init__(self, target: SayTransformTarget):
        self.target = target
        self._buffer = ""

    def add(self, text: str) -> str:
        if not text:
            return ""
        self._buffer += text
        output_parts: list[str] = []

        while self._buffer:
            start_index = self._buffer.find(SAY_MARKER_START)
            if start_index < 0:
                output_parts.append(self._buffer)
                self._buffer = ""
                break

            if start_index > 0:
                output_parts.append(self._buffer[:start_index])
                self._buffer = self._buffer[start_index:]

            separator_index = self._buffer.find(SAY_MARKER_SEPARATOR, 1)
            if separator_index < 0:
                break

            end_index = self._buffer.find(SAY_MARKER_END, separator_index + 1)
            if end_index < 0:
                break

            marker_name = self._buffer[1:separator_index].strip()
            payload = self._buffer[separator_index + 1 : end_index]
            if marker_name == "say":
                transformed = _transform_payload(payload, self.target)
                if transformed:
                    output_parts.append(transformed)
            self._buffer = self._buffer[end_index + 1 :]

        return "".join(output_parts)

    def flush(self) -> str:
        output = ""
        if self._buffer and SAY_MARKER_START not in self._buffer:
            output = self._buffer
        self._buffer = ""
        return output


def transform_say_text(text: str, target: SayTransformTarget) -> str:
    transformer = SayTransformer(target)
    return transformer.add(text) + transformer.flush()


def _transform_payload(payload: str, target: SayTransformTarget) -> str | None:
    try:
        data = json.loads(payload)
    except json.JSONDecodeError:
        return None

    if not isinstance(data, dict):
        return None

    speech = data.get("speech")
    if not isinstance(speech, str):
        return None

    if target == "speech":
        return speech

    display = data.get("display")
    if not isinstance(display, str):
        return None
    return display
