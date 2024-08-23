from abc import ABC, abstractmethod
from datetime import datetime, timedelta
import json
import logging
from typing import Callable, Literal, TypeVar, Union
import aiohttp

from fastapi import HTTPException, BackgroundTasks, Request
from fastapi.responses import RedirectResponse
from jwt.exceptions import PyJWTError
from sqlalchemy.ext.asyncio import AsyncSession

from pingpong.auth import decode_auth_token, encode_auth_token
from pingpong.authz.openfga import OpenFgaAuthzClient
from pingpong.time import convert_seconds

from .config import CanvasSettings, config
from .models import Class, LMSClass as CanvasClass
from .now import NowFn, utcnow
from .retry import with_retry
from .schemas import (
    CanvasAccessToken,
    CanvasInitialAccessTokenRequest,
    CanvasRefreshAccessTokenRequest,
    CanvasRequestResponse,
    CanvasToken,
    LMSClass as CanvasClassSchema,
    ClassUserRoles,
    CreateUserClassRole,
    CreateUserClassRoles,
    LMSClassRequest,
    LMSType,
)
from .users import AddNewUsersScript, AddNewUsersManual


def decode_canvas_token(token: str, nowfn: NowFn) -> CanvasToken:
    """Decodes the Canvas State Token.

    Args:
        token (str): Canvas State Token

    Returns:
        CanvasToken: Canvas State Token

    Raises:
        `jwt.exceptions.PyJWTError` when token is not valid
    """
    try:
        auth_token = decode_auth_token(token, nowfn=nowfn)
        sub_data = json.loads(auth_token.sub)
        return CanvasToken(
            user_id=str(sub_data["user_id"]),
            class_id=str(sub_data["class_id"]),
            lms_tenant=str(sub_data["lms_tenant"]),
            iat=auth_token.iat,
            exp=auth_token.exp,
        )
    except PyJWTError as e:
        raise HTTPException(status_code=400, detail="Invalid Canvas token") from e


def get_canvas_config(tenant: str) -> CanvasSettings:
    """Get the Canvas configuration for the given tenant.

    Args:
        tenant (str): Tenant name

    Returns:
        CanvasSettings: Canvas configuration
    """
    for lms in config.lms.lms_instances:
        if lms.type == "canvas" and lms.tenant == tenant:
            return lms
    raise HTTPException(status_code=400, detail="No Canvas configuration found")


T = TypeVar("T")
logger = logging.getLogger(__name__)


class BreakLoopException(Exception):
    def __init__(self, value):
        self.value = value


