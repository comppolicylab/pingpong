"""Harvard LXP LTI platform handler.

Harvard LXP differs from Canvas in three meaningful ways for this integration:
- No LTI variable substitution, so the course_id is read from the standard
  `context.id` claim rather than a Canvas-style custom parameter.
- No `account_lti_guid` equivalent, so cross-registration class lookup is
  not supported; each deployment stands alone.
- No Canvas vendor extensions in the tool registration payload.
"""

from typing import Any

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from pingpong.lti.claims import get_claim_object
from pingpong.lti.constants import (
    LTI_CLAIM_CONTEXT_KEY,
    LTI_TOOL_CONFIGURATION_KEY,
    MESSAGE_TYPE,
)
from pingpong.lti.lti_course import find_class_by_course_id
from pingpong.lti.platforms.base import (
    LTIPlatformHandler,
    parse_context_memberships_url,
)
from pingpong.lti.schemas import LTIRegisterRequest
from pingpong.models import Class, ExternalLoginProvider, LTIClass, LTIRegistration
from pingpong.schemas import LMSPlatform


class HarvardLxpPlatformHandler(LTIPlatformHandler):
    platform = LMSPlatform.HARVARD_LXP

    def validate_platform_config(
        self,
        platform_config: dict[str, Any],
        message_types_supported: list[dict[str, Any]],
    ) -> None:
        # The generic caller already asserted LtiResourceLinkRequest is
        # supported. LXP has no additional platform-config requirements.
        return None

    def validate_registration_request(self, data: LTIRegisterRequest) -> None:
        # Harvard LXP does not support variable substitution, so an SSO field
        # would be sent to the tool as a literal string (e.g. "$Person.sourcedId")
        # rather than the resolved identifier — never usable. Reject up front.
        if data.provider_id != 0:
            raise HTTPException(
                status_code=400,
                detail=(
                    "Harvard LXP does not support SSO-linked identifiers "
                    "(no LTI variable substitution)."
                ),
            )

    def filter_sso_providers(
        self, providers: list[ExternalLoginProvider]
    ) -> list[ExternalLoginProvider]:
        # Mirrors validate_registration_request: SSO-linked identifiers are
        # never usable on LXP, so hide the provider dropdown entirely.
        return []

    def extract_registration_fields(
        self, platform_config: dict[str, Any]
    ) -> dict[str, Any]:
        # LXP has no account_name / account_lti_guid equivalent.
        return {}

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
        }
        target_link_uri = tool_config["target_link_uri"]
        tool_config["messages"] = [
            {
                "type": MESSAGE_TYPE,
                "target_link_uri": target_link_uri,
                "label": "PingPong",
            }
        ]

        payload[LTI_TOOL_CONFIGURATION_KEY] = tool_config
        return payload

    def extract_course_id(
        self,
        claims: dict[str, Any],
        launch_custom_params: dict[str, Any],
    ) -> str:
        context = get_claim_object(claims, LTI_CLAIM_CONTEXT_KEY)
        course_id = context.get("id")
        if not isinstance(course_id, str) or not course_id:
            raise HTTPException(status_code=400, detail="Missing or invalid course_id")
        return course_id

    def extract_course_metadata(
        self,
        claims: dict[str, Any],
        launch_custom_params: dict[str, Any],
    ) -> tuple[str | None, str | None, str | None, str | None]:
        context = get_claim_object(claims, LTI_CLAIM_CONTEXT_KEY)

        course_name_value = context.get("title")
        course_name = course_name_value if isinstance(course_name_value, str) else None

        context_memberships_url = parse_context_memberships_url(claims)
        # LXP does not provide a meaningful course_code (label is a synthetic
        # "LES-<uuid>" prefix + UUID) or a course term.
        return None, course_name, None, context_memberships_url

    async def find_class_for_course(
        self,
        db: AsyncSession,
        registration: LTIRegistration,
        course_id: str,
    ) -> LTIClass | Class | None:
        return await find_class_by_course_id(
            db,
            registration.id,
            course_id,
        )
