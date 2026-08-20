"""Canvas configuration generation for administrator-created LTI registrations."""

import json
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse

from pingpong.lti.constants import (
    CANVAS_COURSE_NAVIGATION_DEFAULT_ENABLED_KEY,
    CANVAS_COURSE_ID_VARIABLE,
    CANVAS_TERM_NAME_VARIABLE,
    LTI_CUSTOM_SSO_PROVIDER_ID_KEY,
    LTI_CUSTOM_SSO_VALUE_KEY,
    LTI_TOOL_CONFIGURATION_KEY,
    NO_SSO_PROVIDER_ID,
    NRPS_CONTEXT_MEMBERSHIP_SCOPE,
    PINGPONG_LTI_TOOL_VERSION,
)


@dataclass(frozen=True)
class CanvasPlatformPreset:
    id: str
    label: str
    issuer: str
    auth_login_url: str
    auth_token_url: str
    key_set_url: str


DEFAULT_CANVAS_PLATFORM_PRESET_ID = "production"
CANVAS_PLATFORM_PRESETS = (
    CanvasPlatformPreset(
        id="production",
        label="Canvas Hosted: Production",
        issuer="https://canvas.instructure.com",
        auth_login_url="https://sso.canvaslms.com/api/lti/authorize_redirect",
        auth_token_url="https://sso.canvaslms.com/login/oauth2/token",
        key_set_url="https://sso.canvaslms.com/api/lti/security/jwks",
    ),
    CanvasPlatformPreset(
        id="beta",
        label="Canvas Hosted: Beta",
        issuer="https://canvas.beta.instructure.com",
        auth_login_url="https://sso.beta.canvaslms.com/api/lti/authorize_redirect",
        auth_token_url="https://sso.beta.canvaslms.com/login/oauth2/token",
        key_set_url="https://sso.beta.canvaslms.com/api/lti/security/jwks",
    ),
    CanvasPlatformPreset(
        id="test",
        label="Canvas Hosted: Test",
        issuer="https://canvas.test.instructure.com",
        auth_login_url="https://sso.test.canvaslms.com/api/lti/authorize_redirect",
        auth_token_url="https://sso.test.canvaslms.com/login/oauth2/token",
        key_set_url="https://sso.test.canvaslms.com/api/lti/security/jwks",
    ),
)


def build_canvas_manual_configuration(
    *,
    public_url: str,
    provider_id: int,
    sso_field_full_name: str | None,
    show_in_course_navigation: bool,
) -> dict[str, Any]:
    """Build the JSON a Canvas admin pastes into an LTI Developer Key."""
    parsed_public_url = urlparse(public_url)
    if (
        parsed_public_url.scheme not in {"http", "https"}
        or not parsed_public_url.netloc
    ):
        raise ValueError(
            "A valid public URL is required to generate Canvas configuration"
        )

    launch_url = f"{public_url.rstrip('/')}/api/v1/lti/launch"
    login_url = f"{public_url.rstrip('/')}/api/v1/lti/login"
    jwks_url = f"{public_url.rstrip('/')}/api/v1/lti/.well-known/jwks.json"
    icon_url = f"{public_url.rstrip('/')}/pingpong_icon_2x.png"

    shared_custom_fields = {
        "platform": "canvas",
        "pingpong_lti_tool_version": PINGPONG_LTI_TOOL_VERSION,
        LTI_CUSTOM_SSO_PROVIDER_ID_KEY: str(provider_id),
    }
    if provider_id != NO_SSO_PROVIDER_ID and sso_field_full_name:
        shared_custom_fields[LTI_CUSTOM_SSO_VALUE_KEY] = f"${sso_field_full_name}"
    course_custom_fields = {
        "placement": "course_navigation",
        "canvas_course_id": CANVAS_COURSE_ID_VARIABLE,
        "canvas_term_name": CANVAS_TERM_NAME_VARIABLE,
    }

    return {
        "title": "PingPong",
        "description": "A platform carefully designed for AI-driven learning.",
        "oidc_initiation_url": login_url,
        "target_link_uri": launch_url,
        "scopes": [NRPS_CONTEXT_MEMBERSHIP_SCOPE],
        "public_jwk_url": jwks_url,
        "custom_fields": shared_custom_fields,
        "extensions": [
            {
                "domain": parsed_public_url.netloc,
                "tool_id": "pingpong",
                "platform": "canvas.instructure.com",
                "privacy_level": "public",
                "settings": {
                    "text": "PingPong",
                    "icon_url": icon_url,
                    "placements": [
                        {
                            "text": "PingPong",
                            "placement": "course_navigation",
                            "message_type": "LtiResourceLinkRequest",
                            "target_link_uri": launch_url,
                            "default": (
                                "enabled" if show_in_course_navigation else "disabled"
                            ),
                            "display_type": "full_width_in_context",
                            "visibility": "members",
                            "custom_fields": course_custom_fields,
                        },
                        {
                            "text": "PingPong",
                            "placement": "editor_button",
                            "message_type": "LtiDeepLinkingRequest",
                            "target_link_uri": launch_url,
                            "icon_url": icon_url,
                            "selection_width": 1000,
                            "selection_height": 1600,
                            "visibility": "admins",
                            "custom_fields": {
                                **course_custom_fields,
                                "placement": "editor_button",
                            },
                        },
                        {
                            "text": "PingPong",
                            "placement": "link_selection",
                            "message_type": "LtiDeepLinkingRequest",
                            "target_link_uri": launch_url,
                            "selection_width": 900,
                            "selection_height": 850,
                            "visibility": "admins",
                            "custom_fields": {
                                **course_custom_fields,
                                "placement": "link_selection",
                            },
                        },
                    ],
                },
            }
        ],
    }


