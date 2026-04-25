import logging
import ssl
from collections.abc import AsyncGenerator
from html import unescape
import re
from typing import Any
from urllib.parse import quote, urlencode

import aiohttp
import httpx
import orjson
from elevenlabs.client import AsyncElevenLabs
from elevenlabs.core.api_error import ApiError as ElevenLabsApiError
from elevenlabs.core.request_options import RequestOptions
from elevenlabs.errors import (
    UnauthorizedError as ElevenLabsUnauthorizedError,
)

from pingpong import schemas
from pingpong.class_credential_validation import (
    ClassCredentialValidationSSLError,
    ClassCredentialValidationUnavailableError,
    ClassCredentialVoiceValidationError,
)
from pingpong.log_utils import sanitize_for_log

logger = logging.getLogger(__name__)

ELEVENLABS_VOICE_VALIDATION_SAMPLE_TEXT = (
    "Here is a sample of the voice PingPong will use for lecture video mode."
)
ELEVENLABS_VOICE_VALIDATION_OUTPUT_FORMAT = "opus_48000_32"
ELEVENLABS_VOICE_VALIDATION_CONTENT_TYPE = "audio/ogg"
ELEVENLABS_VOICE_SAMPLE_TEXT_HEADER = "X-PingPong-Voice-Sample-Text"
ELEVENLABS_STREAMING_TTS_CONNECT_TIMEOUT = aiohttp.ClientWSTimeout(
    ws_receive=30.0,
    ws_close=10.0,
)


def get_elevenlabs_client(api_key: str) -> AsyncElevenLabs:
    if not api_key:
        raise ValueError("API key is required")
    return AsyncElevenLabs(api_key=api_key)


async def _collect_audio_chunks(audio_stream) -> bytes:
    chunks: list[bytes] = []
    async for chunk in audio_stream:
        if chunk:
            chunks.append(chunk)
    return b"".join(chunks)


def _normalize_elevenlabs_error_body(body: Any) -> dict[str, Any] | None:
    if hasattr(body, "model_dump"):
        body = body.model_dump()
    elif hasattr(body, "dict"):
        body = body.dict()

    return body if isinstance(body, dict) else None


def _is_invalid_elevenlabs_voice_error(exc: ElevenLabsApiError) -> bool:
    body = _normalize_elevenlabs_error_body(exc.body)
    if body is None:
        return False

    detail = body.get("detail", body)
    if not isinstance(detail, dict):
        return False

    identifier = str(
        detail.get("code") or detail.get("status") or detail.get("type") or ""
    ).lower()
    param = str(detail.get("param") or "").lower()
    message = str(detail.get("message") or detail.get("error") or "").lower()

    if identifier in {"voice_not_found", "invalid_voice_id"}:
        return True

    if param == "voice_id":
        return True

    return (
        exc.status_code in {400, 404, 422}
        and "voice" in message
        and ("not found" in message or "invalid" in message)
    )


async def synthesize_elevenlabs_voice_sample(
    api_key: str,
    voice_id: str,
) -> tuple[str, str, bytes]:
    try:
        content_type, audio = await synthesize_elevenlabs_speech(
            api_key,
            voice_id,
            ELEVENLABS_VOICE_VALIDATION_SAMPLE_TEXT,
            timeout_seconds=15,
        )
    except ClassCredentialValidationSSLError as exc:
        raise ClassCredentialValidationSSLError(
            provider=schemas.ClassCredentialProvider.ELEVENLABS,
            message="Unable to validate the ElevenLabs voice due to an SSL error.",
        ) from exc
    except ClassCredentialValidationUnavailableError as exc:
        raise ClassCredentialValidationUnavailableError(
            provider=schemas.ClassCredentialProvider.ELEVENLABS,
            message="Unable to validate the ElevenLabs voice right now.",
        ) from exc
    return (
        ELEVENLABS_VOICE_VALIDATION_SAMPLE_TEXT,
        content_type,
        audio,
    )


