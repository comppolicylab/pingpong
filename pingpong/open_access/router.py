import logging

import uuid_utils as uuid
from fastapi import APIRouter, Request, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

import pingpong.models as models
import pingpong.schemas as schemas
from .. import interactive_lesson_runtime, lecture_threads
from ..audit import audit
from ..session import get_now_fn
from ..state_types import StateRequest
from ..stream_utils import prefetch_stream
from ..video_store import VideoStoreError
from . import limits, store
from ..config import config
from .access import ensure_lesson_access
from .errors import OpenAccessError, session_displaced
from .request import ACCESS_TOKEN_COOKIE, access_token_cookie_path, has_marker
from .settings import OpenAccessSettings
from .threads import delete_thread
from .tokens import (
    CatalogueGrant,
    LaunchGrant,
    ProgressGrant,
    RenewGrant,
    ThumbnailGrant,
    TransferGrant,
    encode_access_token,
    verify_grant,
)

logger = logging.getLogger(__name__)

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
    thumbnail_version: int


class TransferResponse(BaseModel):
    thread_moved: bool


class ProgressResponse(BaseModel):
    started: list[int]


class CatalogueResponse(BaseModel):
    lessons: list[CatalogueLesson]


class PlayerConfigResponse(BaseModel):
    origin: str
    message_max_characters: int


def lesson_unavailable() -> OpenAccessError:
    return OpenAccessError(
        409, "open_access_lesson_unavailable", "This lesson is not available."
    )


def require_request(request: Request) -> OpenAccessSettings:
    settings = config.open_access
    if settings is None:
        raise OpenAccessError(404, "open_access_disabled", "Not found.")
    if not has_marker(request):
        raise OpenAccessError(
            400, "open_access_marker_missing", "Missing Open Access request marker."
        )
    return settings


async def get_principal_thread(
    db: AsyncSession, principal_id: int, assistant_id: int
) -> models.Thread | None:
    return await db.scalar(
        select(models.Thread).where(
            models.Thread.external_principal_id == principal_id,
            models.Thread.assistant_id == assistant_id,
        )
    )


async def get_lesson(
    db: AsyncSession, assistant_id: int
) -> tuple[models.Assistant, models.Class] | None:
    assistant = await models.Assistant.get_by_id_with_lecture_video(db, assistant_id)
    if (
        assistant is None
        or assistant.class_id is None
        or assistant.interaction_mode != schemas.InteractionMode.LECTURE_SLIDES
        or assistant.lecture_slide_deck is None
        or assistant.lecture_slide_deck.status != schemas.LectureSlideDeckStatus.READY
    ):
        return None
    class_ = await models.Class.get_by_id(db, assistant.class_id)
    if class_ is None or class_.archived is not None:
        return None
    return assistant, class_


async def create_principal_thread(
    settings: OpenAccessSettings,
    request: StateRequest,
    principal: models.ExternalPrincipal,
    grant: LaunchGrant,
) -> models.Thread:
    db = request.state["db"]
    lesson = await get_lesson(db, grant.assistant_id)
    if lesson is None:
        raise lesson_unavailable()
    assistant, class_ = lesson
    await limits.reserve_new_thread(settings, get_now_fn(request)())
    target = await lecture_threads.resolve_lecture_thread_target(
        db, assistant, grant.language
    )
    anonymous_session = await models.AnonymousSession.create(db, str(uuid.uuid7()))
    anonymous_session.external_principal_id = principal.id
    try:
        thread = await lecture_threads.create_lecture_thread(
            db,
            assistant=assistant,
            class_=class_,
            target=target,
            users=[],
            anonymous_session=anonymous_session,
            timezone=None,
            conversation_id=None,
            external_principal_id=principal.id,
        )
    except interactive_lesson_runtime.InteractiveLessonRuntimeError as exc:
        raise lesson_unavailable() from exc

    subject = f"anonymous_user:{anonymous_session.session_token}"
    await request.state["authz"].write_safe(
        grant=[
            (f"class:{class_.id}", "parent", f"thread:{thread.id}"),
            (subject, "anonymous_party", f"thread:{thread.id}"),
            (subject, "can_view", f"assistant:{assistant.id}"),
        ]
    )
    return thread


async def find_or_create_principal_thread(
    settings: OpenAccessSettings,
    request: StateRequest,
    principal: models.ExternalPrincipal,
    grant: LaunchGrant,
) -> models.Thread:
    db = request.state["db"]
    thread = await get_principal_thread(db, principal.id, grant.assistant_id)
    revoke = []
    if thread is not None:
        lesson = await get_lesson(db, grant.assistant_id)
        if (
            lesson is None
            or lesson[0].lecture_slide_deck_id == thread.lecture_slide_deck_id
        ):
            return thread
        revoke = await delete_thread(db, thread)
    try:
        async with db.begin_nested():
            thread = await create_principal_thread(settings, request, principal, grant)
    except IntegrityError:
        thread = await get_principal_thread(db, principal.id, grant.assistant_id)
        if thread is None:
            raise
    if revoke:
        await request.state["authz"].write_safe(revoke=revoke)
    return thread


