import re

LOG_SAFE_CHARS = re.compile(r"[^A-Za-z0-9_.:@/+\-]")
ASCII_CONTROL_CHARS = re.compile(r"[\x00-\x1F\x7F]")


def sanitize_for_log(value: object | None, max_len: int = 128) -> str:
    """
    Sanitize a value for safe inclusion in log messages.

    - Restricts characters to a conservative whitelist.
    - Removes control characters (including newlines and carriage returns).
    - Truncates overly long values.
    """
    if value is None:
        return ""
    if not isinstance(value, str):
        value = str(value)

    cleaned = LOG_SAFE_CHARS.sub("_", value)
    cleaned = cleaned.replace("\r", "").replace("\n", "")
    cleaned = ASCII_CONTROL_CHARS.sub("", cleaned)

    if len(cleaned) > max_len:
        return cleaned[:max_len] + "..."
    return cleaned
