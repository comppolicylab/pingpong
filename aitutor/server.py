import asyncio
import json
import logging
import time
from typing import Annotated

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

import aitutor.models as models
import aitutor.schemas as schemas

from .ai import generate_name, get_openai_client, hash_thread
from .auth import (
    decode_auth_token,
    decode_session_token,
    encode_session_token,
    generate_auth_link,
)
from .config import config
from .db import async_session, has_db, init_db
from .email import send_invite
from .errors import sentry
from .metrics import metrics
from .permission import CanManage, CanRead, CanWrite, IsSuper, LoggedIn

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
async def begin_db_session(request: Request, call_next):
    """Create a database session for the request."""
    async with async_session() as db:
        request.state.db = db
        try:
            result = await call_next(request)
            await db.commit()
            return result
        except Exception as e:
            await db.rollback()
            raise e


@v1.get("/config", dependencies=[Depends(IsSuper())])
def get_config(request: Request):
    return {"config": config.dict(), "headers": dict(request.headers)}


@v1.post("/login/magic", response_model=schemas.GenericStatus)
async def login(request: Request):
    """Provide a magic link to the auth endpoint."""
    # Get the email from the request.
    body = await request.json()
    email = body["email"]
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
    magic_link = generate_auth_link(user.id)

    await config.email.sender.send(
        email,
        "Your AI Tutor login link!",
        f"Click this link to log in to the AI Tutor: {magic_link}",
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
    session_dur = 86_400
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

    if await IsSuper().test(request):
        inst = await models.Institution.all(request.state.db)
    else:
        inst = await models.Institution.visible(
            request.state.db, request.state.session.user
        )

    return {"institutions": inst}


@v1.post(
    "/institution",
    dependencies=[Depends(IsSuper())],
    response_model=schemas.Institution,
)
async def create_institution(request: Request):
    data = await request.json()
    return await models.Institution.create(request.state.db, data)


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
async def create_class(institution_id: str, request: Request):
    data = await request.json()
    data["institution_id"] = int(institution_id)
    new_class = await models.Class.create(request.state.db, schemas.CreateClass(**data))

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
    "/class/{class_id}",
    dependencies=[Depends(IsSuper() | CanRead(models.Class, "class_id"))],
    response_model=schemas.Class,
)
async def get_class(class_id: str, request: Request):
    return await models.Class.get_by_id(request.state.db, int(class_id))


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
async def add_users_to_class(class_id: str, request: Request, tasks: BackgroundTasks):
    data = await request.json()
    new_ucr = schemas.CreateUserClassRoles(**data)
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
                    email=user.email,
                    class_name=class_.name,
                )
            )
            result.append(added)

    # Send emails to new users in the background
    for invite in new_:
        # TODO - should send magic link?
        tasks.add_task(send_invite, config.email.sender, invite, config.url("/login"))

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
async def update_class_api_key(class_id: str, request: Request):
    data = await request.json()
    update = schemas.UpdateApiKey(**data)
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
    class_id: str, thread_id: str, request: Request, openai_client: OpenAIClient
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

    if await IsSuper().test(request):
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
async def create_thread(class_id: str, request: Request, openai_client: OpenAIClient):
    data = await request.json()
    req = schemas.CreateThread(**data)

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
    class_id: str, thread_id: str, request: Request, openai_client: OpenAIClient
):
    data = await request.json()
    thread = await models.Thread.get_by_id(request.state.db, int(thread_id))
    asst = await models.Assistant.get_by_id(request.state.db, thread.assistant_id)

    await openai_client.beta.threads.messages.create(
        thread.thread_id,
        role="user",
        content=data["message"],
        metadata={"user_id": request.state.session.user.id},
    )

    run = await openai_client.beta.threads.runs.create(
        thread_id=thread.thread_id,
        assistant_id=asst.assistant_id,
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
    new_f = await openai_client.files.create(
        file=upload.file,
        purpose="assistants",
    )
    data = {
        "file_id": new_f.id,
        "class_id": int(class_id),
        "name": upload.filename,
        "content_type": upload.content_type,
    }
    try:
        return await models.File.create(request.state.db, data)
    except Exception as e:
        await openai_client.files.delete(new_f.id)
        raise e


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
    # TODO - optimize this check
    include_private = await IsSuper().test(request) or await CanWrite(
        models.Class, "class_id"
    ).test(request)
    class_assts = await models.Assistant.for_class(
        request.state.db, int(class_id), include_private=include_private
    )
    my_assts = await models.Assistant.for_user(
        request.state.db, request.state.session.user.id
    )
    creator_ids = {a.creator_id for a in class_assts + my_assts}
    creators = await models.User.get_all_by_id(request.state.db, list(creator_ids))
    return {
        "class_assistants": class_assts,
        "my_assistants": my_assts,
        "creators": {c.id: schemas.Profile.from_email(c.email) for c in creators},
    }


@v1.post(
    "/class/{class_id}/assistant",
    dependencies=[Depends(IsSuper() | CanRead(models.Class, "class_id"))],
    response_model=schemas.Assistant,
)
async def create_assistant(
    class_id: str, request: Request, openai_client: OpenAIClient
):
    data = await request.json()
    req = schemas.CreateAssistant(**data)
    class_id_int = int(class_id)
    creator_id = request.state.session.user.id

    new_asst = await openai_client.beta.assistants.create(
        instructions=req.instructions,
        model=req.model,
        tools=req.tools,
        metadata={"class_id": class_id_int, "creator_id": creator_id},
        file_ids=req.file_ids,
    )

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
    class_id: str, assistant_id: str, request: Request, openai_client: OpenAIClient
):
    data = await request.json()

    # Get the existing assistant.
    asst = await models.Assistant.get_by_id(request.state.db, int(assistant_id))

    if not data:
        return asst

    openai_update = {}
    # Update the assistant
    if "file_ids" in data:
        openai_update["file_ids"] = data["file_ids"]
        asst.files = await models.File.get_all_by_file_id(
            request.state.db, data["file_ids"]
        )
    if "instructions" in data:
        openai_update["instructions"] = data["instructions"]
        asst.instructions = data["instructions"]
    if "model" in data:
        openai_update["model"] = data["model"]
        asst.model = data["model"]
    if "tools" in data:
        openai_update["tools"] = data["tools"]
        asst.tools = json.dumps(data["tools"])
    if "published" in data:
        asst.published = func.now() if data["published"] else None

    request.state.db.add(asst)
    await request.state.db.flush()
    await request.state.db.refresh(asst)

    await openai_client.beta.assistants.update(
        assistant_id=asst.assistant_id, **openai_update
    )

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
    "/me",
    response_model=schemas.SessionState,
)
async def get_me(request: Request):
    """Get the session information."""
    return request.state.session


async def lifespan(app: FastAPI):
    """Run services in the background."""
    if not await has_db():
        logger.warning("Creating a new database since none exists.")
        await init_db()

    with sentry(), metrics():
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
