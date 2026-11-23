import uuid_utils as uuid
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import pingpong.models as models
import pingpong.schemas as schemas
from .. import interactive_lesson_runtime, lecture_threads
from ..config import config
from ..session import get_now_fn
from ..state_types import StateRequest
from . import store
from .request import has_marker
from .settings import OpenAccessSettings
from .tokens import (
    CatalogueGrant,
    LaunchGrant,
    RenewGrant,
    encode_access_token,
    verify_grant,
)

router = APIRouter()


class GrantRequest(BaseModel):
    grant: str = Field(min_length=1, max_length=4096)


class ExchangeRequest(BaseModel):
    code: str = Field(pattern=r"^[A-Za-z0-9_-]{43}$")


class LaunchCodeResponse(BaseModel):
    code: str
    session_id: str
    expires_in: int


class AccessTokenResponse(BaseModel):
    access_token: str
    expires_in: int
    class_id: int
    thread_id: int
    session_id: str


class CatalogueLesson(BaseModel):
    assistant_id: int
    name: str | None
    free: bool
    languages: list[schemas.LectureSlideLanguage]


class CatalogueResponse(BaseModel):
    lessons: list[CatalogueLesson]


def require_settings(request: Request) -> OpenAccessSettings:
    settings = config.open_access
    if settings is None:
        raise HTTPException(404, "Not found")
    if not has_marker(request):
        raise HTTPException(400, "Missing Open Access request marker")
    if settings.paused:
        raise HTTPException(503, "Open Access is paused")
    return settings


def require_tier_open(
    settings: OpenAccessSettings, tier: schemas.ExternalPrincipalTier
) -> None:
    if settings.anonymous_paused and tier == schemas.ExternalPrincipalTier.ANONYMOUS:
        raise HTTPException(503, "Open Access is paused")


def require_not_banned(principal: models.ExternalPrincipal) -> None:
    if principal.banned_at is not None:
        raise HTTPException(403, "Access has been revoked")


async def get_principal_thread(
    db: AsyncSession, principal_id: int, assistant_id: int
) -> models.Thread | None:
    return await db.scalar(
        select(models.Thread).where(
            models.Thread.external_principal_id == principal_id,
            models.Thread.assistant_id == assistant_id,
        )
    )


async def create_principal_thread(
    request: StateRequest,
    principal: models.ExternalPrincipal,
    grant: LaunchGrant,
) -> models.Thread:
    db = request.state["db"]
    assistant = await models.Assistant.get_by_id_with_lecture_video(
        db, grant.assistant_id
    )
    if assistant is None or assistant.class_id is None:
        raise HTTPException(404, "Lesson not found")
    class_ = await models.Class.get_by_id(db, assistant.class_id)
    if class_ is None:
        raise HTTPException(404, "Lesson not found")
    target = await lecture_threads.resolve_lecture_thread_target(
        db, assistant, grant.language
    )

    link = await models.AnonymousLink.create_unlisted(db, str(uuid.uuid7()))
    user = await models.User.create_anonymous_user(db, anonymous_link_id=link.id)
    anonymous_session = await models.AnonymousSession.create(
        db, str(uuid.uuid7()), user_id=user.id
    )
    anonymous_session.external_principal_id = principal.id
    try:
        thread = await lecture_threads.create_lecture_thread(
            db,
            assistant=assistant,
            class_=class_,
            target=target,
            users=[user],
            anonymous_session=anonymous_session,
            timezone=None,
            conversation_id=None,
            external_principal_id=principal.id,
        )
    except interactive_lesson_runtime.InteractiveLessonRuntimeError as exc:
        raise HTTPException(409, "This lesson is not available right now") from exc

    link_auth = f"anonymous_link:{link.share_token}"
    await request.state["authz"].write_safe(
        grant=[
            (f"class:{class_.id}", "parent", f"thread:{thread.id}"),
            (
                f"anonymous_user:{anonymous_session.session_token}",
                "anonymous_party",
                f"thread:{thread.id}",
            ),
            (link_auth, "can_view", f"class:{class_.id}"),
            (link_auth, "can_view", f"assistant:{assistant.id}"),
        ]
    )
    return thread


