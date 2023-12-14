from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from enum import StrEnum, auto
from typing import Optional, cast

import jwt
from jwt.exceptions import PyJWTError

from .config import config
from .db import User
from .gravatar import Profile


@dataclass
class AuthToken:
    """Auth Token - minimal token used to log in."""

    sub: str
    exp: int
    iat: int


@dataclass
class SessionToken:
    """Session Token - stores information about user for a session."""

    sub: str
    exp: int
    iat: int


class SessionStatus(StrEnum):
    VALID = auto()
    MISSING = auto()
    INVALID = auto()
    ERROR = auto()


@dataclass
class SessionState:
    status: SessionStatus
    error: Optional[Exception] = None
    token: Optional[SessionToken] = None
    user: Optional[User] = None
    profile: Optional[Profile] = None


def encode_session_token(user_id: int, expiry: int = 86_400) -> str:
    """Encodes the session token as a JWT.

    Args:
        user_id (int): User ID
        expiry (int, optional): Expiry in seconds. Defaults to 86400 (1 day).

    Returns:
        str: Encoded session token JWT
    """
    return encode_auth_token(user_id, expiry)


def decode_session_token(token: str) -> SessionToken:
    """Decodes the Session Token.

    Args:
        token (str): Encoded session token JWT

    Returns:
        SessionToken: Session Token
    """
    auth_token = decode_auth_token(token)
    return SessionToken(**asdict(auth_token))


def encode_auth_token(user_id: int, expiry: int = 600) -> str:
    """Generates the Auth Token.

    Args:
        user_id (int): User ID
        expiry (int, optional): Expiry in seconds. Defaults to 600.

    Returns:
        str: Auth Token
    """
    if expiry < 1:
        raise ValueError("expiry must be greater than 1 second")

    now = datetime.utcnow().replace(tzinfo=timezone.utc)
    exp = now + timedelta(seconds=expiry)
    tok = AuthToken(
        iat=int(now.timestamp()),
        exp=int(exp.timestamp()),
        sub=str(user_id),
    )

    secret = config.auth.secret_keys[0]

    # For some reason mypy is wrong and thinks this is a bytes object. It is
    # actually a str in PyJWT:
    # https://github.com/jpadilla/pyjwt/blob/2.8.0/jwt/api_jwt.py#L52
    return cast(
        str,
        jwt.encode(
            asdict(tok),
            secret.key,
            algorithm=secret.algorithm,
        ),
    )


def decode_auth_token(token: str) -> AuthToken:
    """Decodes the Auth Token.

    Args:
        token (str): Auth Token

    Returns:
        AuthToken: Auth Token

    Raises:
        jwt.exceptions.PyJWTError when token is not valid
    """
    exc: PyJWTError | None = None

    for secret in config.auth.secret_keys:
        try:
            return AuthToken(
                **jwt.decode(token, secret.key, algorithms=[secret.algorithm])
            )
        except PyJWTError as e:
            exc = e
            continue

    if exc is not None:
        raise exc

    # Unclear why we would get here
    raise ValueError("invalid token")


def generate_auth_link(user_id: int, redirect: str = "/") -> str:
    """Generates the link to log in.

    Args:
        user_id (int): User ID
        redirect (str, optional): Redirect URL. Defaults to "/".

    Returns:
        str: Auth Link
    """
    tok = encode_auth_token(user_id)
    return config.url(f"/api/v1/auth?token={tok}&redirect={redirect}")
