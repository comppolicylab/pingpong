from pingpong.config import LTIAllowDenySettings, LTIUrlSecuritySettings
from pingpong.lti.allowlist import LTIUrlValidationMode, generate_safe_lti_url


def _get_patterns(
    security_config: LTIUrlSecuritySettings,
) -> tuple[list[str], list[str], list[str], list[str]]:
    # Lazy import avoids config import cycles.
    from pingpong.config import config

    if config.lti is None:
        raise ValueError(
            "LTI configuration is required to determine endpoint URL allow/deny patterns"
        )

    host_allow, host_deny = _merge_allow_deny_settings(
        config.lti.security.hosts, security_config.hosts
    )
    path_allow, path_deny = _merge_allow_deny_settings(
        config.lti.security.paths, security_config.paths
    )

    return host_allow, host_deny, path_allow, path_deny


def _merge_allow_deny_settings(
    global_settings: LTIAllowDenySettings,
    endpoint_settings: LTIAllowDenySettings | None,
) -> tuple[list[str], list[str]]:
    if endpoint_settings is None:
        return global_settings.allow, global_settings.deny

    field_names = getattr(endpoint_settings, "model_fields_set", None)
    if field_names is None:
        return endpoint_settings.allow, endpoint_settings.deny

    return (
        endpoint_settings.allow if "allow" in field_names else global_settings.allow,
        endpoint_settings.deny if "deny" in field_names else global_settings.deny,
    )


def _get_security_setting(
    security_config: LTIUrlSecuritySettings,
    *,
    field_name: str,
    default: bool,
) -> bool:
    field_names = getattr(security_config, "model_fields_set", None)
    if field_names is not None and field_name not in field_names:
        return default

    value = getattr(security_config, field_name)
    return default if value is None else value


def _allow_http_in_development(
    security_config: LTIUrlSecuritySettings,
) -> bool:
    # Lazy import avoids config import cycles.
    from pingpong.config import config

    if config.lti is None:
        raise ValueError(
            "LTI configuration is required to determine if HTTP is allowed in development"
        )

    return _get_security_setting(
        security_config,
        field_name="allow_http_in_development",
        default=config.lti.security.allow_http_in_development,
    )


def _generate_lti_url(
    *,
    unverified_url: str,
    security_config: LTIUrlSecuritySettings | None,
    url_type: str,
    validation_mode: LTIUrlValidationMode = "canonicalize",
) -> str:
    # Lazy import avoids config import cycles.
    from pingpong.config import config

    if not config.lti:
        raise ValueError(
            f"LTI configuration is required to validate the {url_type} URL"
        )

    if security_config is None:
        raise ValueError(
            f"LTI security configuration is required for the {url_type} URL"
        )

    host_allow, host_deny, path_allow, path_deny = _get_patterns(security_config)

    return generate_safe_lti_url(
        unverified_url=unverified_url,
        url_type=url_type,
        host_allow=host_allow,
        host_deny=host_deny,
        path_allow=path_allow,
        path_deny=path_deny,
        allow_http_in_development=_allow_http_in_development(security_config),
        validation_mode=validation_mode,
    )


def allow_redirects(security_config: LTIUrlSecuritySettings) -> bool:
    # Lazy import avoids config import cycles.
    from pingpong.config import config

    if config.lti is None:
        raise ValueError(
            "LTI configuration is required to determine if redirects are allowed"
        )

    return _get_security_setting(
        security_config,
        field_name="allow_redirects",
        default=config.lti.security.allow_redirects,
    )


def generate_openid_configuration_url(
    openid_configuration_url: str,
    *,
    validation_mode: LTIUrlValidationMode = "canonicalize",
) -> str:
    # Lazy import avoids config import cycles.
    from pingpong.config import config

    return _generate_lti_url(
        unverified_url=openid_configuration_url,
        security_config=(
            config.lti.security.openid_configuration if config.lti else None
        ),
        url_type="OpenID configuration",
        validation_mode=validation_mode,
    )


def generate_names_and_role_api_url(
    names_and_role_api_url: str,
    *,
    validation_mode: LTIUrlValidationMode = "canonicalize",
) -> str:
    # Lazy import avoids config import cycles.
    from pingpong.config import config

    return _generate_lti_url(
        unverified_url=names_and_role_api_url,
        security_config=(
            config.lti.security.names_and_role_endpoint if config.lti else None
        ),
        url_type="Names and Role API",
        validation_mode=validation_mode,
    )


def generate_authorization_endpoint_url(
    authorization_endpoint_url: str,
    *,
    validation_mode: LTIUrlValidationMode = "canonicalize",
) -> str:
    # Lazy import avoids config import cycles.
    from pingpong.config import config

    return _generate_lti_url(
        unverified_url=authorization_endpoint_url,
        security_config=(
            config.lti.security.authorization_endpoint if config.lti else None
        ),
        url_type="authorization endpoint",
        validation_mode=validation_mode,
    )


def generate_registration_endpoint_url(
    registration_endpoint_url: str,
    *,
    validation_mode: LTIUrlValidationMode = "canonicalize",
) -> str:
    # Lazy import avoids config import cycles.
    from pingpong.config import config

    return _generate_lti_url(
        unverified_url=registration_endpoint_url,
        security_config=(
            config.lti.security.registration_endpoint if config.lti else None
        ),
        url_type="registration endpoint",
        validation_mode=validation_mode,
    )


def generate_jwks_uri_url(
    jwks_uri_url: str,
    *,
    validation_mode: LTIUrlValidationMode = "canonicalize",
) -> str:
    # Lazy import avoids config import cycles.
    from pingpong.config import config

    return _generate_lti_url(
        unverified_url=jwks_uri_url,
        security_config=config.lti.security.jwks_uri if config.lti else None,
        url_type="JWKS URI",
        validation_mode=validation_mode,
    )


def generate_token_endpoint_url(
    token_endpoint_url: str,
    *,
    validation_mode: LTIUrlValidationMode = "canonicalize",
) -> str:
    # Lazy import avoids config import cycles.
    from pingpong.config import config

    return _generate_lti_url(
        unverified_url=token_endpoint_url,
        security_config=config.lti.security.token_endpoint if config.lti else None,
        url_type="token endpoint",
        validation_mode=validation_mode,
    )
