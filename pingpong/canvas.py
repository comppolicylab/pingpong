from datetime import timedelta
from typing import cast
import aiohttp

import jwt
from jwt.exceptions import PyJWTError

from .config import config
from .now import NowFn, utcnow
from .schemas import CanvasToken, CanvasClass


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


async def canvas_token_request(params=dict[str, str]) -> tuple[str, str, int]:
    async with aiohttp.ClientSession() as session:
        async with session.post(
            config.canvas_link("/login/oauth2/token"),
            data=params,
            raise_for_status=True,
        ) as resp:
            if resp.status == 200:
                response = await resp.json()
                return (
                    response["access_token"],
                    response.get("refresh_token", ""),
                    int(response["expires_in"]),
                )
            else:
                raise ValueError("Invalid response from Canvas")


async def get_access_token(code: str) -> tuple[str, str, int]:
    params = {
        "client_id": config.canvas_client_id,
        "client_secret": config.canvas_client_secret,
        "response_type": "code",
        "code": code,
        "redirect_uri": config.url("/api/v1/auth/canvas"),
    }
    return await canvas_token_request(params)


async def refresh_access_token(refresh_token: str) -> tuple[str, str, int]:
    params = {
        "client_id": config.canvas_client_id,
        "client_secret": config.canvas_client_secret,
        "grant_type": "refresh_token",
        "refresh_token": refresh_token,
    }
    return await canvas_token_request(params)


async def get_courses(access_token: str) -> list[CanvasClass]:
    headers = {"Authorization": f"Bearer {access_token}"}
    params = {"include[]": "term"}
    async with aiohttp.ClientSession() as session:
        async with session.get(
            config.canvas_link("/api/v1/courses"),
            data=params,
            headers=headers,
            raise_for_status=True,
        ) as resp:
            courses = [
                {
                    "id": course["id"],
                    "name": course["name"],
                    "course_code": course["course_code"],
                    "term": course["term"]["name"],
                }
                for course in await resp.json()
            ]

            return [CanvasClass.model_validate(course) for course in courses]
