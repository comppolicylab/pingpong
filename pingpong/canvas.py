from datetime import timedelta
from typing import cast
import aiohttp

from fastapi import HTTPException
import jwt
from jwt.exceptions import PyJWTError
from sqlalchemy.ext.asyncio import AsyncSession

from .config import config
from .models import Class, CanvasClass
from .now import NowFn, utcnow
from .schemas import CanvasToken
from .schemas import CanvasClass as CanvasClassSchema


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


async def get_initial_access_token(code: str) -> tuple[str, str, int]:
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


async def get_courses(access_token: str) -> list[CanvasClassSchema]:
    headers = {"Authorization": f"Bearer {access_token}"}
    params = {"include[]": ["term"]}
    courses = []
    async with aiohttp.ClientSession() as session:
        next_url = config.canvas_link("/api/v1/courses")

        while next_url:
            async with session.get(
                next_url,
                params=params,
                headers=headers,
                raise_for_status=True,
            ) as resp:
                data = await resp.json()
                courses.extend(
                    [
                        {
                            "id": course["id"],
                            "name": course["name"],
                            "course_code": course["course_code"],
                            "term": course["term"]["name"],
                        }
                        for course in data
                    ]
                )

                # Check for the next page link
                next_url = ""
                link_header = resp.headers.get("Link")
                if link_header:
                    links = link_header.split(",")
                    for link in links:
                        if 'rel="next"' in link:
                            next_url = link[link.find("<") + 1 : link.find(">")]
                            break

    return [CanvasClassSchema.model_validate(course) for course in courses]


async def get_access_token(
    session: AsyncSession,
    class_id: str,
    buffer: int = 60,
    check_user: bool = False,
    user_id: int = 0,
) -> str:
    (
        canvas_user_id,  # user_id
        canvas_access_token,
        canvas_refresh_token,
        canvas_expires_in,
        canvas_token_added_at,
        now,
    ) = await Class.get_canvas_token(session, int(class_id))
    if not now:
        raise HTTPException(status_code=400, detail="Could not locate PingPong group")
    if not canvas_access_token:
        raise HTTPException(status_code=400, detail="No Canvas access token for class")
    if check_user and canvas_user_id != user_id:
        raise HTTPException(
            status_code=403,
            detail="You're not the authorized Canvas user for this class",
        )

    tok = canvas_access_token

    if not now < canvas_token_added_at + timedelta(seconds=canvas_expires_in - buffer):
        tok, _, expires_in = await refresh_access_token(canvas_refresh_token)
        await Class.update_canvas_token(
            session, int(class_id), tok, expires_in, refresh=True
        )
    return tok


async def check_course_enrollment(access_token: str, course_id: str) -> None:
    headers = {"Authorization": f"Bearer {access_token}"}
    params = {
        "type[]": [
            "TeacherEnrollment",
            "TaEnrollment",
        ]
    }
    async with aiohttp.ClientSession() as session:
        verified_enrollment = False
        next_url = config.canvas_link("/api/v1/users/self/enrollments")
        while next_url:
            async with session.get(
                next_url,
                headers=headers,
                params=params,
                raise_for_status=True,
            ) as resp:
                data = await resp.json()
                for enrollment in data:
                    if enrollment["course_id"] == int(course_id):
                        verified_enrollment = True
                        break

                # Check for the next page link
                next_url = ""
                link_header = resp.headers.get("Link")
                if link_header:
                    links = link_header.split(",")
                    for link in links:
                        if 'rel="next"' in link:
                            next_url = link[link.find("<") + 1 : link.find(">")]
                            break

        if not verified_enrollment:
            raise HTTPException(
                status_code=403,
                detail="You are not an authorized teacher in the Canvas class you are trying to access.",
            )

        if not await course_enrollment_access_check(access_token, course_id):
            raise HTTPException(
                status_code=403,
                detail="You are not authorized to access the enrollment list for this Canvas class.",
            )


async def course_enrollment_access_check(access_token: str, course_id: str) -> bool:
    headers = {"Authorization": f"Bearer {access_token}"}
    async with aiohttp.ClientSession() as session:
        async with session.get(
            config.canvas_link(f"/api/v1/courses/{course_id}/enrollments"),
            headers=headers,
            raise_for_status=True,
        ) as resp:
            return resp.status == 200


async def set_canvas_class(
    session: AsyncSession, access_token: str, db_class_id: int, canvas_course_id: int
) -> None:
    headers = {"Authorization": f"Bearer {access_token}"}
    params = {"include[]": ["term"]}
    async with aiohttp.ClientSession() as session_:
        async with session_.get(
            config.canvas_link(f"/api/v1/courses/{canvas_course_id}"),
            headers=headers,
            params=params,
            raise_for_status=True,
        ) as resp:
            data = await resp.json()
            print(data)
            canvas_class = {
                "canvas_id": data["id"],
                "name": data["name"],
                "course_code": data["course_code"],
                "term": data["term"]["name"],
            }
    canvas_class = await CanvasClass.create_or_update(session, canvas_class)

    await Class.update_canvas_class(session, db_class_id, canvas_class.id)