async def synthesize_elevenlabs_speech(
    api_key: str,
    voice_id: str,
    text: str,
    *,
    timeout_seconds: int | None = None,
) -> tuple[str, bytes]:
    safe_voice_id = sanitize_for_log(voice_id)
    try:
        client = get_elevenlabs_client(api_key)
        request_options = (
            RequestOptions(timeout_in_seconds=timeout_seconds)
            if timeout_seconds is not None
            else None
        )
        audio = await _collect_audio_chunks(
            client.text_to_speech.convert(
                voice_id=voice_id,
                text=text,
                output_format=ELEVENLABS_VOICE_VALIDATION_OUTPUT_FORMAT,
                request_options=request_options,
            ),
        )
    except ElevenLabsUnauthorizedError as exc:
        logger.warning(
            "ElevenLabs speech synthesis failed due to credential error. voice_id=%s",
            safe_voice_id,
            exc_info=exc,
        )
        raise ClassCredentialValidationUnavailableError(
            provider=schemas.ClassCredentialProvider.ELEVENLABS,
            message="Unable to generate the ElevenLabs audio right now.",
        ) from exc
    except (httpx.TimeoutException, TimeoutError) as exc:
        logger.warning(
            "Timed out generating ElevenLabs audio for voice_id=%s.",
            safe_voice_id,
            exc_info=exc,
        )
        raise ClassCredentialValidationUnavailableError(
            provider=schemas.ClassCredentialProvider.ELEVENLABS,
            message="Unable to generate the ElevenLabs audio right now.",
        ) from exc
    except ssl.SSLError as exc:
        logger.warning(
            "SSL error generating ElevenLabs audio for voice_id=%s.",
            safe_voice_id,
            exc_info=exc,
        )
        raise ClassCredentialValidationSSLError(
            provider=schemas.ClassCredentialProvider.ELEVENLABS,
            message="Unable to generate the ElevenLabs audio due to an SSL error.",
        ) from exc
    except ElevenLabsApiError as exc:
        if _is_invalid_elevenlabs_voice_error(exc):
            logger.info(
                "ElevenLabs speech synthesis rejected voice_id=%s",
                safe_voice_id,
                exc_info=exc,
            )
            raise ClassCredentialVoiceValidationError(
                "Invalid voice ID provided. Please choose a different voice."
            ) from exc
        logger.warning(
            "Failed to generate ElevenLabs audio for voice_id=%s due to provider API error.",
            safe_voice_id,
            exc_info=exc,
        )
        raise ClassCredentialValidationUnavailableError(
            provider=schemas.ClassCredentialProvider.ELEVENLABS,
            message="Unable to generate the ElevenLabs audio right now.",
        ) from exc
    except ValueError as exc:
        logger.warning(
            "ElevenLabs speech synthesis failed due to credential error. voice_id=%s",
            safe_voice_id,
            exc_info=exc,
        )
        raise ClassCredentialValidationUnavailableError(
            provider=schemas.ClassCredentialProvider.ELEVENLABS,
            message="Unable to generate the ElevenLabs audio right now.",
        ) from exc
    except Exception as exc:
        logger.warning(
            "Failed to generate ElevenLabs audio for voice_id=%s due to provider error.",
            safe_voice_id,
            exc_info=exc,
        )
        raise ClassCredentialValidationUnavailableError(
            provider=schemas.ClassCredentialProvider.ELEVENLABS,
            message="Unable to generate the ElevenLabs audio right now.",
        ) from exc

    if not audio:
        logger.warning(
            "ElevenLabs speech synthesis returned empty audio. voice_id=%s",
            safe_voice_id,
        )
        raise ClassCredentialValidationUnavailableError(
            provider=schemas.ClassCredentialProvider.ELEVENLABS,
            message="Unable to generate the ElevenLabs audio right now.",
        )

    return (ELEVENLABS_VOICE_VALIDATION_CONTENT_TYPE, audio)


