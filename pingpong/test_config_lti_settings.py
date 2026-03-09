import logging

import pytest
from pydantic import ValidationError

from pingpong.config import LEGACY_OPENID_CONFIGURATION_PATHS_DEFAULTS, LTISettings


def _base_lti_settings() -> dict[str, object]:
    return {"key_store": {"type": "local", "directory": "local_exports/lti_keys"}}


def test_lti_settings_accepts_current_security_shape():
    settings = LTISettings.model_validate(
        {
            **_base_lti_settings(),
            "security": {
                "openid_configuration": {
                    "allow_http_in_development": False,
                    "hosts": {
                        "allow": ["*.instructure.com", "canvas.docker"],
                        "deny": ["evil.instructure.com"],
                    },
                    "paths": {
                        "allow": ["/.well-known/openid-configuration", "/openid/*"],
                        "deny": ["/private/*"],
                    },
                }
            },
        }
    )

    openid_security = settings.security.openid_configuration
    assert openid_security.allow_http_in_development is False
    assert openid_security.hosts.allow == ["*.instructure.com", "canvas.docker"]
    assert openid_security.hosts.deny == ["evil.instructure.com"]
    assert openid_security.paths.allow == [
        "/.well-known/openid-configuration",
        "/openid/*",
    ]
    assert openid_security.paths.deny == ["/private/*"]


def test_lti_settings_maps_legacy_fields_and_logs_deprecation(caplog):
    caplog.set_level(logging.WARNING)

    settings = LTISettings.model_validate(
        {
            **_base_lti_settings(),
            "platform_url_allowlist": ["platform.example.com", "tool.example.com"],
            "openid_configuration_paths": {
                "mode": "append",
                "paths": ["/custom/openid"],
            },
            "dev_http_hosts": ["canvas.docker"],
        }
    )

    assert settings.security.hosts.allow == [
        "platform.example.com",
        "tool.example.com",
        "canvas.docker",
    ]
    assert settings.security.paths.allow == ["*"]
    assert settings.security.openid_configuration.paths.allow == [
        *LEGACY_OPENID_CONFIGURATION_PATHS_DEFAULTS,
        "/custom/openid",
    ]
    assert settings.security.allow_http_in_development is True

    assert "Deprecated config key 'lti.platform_url_allowlist'" in caplog.text
    assert (
        "['platform.example.com', 'tool.example.com', 'canvas.docker']" in caplog.text
    )
    assert "Deprecated config key 'lti.openid_configuration_paths'" in caplog.text
    assert "Deprecated config key 'lti.dev_http_hosts'" in caplog.text
    assert "allow_http_in_development = True" in caplog.text
    dev_http_hosts_warning = next(
        record.getMessage()
        for record in caplog.records
        if "lti.dev_http_hosts" in record.getMessage()
    )
    assert "[lti.security.hosts]" in dev_http_hosts_warning


def test_lti_settings_maps_legacy_dev_http_hosts_into_security_hosts_allow():
    settings = LTISettings.model_validate(
        {
            **_base_lti_settings(),
            "dev_http_hosts": [" Canvas.Docker ", "localhost", ""],
        }
    )

    assert settings.security.hosts.allow == ["canvas.docker", "localhost"]
    assert settings.security.paths.allow == ["*"]
    assert settings.security.openid_configuration.paths.allow == list(
        LEGACY_OPENID_CONFIGURATION_PATHS_DEFAULTS
    )
    assert settings.security.allow_http_in_development is True


def test_lti_settings_maps_legacy_defaults_when_only_platform_allowlist_is_set():
    settings = LTISettings.model_validate(
        {
            **_base_lti_settings(),
            "platform_url_allowlist": ["platform.example.com"],
        }
    )

    assert settings.security.hosts.allow == ["platform.example.com"]
    assert settings.security.paths.allow == ["*"]
    assert settings.security.openid_configuration.paths.allow == list(
        LEGACY_OPENID_CONFIGURATION_PATHS_DEFAULTS
    )
    assert settings.security.allow_http_in_development is True


def test_lti_settings_rejects_unknown_extra_key():
    with pytest.raises(ValidationError) as excinfo:
        LTISettings.model_validate(
            {
                **_base_lti_settings(),
                "unknown_lti_key": "x",
            }
        )

    assert "Extra inputs are not permitted" in str(excinfo.value)
