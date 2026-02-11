import pytest

from pingpong import models, schemas

pytestmark = pytest.mark.asyncio


async def _create_registration(
    session,
    registration_id: int,
    canvas_account_lti_guid: str,
) -> models.LTIRegistration:
    registration = models.LTIRegistration(
        id=registration_id,
        issuer=f"https://issuer-{registration_id}.example.com",
        client_id=f"client-{registration_id}",
        auth_login_url="https://platform.example.com/auth",
        auth_token_url="https://platform.example.com/token",
        key_set_url="https://platform.example.com/jwks",
        token_algorithm=schemas.LTITokenAlgorithm.RS256,
        lms_platform=schemas.LMSPlatform.CANVAS,
        canvas_account_lti_guid=canvas_account_lti_guid,
        review_status=schemas.LTIRegistrationReviewStatus.APPROVED,
        enabled=True,
    )
    session.add(registration)
    await session.flush()
    return registration


async def test_get_linked_by_canvas_account_lti_guid_and_course_id_includes_error_status(
    db,
):
    async with db.async_session() as session:
        registration = await _create_registration(
            session,
            registration_id=3301,
            canvas_account_lti_guid="acct-guid-1",
        )
        errored_lti_class = models.LTIClass(
            registration_id=registration.id,
            lti_status=schemas.LTIStatus.ERROR,
            lti_platform=schemas.LMSPlatform.CANVAS,
            course_id="course-42",
        )
        session.add(errored_lti_class)
        await session.flush()

        result = (
            await models.LTIClass.get_linked_by_canvas_account_lti_guid_and_course_id(
                session,
                canvas_account_lti_guid="acct-guid-1",
                course_id="course-42",
            )
        )

        assert result is not None
        assert result.id == errored_lti_class.id


async def test_get_linked_by_canvas_account_lti_guid_and_course_id_excludes_pending_status(
    db,
):
    async with db.async_session() as session:
        registration = await _create_registration(
            session,
            registration_id=3302,
            canvas_account_lti_guid="acct-guid-2",
        )
        pending_lti_class = models.LTIClass(
            registration_id=registration.id,
            lti_status=schemas.LTIStatus.PENDING,
            lti_platform=schemas.LMSPlatform.CANVAS,
            course_id="course-84",
        )
        session.add(pending_lti_class)
        await session.flush()

        result = (
            await models.LTIClass.get_linked_by_canvas_account_lti_guid_and_course_id(
                session,
                canvas_account_lti_guid="acct-guid-2",
                course_id="course-84",
            )
        )

        assert result is None
