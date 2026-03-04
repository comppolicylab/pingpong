from types import SimpleNamespace

import pytest

from pingpong.lti import allowlist


@pytest.mark.parametrize(
    ("hostname", "pattern", "expected"),
    [
        ("example.com", "example.com", True),
        ("Example.COM.", "example.com", True),
        ("example.com", " EXAMPLE.COM ", True),
        ("sub.example.com", "*.example.com", True),
        ("example.com", "*.example.com", True),
        ("badexample.com", "*.example.com", False),
        ("example.com", "*", True),
        ("example.com", "", False),
        ("example.com", "   ", False),
        ("example.com", "example.com.", False),
    ],
)
def test_hostname_matches(hostname, pattern, expected):
    assert allowlist._hostname_matches(hostname, pattern) is expected


def test_hostname_allowed_deny_precedence():
    assert (
        allowlist._hostname_allowed(
            "api.example.com",
            allow_patterns=["*.example.com"],
            deny_patterns=["api.example.com"],
        )
        is False
    )


def test_hostname_allowed_true_when_allowed_and_not_denied():
    assert (
        allowlist._hostname_allowed(
            "api.example.com",
            allow_patterns=["*.example.com"],
            deny_patterns=["blocked.example.com"],
        )
        is True
    )


def test_hostname_allowed_false_when_no_pattern_matches():
    assert (
        allowlist._hostname_allowed(
            "api.example.com",
            allow_patterns=["canvas.instructure.com"],
            deny_patterns=[],
        )
        is False
    )


@pytest.mark.parametrize(
    ("path", "pattern", "expected"),
    [
        ("/", "*", True),
        ("/openid", "/openid", True),
        ("/openid/config", "/openid/*", True),
        ("/openid", "/openid/*", False),
        ("/openid/config", " /openid/* ", True),
        ("/openid", "", False),
        ("/openid", "   ", False),
        ("/a+b", "/a+b", True),
    ],
)
def test_path_matches(path, pattern, expected):
    assert allowlist._path_matches(path, pattern) is expected


def test_path_allowed_deny_precedence():
    assert (
        allowlist._path_allowed(
            "/.well-known/private/openid-configuration",
            allow_patterns=["/.well-known/*"],
            deny_patterns=["*/private/*"],
        )
        is False
    )


def test_path_allowed_true_when_allowed_and_not_denied():
    assert (
        allowlist._path_allowed(
            "/.well-known/openid-configuration",
            allow_patterns=["/.well-known/*"],
            deny_patterns=["/private/*"],
        )
        is True
    )


def test_path_allowed_false_when_no_pattern_matches():
    assert (
        allowlist._path_allowed(
            "/openid",
            allow_patterns=["/.well-known/*"],
            deny_patterns=[],
        )
        is False
    )


def _make_lti_security_config(
    *,
    host_allow: list[str],
    host_deny: list[str],
    path_allow: list[str],
    path_deny: list[str],
    allow_http_in_development: bool = True,
):
    return SimpleNamespace(
        lti=SimpleNamespace(
            security=SimpleNamespace(
                openid_configuration=SimpleNamespace(
                    allow_http_in_development=allow_http_in_development,
                    hosts=SimpleNamespace(allow=host_allow, deny=host_deny),
                    paths=SimpleNamespace(allow=path_allow, deny=path_deny),
                )
            )
        )
    )


def test_openid_configuration_patterns_defaults_when_lti_is_none(monkeypatch):
    import pingpong.config as config_module

    monkeypatch.setattr(config_module, "config", SimpleNamespace(lti=None))

    assert allowlist._openid_configuration_patterns() == (["*"], [], ["*"], [])


def test_openid_configuration_patterns_reads_lti_security_settings(monkeypatch):
    import pingpong.config as config_module

    expected = (
        ["*.instructure.com", "canvas.instructure.com"],
        ["evil.instructure.com"],
        ["/.well-known/*", "/openid/*"],
        ["/private/*"],
    )

    monkeypatch.setattr(
        config_module,
        "config",
        _make_lti_security_config(
            host_allow=expected[0],
            host_deny=expected[1],
            path_allow=expected[2],
            path_deny=expected[3],
        ),
    )

    assert allowlist._openid_configuration_patterns() == expected


def test_allow_http_in_development_defaults_when_lti_is_none(monkeypatch):
    import pingpong.config as config_module

    monkeypatch.setattr(config_module, "config", SimpleNamespace(lti=None))

    assert allowlist._allow_http_in_development() is True


def test_allow_http_in_development_reads_lti_security_settings(monkeypatch):
    import pingpong.config as config_module

    monkeypatch.setattr(
        config_module,
        "config",
        _make_lti_security_config(
            host_allow=["*"],
            host_deny=[],
            path_allow=["*"],
            path_deny=[],
            allow_http_in_development=False,
        ),
    )

    assert allowlist._allow_http_in_development() is False


def _patch_patterns(
    monkeypatch,
    *,
    host_allow: list[str] | None = None,
    host_deny: list[str] | None = None,
    path_allow: list[str] | None = None,
    path_deny: list[str] | None = None,
):
    monkeypatch.setattr(
        allowlist,
        "_openid_configuration_patterns",
        lambda: (
            host_allow or ["*"],
            host_deny or [],
            path_allow or ["*"],
            path_deny or [],
        ),
    )


def _patch_allow_http_in_development(
    monkeypatch,
    *,
    allow_http_in_development: bool,
):
    monkeypatch.setattr(
        allowlist,
        "_allow_http_in_development",
        lambda: allow_http_in_development,
    )


