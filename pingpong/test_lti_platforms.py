"""Unit tests for pingpong.lti.platforms handlers."""

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

import pingpong.config as config_module
from pingpong.lti.constants import (
    CANVAS_ACCOUNT_LTI_GUID_KEY,
    CANVAS_ACCOUNT_NAME_KEY,
    CANVAS_MESSAGE_PLACEMENT,
    LTI_CLAIM_CONTEXT_KEY,
    LTI_CLAIM_NRPS_KEY,
    LTI_TOOL_CONFIGURATION_KEY,
    MESSAGE_TYPE,
)
from pingpong.lti.platforms import get_handler
from pingpong.lti.platforms.canvas import CanvasPlatformHandler
from pingpong.lti.platforms.harvard_lxp import HarvardLxpPlatformHandler
from pingpong.lti.schemas import LTIRegisterRequest
from pingpong.schemas import LMSPlatform


@pytest.fixture(autouse=True)
def _patch_lti_security_config(monkeypatch):
    real_config = config_module.config
    allow_deny = SimpleNamespace(allow=["*"], deny=[])
    url_security = SimpleNamespace(
        allow_http_in_development=True,
        allow_redirects=True,
        hosts=allow_deny,
        paths=allow_deny,
    )
    security = SimpleNamespace(
        allow_http_in_development=True,
        allow_redirects=True,
        hosts=allow_deny,
        paths=allow_deny,
        authorization_endpoint=url_security,
        jwks_uri=url_security,
        names_and_role_endpoint=url_security,
        openid_configuration=url_security,
        registration_endpoint=url_security,
        token_endpoint=url_security,
    )
    lti = SimpleNamespace(security=security)
    patched_config = SimpleNamespace(
        lti=lti,
        development=False,
        url=real_config.url,
        public_url=real_config.public_url,
    )
    monkeypatch.setattr(config_module, "config", patched_config)


LXP_SAMPLE_CLAIMS = {
    LTI_CLAIM_CONTEXT_KEY: {
        "id": "39b59151-4bcb-4b17-a4f1-c4c8669a6a80",
        "type": ["CourseSection"],
        "title": "Learning Experience Showcase",
        "label": "LES-39b59151-4bcb-4b17-a4f1-c4c8669a6a80",
    },
    LTI_CLAIM_NRPS_KEY: {
        "context_memberships_url": (
            "https://example.com/api/v1/lti/nrps/memberships/"
            "39b59151-4bcb-4b17-a4f1-c4c8669a6a80?page=1"
        ),
        "service_version": "2.0",
    },
}


def _lxp_register_request(provider_id: int = 0) -> LTIRegisterRequest:
    return LTIRegisterRequest(
        name="PingPong",
        admin_name="Admin",
        admin_email="admin@example.com",
        provider_id=provider_id,
        sso_field=None,
        openid_configuration="https://platform.example.com/.well-known/openid",
        registration_token="token",
        institution_ids=[1],
    )


def _base_tool_config() -> dict:
    return {
        "application_type": "web",
        "client_name": "PingPong",
        LTI_TOOL_CONFIGURATION_KEY: {
            "domain": "tool.example.com",
            "target_link_uri": "https://tool.example.com/api/v1/lti/launch",
            "description": "desc",
            "claims": ["sub", "iss"],
        },
    }


# --- Factory ---


def test_get_handler_returns_canvas_handler():
    h = get_handler(LMSPlatform.CANVAS)
    assert isinstance(h, CanvasPlatformHandler)
    assert h.platform == LMSPlatform.CANVAS


def test_get_handler_returns_harvard_lxp_handler():
    h = get_handler(LMSPlatform.HARVARD_LXP)
    assert isinstance(h, HarvardLxpPlatformHandler)
    assert h.platform == LMSPlatform.HARVARD_LXP


# --- CanvasPlatformHandler ---


def test_canvas_validate_platform_config_rejects_missing_course_navigation():
    handler = CanvasPlatformHandler()
    with pytest.raises(HTTPException) as excinfo:
        handler.validate_platform_config(
            {},
            [{"type": MESSAGE_TYPE, "placements": ["https://other.example/placement"]}],
        )
    assert excinfo.value.status_code == 400
    assert "Canvas course navigation" in excinfo.value.detail


def test_canvas_validate_platform_config_accepts_course_navigation():
    handler = CanvasPlatformHandler()
    handler.validate_platform_config(
        {},
        [{"type": MESSAGE_TYPE, "placements": [CANVAS_MESSAGE_PLACEMENT]}],
    )


def test_canvas_extract_registration_fields():
    handler = CanvasPlatformHandler()
    platform_config = {
        CANVAS_ACCOUNT_NAME_KEY: "Harvard Canvas",
        CANVAS_ACCOUNT_LTI_GUID_KEY: "guid-123",
    }
    assert handler.extract_registration_fields(platform_config) == {
        "canvas_account_name": "Harvard Canvas",
        "canvas_account_lti_guid": "guid-123",
    }


