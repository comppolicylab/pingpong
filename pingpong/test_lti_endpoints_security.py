from types import SimpleNamespace

import pytest

import pingpong.config as config_module
from pingpong.lti import endpoints


def _base_lti_settings() -> dict[str, object]:
    return {"key_store": {"type": "local", "directory": "local_exports/lti_keys"}}


def _patch_runtime_config(
    monkeypatch, *, lti: config_module.LTISettings, development: bool
) -> None:
    monkeypatch.setattr(
        config_module,
        "config",
        SimpleNamespace(
            lti=lti,
            development=development,
        ),
    )


def test_lti_security_empty_uses_defaults(monkeypatch):
    settings = config_module.LTISettings.model_validate(_base_lti_settings())
    _patch_runtime_config(monkeypatch, lti=settings, development=True)

    generated = endpoints.generate_token_endpoint_url(
        "http://any-host.example.com/any/path"
    )

    assert generated == "http://any-host.example.com/any/path"
    assert endpoints.allow_redirects(settings.security.token_endpoint) is True


def test_lti_security_only_global_applies_to_endpoint(monkeypatch):
    settings = config_module.LTISettings.model_validate(
        {
            **_base_lti_settings(),
            "security": {
                "allow_http_in_development": False,
                "allow_redirects": False,
                "hosts": {"allow": ["global.example.com"], "deny": []},
                "paths": {"allow": ["/global/*"], "deny": []},
            },
        }
    )
    _patch_runtime_config(monkeypatch, lti=settings, development=True)

    with pytest.raises(
        ValueError, match="Invalid URL for token endpoint: HTTP is not allowed"
    ):
        endpoints.generate_token_endpoint_url("http://global.example.com/global/token")
    assert endpoints.allow_redirects(settings.security.token_endpoint) is False

    with pytest.raises(ValueError, match="Invalid token endpoint URL hostname"):
        endpoints.generate_token_endpoint_url("https://other.example.com/global/token")


def test_lti_security_specific_without_global_override(monkeypatch):
    settings = config_module.LTISettings.model_validate(
        {
            **_base_lti_settings(),
            "security": {
                "token_endpoint": {
                    "allow_http_in_development": False,
                    "allow_redirects": False,
                    "hosts": {"allow": ["specific.example.com"], "deny": []},
                    "paths": {"allow": ["/token/*"], "deny": []},
                }
            },
        }
    )
    _patch_runtime_config(monkeypatch, lti=settings, development=True)

    with pytest.raises(
        ValueError, match="Invalid URL for token endpoint: HTTP is not allowed"
    ):
        endpoints.generate_token_endpoint_url(
            "http://specific.example.com/token/access"
        )
    assert endpoints.allow_redirects(settings.security.token_endpoint) is False

    with pytest.raises(ValueError, match="Invalid token endpoint URL hostname"):
        endpoints.generate_token_endpoint_url("https://global.example.com/token/access")


def test_lti_security_specific_overrides_global(monkeypatch):
    settings = config_module.LTISettings.model_validate(
        {
            **_base_lti_settings(),
            "security": {
                "allow_http_in_development": False,
                "allow_redirects": False,
                "hosts": {"allow": ["global.example.com"], "deny": []},
                "paths": {"allow": ["/global/*"], "deny": []},
                "token_endpoint": {
                    "allow_http_in_development": True,
                    "allow_redirects": True,
                    "hosts": {"allow": ["specific.example.com"], "deny": []},
                    "paths": {"allow": ["/specific/*"], "deny": []},
                },
            },
        }
    )
    _patch_runtime_config(monkeypatch, lti=settings, development=True)

    generated = endpoints.generate_token_endpoint_url(
        "http://specific.example.com/specific/access"
    )

    assert generated == "http://specific.example.com/specific/access"
    assert endpoints.allow_redirects(settings.security.token_endpoint) is True

    with pytest.raises(ValueError, match="Invalid token endpoint URL hostname"):
        endpoints.generate_token_endpoint_url(
            "https://global.example.com/specific/access"
        )


def test_lti_security_empty_nested_endpoint_tables_inherit_global(monkeypatch):
    settings = config_module.LTISettings.model_validate(
        {
            **_base_lti_settings(),
            "security": {
                "allow_http_in_development": False,
                "allow_redirects": False,
                "hosts": {"allow": ["global.example.com"], "deny": []},
                "paths": {"allow": ["/global/*"], "deny": ["/private/*"]},
                "token_endpoint": {
                    "hosts": {},
                    "paths": {},
                },
            },
        }
    )
    _patch_runtime_config(monkeypatch, lti=settings, development=True)

    with pytest.raises(
        ValueError, match="Invalid URL for token endpoint: HTTP is not allowed"
    ):
        endpoints.generate_token_endpoint_url("http://global.example.com/global/token")
    assert endpoints.allow_redirects(settings.security.token_endpoint) is False

    with pytest.raises(ValueError, match="Invalid token endpoint URL hostname"):
        endpoints.generate_token_endpoint_url("https://other.example.com/global/token")

    with pytest.raises(ValueError, match="Invalid token endpoint URL path"):
        endpoints.generate_token_endpoint_url(
            "https://global.example.com/private/token"
        )


def test_lti_security_partial_nested_endpoint_tables_merge_with_global(monkeypatch):
    settings = config_module.LTISettings.model_validate(
        {
            **_base_lti_settings(),
            "security": {
                "hosts": {
                    "allow": ["global.example.com"],
                    "deny": ["blocked.example.com"],
                },
                "paths": {"allow": ["/global/*"], "deny": ["/private/*"]},
                "token_endpoint": {
                    "hosts": {"allow": ["specific.example.com"]},
                    "paths": {"deny": ["/blocked/*"]},
                },
            },
        }
    )
    _patch_runtime_config(monkeypatch, lti=settings, development=False)

    generated = endpoints.generate_token_endpoint_url(
        "https://specific.example.com/global/token"
    )

    assert generated == "https://specific.example.com/global/token"

    with pytest.raises(ValueError, match="Invalid token endpoint URL hostname"):
        endpoints.generate_token_endpoint_url(
            "https://blocked.example.com/global/token"
        )

    with pytest.raises(ValueError, match="Invalid token endpoint URL hostname"):
        endpoints.generate_token_endpoint_url("https://global.example.com/global/token")

    with pytest.raises(ValueError, match="Invalid token endpoint URL path"):
        endpoints.generate_token_endpoint_url(
            "https://specific.example.com/blocked/token"
        )


def test_mixed_legacy_config_keeps_global_openid_path_rules(monkeypatch):
    settings = config_module.LTISettings.model_validate(
        {
            **_base_lti_settings(),
            "platform_url_allowlist": ["platform.example.com"],
            "security": {
                "hosts": {"allow": ["platform.example.com"], "deny": []},
                "paths": {"allow": ["/openid/custom/*"], "deny": []},
            },
        }
    )
    _patch_runtime_config(monkeypatch, lti=settings, development=False)

    generated = endpoints.generate_openid_configuration_url(
        "https://platform.example.com/openid/custom/config"
    )

    assert generated == "https://platform.example.com/openid/custom/config"

    with pytest.raises(ValueError, match="Invalid OpenID configuration URL path"):
        endpoints.generate_openid_configuration_url(
            "https://platform.example.com/.well-known/openid-configuration"
        )