async def issue_launch_code(
    settings: OpenAccessSettings,
    principal: models.ExternalPrincipal,
    thread: models.Thread,
    session_id: str,
) -> LaunchCodeResponse:
    code = await store.issue_code(
        settings,
        store.LaunchCode(
            principal_id=principal.id,
            thread_id=thread.id,
            class_id=thread.class_id,
            assistant_id=thread.assistant_id,
            session_id=session_id,
        ),
    )
    return LaunchCodeResponse(
        code=code, session_id=session_id, expires_in=settings.launch_code_ttl_seconds
    )


@router.post("/launch", response_model=LaunchCodeResponse)
async def launch(req: GrantRequest, request: StateRequest):
    settings = require_request(request)
    grant = verify_grant(settings, req.grant, LaunchGrant)
    principal = await models.ExternalPrincipal.get_or_create(
        request.state["db"], settings.client_id, grant.sub, grant.tier
    )
    if principal.tier != grant.tier:
        raise OpenAccessError(
            409, "open_access_tier_mismatch", "Principal tier does not match."
        )
    await ensure_lesson_access(settings, principal, grant.assistant_id)
    thread = await find_or_create_principal_thread(settings, request, principal, grant)
    previous_session_id = await store.active_session(settings, principal.id)
    session_id = await store.start_session(settings, principal.id, grant.launch_id)
    audit(
        "oa.session.start",
        principal_id=principal.id,
        tier=principal.tier,
        assistant_id=grant.assistant_id,
        thread_id=thread.id,
    )
    if (
        previous_session_id is not None
        and previous_session_id != session_id
        and await store.active_session(settings, principal.id) == session_id
    ):
        audit("oa.session.takeover", principal_id=principal.id, thread_id=thread.id)
    return await issue_launch_code(settings, principal, thread, session_id)


@router.post("/renew", response_model=LaunchCodeResponse)
async def renew(req: GrantRequest, request: StateRequest):
    settings = require_request(request)
    grant = verify_grant(settings, req.grant, RenewGrant)
    db = request.state["db"]
    principal = await db.scalar(
        select(models.ExternalPrincipal).where(
            models.ExternalPrincipal.client_id == settings.client_id,
            models.ExternalPrincipal.subject == grant.sub,
        )
    )
    thread = (
        await get_principal_thread(db, principal.id, grant.assistant_id)
        if principal is not None
        else None
    )
    if principal is None or thread is None:
        raise OpenAccessError(404, "open_access_session_missing", "Session not found.")
    await ensure_lesson_access(settings, principal, grant.assistant_id)
    if not await store.extend_session(settings, principal.id, grant.sid):
        raise session_displaced()
    audit("oa.session.renew", principal_id=principal.id, thread_id=thread.id)
    return await issue_launch_code(settings, principal, thread, grant.sid)


@router.get("/config", response_model=PlayerConfigResponse)
async def player_config(request: Request):
    settings = require_request(request)
    return PlayerConfigResponse(
        origin=settings.origin,
        message_max_characters=settings.limits.message_max_characters,
    )


@router.post("/exchange", response_model=AccessTokenResponse)
async def exchange(req: ExchangeRequest, request: StateRequest, response: Response):
    settings = require_request(request)
    launch_code = await store.consume_code(settings, req.code)
    principal = (
        await request.state["db"].get(
            models.ExternalPrincipal, launch_code.principal_id
        )
        if launch_code is not None
        else None
    )
    if launch_code is None or principal is None:
        raise OpenAccessError(
            400, "open_access_code_invalid", "Invalid or expired launch code."
        )
    await ensure_lesson_access(settings, principal, launch_code.assistant_id)
    if not await store.is_active_session(
        settings, principal.id, launch_code.session_id
    ):
        raise session_displaced()
    audit("oa.token.issue", principal_id=principal.id, thread_id=launch_code.thread_id)
    access_token = encode_access_token(
        settings,
        principal_id=principal.id,
        thread_id=launch_code.thread_id,
        class_id=launch_code.class_id,
        session_id=launch_code.session_id,
        nowfn=get_now_fn(request),
    )
    response.set_cookie(
        ACCESS_TOKEN_COOKIE,
        access_token,
        max_age=settings.access_token_ttl_seconds,
        path=access_token_cookie_path(launch_code.class_id, launch_code.thread_id),
        secure=True,
        httponly=True,
        samesite="strict",
    )
    return AccessTokenResponse(
        access_token=access_token,
        expires_in=settings.access_token_ttl_seconds,
        class_id=launch_code.class_id,
        thread_id=launch_code.thread_id,
        session_id=launch_code.session_id,
    )


