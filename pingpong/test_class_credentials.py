import importlib
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock

import httpx
from elevenlabs.core.api_error import ApiError as ElevenLabsApiError
from elevenlabs.errors import (
    UnprocessableEntityError as ElevenLabsUnprocessableEntityError,
)
from elevenlabs.types.http_validation_error import HttpValidationError
import pytest
from sqlalchemy import func, select

from pingpong import models, schemas
from pingpong import elevenlabs as elevenlabs_module
from pingpong import gemini as gemini_module
from pingpong.class_credentials import (
    _CLASS_CREDENTIAL_VALIDATORS,
    ClassCredentialValidationSSLError,
    ClassCredentialValidationUnavailableError,
    expected_provider_for_purpose,
    provider_matches_purpose,
    validate_class_credential,
)
from .testutil import with_authz, with_user, with_institution

server_module = importlib.import_module("pingpong.server")


def test_class_credential_purpose_helpers_raise_clear_error_for_unsupported_purpose():
    unsupported_purpose = cast(schemas.ClassCredentialPurpose, object())

    with pytest.raises(
        ValueError,
        match="Unsupported class credential purpose:",
    ):
        expected_provider_for_purpose(unsupported_purpose)

    with pytest.raises(
        ValueError,
        match="Unsupported class credential purpose:",
    ):
        provider_matches_purpose(
            schemas.ClassCredentialProvider.GEMINI,
            unsupported_purpose,
        )


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

    api_key = "example-api-key-0000"
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
                "redacted_api_key": _masked(api_key),
                "provider": "elevenlabs",
                "endpoint": None,
                "api_version": None,
                "available_as_default": False,
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
                    "redacted_api_key": _masked(api_key),
                    "provider": "elevenlabs",
                    "endpoint": None,
                    "api_version": None,
                    "available_as_default": False,
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
@with_authz(grants=[("user:123", "admin", "class:1")])
async def test_create_class_credential_returns_400_when_model_create_raises_conflict_error(
    api, db, institution, valid_user_token, monkeypatch
):
    await _create_class(db, institution.id, 1)
    monkeypatch.setattr(
        server_module, "validate_class_credential", AsyncMock(return_value=True)
    )

    async def _raise_conflict_error(*args, **kwargs):
        raise models.ClassCredentialAlreadyExistsError(
            "Credential already exists for this purpose and cannot be changed."
        )

    monkeypatch.setattr(models.ClassCredential, "create", _raise_conflict_error)

    response = api.post(
        "/api/v1/class/1/credentials",
        json={
            "api_key": "gemini-key-0002",
            "provider": "gemini",
            "purpose": "lecture_video_manifest_generation",
        },
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )

    assert response.status_code == 400
    assert response.json() == {
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
    assert schemas.mask_api_key_value("short") == "*****"
    assert schemas.mask_api_key_value("test-key-000") == "************"
    assert (
        schemas.mask_api_key_value("example-api-key-0000")
        == "example-********************0000"
    )


@with_user(123)
@with_institution(11, "Test Institution")
@with_authz(
    grants=[
        ("user:123", "admin", "class:1"),
        ("user:123", "can_view_api_key", "class:1"),
    ]
)
async def test_class_api_key_responses_are_redacted_even_when_returning_models(
    api, db, institution, valid_user_token, monkeypatch
):
    await _create_class(db, institution.id, 1)
    monkeypatch.setattr(
        server_module,
        "validate_api_key",
        AsyncMock(return_value=schemas.APIKeyValidationResponse(valid=True)),
    )

    api_key = "example-api-key-0000"
    update_response = api.put(
        "/api/v1/class/1/api_key",
        json={
            "api_key": api_key,
            "provider": "openai",
        },
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )

    assert update_response.status_code == 200
    assert update_response.json() == {
        "api_key": {
            "redacted_api_key": _masked(api_key),
            "provider": "openai",
            "endpoint": None,
            "api_version": None,
            "available_as_default": False,
        }
    }

    duplicate_update_response = api.put(
        "/api/v1/class/1/api_key",
        json={
            "api_key": api_key,
            "provider": "openai",
        },
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )

    assert duplicate_update_response.status_code == 200
    assert duplicate_update_response.json() == {
        "api_key": {
            "redacted_api_key": _masked(api_key),
            "provider": "openai",
            "endpoint": None,
            "api_version": None,
            "available_as_default": False,
        }
    }

    get_response = api.get(
        "/api/v1/class/1/api_key",
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )

    assert get_response.status_code == 200
    assert get_response.json() == {
        "ai_provider": "openai",
        "has_gemini_credential": False,
        "has_elevenlabs_credential": False,
        "api_key": {
            "redacted_api_key": _masked(api_key),
            "provider": "openai",
            "endpoint": None,
            "api_version": None,
            "available_as_default": None,
        },
        "credentials": [
            {
                "purpose": "lecture_video_narration_tts",
                "credential": None,
            },
            {
                "purpose": "lecture_video_manifest_generation",
                "credential": None,
            },
        ],
    }


@with_user(123)
@with_institution(11, "Test Institution")
@with_authz(grants=[("user:123", "can_edit_info", "class:1")])
async def test_get_class_api_key_returns_summary_without_key_material_for_can_edit_info(
    api, db, institution, valid_user_token
):
    await _create_class(db, institution.id, 1)

    async with db.async_session() as session:
        await models.Class.update_api_key(
            session,
            1,
            "class-openai-key",
            provider="openai",
            endpoint=None,
            api_version=None,
            region=None,
            available_as_default=False,
        )
        await models.ClassCredential.create(
            session,
            1,
            schemas.ClassCredentialPurpose.LECTURE_VIDEO_MANIFEST_GENERATION,
            "gemini-key-1234",
            schemas.ClassCredentialProvider.GEMINI,
        )
        await session.commit()

    response = api.get(
        "/api/v1/class/1/api_key",
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )

    assert response.status_code == 200
    assert response.json() == {
        "ai_provider": "openai",
        "has_gemini_credential": True,
        "has_elevenlabs_credential": False,
        "api_key": None,
        "credentials": None,
    }


@with_user(123)
@with_institution(11, "Test Institution")
@with_authz(grants=[("user:123", "can_view", "class:1")])
async def test_api_key_check_returns_has_api_key_and_lecture_video_enabled(
    api, db, institution, valid_user_token
):
    await _create_class(db, institution.id, 1)

    first_response = api.get(
        "/api/v1/class/1/api_key/check",
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )
    assert first_response.status_code == 200
    assert first_response.json() == {
        "has_api_key": False,
        "has_lecture_video_providers": False,
    }

    async with db.async_session() as session:
        await models.Class.update_api_key(
            session,
            1,
            "class-openai-key",
            provider="openai",
            endpoint=None,
            api_version=None,
            region=None,
            available_as_default=False,
        )
        await models.ClassCredential.create(
            session,
            1,
            schemas.ClassCredentialPurpose.LECTURE_VIDEO_MANIFEST_GENERATION,
            "gemini-key-1234",
            schemas.ClassCredentialProvider.GEMINI,
        )
        await session.commit()

    second_response = api.get(
        "/api/v1/class/1/api_key/check",
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )
    assert second_response.status_code == 200
    assert second_response.json() == {
        "has_api_key": True,
        "has_lecture_video_providers": False,
    }

    async with db.async_session() as session:
        await models.ClassCredential.create(
            session,
            1,
            schemas.ClassCredentialPurpose.LECTURE_VIDEO_NARRATION_TTS,
            "elevenlabs-key-1234",
            schemas.ClassCredentialProvider.ELEVENLABS,
        )
        await session.commit()

    third_response = api.get(
        "/api/v1/class/1/api_key/check",
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )
    assert third_response.status_code == 200
    assert third_response.json() == {
        "has_api_key": True,
        "has_lecture_video_providers": True,
    }


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


async def test_api_key_create_or_update_preserves_region_when_upsert_region_is_none(db):
    async with db.async_session() as session:
        created = await models.APIKey.create_or_update(
            session=session,
            api_key="shared-azure-key",
            provider="azure_openai",
            region="eastus",
        )
        await session.commit()

        updated = await models.APIKey.create_or_update(
            session=session,
            api_key="shared-azure-key",
            provider="azure_openai",
        )
        await session.commit()
        await session.refresh(updated)

    assert created.id == updated.id
    assert updated.region == "eastus"


async def test_class_credential_create_raises_on_duplicate_insert(db):
    async with db.async_session() as session:
        class_ = models.Class(
            name="Credential race class",
            term="Fall 2026",
        )
        session.add(class_)
        await session.commit()
        await session.refresh(class_)

        created = await models.ClassCredential.create(
            session=session,
            class_id=class_.id,
            purpose=schemas.ClassCredentialPurpose.LECTURE_VIDEO_MANIFEST_GENERATION,
            api_key="duplicate-gemini-key",
            provider=schemas.ClassCredentialProvider.GEMINI,
        )
        await session.commit()

        with pytest.raises(
            models.ClassCredentialAlreadyExistsError,
            match="Credential already exists for this purpose and cannot be changed.",
        ):
            await models.ClassCredential.create(
                session=session,
                class_id=class_.id,
                purpose=schemas.ClassCredentialPurpose.LECTURE_VIDEO_MANIFEST_GENERATION,
                api_key="duplicate-gemini-key-2",
                provider=schemas.ClassCredentialProvider.GEMINI,
            )
        await session.commit()

        credential_count = await session.scalar(
            select(func.count()).select_from(models.ClassCredential)
        )
        api_key_count = await session.scalar(
            select(func.count()).select_from(models.APIKey)
        )
        await session.refresh(created)
        created_api_key = await created.awaitable_attrs.api_key_obj
        assert created_api_key.api_key == "duplicate-gemini-key"
    assert credential_count == 1
    assert api_key_count == 1


async def test_validate_class_credential_for_gemini_closes_async_and_sync_clients(
    monkeypatch,
):
    events: list[tuple[str, object | None]] = []

    class FakeModels:
        async def list(self, *, config):
            events.append(("list", config))

    class FakeAsyncClient:
        def __init__(self):
            self.models = FakeModels()

        async def __aenter__(self):
            events.append(("aenter", None))
            return self

        async def __aexit__(self, exc_type, exc_value, traceback):
            events.append(("aexit", None))

    class FakeClient:
        def __init__(self, *, api_key):
            events.append(("init", api_key))
            self.aio = FakeAsyncClient()

    monkeypatch.setattr(gemini_module.genai, "Client", FakeClient)

    result = await validate_class_credential(
        api_key="gemini-key",
        provider=schemas.ClassCredentialProvider.GEMINI,
    )

    assert result is True
    assert events == [
        ("init", "gemini-key"),
        ("aenter", None),
        ("list", {"page_size": 1}),
        ("aexit", None),
    ]


def test_class_credential_validators_cover_all_providers():
    assert set(_CLASS_CREDENTIAL_VALIDATORS) == set(schemas.ClassCredentialProvider)


@pytest.mark.parametrize("status_code", [401, 403])
async def test_validate_class_credential_for_gemini_returns_false_for_auth_client_errors(
    monkeypatch, status_code
):
    class FakeModels:
        async def list(self, *, config):
            raise gemini_module.genai.errors.ClientError(
                status_code,
                {"error": {"status": "PERMISSION_DENIED", "message": "bad auth"}},
            )

    class FakeAsyncClient:
        def __init__(self):
            self.models = FakeModels()

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc_value, traceback):
            return None

    class FakeClient:
        def __init__(self, *, api_key):
            self.aio = FakeAsyncClient()

    monkeypatch.setattr(gemini_module.genai, "Client", FakeClient)

    result = await validate_class_credential(
        api_key="gemini-key",
        provider=schemas.ClassCredentialProvider.GEMINI,
    )

    assert result is False


