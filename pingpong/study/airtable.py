import asyncio
from requests import HTTPError
from pingpong.users import UserNotFoundException
from pingpong.study.schemas import (
    Admin,
    Course,
    Instructor,
    PreAssessmentStudentSubmission,
)


async def get_instructor(user_id: str) -> Instructor:
    try:
        instructor = await asyncio.to_thread(Instructor.from_id, user_id)
    except HTTPError as e:
        if e.response.status_code == 403:
            raise UserNotFoundException(
                detail="We couldn't find you in the study database. Please contact the study administrator.",
                user_id=user_id,
            )

    return instructor


async def get_instructor_by_email(email: str) -> Instructor | None:
    email_to_match = email.lower().strip()
    formula = Instructor.academic_email.eq(
        email_to_match
    ) | Instructor.personal_email.eq(email_to_match)
    instructor = await asyncio.to_thread(Instructor.first, formula=formula)
    return instructor


async def get_courses_by_instructor_id(instructor_id: str) -> list[Course]:
    formula = Course.instructor.eq(instructor_id)
    courses = await asyncio.to_thread(Course.all, formula=formula)
    return courses


async def check_if_instructor_teaches_course_by_ids(
    instructor_id: str, course_id: str
) -> bool:
    courses = await get_courses_by_instructor_id(instructor_id)
    return any(course.id == course_id for course in courses)


async def get_preassessment_students_by_class_id(
    class_id: str,
) -> list[PreAssessmentStudentSubmission]:
    formula = PreAssessmentStudentSubmission.course_id.eq(class_id) & PreAssessmentStudentSubmission.status.eq("Processed")
    submissions = await asyncio.to_thread(
        PreAssessmentStudentSubmission.all, formula=formula
    )
    return submissions


async def get_admin_by_id(admin_id: str) -> Admin | None:
    admin = await asyncio.to_thread(Admin.from_id, admin_id)
    return admin


async def get_admin_by_email(email: str) -> Admin | None:
    email_to_match = email.lower().strip()
    formula = Admin.email.eq(email_to_match)
    admin = await asyncio.to_thread(Admin.first, formula=formula)
    return admin
