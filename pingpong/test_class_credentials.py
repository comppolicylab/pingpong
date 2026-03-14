import importlib
from unittest.mock import AsyncMock

from sqlalchemy import func, select

from pingpong import models
from pingpong.class_credentials import (
    ClassCredentialValidationSSLError,
    ClassCredentialValidationUnavailableError,
)
from .testutil import with_authz, with_user, with_institution

server_module = importlib.import_module("pingpong.server")


async def _create_class(db, institution_id: int, class_id: int) -> models.Class:
    async with db.async_session() as session:
        class_ = models.Class(
            id=class_id,
            name=f"Class {class_id}",
            term="Fall 2026",
            institution_id=institution_id,
        )
        session.add(class_)
        await session.commit()
        await session.refresh(class_)
        return class_


def _masked(api_key: str) -> str:
    if len(api_key) <= 12:
        return "*" * len(api_key)
    return f"{api_key[:8]}{'*' * 20}{api_key[-4:]}"


@with_user(123)
@with_institution(11, "Test Institution")
@with_authz(grants=[("user:123", "admin", "class:1")])
async def test_list_class_credentials_requires_view_permission(
    api, db, institution, valid_user_token
):
    await _create_class(db, institution.id, 1)

    response = api.get(
        "/api/v1/class/1/credentials",
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )

    assert response.status_code == 403
    assert response.json() == {"detail": "Missing required role"}


@with_user(123)
@with_institution(11, "Test Institution")
@with_authz(grants=[("user:123", "admin", "class:1")])
async def test_create_class_credential_grants_view_permission(
    api, db, institution, valid_user_token, monkeypatch
):
    await _create_class(db, institution.id, 1)
    monkeypatch.setattr(
        server_module, "validate_class_credential", AsyncMock(return_value=True)
    )

    api_key = "12345678abcdefghijklmnopqrstuv0000"
    response = api.post(
        "/api/v1/class/1/credentials",
        json={
            "api_key": api_key,
            "provider": "elevenlabs",
            "purpose": "lecture_video_narration_tts",
        },
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "credential": {
            "purpose": "lecture_video_narration_tts",
            "credential": {
                "api_key": _masked(api_key),
                "provider": "elevenlabs",
                "endpoint": None,
                "api_version": None,
                "available_as_default": None,
            },
        }
    }

    list_response = api.get(
        "/api/v1/class/1/credentials",
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )

    assert list_response.status_code == 200
    assert list_response.json() == {
        "credentials": [
            {
                "purpose": "lecture_video_narration_tts",
                "credential": {
                    "api_key": _masked(api_key),
                    "provider": "elevenlabs",
                    "endpoint": None,
                    "api_version": None,
                    "available_as_default": None,
                },
            },
            {
                "purpose": "lecture_video_manifest_generation",
                "credential": None,
            },
        ]
    }


@with_user(123)
@with_institution(11, "Test Institution")
@with_authz(grants=[("user:123", "admin", "class:1")])
async def test_create_class_credential_rejects_provider_purpose_mismatch(
    api, db, institution, valid_user_token
):
    await _create_class(db, institution.id, 1)

    response = api.post(
        "/api/v1/class/1/credentials",
        json={
            "api_key": "test-key",
            "provider": "elevenlabs",
            "purpose": "lecture_video_manifest_generation",
        },
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )

    assert response.status_code == 400
    assert (
        response.json()["detail"]
        == "lecture_video_manifest_generation only supports the gemini provider."
    )


@with_user(123)
@with_institution(11, "Test Institution")
@with_authz(grants=[("user:123", "admin", "class:1")])
async def test_create_class_credential_rejects_invalid_key(
    api, db, institution, valid_user_token, monkeypatch
):
    await _create_class(db, institution.id, 1)
    monkeypatch.setattr(
        server_module, "validate_class_credential", AsyncMock(return_value=False)
    )

    response = api.post(
        "/api/v1/class/1/credentials",
        json={
            "api_key": "bad-key",
            "provider": "gemini",
            "purpose": "lecture_video_manifest_generation",
        },
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )

    assert response.status_code == 400
    assert response.json() == {"detail": "Invalid API key provided. Please try again."}


@with_user(123)
@with_institution(11, "Test Institution")
@with_authz(grants=[("user:123", "admin", "class:1")])
async def test_create_class_credential_returns_503_when_provider_validation_is_unavailable(
    api, db, institution, valid_user_token, monkeypatch
):
    await _create_class(db, institution.id, 1)
    monkeypatch.setattr(
        server_module,
        "validate_class_credential",
        AsyncMock(
            side_effect=ClassCredentialValidationUnavailableError(
                provider="gemini",
                message="Provider temporarily unavailable.",
            )
        ),
    )

    response = api.post(
        "/api/v1/class/1/credentials",
        json={
            "api_key": "temporary-failure-key",
            "provider": "gemini",
            "purpose": "lecture_video_manifest_generation",
        },
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )

    assert response.status_code == 503
    assert response.json() == {
        "detail": (
            "Unable to validate the API key right now because the provider is unavailable. "
            "Please try again later."
        )
    }


