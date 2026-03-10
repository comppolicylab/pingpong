from fnmatch import fnmatch
import re
from typing import Literal
from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit


LTIUrlValidationMode = Literal["canonicalize", "redirect"]

_HOST_RE = re.compile(
    r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)*"
)
_PATH_SEGMENT_RE = r"(?:[A-Za-z0-9._~!$&'()*+,;=:@-]|%[0-9A-Fa-f]{2})+"
_PATH_RE = re.compile(rf"\A/(?:{_PATH_SEGMENT_RE}(?:/{_PATH_SEGMENT_RE})*)?/?\Z")
_ENCODED_PATH_SEPARATOR_RE = re.compile(r"%2f|%5c", re.IGNORECASE)
_UNSAFE_PATH_RE = re.compile(r"[\x00-\x1f\x7f@]")
_UNSAFE_QUERY_RE = re.compile(r"[\x00-\x1f\x7f]")


def _sanitize_url_path(path: str, field_name: str) -> str:
    """Re-encode a URL path to produce a fresh, untainted string.

    Rejects paths containing control characters, ``@`` (authority confusion),
    or ``..`` segments (path traversal).  The returned string is safe to embed
    in a redirect URL.
    """
    if _UNSAFE_PATH_RE.search(path):
        raise ValueError(f"Invalid URL path for {field_name}")
    segments = path.split("/")
    if ".." in segments:
        raise ValueError(f"Invalid URL path for {field_name}")
    return quote(path, safe="/%:=+!*'(),@&~")


def _sanitize_url_query(query: str, field_name: str) -> str:
    """Re-encode a URL query string to produce a fresh, untainted string.

    Rejects query strings containing control characters.  The returned string
    is reconstructed via :func:`urlencode` so it is no longer tainted.
    """
    if _UNSAFE_QUERY_RE.search(query):
        raise ValueError(f"Invalid URL query for {field_name}")
    pairs = parse_qsl(query, keep_blank_values=True)
    return urlencode(pairs)


def _hostname_matches(hostname: str, pattern: str) -> bool:
    normalized_hostname = hostname.lower().rstrip(".")
    normalized_pattern = pattern.lower().strip()
    if not normalized_pattern:
        return False
    if normalized_pattern == "*":
        return True
    if normalized_pattern.startswith("*."):
        suffix = normalized_pattern[2:]
        return normalized_hostname.endswith("." + suffix)
    return normalized_hostname == normalized_pattern


def _hostname_allowed(
    hostname: str, allow_patterns: list[str], deny_patterns: list[str]
) -> bool:
    for pattern in deny_patterns:
        if _hostname_matches(hostname, pattern):
            return False

    for pattern in allow_patterns:
        if _hostname_matches(hostname, pattern):
            return True

    return False


def _path_matches(path: str, pattern: str) -> bool:
    normalized_pattern = pattern.strip()
    if not normalized_pattern:
        return False
    return normalized_pattern == "*" or fnmatch(path, normalized_pattern)


def _path_allowed(
    path: str, allow_patterns: list[str], deny_patterns: list[str]
) -> bool:
    for pattern in deny_patterns:
        if _path_matches(path, pattern):
            return False

    for pattern in allow_patterns:
        if _path_matches(path, pattern):
            return True

    return False


def generate_safe_lti_url(
    unverified_url: str,
    url_type: str,
    host_allow: list[str],
    host_deny: list[str],
    path_allow: list[str],
    path_deny: list[str],
    allow_http_in_development: bool,
    validation_mode: LTIUrlValidationMode = "canonicalize",
) -> str:
    # Lazy import avoids config import cycles.
    from pingpong.config import config

    normalized_url = unverified_url.replace("\\", "/")
    _url = urlsplit(normalized_url)

    if _url.scheme not in {"http", "https"} or not _url.netloc or not _url.hostname:
        raise ValueError(f"Invalid URL for {url_type}")

    raw_hostname = (_url.hostname or "").lower()
    if validation_mode == "redirect" and raw_hostname.endswith("."):
        raise ValueError(f"Invalid {url_type} URL hostname")

    hostname = raw_hostname.rstrip(".")
    if not _HOST_RE.fullmatch(hostname):
        raise ValueError(f"Invalid {url_type} URL hostname")

    if not _hostname_allowed(hostname, host_allow, host_deny):
        raise ValueError(f"Invalid {url_type} URL hostname")

    raw_path = _url.path or "/"
    if validation_mode == "redirect" and _ENCODED_PATH_SEPARATOR_RE.search(raw_path):
        raise ValueError(f"Invalid {url_type} URL path")

    path = _sanitize_url_path(raw_path, url_type)
    if not _PATH_RE.fullmatch(path):
        raise ValueError(f"Invalid {url_type} URL path")
    if not _path_allowed(path, path_allow, path_deny):
        raise ValueError(f"Invalid {url_type} URL path")

    try:
        port = _url.port
    except ValueError as e:
        raise ValueError(f"Invalid URL for {url_type}") from e

    is_development = config.development
    input_scheme = _url.scheme
    if input_scheme == "http":
        if not (is_development and allow_http_in_development):
            raise ValueError(f"Invalid URL for {url_type}: HTTP is not allowed")
        scheme = "http"
    else:
        scheme = "https"

    if _url.username or _url.password or _url.fragment:
        raise ValueError(f"Invalid URL for {url_type}")

    if port is not None:
        is_default_port = (scheme == "https" and port == 443) or (
            scheme == "http" and port == 80
        )
        if not is_default_port:
            raise ValueError(
                f"Invalid URL for {url_type}: non-default port is not allowed"
            )
        # Fix CodeQL warning about using _url.port
        # after validating it is a default port
        port = 443 if scheme == "https" else 80

    # Reconstruct URL entirely from validated allowlist values
    netloc = hostname if port is None else f"{hostname}:{port}"
    query = _sanitize_url_query(_url.query, url_type) if _url.query else ""
    return urlunsplit((scheme, netloc, path, query, ""))
