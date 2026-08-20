from datetime import datetime, timezone
from types import SimpleNamespace
import importlib
import json

import pytest
from fastapi import HTTPException
from starlette.datastructures import State

schemas = importlib.import_module("pingpong.schemas")
server_module = importlib.import_module("pingpong.server")


async def _async_return(value):
    return value


def _make_request(db="db", user_id=1):
    return SimpleNamespace(
        state=State(
            {"db": db, "session": SimpleNamespace(user=SimpleNamespace(id=user_id))}
        )
    )


def _make_registration(
    *,
    id=1,
    issuer="issuer",
    client_id="client",
    auth_login_url="https://example.com/auth",
    auth_token_url="https://example.com/token",
    key_set_url="https://example.com/jwks",
    token_algorithm=schemas.LTITokenAlgorithm.RS256,
    lms_platform=schemas.LMSPlatform.CANVAS,
    canvas_account_name=None,
    admin_name=None,
    admin_email=None,
    friendly_name=None,
    enabled=False,
    review_status=schemas.LTIRegistrationReviewStatus.PENDING,
    registration_method=schemas.LTIRegistrationMethod.DYNAMIC,
    internal_notes=None,
    review_notes=None,
    review_by=None,
    institutions=None,
    openid_configuration=None,
    registration_data=None,
    created=None,
    updated=None,
    lti_classes=None,
):
    return SimpleNamespace(
        id=id,
        issuer=issuer,
        client_id=client_id,
        auth_login_url=auth_login_url,
        auth_token_url=auth_token_url,
        key_set_url=key_set_url,
        token_algorithm=token_algorithm,
        lms_platform=lms_platform,
        canvas_account_name=canvas_account_name,
        admin_name=admin_name,
        admin_email=admin_email,
        friendly_name=friendly_name,
        enabled=enabled,
        review_status=review_status,
        registration_method=registration_method,
        internal_notes=internal_notes,
        review_notes=review_notes,
        review_by=review_by,
        institutions=institutions or [],
        openid_configuration=openid_configuration,
        registration_data=registration_data,
        created=created or datetime.now(timezone.utc),
        updated=updated,
        lti_classes=lti_classes,
    )


@pytest.mark.asyncio
async def test_list_lti_registrations(monkeypatch):
    registrations = [_make_registration(id=1), _make_registration(id=2)]
    monkeypatch.setattr(
        server_module.models.LTIRegistration,
        "get_all",
        lambda db: _async_return(registrations),
    )

    request = _make_request()
    result = await server_module.list_lti_registrations(request)

    assert result["registrations"] == registrations


@pytest.mark.asyncio
async def test_create_manual_lti_registration(monkeypatch):
    created = {}
    registration = _make_registration(
        client_id=None,
        registration_method=schemas.LTIRegistrationMethod.MANUAL,
        lti_classes=[],
    )

    monkeypatch.setattr(
        server_module.models.Institution,
        "all_have_default_api_key",
        lambda db, institution_ids: _async_return(True),
    )

    async def _create(db, data, institution_ids):
        created["data"] = data
        created["institution_ids"] = institution_ids
        registration.registration_data = data["registration_data"]
        registration.openid_configuration = data["openid_configuration"]
        return registration

    monkeypatch.setattr(server_module.models.LTIRegistration, "create", _create)
    monkeypatch.setattr(
        server_module.models.LTIRegistration,
        "get_by_id",
        lambda db, registration_id: _async_return(registration),
    )
    monkeypatch.setattr(
        server_module,
        "config",
        SimpleNamespace(
            public_url="https://pingpong.example",
            url=lambda path: f"https://pingpong.example{path}",
        ),
    )

    body = schemas.CreateManualLTIRegistration(
        name="Example Canvas",
        admin_name="Canvas Admin",
        admin_email="admin@example.edu",
        issuer="https://canvas.instructure.com",
        auth_login_url="http://canvas.docker/api/lti/authorize_redirect",
        auth_token_url="http://canvas.docker/login/oauth2/token",
        key_set_url="http://canvas.docker/api/lti/security/jwks",
        provider_id=0,
        institution_ids=[3],
        show_in_course_navigation=False,
    )
    result = await server_module.create_manual_lti_registration(body, _make_request())

    assert result.client_id is None
    assert created["institution_ids"] == [3]
    assert created["data"]["issuer"] == "https://canvas.instructure.com"
    assert created["data"]["auth_login_url"] == (
        "http://canvas.docker/api/lti/authorize_redirect"
    )
    openid_configuration = json.loads(created["data"]["openid_configuration"])
    assert openid_configuration["token_endpoint"] == (
        "http://canvas.docker/login/oauth2/token"
    )
    config = json.loads(created["data"]["registration_data"])
    assert config["oidc_initiation_url"] == (
        "https://pingpong.example/api/v1/lti/login"
    )
    assert config["extensions"][0]["settings"]["placements"][0]["default"] == (
        "disabled"
    )