@with_user(123)
@with_institution(11, "Test Institution")
@with_authz(grants=[("user:123", "admin", "class:1")])
async def test_create_class_credential_returns_503_when_provider_validation_has_ssl_error(
    api, db, institution, valid_user_token, monkeypatch
):
    await _create_class(db, institution.id, 1)
    monkeypatch.setattr(
        server_module,
        "validate_class_credential",
        AsyncMock(
            side_effect=ClassCredentialValidationSSLError(
                provider="gemini",
                message="SSL failure.",
            )
        ),
    )

    response = api.post(
        "/api/v1/class/1/credentials",
        json={
            "api_key": "temporary-failure-key",
            "provider": "gemini",
            "purpose": "lecture_video_manifest_generation",
        },
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )

    assert response.status_code == 503


@with_user(123)
@with_institution(11, "Test Institution")
@with_authz(grants=[("user:123", "admin", "class:1")])
async def test_create_class_credential_is_immutable_after_first_save(
    api, db, institution, valid_user_token, monkeypatch
):
    await _create_class(db, institution.id, 1)
    monkeypatch.setattr(
        server_module, "validate_class_credential", AsyncMock(return_value=True)
    )

    first_response = api.post(
        "/api/v1/class/1/credentials",
        json={
            "api_key": "gemini-key-0001",
            "provider": "gemini",
            "purpose": "lecture_video_manifest_generation",
        },
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )
    second_response = api.post(
        "/api/v1/class/1/credentials",
        json={
            "api_key": "gemini-key-0002",
            "provider": "gemini",
            "purpose": "lecture_video_manifest_generation",
        },
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )

    assert first_response.status_code == 200
    assert second_response.status_code == 400
    assert second_response.json() == {
        "detail": "Credential already exists for this purpose and cannot be changed."
    }


@with_user(123)
@with_institution(11, "Test Institution")
@with_authz(
    grants=[
        ("user:123", "admin", "class:1"),
        ("user:123", "admin", "class:2"),
    ]
)
async def test_create_class_credential_reuses_api_key_rows_across_classes(
    api, db, institution, valid_user_token, monkeypatch
):
    await _create_class(db, institution.id, 1)
    await _create_class(db, institution.id, 2)
    monkeypatch.setattr(
        server_module, "validate_class_credential", AsyncMock(return_value=True)
    )

    payload = {
        "api_key": "gemini-shared-key-1234",
        "provider": "gemini",
        "purpose": "lecture_video_manifest_generation",
    }
    response_a = api.post(
        "/api/v1/class/1/credentials",
        json=payload,
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )
    response_b = api.post(
        "/api/v1/class/2/credentials",
        json=payload,
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )

    assert response_a.status_code == 200
    assert response_b.status_code == 200

    async with db.async_session() as session:
        api_key_count = await session.scalar(
            select(func.count()).select_from(models.APIKey)
        )
        credential_count = await session.scalar(
            select(func.count()).select_from(models.ClassCredential)
        )

    assert api_key_count == 1
    assert credential_count == 2


@with_user(123)
@with_institution(11, "Test Institution")
@with_authz(grants=[("user:123", "admin", "class:1")])
async def test_create_class_credential_uses_body_purpose(
    api, db, institution, valid_user_token, monkeypatch
):
    await _create_class(db, institution.id, 1)
    monkeypatch.setattr(
        server_module, "validate_class_credential", AsyncMock(return_value=True)
    )

    response = api.post(
        "/api/v1/class/1/credentials",
        json={
            "api_key": "test-key",
            "provider": "gemini",
            "purpose": "lecture_video_manifest_generation",
        },
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )

    assert response.status_code == 200
    assert (
        response.json()["credential"]["purpose"] == "lecture_video_manifest_generation"
    )


def test_mask_api_key_value_fully_masks_short_values():
    assert server_module._mask_api_key_value("short") == "*****"
    assert server_module._mask_api_key_value("123456789012") == "************"
    assert (
        server_module._mask_api_key_value("12345678abcdefghijklmnopqrstuv0000")
        == "12345678********************0000"
    )


async def test_api_key_create_or_update_promotes_available_as_default_on_conflict(db):
    async with db.async_session() as session:
        created = await models.APIKey.create_or_update(
            session=session,
            api_key="shared-gemini-key",
            provider="gemini",
            available_as_default=False,
        )
        await session.commit()

        updated = await models.APIKey.create_or_update(
            session=session,
            api_key="shared-gemini-key",
            provider="gemini",
            available_as_default=True,
        )
        await session.commit()
        await session.refresh(updated)

    assert created.id == updated.id
    assert updated.available_as_default is True


async def test_api_key_create_or_update_preserves_available_as_default_on_false_upsert(
    db,
):
    async with db.async_session() as session:
        created = await models.APIKey.create_or_update(
            session=session,
            api_key="shared-gemini-key",
            provider="gemini",
            available_as_default=True,
        )
        await session.commit()

        updated = await models.APIKey.create_or_update(
            session=session,
            api_key="shared-gemini-key",
            provider="gemini",
            available_as_default=False,
        )
        await session.commit()
        await session.refresh(updated)

    assert created.id == updated.id
    assert updated.available_as_default is True
