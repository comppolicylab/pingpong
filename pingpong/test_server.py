from datetime import datetime

import pytest

from .auth import encode_session_token
from .now import offset


async def test_me_without_token(api):
    response = api.get("/api/v1/me")
    assert response.status_code == 200
    assert response.json() == {
        "error": None,
        "profile": None,
        "status": "missing",
        "token": None,
        "user": None,
    }


async def test_me_with_expired_token(api, now):
    response = api.get(
        "/api/v1/me",
        cookies={
            "session": encode_session_token(123, nowfn=offset(now, seconds=-100_000)),
        },
    )
    assert response.status_code == 200
    assert response.json() == {
        "error": "Token expired",
        "profile": None,
        "status": "invalid",
        "token": None,
        "user": None,
    }


async def test_me_with_invalid_token(api):
    response = api.get(
        "/api/v1/me",
        cookies={
            # Token with invalid signature
            "session": (
                "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
                "eyJzdWIiOiIxMjMiLCJleHAiOjE3MDk0NDg1MzQsImlhdCI6MTcwOTQ0ODUzM30."
                "pRnnClaC1a6yIBFKMdA32pqoaJOcpHyY4lq_NU28gQ"
            ),
        },
    )
    assert response.status_code == 200
    assert response.json() == {
        "error": "Signature verification failed",
        "profile": None,
        "status": "invalid",
        "token": None,
        "user": None,
    }


async def test_me_with_valid_token_but_missing_user(api, now):
    response = api.get(
        "/api/v1/me",
        cookies={
            "session": encode_session_token(123, nowfn=offset(now, seconds=-5)),
        },
    )
    assert response.status_code == 200
    assert response.json() == {
        "error": "User does not exist",
        "profile": None,
        "status": "error",
        "token": None,
        "user": None,
    }


def with_user(id: int, email: str | None = None, created: datetime | None = None):
    return pytest.mark.parametrize(
        "user",
        [
            {
                "id": id,
                "email": email or f"user_{id}@domain.test",
                "created": created or datetime(2024, 1, 1, 0, 0, 0),
            }
        ],
        indirect=True,
    )


def with_authz(grants=None):
    return pytest.mark.parametrize(
        "authz",
        [
            {
                "grants": grants or [],
            }
        ],
        indirect=True,
    )


@with_user(123)
async def test_me_with_valid_user(api, user, now, valid_user_token):
    response = api.get(
        "/api/v1/me",
        cookies={
            "session": valid_user_token,
        },
    )
    assert response.status_code == 200
    assert response.json() == {
        "error": None,
        "profile": {
            "email": "user_123@domain.test",
            "gravatar_id": "45d4d5ec84ab81529df672c3abf0def25df67c0c64859aea0559bc867ea64b19",
            "image_url": (
                "https://www.gravatar.com/avatar/"
                "45d4d5ec84ab81529df672c3abf0def25df67c0c64859aea0559bc867ea64b19"
            ),
        },
        "status": "valid",
        "token": {"exp": 1704182340, "iat": 1704095940, "sub": "123"},
        "user": {
            "created": "2024-01-01T00:00:00",
            "email": "user_123@domain.test",
            "id": 123,
            "name": None,
            "state": "verified",
            "updated": None,
        },
    }


@with_user(123)
@with_authz(
    grants=[],
)
async def test_config_no_permissions(api, valid_user_token):
    response = api.get(
        "/api/v1/config",
        cookies={
            "session": valid_user_token,
        },
    )
    assert response.status_code == 403
    assert response.json() == {"detail": "Missing required role"}


@with_user(123)
@with_authz(
    grants=[
        ("user:123", "admin", "root:0"),
    ],
)
async def test_config_correct_permissions(api, valid_user_token):
    response = api.get(
        "/api/v1/config",
        cookies={
            "session": valid_user_token,
        },
    )
    assert response.status_code == 200
