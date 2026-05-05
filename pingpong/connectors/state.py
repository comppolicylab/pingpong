"""Signed-JWT helpers for the OAuth state round-trip.

The state parameter is a short-lived JWT, signed with the same secret key
used for auth tokens (:mod:`pingpong.auth`), carrying the user_id, service
slug and tenant id so the callback can tie the redirect back to the
originating user without any server-side session storage.

The PKCE code verifier is *also* carried in the state payload, but
authenticated-encrypted with Fernet rather than left as cleartext.  A
plain signed JWT travels through the browser's URL bar, browser history,
provider logs, and referrer headers as the ``state`` query parameter; per
RFC 7636 the verifier must never leak to the front channel, so the raw
value is wrapped in Fernet ciphertext before being placed in the payload.

We don't use :func:`pingpong.auth.encode_auth_token` directly because the
``AuthToken`` schema only carries ``sub``. This module encodes/decodes a
richer payload using the same signing secret.
"""

from __future__ import annotations

import base64
import hashlib
from datetime import timedelta
from typing import Any, cast

import jwt
from cryptography.fernet import Fernet, InvalidToken
from jwt.exceptions import PyJWTError

from pingpong.config import SecretKey, config
from pingpong.now import NowFn, utcnow

from .exceptions import OAuthStateError

DEFAULT_EXPIRY_SECONDS = 600

# Domain-separation salt: ensures the Fernet key used for PKCE is distinct
# from the raw JWT signing key, so compromise of one doesn't cascade.
_PKCE_FERNET_SALT = b"pingpong-oauth-pkce-v1"


def _fernet_for(secret: SecretKey) -> Fernet:
    material = hashlib.sha256(
        secret.key.encode("utf-8") + b":" + _PKCE_FERNET_SALT
    ).digest()
    return Fernet(base64.urlsafe_b64encode(material))


def _require_secret_keys() -> None:
    if not config.auth.secret_keys:
        raise OAuthStateError("OAuth state signing is not configured")


def _encrypt_verifier(verifier: str) -> str:
    f = _fernet_for(config.auth.secret_keys[0])
    return f.encrypt(verifier.encode("utf-8")).decode("ascii")


def _decrypt_verifier(blob: str) -> str:
    # Try each configured key to support key rotation, mirroring how
    # jwt signature verification iterates below.
    for secret in config.auth.secret_keys:
        try:
            return _fernet_for(secret).decrypt(blob.encode("ascii")).decode("utf-8")
        except InvalidToken:
            continue
    raise OAuthStateError("OAuth state PKCE payload invalid")


def encode_state(
    *,
    user_id: int,
    service: str,
    tenant: str | None,
    pkce_verifier: str | None,
    redirect_to: str | None = None,
    expiry: int = DEFAULT_EXPIRY_SECONDS,
    nowfn: NowFn = utcnow,
) -> str:
    _require_secret_keys()
    now = nowfn()
    exp = now + timedelta(seconds=expiry)
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "iat": int(now.timestamp()),
        "exp": int(exp.timestamp()),
        "service": service,
        "tenant": tenant,
    }
    if pkce_verifier is not None:
        payload["pkce_v"] = _encrypt_verifier(pkce_verifier)
    if redirect_to is not None:
        payload["redirect_to"] = redirect_to
    secret = config.auth.secret_keys[0]
    return cast(
        str,
        jwt.encode(payload, secret.key, algorithm=secret.algorithm),
    )


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

        now_ts = nowfn().timestamp()
        exp = payload.get("exp")
        if not isinstance(exp, (int, float)):
            raise OAuthStateError("OAuth state token missing or invalid 'exp'")
        if now_ts >= exp:
            raise OAuthStateError("OAuth state token expired")

        required = ("sub", "service")
        for key in required:
            if key not in payload:
                raise OAuthStateError(f"OAuth state token missing '{key}'")

        # Surface the decrypted verifier under the same key callers used
        # before the encryption change, so the rest of the flow is unchanged.
        blob = payload.pop("pkce_v", None)
        payload["pkce_verifier"] = (
            _decrypt_verifier(blob) if isinstance(blob, str) else None
        )

        return payload

    raise OAuthStateError(
        f"OAuth state token signature invalid: {exc}"
        if exc
        else "OAuth state token invalid"
    )
