import asyncio
import json
import logging
import time
from typing import Annotated

import jwt
import openai
from fastapi import Depends, FastAPI, HTTPException, Request, Response, UploadFile
from fastapi.responses import JSONResponse, RedirectResponse
from jwt.exceptions import PyJWTError

import aitutor.models as models
import aitutor.schemas as schemas

from .ai import generate_name, get_openai_client, hash_thread
from .auth import (
    SessionState,
    SessionStatus,
    decode_auth_token,
    decode_session_token,
    encode_session_token,
    generate_auth_link,
)
from .config import config
from .db import async_session
from .email import get_default_sender
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
        request.state.session = SessionState(
            status=SessionStatus.MISSING,
        )
    else:
        try:
            token = decode_session_token(session_token)
            user = await models.User.get_by_id(request.state.db, int(token.sub))
            if not user:
                raise ValueError("User does not exist")

            request.state.session = SessionState(
                token=token,
                status=SessionStatus.VALID,
                error=None,
                user=user,
                profile=schemas.Profile.from_email(user.email),
            )
        except PyJWTError as e:
            request.state.session = SessionState(
                status=SessionStatus.INVALID,
                error=e,
            )
        except Exception as e:
            request.state.session = SessionState(
                status=SessionStatus.ERROR,
                error=e,
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

    sender = get_default_sender()
    await sender.send(
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
    return await models.Class.create(request.state.db, schemas.CreateClass(**data))


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
            CanManage(models.Class, "class_id")
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
    return {
        "hash": hash_thread(messages, runs),
        "thread": thread,
        "run": runs[0] if runs else None,
        "messages": messages,
        "participants": {u.id: schemas.Profile.from_email(u.email) for u in users},
    }


@v1.get(
    "/class/{class_id}/thread/{thread_id}/last_run",
    dependencies=[
        Depends(
            CanManage(models.Class, "class_id")
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
    dependencies=[Depends(CanRead(models.Thread, "class_id") | IsSuper())],
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
    dependencies=[Depends(IsSuper() | CanWrite(models.Class, "class_id"))],
    response_model=schemas.ThreadRun,
)
async def create_thread(class_id: str, request: Request, openai_client: OpenAIClient):
    data = await request.json()
    req = schemas.CreateThread(**data)

    parties = list[models.User]()
    if req.parties:
        parties = await models.User.get_all_by_id(
            request.state.db, [int(p) for p in req.parties]
        )

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

    try:
        result = await models.Thread.create(request.state.db, new_thread)

        # Find the appropriate assistant.
        # TODO thjis should be specified in the request
        assts = await models.Assistant.for_class(request.state.db, int(class_id))
        if not assts:
            raise HTTPException(status_code=400, detail="No assistants found.")

        # Start a new thread run.
        run = await openai_client.beta.threads.runs.create(
            thread_id=thread.id,
            assistant_id=req.assistant_id,
        )

        return {"thread": result, "run": run}
    except Exception as e:
        await openai_client.beta.threads.delete(thread.id)
        raise e


@v1.post(
    "/class/{class_id}/thread/{thread_id}",
    dependencies=[Depends(IsSuper() | CanWrite(models.Class, "class_id"))],
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

    # TODO - select assistant better
    assts = await models.Assistant.for_class(request.state.db, int(class_id))
    if not assts:
        raise HTTPException(status_code=400, detail="No assistants found.")

    run = await openai_client.beta.threads.runs.create(
        thread_id=thread.thread_id,
        assistant_id=asst.id,
    )

    return {"thread": thread, "run": run}


@v1.post(
    "/class/{class_id}/file",
    dependencies=[Depends(IsSuper() | CanManage(models.Class, "class_id"))],
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
    dependencies=[Depends(IsSuper() | CanManage(models.Class, "class_id"))],
    response_model=schemas.Files,
)
async def list_files(class_id: str, request: Request):
    files = await models.File.for_class(request.state.db, int(class_id))
    return {"files": files}


@v1.get(
    "/class/{class_id}/assistants",
    dependencies=[Depends(IsSuper() | CanManage(models.Class, "class_id"))],
    response_model=schemas.Assistants,
)
async def list_assistants(class_id: str, request: Request):
    class_assts = await models.Assistant.for_class(request.state.db, int(class_id))
    my_assts = await models.Assistant.for_user(
        request.state.db, request.state.session.user.id
    )
    return {"class_assistants": class_assts, "my_assistants": my_assts}


@v1.post(
    "/class/{class_id}/assistant",
    dependencies=[Depends(IsSuper() | CanManage(models.Class, "class_id"))],
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


@v1.post(
    "/class/{class_id}/assistant/{assistant_id}/publish",
    dependencies=[Depends(IsSuper() | CanManage(models.Assistant, "assistant_id"))],
    response_model=schemas.Assistant,
)
async def publish_assistant(
    class_id: str, assistant_id: str, request: Request, openai_client: OpenAIClient
):
    return await models.Assistant.get_by_id(request.state.db, int(assistant_id))


@v1.put(
    "/class/{class_id}/assistant/{assistant_id}",
    dependencies=[Depends(IsSuper() | CanManage(models.Class, "class_id"))],
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

    request.state.db.add(asst)

    await openai_client.beta.assistants.update(
        assistant_id=asst.assistant_id, **openai_update
    )

    return asst


@v1.delete(
    "/class/{class_id}/assistant/{assistant_id}",
    dependencies=[Depends(IsSuper() | CanManage(models.Class, "class_id"))],
    response_model=schemas.GenericStatus,
)
async def delete_assistant(
    class_id: str, assistant_id: str, request: Request, openai_client: OpenAIClient
):
    asst = await models.Assistant.get_by_id(request.state.db, int(assistant_id))
    await asst.delete(request.state.db)
    await openai_client.beta.assistants.delete(asst.assistant_id)
    return {"status": "ok"}


@v1.get("/me")
async def get_me(request: Request):
    """Get the session information."""
    return request.state.session


async def lifespan(app: FastAPI):
    """Run services in the background."""
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