def build_canvas_openid_configuration(
    *,
    issuer: str,
    authorization_endpoint: str,
    token_endpoint: str,
    jwks_uri: str,
) -> dict[str, Any]:
    return {
        "issuer": issuer,
        "authorization_endpoint": authorization_endpoint,
        "token_endpoint": token_endpoint,
        "jwks_uri": jwks_uri,
        "id_token_signing_alg_values_supported": ["RS256"],
        "subject_types_supported": ["public"],
        "scopes_supported": ["openid", NRPS_CONTEXT_MEMBERSHIP_SCOPE],
    }


@dataclass(frozen=True)
class CopiedRegistrationSettings:
    provider_id: int
    sso_field: str | None
    show_in_course_navigation: bool


def _get_dict(value: object) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _parse_provider_id(value: object) -> int:
    try:
        provider_id = int(value) if isinstance(value, (str, int)) else 0
    except ValueError:
        return 0
    return provider_id if provider_id >= 0 else 0


def _parse_sso_field(value: object) -> str | None:
    if not isinstance(value, str) or not value.startswith("$"):
        return None
    full_name = value[1:]
    fields = {
        "Canvas.user.sisIntegrationId": "canvas.sisIntegrationId",
        "Canvas.user.sisSourceId": "canvas.sisSourceId",
        "Person.sourcedId": "person.sourcedId",
    }
    return fields.get(full_name)


def extract_registration_settings(
    registration_data: str | None,
) -> CopiedRegistrationSettings:
    """Normalize reusable settings from manual or Dynamic Registration data."""
    try:
        payload = json.loads(registration_data or "{}")
    except (json.JSONDecodeError, TypeError):
        payload = {}
    payload = _get_dict(payload)

    if "oidc_initiation_url" in payload:
        custom_fields = _get_dict(payload.get("custom_fields"))
        provider_id = _parse_provider_id(
            custom_fields.get(LTI_CUSTOM_SSO_PROVIDER_ID_KEY)
        )
        sso_field = _parse_sso_field(custom_fields.get(LTI_CUSTOM_SSO_VALUE_KEY))
        show_in_course_navigation = True
        extensions = payload.get("extensions")
        if isinstance(extensions, list):
            for extension in extensions:
                settings = _get_dict(_get_dict(extension).get("settings"))
                placements = settings.get("placements")
                if not isinstance(placements, list):
                    continue
                for placement in placements:
                    placement = _get_dict(placement)
                    if placement.get("placement") == "course_navigation":
                        show_in_course_navigation = (
                            placement.get("default") != "disabled"
                        )
                        break
        return CopiedRegistrationSettings(
            provider_id=provider_id,
            sso_field=sso_field,
            show_in_course_navigation=show_in_course_navigation,
        )

    # Dynamic Registration responses store the same values in the IMS tool
    # configuration object and its course_navigation message.
    tool_configuration = _get_dict(payload.get(LTI_TOOL_CONFIGURATION_KEY))
    custom_parameters = _get_dict(tool_configuration.get("custom_parameters"))
    provider_id = _parse_provider_id(
        custom_parameters.get(LTI_CUSTOM_SSO_PROVIDER_ID_KEY)
    )
    sso_field = _parse_sso_field(custom_parameters.get(LTI_CUSTOM_SSO_VALUE_KEY))
    show_in_course_navigation = True
    messages = tool_configuration.get("messages")
    if isinstance(messages, list):
        for message in messages:
            message = _get_dict(message)
            placements = message.get("placements")
            if isinstance(placements, list) and "course_navigation" in placements:
                show_in_course_navigation = bool(
                    message.get(
                        CANVAS_COURSE_NAVIGATION_DEFAULT_ENABLED_KEY,
                        True,
                    )
                )
                break
    return CopiedRegistrationSettings(
        provider_id=provider_id,
        sso_field=sso_field,
        show_in_course_navigation=show_in_course_navigation,
    )
