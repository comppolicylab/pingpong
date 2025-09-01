from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import RedirectResponse
from jwt import PyJWTError
import jwt
from pingpong.auth import (
    TimeException,
    decode_auth_token,
    decode_session_token,
    generate_auth_link,
    redirect_with_session_study,
)
from pingpong.permission import StudyExpression
import pingpong.schemas as schemas
from pingpong.config import config
from pingpong.session import get_now_fn
from pingpong.study.schemas import (
    Course,
    PreAssessmentStudentSubmissionsResponse,
    PreAssessmentStudentSubmissionResponse,
    UpdateEnrollmentRequest,
)
from pingpong.users import UserNotFoundException
from pingpong.study.airtable import (
    check_if_instructor_teaches_course_by_ids,
    get_admin_by_email,
    get_admin_by_id,
    get_courses_by_instructor_id,
    get_instructor,
    get_instructor_by_email,
    get_preassessment_students_by_class_id,
    update_course_enrollment_by_record_id,
    set_instructor_profile_notice_seen,
)
from pingpong.template import email_template as message_template
from pingpong.time import convert_seconds

study = FastAPI()


class LoggedIn(StudyExpression):
    async def test(self, request: Request) -> bool:
        return request.state.session.status == schemas.SessionStatus.VALID

    def __str__(self):
        return "LoggedIn()"


async def populate_request(request):
    try:
        session_token = request.cookies["study_session"]
    except KeyError:
        request.state.session = schemas.StudySessionState(
            status=schemas.SessionStatus.MISSING,
        )
    else:
        try:
            token = decode_session_token(session_token)
            instructor = await get_instructor(token.sub)
            request.state.session = schemas.StudySessionState(
                status=schemas.SessionStatus.VALID,
                token=token,
                instructor=schemas.InstructorResponse(
                    id=instructor.record_id,
                    first_name=instructor.first_name,
                    last_name=instructor.last_name,
                    academic_email=instructor.academic_email,
                    personal_email=instructor.personal_email,
                    honorarium_status=instructor.honorarium_status,
                    mailing_address=instructor.mailing_address,
                    institution=", ".join(instructor.institution),
                ),
                feature_flags=schemas.StudyFeatureFlags(
                    flags={
                        "notice.profile_moved.v1": bool(
                            instructor.profile_notice_seen_sep_25
                        )
                        if instructor.profile_notice_seen_sep_25 is not None
                        else False
                    }
                ),
            )
        except (PyJWTError, TimeException) as e:
            request.state.session = schemas.StudySessionState(
                status=schemas.SessionStatus.INVALID,
                error=e.detail if isinstance(e, TimeException) else str(e),
            )
        except UserNotFoundException as e:
            request.state.session = schemas.StudySessionState(
                status=schemas.SessionStatus.INVALID,
                error=e.detail,
            )
        except Exception as e:
            request.state.session = schemas.StudySessionState(
                status=schemas.SessionStatus.ERROR,
                error=str(e),
            )
    return request


@study.middleware("http")
async def parse_session_token(request: Request, call_next):
    """Parse the session token from the cookie and add it to the request state."""
    request = await populate_request(request)
    return await call_next(request)


@study.get(
    "/me",
)
async def get_me(request: Request):
    """Get the session information."""
    return request.state.session


@study.post(
    "/me/notices/seen",
    dependencies=[Depends(LoggedIn())],
    response_model=schemas.GenericStatus,
)
async def set_notice_seen(req: schemas.StudyNoticeSeenRequest, request: Request):
    """Mark a notice as seen for the current instructor.

    Currently supports:
    - notice.profile_moved.v1
    """
    user_id = request.state.session.token.sub  # type: ignore[attr-defined]
    if req.key == "notice.profile_moved.v1":
        await set_instructor_profile_notice_seen(user_id)
        return {"status": "ok"}
    raise HTTPException(status_code=400, detail="Unknown notice key")