def test_canvas_build_tool_registration_payload_includes_vendor_extensions():
    handler = CanvasPlatformHandler()
    data = LTIRegisterRequest(
        name="PingPong",
        admin_name="Admin",
        admin_email="admin@example.com",
        provider_id=0,
        sso_field=None,
        openid_configuration="https://platform.example.com/.well-known/openid",
        registration_token="token",
        institution_ids=[1],
        show_in_course_navigation=True,
    )
    payload = handler.build_tool_registration_payload(
        base_tool_config=_base_tool_config(),
        data=data,
        sso_field_full_name=None,
    )
    tool = payload[LTI_TOOL_CONFIGURATION_KEY]
    assert tool["custom_parameters"]["platform"] == "canvas"
    assert tool["custom_parameters"]["sso_provider_id"] == "0"
    assert tool["custom_parameters"]["sso_value"] == ""
    assert tool["https://canvas.instructure.com/lti/vendor"] == (
        "Computational Policy Lab"
    )
    message = tool["messages"][0]
    assert message["placements"] == ["course_navigation"]
    assert message["custom_parameters"]["canvas_course_id"] == "$Canvas.course.id"
    assert message["custom_parameters"]["canvas_term_name"] == "$Canvas.term.name"
    assert (
        message["https://canvas.instructure.com/lti/course_navigation/default_enabled"]
        is True
    )


def test_canvas_extract_course_id_rejects_placeholder():
    handler = CanvasPlatformHandler()
    with pytest.raises(HTTPException):
        handler.extract_course_id({}, {"canvas_course_id": "$Canvas.course.id"})
    with pytest.raises(HTTPException):
        handler.extract_course_id({}, {})
    assert handler.extract_course_id({}, {"canvas_course_id": "abc123"}) == "abc123"


def test_canvas_extract_course_metadata_reads_all_fields():
    handler = CanvasPlatformHandler()
    claims = {
        LTI_CLAIM_CONTEXT_KEY: {"label": "CS50", "title": "Intro to CS"},
        LTI_CLAIM_NRPS_KEY: {"context_memberships_url": "https://example.com/nrps"},
    }
    code, name, term, url = handler.extract_course_metadata(
        claims, {"canvas_term_name": "Fall 2026"}
    )
    assert code == "CS50"
    assert name == "Intro to CS"
    assert term == "Fall 2026"
    assert url == "https://example.com/nrps"


# --- HarvardLxpPlatformHandler ---


def test_lxp_validate_platform_config_is_permissive():
    handler = HarvardLxpPlatformHandler()
    # LXP has no extra platform-config requirements beyond LtiResourceLinkRequest
    # which the caller already asserts.
    handler.validate_platform_config({}, [{"type": MESSAGE_TYPE}])


def test_lxp_validate_registration_request_rejects_sso():
    handler = HarvardLxpPlatformHandler()
    with pytest.raises(HTTPException) as excinfo:
        handler.validate_registration_request(_lxp_register_request(provider_id=5))
    assert excinfo.value.status_code == 400
    assert "SSO-linked" in excinfo.value.detail


def test_lxp_validate_registration_request_allows_no_sso():
    handler = HarvardLxpPlatformHandler()
    handler.validate_registration_request(_lxp_register_request(provider_id=0))


def test_lxp_extract_registration_fields_is_empty():
    handler = HarvardLxpPlatformHandler()
    assert handler.extract_registration_fields({"anything": "here"}) == {}


def test_lxp_build_tool_registration_payload_omits_canvas_extensions():
    handler = HarvardLxpPlatformHandler()
    payload = handler.build_tool_registration_payload(
        base_tool_config=_base_tool_config(),
        data=_lxp_register_request(),
        sso_field_full_name=None,
    )
    tool = payload[LTI_TOOL_CONFIGURATION_KEY]
    assert tool["custom_parameters"] == {
        "platform": "harvard_lxp",
        "pingpong_lti_tool_version": "2.0",
    }
    assert "https://canvas.instructure.com/lti/vendor" not in tool
    as_json = str(payload)
    assert "$Canvas" not in as_json
    assert "canvas_course_id" not in as_json
    assert "canvas_term_name" not in as_json
    message = tool["messages"][0]
    assert message["type"] == MESSAGE_TYPE
    assert "placements" not in message
    assert "custom_parameters" not in message


def test_lxp_extract_course_id_reads_context_id():
    handler = HarvardLxpPlatformHandler()
    course_id = handler.extract_course_id(LXP_SAMPLE_CLAIMS, {})
    assert course_id == "39b59151-4bcb-4b17-a4f1-c4c8669a6a80"


def test_lxp_extract_course_id_rejects_missing_context_id():
    handler = HarvardLxpPlatformHandler()
    with pytest.raises(HTTPException) as excinfo:
        handler.extract_course_id({LTI_CLAIM_CONTEXT_KEY: {"title": "Foo"}}, {})
    assert excinfo.value.status_code == 400


def test_lxp_extract_course_metadata_omits_code_and_term():
    handler = HarvardLxpPlatformHandler()
    code, name, term, url = handler.extract_course_metadata(LXP_SAMPLE_CLAIMS, {})
    assert code is None
    assert name == "Learning Experience Showcase"
    assert term is None
    assert url.endswith("/memberships/39b59151-4bcb-4b17-a4f1-c4c8669a6a80?page=1")
