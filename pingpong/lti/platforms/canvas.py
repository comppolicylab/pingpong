"""Canvas-specific LTI platform handler."""

from typing import Any

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from pingpong.lti.claims import get_claim_object
from pingpong.lti.constants import (
    CANVAS_ACCOUNT_LTI_GUID_KEY,
    CANVAS_ACCOUNT_NAME_KEY,
    CANVAS_MESSAGE_PLACEMENT,
    LTI_CLAIM_CONTEXT_KEY,
    LTI_CUSTOM_SSO_PROVIDER_ID_KEY,
    LTI_CUSTOM_SSO_VALUE_KEY,
    LTI_TOOL_CONFIGURATION_KEY,
    MESSAGE_TYPE,
)
from pingpong.lti.lti_course import (
    find_class_by_course_id,
    find_class_by_course_id_search_by_canvas_account_lti_guid,
)
from pingpong.lti.platforms.base import (
    LTIPlatformHandler,
    parse_context_memberships_url,
)
from pingpong.lti.schemas import LTIRegisterRequest
from pingpong.models import Class, LTIClass, LTIRegistration
from pingpong.schemas import LMSPlatform

CANVAS_COURSE_ID_KEY = "canvas_course_id"
CANVAS_TERM_NAME_KEY = "canvas_term_name"
CANVAS_CUSTOM_PARAM_DEFAULT_VALUES = {
    CANVAS_COURSE_ID_KEY: ["$Canvas.course.id"],
    CANVAS_TERM_NAME_KEY: ["$Canvas.term.name"],
}


class CanvasPlatformHandler(LTIPlatformHandler):
    platform = LMSPlatform.CANVAS

    def show_course_navigation_control(self) -> bool:
        return True

    def validate_platform_config(
        self,
        platform_config: dict[str, Any],
        message_types_supported: list[dict[str, Any]],
    ) -> None:
        if not any(
            CANVAS_MESSAGE_PLACEMENT in msg.get("placements", [])
            for msg in message_types_supported
            if msg.get("type") == MESSAGE_TYPE
        ):
            raise HTTPException(
                status_code=400,
                detail="Canvas course navigation placement not supported by platform",
            )

    def validate_registration_request(self, data: LTIRegisterRequest) -> None:
        # Canvas accepts all SSO configurations the generic validator already allows.
        return None

    def extract_registration_fields(
        self, platform_config: dict[str, Any]
    ) -> dict[str, Any]:
        return {
            "canvas_account_name": platform_config.get(CANVAS_ACCOUNT_NAME_KEY),
            "canvas_account_lti_guid": platform_config.get(CANVAS_ACCOUNT_LTI_GUID_KEY),
        }

    def build_tool_registration_payload(
        self,
        *,
        base_tool_config: dict[str, Any],
        data: LTIRegisterRequest,
        sso_field_full_name: str | None,
    ) -> dict[str, Any]:
        payload = dict(base_tool_config)
        tool_config = dict(payload[LTI_TOOL_CONFIGURATION_KEY])

        tool_config["custom_parameters"] = {
            "platform": self.platform.value,
            "pingpong_lti_tool_version": "1.0",
            LTI_CUSTOM_SSO_PROVIDER_ID_KEY: str(data.provider_id),
            LTI_CUSTOM_SSO_VALUE_KEY: (
                f"${sso_field_full_name}" if sso_field_full_name else ""
            ),
        }
        tool_config["https://canvas.instructure.com/lti/vendor"] = (
            "Computational Policy Lab"
        )
        target_link_uri = tool_config["target_link_uri"]
        tool_config["messages"] = [
            {
                "type": MESSAGE_TYPE,
                "target_link_uri": target_link_uri,
                "label": "PingPong",
                "placements": ["course_navigation"],
                "custom_parameters": {
                    "placement": "course_navigation",
                    CANVAS_COURSE_ID_KEY: CANVAS_CUSTOM_PARAM_DEFAULT_VALUES[
                        CANVAS_COURSE_ID_KEY
                    ][0],
                    CANVAS_TERM_NAME_KEY: CANVAS_CUSTOM_PARAM_DEFAULT_VALUES[
                        CANVAS_TERM_NAME_KEY
                    ][0],
                },
                "https://canvas.instructure.com/lti/display_type": "full_width_in_context",
                "https://canvas.instructure.com/lti/course_navigation/default_enabled": data.show_in_course_navigation,
                "https://canvas.instructure.com/lti/visibility": "members",
            }
        ]

        payload[LTI_TOOL_CONFIGURATION_KEY] = tool_config
        return payload

    def extract_course_id(
        self,
        claims: dict[str, Any],
        launch_custom_params: dict[str, Any],
    ) -> str:
        course_id = launch_custom_params.get(CANVAS_COURSE_ID_KEY)
        if (
            not isinstance(course_id, str)
            or not course_id
            or course_id in CANVAS_CUSTOM_PARAM_DEFAULT_VALUES[CANVAS_COURSE_ID_KEY]
        ):
            raise HTTPException(status_code=400, detail="Missing or invalid course_id")
        return course_id

    def extract_course_metadata(
        self,
        claims: dict[str, Any],
        launch_custom_params: dict[str, Any],
    ) -> tuple[str | None, str | None, str | None, str | None]:
        context = get_claim_object(claims, LTI_CLAIM_CONTEXT_KEY)

        course_code_value = context.get("label")
        course_code = course_code_value if isinstance(course_code_value, str) else None

        course_name_value = context.get("title")
        course_name = course_name_value if isinstance(course_name_value, str) else None

        course_term_value = launch_custom_params.get(CANVAS_TERM_NAME_KEY)
        course_term = course_term_value if isinstance(course_term_value, str) else None
        if (
            not course_term
            or course_term in CANVAS_CUSTOM_PARAM_DEFAULT_VALUES[CANVAS_TERM_NAME_KEY]
        ):
            course_term = None

        context_memberships_url = parse_context_memberships_url(claims)
        return course_code, course_name, course_term, context_memberships_url

    async def find_class_for_course(
        self,
        db: AsyncSession,
        registration: LTIRegistration,
        course_id: str,
    ) -> LTIClass | Class | None:
        if registration.canvas_account_lti_guid:
            return await find_class_by_course_id_search_by_canvas_account_lti_guid(
                db,
                registration_id=registration.id,
                canvas_account_lti_guid=registration.canvas_account_lti_guid,
                course_id=course_id,
            )
        return await find_class_by_course_id(
            db,
            registration.id,
            course_id,
        )
