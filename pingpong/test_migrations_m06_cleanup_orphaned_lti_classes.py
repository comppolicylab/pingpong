import pytest
from sqlalchemy import select

from pingpong import models, schemas
from pingpong.migrations.m06_cleanup_orphaned_lti_classes import (
    cleanup_orphaned_lti_classes,
)

pytestmark = pytest.mark.asyncio


async def _create_registration(session) -> models.LTIRegistration:
    registration = models.LTIRegistration(
        issuer="https://issuer.example.com",
        client_id="client-1",
        auth_login_url="https://issuer.example.com/login",
        auth_token_url="https://issuer.example.com/token",
        key_set_url="https://issuer.example.com/jwks",
        token_algorithm=schemas.LTITokenAlgorithm.RS256,
        lms_platform=schemas.LMSPlatform.CANVAS,
        enabled=True,
        review_status=schemas.LTIRegistrationReviewStatus.APPROVED,
    )
    session.add(registration)
    await session.flush()
    return registration


async def test_cleanup_orphaned_lti_classes_deletes_only_orphaned_linked_and_error(db):
    async with db.async_session() as session:
        registration = await _create_registration(session)
        live_class = models.Class(name="Live group")
        session.add(live_class)
        await session.flush()

        orphan_linked = models.LTIClass(
            registration_id=registration.id,
            lti_status=schemas.LTIStatus.LINKED,
            lti_platform=schemas.LMSPlatform.CANVAS,
            course_id="course-linked",
            class_id=None,
        )
        orphan_error = models.LTIClass(
            registration_id=registration.id,
            lti_status=schemas.LTIStatus.ERROR,
            lti_platform=schemas.LMSPlatform.CANVAS,
            course_id="course-error",
            class_id=None,
        )
        keep_pending = models.LTIClass(
            registration_id=registration.id,
            lti_status=schemas.LTIStatus.PENDING,
            lti_platform=schemas.LMSPlatform.CANVAS,
            course_id="course-pending",
            class_id=None,
        )
        keep_linked = models.LTIClass(
            registration_id=registration.id,
            lti_status=schemas.LTIStatus.LINKED,
            lti_platform=schemas.LMSPlatform.CANVAS,
            course_id="course-active",
            class_id=live_class.id,
        )
        session.add_all([orphan_linked, orphan_error, keep_pending, keep_linked])
        await session.flush()

        deleted_count = await cleanup_orphaned_lti_classes(session)
        await session.commit()

        assert deleted_count == 2

    async with db.async_session() as session:
        remaining = await session.execute(select(models.LTIClass.course_id))
        remaining_course_ids = sorted(row[0] for row in remaining.fetchall())
        assert remaining_course_ids == ["course-active", "course-pending"]


async def test_cleanup_orphaned_lti_classes_dry_run_does_not_delete(db):
    async with db.async_session() as session:
        registration = await _create_registration(session)
        orphan_linked = models.LTIClass(
            registration_id=registration.id,
            lti_status=schemas.LTIStatus.LINKED,
            lti_platform=schemas.LMSPlatform.CANVAS,
            course_id="course-linked",
            class_id=None,
        )
        session.add(orphan_linked)
        await session.flush()

        deleted_count = await cleanup_orphaned_lti_classes(session, dry_run=True)
        await session.commit()

        assert deleted_count == 1

    async with db.async_session() as session:
        remaining_count_result = await session.execute(
            select(models.LTIClass).where(models.LTIClass.course_id == "course-linked")
        )
        assert remaining_count_result.scalar() is not None
