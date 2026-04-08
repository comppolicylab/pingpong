import hashlib
import hmac

from pingpong.ai import get_response_safety_identifier


TEST_SECRET = "test-response-safety-identifier-secret"


def _expected(raw_identifier: str, *, secret: str = TEST_SECRET) -> str:
    return hmac.new(
        secret.encode("utf-8"),
        f"pp:v1:{raw_identifier}".encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def test_response_safety_identifier_uses_user_auth_for_logged_in_user():
    assert get_response_safety_identifier(
        user_auth="user:42",
        response_safety_identifier_secret=TEST_SECRET,
    ) == _expected("user:42")


def test_response_safety_identifier_prefers_user_auth_over_anonymous_session_id():
    assert get_response_safety_identifier(
        user_auth="user:42",
        anonymous_session_id=77,
        response_safety_identifier_secret=TEST_SECRET,
    ) == _expected("user:42")


def test_response_safety_identifier_uses_anonymous_link_id_as_fallback():
    assert get_response_safety_identifier(
        user_auth=None,
        anonymous_link_id=9,
        response_safety_identifier_secret=TEST_SECRET,
    ) == _expected("anonymous_link:9")


def test_response_safety_identifier_prefers_user_auth_over_anonymous_link():
    assert get_response_safety_identifier(
        user_auth="user:5",
        anonymous_link_id=9,
        response_safety_identifier_secret=TEST_SECRET,
    ) == _expected("user:5")


def test_response_safety_identifier_returns_none_when_no_identifiers_present():
    assert (
        get_response_safety_identifier(
            user_auth=None,
            response_safety_identifier_secret=TEST_SECRET,
        )
        is None
    )


def test_response_safety_identifier_returns_none_when_secret_not_configured():
    assert (
        get_response_safety_identifier(
            user_auth="user:42",
            response_safety_identifier_secret="",
        )
        is None
    )