@pytest.mark.asyncio
async def test_get_canvas_platform_presets():
    result = await server_module.get_canvas_platform_presets()
    presets = schemas.CanvasPlatformPresets.model_validate(result)

    assert presets.default_preset_id == server_module.DEFAULT_CANVAS_PLATFORM_PRESET_ID
    assert presets.presets
    assert presets.default_preset_id in {preset.id for preset in presets.presets}
    assert "custom" not in {preset.id for preset in presets.presets}


@pytest.mark.asyncio
async def test_get_lti_registration_not_found(monkeypatch):
    monkeypatch.setattr(
        server_module.models.LTIRegistration,
        "get_by_id",
        lambda db, registration_id: _async_return(None),
    )

    request = _make_request()
    with pytest.raises(HTTPException) as excinfo:
        await server_module.get_lti_registration(1, request)

    assert excinfo.value.status_code == 404


@pytest.mark.asyncio
async def test_get_lti_registration_detail(monkeypatch):
    registration = _make_registration(
        registration_method=schemas.LTIRegistrationMethod.MANUAL,
        registration_data=json.dumps(
            {
                "oidc_initiation_url": "https://pingpong.example/api/v1/lti/login",
                "target_link_uri": "https://pingpong.example/api/v1/lti/launch",
                "extensions": [],
            }
        ),
        lti_classes=[object(), object()],
    )
    monkeypatch.setattr(
        server_module.models.LTIRegistration,
        "get_by_id",
        lambda db, registration_id: _async_return(registration),
    )

    request = _make_request()
    result = await server_module.get_lti_registration(1, request)

    assert result.id == registration.id
    assert result.lti_classes_count == 2
    assert result.manual_configuration_url == (
        "http://localhost:5173/api/v1/lti/registrations/1/configuration.json"
    )


@pytest.mark.asyncio
async def test_get_public_manual_lti_configuration_excludes_launch_metadata(
    monkeypatch,
):
    registration = _make_registration(
        registration_method=schemas.LTIRegistrationMethod.MANUAL,
        registration_data=json.dumps(
            {
                "title": "PingPong",
                "oidc_initiation_url": "https://pingpong.example/api/v1/lti/login",
                "target_link_uri": "https://pingpong.example/api/v1/lti/launch",
                "extensions": [],
                "deployment_id": "deployment-from-launch",
            }
        ),
    )
    monkeypatch.setattr(
        server_module.models.LTIRegistration,
        "get_by_id",
        lambda db, registration_id: _async_return(registration),
    )

    response = await server_module.get_public_manual_lti_configuration(
        1, _make_request()
    )

    assert response.status_code == 200
    assert json.loads(response.body) == {
        "title": "PingPong",
        "oidc_initiation_url": "https://pingpong.example/api/v1/lti/login",
        "target_link_uri": "https://pingpong.example/api/v1/lti/launch",
        "extensions": [],
    }
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.asyncio
async def test_get_manual_lti_registration_template_normalizes_copyable_settings(
    monkeypatch,
):
    registration = _make_registration(
        id=42,
        issuer="https://canvas.instructure.com",
        client_id="must-not-be-copied",
        friendly_name="Existing Canvas",
        admin_name="Canvas Admin",
        admin_email="admin@example.edu",
        registration_method=schemas.LTIRegistrationMethod.MANUAL,
        institutions=[SimpleNamespace(id=3), SimpleNamespace(id=8)],
        registration_data=json.dumps(
            {
                "oidc_initiation_url": "https://pingpong.example/api/v1/lti/login",
                "custom_fields": {
                    "sso_provider_id": "7",
                    "sso_value": "$Canvas.user.sisSourceId",
                },
                "extensions": [
                    {
                        "settings": {
                            "placements": [
                                {
                                    "placement": "course_navigation",
                                    "default": "disabled",
                                }
                            ]
                        }
                    }
                ],
            }
        ),
    )
    monkeypatch.setattr(
        server_module.models.LTIRegistration,
        "get_by_id",
        lambda db, registration_id: _async_return(registration),
    )

    result = await server_module.get_manual_lti_registration_template(
        42, _make_request()
    )

    assert result.name == "Existing Canvas"
    assert result.provider_id == 7
    assert result.sso_field == "canvas.sisSourceId"
    assert result.institution_ids == [3, 8]
    assert result.show_in_course_navigation is False
    assert not hasattr(result, "client_id")


