from typing import Annotated, Literal, TypeVar

import jwt
from pydantic import BaseModel, Field, ValidationError

from ..auth import TimeException, decode_signed_claims, encode_signed_claims
from ..now import NowFn, utcnow
from ..schemas import ExternalPrincipalTier
from .errors import OpenAccessError
from .settings import OpenAccessSettings

GRANT_AUDIENCE = "pingpong-open-access"
ACCESS_TOKEN_PURPOSE = "open_access"

Subject = Annotated[
    str, Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")
]


class LaunchGrant(BaseModel):
    typ: Literal["launch"]
    sub: Subject
    tier: ExternalPrincipalTier
    assistant_id: int
    language: str = Field("original", min_length=2, max_length=16)
    launch_id: str = Field(min_length=16, max_length=128, pattern=r"^[A-Za-z0-9_-]+$")


class RenewGrant(BaseModel):
    typ: Literal["renew"]
    sub: Subject
    assistant_id: int
    sid: str = Field(min_length=1, max_length=64)


class CatalogueGrant(BaseModel):
    typ: Literal["catalogue"]


class AccessClaims(BaseModel):
    purpose: Literal["open_access"]
    client: str
    pid: int
    tid: int
    cid: int
    sid: str


GrantT = TypeVar("GrantT", LaunchGrant, RenewGrant, CatalogueGrant)


def verify_grant(
    settings: OpenAccessSettings, token: str, model: type[GrantT]
) -> GrantT:
    try:
        claims = jwt.decode(
            token,
            settings.public_key,
            algorithms=[settings.signing_algorithm],
            audience=GRANT_AUDIENCE,
            issuer=settings.client_id,
            options={"require": ["exp", "iat", "iss", "aud"]},
        )
        if claims["exp"] - claims["iat"] > settings.grant_max_age_seconds:
            raise ValueError("grant lifetime is too long")
        return model.model_validate(claims)
    except (jwt.PyJWTError, ValueError, TypeError) as exc:
        raise OpenAccessError(
            401, "open_access_grant_invalid", "Invalid Open Access grant."
        ) from exc


def encode_access_token(
    settings: OpenAccessSettings,
    *,
    principal_id: int,
    thread_id: int,
    class_id: int,
    session_id: str,
    nowfn: NowFn = utcnow,
) -> str:
    return encode_signed_claims(
        AccessClaims(
            purpose=ACCESS_TOKEN_PURPOSE,
            client=settings.client_id,
            pid=principal_id,
            tid=thread_id,
            cid=class_id,
            sid=session_id,
        ).model_dump(),
        expiry=settings.access_token_ttl_seconds,
        nowfn=nowfn,
    )


def decode_access_token(
    settings: OpenAccessSettings, token: str, nowfn: NowFn = utcnow
) -> AccessClaims | None:
    try:
        raw = decode_signed_claims(token, verify_exp=False)
        claims = AccessClaims.model_validate(raw)
    except (jwt.PyJWTError, TimeException, ValidationError, ValueError):
        return None
    if claims.client != settings.client_id or raw["exp"] < nowfn().timestamp():
        return None
    return claims