def _patch_is_development(
    monkeypatch,
    *,
    is_development: bool,
):
    import pingpong.config as config_module

    monkeypatch.setattr(
        config_module,
        "config",
        SimpleNamespace(development=is_development, lti=None),
    )


def test_generate_openid_configuration_url_normalizes_and_strips_url_parts(monkeypatch):
    _patch_patterns(monkeypatch)

    result = allowlist.generate_openid_configuration_url(
        "HTTPS://user:pass@Platform.Example.com:8443/.well-known/openid-configuration?x=1#frag"
    )

    assert result == "https://platform.example.com/.well-known/openid-configuration"


def test_generate_openid_configuration_url_defaults_path_to_root(monkeypatch):
    _patch_patterns(monkeypatch)

    result = allowlist.generate_openid_configuration_url("https://platform.example.com")

    assert result == "https://platform.example.com/"


def test_generate_openid_configuration_url_strips_trailing_host_dot(monkeypatch):
    _patch_patterns(monkeypatch)

    result = allowlist.generate_openid_configuration_url(
        "https://platform.example.com./openid"
    )

    assert result == "https://platform.example.com/openid"


def test_generate_openid_configuration_url_preserves_http_only_in_development(
    monkeypatch,
):
    _patch_patterns(monkeypatch)
    _patch_allow_http_in_development(monkeypatch, allow_http_in_development=True)
    _patch_is_development(monkeypatch, is_development=True)

    result = allowlist.generate_openid_configuration_url(
        "http://platform.example.com/openid"
    )

    assert result == "http://platform.example.com/openid"


def test_generate_openid_configuration_url_forces_https_when_http_disabled_in_development(
    monkeypatch,
):
    _patch_patterns(monkeypatch)
    _patch_allow_http_in_development(monkeypatch, allow_http_in_development=False)
    _patch_is_development(monkeypatch, is_development=True)

    result = allowlist.generate_openid_configuration_url(
        "http://platform.example.com/openid"
    )

    assert result == "https://platform.example.com/openid"


def test_generate_openid_configuration_url_forces_https_in_non_development(monkeypatch):
    _patch_patterns(monkeypatch)
    _patch_allow_http_in_development(monkeypatch, allow_http_in_development=True)
    _patch_is_development(monkeypatch, is_development=False)

    result = allowlist.generate_openid_configuration_url(
        "http://platform.example.com/openid"
    )

    assert result == "https://platform.example.com/openid"


def test_generate_openid_configuration_url_forces_https_for_non_http_scheme(
    monkeypatch,
):
    _patch_patterns(monkeypatch)
    _patch_allow_http_in_development(monkeypatch, allow_http_in_development=True)
    _patch_is_development(monkeypatch, is_development=True)

    result = allowlist.generate_openid_configuration_url(
        "ftp://platform.example.com/openid"
    )

    assert result == "https://platform.example.com/openid"


def test_generate_openid_configuration_url_rejects_invalid_hostname_pattern(
    monkeypatch,
):
    _patch_patterns(monkeypatch)

    with pytest.raises(ValueError, match="Invalid openid_configuration URL hostname"):
        allowlist.generate_openid_configuration_url(
            "https://invalid_host.example.com/openid"
        )


def test_generate_openid_configuration_url_rejects_missing_hostname(monkeypatch):
    _patch_patterns(monkeypatch)

    with pytest.raises(ValueError, match="Invalid openid_configuration URL hostname"):
        allowlist.generate_openid_configuration_url("/.well-known/openid-configuration")


def test_generate_openid_configuration_url_rejects_hostname_not_on_allowlist(
    monkeypatch,
):
    _patch_patterns(monkeypatch, host_allow=["canvas.instructure.com"])

    with pytest.raises(ValueError, match="Invalid openid_configuration URL hostname"):
        allowlist.generate_openid_configuration_url(
            "https://platform.example.com/openid"
        )


def test_generate_openid_configuration_url_rejects_denied_hostname(monkeypatch):
    _patch_patterns(monkeypatch, host_deny=["*.example.com"])

    with pytest.raises(ValueError, match="Invalid openid_configuration URL hostname"):
        allowlist.generate_openid_configuration_url(
            "https://platform.example.com/openid"
        )


def test_generate_openid_configuration_url_rejects_invalid_path_pattern(monkeypatch):
    _patch_patterns(monkeypatch)

    with pytest.raises(ValueError, match="Invalid openid_configuration URL path"):
        allowlist.generate_openid_configuration_url(
            "https://platform.example.com/openid%20configuration"
        )


def test_generate_openid_configuration_url_rejects_path_not_on_allowlist(monkeypatch):
    _patch_patterns(monkeypatch, path_allow=["/.well-known/*"])

    with pytest.raises(ValueError, match="Invalid openid_configuration URL path"):
        allowlist.generate_openid_configuration_url(
            "https://platform.example.com/openid"
        )


def test_generate_openid_configuration_url_rejects_denied_path(monkeypatch):
    _patch_patterns(monkeypatch, path_deny=["/private/*"])

    with pytest.raises(ValueError, match="Invalid openid_configuration URL path"):
        allowlist.generate_openid_configuration_url(
            "https://platform.example.com/private/openid"
        )


def test_generate_openid_configuration_url_accepts_host_and_path_allowlist(monkeypatch):
    _patch_patterns(
        monkeypatch,
        host_allow=["*.instructure.com"],
        path_allow=["/.well-known/*"],
    )

    result = allowlist.generate_openid_configuration_url(
        "https://canvas.instructure.com/.well-known/openid-configuration"
    )

    assert result == "https://canvas.instructure.com/.well-known/openid-configuration"
