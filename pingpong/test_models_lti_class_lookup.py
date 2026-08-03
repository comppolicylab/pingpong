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


async def test_has_link_for_registration_and_course_allows_second_course_for_same_group(
    db,
):
    """A group may receive links from several courses in one registration."""
    async with db.async_session() as session:
        registration = await _create_registration(
            session,
            registration_id=3303,
            canvas_account_lti_guid="acct-guid-3",
        )
        group = models.Class(name="Shared group", term="Fall")
        session.add(group)
        await session.flush()

        # The group is already linked to one course in this registration.
        session.add(
            models.LTIClass(
                registration_id=registration.id,
                lti_status=schemas.LTIStatus.LINKED,
                lti_platform=schemas.LMSPlatform.CANVAS,
                course_id="course-101",
                class_id=group.id,
            )
        )
        # A second, not-yet-linked course in the same registration.
        session.add(
            models.LTIClass(
                registration_id=registration.id,
                lti_status=schemas.LTIStatus.PENDING,
                lti_platform=schemas.LMSPlatform.CANVAS,
                course_id="course-102",
            )
        )
        await session.flush()

        assert not await models.LTIClass.has_link_for_registration_and_course(
            session,
            registration_id=registration.id,
            course_id="course-102",
        )


async def test_has_link_for_registration_and_course_rejects_linked_course(db):
    async with db.async_session() as session:
        registration = await _create_registration(
            session,
            registration_id=3304,
            canvas_account_lti_guid="acct-guid-4",
        )
        group = models.Class(name="Group", term="Fall")
        session.add(group)
        await session.flush()

        session.add(
            models.LTIClass(
                registration_id=registration.id,
                lti_status=schemas.LTIStatus.LINKED,
                lti_platform=schemas.LMSPlatform.CANVAS,
                course_id="course-201",
                class_id=group.id,
            )
        )
        await session.flush()

        assert await models.LTIClass.has_link_for_registration_and_course(
            session,
            registration_id=registration.id,
            course_id="course-201",
        )


async def test_has_link_for_registration_and_course_scopes_to_registration(db):
    """The same LMS course id under a different registration must not collide."""
    async with db.async_session() as session:
        linked_reg = await _create_registration(
            session,
            registration_id=3305,
            canvas_account_lti_guid="acct-guid-5",
        )
        other_reg = await _create_registration(
            session,
            registration_id=3306,
            canvas_account_lti_guid="acct-guid-6",
        )
        group = models.Class(name="Group", term="Fall")
        session.add(group)
        await session.flush()

        session.add(
            models.LTIClass(
                registration_id=linked_reg.id,
                lti_status=schemas.LTIStatus.LINKED,
                lti_platform=schemas.LMSPlatform.CANVAS,
                course_id="course-301",
                class_id=group.id,
            )
        )
        await session.flush()

        assert not await models.LTIClass.has_link_for_registration_and_course(
            session,
            registration_id=other_reg.id,
            course_id="course-301",
        )
