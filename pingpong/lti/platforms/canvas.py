"""Canvas-specific LTI platform handler."""

import json
from typing import Any

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from pingpong.lti.claims import get_claim_object
from pingpong.lti.constants import (
    CANVAS_ACCOUNT_LTI_GUID_KEY,
    CANVAS_ACCOUNT_NAME_KEY,
    CANVAS_COURSE_ID_VARIABLE,
    CANVAS_COURSE_NAVIGATION_DEFAULT_ENABLED_KEY,
    CANVAS_EDITOR_BUTTON_PLACEMENT,
    CANVAS_LINK_SELECTION_PLACEMENT,
    CANVAS_MESSAGE_PLACEMENT,
    CANVAS_TERM_NAME_VARIABLE,
    DEEP_LINK_MESSAGE_TYPE,
    LTI_CLAIM_CONTEXT_KEY,
    LTI_CUSTOM_SSO_PROVIDER_ID_KEY,
    LTI_CUSTOM_SSO_VALUE_KEY,
    LTI_TOOL_CONFIGURATION_KEY,
    MESSAGE_TYPE,
    NO_SSO_PROVIDER_ID,
    PINGPONG_LTI_TOOL_VERSION,
    SSO_FIELD_FULL_NAME,
)
from pingpong.lti.lti_course import (
    find_class_by_course_id,
    find_class_by_course_id_search_by_canvas_account_lti_guid,
)
from pingpong.lti.platforms.base import (
    LTIPlatformHandler,
    parse_context_memberships_url,
)
from pingpong.lti.schemas import LTILaunchCourseMetadata, LTIRegisterRequest
from pingpong.models import Class, LTIClass, LTIRegistration
from pingpong.schemas import LMSPlatform

CANVAS_COURSE_ID_KEY = "canvas_course_id"
CANVAS_TERM_NAME_KEY = "canvas_term_name"
CANVAS_CUSTOM_PARAM_DEFAULT_VALUES = {
    CANVAS_COURSE_ID_KEY: [CANVAS_COURSE_ID_VARIABLE],
    CANVAS_TERM_NAME_KEY: [CANVAS_TERM_NAME_VARIABLE],
}