async def test_validate_class_credential_for_gemini_raises_unavailable_for_non_auth_client_errors(
    monkeypatch,
):
    class FakeModels:
        async def list(self, *, config):
            raise gemini_module.genai.errors.ClientError(
                429,
                {
                    "error": {
                        "status": "RESOURCE_EXHAUSTED",
                        "message": "quota exceeded",
                    }
                },
            )

    class FakeAsyncClient:
        def __init__(self):
            self.models = FakeModels()

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc_value, traceback):
            return None

    class FakeClient:
        def __init__(self, *, api_key):
            self.aio = FakeAsyncClient()

    monkeypatch.setattr(gemini_module.genai, "Client", FakeClient)

    with pytest.raises(
        ClassCredentialValidationUnavailableError,
        match=r"Unable to validate the Gemini API key right now\.",
    ):
        await validate_class_credential(
            api_key="gemini-key",
            provider=schemas.ClassCredentialProvider.GEMINI,
        )


async def test_synthesize_elevenlabs_voice_sample_maps_generic_voice_not_found_api_error(
    monkeypatch,
):
    def fake_convert(*, voice_id, text, output_format, request_options=None):
        raise ElevenLabsApiError(
            status_code=404,
            body={
                "detail": {
                    "type": "not_found",
                    "code": "voice_not_found",
                    "message": f"A voice with voice_id '{voice_id}' was not found.",
                    "status": "voice_not_found",
                }
            },
        )

    class FakeClient:
        def __init__(self, *, api_key):
            self.text_to_speech = SimpleNamespace(convert=fake_convert)

    monkeypatch.setattr(elevenlabs_module, "AsyncElevenLabs", FakeClient)

    with pytest.raises(
        elevenlabs_module.ClassCredentialVoiceValidationError,
        match=r"Invalid voice ID provided. Please choose a different voice\.",
    ):
        await elevenlabs_module.synthesize_elevenlabs_voice_sample(
            api_key="elevenlabs-key",
            voice_id="4hMvr6P1cLNnRExeqE1d",
        )


