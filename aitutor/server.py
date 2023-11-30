from fastapi import FastAPI, HTTPException, Request, Response, Depends
from fastapi.responses import RedirectResponse
import jwt

from .ai import openai_client
from .auth import decode_auth_token, encode_session_token, Role, decode_session_token, SessionState, SessionStatus
from .db import Thread, User, async_session
from .errors import sentry
from .metrics import metrics
from .config import config
from .permission import CanRead, HasRole, LoggedIn

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
        except jwt.exceptions.PyJWTError as e:
            request.state.session = SessionState(
                    status=SessionStatus.INVALID,
                    error=e,
                    )
        except Exception as e:
            request.state.session = SessionState(
                    status=SessionStatus.ERROR,
                    error=e,
                    )

    print(request.state.session)
    return await call_next(request)


@v1.middleware("http")
async def begin_db_session(request: Request, call_next):
    """Create a database session for the request."""
    async with async_session() as db:
        request.state.db = db
        return await call_next(request)


@v1.get("/config",
        dependencies=[Depends(HasRole(Role.SUPER))])
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


@v1.get("/thread/{thread_id}",
        dependencies=[Depends(CanRead(Thread, "thread_id") | HasRole(Role.SUPER))])
async def get_thread(thread_id: str):
    return await openai_client.beta.threads.messages.list(thread_id=thread_id)


@v1.get("/thread")
async def list_threads():
    ...


@v1.post("/thread",
         dependencies=[Depends(LoggedIn())])
async def create_thread():
    return await openai_client.beta.threads.create()


async def lifespan(app: FastAPI):
    """Run services in the background."""
    with sentry(), metrics():
        yield


app = FastAPI(lifespan=lifespan)

app.mount("/api/v1", v1)