class CanvasCourseClient(ABC):
    def __init__(
        self,
        canvas_backend_config: CanvasSettings,
        db: AsyncSession,
        class_id: int,
        user_id: int,
        min_between_syncs: int = 10,
        nowfn: NowFn = utcnow,
    ):
        self.config = canvas_backend_config
        self.db = db
        self.class_id = class_id
        self.user_id = user_id
        self.min_between_syncs = min_between_syncs
        self.nowfn = nowfn

    async def __aenter__(self):
        self.http_session = aiohttp.ClientSession()
        return self

    async def __aexit__(self, exc_type, exc, tb):
        await self.http_session.close()

    def _encode_token(self) -> str:
        """Generates the Canvas State Token.

        Returns:
            str: Canvas State Token
        """
        if not self.user_id:
            raise HTTPException(status_code=400, detail="No user ID provided")

        if not self.class_id:
            raise HTTPException(status_code=400, detail="No class ID provided")

        return encode_auth_token(
            sub=json.dumps(
                {
                    "class_id": self.class_id,
                    "user_id": self.user_id,
                    "lms_tenant": self.config.tenant,
                }
            ),
            expiry=self.config.auth_token_expiry,
            nowfn=self.nowfn,
        )

    def get_oauth_link(self) -> str:
        """Generates the redirect link to authenticate with Canvas.

        Returns:
            str: Redirect URL.
        """
        token = self._encode_token()
        return self.config.url(
            f"/login/oauth2/auth?client_id={self.config.client_id}&scopes=&response_type=code&redirect_uri={config.url('/api/v1/auth/canvas')}&state={token}"
        )

    async def _get_access_token(
        self,
        buffer: int = 60,
        force_refresh: bool = False,
    ) -> str:
        """Get the Canvas access token for the class.

        Args:
            buffer (int, optional): Buffer time in seconds. Defaults to 60.
            force_refresh (bool, optional): Refresh the token even if it's still valid. Defaults to False.
        """
        response = await Class.get_lms_token(self.db, int(self.class_id))

        # If no Canvas class is found, the tuple will be None, so we can detect that here
        if not response.now:
            raise HTTPException(
                status_code=400, detail="Could not locate PingPong group"
            )

        # No Canvas access token is found for this class
        if not response.access_token:
            raise HTTPException(
                status_code=400, detail="No Canvas access token for class"
            )

        # Check if the user making the request is the user whose Canvas account is connected for the class
        if response.user_id != self.user_id:
            raise HTTPException(
                status_code=403,
                detail="You're not the authorized Canvas user for this class",
            )

        # Set the access token to use for the request as the current access token
        tok = response.access_token

        # Refresh the token if it's expired or about to expire
        if force_refresh or response.now > response.token_added_at + timedelta(
            seconds=response.expires_in - buffer
        ):
            access_token = await self._refresh_access_token(response.refresh_token)
            await Class.update_lms_token(
                self.db,
                int(self.class_id),
                access_token.access_token,
                access_token.expires_in,
                refresh=True,
            )
            tok = access_token.access_token
        return tok

    async def _request_access_token(
        self, params: CanvasInitialAccessTokenRequest | CanvasRefreshAccessTokenRequest
    ) -> CanvasAccessToken:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                self.config.url("/login/oauth2/token"),
                data=params.__dict__,
                raise_for_status=True,
            ) as resp:
                response = await resp.json()
                return CanvasAccessToken(
                    access_token=response["access_token"],
                    refresh_token=response.get("refresh_token", ""),
                    expires_in=int(response["expires_in"]),
                )

    async def create_response(
        self, resp: aiohttp.ClientResponse
    ) -> CanvasRequestResponse:
        """Create a CanvasRequestResponse object from a response dictionary."""
        # Check for the next page link in case of paginated responses
        next_page = ""
        link_header = resp.headers.get("Link")
        if link_header:
            links = link_header.split(",")
            for link in links:
                if 'rel="next"' in link:
                    next_page = link[link.find("<") + 1 : link.find(">")]
                    break

        return CanvasRequestResponse(
            response=await resp.json(),
            next_page=next_page,
        )

    @with_retry(max_retries=3)
    async def _make_authed_request_post(
        self,
        path: str,
        body: dict | None = None,
        params: dict | None = None,
        retry_attempt: int = 0,
    ) -> CanvasRequestResponse:
        # Get the access token. Force refresh the token if this is a retry attempt
        access_token = await self._get_access_token(force_refresh=retry_attempt > 0)
        headers = {"Authorization": f"Bearer {access_token}"}

        async with self.http_session.post(
            path,
            params=params,
            headers=headers,
            json=body,
            raise_for_status=True,
        ) as resp:
            return await self.create_response(resp)

    @with_retry(max_retries=3)
    async def _make_authed_request_get(
        self,
        path: str,
        body: dict | None = None,
        params: dict | None = None,
        retry_attempt: int = 0,
    ) -> CanvasRequestResponse:
        # Get the access token. Force refresh the token if this is a retry attempt
        access_token = await self._get_access_token(force_refresh=retry_attempt > 0)
        headers = {"Authorization": f"Bearer {access_token}"}

        async with self.http_session.get(
            path,
            params=params,
            headers=headers,
            json=body,
            raise_for_status=True,
        ) as resp:
            return await self.create_response(resp)

    async def _paginated_request(
        self,
        path: str,
        f: Callable[[list[dict]], list[T]],
        body: dict | None = None,
        params: dict | None = None,
        method: Union[Literal["GET"], Literal["POST"]] = "GET",
    ) -> list[T]:
        """Paginate through a request response. Returns the parsed response of all pages.

        Args:
            path (str): The path to the API endpoint.
            f (Callable[[list[dict]], list[any]]): The function to parse the JSON response.
            body (dict, optional): The body of the request. Defaults to None.
            params (dict, optional): The parameters of the request. Defaults to None.

        Returns:
            list[any]: The parsed response of all pages.
        """
        results = []

        next_page = self.config.url(path)

        while next_page:
            if method == "GET":
                response = await self._make_authed_request_get(next_page, body, params)
            else:
                response = await self._make_authed_request_post(next_page, body, params)
            result = f(response.response)
            results.extend(result)
            next_page = response.next_page

        return results

    async def _paginated_request_single(
        self,
        path: str,
        f: Callable[[list[dict], Union[T, None]], Union[T, None]],
        body: dict | None = None,
        params: dict | None = None,
        method: Union[Literal["GET"], Literal["POST"]] = "GET",
    ) -> Union[T, None]:
        """Paginate through a request response. Returns a single object or None.
        For example, can be used for returning a boolean value.

        Args:
            path (str): The path to the API endpoint.
            f (Callable[[list[dict], Union[T, None]], T]): The function to parse the JSON response.
            body (dict, optional): The body of the request. Defaults to None.
            params (dict, optional): The parameters of the request. Defaults to None.

        Returns:
            Union[T, None]: Result.
        """
        next_page = self.config.url(path)

        result = None

        while next_page:
            try:
                if method == "GET":
                    response = await self._make_authed_request_get(
                        next_page, body, params
                    )
                else:
                    response = await self._make_authed_request_post(
                        next_page, body, params
                    )
                result = f(response.response, result)
                next_page = response.next_page
            except BreakLoopException as e:
                return e.value

        return result

    async def _non_paginated_request(
        self,
        path: str,
        f: Callable[[dict], T],
        body: dict | None = None,
        params: dict | None = None,
        method: Union[Literal["GET"], Literal["POST"]] = "GET",
    ) -> T:
        """Make a request to an API endpoint that does not require pagination.

        Args:
            path (str): The path to the API endpoint.
            f (Callable[[dict], T]): The function to parse the JSON response.
            body (dict, optional): The body of the request. Defaults to None.
            params (dict, optional): The parameters of the request. Defaults to None.

        Returns:
            T: Result.
        """
        if method == "GET":
            response = await self._make_authed_request_get(
                self.config.url(path), body, params
            )
        else:
            response = await self._make_authed_request_post(
                self.config.url(path), body, params
            )
        return f(response.response)

    async def _request_returns_data(
        self,
        path: str,
        body: dict | None = None,
        params: dict | None = None,
    ) -> bool:
        """Check if a request to an API endpoint returns data.

        Args:
            path (str): The path to the API endpoint.
            body (dict, optional): The body of the request. Defaults to None.
            params (dict, optional): The parameters of the request. Defaults to None.

        Returns:
            bool: True if data is returned, False otherwise.
        """
        response = await self._make_authed_request_get(
            self.config.url(path), body, params
        )
        return bool(response.response)

    async def _get_initial_access_token(self, code: str) -> CanvasAccessToken:
        params = {
            "client_id": self.config.client_id,
            "client_secret": self.config.client_secret,
            "response_type": "code",
            "code": code,
            "redirect_uri": config.url("/api/v1/auth/canvas"),
        }
        return await self._request_access_token(
            CanvasInitialAccessTokenRequest(**params)
        )

    async def complete_initial_auth(self, code: str) -> RedirectResponse:
        try:
            response = await self._get_initial_access_token(code)
        except aiohttp.ClientResponseError:
            return RedirectResponse(
                config.url(f"/group/{self.class_id}/manage?error_code=5"),
                status_code=303,
            )

        # Save the access token to the database
        await Class.update_lms_token(
            self.db,
            self.class_id,
            response.access_token,
            response.expires_in,
            refresh_token=response.refresh_token,
            user_id=self.user_id,
        )
        return RedirectResponse(
            config.url(f"/group/{self.class_id}/manage"),
            status_code=303,
        )

    async def _refresh_access_token(self, refresh_token: str) -> CanvasAccessToken:
        params = {
            "client_id": self.config.client_id,
            "client_secret": self.config.client_secret,
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        }
        return await self._request_access_token(
            CanvasRefreshAccessTokenRequest(**params)
        )

    def _process_courses(self, data: list[dict]) -> list[CanvasClassSchema]:
        """Process the JSON response of the Canvas courses API."""

        return [self._process_course(course) for course in data]

    def _process_course(self, data: dict) -> CanvasClassSchema:
        """Process the JSON response of the Canvas course API.

        We extract:
        - The course ID (canvas_id)
        - The course name
        - The course code (shortened course name)
        - The term name (used to differentiate between courses with the same name)

        Documentation for the Course object response can be found at:
        https://canvas.instructure.com/doc/api/courses.html#Course
        """
        return CanvasClassSchema(
            lms_id=data["id"],
            lms_tenant=self.config.tenant,
            lms_type=self.config.type,
            name=data["name"],
            course_code=data["course_code"],
            term=data["term"]["name"],
        )

    async def get_courses(self) -> list[CanvasClassSchema]:
        """Get the list of courses for the current user."""

        # List your courses
        # Scope: url:GET|/api/v1/courses
        # Returns the paginated list of active courses for the current user.
        #
        # Documentation for the Course object response can be found at:
        # https://canvas.instructure.com/doc/api/courses.html#Course
        request_url = "/api/v1/courses"

        # Request Parameters:
        # - include[]:
        #   - term: Optional information to include with each Course.
        #           When term is given, the information for the enrollment
        #           term for each course is returned.
        params = {"include[]": ["term"]}

        return await self._paginated_request(
            request_url, self._process_courses, params=params
        )

    def _enrollment_check(
        self,
        course_id: str,
    ) -> Callable[[list[dict], bool | None], bool | None]:
        """Generate a function to check if the user has a teacher or TA enrollment in the course."""

        def f(data: list[dict], result: bool | None) -> bool | None:
            for enrollment in data:
                if enrollment["course_id"] == int(course_id):
                    raise BreakLoopException(True)
            return result

        return f

    async def _in_teaching_staff(self, course_id: str) -> bool:
        """Confirm that the current user has a Teacher or TA role in the current class."""

        # List user enrollments
        # Scope: url:GET|/api/v1/users/self/enrollments
        # Returns the paginated list of courses in which the current user is enrolled.
        #
        # If a user has multiple enrollments in a context (e.g. as a teacher and a student
        # or in multiple course sections), each enrollment will be listed separately.
        #
        # Documentation for the Enrollment object response can be found at:
        # https://canvas.instructure.com/doc/api/enrollments.html#Enrollment
        request_url = "/api/v1/users/self/enrollments"

        # Request Parameters:
        # - type[]: The type of enrollments to list. A list of enrollment types to return.
        # Accepted values are ‘StudentEnrollment’, ‘TeacherEnrollment’, ‘TaEnrollment’,
        # ‘DesignerEnrollment’, and ‘ObserverEnrollment.’ If omitted, all enrollment types
        # are returned.
        params = {
            "type[]": [
                "TeacherEnrollment",
                "TaEnrollment",
            ]
        }

        return (
            await self._paginated_request_single(
                request_url, self._enrollment_check(course_id), params=params
            )
            or False
        )

    async def _roster_access_check(self, course_id: str) -> bool:
        """Check if the user has access to the course roster."""

        # List users in course
        # Scope: url:GET|/api/v1/courses/:course_id/search_users
        # Returns the paginated list of users in this course.
        #
        # Documentation for the User object response can be found at:
        # https://canvas.instructure.com/doc/api/users.html#User
        request_url = f"/api/v1/courses/{course_id}/users"

        return await self._request_returns_data(request_url)

    async def verify_access(self, course_id: str) -> None:
        """Verify that the user has access to the course and the roster."""
        if not await self._in_teaching_staff(course_id):
            raise HTTPException(
                status_code=403,
                detail="You are not an authorized teacher or TA in the Canvas class you are trying to access.",
            )

        if not await self._roster_access_check(course_id):
            raise HTTPException(
                status_code=403,
                detail="You are not authorized to access the enrollment list for this Canvas class.",
            )

    async def _get_course_details(self, course_id: str) -> CanvasClassSchema:
        """Get the details of a course."""

        # Get a single course
        # Scope: url:GET|/api/v1/courses/:id
        # Return information on a single course.
        #
        # Documentation for the Course object response can be found at:
        # https://canvas.instructure.com/doc/api/courses.html#Course
        request_url = f"/api/v1/courses/{course_id}"

        # Request Parameters:
        # - include[]:
        #   - term: Optional information to include with each Course.
        #           When term is given, the information for the enrollment
        #           term for each course is returned.
        params = {"include[]": ["term"]}

        return await self._non_paginated_request(
            request_url, self._process_course, params=params
        )

    async def set_canvas_class(self, course_id: str) -> None:
        """Set the Canvas class for the PingPong class."""

        await self.verify_access(course_id)

        canvas_class = await self._get_course_details(course_id)
        r = LMSClassRequest(
            name=canvas_class.name,
            course_code=canvas_class.course_code,
            term=canvas_class.term,
            lms_id=canvas_class.lms_id,
            lms_tenant=self.config.tenant,
            lms_type=self.config.type,
        )
        lms_class = await CanvasClass.create_or_update(self.db, r)
        await Class.update_lms_class(self.db, self.class_id, lms_class.id)

    @abstractmethod
    def _sync_allowed(self, last_synced: datetime | None, now: datetime) -> bool:
        """Check if a sync is allowed based on the last sync time and the time between syncs."""
        pass

    def _process_users(self, data: list[dict]) -> list[CreateUserClassRole]:
        """Generate a CreateUserClassRole object from the JSON response of a user.

        We extract the user's email address and determine if they are a teacher or student.

        Relevant fields:
        // Optional: This field can be requested with certain API calls, and will return
        // the users primary email address.
        "email": "sheldon@caltech.example.com",

        // Optional: This field can be requested with certain API calls, and will return
        // a list of the users active enrollments. See the List enrollments API for more
        // details about the format of these records.
        "enrollments": null,

        Documentation for the User object response can be found at:
        https://canvas.instructure.com/doc/api/users.html#User

        Documentation for the Enrollment object response can be found at:
        https://canvas.instructure.com/doc/api/enrollments.html#Enrollment
        """

        user_roles: list[CreateUserClassRole] = []
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

        return user_roles

    async def _get_course_users(self, course_id: str) -> list[CreateUserClassRole]:
        """Get the users in a course."""

        # List users in course
        # Scope: url:GET|/api/v1/courses/:course_id/users
        # Returns the paginated list of users in this course.
        #
        # Documentation for the User object response can be found at:
        # https://canvas.instructure.com/doc/api/users.html#User
        # Documentation for the Enrollment object response can be found at:
        # https://canvas.instructure.com/doc/api/enrollments.html#Enrollment
        request_url = f"/api/v1/courses/{course_id}/users"

        # Request Parameters:
        # - include[]:
        #   - enrollments: Optionally include with each Course the user’s current
        #                  and invited enrollments. If the user is enrolled as a student,
        #                  and the account has permission to manage or view all grades,
        #                  each enrollment will include a ‘grades’ key with ‘current_score’,
        #                  ‘final_score’, ‘current_grade’ and ‘final_grade’ values.
        params = {"include[]": ["enrollments"]}

        return await self._paginated_request(
            request_url, self._process_users, params=params
        )

    @abstractmethod
    async def _update_user_roles(self) -> None:
        """Update the user roles for the class."""
        pass

    async def sync_roster(self) -> None:
        """Sync the roster for the class."""

        class_, now = await Class.get_lms_course_id(self.db, self.class_id)
        if not class_:
            raise HTTPException(status_code=400, detail="No linked Canvas course found")

        self._sync_allowed(class_.lms_last_synced, now)
        self.new_ucr = CreateUserClassRoles(
            roles=await self._get_course_users(class_.lms_class_id),
            silent=False,
            lms_tenant=self.config.tenant,
            lms_type=self.config.type,
        )
        await self._update_user_roles()
        await Class.update_last_synced(self.db, self.class_id)


