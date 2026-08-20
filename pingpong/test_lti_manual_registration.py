import json

import pytest

from pingpong.lti.constants import (
    LTI_TOOL_CONFIGURATION_KEY,
    NRPS_CONTEXT_MEMBERSHIP_SCOPE,
)
from pingpong.lti.manual_registration import (
    build_canvas_manual_configuration,
    build_canvas_openid_configuration,
    extract_registration_settings,
)
from pingpong.models import LTIRegistration
from pingpong.schemas import LTIRegistrationMethod


def test_build_canvas_manual_configuration_contains_supported_placements():
    configuration = build_canvas_manual_configuration(
        public_url="https://pingpong.example/",
        provider_id=12,
        sso_field_full_name="Canvas.user.sisIntegrationId",
        show_in_course_navigation=True,
    )

    assert configuration["oidc_initiation_url"] == (
        "https://pingpong.example/api/v1/lti/login"
    )
    assert configuration["target_link_uri"] == (
        "https://pingpong.example/api/v1/lti/launch"
    )
    assert configuration["public_jwk_url"] == (
        "https://pingpong.example/api/v1/lti/.well-known/jwks.json"
    )
    assert configuration["scopes"] == [NRPS_CONTEXT_MEMBERSHIP_SCOPE]
    assert configuration["custom_fields"]["sso_provider_id"] == "12"
    assert configuration["custom_fields"]["sso_value"] == (
        "$Canvas.user.sisIntegrationId"
    )

    placements = configuration["extensions"][0]["settings"]["placements"]
    assert [placement["placement"] for placement in placements] == [
        "course_navigation",
        "editor_button",
        "link_selection",
    ]
    assert placements[0]["message_type"] == "LtiResourceLinkRequest"
    assert placements[0]["default"] == "enabled"
    assert placements[1]["message_type"] == "LtiDeepLinkingRequest"
    assert placements[2]["message_type"] == "LtiDeepLinkingRequest"


def test_build_canvas_openid_configuration_uses_explicit_platform_values():
    configuration = build_canvas_openid_configuration(
        issuer="https://canvas.instructure.com",
        authorization_endpoint="http://canvas.docker/api/lti/authorize_redirect",
        token_endpoint="http://canvas.docker/login/oauth2/token",
        jwks_uri="http://canvas.docker/api/lti/security/jwks",
    )

    assert configuration["issuer"] == "https://canvas.instructure.com"
    assert configuration["authorization_endpoint"].startswith("http://canvas.docker")
    assert configuration["token_endpoint"].startswith("http://canvas.docker")
    assert configuration["jwks_uri"].startswith("http://canvas.docker")


def test_build_canvas_manual_configuration_omits_sso_value_without_sso():
    configuration = build_canvas_manual_configuration(
        public_url="https://pingpong.example",
        provider_id=0,
        sso_field_full_name=None,
        show_in_course_navigation=True,
    )

    assert configuration["custom_fields"]["sso_provider_id"] == "0"
    assert "sso_value" not in configuration["custom_fields"]


def test_extract_registration_settings_from_manual_configuration():
    configuration = build_canvas_manual_configuration(
        public_url="https://pingpong.example",
        provider_id=12,
        sso_field_full_name="Canvas.user.sisSourceId",
        show_in_course_navigation=False,
    )

    settings = extract_registration_settings(json.dumps(configuration))

    assert settings.provider_id == 12
    assert settings.sso_field == "canvas.sisSourceId"
    assert settings.show_in_course_navigation is False


def test_extract_registration_settings_from_dynamic_registration():
    settings = extract_registration_settings(
        json.dumps(
            {
                LTI_TOOL_CONFIGURATION_KEY: {
                    "custom_parameters": {
                        "sso_provider_id": "7",
                        "sso_value": "$Person.sourcedId",
                    },
                    "messages": [
                        {
                            "placements": ["course_navigation"],
                            "https://canvas.instructure.com/lti/course_navigation/default_enabled": False,
                        }
                    ],
                }
            }
        )
    )

    assert settings.provider_id == 7
    assert settings.sso_field == "person.sourcedId"
    assert settings.show_in_course_navigation is False


def test_build_canvas_manual_configuration_rejects_invalid_public_url():
    with pytest.raises(ValueError):
        build_canvas_manual_configuration(
            public_url="not-a-url",
            provider_id=0,
            sso_field_full_name=None,
            show_in_course_navigation=True,
        )


def test_lti_registration_identifies_manual_configuration():
    registration = LTIRegistration(
        registration_data=(
            '{"oidc_initiation_url":"https://example.com/login",'
            '"target_link_uri":"https://example.com/launch","extensions":[]}'
        )
    )

    assert registration.registration_method == LTIRegistrationMethod.MANUAL
