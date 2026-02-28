import json
from collections.abc import Sequence
from urllib.parse import urlsplit

INVALID_PLATFORM_URL_ALLOWLIST_DETAIL = (
    "LTI platform URL allowlist contains invalid entries"
)
MISSING_PLATFORM_URL_ALLOWLIST_DETAIL = (
    "LTI platform URL allowlist is not configured. "
    "Set lti.platform_url_allowlist in config.toml."
)


class MissingLTIPlatformUrlAllowlistError(ValueError):
    pass


class InvalidLTIPlatformUrlAllowlistError(ValueError):
    pass


def normalize_lti_platform_url_allowlist(allowlist: Sequence[object]) -> list[str]:
    normalized: list[str] = []
    for entry in allowlist:
        if not isinstance(entry, str):
            raise InvalidLTIPlatformUrlAllowlistError(
                INVALID_PLATFORM_URL_ALLOWLIST_DETAIL
            )
        value = entry.strip().lower()
        if not value:
            raise InvalidLTIPlatformUrlAllowlistError(
                INVALID_PLATFORM_URL_ALLOWLIST_DETAIL
            )
        if value.startswith("*."):
            raise InvalidLTIPlatformUrlAllowlistError(
                INVALID_PLATFORM_URL_ALLOWLIST_DETAIL
            )
        if "://" in value:
            parsed = urlsplit(value)
            if parsed.scheme not in {"http", "https"} or not parsed.hostname:
                raise InvalidLTIPlatformUrlAllowlistError(
                    INVALID_PLATFORM_URL_ALLOWLIST_DETAIL
                )
            value = parsed.hostname
        elif "/" in value or ":" in value:
            raise InvalidLTIPlatformUrlAllowlistError(
                INVALID_PLATFORM_URL_ALLOWLIST_DETAIL
            )
        normalized.append(value)
    return normalized


def get_lti_platform_url_allowlist_from_settings(lti_settings: object) -> list[str]:
    allowlist = (
        getattr(lti_settings, "platform_url_allowlist", None) if lti_settings else None
    )
    if not isinstance(allowlist, list) or not allowlist:
        raise MissingLTIPlatformUrlAllowlistError(MISSING_PLATFORM_URL_ALLOWLIST_DETAIL)
    return normalize_lti_platform_url_allowlist(allowlist)


def try_parse_json_object(raw_value: object) -> dict[str, object] | None:
    if not isinstance(raw_value, str) or not raw_value:
        return None
    try:
        parsed = json.loads(raw_value)
    except json.JSONDecodeError:
        return None
    if not isinstance(parsed, dict):
        return None
    if any(not isinstance(key, str) for key in parsed):
        return None
    return parsed


def extract_lti_url_hostname(url: object) -> str | None:
    if not isinstance(url, str) or not url:
        return None
    normalized_url = url.replace("\\", "/")
    parsed = urlsplit(normalized_url)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.netloc
        or not parsed.hostname
    ):
        return None
    return parsed.hostname.lower()


def is_lti_host_allowlisted(host: str, allowlist: Sequence[str]) -> bool:
    host_lower = host.lower()
    for allowed in allowlist:
        if host_lower == allowed:
            return True
    return False