class ManualCanvasClient(CanvasCourseClient):
    def __init__(
        self,
        canvas_backend_config: CanvasSettings,
        class_id: int,
        request: Request,
        tasks: BackgroundTasks,
        nowfn: NowFn = utcnow,
    ):
        super().__init__(
            canvas_backend_config,
            request.state.db,
            class_id,
            request.state.session.user.id,
            nowfn=nowfn,
        )
        self.request = request
        self.tasks = tasks

    def _sync_allowed(self, last_synced: datetime | None, now: datetime):
        """Check if a sync is allowed based on the last sync time and the time between syncs."""
        if last_synced and last_synced > now - timedelta(
            minutes=self.min_between_syncs
        ):
            # Calculate the remaining time until the next allowed sync. Add one second so we never return 0.
            time_remaining = (
                last_synced + timedelta(minutes=self.min_between_syncs) - now
            ).total_seconds() + 1

            raise HTTPException(
                status_code=429,
                detail=f"A Canvas sync was recently completed. Please wait before trying again. You can request a manual sync in {convert_seconds(int(time_remaining))}.",
            )

    async def _update_user_roles(self):
        """Update the user roles for the class."""
        await AddNewUsersManual(
            str(self.class_id), self.new_ucr, self.request, self.tasks
        ).add_new_users()


