import pytest
from sqlalchemy.exc import IntegrityError

from pingpong import models, schemas

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
    provider_id: int | None = None,
) -> models.ExternalLogin:
    login = models.ExternalLogin(
        user_id=user_id,
        provider=provider,
        identifier=identifier,
        provider_id=provider_id,
    )
    session.add(login)
    await session.flush()
    return login


async def test_get_by_email_external_logins_priority_providers_win_over_email(db):
    async with db.async_session() as session:
        email_user = await _create_user(session, 1001, "email-hit@example.com")
        fallback_user = await _create_user(session, 1002, "fallback@example.com")
        saml_provider = await models.ExternalLoginProvider.get_or_create_by_name(
            session, "saml"
        )
        await _create_external_login(
            session,
            fallback_user.id,
            provider="saml",
            identifier="sso-123",
            provider_id=saml_provider.id,
        )

        (
            result_user,
            matched_user_ids,
        ) = await models.User.get_by_email_external_logins_priority(
            session,
            email="email-hit@example.com",
            lookup_items=[
                schemas.ExternalLoginLookupItem(provider="saml", identifier="sso-123")
            ],
        )

        assert result_user is not None
        assert result_user.id == fallback_user.id
        assert matched_user_ids == [email_user.id, fallback_user.id]


async def test_get_by_email_external_logins_priority_falls_back_to_email(db):
    async with db.async_session() as session:
        email_user = await _create_user(session, 1003, "email-fallback@example.com")

        (
            result_user,
            matched_user_ids,
        ) = await models.User.get_by_email_external_logins_priority(
            session,
            email="email-fallback@example.com",
            lookup_items=[
                schemas.ExternalLoginLookupItem(
                    provider="saml",
                    identifier="missing-sso",
                )
            ],
        )

        assert result_user is not None
        assert result_user.id == email_user.id
        assert matched_user_ids == [email_user.id]


async def test_get_by_email_external_logins_priority_respects_lookup_order(db):
    async with db.async_session() as session:
        saml_provider = await models.ExternalLoginProvider.get_or_create_by_name(
            session, "saml"
        )
        canvas_provider = await models.ExternalLoginProvider.get_or_create_by_name(
            session, "canvas"
        )

        saml_user = await _create_user(session, 1101, "saml-user@example.com")
        canvas_user = await _create_user(session, 1102, "canvas-user@example.com")

        await _create_external_login(
            session,
            saml_user.id,
            provider="saml",
            identifier="shared-id",
            provider_id=saml_provider.id,
        )
        await _create_external_login(
            session,
            canvas_user.id,
            provider="canvas",
            identifier="shared-id",
            provider_id=canvas_provider.id,
        )

        (
            result_user,
            matched_user_ids,
        ) = await models.User.get_by_email_external_logins_priority(
            session,
            email="missing@example.com",
            lookup_items=[
                schemas.ExternalLoginLookupItem(
                    provider="canvas", identifier="shared-id"
                ),
                schemas.ExternalLoginLookupItem(
                    provider="saml", identifier="shared-id"
                ),
            ],
        )

        assert result_user is not None
        assert result_user.id == canvas_user.id
        assert matched_user_ids == [saml_user.id, canvas_user.id]


async def test_get_by_email_external_logins_priority_provider_id_and_provider_name(db):
    async with db.async_session() as session:
        saml_provider = await models.ExternalLoginProvider.get_or_create_by_name(
            session, "saml"
        )
        canvas_provider = await models.ExternalLoginProvider.get_or_create_by_name(
            session, "canvas"
        )

        saml_user = await _create_user(session, 1201, "saml@example.com")
        canvas_user = await _create_user(session, 1202, "canvas@example.com")

        # Provider-id-based lookup now depends on ExternalLogin.provider_id.
        await _create_external_login(
            session,
            saml_user.id,
            provider="saml",
            identifier="legacy-sso",
            provider_id=saml_provider.id,
        )
        await _create_external_login(
            session,
            canvas_user.id,
            provider="canvas",
            identifier="canvas-sso",
            provider_id=canvas_provider.id,
        )

        (
            provider_id_result,
            provider_id_matches,
        ) = await models.User.get_by_email_external_logins_priority(
            session,
            email="missing-1@example.com",
            lookup_items=[
                schemas.ExternalLoginLookupItem(
                    provider_id=saml_provider.id, identifier="legacy-sso"
                )
            ],
        )
        (
            provider_name_result,
            provider_name_matches,
        ) = await models.User.get_by_email_external_logins_priority(
            session,
            email="missing-2@example.com",
            lookup_items=[
                schemas.ExternalLoginLookupItem(
                    provider="canvas", identifier="canvas-sso"
                )
            ],
        )

        assert provider_id_result is not None
        assert provider_id_result.id == saml_user.id
        assert provider_id_matches == [saml_user.id]
        assert provider_name_result is not None
        assert provider_name_result.id == canvas_user.id
        assert provider_name_matches == [canvas_user.id]


async def test_get_by_email_external_logins_priority_provider_id_name_mismatch(db):
    async with db.async_session() as session:
        saml_provider = await models.ExternalLoginProvider.get_or_create_by_name(
            session, "saml"
        )

        with pytest.raises(ValueError, match="does not match provider_id"):
            await models.User.get_by_email_external_logins_priority(
                session,
                email="missing@example.com",
                lookup_items=[
                    schemas.ExternalLoginLookupItem(
                        provider_id=saml_provider.id,
                        provider="canvas",
                        identifier="abc123",
                    )
                ],
            )


