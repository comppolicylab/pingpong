from pathlib import Path
from urllib.parse import urlparse
import json
import os

from pydantic import BaseModel
from fastapi import Request
from onelogin.saml2.auth import OneLogin_Saml2_Auth, OneLogin_Saml2_Settings

from .config import Saml2AuthnSettings, config


class SamlAttrs(BaseModel):
    email: str
    first_name: str
    middle_name: str
    last_name: str
    name: str
    identifier: str


def get_saml2_settings(provider: str) -> Saml2AuthnSettings:
    """Get the SAML2 settings for the given provider.

    Args:
        provider: The SAML2 provider name.

    Returns:
        The SAML2 settings from the config.
    """
    try:
        return next(
            method
            for method in config.auth.authn_methods
            if method.method == "sso" and method.provider == provider
        )
    except StopIteration:
        raise ValueError(f"Provider {provider} not found in SAML2 authn settings.")


async def from_fastapi_request(request: Request) -> dict:
    """Format a FastAPI request into a SAML request data object.

    Args:
        request: The FastAPI request.

    Returns:
        The SAML request data object. See python3-saml docs for more info.
        https://github.com/SAML-Toolkits/python3-saml?tab=readme-ov-file#settings
    """
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


def get_saml2_attrs(cfg: Saml2AuthnSettings, client: OneLogin_Saml2_Auth) -> SamlAttrs:
    """Get the SAML2 attributes for the given client and config.

    Args:
        cfg: The SAML2 authn settings.
        client: The SAML2 auth client.

    Returns:
        The SAML2 attributes.
    """
    attrs = client.get_attributes()
    fields_path = Path(cfg.base_path) / cfg.provider / "fields.json"
    fields = json.loads(fields_path.read_text())
    return SamlAttrs(
        email=(attrs.get(fields["email"]) or [""])[0],
        first_name=(attrs.get(fields["firstName"]) or [""])[0],
        middle_name=(attrs.get(fields["middleName"]) or [""])[0],
        last_name=(attrs.get(fields["lastName"]) or [""])[0],
        name=(attrs.get(fields["name"]) or [""])[0],
        identifier=(attrs.get(fields["identifier"]) or [""])[0],
    )


async def get_saml2_client(
    cfg: Saml2AuthnSettings, request: Request
) -> OneLogin_Saml2_Auth:
    """Get the SAML2 auth client for the given request and config.

    Args:
        cfg: The SAML2 authn settings.
        request_data: The request data.

    Returns:
        The SAML2 auth client.
    """
    request_data = await from_fastapi_request(request)
    settings_dir = Path(cfg.base_path) / cfg.provider

    # Detect if the certs are stored in the env. If so, load settings manually.
    # This adds support for environments like ECS where we can't mount files from secrets,
    # and can only set environment variables.
    env_sfx = cfg.provider.upper().replace("-", "_")
    env_key = f"SAML_{env_sfx}"

    if env_key in os.environ:
        settings_path = settings_dir / "settings.json"
        settings = json.loads(settings_path.read_text())
        cert_info = json.loads(os.environ[env_key])
        settings["sp"]["x509cert"] = cert_info.get(
            "x509cert", settings["sp"]["x509cert"]
        )
        settings["sp"]["privateKey"] = cert_info.get(
            "privateKey", settings["sp"]["privateKey"]
        )
        return OneLogin_Saml2_Auth(request_data, OneLogin_Saml2_Settings(settings))
    else:
        return OneLogin_Saml2_Auth(request_data, custom_base_path=str(settings_dir))