class LightweightCanvasClient(CanvasCourseClient):
    """A lightweight version of the Canvas client that does not support syncing or updating user roles."""

    def __init__(
        self,
        canvas_backend_config: CanvasSettings,
        class_id: int,
        request: Request,
        nowfn: NowFn = utcnow,
    ):
        super().__init__(
            canvas_backend_config,
            request.state.db,
            class_id,
            request.state.session.user.id,
            nowfn=nowfn,
        )
        self.request = request

    def _sync_allowed(self, last_synced: datetime | None, now: datetime):
        """Check if a sync is allowed based on the last sync time and the time between syncs."""
        raise NotImplementedError("LightweightCanvasClient does not support syncing.")

    async def _update_user_roles(self):
        """Update the user roles for the class."""
        raise NotImplementedError(
            "LightweightCanvasClient does not support updating user roles."
        )


class ScriptCanvasClient(CanvasCourseClient):
    def __init__(
        self,
        canvas_backend_config: CanvasSettings,
        db: AsyncSession,
        client: OpenFgaAuthzClient,
        class_id: int,
        user_id: int,
        nowfn: Callable[[], datetime] = utcnow,
    ):
        super().__init__(
            canvas_backend_config,
            db,
            class_id,
            user_id,
            nowfn=nowfn,
        )
        self.client = client

    def _sync_allowed(self, last_synced: datetime | None, now: datetime):
        pass

    async def _update_user_roles(self):
        """Update the user roles for the class."""
        await AddNewUsersScript(
            str(self.class_id), self.user_id, self.db, self.client, self.new_ucr
        ).add_new_users()


async def canvas_sync_all(
    session: AsyncSession, authz_: OpenFgaAuthzClient, canvas_backend: CanvasSettings
) -> None:
    async for class_ in Class.get_all_to_sync(
        session, canvas_backend.tenant, LMSType(canvas_backend.type)
    ):
        logger.info(f"Syncing class {class_.id}...")
        async with ScriptCanvasClient(
            canvas_backend,
            session,
            authz_,
            class_.id,
            class_.lms_user_id,
        ) as client:
            await client.sync_roster()
            await session.commit()
