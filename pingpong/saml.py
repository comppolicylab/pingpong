from pathlib import Path
from urllib.parse import urlparse

from fastapi import Request
from onelogin.saml2.auth import OneLogin_Saml2_Auth

from .config import Saml2AuthnSettings, config


async def from_fastapi_request(request: Request) -> dict:
    """Format a FastAPI request into a SAML request data object."""
    public_url = urlparse(config.public_url)
    post_data = await request.form()

    return {
        "https": "on" if public_url.scheme == "https" else "off",
        "http_host": request.headers.get("host", public_url.hostname),
        "server_port": public_url.port or (443 if public_url.scheme == "https" else 80),
        "script_name": request.url.path,
        "get_data": request.query_params,
        "post_data": post_data,
    }


async def get_saml2_client(
    config: Saml2AuthnSettings, request: Request
) -> OneLogin_Saml2_Auth:
    """Get the SAML2 auth client for the given request and config.

    Args:
        config: The SAML2 authn settings.
        request_data: The request data.

    Returns:
        The SAML2 auth client.
    """
    request_data = await from_fastapi_request(request)
    settings_path = Path(config.base_path) / config.provider
    return OneLogin_Saml2_Auth(request_data, custom_base_path=str(settings_path))
