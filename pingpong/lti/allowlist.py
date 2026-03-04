from fnmatch import fnmatch
import re
from urllib.parse import urlsplit


_HOST_RE = re.compile(
    r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?(?:\.[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)*"
)
_PATH_RE = re.compile(
    r"\A/(?:[A-Za-z0-9._~!$&'()*+,;=:@-]+(?:/[A-Za-z0-9._~!$&'()*+,;=:@-]+)*)?/?\Z"
)


def _hostname_matches(hostname: str, pattern: str) -> bool:
    normalized_hostname = hostname.lower().rstrip(".")
    normalized_pattern = pattern.lower().strip()
    if not normalized_pattern:
        return False
    if normalized_pattern == "*":
        return True
    if normalized_pattern.startswith("*."):
        suffix = normalized_pattern[2:]
        return normalized_hostname == suffix or normalized_hostname.endswith(
            "." + suffix
        )
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


def _openid_configuration_patterns() -> tuple[
    list[str], list[str], list[str], list[str]
]:
    # Lazy import avoids config import cycles.
    from pingpong.config import config

    if config.lti is None:
        return ["*"], [], ["*"], []

    openid_security = config.lti.security.openid_configuration
    return (
        openid_security.hosts.allow,
        openid_security.hosts.deny,
        openid_security.paths.allow,
        openid_security.paths.deny,
    )


def _allow_http_in_development() -> bool:
    # Lazy import avoids config import cycles.
    from pingpong.config import config

    if config.lti is None:
        return True

    return config.lti.security.openid_configuration.allow_http_in_development


def generate_openid_configuration_url(openid_configuration_url: str) -> str:
    # Lazy import avoids config import cycles.
    from pingpong.config import config

    _openid_configuration_url = urlsplit(openid_configuration_url)
    host_allow, host_deny, path_allow, path_deny = _openid_configuration_patterns()

    hostname = (_openid_configuration_url.hostname or "").lower().rstrip(".")
    if not _HOST_RE.fullmatch(hostname):
        raise ValueError("Invalid openid_configuration URL hostname")

    if not _hostname_allowed(hostname, host_allow, host_deny):
        raise ValueError("Invalid openid_configuration URL hostname")

    path = _openid_configuration_url.path or "/"
    if not _PATH_RE.fullmatch(path):
        raise ValueError("Invalid openid_configuration URL path")
    if not _path_allowed(path, path_allow, path_deny):
        raise ValueError("Invalid openid_configuration URL path")

    is_development = config.development
    input_scheme = _openid_configuration_url.scheme
    allow_http_in_development = _allow_http_in_development()
    scheme = (
        "http"
        if (is_development and allow_http_in_development and input_scheme == "http")
        else "https"
    )

    # Reconstruct URL entirely from validated allowlist values
    return scheme + "://" + hostname + path
