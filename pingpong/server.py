import asyncio
import json
import logging
import time
from datetime import datetime
from typing import Annotated, Any

import jwt
import openai
from fastapi import (
    BackgroundTasks,
    Depends,
    FastAPI,
    HTTPException,
    Request,
    Response,
    UploadFile,
)
from fastapi.responses import JSONResponse, RedirectResponse
from jwt.exceptions import PyJWTError
from sqlalchemy.sql import func

import pingpong.metrics as metrics
import pingpong.models as models
import pingpong.schemas as schemas

from .ai import format_instructions, generate_name, get_openai_client, hash_thread
from .auth import (
    decode_auth_token,
    decode_session_token,
    encode_session_token,
    generate_auth_link,
)
from .config import config
from .errors import sentry
from .files import FILE_TYPES, handle_create_file, handle_delete_file
from .invite import send_invite
from .permission import Authz, CanManage, CanRead, CanWrite, IsSuper, IsUser, LoggedIn

logger = logging.getLogger(__name__)

v1 = FastAPI()


async def get_openai_client_for_class(request: Request) -> openai.AsyncClient:
    """Get an OpenAI client for the class.

    Requires the class_id to be in the path parameters.
    """
    class_id = request.path_params["class_id"]
    api_key = await models.Class.get_api_key(request.state.db, int(class_id))
    if not api_key:
        raise HTTPException(status_code=401, detail="No API key for class")
    return get_openai_client(api_key)


OpenAIClientDependency = Depends(get_openai_client_for_class)
OpenAIClient = Annotated[openai.AsyncClient, OpenAIClientDependency]


@v1.middleware("http")
async def parse_session_token(request: Request, call_next):
    """Parse the session token from the cookie and add it to the request state."""
    try:
        session_token = request.cookies["session"]
    except KeyError:
        request.state.session = schemas.SessionState(
            status=schemas.SessionStatus.MISSING,
        )
    else:
        try:
            token = decode_session_token(session_token)
            user = await models.User.get_by_id(request.state.db, int(token.sub))
            if not user:
                raise ValueError("User does not exist")

            # Modify user state if necessary
            if user.state == schemas.UserState.UNVERIFIED:
                await user.verify(request.state.db)

            request.state.session = schemas.SessionState(
                token=token,
                status=schemas.SessionStatus.VALID,
                error=None,
                user=user,
                profile=schemas.Profile.from_email(user.email),
            )
        except PyJWTError as e:
            request.state.session = schemas.SessionState(
                status=schemas.SessionStatus.INVALID,
                error=str(e),
            )
        except Exception as e:
            request.state.session = schemas.SessionState(
                status=schemas.SessionStatus.ERROR,
                error=str(e),
            )

    return await call_next(request)


@v1.middleware("http")
async def begin_authz_session(request: Request, call_next):
    """Connect to authorization server."""
    async with config.authz.driver.get_client() as c:
        request.state.authz = c
        response = await call_next(request)
        await c.close()
        return response


@v1.middleware("http")
async def begin_db_session(request: Request, call_next):
    """Create a database session for the request."""
    async with config.db.driver.async_session() as db:
        request.state.db = db
        try:
            result = await call_next(request)
            await db.commit()
            return result
        except Exception as e:
            await db.rollback()
            raise e


@v1.middleware("http")
async def log_request(request: Request, call_next):
    """Log the request."""
    metrics.in_flight.inc(app=config.public_url)
    start_time = time.monotonic()
    result = None
    try:
        result = await call_next(request)
        return result
    finally:
        metrics.in_flight.dec(app=config.public_url)
        status = result.status_code if result else 500
        duration = time.monotonic() - start_time
        metrics.api_requests.inc(
            app=config.public_url,
            route=request.url.path,
            method=request.method,
            status=status,
        )
        metrics.api_request_duration.observe(
            duration,
            app=config.public_url,
            route=request.url.path,
            method=request.method,
            status=status,
        )


@v1.get("/config", dependencies=[Depends(Authz("admin"))])
def get_config(request: Request):
    return {"config": config.dict(), "headers": dict(request.headers)}


