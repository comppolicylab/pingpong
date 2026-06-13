import inspect
import logging

import pytest
from pydantic import ValidationError
from pydantic_settings import BaseSettings

import pingpong.config as config_module
from pingpong.config import (
    Config,
    LEGACY_OPENID_CONFIGURATION_PATHS_DEFAULTS,
    LocalAudioStoreSettings,
    LocalDiskBackedSettings,
    LocalStoreSettings,
    LTISettings,
    SqliteSettings,
    config,
)
from pingpong.lti.allowlist import generate_safe_lti_url


def test_config_loads_deployment_identifier():
    assert config.deployment_identifier == "test"


def _s3_store_settings() -> dict[str, dict[str, str]]:
    return {
        "artifact_store": {"type": "s3", "save_target": "artifact-bucket"},
        "file_store": {"type": "s3", "save_target": "file-bucket"},
        "audio_store": {"type": "s3", "save_target": "audio-bucket"},
        "lecture_video_audio_store": {
            "type": "s3",
            "save_target": "lecture-audio-bucket",
        },
    }


def _minimal_config_settings() -> dict[str, object]:
    return {
        **_s3_store_settings(),
        "db": SqliteSettings(path=":memory:"),
        "auth": {"authn_methods": [], "secret_keys": [{"key": "secret"}]},
        "authz": {"type": "openfga"},
        "email": {"type": "mock"},
    }


def test_config_defaults_deployment_identifier_to_unknown():
    cfg = Config.model_validate(_minimal_config_settings())

    assert cfg.deployment_identifier == "unknown"
    assert cfg.lms.lms_instances == []


def test_config_injects_local_store_defaults_in_development():
    cfg = Config.model_validate(
        {
            "development": True,
            "db": SqliteSettings(path=":memory:"),
            "auth": {"authn_methods": [], "secret_keys": [{"key": "secret"}]},
            "authz": {"type": "openfga"},
            "email": {"type": "mock"},
        }
    )

    assert isinstance(cfg.artifact_store, LocalStoreSettings)
    assert cfg.artifact_store.save_target == "local_exports/thread_exports"
    assert isinstance(cfg.file_store, LocalStoreSettings)
    assert cfg.file_store.save_target == "local_exports/files"
    assert isinstance(cfg.audio_store, LocalAudioStoreSettings)
    assert cfg.audio_store.save_target == "local_exports/voice_mode_recordings"
    assert isinstance(cfg.lecture_video_audio_store, LocalAudioStoreSettings)
    assert (
        cfg.lecture_video_audio_store.save_target
        == "local_exports/lecture_video_narrations"
    )


def test_config_requires_explicit_stores_outside_development():
    with pytest.raises(ValidationError) as excinfo:
        Config.model_validate(
            {
                "db": SqliteSettings(path=":memory:"),
                "auth": {"authn_methods": [], "secret_keys": [{"key": "secret"}]},
                "authz": {"type": "openfga"},
                "email": {"type": "mock"},
            }
        )

    error_text = str(excinfo.value)
    assert "artifact_store" in error_text
    assert "file_store" in error_text
    assert "audio_store" in error_text
    assert "lecture_video_audio_store" in error_text


def test_config_rejects_local_disk_store_outside_development():
    settings = {
        **_minimal_config_settings(),
        "artifact_store": {
            "type": "local",
            "save_target": "local_exports/thread_exports",
        },
    }

    with pytest.raises(ValidationError) as excinfo:
        Config.model_validate(settings)

    error_text = str(excinfo.value)
    assert (
        "Local disk-backed stores are only allowed when development is true"
        in error_text
    )
    assert "artifact_store" in error_text


def test_config_rejects_local_nested_store_outside_development():
    settings = {
        **_minimal_config_settings(),
        "lti": {"key_store": {"type": "local", "directory": "local_exports/lti_keys"}},
    }

    with pytest.raises(ValidationError) as excinfo:
        Config.model_validate(settings)

    error_text = str(excinfo.value)
    assert (
        "Local disk-backed stores are only allowed when development is true"
        in error_text
    )
    assert "lti.key_store" in error_text


