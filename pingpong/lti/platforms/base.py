"""Abstract base class for LTI platform-specific logic.

Each supported LTI platform (Canvas, Harvard LXP, ...) has one concrete
handler that encapsulates the differences between platforms: openid config
validation, registration-payload construction, launch-claim extraction, and
cross-registration class lookup. Shared flow (OIDC state, JWT verification,
user resolution, role gating, class linking) lives in `pingpong/lti/server.py`.
"""

from abc import ABC, abstractmethod
from typing import Any

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from pingpong.lti.claims import get_claim_object
from pingpong.lti.constants import (
    LTI_CLAIM_NRPS_KEY,
)
from pingpong.lti.endpoints import generate_names_and_role_api_url
from pingpong.lti.schemas import LTILaunchCourseMetadata, LTIRegisterRequest
from pingpong.models import Class, ExternalLoginProvider, LTIClass, LTIRegistration
from pingpong.schemas import LMSPlatform


def parse_context_memberships_url(claims: dict[str, Any]) -> str | None:
    """Extract and validate the NRPS context_memberships_url from an LTI launch
    claim dict. Returns None if the claim is missing or empty; raises
    HTTPException(400) if the URL is present but fails URL-security validation.
    """
    nrps_claim = get_claim_object(claims, LTI_CLAIM_NRPS_KEY)
    url_value = nrps_claim.get("context_memberships_url")
    if not isinstance(url_value, str) or not url_value.strip():
        return None
    try:
        return generate_names_and_role_api_url(url_value)
    except ValueError as e:
        raise HTTPException(
            status_code=400,
            detail="Invalid context_memberships_url",
        ) from e


class LTIPlatformHandler(ABC):
    platform: LMSPlatform

    # --- Registration-time ---

    @abstractmethod
    def validate_platform_config(
        self,
        platform_config: dict[str, Any],
        message_types_supported: list[dict[str, Any]],
    ) -> None:
        """Raise HTTPException(400) if the platform's openid configuration is
        unusable for this handler. The caller already verified that
        `LtiResourceLinkRequest` is listed in `message_types_supported`.
        """

    @abstractmethod
    def validate_registration_request(self, data: LTIRegisterRequest) -> None:
        """Raise HTTPException(400) if the admin's registration form input is
        incompatible with this platform (e.g., SSO selection on a platform that
        does not support variable substitution)."""

    def filter_sso_providers(
        self, providers: list[ExternalLoginProvider]
    ) -> list[ExternalLoginProvider]:
        """Return the subset of public SSO providers selectable for this
        platform's registration form. Default: all. Platforms that do not
        support SSO-linked identifiers (e.g. no LTI variable substitution)
        should override this to return an empty list so the UI can hide the
        provider dropdown entirely.
        """
        return providers

    def show_course_navigation_control(self) -> bool:
        """Whether the registration UI should show the course-navigation toggle."""
        return False

    @abstractmethod
    def extract_registration_fields(
        self, platform_config: dict[str, Any]
    ) -> dict[str, Any]:
        """Return platform-specific fields to persist on LTIRegistration
        (e.g. canvas_account_name, canvas_account_lti_guid). Empty dict for
        platforms that do not populate the Canvas-named columns.
        """

    @abstractmethod
    def build_tool_registration_payload(
        self,
        *,
        base_tool_config: dict[str, Any],
        data: LTIRegisterRequest,
        sso_field_full_name: str | None,
    ) -> dict[str, Any]:
        """Return the full tool_registration_data dict that will be POSTed to
        the platform's registration_endpoint. The handler decides what goes
        into custom_parameters, messages[].custom_parameters, and any
        platform-specific vendor extensions.
        """

    # --- Launch-time ---

    @abstractmethod
    def extract_course_id(
        self,
        claims: dict[str, Any],
        launch_custom_params: dict[str, Any],
    ) -> str:
        """Return the course_id used to find/create the LTIClass.
        Raise HTTPException(400) if unobtainable.
        """

    @abstractmethod
    def extract_course_metadata(
        self,
        claims: dict[str, Any],
        launch_custom_params: dict[str, Any],
    ) -> LTILaunchCourseMetadata:
        """Return (course_code, course_name, course_term, context_memberships_url)
        for persistence on LTIClass. Any field may be None.
        """

    @abstractmethod
    async def find_class_for_course(
        self,
        db: AsyncSession,
        registration: LTIRegistration,
        course_id: str,
    ) -> LTIClass | Class | None:
        """Return the existing LTIClass/Class for this (registration, course_id),
        applying any platform-specific cross-registration lookup. Return None
        if no class has been linked yet (caller will create a pending LTIClass).
        """


__all__ = [
    "LTIPlatformHandler",
    "parse_context_memberships_url",
]
