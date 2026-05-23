"""Signed-JWT helpers for the OAuth state round-trip.

PingPong owns the OAuth state value. Authlib receives the generated state
when building the authorization URL, but no Authlib session storage is used.
"""

from __future__ import annotations

import base64
import hashlib
import secrets
from datetime import timedelta
from typing import Any, cast

import jwt
from cryptography.fernet import Fernet, InvalidToken
from jwt.exceptions import PyJWTError

from pingpong.config import SecretKey, config
from pingpong.now import NowFn, utcnow

from .exceptions import OAuthStateError

DEFAULT_EXPIRY_SECONDS = 600
_PKCE_FERNET_SALT = b"pingpong-connectors-oauth-pkce-v1"


def _fernet_for(secret: SecretKey) -> Fernet:
    material = hashlib.sha256(
        secret.key.encode("utf-8") + b":" + _PKCE_FERNET_SALT
    ).digest()
    return Fernet(base64.urlsafe_b64encode(material))


def _require_secret_keys() -> None:
    if not config.auth.secret_keys:
        raise OAuthStateError("OAuth state signing is not configured")


def _encrypt_verifier(verifier: str) -> str:
    return (
        _fernet_for(config.auth.secret_keys[0])
        .encrypt(verifier.encode("utf-8"))
        .decode("ascii")
    )


def _decrypt_verifier(blob: str) -> str:
    for secret in config.auth.secret_keys:
        try:
            return _fernet_for(secret).decrypt(blob.encode("ascii")).decode("utf-8")
        except InvalidToken:
            continue
    raise OAuthStateError("OAuth state PKCE payload invalid")


def generate_nonce() -> str:
    return secrets.token_urlsafe(32)


def encode_state(
    *,
    user_id: int,
    service: str,
    connector_config_id: int,
    pkce_verifier: str | None,
    nonce: str | None = None,
    redirect_to: str | None = None,
    expiry: int = DEFAULT_EXPIRY_SECONDS,
    nowfn: NowFn = utcnow,
) -> str:
    _require_secret_keys()
    now = nowfn()
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(seconds=expiry)).timestamp()),
        "service": service,
        "connector_config_id": connector_config_id,
    }
    if pkce_verifier is not None:
        payload["pkce_v"] = _encrypt_verifier(pkce_verifier)
    if nonce is not None:
        payload["nonce"] = nonce
    if redirect_to is not None:
        payload["redirect_to"] = redirect_to
    secret = config.auth.secret_keys[0]
    return cast(str, jwt.encode(payload, secret.key, algorithm=secret.algorithm))


def decode_state(token: str, nowfn: NowFn = utcnow) -> dict[str, Any]:
    _require_secret_keys()
    exc: Exception | None = None
    for secret in config.auth.secret_keys:
        try:
            payload = jwt.decode(
                token,
                secret.key,
                algorithms=[secret.algorithm],
                options={"verify_exp": False, "verify_nbf": False},
            )
        except PyJWTError as e:
            exc = e
            continue

        exp = payload.get("exp")
        if not isinstance(exp, (int, float)):
            raise OAuthStateError("OAuth state token missing or invalid 'exp'")
        if nowfn().timestamp() >= exp:
            raise OAuthStateError("OAuth state token expired")

        for key in ("sub", "service", "connector_config_id"):
            if key not in payload:
                raise OAuthStateError(f"OAuth state token missing '{key}'")
        if not isinstance(payload["connector_config_id"], int):
            raise OAuthStateError(
                "OAuth state token missing or invalid 'connector_config_id'"
            )

        blob = payload.pop("pkce_v", None)
        payload["pkce_verifier"] = (
            _decrypt_verifier(blob) if isinstance(blob, str) else None
        )
        return payload

    raise OAuthStateError("OAuth state token invalid") from exc
