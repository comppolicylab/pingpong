import logging
from copy import deepcopy
from typing import Any

from pingpong.schemas import RunStatus


logger = logging.getLogger(__name__)


def _provider_json(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    try:
        if hasattr(value, "model_dump"):
            return value.model_dump(mode="json", exclude_unset=True)
        return dict(value)
    except (TypeError, ValueError):
        # Accounting metadata must not interrupt transcript/audio processing.
        logger.exception("Failed to serialize realtime usage metadata.")
        return None


class RealtimeUsage:
    """Provider work is retained independently of transcript/playback retention."""

    def __init__(self) -> None:
        self.session_id: str | None = None
        self.responses: dict[str, dict[str, Any]] = {}
        self.transcriptions: dict[str, dict[str, dict[str, Any]]] = {}
        self.errors: list[dict[str, Any]] = []
        self.error_code: str | None = None
        self.error_message: str | None = None
        self.incomplete_reason: str | None = None
        self.pending_response_ids: set[str] = set()
        self._finished_response_ids: set[str] = set()
        self._transcription_model: str | None = None

    def observe(self, event) -> None:
        if event.type in {"session.created", "session.updated"}:
            session_id = getattr(event.session, "id", None)
            if isinstance(session_id, str) and session_id:
                self.session_id = session_id
        if event.type == "session.updated":
            audio = getattr(event.session, "audio", None)
            transcription = getattr(
                getattr(audio, "input", None), "transcription", None
            )
            model = getattr(transcription, "model", None)
            if model:
                self._transcription_model = model
        elif event.type in {
            "response.created",
            "response.done",
            "response.output_item.added",
            "response.output_item.done",
        }:
            response = getattr(event, "response", None)
            response_id = getattr(response, "id", None) or getattr(
                event, "response_id", None
            )
            if not response_id:
                return
            record = self.responses.setdefault(
                response_id,
                {"item_ids": [], "status": None, "status_details": None, "usage": None},
            )
            items = (
                getattr(response, "output", None) or []
                if response is not None
                else [getattr(event, "item", None)]
            )
            for item in items:
                item_id = getattr(item, "id", None)
                if item_id and item_id not in record["item_ids"]:
                    record["item_ids"].append(item_id)
            if event.type == "response.done":
                self._finished_response_ids.add(response_id)
                self.pending_response_ids.discard(response_id)
                status = getattr(response, "status", None)
                if status is not None:
                    record["status"] = status
                details = _provider_json(getattr(response, "status_details", None))
                if details is not None:
                    record["status_details"] = details
                usage = _provider_json(getattr(response, "usage", None))
                if usage is not None:
                    record["usage"] = usage
            elif response_id not in self._finished_response_ids:
                self.pending_response_ids.add(response_id)
        elif event.type in {
            "input_audio_buffer.committed",
            "conversation.item.input_audio_transcription.delta",
            "conversation.item.input_audio_transcription.completed",
            "conversation.item.input_audio_transcription.failed",
        }:
            item_id = getattr(event, "item_id", None)
            if not item_id:
                return
            # Microphone-buffer commits contain one input-audio part at index 0.
            content_index = str(getattr(event, "content_index", None) or 0)
            record = self.transcriptions.setdefault(item_id, {}).setdefault(
                content_index, {"model": self._transcription_model, "usage": None}
            )
            usage = _provider_json(getattr(event, "usage", None))
            if usage is not None:
                record["usage"] = usage
            if (
                event.type == "conversation.item.input_audio_transcription.failed"
                and getattr(event, "error", None) is not None
            ):
                self.record_error(event)

    def record_error(self, event) -> None:
        record = {
            "event_id": getattr(event, "event_id", None),
            "error": {
                field: getattr(event.error, field, None)
                for field in ("type", "code", "message", "param", "event_id")
            },
        }
        if event.type == "conversation.item.input_audio_transcription.failed":
            record.update(
                item_id=event.item_id,
                content_index=getattr(event, "content_index", None) or 0,
            )
        if record not in self.errors:
            self.errors.append(record)

    def record_exception(self, error: Exception, *, code: str) -> None:
        record = {
            "event_id": None,
            "error": {
                "type": type(error).__name__,
                "code": code,
                "message": str(error),
                "param": None,
                "event_id": None,
            },
        }
        if record not in self.errors:
            self.errors.append(record)

    def fail(self, code: str, message: str) -> None:
        # Preserve the first terminal cause, including across later disconnects.
        if self.error_code is None:
            self.error_code = code
            self.error_message = message

    def mark_incomplete(self, reason: str) -> None:
        if self.incomplete_reason is None:
            self.incomplete_reason = reason

    @property
    def final_status(self) -> RunStatus:
        if self.error_code is not None:
            return RunStatus.FAILED
        if self.incomplete_reason is not None:
            return RunStatus.INCOMPLETE
        return RunStatus.COMPLETED

    @property
    def has_records(self) -> bool:
        # Failed or unfinished provider work is retained even without usage.
        return bool(
            self.responses
            or self.transcriptions
            or self.errors
            or self.error_code is not None
            or self.incomplete_reason is not None
        )

    def to_json(self) -> dict[str, Any] | None:
        if not self.responses and not self.transcriptions:
            return None
        return {
            "schema_version": 1,
            "provider": "openai",
            "api": "realtime",
            "responses": {
                response_id: {"usage": deepcopy(record["usage"])}
                for response_id, record in self.responses.items()
            },
            "transcriptions": deepcopy(self.transcriptions),
        }

    def provider_metadata_to_json(self) -> dict[str, Any] | None:
        if not self.responses and not self.errors:
            return None
        result = {
            "schema_version": 1,
            "provider": "openai",
            "api": "realtime",
            "responses": {
                response_id: {
                    field: deepcopy(record[field])
                    for field in ("item_ids", "status", "status_details")
                }
                for response_id, record in self.responses.items()
            },
        }
        if self.errors:
            result["errors"] = deepcopy(self.errors)
        return result
