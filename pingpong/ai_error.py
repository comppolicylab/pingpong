from openai import APIError


def get_details_from_api_error(e: APIError, custom_fallback: str | None = None) -> str:
    fallback = custom_fallback or "OpenAI was unable to process your request."
    if hasattr(e, "body") and isinstance(e.body, dict):
        message = e.body.get("message")
        if message:
            return message
    if hasattr(e, "message") and e.message:
        return e.message
    return fallback