@router.post("/launch", response_model=LaunchCodeResponse)
async def launch(req: GrantRequest, request: StateRequest):
    settings = require_settings(request)
    grant = verify_grant(settings, req.grant, LaunchGrant)
    require_tier_open(settings, grant.tier)
    if grant.assistant_id not in settings.assistant_ids:
        raise HTTPException(404, "Lesson not found")
    if (
        grant.tier == schemas.ExternalPrincipalTier.ANONYMOUS
        and grant.assistant_id != settings.free_assistant_id
    ):
        raise HTTPException(403, "Sign up to access this lesson")

    db = request.state["db"]
    principal = await models.ExternalPrincipal.get_or_create(
        db, settings.client_id, grant.sub, grant.tier
    )
    if principal.tier != grant.tier:
        raise HTTPException(409, "Principal tier mismatch")
    require_not_banned(principal)

    thread = await get_principal_thread(db, principal.id, grant.assistant_id)
    if thread is None:
        thread = await create_principal_thread(request, principal, grant)

    session_id = await store.start_session(settings, principal.id, grant.launch_id)
    code = await store.issue_code(
        settings,
        store.LaunchCode(
            principal_id=principal.id,
            thread_id=thread.id,
            class_id=thread.class_id,
            session_id=session_id,
        ),
    )
    return LaunchCodeResponse(
        code=code, session_id=session_id, expires_in=settings.launch_code_ttl_seconds
    )


@router.post("/renew", response_model=LaunchCodeResponse)
async def renew(req: GrantRequest, request: StateRequest):
    settings = require_settings(request)
    grant = verify_grant(settings, req.grant, RenewGrant)
    db = request.state["db"]
    principal = await db.scalar(
        select(models.ExternalPrincipal).where(
            models.ExternalPrincipal.client_id == settings.client_id,
            models.ExternalPrincipal.subject == grant.sub,
        )
    )
    if principal is None:
        raise HTTPException(404, "Session not found")
    require_tier_open(settings, principal.tier)
    require_not_banned(principal)
    thread = await get_principal_thread(db, principal.id, grant.assistant_id)
    if thread is None:
        raise HTTPException(404, "Session not found")
    if not await store.extend_session(settings, principal.id, grant.sid):
        raise HTTPException(
            409,
            {"message": "Continued elsewhere", "error_code": "session_displaced"},
        )
    code = await store.issue_code(
        settings,
        store.LaunchCode(
            principal_id=principal.id,
            thread_id=thread.id,
            class_id=thread.class_id,
            session_id=grant.sid,
        ),
    )
    return LaunchCodeResponse(
        code=code, session_id=grant.sid, expires_in=settings.launch_code_ttl_seconds
    )


@router.post("/exchange", response_model=AccessTokenResponse)
async def exchange(req: ExchangeRequest, request: StateRequest):
    settings = require_settings(request)
    launch_code = await store.consume_code(settings, req.code)
    if launch_code is None:
        raise HTTPException(400, "Invalid or expired launch code")
    principal = await request.state["db"].get(
        models.ExternalPrincipal, launch_code.principal_id
    )
    if principal is None:
        raise HTTPException(400, "Invalid or expired launch code")
    require_tier_open(settings, principal.tier)
    require_not_banned(principal)
    if not await store.is_active_session(
        settings, principal.id, launch_code.session_id
    ):
        raise HTTPException(
            409,
            {"message": "Continued elsewhere", "error_code": "session_displaced"},
        )
    return AccessTokenResponse(
        access_token=encode_access_token(
            settings,
            principal_id=principal.id,
            thread_id=launch_code.thread_id,
            class_id=launch_code.class_id,
            session_id=launch_code.session_id,
            nowfn=get_now_fn(request),
        ),
        expires_in=settings.access_token_ttl_seconds,
        class_id=launch_code.class_id,
        thread_id=launch_code.thread_id,
        session_id=launch_code.session_id,
    )


@router.post("/catalogue", response_model=CatalogueResponse)
async def catalogue(req: GrantRequest, request: StateRequest):
    settings = require_settings(request)
    verify_grant(settings, req.grant, CatalogueGrant)
    db = request.state["db"]
    lessons = []
    for assistant_id in settings.assistant_ids:
        assistant = await models.Assistant.get_by_id_with_lecture_video(
            db, assistant_id
        )
        if assistant is None or assistant.lecture_slide_deck is None:
            continue
        languages = [schemas.LectureSlideLanguage(code="original", name="Original")]
        for translation in await models.LectureSlideTranslation.list_by_deck(
            db, assistant.lecture_slide_deck_id
        ):
            if await lecture_threads.translation_is_playable(
                db, assistant.lecture_slide_deck, translation
            ):
                languages.append(
                    schemas.LectureSlideLanguage(
                        code=translation.language_code, name=translation.language_name
                    )
                )
        lessons.append(
            CatalogueLesson(
                assistant_id=assistant.id,
                name=assistant.name,
                free=assistant.id == settings.free_assistant_id,
                languages=languages,
            )
        )
    return CatalogueResponse(lessons=lessons)
