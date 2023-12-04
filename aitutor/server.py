import jwt
from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from jwt.exceptions import PyJWTError

from .ai import openai_client
from .auth import (
    SessionState,
    SessionStatus,
    decode_auth_token,
    decode_session_token,
    encode_session_token,
)
from .config import config
from .db import Class, Institution, Thread, User, async_session
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
async def get_thread(thread_id: str):
    return await openai_client.beta.threads.messages.list(thread_id=thread_id)


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
async def create_thread(class_id: str):
    return await openai_client.beta.threads.create()


@v1.post(
    "/class/{class_id}/file",
    dependencies=[Depends(IsSuper() | CanManage(Class, "class_id"))],
)
async def create_file(class_id: str):
    return await openai_client.files.create(classification_id=class_id)


@v1.post(
    "/class/{class_id}/assistant",
    dependencies=[Depends(IsSuper() | CanManage(Class, "class_id"))],
)
async def create_assistant(class_id: str):
    # TODO:
    # create assistant object in DB
    # create assistant in OpenAI
    # Mark assistant as created in DB
    # return assistant object
    return await openai_client.beta.assistants.create(classification_id=class_id)


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