@study.post("/login/magic", response_model=schemas.GenericStatus)
async def login_magic(body: schemas.MagicLoginRequest, request: Request):
    """Provide a magic link to the auth endpoint."""

    # Get the email from the request.
    email = body.email
    # Look up the user by email
    instructor = await get_instructor_by_email(email)
    # Throw an error if the user does not exist.
    if not instructor:
        raise HTTPException(
            status_code=401,
            detail="We couldn't find you in the study database. Ensure that you're using your institutional email address. If you're still having trouble, please contact the study administrator.",
        )

    nowfn = get_now_fn(request)
    magic_link = generate_auth_link(
        instructor.record_id,
        expiry=86_400,
        nowfn=nowfn,
        redirect=body.forward,
        is_study=True,
    )

    message = message_template.substitute(
        {
            "title": "Welcome back!",
            "subtitle": "Click the button below to log in to the PingPong College Study dashboard. No password required. It&#8217;s secure and easy.",
            "type": "login link",
            "cta": "Login to your Study Dashboard",
            "underline": "",
            "expires": convert_seconds(86_400),
            "link": magic_link,
            "email": email,
            "legal_text": "because you requested a login link from PingPong Study",
        }
    )

    await config.email.sender.send(
        email,
        "Log back in to your Study Dashboard",
        message,
    )

    return {"status": "ok"}


@study.post("/admin/login-as", response_model=schemas.GenericStatus)
async def login_as(body: schemas.LoginAsRequest, request: Request):
    """Send a magic link to the admin email to login as the instructor."""
    admin = await get_admin_by_email(body.admin_email)
    if not admin:
        raise HTTPException(status_code=403, detail="Access denied.")

    instructor = await get_instructor_by_email(body.instructor_email)
    if not instructor:
        raise HTTPException(status_code=404, detail="Instructor not found.")

    nowfn = get_now_fn(request)
    magic_link = generate_auth_link(
        f"{instructor.record_id}:{admin.record_id}",
        expiry=3_600,
        nowfn=nowfn,
        redirect=body.forward,
        is_study=True,
        is_study_admin=True,
    )

    message = message_template.substitute(
        {
            "title": f"Login as {instructor.first_name} {instructor.last_name}",
            "subtitle": "Click the button below to log in to the PingPong College Study dashboard as this instructor. No password required. It&#8217;s secure and easy.",
            "type": "login link",
            "cta": "Login as instructor",
            "underline": "",
            "expires": convert_seconds(3_600),
            "link": magic_link,
            "email": admin.email,
            "legal_text": "because you requested a login link from PingPong Study",
        }
    )

    await config.email.sender.send(
        admin.email,
        "Here's the Study Dashboard login link you requested",
        message,
    )

    return {"status": "ok"}