async def test_synthesize_elevenlabs_speech_maps_invalid_voice_id_api_error(
    monkeypatch,
):
    def fake_convert(*, voice_id, text, output_format, request_options=None):
        raise ElevenLabsApiError(
            status_code=400,
            body={
                "detail": {
                    "type": "validation_error",
                    "code": "invalid_voice_id",
                    "message": "The voice ID format is invalid.",
                    "param": "voice_id",
                }
            },
        )

    class FakeClient:
        def __init__(self, *, api_key):
            self.text_to_speech = SimpleNamespace(convert=fake_convert)

    monkeypatch.setattr(elevenlabs_module, "AsyncElevenLabs", FakeClient)

    with pytest.raises(
        elevenlabs_module.ClassCredentialVoiceValidationError,
        match=r"Invalid voice ID provided. Please choose a different voice\.",
    ):
        await elevenlabs_module.synthesize_elevenlabs_speech(
            api_key="elevenlabs-key",
            voice_id="bad-voice",
            text="Narration text",
        )


async def test_synthesize_elevenlabs_speech_maps_non_voice_unprocessable_entity_to_unavailable(
    monkeypatch,
):
    def fake_convert(*, voice_id, text, output_format, request_options=None):
        raise ElevenLabsUnprocessableEntityError(
            body=HttpValidationError(
                detail=[
                    {
                        "loc": ["body", "text"],
                        "msg": "The provided text exceeds the maximum allowed length.",
                        "type": "value_error",
                    }
                ]
            )
        )

    class FakeClient:
        def __init__(self, *, api_key):
            self.text_to_speech = SimpleNamespace(convert=fake_convert)

    monkeypatch.setattr(elevenlabs_module, "AsyncElevenLabs", FakeClient)

    with pytest.raises(
        ClassCredentialValidationUnavailableError,
        match="Unable to generate the ElevenLabs audio right now.",
    ) as exc_info:
        await elevenlabs_module.synthesize_elevenlabs_speech(
            api_key="elevenlabs-key",
            voice_id="voice-123",
            text="Narration text",
        )

    assert exc_info.value.provider == schemas.ClassCredentialProvider.ELEVENLABS


