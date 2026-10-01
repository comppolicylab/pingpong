"""The removable integration surface for SAML callbacks and application startup."""

from contextlib import asynccontextmanager

from fastapi import Request
from starlette.responses import Response

from ..config import config
from ..now import NowFn, utcnow
from .cache import close_redis_clients
from .exchange import (
    finish_saml_login,
    relay_state,
    validate_login_host,
)


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


@asynccontextmanager
async def lifespan():
    try:
        yield
    finally:
        await close_redis_clients()
