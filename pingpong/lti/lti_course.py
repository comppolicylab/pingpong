from pingpong.models import LTIClass, Class
from sqlalchemy.ext.asyncio import AsyncSession


async def find_class_by_course_id(
    db: AsyncSession, registration_id: int, course_id: str
) -> LTIClass | Class | None:
    lti_course = await LTIClass.get_by_registration_and_course_id(
        db,
        registration_id=registration_id,
        course_id=course_id,
    )
    if lti_course is not None:
        return lti_course

    return None


async def find_class_by_course_id_search_by_canvas_account_lti_guid(
    db: AsyncSession, registration_id: int, canvas_account_lti_guid: str, course_id: str
) -> LTIClass | Class | None:
    # First try to find by registration and course ID
    lti_course = await LTIClass.get_by_registration_and_course_id(
        db,
        registration_id=registration_id,
        course_id=course_id,
    )
    if lti_course is not None:
        return lti_course

    lti_course = await LTIClass.get_linked_by_canvas_account_lti_guid_and_course_id(
        db,
        canvas_account_lti_guid=canvas_account_lti_guid,
        course_id=course_id,
    )
    return lti_course
