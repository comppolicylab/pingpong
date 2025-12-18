"""FastAPI routes for LTI Advantage Service."""

import json
import logging
from typing import Any, cast
import aiohttp
from fastapi import APIRouter, HTTPException, Depends, Request

from pingpong.config import config
from pingpong.lti.schemas import LTIRegisterRequest
from pingpong.models import ExternalLoginProvider, LTIRegistration
from .key_manager import LTIKeyManager
from pingpong.schemas import ExternalLoginProviders, LMSPlatform

logger = logging.getLogger(__name__)

lti_router = APIRouter()


def get_lti_key_manager() -> LTIKeyManager:
    """Get the LTI key manager from config."""
    lti_settings = config.lti
    if lti_settings is None:
        raise HTTPException(status_code=404, detail="LTI service not enabled")
    return lti_settings.key_store.key_manager


@lti_router.get("/.well-known/jwks.json")
async def get_jwks(key_manager: LTIKeyManager = Depends(get_lti_key_manager)):
    """
    Get the JSON Web Key Set (JWKS) containing all valid public keys.

    This endpoint provides the public keys that LTI platforms can use to verify
    JWTs signed by this tool. The endpoint returns the last 3 valid keys as
    specified in the LTI Advantage specification.
    """
    try:
        jwks = await key_manager.get_public_keys_jwks()
        logger.info(f"Served JWKS with {len(jwks['keys'])} keys")
        return jwks
    except Exception as e:
        logger.error(f"Error serving JWKS: {e}")
        raise HTTPException(status_code=500, detail="Error retrieving public keys")


@lti_router.get("/sso/providers", response_model=ExternalLoginProviders)
async def get_sso_ids(request: Request):
    """
    Get the SSO identifiers for the LTI instance.
    """
    external_login_providers = await ExternalLoginProvider.get_all(request.state.db)
    no_email_providers = [
        provider for provider in external_login_providers if provider.name != "email"
    ]
    return {"providers": no_email_providers}