@pytest.mark.asyncio
async def test_update_lti_registration_not_found(monkeypatch):
    monkeypatch.setattr(
        server_module.models.LTIRegistration,
        "update",
        lambda *args, **kwargs: _async_return(None),
    )

    request = _make_request(user_id=5)
    body = schemas.UpdateLTIRegistration(friendly_name="Name")
    with pytest.raises(HTTPException) as excinfo:
        await server_module.update_lti_registration(1, body, request)

    assert excinfo.value.status_code == 404


@pytest.mark.asyncio
async def test_update_lti_registration_success(monkeypatch):
    registration = _make_registration()
    called = {}

    async def _update(db, registration_id, data, reviewer_id=None):
        called["data"] = data
        called["reviewer_id"] = reviewer_id
        return registration

    monkeypatch.setattr(server_module.models.LTIRegistration, "update", _update)

    request = _make_request(user_id=9)
    body = schemas.UpdateLTIRegistration(friendly_name="New Name")
    result = await server_module.update_lti_registration(1, body, request)

    assert result is registration
    assert called["data"] == {"friendly_name": "New Name"}
    assert called["reviewer_id"] == 9


@pytest.mark.asyncio
async def test_set_lti_registration_status_not_found(monkeypatch):
    monkeypatch.setattr(
        server_module.models.LTIRegistration,
        "get_by_id",
        lambda db, registration_id: _async_return(None),
    )

    request = _make_request()
    body = schemas.SetLTIRegistrationStatus(
        review_status=schemas.LTIRegistrationReviewStatus.APPROVED
    )
    with pytest.raises(HTTPException) as excinfo:
        await server_module.set_lti_registration_status(1, body, request)

    assert excinfo.value.status_code == 404


@pytest.mark.asyncio
async def test_set_lti_registration_status_requires_client_id_for_approval(monkeypatch):
    current = _make_registration(client_id=None)
    monkeypatch.setattr(
        server_module.models.LTIRegistration,
        "get_by_id",
        lambda db, registration_id: _async_return(current),
    )

    with pytest.raises(HTTPException) as excinfo:
        await server_module.set_lti_registration_status(
            1,
            schemas.SetLTIRegistrationStatus(
                review_status=schemas.LTIRegistrationReviewStatus.APPROVED
            ),
            _make_request(),
        )

    assert excinfo.value.status_code == 400
    assert excinfo.value.detail == "A Canvas client ID is required before approval"


@pytest.mark.asyncio
async def test_accept_manual_lti_registration(monkeypatch):
    registration = _make_registration(
        client_id=None,
        registration_method=schemas.LTIRegistrationMethod.MANUAL,
    )
    updated = _make_registration(
        client_id="12345",
        registration_method=schemas.LTIRegistrationMethod.MANUAL,
        review_status=schemas.LTIRegistrationReviewStatus.APPROVED,
        enabled=True,
    )
    called = {}
    monkeypatch.setattr(
        server_module.models.LTIRegistration,
        "get_by_id",
        lambda db, registration_id: _async_return(registration),
    )
    monkeypatch.setattr(
        server_module.models.LTIRegistration,
        "get_by_issuer_and_client_id",
        lambda db, issuer, client_id: _async_return(None),
    )

    async def _update(db, registration_id, data, reviewer_id=None):
        called["data"] = data
        called["reviewer_id"] = reviewer_id
        return updated

    monkeypatch.setattr(server_module.models.LTIRegistration, "update", _update)

    result = await server_module.accept_manual_lti_registration(
        1,
        schemas.AcceptManualLTIRegistration(client_id=" 12345 "),
        _make_request(user_id=19),
    )

    assert result is updated
    assert called == {
        "data": {
            "client_id": "12345",
            "review_status": schemas.LTIRegistrationReviewStatus.APPROVED,
            "enabled": True,
        },
        "reviewer_id": 19,
    }


