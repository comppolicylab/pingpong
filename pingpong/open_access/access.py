import re
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import pingpong.models as models
import pingpong.schemas as schemas
from ..config import config
from ..now import NowFn
from . import limits, store
from .errors import OpenAccessError, session_displaced, token_invalid
from .settings import OpenAccessSettings
from .tokens import AccessClaims, decode_access_token

_THREAD = r"/api/v1/class/(?P<class_id>\d+)/thread/(?P<thread_id>\d+)"
_SLIDES = _THREAD + r"/lecture-slides"

PLAYER_ROUTES: tuple[tuple[str, re.Pattern[str]], ...] = tuple(
    (method, re.compile(pattern))
    for method, pattern in (
        ("GET", _THREAD),
        ("GET", _THREAD + r"/messages"),
        ("POST", _THREAD),
        ("GET", _THREAD + r"/lesson/history"),
        ("GET", _THREAD + r"/assistant-avatar"),
        ("GET", _SLIDES + r"/audio"),
        ("GET", _SLIDES + r"/captions\.vtt"),
        ("GET", _SLIDES + r"/[^/]+/narration"),
        ("GET", _SLIDES + r"/[^/]+/image"),
        ("GET", _SLIDES + r"/narration/[^/]+"),
        ("POST", _THREAD + r"/lecture-slide/control/(?:acquire|release|renew)"),
        ("POST", _THREAD + r"/lecture-slide/interactions"),
    )
)


@dataclass
class OpenAccessContext:
    claims: AccessClaims
    principal: models.ExternalPrincipal
    anonymous_session: models.AnonymousSession
    assistant_id: int


async def ensure_lesson_access(
    settings: OpenAccessSettings,
    principal: models.ExternalPrincipal,
    assistant_id: int,
) -> None:
    anonymous = principal.tier == schemas.ExternalPrincipalTier.ANONYMOUS
    if await limits.is_paused(settings, anonymous=anonymous):
        raise OpenAccessError(503, "open_access_paused", "Open Access is paused.")
    if assistant_id not in settings.assistant_ids or (
        anonymous and assistant_id != settings.free_assistant_id
    ):
        raise OpenAccessError(
            403, "open_access_lesson_unavailable", "This lesson is not available."
        )


def player_route_thread(method: str, path: str) -> tuple[int, int] | None:
    for route_method, pattern in PLAYER_ROUTES:
        if route_method == method and (match := pattern.fullmatch(path)):
            return int(match["class_id"]), int(match["thread_id"])
    return None


def is_player_route(method: str, path: str) -> bool:
    return player_route_thread(method, path) is not None


async def authenticate(
    db: AsyncSession,
    *,
    method: str,
    path: str,
    token: str,
    has_marker: bool,
    nowfn: NowFn,
) -> OpenAccessContext:
    settings = config.open_access
    claims = (
        decode_access_token(settings, token, nowfn=nowfn)
        if settings is not None and has_marker
        else None
    )
    if settings is None or claims is None:
        raise token_invalid()
    if player_route_thread(method, path) != (claims.cid, claims.tid):
        raise OpenAccessError(
            403, "open_access_route_forbidden", "This request is not allowed."
        )
    row = (
        await db.execute(
            select(
                models.AnonymousSession,
                models.ExternalPrincipal,
                models.Thread.assistant_id,
            )
            .join(
                models.ExternalPrincipal,
                models.ExternalPrincipal.id
                == models.AnonymousSession.external_principal_id,
            )
            .join(models.Thread, models.Thread.id == models.AnonymousSession.thread_id)
            .where(
                models.AnonymousSession.external_principal_id == claims.pid,
                models.AnonymousSession.thread_id == claims.tid,
                models.Thread.class_id == claims.cid,
                models.Thread.external_principal_id == claims.pid,
            )
        )
    ).first()
    if row is None:
        raise token_invalid()
    anonymous_session, principal, assistant_id = row
    await ensure_lesson_access(settings, principal, assistant_id)
    if not await store.is_active_session(settings, principal.id, claims.sid):
        raise session_displaced()
    return OpenAccessContext(claims, principal, anonymous_session, assistant_id)
