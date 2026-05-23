from __future__ import annotations

from datetime import datetime, timedelta, timezone

import jwt
import pytest

from pingpong.config import config
from pingpong.connectors.core.exceptions import OAuthStateError
from pingpong.connectors.core.state import decode_state, encode_state, generate_nonce


def _fixed_now(dt: datetime):
    def fn():
        return dt

    return fn


def test_state_round_trips_connector_config_id_and_encrypted_pkce():
    verifier = "pkce-verifier-value"
    nonce = "nonce-value"
    token = encode_state(
        user_id=42,
        service="panopto",
        connector_config_id=7,
        pkce_verifier=verifier,
        nonce=nonce,
    )

    secret = config.auth.secret_keys[0]
    raw = jwt.decode(
        token,
        secret.key,
        algorithms=[secret.algorithm],
        options={"verify_exp": False},
    )
    assert raw["connector_config_id"] == 7
    assert verifier not in str(raw)
    assert "pkce_verifier" not in raw

    decoded = decode_state(token)
    assert decoded["sub"] == "42"
    assert decoded["service"] == "panopto"
    assert decoded["connector_config_id"] == 7
    assert decoded["pkce_verifier"] == verifier
    assert decoded["nonce"] == nonce
    assert "pkce_v" not in decoded


def test_generate_nonce_returns_unguessable_urlsafe_value():
    nonce = generate_nonce()
    assert isinstance(nonce, str)
    assert len(nonce) >= 32
    assert generate_nonce() != nonce


def test_state_without_pkce_yields_none():
    token = encode_state(
        user_id=1,
        service="panopto",
        connector_config_id=2,
        pkce_verifier=None,
    )
    decoded = decode_state(token)
    assert decoded["connector_config_id"] == 2
    assert decoded["pkce_verifier"] is None


def test_state_rejects_expired_token():
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    token = encode_state(
        user_id=1,
        service="panopto",
        connector_config_id=2,
        pkce_verifier=None,
        expiry=60,
        nowfn=_fixed_now(now),
    )
    with pytest.raises(OAuthStateError, match="expired"):
        decode_state(token, nowfn=_fixed_now(now + timedelta(seconds=120)))


def test_state_rejects_tampered_token():
    token = encode_state(
        user_id=1,
        service="panopto",
        connector_config_id=2,
        pkce_verifier=None,
    )
    head, _, _ = token.rpartition(".")
    with pytest.raises(OAuthStateError):
        decode_state(head + ".AAAAAA")


def test_state_requires_connector_config_id():
    secret = config.auth.secret_keys[0]
    payload = {"sub": "1", "service": "panopto", "exp": 2_000_000_000}
    token = jwt.encode(payload, secret.key, algorithm=secret.algorithm)
    with pytest.raises(OAuthStateError, match="connector_config_id"):
        decode_state(token)