@pytest.mark.asyncio
async def test_accept_manual_lti_registration_rejects_duplicate_client_id(monkeypatch):
    registration = _make_registration(
        id=1,
        client_id=None,
        registration_method=schemas.LTIRegistrationMethod.MANUAL,
    )
    existing = _make_registration(id=2, client_id="12345")
    monkeypatch.setattr(
        server_module.models.LTIRegistration,
        "get_by_id",
        lambda db, registration_id: _async_return(registration),
    )
    monkeypatch.setattr(
        server_module.models.LTIRegistration,
        "get_by_issuer_and_client_id",
        lambda db, issuer, client_id: _async_return(existing),
    )

    with pytest.raises(HTTPException) as excinfo:
        await server_module.accept_manual_lti_registration(
            1,
            schemas.AcceptManualLTIRegistration(client_id="12345"),
            _make_request(),
        )

    assert excinfo.value.status_code == 409


@pytest.mark.asyncio
async def test_set_lti_registration_status_approved_sends_email(monkeypatch):
    current = _make_registration(
        review_status=schemas.LTIRegistrationReviewStatus.PENDING,
        admin_email="admin@example.com",
        admin_name="Admin",
        friendly_name="Friendly",
    )
    updated = _make_registration(
        review_status=schemas.LTIRegistrationReviewStatus.APPROVED,
        enabled=True,
        admin_email="admin@example.com",
        admin_name="Admin",
        friendly_name="Friendly",
    )
    called = {}

    monkeypatch.setattr(
        server_module.models.LTIRegistration,
        "get_by_id",
        lambda db, registration_id: _async_return(current),
    )

    async def _update(db, registration_id, data, reviewer_id=None):
        called["data"] = data
        called["reviewer_id"] = reviewer_id
        return updated

    monkeypatch.setattr(server_module.models.LTIRegistration, "update", _update)

    async def _send_approved(sender, admin_email, admin_name, integration_name):
        called["approved"] = (sender, admin_email, admin_name, integration_name)

    monkeypatch.setattr(server_module, "send_lti_registration_approved", _send_approved)
    monkeypatch.setattr(
        server_module,
        "config",
        SimpleNamespace(email=SimpleNamespace(sender="sender@example.com")),
    )

    request = _make_request(user_id=7)
    body = schemas.SetLTIRegistrationStatus(
        review_status=schemas.LTIRegistrationReviewStatus.APPROVED
    )
    result = await server_module.set_lti_registration_status(1, body, request)

    assert result is updated
    assert called["data"]["enabled"] is True
    assert called["reviewer_id"] == 7
    assert called["approved"][1] == "admin@example.com"


@pytest.mark.asyncio
async def test_set_lti_registration_status_rejected_sends_email(monkeypatch):
    current = _make_registration(
        review_status=schemas.LTIRegistrationReviewStatus.APPROVED,
        admin_email="admin@example.com",
        review_notes="Notes",
        canvas_account_name="Canvas",
    )
    updated = _make_registration(
        review_status=schemas.LTIRegistrationReviewStatus.REJECTED,
        enabled=False,
        admin_email="admin@example.com",
        review_notes="Notes",
        canvas_account_name="Canvas",
    )
    called = {}

    monkeypatch.setattr(
        server_module.models.LTIRegistration,
        "get_by_id",
        lambda db, registration_id: _async_return(current),
    )
    monkeypatch.setattr(
        server_module.models.LTIRegistration,
        "update",
        lambda *args, **kwargs: _async_return(updated),
    )

    async def _send_rejected(
        sender, admin_email, admin_name, integration_name, review_notes
    ):
        called["rejected"] = (
            sender,
            admin_email,
            admin_name,
            integration_name,
            review_notes,
        )

    monkeypatch.setattr(server_module, "send_lti_registration_rejected", _send_rejected)
    monkeypatch.setattr(
        server_module,
        "config",
        SimpleNamespace(email=SimpleNamespace(sender="sender@example.com")),
    )

    request = _make_request()
    body = schemas.SetLTIRegistrationStatus(
        review_status=schemas.LTIRegistrationReviewStatus.REJECTED
    )
    result = await server_module.set_lti_registration_status(1, body, request)

    assert result is updated
    assert called["rejected"][1] == "admin@example.com"
    assert called["rejected"][4] == "Notes"


