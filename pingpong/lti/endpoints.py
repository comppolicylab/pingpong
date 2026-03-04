from pingpong.config import LTIUrlSecuritySettings
from pingpong.lti.allowlist import (
    generate_safe_lti_url,
)


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
        else config.lti.security.allow_http_in_development
    )


def generate_openid_configuration_url(openid_configuration_url: str) -> str:
    # Lazy import avoids config import cycles.
    from pingpong.config import config

    if not config.lti:
        raise ValueError(
            "LTI configuration is required to validate the OpenID configuration URL"
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


def allow_redirects(security_config: LTIUrlSecuritySettings) -> bool:
    # Lazy import avoids config import cycles.
    from pingpong.config import config

    if config.lti is None:
        raise ValueError(
            "LTI configuration is required to determine if redirects are allowed"
        )

    return (
        security_config.allow_redirects
        if security_config.allow_redirects is not None
        else config.lti.security.allow_redirects
    )


def generate_names_and_role_api_url(names_and_role_api_url: str) -> str:
    # Lazy import avoids config import cycles.
    from pingpong.config import config

    if not config.lti:
        raise ValueError(
            "LTI configuration is required to validate the Names and Role API URL"
        )

    host_allow, host_deny, path_allow, path_deny = _get_openid_configuration_patterns(
        config.lti.security.names_and_role_endpoint
    )

    return generate_safe_lti_url(
        unverified_url=names_and_role_api_url,
        url_type="Names and Role API",
        host_allow=host_allow,
        host_deny=host_deny,
        path_allow=path_allow,
        path_deny=path_deny,
        allow_http_in_development=_allow_http_in_development(
            config.lti.security.names_and_role_endpoint
        ),
    )


def generate_authorization_endpoint_url(auth_token_url: str) -> str:
    # Lazy import avoids config import cycles.
    from pingpong.config import config

    if not config.lti:
        raise ValueError(
            "LTI configuration is required to validate the authorization endpoint URL"
        )

    host_allow, host_deny, path_allow, path_deny = _get_openid_configuration_patterns(
        config.lti.security.authorization_endpoint
    )

    return generate_safe_lti_url(
        unverified_url=auth_token_url,
        url_type="authorization endpoint",
        host_allow=host_allow,
        host_deny=host_deny,
        path_allow=path_allow,
        path_deny=path_deny,
        allow_http_in_development=_allow_http_in_development(
            config.lti.security.authorization_endpoint
        ),
    )


def generate_registration_endpoint_url(registration_endpoint_url: str) -> str:
    # Lazy import avoids config import cycles.
    from pingpong.config import config

    if not config.lti:
        raise ValueError(
            "LTI configuration is required to validate the registration endpoint URL"
        )

    host_allow, host_deny, path_allow, path_deny = _get_openid_configuration_patterns(
        config.lti.security.registration_endpoint
    )

    return generate_safe_lti_url(
        unverified_url=registration_endpoint_url,
        url_type="registration endpoint",
        host_allow=host_allow,
        host_deny=host_deny,
        path_allow=path_allow,
        path_deny=path_deny,
        allow_http_in_development=_allow_http_in_development(
            config.lti.security.registration_endpoint
        ),
    )


def generate_jwks_uri_url(jwks_uri_url: str) -> str:
    # Lazy import avoids config import cycles.
    from pingpong.config import config

    if not config.lti:
        raise ValueError("LTI configuration is required to validate the JWKS URI URL")

    host_allow, host_deny, path_allow, path_deny = _get_openid_configuration_patterns(
        config.lti.security.jwks_uri
    )

    return generate_safe_lti_url(
        unverified_url=jwks_uri_url,
        url_type="JWKS URI",
        host_allow=host_allow,
        host_deny=host_deny,
        path_allow=path_allow,
        path_deny=path_deny,
        allow_http_in_development=_allow_http_in_development(
            config.lti.security.jwks_uri
        ),
    )


def generate_token_endpoint_url(token_endpoint_url: str) -> str:
    # Lazy import avoids config import cycles.
    from pingpong.config import config

    if not config.lti:
        raise ValueError(
            "LTI configuration is required to validate the token endpoint URL"
        )

    host_allow, host_deny, path_allow, path_deny = _get_openid_configuration_patterns(
        config.lti.security.token_endpoint
    )

    return generate_safe_lti_url(
        unverified_url=token_endpoint_url,
        url_type="token endpoint",
        host_allow=host_allow,
        host_deny=host_deny,
        path_allow=path_allow,
        path_deny=path_deny,
        allow_http_in_development=_allow_http_in_development(
            config.lti.security.token_endpoint
        ),
    )
