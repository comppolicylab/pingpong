import pytest

from pingpong.lti import allowlist


@pytest.mark.parametrize(
    ("hostname", "pattern", "expected"),
    [
        ("example.com", "example.com", True),
        ("Example.COM.", "example.com", True),
        ("example.com", " EXAMPLE.COM ", True),
        ("sub.example.com", "*.example.com", True),
        ("example.com", "*.example.com", False),
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
    ],
)
def test_path_matches(path, pattern, expected):
    assert allowlist._path_matches(path, pattern) is expected


@pytest.fixture
def development_config(config, monkeypatch, request):
    monkeypatch.setattr(config, "development", request.param)
    return config


@pytest.mark.parametrize("development_config", [False], indirect=True)
def test_generate_safe_lti_url_normalizes_and_validates(development_config):
    result = allowlist.generate_safe_lti_url(
        unverified_url="https://Platform.Example.com./.well-known/openid-configuration?x=1&y=2",
        url_type="OpenID configuration",
        host_allow=["*.example.com"],
        host_deny=[],
        path_allow=["/.well-known/*"],
        path_deny=[],
        allow_http_in_development=True,
    )

    assert (
        result
        == "https://platform.example.com/.well-known/openid-configuration?x=1&y=2"
    )


@pytest.mark.parametrize("development_config", [False], indirect=True)
def test_generate_safe_lti_url_treats_empty_path_as_root(development_config):
    result = allowlist.generate_safe_lti_url(
        unverified_url="https://platform.example.com",
        url_type="Token endpoint",
        host_allow=["*.example.com"],
        host_deny=[],
        path_allow=["/"],
        path_deny=[],
        allow_http_in_development=True,
    )

    assert result == "https://platform.example.com/"


@pytest.mark.parametrize("development_config", [True], indirect=True)
def test_generate_safe_lti_url_allows_http_only_in_development(development_config):
    result = allowlist.generate_safe_lti_url(
        unverified_url="http://platform.example.com/openid",
        url_type="OpenID configuration",
        host_allow=["*.example.com"],
        host_deny=[],
        path_allow=["/openid"],
        path_deny=[],
        allow_http_in_development=True,
    )

    assert result == "http://platform.example.com/openid"


@pytest.mark.parametrize("development_config", [True], indirect=True)
def test_generate_safe_lti_url_forces_https_when_http_not_allowed(
    development_config,
):
    result = allowlist.generate_safe_lti_url(
        unverified_url="http://platform.example.com/openid",
        url_type="OpenID configuration",
        host_allow=["*.example.com"],
        host_deny=[],
        path_allow=["/openid"],
        path_deny=[],
        allow_http_in_development=False,
    )

    assert result == "https://platform.example.com/openid"


@pytest.mark.parametrize("development_config", [True], indirect=True)
def test_generate_safe_lti_url_accepts_default_http_port_before_https_upgrade(
    development_config,
):
    result = allowlist.generate_safe_lti_url(
        unverified_url="http://platform.example.com:80/openid",
        url_type="OpenID configuration",
        host_allow=["*.example.com"],
        host_deny=[],
        path_allow=["/openid"],
        path_deny=[],
        allow_http_in_development=False,
    )

    assert result == "https://platform.example.com:443/openid"


@pytest.mark.parametrize("development_config", [False], indirect=True)
def test_generate_safe_lti_url_rejects_invalid_hostname(development_config):
    with pytest.raises(ValueError, match="Invalid OpenID configuration URL hostname"):
        allowlist.generate_safe_lti_url(
            unverified_url="https://invalid_host.example.com/openid",
            url_type="OpenID configuration",
            host_allow=["*"],
            host_deny=[],
            path_allow=["*"],
            path_deny=[],
            allow_http_in_development=True,
        )


@pytest.mark.parametrize("development_config", [False], indirect=True)
def test_generate_safe_lti_url_rejects_invalid_url_shape(development_config):
    with pytest.raises(ValueError, match="Invalid URL for OpenID configuration"):
        allowlist.generate_safe_lti_url(
            unverified_url="/.well-known/openid-configuration",
            url_type="OpenID configuration",
            host_allow=["*"],
            host_deny=[],
            path_allow=["*"],
            path_deny=[],
            allow_http_in_development=True,
        )


@pytest.mark.parametrize("development_config", [False], indirect=True)
def test_generate_safe_lti_url_rejects_disallowed_host(development_config):
    with pytest.raises(ValueError, match="Invalid OpenID configuration URL hostname"):
        allowlist.generate_safe_lti_url(
            unverified_url="https://platform.example.com/openid",
            url_type="OpenID configuration",
            host_allow=["canvas.instructure.com"],
            host_deny=[],
            path_allow=["*"],
            path_deny=[],
            allow_http_in_development=True,
        )


@pytest.mark.parametrize("development_config", [False], indirect=True)
def test_generate_safe_lti_url_rejects_disallowed_path(development_config):
    with pytest.raises(ValueError, match="Invalid OpenID configuration URL path"):
        allowlist.generate_safe_lti_url(
            unverified_url="https://platform.example.com/openid",
            url_type="OpenID configuration",
            host_allow=["*.example.com"],
            host_deny=[],
            path_allow=["/.well-known/*"],
            path_deny=[],
            allow_http_in_development=True,
        )


@pytest.mark.parametrize("development_config", [False], indirect=True)
def test_generate_safe_lti_url_double_encodes_encoded_path_separators(
    development_config,
):
    result = allowlist.generate_safe_lti_url(
        unverified_url="https://platform.example.com/api/private%2Ftoken",
        url_type="OpenID configuration",
        host_allow=["*.example.com"],
        host_deny=[],
        path_allow=["/api/*"],
        path_deny=["/api/private/*"],
        allow_http_in_development=True,
    )

    assert result == "https://platform.example.com/api/private%252Ftoken"


@pytest.mark.parametrize(
    ("unverified_url", "expected"),
    [
        (
            "https://platform.example.com/foo bar",
            "https://platform.example.com/foo%20bar",
        ),
        (
            "https://platform.example.com/caf\u00e9",
            "https://platform.example.com/caf%C3%A9",
        ),
    ],
)
@pytest.mark.parametrize("development_config", [False], indirect=True)
def test_generate_safe_lti_url_accepts_percent_encoded_sanitized_paths(
    development_config, unverified_url, expected
):
    result = allowlist.generate_safe_lti_url(
        unverified_url=unverified_url,
        url_type="OpenID configuration",
        host_allow=["*.example.com"],
        host_deny=[],
        path_allow=["*"],
        path_deny=[],
        allow_http_in_development=True,
    )

    assert result == expected