@pytest.mark.asyncio
async def test_set_lti_registration_status_no_email_on_same_status(monkeypatch):
    current = _make_registration(
        review_status=schemas.LTIRegistrationReviewStatus.PENDING,
        admin_email="admin@example.com",
    )
    monkeypatch.setattr(
        server_module.models.LTIRegistration,
        "get_by_id",
        lambda db, registration_id: _async_return(current),
    )
    monkeypatch.setattr(
        server_module.models.LTIRegistration,
        "update",
        lambda *args, **kwargs: _async_return(current),
    )

    called = {}

    async def _send_approved(*args, **kwargs):
        called["approved"] = True

    monkeypatch.setattr(server_module, "send_lti_registration_approved", _send_approved)
    monkeypatch.setattr(
        server_module,
        "config",
        SimpleNamespace(email=SimpleNamespace(sender="sender@example.com")),
    )

    request = _make_request()
    body = schemas.SetLTIRegistrationStatus(
        review_status=schemas.LTIRegistrationReviewStatus.PENDING
    )
    result = await server_module.set_lti_registration_status(1, body, request)

    assert result is current
    assert "approved" not in called


@pytest.mark.asyncio
async def test_set_lti_registration_enabled_not_found(monkeypatch):
    monkeypatch.setattr(
        server_module.models.LTIRegistration,
        "get_by_id",
        lambda db, registration_id: _async_return(None),
    )

    request = _make_request()
    body = schemas.SetLTIRegistrationEnabled(enabled=True)
    with pytest.raises(HTTPException) as excinfo:
        await server_module.set_lti_registration_enabled(1, body, request)

    assert excinfo.value.status_code == 404


@pytest.mark.asyncio
async def test_set_lti_registration_enabled_requires_approved(monkeypatch):
    registration = _make_registration(
        review_status=schemas.LTIRegistrationReviewStatus.PENDING
    )
    monkeypatch.setattr(
        server_module.models.LTIRegistration,
        "get_by_id",
        lambda db, registration_id: _async_return(registration),
    )

    request = _make_request()
    body = schemas.SetLTIRegistrationEnabled(enabled=True)
    with pytest.raises(HTTPException) as excinfo:
        await server_module.set_lti_registration_enabled(1, body, request)

    assert excinfo.value.status_code == 400


@pytest.mark.asyncio
async def test_set_lti_registration_enabled_success(monkeypatch):
    registration = _make_registration(
        review_status=schemas.LTIRegistrationReviewStatus.APPROVED
    )
    monkeypatch.setattr(
        server_module.models.LTIRegistration,
        "get_by_id",
        lambda db, registration_id: _async_return(registration),
    )
    monkeypatch.setattr(
        server_module.models.LTIRegistration,
        "set_enabled",
        lambda db, registration_id, enabled: _async_return(registration),
    )

    request = _make_request()
    body = schemas.SetLTIRegistrationEnabled(enabled=True)
    result = await server_module.set_lti_registration_enabled(1, body, request)

    assert result is registration


@pytest.mark.asyncio
async def test_set_lti_registration_institutions_not_found(monkeypatch):
    monkeypatch.setattr(
        server_module.models.LTIRegistration,
        "set_institutions",
        lambda *args, **kwargs: _async_return(None),
    )

    request = _make_request()
    body = schemas.SetLTIRegistrationInstitutions(institution_ids=[1, 2])
    with pytest.raises(HTTPException) as excinfo:
        await server_module.set_lti_registration_institutions(1, body, request)

    assert excinfo.value.status_code == 404


@pytest.mark.asyncio
async def test_set_lti_registration_institutions_success(monkeypatch):
    registration = _make_registration()
    monkeypatch.setattr(
        server_module.models.LTIRegistration,
        "set_institutions",
        lambda *args, **kwargs: _async_return(registration),
    )

    request = _make_request()
    body = schemas.SetLTIRegistrationInstitutions(institution_ids=[1, 2])
    result = await server_module.set_lti_registration_institutions(1, body, request)

    assert result is registration


@pytest.mark.asyncio
async def test_get_institutions_with_default_api_key(monkeypatch):
    institutions = [SimpleNamespace(id=1, name="A")]
    monkeypatch.setattr(
        server_module.models.Institution,
        "get_all_with_default_api_key",
        lambda db: _async_return(institutions),
    )

    request = _make_request()
    result = await server_module.get_institutions_with_default_api_key(request)

    assert result["institutions"] == institutions