@study.get("/auth")
async def auth(request: Request):
    """Continue the auth flow based on a JWT in the query params.

    If the token is valid, determine the correct authn method based on the user.
    If the user is allowed to use magic link auth, they'll be authed automatically
    by this endpoint. If they have to go through SSO, they'll be redirected to the
    SSO login endpoint.

    Raises:
        HTTPException(401): If the token is invalid.
        HTTPException(500): If there is an runtime error decoding the token.
        HTTPException(404): If the user ID is not found.
        HTTPException(501): If we don't support the auth method for the user.

    Returns:
        RedirectResponse: Redirect either to the SSO login endpoint or to the destination.
    """
    dest = request.query_params.get("redirect", "/")
    stok = request.query_params.get("token")
    nowfn = get_now_fn(request)
    try:
        auth_token = decode_auth_token(stok, nowfn=nowfn)
    except jwt.exceptions.PyJWTError as e:
        raise HTTPException(status_code=401, detail=str(e))
    except TimeException as e:
        instructor = await get_instructor(e.user_id)
        forward = request.query_params.get("redirect", "/")
        if instructor and instructor.academic_email:
            try:
                await login_magic(
                    schemas.MagicLoginRequest(
                        email=instructor.academic_email, forward=forward
                    ),
                    request,
                )
            except HTTPException as e:
                # login_magic will throw a 403 if the user needs to use SSO
                # to log in. In that case, we redirect them to the SSO login
                # page.
                if e.status_code == 403:
                    return RedirectResponse(e.detail, status_code=303)
                else:
                    return RedirectResponse(
                        f"/login?expired=true&forward={forward}", status_code=303
                    )
            return RedirectResponse("/login?new_link=true", status_code=303)
        return RedirectResponse(
            f"/login?expired=true&forward={forward}", status_code=303
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    instructor = await get_instructor(auth_token.sub)
    if not instructor:
        raise HTTPException(
            status_code=404,
            detail="We couldn't find you in the study database. Please contact the study administrator.",
        )

    return redirect_with_session_study(dest, auth_token.sub, nowfn=nowfn)


@study.get("/auth/admin")
async def auth_admin(request: Request):
    """Continue the auth flow based on a JWT in the query params.

    If the token is valid, determine the correct authn method based on the user.
    If the user is allowed to use magic link auth, they'll be authed automatically
    by this endpoint. If they have to go through SSO, they'll be redirected to the
    SSO login endpoint.

    Raises:
        HTTPException(401): If the token is invalid.
        HTTPException(500): If there is an runtime error decoding the token.
        HTTPException(404): If the user ID is not found.
        HTTPException(501): If we don't support the auth method for the user.

    Returns:
        RedirectResponse: Redirect either to the SSO login endpoint or to the destination.
    """
    dest = request.query_params.get("redirect", "/")
    stok = request.query_params.get("token")
    nowfn = get_now_fn(request)
    try:
        auth_token = decode_auth_token(stok, nowfn=nowfn)
    except jwt.exceptions.PyJWTError as e:
        raise HTTPException(status_code=401, detail=str(e))
    except TimeException as e:
        # UserID format is <instructor_id>:<admin_id>
        instructor_id, admin_id = e.user_id.split(":")
        instructor = await get_instructor(instructor_id)
        admin = await get_admin_by_id(admin_id)
        forward = request.query_params.get("redirect", "/")
        if instructor and instructor.academic_email and admin and admin.email:
            try:
                await login_as(
                    schemas.LoginAsRequest(
                        instructor_email=instructor.academic_email,
                        admin_email=admin.email,
                        forward=forward,
                    ),
                    request,
                )
            except HTTPException as e:
                # login_magic will throw a 403 if the user needs to use SSO
                # to log in. In that case, we redirect them to the SSO login
                # page.
                if e.status_code == 403:
                    return RedirectResponse(e.detail, status_code=303)
                else:
                    return RedirectResponse(
                        f"/login?expired=true&forward={forward}", status_code=303
                    )
            return RedirectResponse("/login?new_link=true", status_code=303)
        return RedirectResponse(
            f"/login?expired=true&forward={forward}", status_code=303
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    instructor_id, admin_id = auth_token.sub.split(":")
    instructor = await get_instructor(instructor_id)
    admin = await get_admin_by_id(admin_id)
    if not admin:
        raise HTTPException(
            status_code=403,
            detail="Access denied. Please contact the study administrator.",
        )
    if not instructor:
        raise HTTPException(
            status_code=404,
            detail="We couldn't find the instructor in the study database. Please contact the study administrator.",
        )

    return redirect_with_session_study(dest, instructor_id, nowfn=nowfn)


def process_course(course: Course) -> schemas.StudyCourse:
    course_status = None
    match course.status:
        case "Ready for Review":
            course_status = "in_review"
        case "Further Review Needed":
            course_status = "in_review"
        case "Accepted, Pending Randomization":
            course_status = "in_review"
        case "Randomized":
            course_status = "in_review"
        case "Rejected":
            course_status = "rejected"
        case "Withdrawn":
            course_status = "withdrawn"
        case "Accepted — Treatment":
            course_status = "accepted"
        case "Accepted — Control":
            course_status = "accepted"
        case _:
            course_status = "in_review"

    randomization = None
    match course.randomization:
        case "Treatment":
            randomization = "treatment" if course_status == "accepted" else None
        case "Control":
            randomization = "control" if course_status == "accepted" else None
        case _:
            randomization = None

    return schemas.StudyCourse(
        id=course.record_id,
        name=course.name,
        status=course_status,
        randomization=randomization,
        start_date=course.start_date,
        enrollment_count=course.enrollment_count,
        completion_rate_target=course.completion_rate_target * 100
        if course_status == "accepted"
        else None,
        preassessment_url=course.preassessment_url
        if course_status == "accepted"
        else None,
        pingpong_group_url=course.pingpong_group_url
        if course_status == "accepted"
        else None,
        preassessment_student_count=course.preassessment_student_count
        if course_status == "accepted"
        else None,
    )


@study.get("/courses", dependencies=[Depends(LoggedIn())])
async def get_courses(request: Request):
    """Get the courses for the current user."""
    instructor = await get_instructor(request.state.session.token.sub)
    if not instructor:
        raise HTTPException(
            status_code=404,
            detail="We couldn't find you in the study database. Please contact the study administrator.",
        )

    courses = await get_courses_by_instructor_id(instructor.record_id)
    return {"courses": [process_course(course) for course in courses]}


@study.get(
    "/preassessment/{class_id}/students",
    dependencies=[Depends(LoggedIn())],
    response_model=PreAssessmentStudentSubmissionsResponse,
)
async def get_preassessment_students(class_id: str, request: Request):
    """Get the pre-assessment students for a specific class."""
    instructor = await get_instructor(request.state.session.token.sub)
    if not instructor:
        raise HTTPException(
            status_code=404,
            detail="We couldn't find you in the study database. Please contact the study administrator.",
        )

    if not await check_if_instructor_teaches_course_by_ids(
        instructor.record_id, class_id
    ):
        raise HTTPException(
            status_code=403,
            detail="You do not have permission to view this class's pre-assessment students.",
        )

    students = await get_preassessment_students_by_class_id(class_id)
    return {
        "students": [
            PreAssessmentStudentSubmissionResponse(
                id=student.submission_id,
                first_name=student.first_name,
                last_name=student.last_name,
                email=student.email,
                submission_date=student.submitted_at or "",
            )
            for student in sorted(
                students,
                key=lambda s: (
                    (s.last_name or "").lower(),
                    (s.first_name or "").lower(),
                ),
            )
        ]
    }


@study.patch(
    "/courses/{class_id}/enrollment",
    dependencies=[Depends(LoggedIn())],
    response_model=schemas.GenericStatus,
)
async def update_course_enrollment(
    class_id: str, body: UpdateEnrollmentRequest, request: Request
):
    """Update the enrollment count for a course taught by the current instructor.

    The `class_id` here refers to the course's custom "ID" field (`record_id`).
    """
    instructor = await get_instructor(request.state.session.token.sub)
    if not instructor:
        raise HTTPException(
            status_code=404,
            detail="We couldn't find you in the study database. Please contact the study administrator.",
        )

    # Basic validation
    if body.enrollment_count < 0:
        raise HTTPException(
            status_code=400, detail="Enrollment must be a non-negative integer."
        )

    # Authorization: instructor must teach this course
    teaches = await check_if_instructor_teaches_course_by_ids(
        instructor.record_id, class_id
    )
    if not teaches:
        raise HTTPException(
            status_code=403, detail="You do not have permission to update this course."
        )

    # Perform update
    try:
        await update_course_enrollment_by_record_id(class_id, body.enrollment_count)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    return {"status": "ok"}
