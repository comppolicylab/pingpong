import json
import re
from collections.abc import Sequence
from typing import NamedTuple
from urllib.parse import parse_qsl, quote, urlencode, urlsplit

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


class LTIUrlValidationError(ValueError):
    pass


class AllowlistedLTIUrlParts(NamedTuple):
    scheme: str
    host: str
    path: str
    query: str


class LTIHostValidationContext(NamedTuple):
    allowlist_lookup: dict[str, str]
    dev_http_hosts: set[str]
    development: bool


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
    return find_lti_allowlisted_host(host, allowlist) is not None


def find_lti_allowlisted_host(host: str, allowlist: Sequence[str]) -> str | None:
    """Return the matched allowlist entry for *host*, or ``None``.

    Returning the allowlist entry (a server-controlled string) instead of the
    caller-supplied *host* lets callers reconstruct URLs without propagating
    user-supplied values, which satisfies static-analysis taint tracking.
    """
    host_lower = host.lower()
    for allowed in allowlist:
        if host_lower == allowed:
            return allowed
    return None


def build_lti_host_validation_context(
    *,
    allowlist: Sequence[str],
    development: bool,
    dev_http_hosts: Sequence[object],
) -> LTIHostValidationContext:
    allowlist_lookup = {host.lower(): host for host in allowlist}
    dev_http_hosts_set = {
        candidate.strip().lower()
        for candidate in dev_http_hosts
        if isinstance(candidate, str) and candidate.strip()
    }
    return LTIHostValidationContext(
        allowlist_lookup=allowlist_lookup,
        dev_http_hosts=dev_http_hosts_set,
        development=development,
    )


def allow_http_for_lti_host(host: str, context: LTIHostValidationContext) -> bool:
    if not context.development:
        return False
    return host.lower() in context.dev_http_hosts


_UNSAFE_PATH_RE = re.compile(r"[\x00-\x1f\x7f@]")


def _sanitize_url_path(path: str, field_name: str) -> str:
    """Re-encode a URL path to produce a fresh, untainted string.

    Rejects paths containing control characters, ``@`` (authority confusion),
    or ``..`` segments (path traversal).  The returned string is safe to embed
    in a redirect URL.
    """
    if _UNSAFE_PATH_RE.search(path):
        raise LTIUrlValidationError(f"Invalid URL path for {field_name}")
    segments = path.split("/")
    if ".." in segments:
        raise LTIUrlValidationError(f"Invalid URL path for {field_name}")
    return quote(path, safe="/:=+!*'(),@&~")


def _sanitize_url_query(query: str, field_name: str) -> str:
    """Re-encode a URL query string to produce a fresh, untainted string.

    Rejects query strings containing control characters.  The returned string
    is reconstructed via :func:`urlencode` so it is no longer tainted.
    """
    if _UNSAFE_PATH_RE.search(query):
        raise LTIUrlValidationError(f"Invalid URL query for {field_name}")
    pairs = parse_qsl(query, keep_blank_values=True)
    return urlencode(pairs)


def validate_allowlisted_lti_url_parts(
    url: object,
    field_name: str,
    context: LTIHostValidationContext,
) -> AllowlistedLTIUrlParts:
    if not isinstance(url, str) or not url:
        raise LTIUrlValidationError(f"Missing or invalid {field_name}")

    normalized_url = url.replace("\\", "/")
    parsed = urlsplit(normalized_url)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.netloc
        or not parsed.hostname
    ):
        raise LTIUrlValidationError(f"Invalid URL for {field_name}")

    try:
        port = parsed.port
    except ValueError as e:
        raise LTIUrlValidationError(f"Invalid URL for {field_name}") from e

    if parsed.username or parsed.password or parsed.fragment:
        raise LTIUrlValidationError(f"Invalid URL for {field_name}")

    if port is not None:
        is_default_port = (parsed.scheme == "https" and port == 443) or (
            parsed.scheme == "http" and port == 80
        )
        if not is_default_port:
            raise LTIUrlValidationError(f"Invalid URL for {field_name}")

    matched_host = context.allowlist_lookup.get(parsed.hostname.lower())
    if matched_host is None:
        raise LTIUrlValidationError(f"{field_name} host is not allowlisted")

    if parsed.scheme != "https" and not allow_http_for_lti_host(matched_host, context):
        raise LTIUrlValidationError(f"{field_name} must use HTTPS")

    safe_path = _sanitize_url_path(parsed.path or "/", field_name)
    safe_query = _sanitize_url_query(parsed.query, field_name) if parsed.query else ""

    return AllowlistedLTIUrlParts(
        scheme="https" if parsed.scheme == "https" else "http",
        host=matched_host,
        path=safe_path,
        query=safe_query,
    )