async def validate_elevenlabs_api_key(api_key: str) -> bool:
    safe_provider = sanitize_for_log(schemas.ClassCredentialProvider.ELEVENLABS.value)
    try:
        client = get_elevenlabs_client(api_key)
        await client.voices.settings.get_default(
            request_options=RequestOptions(timeout_in_seconds=10)
        )
        return True
    except ValueError:
        return False
    except ElevenLabsUnauthorizedError:
        return False
    except (httpx.TimeoutException, TimeoutError) as exc:
        logger.warning(
            "Timed out validating %s class credential.",
            safe_provider,
            exc_info=exc,
        )
        raise ClassCredentialValidationUnavailableError(
            provider=schemas.ClassCredentialProvider.ELEVENLABS,
            message="Unable to validate the ElevenLabs API key right now.",
        ) from exc
    except ssl.SSLError as exc:
        logger.warning(
            "SSL error validating %s class credential.",
            safe_provider,
            exc_info=exc,
        )
        raise ClassCredentialValidationSSLError(
            provider=schemas.ClassCredentialProvider.ELEVENLABS,
            message="Unable to validate the ElevenLabs API key due to an SSL error.",
        ) from exc
    except Exception as exc:
        logger.warning(
            "Failed to validate %s class credential due to provider error.",
            safe_provider,
            exc_info=exc,
        )
        raise ClassCredentialValidationUnavailableError(
            provider=schemas.ClassCredentialProvider.ELEVENLABS,
            message="Unable to validate the ElevenLabs API key right now.",
        ) from exc


# ---------------------------------------------------------------------------
# Streaming TTS via ElevenLabs WebSocket API
# ---------------------------------------------------------------------------

ELEVENLABS_STREAMING_TTS_MODEL = "eleven_flash_v2_5"
ELEVENLABS_STREAMING_TTS_OUTPUT_FORMAT = "pcm_24000"

_MARKDOWN_FENCE_RE = re.compile(r"```(?:[\w+-]+)?\s*([\s\S]*?)```")
_MARKDOWN_IMAGE_RE = re.compile(r"!\[([^\]]*)\]\([^)]+\)")
_MARKDOWN_LINK_RE = re.compile(r"\[([^\]]+)\]\([^)]+\)")
_MARKDOWN_AUTOLINK_RE = re.compile(r"<((?:https?|mailto):[^>]+)>")
_MARKDOWN_HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s+", re.MULTILINE)
_MARKDOWN_BLOCKQUOTE_RE = re.compile(r"^\s{0,3}>\s?", re.MULTILINE)
_MARKDOWN_LIST_RE = re.compile(r"^\s{0,3}(?:[-*+]\s+|\d+\.\s+)", re.MULTILINE)
_MARKDOWN_CODE_RE = re.compile(r"`([^`]+)`")
_MARKDOWN_STRIKE_RE = re.compile(r"~~(.*?)~~")
_MARKDOWN_STRONG_RE = re.compile(r"(\*\*|__)(.*?)\1")
_MARKDOWN_EMPHASIS_RE = re.compile(r"(?<!\w)(\*|_)([^*_]+?)\1(?!\w)")
_MARKDOWN_AUTOLINK_START_RE = re.compile(r"<(?:https?|mailto):", re.IGNORECASE)
_MARKDOWN_WHITESPACE_RE = re.compile(r"[ \t]+")
_MARKDOWN_BLANK_LINES_RE = re.compile(r"\n{3,}")


