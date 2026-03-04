from fnmatch import fnmatch
import re
from urllib.parse import urlsplit

from pingpong.config import LTIUrlSecuritySettings


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


def _get_openid_configuration_patterns(
    security_config: LTIUrlSecuritySettings,
) -> tuple[list[str], list[str], list[str], list[str]]:
    # Lazy import avoids config import cycles.
    from pingpong.config import config

    if config.lti is None:
        raise ValueError(
            "LTI configuration is required to determine OpenID configuration allow/deny patterns"
        )

    return (
        security_config.hosts.allow
        if security_config.hosts is not None
        else config.lti.security.hosts.allow,
        security_config.hosts.deny
        if security_config.hosts is not None
        else config.lti.security.hosts.deny,
        security_config.paths.allow
        if security_config.paths is not None
        else config.lti.security.paths.allow,
        security_config.paths.deny
        if security_config.paths is not None
        else config.lti.security.paths.deny,
    )


def _allow_http_in_development(
    security_config: LTIUrlSecuritySettings,
) -> bool:
    # Lazy import avoids config import cycles.
    from pingpong.config import config

    if config.lti is None:
        raise ValueError(
            "LTI configuration is required to determine if HTTP is allowed in development"
        )

    return (
        security_config.allow_http_in_development
        if security_config.allow_http_in_development is not None
        else config.lti.allow_http_in_development
    )


def _allow_redirects(security_config: LTIUrlSecuritySettings) -> bool:
    # Lazy import avoids config import cycles.
    from pingpong.config import config

    if config.lti is None:
        raise ValueError(
            "LTI configuration is required to determine if redirects are allowed"
        )

    return (
        security_config.allow_redirects
        if security_config.allow_redirects is not None
        else config.lti.allow_redirects
    )


def generate_safe_lti_url(
    unverified_url: str,
    url_type: str,
    host_allow: list[str],
    host_deny: list[str],
    path_allow: list[str],
    path_deny: list[str],
    allow_http_in_development: bool,
) -> str:
    # Lazy import avoids config import cycles.
    from pingpong.config import config

    _url = urlsplit(unverified_url)
    hostname = (_url.hostname or "").lower().rstrip(".")

    if not _HOST_RE.fullmatch(hostname):
        raise ValueError(f"Invalid {url_type} URL hostname")

    if not _hostname_allowed(hostname, host_allow, host_deny):
        raise ValueError(f"Invalid {url_type} URL hostname")

    path = _url.path or "/"
    if not _PATH_RE.fullmatch(path):
        raise ValueError(f"Invalid {url_type} URL path")
    if not _path_allowed(path, path_allow, path_deny):
        raise ValueError(f"Invalid {url_type} URL path")

    is_development = config.development
    input_scheme = _url.scheme
    scheme = (
        "http"
        if (is_development and allow_http_in_development and input_scheme == "http")
        else "https"
    )

    # Reconstruct URL entirely from validated allowlist values
    if _url.query:
        path += "?" + _url.query
    return scheme + "://" + hostname + path


def generate_openid_configuration_url(openid_configuration_url: str) -> str:
    # Lazy import avoids config import cycles.
    from pingpong.config import config

    if not config.lti:
        raise ValueError(
            "LTI configuration is required to validate context memberships URL"
        )

    host_allow, host_deny, path_allow, path_deny = _get_openid_configuration_patterns(
        config.lti.security.openid_configuration
    )

    return generate_safe_lti_url(
        unverified_url=openid_configuration_url,
        url_type="OpenID configuration",
        host_allow=host_allow,
        host_deny=host_deny,
        path_allow=path_allow,
        path_deny=path_deny,
        allow_http_in_development=_allow_http_in_development(
            config.lti.security.openid_configuration
        ),
    )


def generate_context_memberships_url(context_memberships_url: str) -> str:
    # Lazy import avoids config import cycles.
    from pingpong.config import config

    if not config.lti:
        raise ValueError(
            "LTI configuration is required to validate context memberships URL"
        )

    host_allow, host_deny, path_allow, path_deny = _get_openid_configuration_patterns(
        config.lti.security.context_memberships_url
    )

    return generate_safe_lti_url(
        unverified_url=context_memberships_url,
        url_type="context memberships",
        host_allow=host_allow,
        host_deny=host_deny,
        path_allow=path_allow,
        path_deny=path_deny,
        allow_http_in_development=_allow_http_in_development(
            config.lti.security.context_memberships_url
        ),
    )


def generate_auth_token_url(auth_token_url: str) -> str:
    # Lazy import avoids config import cycles.
    from pingpong.config import config

    if not config.lti:
        raise ValueError("LTI configuration is required to validate auth token URL")

    host_allow, host_deny, path_allow, path_deny = _get_openid_configuration_patterns(
        config.lti.security.auth_login_url
    )

    return generate_safe_lti_url(
        unverified_url=auth_token_url,
        url_type="auth token",
        host_allow=host_allow,
        host_deny=host_deny,
        path_allow=path_allow,
        path_deny=path_deny,
        allow_http_in_development=_allow_http_in_development(
            config.lti.security.auth_login_url
        ),
    )
