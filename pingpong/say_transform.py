import json
import logging
from typing import Literal


SAY_MARKER_START = "\ue200"
SAY_MARKER_SEPARATOR = "\ue202"
SAY_MARKER_END = "\ue201"

SNIPPET_MARKERS = frozenset({"say", "svg", "mermaid"})
FLUSH_MARKERS = frozenset({"svg", "mermaid"})
FOLLOWUP_MARKER_NAME = "followups"
MAX_FOLLOWUP_SUGGESTIONS = 3

SUPPORTED_MARKERS = SNIPPET_MARKERS | {FOLLOWUP_MARKER_NAME}

PuaStreamTarget = Literal["display", "speech"]
SnippetTransformTarget = PuaStreamTarget

logger = logging.getLogger(__name__)


class _StreamingSnippetJsonParser:
    """Incrementally parse block JSON and stream selected string fields."""

    _EXPECT_OBJECT_START = "expect_object_start"
    _EXPECT_KEY_OR_END = "expect_key_or_end"
    _KEY = "key"
    _AFTER_KEY = "after_key"
    _BEFORE_VALUE = "before_value"
    _VALUE_STRING = "value_string"
    _VALUE_LITERAL = "value_literal"
    _AFTER_VALUE = "after_value"
    _DONE = "done"
    _INVALID = "invalid"

    def __init__(
        self,
        *,
        target: PuaStreamTarget,
        marker_name: str,
        max_speech_buffer_chars: int,
    ):
        self.target = target
        self.marker_name = marker_name
        self.max_speech_buffer_chars = max_speech_buffer_chars
        self.state = self._EXPECT_OBJECT_START
        self.current_key = ""
        self.current_value_key: str | None = None
        self.literal_buf = ""
        self.escape = False
        self.unicode_escape: str | None = None
        self.pending_high_surrogate: int | None = None
        self.display_speech_fallback = ""
        self.display_speech_fallback_overflowed = False
        self.saw_content = False
        self.saw_speech = False
        self.started_content = False
        self.emitted_flush_signal = False
        self.invalid_reason: str | None = None

    @property
    def done(self) -> bool:
        return self.state == self._DONE

    @property
    def invalid(self) -> bool:
        return self.state == self._INVALID

    @property
    def in_string(self) -> bool:
        return self.state in {self._KEY, self._VALUE_STRING}

    def feed(self, ch: str, out: list[str]) -> bool:
        """Consume one char. Return True when a TTS flush signal should fire."""
        if self.invalid or self.done:
            return False

        if self.state == self._EXPECT_OBJECT_START:
            if ch.isspace():
                return False
            if ch == "{":
                self.state = self._EXPECT_KEY_OR_END
                return False
            return self._invalidate("expected JSON object")

        if self.state == self._EXPECT_KEY_OR_END:
            if ch.isspace():
                return False
            if ch == "}":
                self.state = self._DONE
                return False
            if ch == '"':
                self.current_key = ""
                self.escape = False
                self.unicode_escape = None
                self.pending_high_surrogate = None
                self.state = self._KEY
                return False
            return self._invalidate("expected object key")

        if self.state == self._KEY:
            decoded, ended = self._feed_json_string_char(ch)
            if decoded:
                self.current_key += decoded
            if decoded is None:
                return False
            if ended:
                self.state = self._AFTER_KEY
                return False
            return False

        if self.state == self._AFTER_KEY:
            if ch.isspace():
                return False
            if ch == ":":
                self.state = self._BEFORE_VALUE
                return False
            return self._invalidate("expected ':' after object key")

        if self.state == self._BEFORE_VALUE:
            if ch.isspace():
                return False
            self.current_value_key = self.current_key
            if ch == '"':
                self.escape = False
                self.unicode_escape = None
                self.pending_high_surrogate = None
                self.state = self._VALUE_STRING
                if self.current_value_key == "content":
                    self.saw_content = True
                    self.started_content = True
                    return self._should_flush_before_content()
                return False
            if self.current_value_key in {"content", "speech"}:
                return self._invalidate("snippet speech/content values must be strings")
            if ch in "{[":
                return self._invalidate("snippet JSON values must be strings")
            self.literal_buf = ch
            self.state = self._VALUE_LITERAL
            return False

        if self.state == self._VALUE_STRING:
            decoded, ended = self._feed_json_string_char(ch)
            if decoded:
                self._consume_value_char(decoded, out)
            if decoded is None:
                return False
            if ended:
                should_flush = (
                    self.current_value_key == "speech"
                    and self.started_content
                    and self._should_flush_after_speech()
                )
                self.state = self._AFTER_VALUE
                self.current_value_key = None
                return should_flush
            return False

        if self.state == self._VALUE_LITERAL:
            if ch in ",}":
                if (
                    self.current_value_key in {"content", "speech"}
                    or not self.literal_buf.strip()
                ):
                    return self._invalidate("snippet JSON values must be strings")
                self.current_value_key = None
                if ch == ",":
                    self.state = self._EXPECT_KEY_OR_END
                else:
                    self.state = self._DONE
                return False
            if ch.isspace():
                if (
                    self.current_value_key in {"content", "speech"}
                    or not self.literal_buf.strip()
                ):
                    return self._invalidate("snippet JSON values must be strings")
                self.current_value_key = None
                self.state = self._AFTER_VALUE
                return False
            self.literal_buf += ch
            return False

        if self.state == self._AFTER_VALUE:
            if ch.isspace():
                return False
            if ch == ",":
                self.state = self._EXPECT_KEY_OR_END
                return False
            if ch == "}":
                self.state = self._DONE
                return False
            return self._invalidate("expected ',' or '}' after object value")

        return False

    def flush_output(self) -> str:
        if (
            self.target == "display"
            and not self.saw_content
            and not self.display_speech_fallback_overflowed
        ):
            return self.display_speech_fallback
        return ""

    def _should_flush_before_content(self) -> bool:
        if self.target != "speech" or self.marker_name not in FLUSH_MARKERS:
            return False
        if not self.saw_speech or self.emitted_flush_signal:
            return False
        self.emitted_flush_signal = True
        return True

    def _should_flush_after_speech(self) -> bool:
        if self.target != "speech" or self.marker_name not in FLUSH_MARKERS:
            return False
        if not self.saw_speech or self.emitted_flush_signal:
            return False
        self.emitted_flush_signal = True
        return True

    def _feed_json_string_char(self, ch: str) -> tuple[str | None, bool]:
        if self.unicode_escape is not None:
            if ch.lower() not in "0123456789abcdef":
                self._invalidate("invalid unicode escape")
                return None, False
            self.unicode_escape += ch
            if len(self.unicode_escape) == 4:
                decoded = self._decode_unicode_escape(int(self.unicode_escape, 16))
                self.unicode_escape = None
                self.escape = False
                return decoded, False
            return None, False

        if self.escape:
            self.escape = False
            if self.pending_high_surrogate is not None and ch != "u":
                self._invalidate("invalid unicode surrogate pair")
                return None, False
            match ch:
                case '"':
                    return '"', False
                case "\\":
                    return "\\", False
                case "/":
                    return "/", False
                case "b":
                    return "\b", False
                case "f":
                    return "\f", False
                case "n":
                    return "\n", False
                case "r":
                    return "\r", False
                case "t":
                    return "\t", False
                case "u":
                    self.unicode_escape = ""
                    self.escape = True
                    return None, False
                case _:
                    if self.current_value_key == "content":
                        return "\\" + ch, False
                    self._invalidate("invalid string escape")
                    return None, False

        if self.pending_high_surrogate is not None:
            if ch != "\\":
                self._invalidate("invalid unicode surrogate pair")
                return None, False
            self.escape = True
            return None, False

        if ch == "\\":
            self.escape = True
            return None, False
        if ch == '"':
            return "", True
        return ch, False

    def _decode_unicode_escape(self, code_unit: int) -> str | None:
        if 0xD800 <= code_unit <= 0xDBFF:
            if self.pending_high_surrogate is not None:
                self._invalidate("invalid unicode surrogate pair")
                return None
            self.pending_high_surrogate = code_unit
            return None

        if 0xDC00 <= code_unit <= 0xDFFF:
            if self.pending_high_surrogate is None:
                self._invalidate("invalid unicode surrogate pair")
                return None
            high = self.pending_high_surrogate
            self.pending_high_surrogate = None
            code_point = 0x10000 + ((high - 0xD800) << 10) + (code_unit - 0xDC00)
            return chr(code_point)

        if self.pending_high_surrogate is not None:
            self._invalidate("invalid unicode surrogate pair")
            return None

        return chr(code_unit)

    def _consume_value_char(self, ch: str, out: list[str]) -> None:
        if self.current_value_key == "speech":
            self.saw_speech = True
            if self.target == "speech":
                out.append(ch)
                return
            if not self.saw_content:
                self.display_speech_fallback += ch
                if len(self.display_speech_fallback) > self.max_speech_buffer_chars:
                    logger.warning(
                        "Speech fallback buffer exceeded cap; dropping fallback"
                    )
                    self.display_speech_fallback = ""
                    self.display_speech_fallback_overflowed = True
            return

        if self.current_value_key == "content":
            self.saw_content = True
            if self.target == "display":
                out.append(ch)

    def _invalidate(self, reason: str) -> bool:
        self.state = self._INVALID
        self.invalid_reason = reason
        return False


