from collections.abc import Sequence
from urllib.parse import urlsplit

INVALID_PLATFORM_URL_ALLOWLIST_DETAIL = (
    "LTI platform URL allowlist contains invalid entries"
)


def normalize_lti_platform_url_allowlist(allowlist: Sequence[object]) -> list[str]:
    normalized: list[str] = []
    for entry in allowlist:
        if not isinstance(entry, str):
            raise ValueError(INVALID_PLATFORM_URL_ALLOWLIST_DETAIL)
        value = entry.strip().lower()
        if not value:
            raise ValueError(INVALID_PLATFORM_URL_ALLOWLIST_DETAIL)
        if "://" in value:
            parsed = urlsplit(value)
            if parsed.scheme not in {"http", "https"} or not parsed.hostname:
                raise ValueError(INVALID_PLATFORM_URL_ALLOWLIST_DETAIL)
            value = parsed.hostname
        elif "/" in value or ":" in value:
            raise ValueError(INVALID_PLATFORM_URL_ALLOWLIST_DETAIL)
        normalized.append(value)
    return normalized


def is_lti_host_allowlisted(host: str, allowlist: Sequence[str]) -> bool:
    host_lower = host.lower()
    for allowed in allowlist:
        if allowed.startswith("*."):
            suffix = allowed[1:]  # ".example.com"
            if host_lower.endswith(suffix) and host_lower != allowed[2:]:
                return True
        elif host_lower == allowed:
            return True
    return False
