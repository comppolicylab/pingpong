"""The removable integration surface for SAML callbacks and application startup."""

from contextlib import asynccontextmanager

from fastapi import APIRouter, HTTPException, Request
from starlette.responses import Response

from .. import models
from ..config import config
from ..now import NowFn, utcnow
from ..state_types import StateRequest
from .cache import close_redis_clients
from .exchange import (
    consume_grant,
    finish_saml_login,
    relay_state,
    session_redirect,
    validate_login_host,
)

router = APIRouter()


def validate_callback_host(request: Request) -> None:
    if config.auth.login_exchange is not None:
        validate_login_host(request)


def prepare_relay_state(request: Request, destination: str) -> str:
    """Preserve legacy RelayState unless the login exchange is enabled."""
    if config.auth.login_exchange is None:
        return destination
    return relay_state(request, destination)


async def finish_login(
    request: Request, user_id: int, destination: str, nowfn: NowFn = utcnow
) -> Response | None:
    """Return None to preserve the original SAML redirect when disabled."""
    if config.auth.login_exchange is None:
        return None
    return await finish_saml_login(request, user_id, destination, nowfn=nowfn)


@router.post("/login/sso/exchange")
async def login_sso_exchange(request: StateRequest):
    if config.auth.login_exchange is None:
        raise HTTPException(404, "Login exchange is not configured")
    grant = await consume_grant(request)
    user = await models.User.get_by_id(request.state["db"], grant.user_id)
    if user is None:
        raise HTTPException(400, "Invalid login exchange user")
    nowfn = getattr(request.app.state, "now", utcnow)
    return session_redirect(grant.destination, user.id, nowfn=nowfn)


@asynccontextmanager
async def lifespan():
    try:
        yield
    finally:
        await close_redis_clients()
