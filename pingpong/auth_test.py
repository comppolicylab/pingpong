from datetime import datetime, timezone

from .auth import encode_auth_token


def now_for_test():
    """Return a fixed datetime for testing."""
    return datetime(2023, 2, 3, 4, 5, 6, tzinfo=timezone.utc)


def test_encode_auth_token(self):
    assert encode_auth_token(1, now_for_test()) == (
        b"eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9."
        b"eyJpYXQiOjE2MzIwMzIwMDYsImV4cCI6MTYzMjAzMjAwNywibmJmIjoxNjMyMDMyMDA2LCJpZCI6MX0.7"
    )
