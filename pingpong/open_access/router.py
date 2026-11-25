import uuid_utils as uuid
from fastapi import APIRouter, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

import pingpong.models as models
import pingpong.schemas as schemas
from .. import interactive_lesson_runtime, lecture_threads
from ..session import get_now_fn
from ..state_types import StateRequest
from . import store
from ..config import config
from .access import ensure_lesson_access
from .errors import OpenAccessError, session_displaced
from .request import has_marker
from .settings import OpenAccessSettings
from .threads import delete_thread
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
    request: StateRequest,
    principal: models.ExternalPrincipal,
    grant: LaunchGrant,
) -> models.Thread:
    db = request.state["db"]
    lesson = await get_lesson(db, grant.assistant_id)
    if lesson is None:
        raise lesson_unavailable()
    assistant, class_ = lesson
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
    request: StateRequest,
    principal: models.ExternalPrincipal,
    grant: LaunchGrant,
) -> models.Thread:
    db = request.state["db"]
    thread = await get_principal_thread(db, principal.id, grant.assistant_id)
    if thread is not None:
        lesson = await get_lesson(db, grant.assistant_id)
        if (
            lesson is None
            or lesson[0].lecture_slide_deck_id == thread.lecture_slide_deck_id
        ):
            return thread
        await request.state["authz"].write_safe(revoke=await delete_thread(db, thread))
    try:
        async with db.begin_nested():
            return await create_principal_thread(request, principal, grant)
    except IntegrityError:
        thread = await get_principal_thread(db, principal.id, grant.assistant_id)
        if thread is None:
            raise
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
    ensure_lesson_access(settings, principal, grant.assistant_id)
    thread = await find_or_create_principal_thread(request, principal, grant)
    session_id = await store.start_session(settings, principal.id, grant.launch_id)
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
    ensure_lesson_access(settings, principal, grant.assistant_id)
    if not await store.extend_session(settings, principal.id, grant.sid):
        raise session_displaced()
    return await issue_launch_code(settings, principal, thread, grant.sid)


@router.post("/exchange", response_model=AccessTokenResponse)
async def exchange(req: ExchangeRequest, request: StateRequest):
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
    ensure_lesson_access(settings, principal, launch_code.assistant_id)
    if not await store.is_active_session(
        settings, principal.id, launch_code.session_id
    ):
        raise session_displaced()
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
    settings = require_request(request)
    verify_grant(settings, req.grant, CatalogueGrant)
    db = request.state["db"]
    lessons = []
    for assistant_id in settings.assistant_ids:
        lesson = await get_lesson(db, assistant_id)
        if lesson is None:
            continue
        assistant, _ = lesson
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