@lti_router.post("/register")
async def register_lti_instance(request: Request, data: LTIRegisterRequest):
    """
    Register a new LTI instance.
    """
    if not data.openid_configuration or not data.registration_token:
        raise HTTPException(
            status_code=400, detail="Missing openid_configuration or registration_token"
        )

    headers = {"Authorization": f"Bearer {data.registration_token}"}

    response_data: dict[str, Any] | None = None
    async with aiohttp.ClientSession() as session:
        async with session.get(
            data.openid_configuration, raise_for_status=True, headers=headers
        ) as response:
            payload = await response.json()
            if not isinstance(payload, dict):
                raise HTTPException(
                    status_code=500,
                    detail="Invalid OpenID configuration response payload",
                )
            response_data = cast(dict[str, Any], payload)

    if not response_data:
        raise HTTPException(
            status_code=500, detail="Failed to fetch OpenID configuration"
        )

    ISSUER_KEY = "issuer"
    AUTHORIZATION_ENDPOINT_KEY = "authorization_endpoint"
    REGISTRATION_ENDPOINT_KEY = "registration_endpoint"
    KEYS_ENDPOINT_KEY = "jwks_uri"
    TOKEN_ENDPOINT_KEY = "token_endpoint"
    SCOPES_SUPPORTED_KEY = "scopes_supported"
    TOKEN_ALG_KEY = "id_token_signing_alg_values_supported"
    SUBJECT_TYPES_KEY = "subject_types_supported"

    PLATFORM_CONFIGURATION_KEY = (
        "https://purl.imsglobal.org/spec/lti-platform-configuration"
    )
    MESSAGE_TYPES_KEY = "messages_supported"
    MESSAGE_TYPE = "LtiResourceLinkRequest"
    CANVAS_MESSAGE_PLACEMENT = "https://canvas.instructure.com/lti/course_navigation"

    CANVAS_ACCOUNT_NAME_KEY = "https://canvas.instructure.com/lti/account_name"

    REQUIRED_SCOPES = [
        "https://purl.imsglobal.org/spec/lti-nrps/scope/contextmembership.readonly"
    ]

    issuer = response_data.get(ISSUER_KEY)
    authorization_endpoint = response_data.get(AUTHORIZATION_ENDPOINT_KEY)
    registration_endpoint = response_data.get(REGISTRATION_ENDPOINT_KEY)
    keys_endpoint = response_data.get(KEYS_ENDPOINT_KEY)
    token_endpoint = response_data.get(TOKEN_ENDPOINT_KEY)
    scopes_supported = response_data.get(SCOPES_SUPPORTED_KEY, [])
    token_algorithms = response_data.get(TOKEN_ALG_KEY, [])
    subject_types = response_data.get(SUBJECT_TYPES_KEY, [])

    platform_config = response_data.get(PLATFORM_CONFIGURATION_KEY)
    if not isinstance(platform_config, dict):
        raise HTTPException(
            status_code=400, detail="Missing platform configuration in OpenID response"
        )

    product_family_code = platform_config.get("product_family_code")

    # Check that the product family code exists in schema.LMSPlatform
    if product_family_code not in {platform.value for platform in LMSPlatform}:
        raise HTTPException(status_code=400, detail="Invalid product family")

    platform = LMSPlatform(product_family_code)

    if (
        not issuer
        or not authorization_endpoint
        or not registration_endpoint
        or not keys_endpoint
        or not token_endpoint
    ):
        raise HTTPException(
            status_code=400, detail="Missing required OpenID configuration fields"
        )

    if not all(scope in scopes_supported for scope in REQUIRED_SCOPES):
        raise HTTPException(
            status_code=400, detail="Missing required scopes in OpenID configuration"
        )

    message_types_supported = platform_config.get(MESSAGE_TYPES_KEY, [])
    if not any(msg.get("type") == MESSAGE_TYPE for msg in message_types_supported):
        raise HTTPException(
            status_code=400, detail="LtiResourceLinkRequest not supported by platform"
        )

    if not any(
        CANVAS_MESSAGE_PLACEMENT in msg.get("placements", [])
        for msg in message_types_supported
        if msg.get("type") == MESSAGE_TYPE
    ):
        raise HTTPException(
            status_code=400,
            detail="Canvas course navigation placement not supported by platform",
        )

    if "RS256" not in token_algorithms:
        raise HTTPException(
            status_code=400, detail="RS256 not supported for ID token signing"
        )

    if "public" not in subject_types:
        raise HTTPException(status_code=400, detail="public subject type not supported")

    canvas_account_name = platform_config.get(CANVAS_ACCOUNT_NAME_KEY)

    tool_registration_data = {
        "application_type": "web",
        "grant_types": ["client_credentials", "implicit"],
        "initiate_login_uri": config.url("/api/v1/lti/login"),
        "redirect_uris": [config.url("/api/v1/lti/launch")],
        "response_types": ["id_token"],
        "client_name": "PingPong LTI Tool",
        "jwks_uri": config.url("/api/v1/lti/.well-known/jwks.json"),
        "token_endpoint_auth_method": "private_key_jwt",
        "scope": " ".join(REQUIRED_SCOPES + ["openid"]),
        "https://purl.imsglobal.org/spec/lti-tool-configuration": {
            "domain": config.host,
            "target_link_uri": config.url("/api/v1/lti/launch"),
            "description": "LTI Tool for easy launching of the PingPong application.",
            "custom_parameters": {"platform": platform.value},
            "claims": [
                "sub",
                "iss",
                "name",
                "given_name",
                "family_name",
                "email",
                "picture",
                "https://purl.imsglobal.org/spec/lti/claim/context",
                "https://purl.imsglobal.org/spec/lti/claim/roles",
                "https://purl.imsglobal.org/spec/lti/claim/resource_link",
                "https://purl.imsglobal.org/spec/lti/claim/tool_platform",
                "https://purl.imsglobal.org/spec/lti-nrps/claim/namesroleservice",
            ],
            "extensions": {
                "https://canvas.instructure.com/lti/extensions/course_navigation": {
                    "default": True,
                    "text": "PingPong LTI Tool",
                    "enabled": True,
                    "visibility": "members",
                }
            },
        },
    }

    new_registration = LTIRegistration(
        issuer=issuer,
        configuration=json.dumps(response_data),
        auth_login_url=authorization_endpoint,
        auth_token_url=token_endpoint,
        key_set_url=keys_endpoint,
        lms_platform=platform,
        token_algorithm="RS256",
        canvas_account_name=canvas_account_name,
        admin_name=data.admin_name,
        admin_email=data.admin_email,
        friendly_name=data.friendly_name,
    )

    return {"status": "ok"}
