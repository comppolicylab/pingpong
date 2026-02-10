import re

LOG_SAFE_CHARS = re.compile(r"[^A-Za-z0-9_.:@/+\-]")


def sanitize_for_log(value: str, max_len: int = 128) -> str:
    cleaned = LOG_SAFE_CHARS.sub("_", value)
    if len(cleaned) > max_len:
        return cleaned[:max_len] + "..."
    return cleaned
