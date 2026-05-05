from __future__ import annotations

from datetime import datetime, timedelta, timezone

import jwt
import pytest

from pingpong.config import config
from pingpong.connectors.exceptions import OAuthStateError
from pingpong.connectors.state import decode_state, encode_state


def _fixed_now(dt: datetime):
    def fn():
        return dt

    return fn


def test_encode_state_does_not_expose_pkce_verifier_in_jwt():
    """The raw verifier must never be readable from the signed (not encrypted) JWT."""
    verifier = "super-secret-code-verifier-value"
    token = encode_state(
        user_id=42,
        service="panopto",
        tenant="demo",
        pkce_verifier=verifier,
    )
    secret = config.auth.secret_keys[0]
    payload = jwt.decode(
        token,
        secret.key,
        algorithms=[secret.algorithm],
        options={"verify_exp": False},
    )
    # The raw verifier must not appear anywhere in the JWT payload.
    assert verifier not in str(payload)
    assert "pkce_verifier" not in payload
    # The ciphertext field is present but opaque.
    assert isinstance(payload["pkce_v"], str)
    assert verifier not in payload["pkce_v"]


def test_decode_state_round_trips_encrypted_verifier():
    verifier = "rfc7636-verifier"
    token = encode_state(
        user_id=7,
        service="panopto",
        tenant=None,
        pkce_verifier=verifier,
    )
    decoded = decode_state(token)
    assert decoded["pkce_verifier"] == verifier
    assert decoded["sub"] == "7"
    # The ciphertext field should have been consumed during decode.
    assert "pkce_v" not in decoded


def test_decode_state_without_verifier_yields_none():
    token = encode_state(
        user_id=1,
        service="panopto",
        tenant="demo",
        pkce_verifier=None,
    )
    decoded = decode_state(token)
    assert decoded["pkce_verifier"] is None


def test_decode_state_rejects_expired_token():
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    token = encode_state(
        user_id=1,
        service="panopto",
        tenant=None,
        pkce_verifier=None,
        expiry=60,
        nowfn=_fixed_now(now),
    )
    with pytest.raises(OAuthStateError, match="expired"):
        decode_state(token, nowfn=_fixed_now(now + timedelta(seconds=120)))


def test_decode_state_rejects_token_without_exp():
    # Craft a token that passes signature verification but has no `exp`.
    secret = config.auth.secret_keys[0]
    payload = {"sub": "1", "service": "panopto", "tenant": None}
    token = jwt.encode(payload, secret.key, algorithm=secret.algorithm)
    with pytest.raises(OAuthStateError, match="exp"):
        decode_state(token)


def test_decode_state_rejects_tampered_token():
    token = encode_state(
        user_id=1,
        service="panopto",
        tenant=None,
        pkce_verifier=None,
    )
    # Flip a character in the signature section.
    head, _, _ = token.rpartition(".")
    tampered = head + ".AAAAAA"
    with pytest.raises(OAuthStateError):
        decode_state(tampered)
