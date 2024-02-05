from .auth import (
    decode_auth_token,
    decode_session_token,
    encode_auth_token,
    encode_session_token,
)
from .now import utcnow
from .schemas import AuthToken, SessionToken


def test_auth_token():
    now = utcnow()
    now_ts = int(now.timestamp())
    tok = encode_auth_token(1, nowfn=lambda: now)
    payload = decode_auth_token(tok)
    assert payload == AuthToken(sub="1", exp=now_ts + 600, iat=now_ts)


def test_session_token():
    now = utcnow()
    now_ts = int(now.timestamp())
    tok = encode_session_token(1, nowfn=lambda: now)
    payload = decode_session_token(tok)
    assert payload == SessionToken(sub="1", exp=now_ts + 86_400, iat=now_ts)
