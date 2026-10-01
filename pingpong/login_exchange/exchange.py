"""Single-use login grants after SAML validation at the original ACS."""

import hashlib
import re
import secrets
from html import escape
from urllib.parse import unquote, urlsplit, urlunsplit

from fastapi import HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from redis.exceptions import RedisError

from ..auth import redirect_with_session
from ..config import config
from ..now import NowFn, utcnow
from .cache import redis_client

EXCHANGE_PATH = "/api/v1/login/sso/exchange"
NO_STORE = {"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"}


class LoginGrant(BaseModel):
    user_id: int
    audience: str
    destination: str


def public_origin() -> str:
    url = urlsplit(config.public_url)
    return urlunsplit((url.scheme, url.netloc, "", "", ""))


def exchange_target_origin() -> str:
    settings = config.auth.login_exchange
    if settings is None:
        raise HTTPException(503, "Login exchange is not configured")
    return settings.target_origin


def request_host_matches(request: Request, origin: str) -> bool:
    # Scheme may be HTTP behind TLS termination; the configured origin is trusted.
    return request.headers.get("host", "").lower() == urlsplit(origin).netloc.lower()


def allowed_origins() -> set[str]:
    settings = config.auth.login_exchange
    if settings is None:
        return {public_origin()}
    return {public_origin(), settings.target_origin, *settings.source_origins}


def request_origin(request: Request) -> str:
    for origin in allowed_origins():
        if request_host_matches(request, origin):
            return origin
    raise HTTPException(400, "Unsupported login host")


def validate_login_host(request: Request) -> None:
    request_origin(request)


def relative_destination(value: str) -> str:
    """Accept local paths or explicitly configured origins, never arbitrary redirects."""
    if not isinstance(value, str) or not value:
        raise HTTPException(400, "Invalid login destination")
    decoded = unquote(value)
    if any(ord(c) < 32 or ord(c) == 127 or c == "\\" for c in decoded):
        raise HTTPException(400, "Invalid login destination")
    try:
        parsed = urlsplit(value)
        if parsed.scheme or parsed.netloc:
            origin = urlunsplit((parsed.scheme, parsed.netloc, "", "", ""))
            if origin not in allowed_origins():
                raise ValueError("Untrusted origin")
        elif not value.startswith("/") or value.startswith("//"):
            raise ValueError("Not a local path")
        path = parsed.path or "/"
        if unquote(path).startswith("//"):
            raise ValueError("Not a local path")
    except ValueError as exc:
        raise HTTPException(400, "Invalid login destination") from exc
    return urlunsplit(("", "", path, parsed.query, parsed.fragment))


def destination_origin(value: str, default_origin: str) -> str:
    """Return the allowlisted origin carried by a validated destination."""
    parsed = urlsplit(value)
    if not parsed.scheme and not parsed.netloc:
        return default_origin
    origin = urlunsplit((parsed.scheme, parsed.netloc, "", "", ""))
    if origin not in allowed_origins():
        raise HTTPException(400, "Invalid login destination")
    return origin


def relay_state(request: Request, destination: str) -> str:
    """Bind the post-login destination to the host that initiated SAML."""
    origin = request_origin(request)
    return origin + relative_destination(destination)


def exchange_key(code: str) -> str:
    # Neither Redis keys nor stored values contain the bearer code itself.
    audience = hashlib.sha256(exchange_target_origin().encode()).hexdigest()
    digest = hashlib.sha256(code.encode()).hexdigest()
    return f"pingpong:login-exchange:{audience}:{digest}"


async def issue_grant(user_id: int, destination: str) -> str:
    settings = config.auth.login_exchange
    if settings is None:
        raise HTTPException(503, "Login exchange is not configured")
    grant = LoginGrant(
        user_id=user_id,
        audience=exchange_target_origin(),
        destination=relative_destination(destination),
    )
    code = secrets.token_urlsafe(32)
    try:
        async with redis_client() as redis:
            stored = await redis.set(
                exchange_key(code),
                grant.model_dump_json(),
                ex=settings.ttl_seconds,
                nx=True,
            )
    except RedisError as exc:
        raise HTTPException(503, "Login exchange unavailable") from exc
    if not stored:
        raise HTTPException(503, "Login exchange unavailable")
    return code


async def consume_grant(request: Request) -> LoginGrant:
    if not request_host_matches(request, exchange_target_origin()):
        raise HTTPException(400, "Login exchange requires the target host")
    if request.headers.get("origin") not in (None, *allowed_origins()):
        raise HTTPException(400, "Unsupported login origin")
    form = await request.form()
    code = form.get("code")
    if not isinstance(code, str) or not re.fullmatch(r"[A-Za-z0-9_-]{43}", code):
        raise HTTPException(400, "Invalid or expired login exchange")
    try:
        async with redis_client() as redis:
            raw = await redis.getdel(exchange_key(code))
    except RedisError as exc:
        raise HTTPException(503, "Login exchange unavailable") from exc
    if raw is None:
        raise HTTPException(400, "Invalid or expired login exchange")
    try:
        grant = LoginGrant.model_validate_json(raw)
    except ValueError as exc:
        raise HTTPException(400, "Invalid login exchange") from exc
    if grant.audience != exchange_target_origin():
        raise HTTPException(400, "Invalid login exchange audience")
    grant.destination = relative_destination(grant.destination)
    return grant


def session_redirect(destination: str, user_id: int, nowfn: NowFn = utcnow):
    response = redirect_with_session(
        exchange_target_origin() + relative_destination(destination),
        user_id,
        nowfn=nowfn,
    )
    response.headers.update(NO_STORE)
    return response


async def finish_saml_login(
    request: Request, user_id: int, destination: str, nowfn: NowFn = utcnow
):
    callback_origin = request_origin(request)
    target_origin = destination_origin(destination, callback_origin)
    destination = relative_destination(destination)
    if target_origin == callback_origin:
        response = redirect_with_session(
            target_origin + destination, user_id, nowfn=nowfn
        )
        response.headers.update(NO_STORE)
        return response
    # Other configured source aliases hand off to the canonical target host.
    code = await issue_grant(user_id, destination)
    nonce = secrets.token_urlsafe(24)
    action = exchange_target_origin() + EXCHANGE_PATH
    return HTMLResponse(
        "<!doctype html><html><head><meta charset='utf-8'><title>Completing sign-in</title>"
        "</head><body>"
        f'<form id="exchange" method="post" action="{escape(action, quote=True)}">'
        f'<input type="hidden" name="code" value="{escape(code, quote=True)}">'
        '<button type="submit">Continue signing in</button></form>'
        f'<script nonce="{nonce}">document.getElementById("exchange").submit();</script>'
        "</body></html>",
        headers={
            **NO_STORE,
            "Referrer-Policy": "strict-origin",
            "Content-Security-Policy": (
                f"default-src 'none'; script-src 'nonce-{nonce}'; "
                f"form-action {exchange_target_origin()}; base-uri 'none'; "
                "frame-ancestors 'none'"
            ),
            "X-Content-Type-Options": "nosniff",
        },
    )