async def test_get_by_email_external_logins_priority_duplicate_identity_is_rejected(db):
    async with db.async_session() as session:
        user_a = await _create_user(session, 1301, "a@example.com")
        user_b = await _create_user(session, 1302, "b@example.com")

        created_for_a = await models.ExternalLogin.create_or_update(
            session,
            user_id=user_a.id,
            provider="saml",
            identifier="duplicate-id",
        )
        created_for_b = await models.ExternalLogin.create_or_update(
            session,
            user_id=user_b.id,
            provider="saml",
            identifier="duplicate-id",
        )

        assert created_for_a is True
        assert created_for_b is False

        (
            result_user,
            matched_user_ids,
        ) = await models.User.get_by_email_external_logins_priority(
            session,
            email="missing@example.com",
            lookup_items=[
                schemas.ExternalLoginLookupItem(
                    provider="saml", identifier="duplicate-id"
                )
            ],
        )

        assert result_user is not None
        assert result_user.id == user_a.id
        assert matched_user_ids == [user_a.id]


async def test_get_by_email_external_logins_priority_returns_none_when_all_miss(db):
    async with db.async_session() as session:
        saml_provider = await models.ExternalLoginProvider.get_or_create_by_name(
            session, "saml"
        )
        user = await _create_user(session, 1401, "present@example.com")

        await _create_external_login(
            session,
            user.id,
            provider="saml",
            identifier="existing-id",
            provider_id=saml_provider.id,
        )

        (
            result_user,
            matched_user_ids,
        ) = await models.User.get_by_email_external_logins_priority(
            session,
            email="missing@example.com",
            lookup_items=[
                schemas.ExternalLoginLookupItem(
                    provider="saml", identifier="missing-id"
                )
            ],
        )

        assert result_user is None
        assert matched_user_ids == []


async def test_external_login_create_or_update_non_email_keeps_multiple_identifiers(db):
    async with db.async_session() as session:
        user = await _create_user(session, 1501, "issuer-user@example.com")
        provider = "https://canvas.instructure.com"

        await models.ExternalLogin.create_or_update(
            session,
            user_id=user.id,
            provider=provider,
            identifier="sub-1",
            replace_existing=False,
        )
        await models.ExternalLogin.create_or_update(
            session,
            user_id=user.id,
            provider=provider,
            identifier="sub-2",
            replace_existing=False,
        )

        logins = await models.User.get_external_logins_by_id(session, user.id)
        provider_logins = [login for login in logins if login.provider == provider]

        assert sorted(login.identifier for login in provider_logins) == [
            "sub-1",
            "sub-2",
        ]


async def test_external_login_create_or_update_non_email_replaces_by_default(db):
    async with db.async_session() as session:
        user = await _create_user(session, 1502, "replace-user@example.com")
        provider = "saml"

        await models.ExternalLogin.create_or_update(
            session,
            user_id=user.id,
            provider=provider,
            identifier="old-id",
        )
        await models.ExternalLogin.create_or_update(
            session,
            user_id=user.id,
            provider=provider,
            identifier="new-id",
        )

        logins = await models.User.get_external_logins_by_id(session, user.id)
        provider_logins = [login for login in logins if login.provider == provider]

        assert len(provider_logins) == 1
        assert provider_logins[0].identifier == "new-id"


async def test_external_login_create_or_update_non_email_returns_false_on_conflicting_user(
    db,
):
    async with db.async_session() as session:
        user_a = await _create_user(session, 1503, "owner@example.com")
        user_b = await _create_user(session, 1504, "other@example.com")
        provider = "saml"

        await models.ExternalLogin.create_or_update(
            session,
            user_id=user_a.id,
            provider=provider,
            identifier="shared-id",
        )
        result = await models.ExternalLogin.create_or_update(
            session,
            user_id=user_b.id,
            provider=provider,
            identifier="shared-id",
        )

        assert result is False
        user_b_logins = await models.User.get_external_logins_by_id(session, user_b.id)
        assert [login for login in user_b_logins if login.provider == provider] == []


async def test_external_login_uniqueness_prevents_cross_user_duplicates(db):
    async with db.async_session() as session:
        saml_provider = await models.ExternalLoginProvider.get_or_create_by_name(
            session, "saml"
        )
        user_a = await _create_user(session, 1601, "conflict-a@example.com")
        user_b = await _create_user(session, 1602, "conflict-b@example.com")

        await _create_external_login(
            session,
            user_a.id,
            provider="saml",
            identifier="shared-identifier",
            provider_id=saml_provider.id,
        )
        with pytest.raises(IntegrityError):
            await _create_external_login(
                session,
                user_b.id,
                provider="saml",
                identifier="shared-identifier",
                provider_id=saml_provider.id,
            )
        await session.rollback()


async def test_external_login_uniqueness_prevents_cross_user_email_duplicates(db):
    async with db.async_session() as session:
        email_provider = await models.ExternalLoginProvider.get_or_create_by_name(
            session, "email"
        )
        user_a = await _create_user(session, 1701, "email-a@example.com")
        user_b = await _create_user(session, 1702, "email-b@example.com")

        await _create_external_login(
            session,
            user_a.id,
            provider="email",
            identifier="secondary@example.com",
            provider_id=email_provider.id,
        )
        with pytest.raises(IntegrityError):
            await _create_external_login(
                session,
                user_b.id,
                provider="email",
                identifier="secondary@example.com",
                provider_id=email_provider.id,
            )
        await session.rollback()
