from pingpong.models import LTIClass, Class
from sqlalchemy.ext.asyncio import AsyncSession


async def find_class_by_course_id(db: AsyncSession, registration_id: int, course_id: str) -> Class | None:
    lti_course = await LTIClass.get_by_registration_and_course_id(
        db,
        registration_id=registration_id,
        course_id=course_id,
    )
    if lti_course is not None:
        return lti_course.class_
    
    lms_courses = await Class.get_all_by_lms_course_id(
        db,
        lms_course_id=int(course_id),
    )
    if not lms_courses or len(lms_courses) > 1:
        return None
    
    return lms_courses[0]