async def test_synthesize_elevenlabs_voice_sample_requests_direct_ogg_opus(monkeypatch):
    seen: dict[str, object] = {}

    async def fake_collect_audio_chunks(_audio_stream) -> bytes:
        return b"ogg-audio"

    def fake_convert(*, voice_id, text, output_format, request_options=None):
        seen["voice_id"] = voice_id
        seen["text"] = text
        seen["output_format"] = output_format
        seen["request_options"] = request_options
        return object()

    class FakeClient:
        def __init__(self, *, api_key):
            seen["api_key"] = api_key
            self.text_to_speech = SimpleNamespace(convert=fake_convert)

    monkeypatch.setattr(elevenlabs_module, "AsyncElevenLabs", FakeClient)
    monkeypatch.setattr(
        elevenlabs_module, "_collect_audio_chunks", fake_collect_audio_chunks
    )

    (
        sample_text,
        content_type,
        audio,
    ) = await elevenlabs_module.synthesize_elevenlabs_voice_sample(
        api_key="elevenlabs-key",
        voice_id="voice-123",
    )

    assert seen == {
        "api_key": "elevenlabs-key",
        "voice_id": "voice-123",
        "text": elevenlabs_module.ELEVENLABS_VOICE_VALIDATION_SAMPLE_TEXT,
        "output_format": "opus_48000_32",
        "request_options": {"timeout_in_seconds": 15},
    }
    assert sample_text == elevenlabs_module.ELEVENLABS_VOICE_VALIDATION_SAMPLE_TEXT
    assert content_type == "audio/ogg"
    assert audio == b"ogg-audio"


