from typing import Any

from openai import APIError
from websockets.exceptions import ConnectionClosed


MODEL_NOT_AVAILABLE_MESSAGE = (
    "The selected model is not available. Edit your assistant to select a different "
    "model, or contact a group moderator."
)


def is_model_unavailable_error(error: Any) -> bool:
    # A rejected model can arrive as a provider event or a WebSocket close reason.
    # Match known codes without exposing the provider's raw error text.
    if isinstance(error, ConnectionClosed):
        close = error.rcvd or error.sent
        code = close.reason if close is not None else None
    else:
        code = getattr(error, "code", None)
    return code in (
        "model_not_found",
        "model_unavailable",
        "invalid_request_error.model_not_found",
        "invalid_request_error.model_unavailable",
        "DeploymentNotFound",
    )


def get_ai_error_message(error: Any, default: str) -> str:
    return MODEL_NOT_AVAILABLE_MESSAGE if is_model_unavailable_error(error) else default


def get_details_from_api_error(e: APIError, custom_fallback: str | None = None) -> str:
    fallback = custom_fallback or "OpenAI was unable to process your request."
    if hasattr(e, "body") and isinstance(e.body, dict):
        message = e.body.get("message")
        if message:
            return message
    if hasattr(e, "message") and e.message:
        return e.message
    return fallback