def strip_markdown_for_tts(text: str) -> str:
    """Reduce common Markdown formatting to cleaner spoken text."""
    if not text:
        return ""

    plain_text = text
    plain_text = _MARKDOWN_FENCE_RE.sub(
        lambda match: match.group(1).strip(), plain_text
    )
    plain_text = _MARKDOWN_IMAGE_RE.sub(
        lambda match: match.group(1).strip(), plain_text
    )
    plain_text = _MARKDOWN_LINK_RE.sub(lambda match: match.group(1).strip(), plain_text)
    plain_text = _MARKDOWN_AUTOLINK_RE.sub(
        lambda match: match.group(1).strip(), plain_text
    )
    plain_text = _MARKDOWN_HEADING_RE.sub("", plain_text)
    plain_text = _MARKDOWN_BLOCKQUOTE_RE.sub("", plain_text)
    plain_text = _MARKDOWN_LIST_RE.sub("", plain_text)
    plain_text = _MARKDOWN_CODE_RE.sub(lambda match: match.group(1).strip(), plain_text)
    plain_text = _MARKDOWN_STRIKE_RE.sub(
        lambda match: match.group(1).strip(), plain_text
    )
    plain_text = _MARKDOWN_STRONG_RE.sub(lambda match: match.group(2), plain_text)
    plain_text = _MARKDOWN_EMPHASIS_RE.sub(lambda match: match.group(2), plain_text)
    plain_text = plain_text.replace("```", "")
    plain_text = plain_text.replace("`", "")
    plain_text = plain_text.replace("![", "")
    plain_text = plain_text.replace("[", "").replace("]", "")
    plain_text = plain_text.replace("\\*", "*").replace("\\_", "_").replace("\\`", "`")
    plain_text = plain_text.replace("\\[", "[").replace("\\]", "]")
    plain_text = plain_text.replace("\\(", "(").replace("\\)", ")")
    plain_text = unescape(plain_text)
    plain_text = _MARKDOWN_WHITESPACE_RE.sub(" ", plain_text)
    plain_text = _MARKDOWN_BLANK_LINES_RE.sub("\n\n", plain_text)
    return plain_text.strip()


class StreamingMarkdownSanitizer:
    """Emit speakable snippets immediately while holding incomplete markdown.

    The sanitizer keeps only enough state to avoid streaming half-finished
    markdown constructs such as links, code spans, code fences, and autolinks.
    Plain prose is passed through as soon as it is safe to speak.
    """

    def __init__(self) -> None:
        self._pending = ""

    def add(self, text: str) -> list[str]:
        """Append streamed text and return any snippets safe for TTS."""
        if not text:
            return []
        self._pending += text
        return self._drain_ready()

    def flush(self) -> str | None:
        """Return any remaining text after best-effort markdown cleanup."""
        if not self._pending:
            return None
        chunk = strip_markdown_for_tts(self._pending)
        self._pending = ""
        return chunk or None

    def _drain_ready(self) -> list[str]:
        snippets: list[str] = []
        while self._pending:
            safe_end = self._find_safe_prefix_end(self._pending)
            if safe_end <= 0:
                break
            chunk = strip_markdown_for_tts(self._pending[:safe_end])
            self._pending = self._pending[safe_end:]
            if chunk:
                snippets.append(chunk)
        return snippets

    @classmethod
    def _find_safe_prefix_end(cls, text: str) -> int:
        in_fence = False
        fence_start: int | None = None
        in_inline_code = False
        inline_code_start: int | None = None
        link_starts: list[int] = []
        pending_link_start: int | None = None
        in_link_destination = False
        link_destination_start: int | None = None
        link_destination_depth = 0
        in_autolink = False
        autolink_start: int | None = None

        i = 0
        while i < len(text):
            if in_fence:
                if text.startswith("```", i):
                    in_fence = False
                    fence_start = None
                    i += 3
                else:
                    i += 1
                continue

            if in_inline_code:
                if text[i] == "`":
                    in_inline_code = False
                    inline_code_start = None
                i += 1
                continue

            if in_link_destination:
                if text[i] == "(":
                    link_destination_depth += 1
                elif text[i] == ")":
                    link_destination_depth -= 1
                    if link_destination_depth == 0:
                        in_link_destination = False
                        link_destination_start = None
                i += 1
                continue

            if in_autolink:
                if text[i] == ">":
                    in_autolink = False
                    autolink_start = None
                i += 1
                continue

            if pending_link_start is not None:
                if text[i].isspace():
                    pending_link_start = None
                elif text[i] == "(":
                    in_link_destination = True
                    link_destination_start = pending_link_start
                    link_destination_depth = 1
                    pending_link_start = None
                    i += 1
                    continue
                else:
                    pending_link_start = None
                    continue

            if text.startswith("```", i):
                in_fence = True
                fence_start = i
                i += 3
                continue

            if text[i] == "`":
                in_inline_code = True
                inline_code_start = i
                i += 1
                continue

            if text[i] == "!" and i + 1 < len(text) and text[i + 1] == "[":
                link_starts.append(i)
                i += 2
                continue

            if text[i] == "[":
                link_starts.append(i)
                i += 1
                continue

            if text[i] == "]" and link_starts:
                pending_link_start = link_starts.pop()
                i += 1
                continue

            if _MARKDOWN_AUTOLINK_START_RE.match(text, i):
                in_autolink = True
                autolink_start = i
                i += 1
                continue

            i += 1

        unresolved_starts = link_starts
        if pending_link_start is not None:
            unresolved_starts.append(pending_link_start)
        if fence_start is not None:
            unresolved_starts.append(fence_start)
        if inline_code_start is not None:
            unresolved_starts.append(inline_code_start)
        if link_destination_start is not None:
            unresolved_starts.append(link_destination_start)
        if autolink_start is not None:
            unresolved_starts.append(autolink_start)

        return min(unresolved_starts) if unresolved_starts else len(text)


