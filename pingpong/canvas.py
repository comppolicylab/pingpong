from datetime import timedelta
import json
from logging import Logger
from typing import List
import aiohttp

from fastapi import HTTPException, BackgroundTasks, Request
from jwt.exceptions import PyJWTError
from sqlalchemy.ext.asyncio import AsyncSession

from pingpong.auth import decode_auth_token, encode_auth_token
from pingpong.authz.openfga import OpenFgaAuthzClient

from .config import config
from .models import Class, CanvasClass
from .now import NowFn, utcnow
from .retry import with_retry
from .schemas import (
    CanvasToken,
    CanvasClass as CanvasClassSchema,
    ClassUserRoles,
    CreateUserClassRole,
    CreateUserClassRoles,
)
from .users import add_new_users


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
    return encode_auth_token(
        user_id,
        expiry,
        nowfn=nowfn,
        sub=json.dumps({"class_id": class_id, "user_id": user_id}),
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
    try:
        auth_token = decode_auth_token(token, nowfn=nowfn)
        sub_data = json.loads(auth_token.sub)
        return CanvasToken(
            user_id=str(sub_data["user_id"]),
            class_id=str(sub_data["class_id"]),
            iat=auth_token.iat,
            exp=auth_token.exp,
        )
    except PyJWTError as e:
        raise HTTPException(status_code=400, detail="Invalid Canvas token") from e


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


@with_retry(max_retries=3)
async def get_courses(
    session: AsyncSession, class_id: int, retry_attempt: int = 0
) -> list[CanvasClassSchema]:
    # Get the access token and force refresh if this is a retry attempt
    access_token = await get_access_token(
        session, str(class_id), force_refresh=retry_attempt > 0
    )
    headers = {"Authorization": f"Bearer {access_token}"}
    params = {"include[]": ["term"]}
    courses = []

    async with aiohttp.ClientSession() as session_:
        next_url = config.canvas_link("/api/v1/courses")

        while next_url:
            async with session_.get(
                next_url,
                params=params,
                headers=headers,
                raise_for_status=True,
            ) as resp:
                data = await resp.json()
                courses.extend(
                    [
                        {
                            "canvas_id": course["id"],
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
    force_refresh: bool = False,
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

    if (
        not now < canvas_token_added_at + timedelta(seconds=canvas_expires_in - buffer)
        or force_refresh
    ):
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
            canvas_class = {
                "canvas_id": data["id"],
                "name": data["name"],
                "course_code": data["course_code"],
                "term": data["term"]["name"],
            }
    canvas_class = await CanvasClass.create_or_update(session, canvas_class)

    await Class.update_canvas_class(session, db_class_id, canvas_class.id)


@with_retry(max_retries=3)
async def sync_roster(
    session: AsyncSession,
    user_id: int,
    class_id: int,
    request: Request,
    tasks: BackgroundTasks,
    retry_attempt: int = 0,
    cron: bool = False,
    client: OpenFgaAuthzClient | None = None,
    time_between_syncs: int = 10,
) -> None:
    access_token = await get_access_token(
        session,
        str(class_id),
        check_user=True,
        user_id=user_id,
        force_refresh=retry_attempt > 0,
    )
    class_, now = await Class.get_canvas_course_id(session, class_id)

    if not class_:
        raise HTTPException(status_code=400, detail="No linked Canvas course found")

    if (
        class_.canvas_last_synced
        and class_.canvas_last_synced > now - timedelta(minutes=10)
        and not cron
    ):
        # Calculate the remaining time until the next allowed sync
        time_remaining = (
            class_.canvas_last_synced + timedelta(minutes=time_between_syncs) - now
        ).total_seconds() + 1
        time_remaining_string = (
            f"{int(time_remaining // 60)} minute{'s'[:(int(time_remaining)// 60)^1]}"
            if int(time_remaining // 60) > 0
            else f"{int(time_remaining)} second{'s'[:(int(time_remaining)^1)]}"
        )
        raise HTTPException(
            status_code=429,
            detail=f"A Canvas sync was recently completed. Please wait before trying again. You can request a manual sync in {time_remaining_string}.",
        )
    user_roles: List[CreateUserClassRole] = []
    headers = {"Authorization": f"Bearer {access_token}"}
    params = {"include[]": ["enrollments"]}
    async with aiohttp.ClientSession() as session_:
        next_url = config.canvas_link(
            f"/api/v1/courses/{class_.canvas_class.canvas_id}/users"
        )
        while next_url:
            async with session_.get(
                next_url,
                headers=headers,
                params=params,
                raise_for_status=True,
            ) as resp:
                data = await resp.json()
                for user in data:
                    is_teacher = False
                    for enrollment in user["enrollments"]:
                        if enrollment["type"] in ["TeacherEnrollment", "TaEnrollment"]:
                            is_teacher = True
                        break
                    user_roles.append(
                        CreateUserClassRole(
                            email=user["email"],
                            roles=ClassUserRoles(
                                admin=False,
                                teacher=is_teacher,
                                student=not is_teacher,
                            ),
                        )
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
    new_ucr = CreateUserClassRoles(roles=user_roles, silent=False, from_canvas=True)

    if not cron:
        await add_new_users(
            class_id=str(class_id),
            new_ucr=new_ucr,
            request=request,
            tasks=tasks,
            ignore_self=True,
        )
    else:
        await add_new_users(
            class_id=str(class_id),
            user_id=user_id,
            session=session,
            client=client,
            new_ucr=new_ucr,
            ignore_self=True,
            cron=True,
        )

    await Class.update_last_synced(session, class_id)


async def sync_all(
    session: AsyncSession, client: OpenFgaAuthzClient, logger: Logger
) -> None:
    async for class_ in Class.get_all_to_sync(session):
        try:
            logger.info(f"Syncing class {class_.id}")
            await sync_roster(
                session,
                class_.canvas_user_id,
                class_.id,
                None,
                None,
                cron=True,
                client=client,
            )
            await session.commit()
        except Exception as e:
            logger.error(f"Failed to sync class {class_.id}: {e}")