@v1.post("/login/magic", response_model=schemas.GenericStatus)
async def login(body: schemas.MagicLoginRequest, request: Request):
    """Provide a magic link to the auth endpoint."""
    # Get the email from the request.
    email = body.email
    # Look up the user by email
    user = await models.User.get_by_email(request.state.db, email)
    # Throw an error if the user does not exist.
    if not user:
        if config.development:
            user = models.User(email=email)
            user.name = ""
            user.super_admin = True
            request.state.db.add(user)
            await request.state.db.commit()
            await request.state.db.refresh(user)
        else:
            raise HTTPException(status_code=401, detail="User does not exist")
    magic_link = generate_auth_link(user.id, expiry=86_400)

    await config.email.sender.send(
        email,
        "Your PingPong login link!",
        f"Click this link to log in to PingPong: {magic_link}",
    )

    return {"status": "ok"}


@v1.get("/auth")
async def auth(request: Request, response: Response):
    # Get the `token` query parameter from the request and store it in variable.
    dest = request.query_params.get("redirect")
    stok = request.query_params.get("token")
    try:
        auth_token = decode_auth_token(stok)
    except jwt.exceptions.PyJWTError as e:
        raise HTTPException(status_code=401, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    # Create a token for the user with more information.
    session_dur = 86_400 * 30
    session_token = encode_session_token(int(auth_token.sub), expiry=session_dur)

    response = RedirectResponse(config.url(dest), status_code=303)
    response.set_cookie(key="session", value=session_token, max_age=session_dur)
    return response


@v1.get(
    "/institutions",
    dependencies=[Depends(LoggedIn())],
    response_model=schemas.Institutions,
)
async def list_institutions(request: Request):
    inst = list[models.Institution]()

    if await IsSuper().test_with_cache(request):
        inst = await models.Institution.all(request.state.db)
    else:
        inst = await models.Institution.visible(
            request.state.db, request.state.session.user
        )

    return {"institutions": inst}


@v1.post(
    "/institution",
    dependencies=[Depends(Authz("institution_creator"))],
    response_model=schemas.Institution,
)
async def create_institution(create: schemas.CreateInstitution, request: Request):
    return await models.Institution.create(request.state.db, create)


@v1.get(
    "/institution/{institution_id}",
    dependencies=[Depends(IsSuper() | CanRead(models.Institution, "institution_id"))],
    response_model=schemas.Institution,
)
async def get_institution(institution_id: str, request: Request):
    return await models.Institution.get_by_id(request.state.db, int(institution_id))


@v1.get(
    "/institution/{institution_id}/classes",
    dependencies=[Depends(IsSuper() | CanRead(models.Institution, "institution_id"))],
    response_model=schemas.Classes,
)
async def get_institution_classes(institution_id: str, request: Request):
    classes = await models.Class.get_by_institution(
        request.state.db, int(institution_id)
    )
    return {"classes": classes}


@v1.post(
    "/institution/{institution_id}/class",
    dependencies=[Depends(IsSuper() | CanWrite(models.Institution, "institution_id"))],
    response_model=schemas.Class,
)
async def create_class(
    institution_id: str, create: schemas.CreateClass, request: Request
):
    new_class = await models.Class.create(request.state.db, int(institution_id), create)

    # Create an entry for the creator as the owner
    ucr = models.UserClassRole(
        user_id=request.state.session.user.id,
        class_id=new_class.id,
        role=schemas.Role.ADMIN,
        title="Owner",
    )
    request.state.db.add(ucr)
    return new_class


@v1.get(
    "/classes",
    dependencies=[Depends(LoggedIn())],
    response_model=schemas.Classes,
)
async def get_my_classes(request: Request):
    classes = await models.Class.visible(request.state.db, request.state.session.user)
    return {"classes": classes}


@v1.get(
    "/class/{class_id}",
    dependencies=[Depends(IsSuper() | CanRead(models.Class, "class_id"))],
    response_model=schemas.Class,
)
async def get_class(class_id: str, request: Request):
    return await models.Class.get_by_id(request.state.db, int(class_id))


@v1.get(
    "/class/{class_id}/upload_info",
    dependencies=[Depends(IsSuper() | CanRead(models.Class, "class_id"))],
    response_model=schemas.FileUploadSupport,
)
async def get_class_upload_info(class_id: str, request: Request):
    return {
        "types": FILE_TYPES,
        "allow_private": True,
        "private_file_max_size": config.upload.private_file_max_size,
        "class_file_max_size": config.upload.class_file_max_size,
    }


@v1.put(
    "/class/{class_id}",
    dependencies=[Depends(IsSuper() | CanManage(models.Class, "class_id"))],
    response_model=schemas.Class,
)
async def update_class(class_id: str, update: schemas.UpdateClass, request: Request):
    return await models.Class.update(request.state.db, int(class_id), update)


@v1.get(
    "/class/{class_id}/users",
    dependencies=[Depends(IsSuper() | CanWrite(models.Class, "class_id"))],
    response_model=schemas.ClassUsers,
)
async def list_class_users(class_id: str, request: Request):
    users = await models.Class.get_users(request.state.db, int(class_id))
    return {"users": users}


@v1.post(
    "/class/{class_id}/user",
    dependencies=[Depends(IsSuper() | CanManage(models.Class, "class_id"))],
    response_model=schemas.UserClassRoles,
)
async def add_users_to_class(
    class_id: str,
    new_ucr: schemas.CreateUserClassRoles,
    request: Request,
    tasks: BackgroundTasks,
):
    cid = int(class_id)
    class_ = await models.Class.get_by_id(request.state.db, cid)
    result: list[schemas.UserClassRole] = []
    new_: list[schemas.CreateInvite] = []
    for ucr in new_ucr.roles:
        user = await models.User.get_or_create_by_email(request.state.db, ucr.email)
        if user.id == request.state.session.user.id:
            if ucr.role != schemas.Role.ADMIN:
                raise HTTPException(status_code=403, detail="Cannot demote yourself")

        existing = await models.UserClassRole.get(request.state.db, user.id, cid)
        if existing:
            existing.role = ucr.role
            existing.title = ucr.title
            result.append(existing)
            request.state.db.add(existing)
        else:
            # Make sure the user exists...
            added = await models.UserClassRole.create(
                request.state.db, user.id, cid, ucr
            )
            new_.append(
                schemas.CreateInvite(
                    user_id=user.id,
                    email=user.email,
                    class_name=class_.name,
                )
            )
            result.append(added)

    # Send emails to new users in the background
    for invite in new_:
        magic_link = generate_auth_link(invite.user_id, expiry=86_400 * 7)
        tasks.add_task(
            send_invite,
            config.email.sender,
            invite,
            magic_link,
            new_ucr.silent,
        )

    return {"roles": result}


@v1.put(
    "/class/{class_id}/user/{user_id}",
    dependencies=[Depends(IsSuper() | CanManage(models.Class, "class_id"))],
    response_model=schemas.UserClassRole,
)
async def update_user_class_role(
    class_id: str, user_id: str, update: schemas.UpdateUserClassRole, request: Request
):
    cid = int(class_id)
    uid = int(user_id)
    if uid == request.state.session.user.id and update.role != schemas.Role.ADMIN:
        raise HTTPException(status_code=403, detail="Cannot demote yourself")
    existing = await models.UserClassRole.get(request.state.db, uid, cid)
    if not existing:
        raise HTTPException(status_code=404, detail="User not found in class")
    existing.role = update.role
    existing.title = update.title
    request.state.db.add(existing)
    return existing


@v1.put(
    "/class/{class_id}/api_key",
    dependencies=[Depends(IsSuper() | CanManage(models.Class, "class_id"))],
    response_model=schemas.ApiKey,
)
async def update_class_api_key(
    class_id: str, update: schemas.UpdateApiKey, request: Request
):
    await models.Class.update_api_key(request.state.db, int(class_id), update.api_key)
    return {"api_key": update.api_key}


@v1.get(
    "/class/{class_id}/api_key",
    dependencies=[Depends(IsSuper() | CanManage(models.Class, "class_id"))],
    response_model=schemas.ApiKey,
)
async def get_class_api_key(class_id: str, request: Request):
    api_key = await models.Class.get_api_key(request.state.db, int(class_id))
    return {"api_key": api_key}


@v1.get(
    "/class/{class_id}/models",
    dependencies=[Depends(IsSuper() | CanRead(models.Class, "class_id"))],
    response_model=schemas.AssistantModels,
)
async def list_class_models(
    class_id: str, request: Request, openai_client: OpenAIClient
):
    """List available models for the class assistants."""
    all_models = await openai_client.models.list()
    # Models known to work with file_retrieval, which we always have on.
    known_models = {
        "gpt-4-0125-preview",
        "gpt-4-1106-preview",
        "gpt-4-turbo-preview",
        "gpt-3.5-turbo-1106",
    }
    # Only GPT-* models are currently available for assistants.
    # TODO - there might be other filters we need.
    filtered = [
        {
            "id": m.id,
            "created": datetime.fromtimestamp(m.created),
            "owner": m.owned_by,
        }
        for m in all_models.data
        if m.id in known_models
    ]
    return {"models": filtered}


@v1.get(
    "/class/{class_id}/thread/{thread_id}",
    dependencies=[
        Depends(
            CanWrite(models.Class, "class_id")
            | CanRead(models.Thread, "thread_id")
            | IsSuper()
        )
    ],
    response_model=schemas.ThreadWithMeta,
)
async def get_thread(
    class_id: str, thread_id: str, request: Request, openai_client: OpenAIClient
):
    thread = await models.Thread.get_by_id(request.state.db, int(thread_id))

    runs = [
        r
        async for r in await openai_client.beta.threads.runs.list(
            thread.thread_id, limit=1, order="desc"
        )
    ]

    messages = await openai_client.beta.threads.messages.list(thread.thread_id)
    user_ids = {m.metadata.get("user_id") for m in messages.data} - {None}
    users = await models.User.get_all_by_id(request.state.db, list(user_ids))
    assistants = await models.Assistant.get_all_by_id(
        request.state.db, [thread.assistant_id]
    )
    return {
        "hash": hash_thread(messages, runs),
        "thread": thread,
        "run": runs[0] if runs else None,
        "messages": list(messages.data),
        "participants": {
            "user": {u.id: schemas.Profile.from_email(u.email) for u in users},
            "assistant": {a.id: a.name for a in assistants},
        },
    }


@v1.get(
    "/class/{class_id}/thread/{thread_id}/last_run",
    dependencies=[
        Depends(
            CanWrite(models.Class, "class_id")
            | CanRead(models.Thread, "thread_id")
            | IsSuper()
        )
    ],
    response_model=schemas.ThreadRun,
)
async def get_last_run(
    class_id: str,
    thread_id: str,
    request: Request,
    openai_client: OpenAIClient,
    block: bool = True,
):
    TIMEOUT = 60  # seconds
    thread = await models.Thread.get_by_id(request.state.db, int(thread_id))

    # Streaming is not supported right now, so we need to poll to get the last run.
    # https://platform.openai.com/docs/assistants/how-it-works/runs-and-run-steps
    runs = [
        r
        async for r in await openai_client.beta.threads.runs.list(
            thread.thread_id, limit=1, order="desc"
        )
    ]

    if not runs:
        return {"thread": thread, "run": None}

    last_run = runs[0]

    if not block:
        return {"thread": thread, "run": last_run}

    t0 = time.monotonic()
    while last_run.status not in {"completed", "failed", "expired", "cancelled"}:
        if time.monotonic() - t0 > TIMEOUT:
            raise HTTPException(
                status_code=504, detail="Timeout waiting for run to complete"
            )
        # Poll until the run is complete.
        await asyncio.sleep(1)
        try:
            last_run = await openai_client.beta.threads.runs.retrieve(
                last_run.id, thread_id=thread.thread_id
            )
        except openai.APIConnectionError as e:
            logger.error("Error connecting to OpenAI: %s", e)
            # Contine polling

    return {"thread": thread, "run": last_run}


@v1.get(
    "/class/{class_id}/threads",
    dependencies=[Depends(CanRead(models.Class, "class_id") | IsSuper())],
    response_model=schemas.Threads,
)
async def list_threads(class_id: str, request: Request):
    threads = list[models.Thread]()

    perm_coros = [
        IsSuper().test_with_cache(request),
        CanManage(models.Class, "class_id").test_with_cache(request),
    ]
    if any(await asyncio.gather(*perm_coros)):
        threads = await models.Thread.all(request.state.db, int(class_id))
    else:
        threads = await models.Thread.visible(
            request.state.db, int(class_id), request.state.session.user
        )

    return {"threads": threads}


@v1.post(
    "/class/{class_id}/thread",
    dependencies=[Depends(IsSuper() | CanRead(models.Class, "class_id"))],
    response_model=schemas.ThreadRun,
)
async def create_thread(
    class_id: str,
    req: schemas.CreateThread,
    request: Request,
    openai_client: OpenAIClient,
):
    parties = list[models.User]()
    if req.parties:
        parties = await models.User.get_all_by_id(request.state.db, req.parties)

    name = await generate_name(openai_client, req.message)

    thread = await openai_client.beta.threads.create(
        messages=[
            {
                "metadata": {"user_id": request.state.session.user.id},
                "role": "user",
                "content": req.message,
                "file_ids": req.file_ids,
            }
        ]
    )

    new_thread = {
        "class_id": int(class_id),
        "name": name,
        "private": True if parties else False,
        "users": parties or [],
        "thread_id": thread.id,
        "assistant_id": req.assistant_id,
    }

    result: None | models.Thread = None
    try:
        result = await models.Thread.create(request.state.db, new_thread)
        asst = await models.Assistant.get_by_id(request.state.db, req.assistant_id)

        # Start a new thread run.
        run = await openai_client.beta.threads.runs.create(
            thread_id=thread.id,
            assistant_id=asst.assistant_id,
        )

        return {"thread": result, "run": run}
    except Exception as e:
        await openai_client.beta.threads.delete(thread.id)
        if result:
            await result.delete(request.state.db)
        raise e


@v1.post(
    "/class/{class_id}/thread/{thread_id}",
    dependencies=[
        Depends(
            IsSuper()
            | CanWrite(models.Class, "class_id")
            | CanRead(models.Thread, "thread_id")
        )
    ],
    response_model=schemas.ThreadRun,
)
async def send_message(
    class_id: str,
    thread_id: str,
    data: schemas.NewThreadMessage,
    request: Request,
    openai_client: OpenAIClient,
):
    thread = await models.Thread.get_by_id(request.state.db, int(thread_id))
    asst = await models.Assistant.get_by_id(request.state.db, thread.assistant_id)

    await openai_client.beta.threads.messages.create(
        thread.thread_id,
        role="user",
        content=data.message,
        file_ids=data.file_ids,
        metadata={"user_id": request.state.session.user.id},
    )

    run = await openai_client.beta.threads.runs.create(
        thread_id=thread.thread_id,
        assistant_id=asst.assistant_id,
    )

    metrics.inbound_messages.inc(
        app=config.public_url,
        class_=int(class_id),
        user=request.state.session.user.id,
        thread=thread.thread_id,
    )

    thread.updated = func.now()
    request.state.db.add(thread)
    await request.state.db.commit()
    await request.state.db.refresh(thread)

    return {"thread": thread, "run": run}


@v1.post(
    "/class/{class_id}/file",
    dependencies=[Depends(IsSuper() | CanWrite(models.Class, "class_id"))],
    response_model=schemas.File,
)
async def create_file(
    class_id: str, request: Request, upload: UploadFile, openai_client: OpenAIClient
):
    if upload.size > config.upload.class_file_max_size:
        raise HTTPException(
            status_code=413,
            detail=f"File too large. Max size is {config.upload.class_file_max_size} bytes.",
        )

    return await handle_create_file(
        request.state.db,
        openai_client,
        upload=upload,
        class_id=int(class_id),
        uploader_id=request.state.session.user.id,
        private=False,
    )


@v1.post(
    "/class/{class_id}/user/{user_id}/file",
    dependencies=[
        Depends(IsSuper() | (IsUser("user_id") & CanRead(models.Class, "class_id")))
    ],
    response_model=schemas.File,
)
async def create_user_file(
    class_id: str,
    user_id: str,
    request: Request,
    upload: UploadFile,
    openai_client: OpenAIClient,
):
    if upload.size > config.upload.private_file_max_size:
        raise HTTPException(
            status_code=413,
            detail=f"File too large. Max size is {config.upload.private_file_max_size} bytes.",
        )

    return await handle_create_file(
        request.state.db,
        openai_client,
        upload=upload,
        class_id=int(class_id),
        uploader_id=request.state.session.user.id,
        private=True,
    )


@v1.delete(
    "/class/{class_id}/file/{file_id}",
    # TODO: file-level permissions
    dependencies=[Depends(IsSuper() | CanWrite(models.Class, "class_id"))],
    response_model=schemas.GenericStatus,
)
async def delete_file(
    class_id: str, file_id: str, request: Request, openai_client: OpenAIClient
):
    return await handle_delete_file(request.state.db, openai_client, int(file_id))


@v1.delete(
    "/class/{class_id}/user/{user_id}/file/{file_id}",
    dependencies=[
        Depends(IsSuper() | (IsUser("user_id") & CanRead(models.Class, "class_id")))
    ],
    response_model=schemas.GenericStatus,
)
async def delete_user_file(
    class_id: str,
    user_id: str,
    file_id: str,
    request: Request,
    openai_client: OpenAIClient,
):
    return await handle_delete_file(request.state.db, openai_client, int(file_id))


@v1.get(
    "/class/{class_id}/files",
    dependencies=[Depends(IsSuper() | CanRead(models.Class, "class_id"))],
    response_model=schemas.Files,
)
async def list_files(class_id: str, request: Request):
    files = await models.File.for_class(request.state.db, int(class_id))
    return {"files": files}


@v1.get(
    "/class/{class_id}/assistants",
    dependencies=[Depends(IsSuper() | CanRead(models.Class, "class_id"))],
    response_model=schemas.Assistants,
)
async def list_assistants(class_id: str, request: Request):
    include_private = await IsSuper().test_with_cache(request) or await CanWrite(
        models.Class, "class_id"
    ).test_with_cache(request)

    assts = await models.Assistant.for_class(
        request.state.db,
        int(class_id),
        user_id=request.state.session.user.id,
        include_all_private=include_private,
    )
    creator_ids = {a.creator_id for a in assts}
    creators = await models.User.get_all_by_id(request.state.db, list(creator_ids))

    # Hide the prompt if requested and the user doesn't have elevated permissions.
    has_elevated_permissions = await IsSuper().test_with_cache(
        request
    ) or await CanWrite(models.Class, "class_id").test_with_cache(request)

    ret_assistants = list[schemas.Assistant]()

    for asst in assts:
        cur_asst = schemas.Assistant.from_orm(asst)
        if (
            asst.hide_prompt
            and not has_elevated_permissions
            and asst.creator_id != request.state.session.user.id
        ):
            cur_asst.instructions = ""
        ret_assistants.append(cur_asst)

    return {
        "assistants": ret_assistants,
        "creators": {c.id: schemas.Profile.from_email(c.email) for c in creators},
    }


@v1.post(
    "/class/{class_id}/assistant",
    dependencies=[Depends(IsSuper() | CanRead(models.Class, "class_id"))],
    response_model=schemas.Assistant,
)
async def create_assistant(
    class_id: str,
    req: schemas.CreateAssistant,
    request: Request,
    openai_client: OpenAIClient,
):
    class_id_int = int(class_id)
    cls = await models.Class.get_by_id(request.state.db, class_id_int)

    # Check additional permissions
    if not cls.any_can_create_assistant or not cls.any_can_publish_assistant:
        can_override = await IsSuper().test_with_cache(request) or await CanWrite(
            models.Class, "class_id"
        ).test_with_cache(request)
        if not can_override:
            if not cls.any_can_create_assistant:
                raise HTTPException(
                    status_code=403,
                    detail="You are not allowed to create assistants for this class.",
                )
            if not cls.any_can_publish_assistant and req.published:
                raise HTTPException(
                    status_code=403,
                    detail="You are not allowed to publish assistants for this class.",
                )

    creator_id = request.state.session.user.id

    try:
        new_asst = await openai_client.beta.assistants.create(
            instructions=format_instructions(req.instructions, use_latex=req.use_latex),
            model=req.model,
            tools=req.tools,
            metadata={"class_id": class_id_int, "creator_id": creator_id},
            file_ids=req.file_ids,
        )
    except openai.BadRequestError as e:
        raise HTTPException(400, e.message or "OpenAI rejected this request")

    try:
        return await models.Assistant.create(
            request.state.db,
            req,
            class_id=class_id_int,
            user_id=creator_id,
            assistant_id=new_asst.id,
        )
    except Exception as e:
        await openai_client.beta.assistants.delete(new_asst.id)
        raise e


@v1.put(
    "/class/{class_id}/assistant/{assistant_id}",
    dependencies=[Depends(IsSuper() | CanManage(models.Assistant, "assistant_id"))],
    response_model=schemas.Assistant,
)
async def update_assistant(
    class_id: str,
    assistant_id: str,
    req: schemas.UpdateAssistant,
    request: Request,
    openai_client: OpenAIClient,
):
    # Get the existing assistant.
    asst = await models.Assistant.get_by_id(request.state.db, int(assistant_id))

    # Check additional permissions
    if not asst.published:
        cls = await models.Class.get_by_id(request.state.db, asst.class_id)
        if not cls.any_can_publish_assistant and req.published:
            can_override = await IsSuper().test_with_cache(request) or await CanWrite(
                models.Class, "class_id"
            ).test_with_cache(request)
            if not can_override:
                raise HTTPException(
                    status_code=403,
                    detail="You are not allowed to publish assistants for this class.",
                )

    if not req.dict():
        return asst

    openai_update: dict[str, Any] = {}
    # Update the assistant
    if req.file_ids is not None:
        openai_update["file_ids"] = req.file_ids
        asst.files = await models.File.get_all_by_file_id(
            request.state.db, req.file_ids
        )
    if req.use_latex is not None:
        asst.use_latex = req.use_latex
    if req.hide_prompt is not None:
        asst.hide_prompt = req.hide_prompt
    if req.instructions is not None:
        if not req.instructions:
            raise HTTPException(400, "Instructions cannot be empty.")
        asst.instructions = req.instructions
    if req.model is not None:
        openai_update["model"] = req.model
        asst.model = req.model
    if req.description is not None:
        asst.description = req.description
    if req.tools is not None:
        openai_update["tools"] = req.tools
        asst.tools = json.dumps(req.tools)
    if req.published is not None:
        asst.published = func.now() if req.published else None
    if req.name is not None:
        asst.name = req.name

    request.state.db.add(asst)
    await request.state.db.flush()
    await request.state.db.refresh(asst)

    if not asst.instructions:
        raise HTTPException(500, "Instructions cannot be empty.")
    openai_update["instructions"] = format_instructions(
        asst.instructions, use_latex=asst.use_latex
    )

    try:
        await openai_client.beta.assistants.update(
            assistant_id=asst.assistant_id, **openai_update
        )
    except openai.BadRequestError as e:
        raise HTTPException(400, e.message or "OpenAI rejected this request")

    return asst


@v1.delete(
    "/class/{class_id}/assistant/{assistant_id}",
    dependencies=[
        Depends(
            IsSuper()
            | CanManage(models.Class, "class_id")
            | CanManage(models.Assistant, "assistant_id")
        )
    ],
    response_model=schemas.GenericStatus,
)
async def delete_assistant(
    class_id: str, assistant_id: str, request: Request, openai_client: OpenAIClient
):
    asst = await models.Assistant.get_by_id(request.state.db, int(assistant_id))
    await asst.delete(request.state.db)
    await openai_client.beta.assistants.delete(asst.assistant_id)
    return {"status": "ok"}


@v1.get(
    "/class/{class_id}/image/{file_id}",
    # TODO ideally need to check thread permission too!
    dependencies=[Depends(IsSuper() | CanRead(models.Class, "class_id"))],
)
async def get_image(file_id: str, request: Request, openai_client: OpenAIClient):
    response = await openai_client.files.with_raw_response.retrieve_content(file_id)
    if response.status_code != 200:
        raise HTTPException(
            status_code=response.status_code,
            detail="An error occurred fetching the requested file",
        )
    return Response(content=response.content, media_type="image/png")


@v1.get(
    "/class/{class_id}/thread/{thread_id}/file/{file_id}",
    dependencies=[Depends(IsSuper() | CanRead(models.Thread, "thread_id"))],
)
async def download_file(
    class_id: str,
    thread_id: str,
    file_id: str,
    request: Request,
    openai_client: OpenAIClient,
):
    response = await openai_client.files.with_raw_response.retrieve_content(file_id)
    if response.status_code != 200:
        raise HTTPException(
            status_code=response.status_code,
            detail="An error occurred fetching the requested file",
        )
    # Usually we can just proxy headers from the OpenAI response, but make sure we have
    # defaults set just in case.
    media_type = response.headers.get("content-type", "application/octet-stream")
    disposition = response.headers.get(
        "content-disposition", f"attachment; filename={file_id}"
    )
    headers = {
        "Content-Type": media_type,
        "Content-Disposition": disposition,
    }
    return Response(content=response.content, headers=headers)


@v1.get(
    "/me",
)
async def get_me(request: Request):
    """Get the session information."""
    return request.state.session


@v1.get(
    "/support",
    response_model=schemas.Support,
)
async def get_support(request: Request):
    """Get the support information."""
    return {
        "blurb": config.support.blurb(),
        "can_post": bool(config.support.driver),
    }


@v1.post(
    "/support",
    dependencies=[Depends(LoggedIn())],
    response_model=schemas.GenericStatus,
)
async def post_support(
    req: schemas.SupportRequest,
    request: Request,
):
    """Post a support request."""
    if not config.support.driver:
        raise HTTPException(status_code=403, detail="Support is not available.")

    try:
        await config.support.driver.post(
            req, env=config.public_url, ts=datetime.utcnow()
        )
        return {"status": "ok"}
    except Exception as e:
        logger.exception(e)
        raise HTTPException(status_code=500, detail="Failed to post support request.")


async def lifespan(app: FastAPI):
    """Run services in the background."""
    if not await config.db.driver.exists():
        logger.warning("Creating a new database since none exists.")
        await config.db.driver.create()
        await config.db.driver.init(models.Base)

        logger.info("Creating superusers ...")
        async with config.db.driver.async_session() as session:
            for superuser in config.init.super_users:
                user = models.User(email=superuser, super_admin=True)
                session.add(user)
            await session.commit()

    logger.info("Configuration authorization ...")
    await config.authz.driver.init()

    with sentry(), metrics.metrics():
        yield


app = FastAPI(lifespan=lifespan)


@app.exception_handler(Exception)
async def handle_exception(request: Request, exc: Exception):
    """Handle exceptions."""
    if isinstance(exc, HTTPException):
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.detail},
        )
    else:
        return JSONResponse(
            status_code=500,
            content={"detail": "Internal server error."},
        )


app.mount("/api/v1", v1)


@app.get("/health")
async def health():
    """Health check."""
    return {"status": "ok"}