class ElevenLabsStreamingTTS:
    """WebSocket client for ElevenLabs streaming-input text-to-speech.

    Uses the ``/v1/text-to-speech/{voice_id}/stream-input`` WebSocket
    endpoint which accepts text chunks in real time and returns base64-
    encoded audio chunks.
    """

    def __init__(
        self,
        api_key: str,
        voice_id: str,
        *,
        model_id: str = ELEVENLABS_STREAMING_TTS_MODEL,
        output_format: str = ELEVENLABS_STREAMING_TTS_OUTPUT_FORMAT,
    ) -> None:
        self._api_key = api_key
        self._voice_id = voice_id
        self._model_id = model_id
        self._output_format = output_format
        self._session: aiohttp.ClientSession | None = None
        self._ws: aiohttp.ClientWebSocketResponse | None = None

    async def connect(self) -> None:
        """Open a WebSocket connection and send the initialization frame."""
        encoded_voice_id = quote(self._voice_id, safe="")
        query = urlencode(
            {
                "model_id": self._model_id,
                "output_format": self._output_format,
            }
        )
        url = (
            f"wss://api.elevenlabs.io/v1/text-to-speech/"
            f"{encoded_voice_id}/stream-input?{query}"
        )
        self._session = aiohttp.ClientSession(headers={"xi-api-key": self._api_key})
        try:
            self._ws = await self._session.ws_connect(
                url, timeout=ELEVENLABS_STREAMING_TTS_CONNECT_TIMEOUT
            )
            # Send initializeConnection message.
            await self._ws.send_json(
                {
                    "text": " ",
                    "voice_settings": {
                        "stability": 0.5,
                        "similarity_boost": 0.8,
                    },
                }
            )
        except Exception:
            await self.cleanup()
            raise

    async def send_text(self, text: str, *, flush: bool = False) -> None:
        """Send a text chunk to be synthesized.

        *text* should ideally end with a space for optimal latency.
        When *flush* is ``True``, ElevenLabs will immediately synthesize
        any buffered text rather than waiting for more input.
        """
        if not self._ws:
            raise RuntimeError("Not connected – call connect() first")
        msg: dict[str, Any] = {"text": text}
        if flush:
            msg["flush"] = True
        await self._ws.send_json(msg)

    async def close_input(self) -> None:
        """Signal end of text input (EOS)."""
        if not self._ws:
            return
        await self._ws.send_json({"text": ""})

    async def receive_audio(self) -> AsyncGenerator[str, None]:
        """Yield base64-encoded audio strings until ``isFinal`` is received."""
        if not self._ws:
            raise RuntimeError("Not connected – call connect() first")
        async for msg in self._ws:
            if msg.type == aiohttp.WSMsgType.TEXT:
                data = orjson.loads(msg.data)
                if data.get("isFinal"):
                    return
                audio = data.get("audio")
                if audio:
                    yield audio
            elif msg.type in (
                aiohttp.WSMsgType.ERROR,
                aiohttp.WSMsgType.CLOSED,
                aiohttp.WSMsgType.CLOSING,
            ):
                return

    async def cleanup(self) -> None:
        """Close the WebSocket and the underlying HTTP session."""
        if self._ws and not self._ws.closed:
            await self._ws.close()
        self._ws = None
        if self._session and not self._session.closed:
            await self._session.close()
        self._session = None
