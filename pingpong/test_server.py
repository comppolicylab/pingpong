from unittest.mock import AsyncMock

from .auth import encode_session_token
from .now import offset
from .testutil import with_authz, with_authz_series, with_user


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
        "token": {"exp": 1704153540, "iat": 1704067140, "sub": "123"},
        "user": {
            "created": "2024-01-01T00:00:00",
            "email": "user_123@domain.test",
            "id": 123,
            "name": "user_123@domain.test",
            "first_name": None,
            "last_name": None,
            "display_name": None,
            "state": "verified",
            "updated": None,
        },
    }


@with_user(123)
@with_authz_series(
    [
        {"grants": []},
        {"grants": [("user:123", "admin", "institution:1")]},
        {"grants": [("user:123", "can_create_institution", "root:0")]},
        {"grants": [("user:123", "can_create_class", "institution:1")]},
        {"grants": [("user:122", "admin", "root:0")]},
    ]
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


async def test_auth_with_invalid_token(api):
    invalid_token = (
        "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
        "eyJzdWIiOiIxMjMiLCJleHAiOjE3MDk0NDg1MzQsImlhdCI6MTcwOTQ0ODUzM30."
        "pRnnClaC1a6yIBFKMdA32pqoaJOcpHyY4lq_NU28gQ"
    )
    response = api.get(f"/api/v1/auth?token={invalid_token}")
    assert response.status_code == 401
    assert response.json() == {"detail": "Signature verification failed"}


async def test_auth_with_expired_token(api, now):
    expired_token = encode_session_token(123, nowfn=offset(now, seconds=-100_000))
    response = api.get(f"/api/v1/auth?token={expired_token}")
    assert response.status_code == 401
    assert response.json() == {"detail": "Token expired"}


async def test_auth_valid_token(api, now):
    valid_token = encode_session_token(123, nowfn=offset(now, seconds=-5))
    response = api.get(f"/api/v1/auth?token={valid_token}", allow_redirects=False)
    assert response.status_code == 303
    # Check where redirect goes
    assert response.headers["location"] == "http://localhost:5173/"


async def test_auth_valid_token_with_redirect(api, now):
    valid_token = encode_session_token(123, nowfn=offset(now, seconds=-5))
    response = api.get(
        f"/api/v1/auth?token={valid_token}&redirect=/foo/bar", allow_redirects=False
    )
    assert response.status_code == 303
    # Check where redirect goes
    assert response.headers["location"] == "http://localhost:5173/foo/bar"


async def test_magic_link_login_no_user(api, config, monkeypatch):
    # Patch the email driver in config.email
    send_mock = AsyncMock()
    monkeypatch.setattr(config.email.sender, "send", send_mock)
    response = api.post(
        "/api/v1/login/magic",
        json={"email": "me@org.test"},
    )
    assert response.status_code == 401
    assert response.json() == {"detail": "User does not exist"}
    # Send should not have been called
    send_mock.assert_not_called()


@with_user(123)
async def test_magic_link_login(api, config, monkeypatch):
    # Patch the email driver in config.email
    send_mock = AsyncMock()
    monkeypatch.setattr(config.email.sender, "send", send_mock)
    response = api.post(
        "/api/v1/login/magic",
        json={"email": "user_123@domain.test"},
    )
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    send_mock.assert_called_once_with(
        "user_123@domain.test",
        "Your PingPong login link!",
        (
            "Click this link to log in to PingPong: "
            "http://localhost:5173/api/v1/auth?"
            "token=eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9."
            "eyJzdWIiOiIxMjMiLCJleHAiOjE3MDQxNTM2MDAsImlhdCI6MTcwNDA2NzIwMH0."
            "Z6PEytos_I5QVHJp0kIzmoTjI_PyZIT5P8YVwo2SVCU"
            "&redirect=/"
        ),
    )