@router.post("/catalogue", response_model=CatalogueResponse)
async def catalogue(req: GrantRequest, request: StateRequest):
    settings = require_request(request)
    verify_grant(settings, req.grant, CatalogueGrant)
    db = request.state["db"]
    lessons = []
    for assistant_id in settings.assistant_ids:
        lesson = await get_lesson(db, assistant_id)
        if lesson is None:
            continue
        assistant, _ = lesson
        lessons.append(
            CatalogueLesson(
                assistant_id=assistant.id,
                name=assistant.name,
                free=assistant.id == settings.free_assistant_id,
                thumbnail_version=assistant.lecture_slide_deck_id,
            )
        )
    return CatalogueResponse(lessons=lessons)


@router.post("/transfer", response_model=TransferResponse)
async def transfer(req: GrantRequest, request: StateRequest):
    settings = require_request(request)
    grant = verify_grant(settings, req.grant, TransferGrant)
    db = request.state["db"]
    source = await db.scalar(
        select(models.ExternalPrincipal).where(
            models.ExternalPrincipal.client_id == settings.client_id,
            models.ExternalPrincipal.subject == grant.sub,
            models.ExternalPrincipal.tier == schemas.ExternalPrincipalTier.ANONYMOUS,
        )
    )
    if source is None:
        return TransferResponse(thread_moved=False)
    target = await models.ExternalPrincipal.get_or_create(
        db, settings.client_id, grant.to, schemas.ExternalPrincipalTier.REGISTERED
    )
    if target.tier != schemas.ExternalPrincipalTier.REGISTERED:
        raise OpenAccessError(
            409, "open_access_tier_mismatch", "Principal tier does not match."
        )
    thread = await get_principal_thread(db, source.id, settings.free_assistant_id)
    moved = (
        thread is not None
        and await get_principal_thread(db, target.id, settings.free_assistant_id)
        is None
    )
    if moved:
        assert thread is not None
        try:
            async with db.begin_nested():
                thread.external_principal_id = target.id
                await db.execute(
                    update(models.AnonymousSession)
                    .where(
                        models.AnonymousSession.thread_id == thread.id,
                        models.AnonymousSession.external_principal_id == source.id,
                    )
                    .values(external_principal_id=target.id)
                )
        except IntegrityError:
            await db.refresh(thread)
            moved = False
    await limits.transfer_usage(
        settings,
        source.id,
        target.id,
        thread.id if moved and thread is not None else None,
        get_now_fn(request)(),
    )
    audit(
        "oa.transfer",
        source_principal_id=source.id,
        target_principal_id=target.id,
        thread_id=thread.id if moved and thread is not None else None,
    )
    return TransferResponse(thread_moved=moved)


@router.post("/progress", response_model=ProgressResponse)
async def progress(req: GrantRequest, request: StateRequest):
    settings = require_request(request)
    grant = verify_grant(settings, req.grant, ProgressGrant)
    assistant_ids = await request.state["db"].scalars(
        select(models.Thread.assistant_id)
        .join(
            models.ExternalPrincipal,
            models.ExternalPrincipal.id == models.Thread.external_principal_id,
        )
        .where(
            models.ExternalPrincipal.client_id == settings.client_id,
            models.ExternalPrincipal.subject == grant.sub,
        )
    )
    return ProgressResponse(
        started=[assistant_id for assistant_id in assistant_ids if assistant_id]
    )


@router.post("/thumbnail")
async def thumbnail(req: GrantRequest, request: StateRequest) -> Response:
    settings = require_request(request)
    grant = verify_grant(settings, req.grant, ThumbnailGrant)
    db = request.state["db"]
    lesson = (
        await get_lesson(db, grant.assistant_id)
        if grant.assistant_id in settings.assistant_ids
        else None
    )
    image = (
        await db.scalar(
            select(models.LectureSlideImageStoredObject)
            .join(
                models.LectureSlidePage,
                models.LectureSlidePage.image_stored_object_id
                == models.LectureSlideImageStoredObject.id,
            )
            .where(
                models.LectureSlidePage.lecture_slide_deck_id
                == lesson[0].lecture_slide_deck_id
            )
            .order_by(models.LectureSlidePage.position)
            .limit(1)
        )
        if lesson is not None and config.video_store
        else None
    )
    if image is None or not config.video_store:
        raise OpenAccessError(
            404, "open_access_thumbnail_unavailable", "No thumbnail for this lesson."
        )
    try:
        stream = await prefetch_stream(
            config.video_store.store.stream_video_range(key=image.key),
            store_error=VideoStoreError,
            logger=logger,
            store_error_log="VideoStoreError while streaming an open access thumbnail",
            unexpected_error_log="Unexpected error while streaming an open access thumbnail",
        )
    except VideoStoreError as exc:
        raise OpenAccessError(
            404, "open_access_thumbnail_unavailable", "No thumbnail for this lesson."
        ) from exc
    return StreamingResponse(stream, media_type=image.content_type)
