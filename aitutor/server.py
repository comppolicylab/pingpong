import json

import jwt
from fastapi import (
    BackgroundTasks,
    Depends,
    FastAPI,
    HTTPException,
    Request,
    Response,
    UploadFile,
)
from fastapi.responses import RedirectResponse
from jwt.exceptions import PyJWTError

from .ai import openai_client, run_assistant
from .auth import (
    SessionState,
    SessionStatus,
    decode_auth_token,
    decode_session_token,
    encode_session_token,
)
from .config import config
from .db import Assistant, Class, File, Institution, Thread, User, async_session
from .errors import sentry
from .metrics import metrics
from .permission import CanManage, CanRead, CanWrite, IsSuper, LoggedIn

v1 = FastAPI()


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
            user = await User.get_by_id(request.state.db, int(token.sub))
            if not user:
                raise ValueError("User does not exist")
            request.state.session = SessionState(
                token=token,
                status=SessionStatus.VALID,
                error=None,
                user=user,
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


@v1.get("/institutions", dependencies=[Depends(LoggedIn())])
async def list_institutions(request: Request):
    inst = list[Institution]()

    if await IsSuper().test(request):
        inst = await Institution.all(request.state.db)
    else:
        inst = await Institution.visible(request.state.db, request.state.session.user)

    return {"institutions": inst}


@v1.post("/institution", dependencies=[Depends(IsSuper())])
async def create_institution(request: Request):
    data = await request.json()
    return await Institution.create(request.state.db, data)


@v1.get(
    "/institution/{institution_id}",
    dependencies=[Depends(IsSuper() | CanRead(Institution, "institution_id"))],
)
async def get_institution(institution_id: str, request: Request):
    return await Institution.get_by_id(request.state.db, int(institution_id))


@v1.get(
    "/institution/{institution_id}/classes",
    dependencies=[Depends(IsSuper() | CanRead(Institution, "institution_id"))],
)
async def get_institution_classes(institution_id: str, request: Request):
    classes = await Class.get_by_institution(request.state.db, int(institution_id))
    return {"classes": classes}


@v1.post(
    "/institution/{institution_id}/class",
    dependencies=[Depends(IsSuper() | CanWrite(Institution, "institution_id"))],
)
async def create_class(institution_id: str, request: Request):
    data = await request.json()
    data["institution_id"] = int(institution_id)
    return await Class.create(request.state.db, data)


@v1.get(
    "/class/{class_id}",
    dependencies=[Depends(IsSuper() | CanRead(Class, "class_id"))],
)
async def get_class(class_id: str, request: Request):
    return await Class.get_by_id(request.state.db, int(class_id))


@v1.get(
    "/class/{class_id}/thread/{thread_id}",
    dependencies=[
        Depends(CanManage(Class, "class_id") | CanRead(Thread, "thread_id") | IsSuper())
    ],
)
async def get_thread(class_id: str, thread_id: str, request: Request):
    thread = await Thread.get_by_id(request.state.db, int(thread_id))

    return await openai_client.beta.threads.messages.list(thread.thread_id)


@v1.get(
    "/class/{class_id}/threads",
    dependencies=[Depends(CanRead(Thread, "class_id") | IsSuper())],
)
async def list_threads(class_id: str, request: Request):
    threads = list[Thread]()

    if await IsSuper().test(request):
        threads = await Thread.all(request.state.db, int(class_id))
    else:
        threads = await Thread.visible(
            request.state.db, int(class_id), request.state.session.user
        )

    return {"threads": threads}


@v1.post(
    "/class/{class_id}/thread",
    dependencies=[Depends(IsSuper() | CanWrite(Class, "class_id"))],
)
async def create_thread(
    class_id: str, request: Request, background_tasks: BackgroundTasks
):
    data = await request.json()

    parties = list[User]()
    if "parties" in data:
        parties = await User.get_all_by_id(
            request.state.db, [int(p) for p in data["parties"]]
        )

    thread = await openai_client.beta.threads.create(
        messages=[
            {
                "role": "user",
                "content": data["message"],
            }
        ]
    )

    new_thread = {
        "class_id": int(class_id),
        "name": data["message"],
        "private": True if parties else False,
        "users": parties or [],
        "thread_id": thread.id,
    }

    try:
        result = await Thread.create(request.state.db, new_thread)

        # Find the appropriate assistant.
        # TODO be more clever about this
        assts = await Assistant.for_class(request.state.db, int(class_id))
        if not assts:
            raise HTTPException(status_code=400, detail="No assistants found.")

        background_tasks.add_task(
            run_assistant, openai_client, assts[0].assistant_id, thread.id
        )
        # TODO - push response to thread

        # Start running the thread in the background.
        return result
    except Exception as e:
        await openai_client.beta.threads.delete(thread.id)
        raise e


@v1.post(
    "/class/{class_id}/thread/{thread_id}",
    dependencies=[Depends(IsSuper() | CanWrite(Class, "class_id"))],
)
async def send_message(
    class_id: str, thread_id: str, request: Request, background_tasks: BackgroundTasks
):
    data = await request.json()
    thread = await Thread.get_by_id(request.state.db, int(thread_id))

    await openai_client.beta.threads.messages.create(
        thread.thread_id,
        role="user",
        content=data["message"],
        metadata={"user_id": request.state.session.user.id},
    )

    # TODO - select assistant better
    assts = await Assistant.for_class(request.state.db, int(class_id))
    if not assts:
        raise HTTPException(status_code=400, detail="No assistants found.")

    background_tasks.add_task(
        run_assistant, openai_client, assts[0].assistant_id, thread.thread_id
    )

    # TODO - push response to thread

    return {"message": "ok"}


@v1.post(
    "/class/{class_id}/file",
    dependencies=[Depends(IsSuper() | CanManage(Class, "class_id"))],
)
async def create_file(class_id: str, request: Request, upload: UploadFile):
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
        return await File.create(request.state.db, data)
    except Exception as e:
        await openai_client.files.delete(new_f.id)
        raise e


@v1.get(
    "/class/{class_id}/files",
    dependencies=[Depends(IsSuper() | CanManage(Class, "class_id"))],
)
async def list_files(class_id: str, request: Request):
    return await File.for_class(request.state.db, int(class_id))


@v1.get(
    "/class/{class_id}/assistants",
    dependencies=[Depends(IsSuper() | CanManage(Class, "class_id"))],
)
async def list_assistants(class_id: str, request: Request):
    return await Assistant.for_class(request.state.db, int(class_id))


@v1.post(
    "/class/{class_id}/assistant",
    dependencies=[Depends(IsSuper() | CanManage(Class, "class_id"))],
)
async def create_assistant(class_id: str, request: Request):
    data = await request.json()
    file_ids = data.pop("file_ids", [])
    files = []
    if file_ids:
        files = await File.get_all_by_file_id(request.state.db, file_ids)
    data["class_id"] = int(class_id)
    data["files"] = files

    new_asst = await openai_client.beta.assistants.create(
        instructions=data["instructions"],
        model=data["model"],
        tools=data["tools"],
        file_ids=file_ids,
    )
    data["assistant_id"] = new_asst.id

    try:
        data["tools"] = json.dumps(data["tools"])
        return await Assistant.create(request.state.db, data)
    except Exception as e:
        await openai_client.beta.assistants.delete(new_asst.id)
        raise e


@v1.get("/me")
async def get_me(request: Request):
    """Get the session information."""
    return request.state.session


async def lifespan(app: FastAPI):
    """Run services in the background."""
    with sentry(), metrics():
        yield


app = FastAPI(lifespan=lifespan)

app.mount("/api/v1", v1)
