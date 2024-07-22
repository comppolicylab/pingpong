from datetime import timedelta, datetime
from typing import cast
import requests

import jwt
from jwt.exceptions import PyJWTError
from sqlalchemy.ext.asyncio import AsyncSession

from .config import config
from .now import NowFn, utcnow
from .schemas import CanvasToken, CanvasClass
from .models import Class


def encode_canvas_token(
    user_id: int, class_id: str, expiry: int = 600, nowfn: NowFn = utcnow
) -> str:
    """Generates the Canvas State Token.

    Args:
        user_id (int): User ID
        expiry (int, optional): Expiry in seconds. Defaults to 600.
        nowfn (NowFn, optional): Function to get the current time. Defaults to utcnow.

    Returns:
        str: Canvas State Token
    """
    if expiry < 1:
        raise ValueError("expiry must be greater than 1 second")

    now = nowfn()
    exp = now + timedelta(seconds=expiry)
    tok = CanvasToken(
        iat=int(now.timestamp()),
        exp=int(exp.timestamp()),
        user_id=str(user_id),
        class_id=class_id,
    )

    secret = config.auth.secret_keys[0]

    # For some reason mypy is wrong and thinks this is a bytes object. It is
    # actually a str in PyJWT:
    # https://github.com/jpadilla/pyjwt/blob/2.8.0/jwt/api_jwt.py#L52
    return cast(
        str,
        jwt.encode(
            tok.model_dump(),
            secret.key,
            algorithm=secret.algorithm,
        ),
    )


def decode_canvas_token(token: str, nowfn: NowFn = utcnow) -> CanvasToken:
    """Decodes the Canvas State Token.

    Args:
        token (str): Canvas State Token
        nowfn (NowFn, optional): Function to get the current time. Defaults to utcnow.

    Returns:
        CanvasToken: Canvas State Token

    Raises:
        jwt.exceptions.PyJWTError when token is not valid
    """
    exc: PyJWTError | None = None

    for secret in config.auth.secret_keys:
        try:
            tok = CanvasToken(
                **jwt.decode(
                    token,
                    secret.key,
                    algorithms=[secret.algorithm],
                    options={
                        "verify_exp": False,
                        "verify_nbf": False,
                    },
                )
            )

            # Custom timestamp verification according to the nowfn
            now = nowfn().timestamp()
            nbf = getattr(tok, "nbf", None)
            if nbf is not None and now < nbf:
                raise PyJWTError("Token not valid yet")

            exp = getattr(tok, "exp", None)
            if exp is not None and now > exp:
                raise PyJWTError("Token expired")

            return tok

        except PyJWTError as e:
            exc = e
            continue

    if exc is not None:
        raise exc

    # Unclear why we would get here
    raise ValueError("invalid token")


def generate_canvas_link(
    user_id: int, course_id: str, expiry: int = 600, nowfn: NowFn = utcnow
) -> str:
    """Generates the redirect link to authenticate with Canvas.

    Args:
        user_id (int): User ID
        redirect (str, optional): Redirect URL. Defaults to "/".

    Returns:
        str: Auth Link
    """
    tok = encode_canvas_token(user_id, course_id, expiry=expiry, nowfn=nowfn)
    return canvas_auth_link(tok)


def canvas_auth_link(token: str) -> str:
    return config.canvas_link(
        f"/login/oauth2/auth?client_id={config.canvas_client_id}&response_type=code&redirect_uri={config.url('/api/v1/auth/canvas')}&state={token}"
    )


def canvas_request_access_token(
    code: str, nowfn: NowFn = utcnow
) -> tuple[str, str, float]:
    params = {
        "client_id": config.canvas_client_id,
        "client_secret": config.canvas_client_secret,
        "response_type": "code",
        "code": code,
        "redirect_uri": config.url("/api/v1/auth/canvas"),
    }
    result = requests.post(config.canvas_link("/login/oauth2/token"), data=params)
    result.raise_for_status()
    response = result.json()
    now = nowfn()
    exp = now + timedelta(seconds=int(response["expires_in"]) - 60)
    return (response["access_token"], response["refresh_token"], exp.timestamp())


def get_courses(access_token: str) -> list[CanvasClass]:
    result = requests.get(
        config.canvas_link("/api/v1/courses"),
        headers={"Authorization": f"Bearer {access_token}"},
    )
    result.raise_for_status()
    return [CanvasClass.model_validate(course) for course in result.json()]


async def refresh_access_token(
    session: AsyncSession, class_id: int, refresh_token: str
) -> str:
    params = {
        "client_id": config.canvas_client_id,
        "client_secret": config.canvas_client_secret,
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
    }
    result = requests.post(config.canvas_link("/login/oauth2/token"), data=params)
    result.raise_for_status()
    response = result.json()
    now = utcnow()
    exp = now + timedelta(seconds=int(response["expires_in"]) - 60)

    await Class.update_canvas_token(
        session,
        class_id,
        response["access_token"],
        refresh_token,
        datetime.fromtimestamp(exp.timestamp()),
    )
    return response["access_token"]
