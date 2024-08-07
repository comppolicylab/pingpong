import pytest

from .auth import (
    decode_auth_token,
    decode_session_token,
    encode_auth_token,
    encode_session_token,
    authn_method_for_email,
)
from .now import utcnow
from .schemas import AuthToken, SessionToken
from .config import Saml2AuthnSettings, MagicLinkAuthnSettings


def test_auth_token():
    now = utcnow()
    now_ts = int(now.timestamp())
    tok = encode_auth_token("1", nowfn=lambda: now)
    payload = decode_auth_token(tok)
    assert payload == AuthToken(sub="1", exp=now_ts + 600, iat=now_ts)


def test_session_token():
    now = utcnow()
    now_ts = int(now.timestamp())
    tok = encode_session_token(1, nowfn=lambda: now)
    payload = decode_session_token(tok)
    assert payload == SessionToken(sub="1", exp=now_ts + 86_400, iat=now_ts)


@pytest.mark.parametrize(
    "email,name",
    [
        ("foo@bar.com", "Email"),
        ("foo@hks.harvard.edu", "Email"),
    ],
)
def test_authn_method_for_email_simple(email: str, name: str):
    authn_settings = MagicLinkAuthnSettings(
        name="Email",
        method="magic_link",
        expiry=86_400,
    )
    assert authn_method_for_email([authn_settings], email).name == name


@pytest.mark.parametrize(
    "email,name",
    [
        ("jack@harvard.edu", "Harvard Key"),
        ("martha@alumni.harvard.edu", "Email"),
        ("abc@hks.harvard.edu", "Harvard Key"),
        ("xyz@mit.edu", "Email"),
    ],
)
def test_authn_method_for_email_multi(email: str, name: str):
    harvard_sso_settings = Saml2AuthnSettings(
        name="Harvard Key",
        domains=["harvard.edu", "*.harvard.edu"],
        excluded_domains=["alumni.harvard.edu"],
        method="sso",
        protocol="saml",
        provider="harvard",
        base_path="saml",
    )

    magic_link_settings = MagicLinkAuthnSettings(
        name="Email",
        method="magic_link",
        expiry=86_400,
    )

    methods = [harvard_sso_settings, magic_link_settings]
    assert authn_method_for_email(methods, email).name == name
