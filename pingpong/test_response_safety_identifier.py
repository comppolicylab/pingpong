import pytest

from pingpong import models, schemas
from pingpong.session import _ensure_safety_identifier_uuid


class _DummyRequest:
    def __init__(self, db_session):
        self.state = {"db": db_session}


@pytest.mark.asyncio
async def test_response_safety_identifier_preserves_existing_user_uuid(db):
    async with db.async_session() as session:
        user = models.User(
            email="existing-user-uuid@example.com",
            state=schemas.UserState.VERIFIED,
            safety_identifier_uuid="existing-user-uuid",
        )
        session.add(user)
        await session.flush()

        request = _DummyRequest(session)
        safety_identifier = await _ensure_safety_identifier_uuid(request, user)

        assert safety_identifier == "existing-user-uuid"
        assert user.safety_identifier_uuid == "existing-user-uuid"


@pytest.mark.asyncio
async def test_response_safety_identifier_generates_missing_user_uuid(db):
    async with db.async_session() as session:
        user = models.User(
            email="missing-user-uuid@example.com",
            state=schemas.UserState.VERIFIED,
            safety_identifier_uuid=None,
        )
        session.add(user)
        await session.flush()

        request = _DummyRequest(session)
        safety_identifier = await _ensure_safety_identifier_uuid(request, user)

        assert safety_identifier is not None
        assert user.safety_identifier_uuid == safety_identifier


@pytest.mark.asyncio
async def test_response_safety_identifier_generates_missing_anonymous_session_uuid(db):
    async with db.async_session() as session:
        user = models.User(
            email="anon-session-owner@example.com",
            state=schemas.UserState.VERIFIED,
        )
        session.add(user)
        await session.flush()

        anonymous_session = models.AnonymousSession(
            session_token="anon-session-token",
            user_id=user.id,
            safety_identifier_uuid=None,
        )
        session.add(anonymous_session)
        await session.flush()

        request = _DummyRequest(session)
        safety_identifier = await _ensure_safety_identifier_uuid(
            request, anonymous_session
        )

        assert safety_identifier is not None
        assert anonymous_session.safety_identifier_uuid == safety_identifier


@pytest.mark.asyncio
async def test_response_safety_identifier_generates_missing_anonymous_link_uuid(db):
    async with db.async_session() as session:
        link = models.AnonymousLink(
            share_token="anon-link-token",
            safety_identifier_uuid=None,
        )
        session.add(link)
        await session.flush()

        request = _DummyRequest(session)
        safety_identifier = await _ensure_safety_identifier_uuid(request, link)

        assert safety_identifier is not None
        assert link.safety_identifier_uuid == safety_identifier
