import pytest
from sqlalchemy import func, select

from pingpong import models, schemas
from pingpong.merge import merge_external_logins

pytestmark = pytest.mark.asyncio


async def _create_user(session, user_id: int, email: str) -> models.User:
    user = models.User(id=user_id, email=email, state=schemas.UserState.VERIFIED)
    session.add(user)
    await session.flush()
    return user


async def _create_external_login(
    session,
    user_id: int,
    provider: str,
    identifier: str,
    provider_id: int,
) -> models.ExternalLogin:
    login = models.ExternalLogin(
        user_id=user_id,
        provider=provider,
        provider_id=provider_id,
        identifier=identifier,
    )
    session.add(login)
    await session.flush()
    return login


async def test_merge_external_logins_moves_rows_to_new_user(db):
    async with db.async_session() as session:
        old_user = await _create_user(session, 2001, "old-user@example.com")
        new_user = await _create_user(session, 2002, "new-user@example.com")

        saml_provider = await models.ExternalLoginProvider.get_or_create_by_name(
            session, "saml"
        )
        canvas_provider = await models.ExternalLoginProvider.get_or_create_by_name(
            session, "canvas"
        )

        old_saml_login = await _create_external_login(
            session,
            user_id=old_user.id,
            provider="saml",
            provider_id=saml_provider.id,
            identifier="saml-old-id",
        )
        old_canvas_login = await _create_external_login(
            session,
            user_id=old_user.id,
            provider="canvas",
            provider_id=canvas_provider.id,
            identifier="canvas-old-id",
        )
        github_provider = await models.ExternalLoginProvider.get_or_create_by_name(
            session, "github"
        )
        existing_new_login = await _create_external_login(
            session,
            user_id=new_user.id,
            provider="github",
            provider_id=github_provider.id,
            identifier="github-new-id",
        )

        moved_login_ids = {old_saml_login.id, old_canvas_login.id}

        await merge_external_logins(session, new_user.id, old_user.id)
        await session.flush()

        old_user_login_count = await session.scalar(
            select(func.count(models.ExternalLogin.id)).where(
                models.ExternalLogin.user_id == old_user.id
            )
        )
        assert old_user_login_count == 0

        moved_rows_result = await session.execute(
            select(models.ExternalLogin).where(
                models.ExternalLogin.id.in_(moved_login_ids)
            )
        )
        moved_rows = moved_rows_result.scalars().all()
        assert {login.id for login in moved_rows} == moved_login_ids
        assert all(login.user_id == new_user.id for login in moved_rows)

        new_user_rows_result = await session.execute(
            select(models.ExternalLogin).where(
                models.ExternalLogin.user_id == new_user.id
            )
        )
        new_user_rows = new_user_rows_result.scalars().all()
        assert {login.id for login in new_user_rows} == moved_login_ids | {
            existing_new_login.id
        }


async def test_merge_external_logins_drops_same_provider_different_identifier(db):
    async with db.async_session() as session:
        old_user = await _create_user(session, 2011, "old-dup@example.com")
        new_user = await _create_user(session, 2012, "new-dup@example.com")

        saml_provider = await models.ExternalLoginProvider.get_or_create_by_name(
            session, "saml"
        )
        canvas_provider = await models.ExternalLoginProvider.get_or_create_by_name(
            session, "canvas"
        )

        old_conflicting_saml = await _create_external_login(
            session,
            user_id=old_user.id,
            provider="saml",
            provider_id=saml_provider.id,
            identifier="shared-sso-id-old",
        )
        old_canvas_login = await _create_external_login(
            session,
            user_id=old_user.id,
            provider="canvas",
            provider_id=canvas_provider.id,
            identifier="canvas-unique-id",
        )
        existing_new_saml = await _create_external_login(
            session,
            user_id=new_user.id,
            provider="saml",
            provider_id=saml_provider.id,
            identifier="shared-sso-id-new",
        )

        await merge_external_logins(session, new_user.id, old_user.id)
        await session.flush()

        old_user_login_count = await session.scalar(
            select(func.count(models.ExternalLogin.id)).where(
                models.ExternalLogin.user_id == old_user.id
            )
        )
        assert old_user_login_count == 0

        new_user_rows_result = await session.execute(
            select(models.ExternalLogin).where(
                models.ExternalLogin.user_id == new_user.id
            )
        )
        new_user_rows = new_user_rows_result.scalars().all()
        assert {login.id for login in new_user_rows} == {
            existing_new_saml.id,
            old_canvas_login.id,
        }
        assert old_conflicting_saml.id not in {login.id for login in new_user_rows}


async def test_merge_external_logins_allows_multiple_email_identifiers(db):
    async with db.async_session() as session:
        old_user = await _create_user(session, 2021, "old-email@example.com")
        new_user = await _create_user(session, 2022, "new-email@example.com")

        email_provider = await models.ExternalLoginProvider.get_or_create_by_name(
            session, "email"
        )

        old_email_login = await _create_external_login(
            session,
            user_id=old_user.id,
            provider="email",
            provider_id=email_provider.id,
            identifier="old-secondary@example.com",
        )
        new_email_login = await _create_external_login(
            session,
            user_id=new_user.id,
            provider="email",
            provider_id=email_provider.id,
            identifier="new-secondary@example.com",
        )

        await merge_external_logins(session, new_user.id, old_user.id)
        await session.flush()

        old_user_login_count = await session.scalar(
            select(func.count(models.ExternalLogin.id)).where(
                models.ExternalLogin.user_id == old_user.id
            )
        )
        assert old_user_login_count == 0

        new_user_rows_result = await session.execute(
            select(models.ExternalLogin).where(
                models.ExternalLogin.user_id == new_user.id
            )
        )
        new_user_rows = new_user_rows_result.scalars().all()
        assert {login.id for login in new_user_rows} == {
            old_email_login.id,
            new_email_login.id,
        }
