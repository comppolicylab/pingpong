from datetime import datetime, timedelta

import pytest

from .auth import encode_session_token
from .now import NowFn


def offset(now: NowFn, seconds: int = 0) -> NowFn:
    return lambda: now() + timedelta(seconds=seconds)


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


@pytest.mark.parametrize(
    "user",
    [
        {
            "id": 123,
            "email": "me@org.test",
            "created": datetime(2024, 3, 3, 7, 3, 53),
        }
    ],
    indirect=True,
)
async def test_me_with_valid_user(api, user, now):
    response = api.get(
        "/api/v1/me",
        cookies={
            "session": encode_session_token(123, nowfn=offset(now, seconds=-5)),
        },
    )
    print("\n\n\n\n\nSTATE\n\n\n\n\n", api.app.state.__dict__, "\n\n\n\n")
    assert response.status_code == 200
    assert response.json() == {
        "error": None,
        "profile": {
            "email": "me@org.test",
            "gravatar_id": "ef02b9c38dce132e881a81b17f8a16971754189e8294768b2d519e2c62f0f5ec",
            "image_url": (
                "https://www.gravatar.com/avatar/"
                "ef02b9c38dce132e881a81b17f8a16971754189e8294768b2d519e2c62f0f5ec"
            ),
        },
        "status": "valid",
        "token": {"exp": 1704182395, "iat": 1704095995, "sub": "123"},
        "user": {
            "created": "2024-03-03T07:03:53",
            "email": "me@org.test",
            "id": 123,
            "name": None,
            "state": "verified",
            "updated": None,
        },
    }