@pytest.mark.asyncio
async def test_synthesize_elevenlabs_voice_sample_maps_httpx_timeout_to_unavailable(
    monkeypatch,
):
    def fake_convert(*, voice_id, text, output_format, request_options=None):
        assert request_options == {"timeout_in_seconds": 15}
        raise httpx.ReadTimeout("timed out")

    class FakeClient:
        def __init__(self, *, api_key):
            self.text_to_speech = SimpleNamespace(convert=fake_convert)

    monkeypatch.setattr(elevenlabs_module, "AsyncElevenLabs", FakeClient)

    with pytest.raises(
        ClassCredentialValidationUnavailableError,
        match="Unable to validate the ElevenLabs voice right now.",
    ) as exc_info:
        await elevenlabs_module.synthesize_elevenlabs_voice_sample(
            api_key="elevenlabs-key",
            voice_id="voice-123",
        )

    assert exc_info.value.provider == schemas.ClassCredentialProvider.ELEVENLABS


@pytest.mark.asyncio
async def test_synthesize_elevenlabs_speech_omits_request_options_without_timeout(
    monkeypatch,
):
    seen: dict[str, object] = {}

    async def fake_collect_audio_chunks(_audio_stream) -> bytes:
        return b"ogg-audio"

    def fake_convert(*, voice_id, text, output_format, request_options=None):
        seen["voice_id"] = voice_id
        seen["text"] = text
        seen["output_format"] = output_format
        seen["request_options"] = request_options
        return object()

    class FakeClient:
        def __init__(self, *, api_key):
            seen["api_key"] = api_key
            self.text_to_speech = SimpleNamespace(convert=fake_convert)

    monkeypatch.setattr(elevenlabs_module, "AsyncElevenLabs", FakeClient)
    monkeypatch.setattr(
        elevenlabs_module, "_collect_audio_chunks", fake_collect_audio_chunks
    )

    content_type, audio = await elevenlabs_module.synthesize_elevenlabs_speech(
        api_key="elevenlabs-key",
        voice_id="voice-123",
        text="Narration text",
    )

    assert seen == {
        "api_key": "elevenlabs-key",
        "voice_id": "voice-123",
        "text": "Narration text",
        "output_format": "opus_48000_32",
        "request_options": None,
    }
    assert content_type == "audio/ogg"
    assert audio == b"ogg-audio"


async def test_synthesize_elevenlabs_voice_sample_maps_empty_api_key_to_unavailable():
    with pytest.raises(
        ClassCredentialValidationUnavailableError,
        match="Unable to validate the ElevenLabs voice right now.",
    ) as exc_info:
        await elevenlabs_module.synthesize_elevenlabs_voice_sample(
            api_key="",
            voice_id="voice-123",
        )

    assert exc_info.value.provider == schemas.ClassCredentialProvider.ELEVENLABS


async def test_validate_elevenlabs_api_key_returns_false_for_empty_api_key():
    assert await elevenlabs_module.validate_elevenlabs_api_key("") is False


async def test_validate_elevenlabs_api_key_maps_client_construction_errors_to_unavailable(
    monkeypatch,
):
    class FakeClient:
        def __init__(self, *, api_key):
            raise RuntimeError(f"boom: {api_key}")

    monkeypatch.setattr(elevenlabs_module, "AsyncElevenLabs", FakeClient)

    with pytest.raises(
        ClassCredentialValidationUnavailableError,
        match="Unable to validate the ElevenLabs API key right now.",
    ) as exc_info:
        await elevenlabs_module.validate_elevenlabs_api_key("elevenlabs-key")

    assert exc_info.value.provider == schemas.ClassCredentialProvider.ELEVENLABS


def test_get_elevenlabs_client_creates_new_client_for_each_call(monkeypatch):
    created: list[str] = []

    class FakeClient:
        def __init__(self, *, api_key):
            created.append(api_key)

    monkeypatch.setattr(elevenlabs_module, "AsyncElevenLabs", FakeClient)

    first = elevenlabs_module.get_elevenlabs_client("elevenlabs-key")
    second = elevenlabs_module.get_elevenlabs_client("elevenlabs-key")
    third = elevenlabs_module.get_elevenlabs_client("other-elevenlabs-key")

    assert first is not second
    assert first is not third
    assert created == ["elevenlabs-key", "elevenlabs-key", "other-elevenlabs-key"]