class PuaStreamTransformer:
    """Streaming transformer for PUA-delimited blocks.

    Block shape::

        \\ue200<marker>\\ue202{"speech":"spoken text","content":"visible text"}\\ue201

    Known markers:

    - ``say``, ``svg``, ``mermaid`` — JSON blocks using common ``speech`` and
      ``content`` keys. The speech target streams ``speech`` string characters
      as they decode. The display target streams ``content`` string characters
      as they decode. If ``content`` is omitted, display falls back to
      ``speech``. If ``speech`` is omitted, the speech target emits nothing.
      An empty ``content`` string is an explicit empty display. For ``svg`` and
      ``mermaid``, starting the ``content`` field emits a flush signal so TTS
      can play speech before long silent content.

    - ``followups`` — payload is buffered until the end marker, then parsed as
      JSON. Suggestions are collected via ``consume_followup_suggestions``.

    Unknown markers are dropped so raw private-use delimiters do not leak into
    display or speech output.
    """

    _OUTSIDE = "outside"
    _MARKER = "marker"
    _SNIPPET_JSON = "snippet_json"
    _FOLLOWUP_PAYLOAD = "followup_payload"
    _RECOVERING = "recovering"

    def __init__(
        self,
        target: PuaStreamTarget,
        *,
        max_marker_chars: int = 64,
        max_speech_buffer_chars: int = 1024,
        max_followup_buffer_chars: int = 4096,
    ):
        self.target = target
        self.max_marker_chars = max_marker_chars
        self.max_speech_buffer_chars = max_speech_buffer_chars
        self.max_followup_buffer_chars = max_followup_buffer_chars
        self._buffer = ""
        self._state = self._OUTSIDE
        self._marker_buf = ""
        self._marker_name: str | None = None
        self._json_parser: _StreamingSnippetJsonParser | None = None
        self._followup_buf = ""
        self._pending_flushes = 0
        self._followup_suggestions: list[str] = []

    def add(self, text: str) -> str:
        if not text:
            return ""
        self._buffer += text
        out: list[str] = []
        while self._advance(out):
            pass
        return "".join(out)

    def flush(self) -> str:
        out: list[str] = []
        if self._state == self._OUTSIDE:
            if self._buffer:
                out.append(self._buffer)
                self._buffer = ""
        elif self._state == self._MARKER:
            logger.warning("Dropping incomplete snippet (marker phase)")
            self._buffer = ""
            self._reset()
        elif self._state == self._SNIPPET_JSON:
            logger.warning("Flushing incomplete snippet JSON")
            if self._json_parser:
                out.append(self._json_parser.flush_output())
            self._buffer = ""
            self._reset()
        elif self._state == self._FOLLOWUP_PAYLOAD:
            logger.warning("Dropping incomplete followups snippet buffer")
            self._buffer = ""
            self._followup_buf = ""
            self._reset()
        elif self._state == self._RECOVERING:
            logger.warning("Dropping incomplete malformed snippet buffer")
            self._buffer = ""
            self._reset()
        return "".join(out)

    def consume_flush_signals(self) -> int:
        n = self._pending_flushes
        self._pending_flushes = 0
        return n

    def consume_followup_suggestions(self) -> list[str]:
        suggestions = list(self._followup_suggestions)
        self._followup_suggestions.clear()
        return suggestions

    def _advance(self, out: list[str]) -> bool:
        if self._state == self._OUTSIDE:
            return self._step_outside(out)
        if self._state == self._MARKER:
            return self._step_marker(out)
        if self._state == self._SNIPPET_JSON:
            return self._step_snippet_json(out)
        if self._state == self._FOLLOWUP_PAYLOAD:
            return self._step_followup(out)
        if self._state == self._RECOVERING:
            return self._step_recovering()
        return False

    def _step_outside(self, out: list[str]) -> bool:
        idx = self._buffer.find(SAY_MARKER_START)
        if idx < 0:
            if self._buffer:
                out.append(self._buffer)
                self._buffer = ""
            return False
        if idx > 0:
            out.append(self._buffer[:idx])
        self._buffer = self._buffer[idx + 1 :]
        self._state = self._MARKER
        self._marker_buf = ""
        return True

    def _step_marker(self, out: list[str]) -> bool:
        sep_idx = self._buffer.find(SAY_MARKER_SEPARATOR)
        if sep_idx < 0:
            self._marker_buf += self._buffer
            self._buffer = ""
            if len(self._marker_buf) > self.max_marker_chars:
                logger.warning("Dropping snippet with oversized marker name buffer")
                self._reset()
                self._state = self._RECOVERING
                return True
            return False
        self._marker_buf += self._buffer[:sep_idx]
        self._buffer = self._buffer[sep_idx + 1 :]
        marker_name = self._marker_buf.strip()
        if marker_name in SNIPPET_MARKERS:
            self._marker_name = marker_name
            self._json_parser = _StreamingSnippetJsonParser(
                target=self.target,
                marker_name=marker_name,
                max_speech_buffer_chars=self.max_speech_buffer_chars,
            )
            self._state = self._SNIPPET_JSON
        elif marker_name == FOLLOWUP_MARKER_NAME:
            self._marker_name = marker_name
            self._state = self._FOLLOWUP_PAYLOAD
            self._followup_buf = ""
            if self.target == "speech":
                self._pending_flushes += 1
        else:
            logger.debug("Dropping snippet with unknown marker name: %s", marker_name)
            self._drop_until_marker_end()
        return True

    def _step_snippet_json(self, out: list[str]) -> bool:
        if not self._buffer:
            return False
        parser = self._json_parser
        if parser is None:
            self._reset()
            return True

        while self._buffer:
            ch = self._buffer[0]
            self._buffer = self._buffer[1:]

            if ch == SAY_MARKER_START and parser.done:
                self._buffer = ch + self._buffer
                out.append(parser.flush_output())
                self._reset()
                return True

            if ch == SAY_MARKER_END and parser.done:
                out.append(parser.flush_output())
                self._reset()
                return True

            if ch == SAY_MARKER_END and parser.in_string:
                logger.debug("Dropping malformed snippet JSON with embedded end marker")
                self._recover_after_invalid()
                return bool(self._buffer)

            if ch == SAY_MARKER_END:
                logger.debug("Dropping malformed snippet JSON before complete object")
                self._reset()
                return True

            if parser.done:
                if ch.isspace():
                    continue
                logger.debug("Dropping malformed snippet JSON after complete object")
                self._recover_after_invalid()
                return bool(self._buffer)

            should_flush = parser.feed(ch, out)
            if should_flush:
                self._pending_flushes += 1
            if parser.invalid:
                logger.debug(
                    "Dropping malformed snippet JSON: %s",
                    parser.invalid_reason,
                )
                self._recover_after_invalid()
                return bool(self._buffer)

        return False

    def _drop_until_marker_end(self) -> None:
        end_idx = self._buffer.find(SAY_MARKER_END)
        if end_idx < 0:
            self._buffer = ""
            self._state = self._RECOVERING
        else:
            self._buffer = self._buffer[end_idx + 1 :]
            self._reset()

    def _recover_after_invalid(self) -> None:
        start_idx = self._buffer.find(SAY_MARKER_START)
        end_idx = self._buffer.find(SAY_MARKER_END)
        if start_idx < 0 and end_idx < 0:
            self._buffer = ""
            self._state = self._RECOVERING
            return
        if end_idx >= 0 and (start_idx < 0 or end_idx < start_idx):
            self._buffer = self._buffer[end_idx + 1 :]
            self._reset()
            return
        self._buffer = self._buffer[start_idx:]
        self._reset()

    def _step_followup(self, out: list[str]) -> bool:
        if not self._buffer:
            return False
        end_idx = self._buffer.find(SAY_MARKER_END)
        if end_idx < 0:
            self._followup_buf += self._buffer
            self._buffer = ""
            if len(self._followup_buf) > self.max_followup_buffer_chars:
                logger.warning("Dropping oversized incomplete followups snippet buffer")
                self._followup_buf = ""
                self._reset()
                self._state = self._RECOVERING
                return True
            return False
        self._followup_buf += self._buffer[:end_idx]
        self._buffer = self._buffer[end_idx + 1 :]
        self._collect_followup_payload(self._followup_buf)
        self._followup_buf = ""
        self._reset()
        return True

    def _collect_followup_payload(self, payload: str) -> None:
        for suggestion in _extract_followup_responses(payload):
            if suggestion in self._followup_suggestions:
                continue
            if len(self._followup_suggestions) >= MAX_FOLLOWUP_SUGGESTIONS:
                break
            self._followup_suggestions.append(suggestion)

    def _step_recovering(self) -> bool:
        if not self._buffer:
            return False
        start_idx = self._buffer.find(SAY_MARKER_START)
        end_idx = self._buffer.find(SAY_MARKER_END)
        if start_idx < 0 and end_idx < 0:
            self._buffer = ""
            return False
        if end_idx >= 0 and (start_idx < 0 or end_idx < start_idx):
            self._buffer = self._buffer[end_idx + 1 :]
        else:
            self._buffer = self._buffer[start_idx:]
        self._reset()
        return True

    def _reset(self) -> None:
        self._state = self._OUTSIDE
        self._marker_buf = ""
        self._marker_name = None
        self._json_parser = None


SnippetTransformer = PuaStreamTransformer
SayTransformer = PuaStreamTransformer


def transform_say_text(text: str, target: PuaStreamTarget) -> str:
    transformer = PuaStreamTransformer(target)
    return transformer.add(text) + transformer.flush()


def _extract_followup_responses(payload: str) -> list[str]:
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