class CanvasPlatformHandler(LTIPlatformHandler):
    platform = LMSPlatform.CANVAS

    def show_course_navigation_control(self) -> bool:
        return True

    async def get_registration_quickstarts(
        self,
        session: AsyncSession,
        *,
        issuer: str,
        platform_config: dict[str, Any],
        allowed_provider_ids: set[int],
        allowed_institution_ids: set[int],
    ) -> list[dict[str, Any]]:
        account_lti_guid = platform_config.get(CANVAS_ACCOUNT_LTI_GUID_KEY)
        if not isinstance(account_lti_guid, str) or not account_lti_guid:
            return []

        registrations = await LTIRegistration.get_canvas_quickstart_candidates(
            session, issuer, account_lti_guid
        )
        quickstarts: list[dict[str, Any]] = []
        seen_client_ids: set[str] = set()
        for registration in registrations:
            if not registration.client_id or registration.client_id in seen_client_ids:
                continue
            seen_client_ids.add(registration.client_id)
            quickstarts.append(
                self._registration_quickstart(
                    registration,
                    allowed_provider_ids=allowed_provider_ids,
                    allowed_institution_ids=allowed_institution_ids,
                )
            )
        return quickstarts

    def _registration_quickstart(
        self,
        registration: LTIRegistration,
        *,
        allowed_provider_ids: set[int],
        allowed_institution_ids: set[int],
    ) -> dict[str, Any]:
        provider_id = NO_SSO_PROVIDER_ID
        sso_field = None
        show_in_course_navigation = True
        try:
            registration_data = json.loads(registration.registration_data or "{}")
        except (json.JSONDecodeError, TypeError):
            registration_data = {}

        if isinstance(registration_data, dict):
            tool_configuration = registration_data.get(LTI_TOOL_CONFIGURATION_KEY)
            if isinstance(tool_configuration, dict):
                custom_parameters = tool_configuration.get("custom_parameters")
                if isinstance(custom_parameters, dict):
                    raw_provider_id = custom_parameters.get(
                        LTI_CUSTOM_SSO_PROVIDER_ID_KEY
                    )
                    try:
                        parsed_provider_id = (
                            int(raw_provider_id)
                            if isinstance(raw_provider_id, (str, int))
                            else NO_SSO_PROVIDER_ID
                        )
                    except (TypeError, ValueError):
                        parsed_provider_id = NO_SSO_PROVIDER_ID

                    raw_sso_value = custom_parameters.get(LTI_CUSTOM_SSO_VALUE_KEY)
                    if isinstance(raw_sso_value, str) and raw_sso_value.startswith("$"):
                        full_name = raw_sso_value[1:]
                        sso_field = next(
                            (
                                field
                                for field, configured_name in SSO_FIELD_FULL_NAME.items()
                                if configured_name == full_name
                            ),
                            None,
                        )
                    if (
                        parsed_provider_id in allowed_provider_ids
                        and sso_field is not None
                    ):
                        provider_id = parsed_provider_id
                    else:
                        sso_field = None

                messages = tool_configuration.get("messages")
                if isinstance(messages, list):
                    for message in messages:
                        if not isinstance(message, dict):
                            continue
                        placements = message.get("placements")
                        if (
                            message.get("type") == MESSAGE_TYPE
                            and isinstance(placements, list)
                            and "course_navigation" in placements
                        ):
                            default_enabled = message.get(
                                CANVAS_COURSE_NAVIGATION_DEFAULT_ENABLED_KEY
                            )
                            if isinstance(default_enabled, bool):
                                show_in_course_navigation = default_enabled
                            break

        return {
            "client_id": registration.client_id,
            "name": registration.friendly_name or "",
            "admin_name": registration.admin_name or "",
            "admin_email": registration.admin_email or "",
            "provider_id": provider_id,
            "sso_field": sso_field,
            "institution_ids": [
                institution.id
                for institution in registration.institutions
                if institution.id in allowed_institution_ids
            ],
            "show_in_course_navigation": show_in_course_navigation,
        }

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
        message_types_supported: list[dict[str, Any]],
    ) -> dict[str, Any]:
        payload = dict(base_tool_config)
        tool_config = dict(payload[LTI_TOOL_CONFIGURATION_KEY])

        tool_config["custom_parameters"] = {
            "platform": self.platform.value,
            "pingpong_lti_tool_version": PINGPONG_LTI_TOOL_VERSION,
            LTI_CUSTOM_SSO_PROVIDER_ID_KEY: str(data.provider_id),
            LTI_CUSTOM_SSO_VALUE_KEY: (
                f"${sso_field_full_name}" if sso_field_full_name else ""
            ),
        }
        tool_config["https://canvas.instructure.com/lti/vendor"] = (
            "Computational Policy Lab"
        )
        target_link_uri = tool_config["target_link_uri"]
        course_navigation_message = {
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
            CANVAS_COURSE_NAVIGATION_DEFAULT_ENABLED_KEY: data.show_in_course_navigation,
            "https://canvas.instructure.com/lti/visibility": "members",
        }
        editor_button_message = {
            "type": DEEP_LINK_MESSAGE_TYPE,
            "target_link_uri": target_link_uri,
            "label": "PingPong",
            "placements": ["editor_button"],
            "selection_width": 1000,
            "selection_height": 1600,
            "https://canvas.instructure.com/lti/launch_width": 1000,
            "https://canvas.instructure.com/lti/launch_height": 1600,
            "custom_parameters": {
                "placement": "editor_button",
                CANVAS_COURSE_ID_KEY: CANVAS_CUSTOM_PARAM_DEFAULT_VALUES[
                    CANVAS_COURSE_ID_KEY
                ][0],
                CANVAS_TERM_NAME_KEY: CANVAS_CUSTOM_PARAM_DEFAULT_VALUES[
                    CANVAS_TERM_NAME_KEY
                ][0],
            },
            "https://canvas.instructure.com/lti/visibility": "admins",
        }
        link_selection_message = {
            "type": DEEP_LINK_MESSAGE_TYPE,
            "target_link_uri": target_link_uri,
            "label": "PingPong",
            "placements": ["link_selection"],
            "selection_width": 900,
            "selection_height": 850,
            "https://canvas.instructure.com/lti/launch_width": 900,
            "https://canvas.instructure.com/lti/launch_height": 850,
            "custom_parameters": {
                "placement": "link_selection",
                CANVAS_COURSE_ID_KEY: CANVAS_CUSTOM_PARAM_DEFAULT_VALUES[
                    CANVAS_COURSE_ID_KEY
                ][0],
                CANVAS_TERM_NAME_KEY: CANVAS_CUSTOM_PARAM_DEFAULT_VALUES[
                    CANVAS_TERM_NAME_KEY
                ][0],
            },
            "https://canvas.instructure.com/lti/visibility": "admins",
        }
        logo_uri = payload.get("logo_uri")
        if isinstance(logo_uri, str) and logo_uri:
            editor_button_message["icon_uri"] = logo_uri
            link_selection_message["icon_uri"] = logo_uri
        messages = [course_navigation_message]
        deep_link_placements = {
            placement
            for message in message_types_supported
            if message.get("type") == DEEP_LINK_MESSAGE_TYPE
            for placement in message.get("placements", [])
        }
        if CANVAS_EDITOR_BUTTON_PLACEMENT in deep_link_placements:
            messages.append(editor_button_message)
        if CANVAS_LINK_SELECTION_PLACEMENT in deep_link_placements:
            messages.append(link_selection_message)
        tool_config["messages"] = messages

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
    ) -> LTILaunchCourseMetadata:
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
        return LTILaunchCourseMetadata(
            course_code=course_code,
            course_name=course_name,
            course_term=course_term,
            context_memberships_url=context_memberships_url,
        )

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
