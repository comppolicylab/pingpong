import pytest
from sqlalchemy import select

from pingpong import models, schemas
import pingpong.merge as merge_module
from pingpong.merge import merge_users

pytestmark = pytest.mark.asyncio


async def _create_user(session, user_id: int, email: str) -> models.User:
    user = models.User(id=user_id, email=email, state=schemas.UserState.VERIFIED)
    session.add(user)
    await session.flush()
    return user


async def test_merge_users_preserves_old_primary_email_as_secondary(db):
    async with db.async_session() as session:
        old_user = await _create_user(session, 2101, "old-primary@example.com")
        new_user = await _create_user(session, 2102, "new-primary@example.com")

        await merge_users(session, new_user.id, old_user.id)
        await session.flush()

        merged_user = await models.User.get_by_id(session, new_user.id)
        assert merged_user is not None
        assert merged_user.email == "new-primary@example.com"

        old_user_row = await models.User.get_by_id(session, old_user.id)
        assert old_user_row is None

        secondary_email_rows = await session.execute(
            select(models.ExternalLogin).where(
                models.ExternalLogin.user_id == new_user.id,
                models.ExternalLogin.provider == "email",
                models.ExternalLogin.identifier == "old-primary@example.com",
            )
        )
        secondary_emails = secondary_email_rows.scalars().all()
        assert len(secondary_emails) == 1


async def test_merge_users_does_not_duplicate_existing_secondary_email(db):
    async with db.async_session() as session:
        old_user = await _create_user(session, 2111, "old-secondary@example.com")
        new_user = await _create_user(session, 2112, "new-primary@example.com")

        email_provider = await models.ExternalLoginProvider.get_or_create_by_name(
            session, "email"
        )
        existing_secondary = models.ExternalLogin(
            user_id=new_user.id,
            provider="email",
            provider_id=email_provider.id,
            identifier="old-secondary@example.com",
        )
        session.add(existing_secondary)
        await session.flush()

        await merge_users(session, new_user.id, old_user.id)
        await session.flush()

        secondary_email_rows = await session.execute(
            select(models.ExternalLogin).where(
                models.ExternalLogin.user_id == new_user.id,
                models.ExternalLogin.provider == "email",
                models.ExternalLogin.identifier == "old-secondary@example.com",
            )
        )
        secondary_emails = secondary_email_rows.scalars().all()
        assert len(secondary_emails) == 1


async def test_merge_users_continues_when_secondary_email_upsert_raises_value_error(
    db, monkeypatch
):
    async with db.async_session() as session:
        old_user = await _create_user(session, 2121, "old-merge-error@example.com")
        new_user = await _create_user(session, 2122, "new-merge@example.com")
        call_count = 0

        async def _raise_value_error(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            raise ValueError("simulated create_or_update failure")

        monkeypatch.setattr(
            merge_module.ExternalLogin,
            "create_or_update",
            _raise_value_error,
        )

        merged_user = await merge_users(session, new_user.id, old_user.id)
        await session.flush()

        assert merged_user.id == new_user.id
        assert call_count == 1
        assert await models.User.get_by_id(session, old_user.id) is None
        assert await models.User.get_by_id(session, new_user.id) is not None

        secondary_email_rows = await session.execute(
            select(models.ExternalLogin).where(
                models.ExternalLogin.user_id == new_user.id,
                models.ExternalLogin.provider == "email",
                models.ExternalLogin.identifier == "old-merge-error@example.com",
            )
        )
        assert secondary_email_rows.scalars().first() is None
