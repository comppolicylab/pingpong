from types import SimpleNamespace

import pytest

import pingpong.config as config_module
from pingpong.config import LTISettings
from pingpong.lti import endpoints


def _base_lti_settings() -> dict[str, object]:
    return {"key_store": {"type": "local", "directory": "local_exports/lti_keys"}}


def _patch_runtime_config(monkeypatch, *, lti: LTISettings, development: bool) -> None:
    monkeypatch.setattr(
        config_module,
        "config",
        SimpleNamespace(
            lti=lti,
            development=development,
        ),
    )


def test_lti_security_empty_uses_defaults(monkeypatch):
    settings = LTISettings.model_validate(_base_lti_settings())
    _patch_runtime_config(monkeypatch, lti=settings, development=True)

    generated = endpoints.generate_token_endpoint_url(
        "http://any-host.example.com/any/path"
    )

    assert generated == "http://any-host.example.com/any/path"
    assert endpoints.allow_redirects(settings.security.token_endpoint) is True


def test_lti_security_only_global_applies_to_endpoint(monkeypatch):
    settings = LTISettings.model_validate(
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

    generated = endpoints.generate_token_endpoint_url(
        "http://global.example.com/global/token"
    )

    assert generated == "https://global.example.com/global/token"
    assert endpoints.allow_redirects(settings.security.token_endpoint) is False

    with pytest.raises(ValueError, match="Invalid token endpoint URL hostname"):
        endpoints.generate_token_endpoint_url("https://other.example.com/global/token")


def test_lti_security_specific_without_global_override(monkeypatch):
    settings = LTISettings.model_validate(
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

    generated = endpoints.generate_token_endpoint_url(
        "http://specific.example.com/token/access"
    )

    assert generated == "https://specific.example.com/token/access"
    assert endpoints.allow_redirects(settings.security.token_endpoint) is False

    with pytest.raises(ValueError, match="Invalid token endpoint URL hostname"):
        endpoints.generate_token_endpoint_url("https://global.example.com/token/access")


def test_lti_security_specific_overrides_global(monkeypatch):
    settings = LTISettings.model_validate(
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