def test_local_type_settings_are_marked_disk_backed():
    local_type_settings_classes = []
    for cls in vars(config_module).values():
        if not inspect.isclass(cls) or not issubclass(cls, BaseSettings):
            continue

        type_field = cls.model_fields.get("type")
        if type_field is not None and type_field.default == "local":
            local_type_settings_classes.append(cls)

    assert local_type_settings_classes
    assert all(
        issubclass(cls, LocalDiskBackedSettings) for cls in local_type_settings_classes
    )


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
    ]
    assert settings.security.paths.allow == ["*"]
    assert settings.security.openid_configuration.paths.allow == [
        *LEGACY_OPENID_CONFIGURATION_PATHS_DEFAULTS,
        "/custom/openid",
    ]
    assert settings.security.allow_http_in_development is True

    assert "Deprecated config key 'lti.platform_url_allowlist'" in caplog.text
    assert "['platform.example.com', 'tool.example.com']" in caplog.text
    assert "Deprecated config key 'lti.openid_configuration_paths'" in caplog.text
    assert "Deprecated config key 'lti.dev_http_hosts'" in caplog.text
    assert "allow_http_in_development = True" in caplog.text
    dev_http_hosts_warning = next(
        record.getMessage()
        for record in caplog.records
        if "lti.dev_http_hosts" in record.getMessage()
    )
    assert "[lti.security.hosts]" in dev_http_hosts_warning


def test_lti_settings_legacy_dev_http_hosts_only_enable_http_in_development():
    settings = LTISettings.model_validate(
        {
            **_base_lti_settings(),
            "dev_http_hosts": [" Canvas.Docker ", "localhost", ""],
        }
    )

    assert settings.security.hosts.allow == ["*"]
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


def test_lti_settings_prefers_security_hosts_over_legacy_platform_allowlist():
    settings = LTISettings.model_validate(
        {
            **_base_lti_settings(),
            "platform_url_allowlist": ["*.legacy.example.com"],
            "security": {
                "hosts": {
                    "allow": ["canvas.example.edu"],
                }
            },
        }
    )

    assert settings.security.hosts.allow == ["canvas.example.edu"]


def test_lti_settings_prefers_security_http_flag_over_legacy_dev_http_hosts():
    settings = LTISettings.model_validate(
        {
            **_base_lti_settings(),
            "dev_http_hosts": "not-a-list",
            "security": {
                "allow_http_in_development": False,
            },
        }
    )

    assert settings.security.allow_http_in_development is False


def test_lti_settings_mixed_legacy_config_preserves_global_openid_paths():
    settings = LTISettings.model_validate(
        {
            **_base_lti_settings(),
            "platform_url_allowlist": ["platform.example.com"],
            "security": {
                "paths": {
                    "allow": ["/openid/custom/*"],
                    "deny": [],
                },
            },
        }
    )

    assert settings.security.paths.allow == ["/openid/custom/*"]
    assert settings.security.openid_configuration.paths.allow == ["*"]
    assert settings.security.openid_configuration.paths.model_fields_set == set()


def test_lti_settings_normalizes_legacy_platform_allowlist_urls():
    settings = LTISettings.model_validate(
        {
            **_base_lti_settings(),
            "platform_url_allowlist": ["https://canvas.example.edu"],
        }
    )

    assert settings.security.hosts.allow == ["canvas.example.edu"]
    assert (
        generate_safe_lti_url(
            "https://canvas.example.edu/.well-known/openid-configuration",
            "openid_configuration",
            settings.security.hosts.allow,
            settings.security.hosts.deny,
            settings.security.openid_configuration.paths.allow or ["*"],
            settings.security.openid_configuration.paths.deny or [],
            settings.security.allow_http_in_development,
        )
        == "https://canvas.example.edu/.well-known/openid-configuration"
    )


def test_lti_settings_rejects_unknown_extra_key():
    with pytest.raises(ValidationError) as excinfo:
        LTISettings.model_validate(
            {
                **_base_lti_settings(),
                "unknown_lti_key": "x",
            }
        )

    assert "Extra inputs are not permitted" in str(excinfo.value)
