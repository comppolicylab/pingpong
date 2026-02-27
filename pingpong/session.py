import logging
import re
from typing import cast

from fastapi import Request
from jwt import PyJWTError
from pingpong import models, schemas
from pingpong.auth import TimeException, decode_session_token
from pingpong.state_types import AppState, StateRequest, StateWebSocket
from pingpong.users import UserNotFoundException
from .now import NowFn, utcnow

logger = logging.getLogger(__name__)

ANONYMOUS_TOKEN_QUERY_PATH_ALLOWLIST = (
    re.compile(r"^/api/v1/class/[^/]+/thread/[^/]+/video$"),
)


def is_media_route(path: str) -> bool:
    return any(pattern.fullmatch(path) for pattern in ANONYMOUS_TOKEN_QUERY_PATH_ALLOWLIST)


def get_now_fn(req: StateRequest) -> NowFn:
    """Get the current time function for the request."""
    app_state = cast(AppState, req.app.state)
    return app_state["now"] if "now" in app_state else utcnow


def _initialize_shared_state(request: StateRequest | StateWebSocket) -> None:
    request.state["permissions"] = dict[str, bool]()
    request.state["auth_user"] = None
    request.state["is_anonymous"] = False
    request.state["anonymous_share_token_auth"] = None
    request.state["anonymous_session_token_auth"] = None
    request.state["anonymous_session"] = schemas.SessionState(
        status=schemas.SessionStatus.MISSING,
    )
    if "anonymous_share_token" not in request.state:
        request.state["anonymous_share_token"] = None
    if "anonymous_session_token" not in request.state:
        request.state["anonymous_session_token"] = None
    request.state["anonymous_session_id"] = None
    request.state["anonymous_link_id"] = None


async def populate_anonymous_tokens(
    request: StateRequest | StateWebSocket,
) -> StateRequest | StateWebSocket:
    is_http_request = isinstance(request, Request)
    user: models.User | None = None

    if is_http_request:
        req = cast(Request, request)
        allow_query_param_tokens = is_media_route(req.url.path)
        # Support token auth via query params only on allowlisted media URLs that
        # cannot send custom headers.
        request.state["anonymous_share_token"] = req.headers.get(
            "X-Anonymous-Link-Share"
        ) or (
            req.query_params.get("anonymous_share_token")
            if allow_query_param_tokens
            else None
        )
        request.state["anonymous_session_token"] = req.headers.get(
            "X-Anonymous-Thread-Session"
        ) or (
            req.query_params.get("anonymous_session_token")
            if allow_query_param_tokens
            else None
        )

    if (
        request.state["anonymous_share_token"] is None
        and request.state["anonymous_session_token"] is None
    ):
        return request
    else:
        if request.state["anonymous_session_token"]:
            user, anonymous_session = await models.User.get_by_session_token(
                request.state["db"], request.state["anonymous_session_token"]
            )
            if user:
                request.state["anonymous_share_token"] = user.anonymous_link.share_token
                request.state["anonymous_session_id"] = (
                    anonymous_session.id if anonymous_session else None
                )
                request.state["anonymous_link_id"] = (
                    user.anonymous_link.id if user else None
                )
        else:
            user = await models.User.get_by_share_token(
                request.state["db"], request.state["anonymous_share_token"]
            )
            request.state["anonymous_link_id"] = (
                user.anonymous_link.id if user else None
            )
        if not user:
            return request

        request.state["is_anonymous"] = True
        request.state["anonymous_share_token_auth"] = (
            f"anonymous_link:{request.state['anonymous_share_token']}"
            if request.state["anonymous_share_token"]
            else None
        )
        request.state["anonymous_session_token_auth"] = (
            f"anonymous_user:{request.state['anonymous_session_token']}"
            if request.state["anonymous_session_token"]
            else None
        )
        request.state["anonymous_session"] = schemas.SessionState(
            status=schemas.SessionStatus.ANONYMOUS,
            user=user,
        )

    return request


def populate_authorization_token(request: StateRequest | StateWebSocket):
    try:
        request.cookies["session"]
    except KeyError:
        auth_header = request.headers.get("Authorization")
        if auth_header and auth_header.startswith("Bearer "):
            bearer_token = auth_header.removeprefix("Bearer ").strip()
            request.cookies["session"] = bearer_token
        elif isinstance(request, Request):
            lti_session = request.query_params.get("lti_session")
            if lti_session:
                request.cookies["session"] = lti_session

    return request


async def populate_request(
    request: StateRequest | StateWebSocket,
) -> StateRequest | StateWebSocket:
    user: models.User | None = None
    _initialize_shared_state(request)
    try:
        request = await populate_anonymous_tokens(request)
        request = populate_authorization_token(request)
        session_token = request.cookies["session"]
    except KeyError:
        if (
            request.state["is_anonymous"]
            and request.state["anonymous_session"].user is not None
        ):
            request.state["session"] = schemas.SessionState(
                status=schemas.SessionStatus.ANONYMOUS,
                user=request.state["anonymous_session"].user,
            )
        else:
            request.state["session"] = schemas.SessionState(
                status=schemas.SessionStatus.MISSING,
            )
    else:
        try:
            if isinstance(request, Request):
                token = decode_session_token(
                    session_token, nowfn=get_now_fn(cast(StateRequest, request))
                )
            else:
                token = decode_session_token(session_token)
            user_id = int(token.sub)
            user = await models.User.get_by_id(request.state["db"], user_id)
            if not user:
                raise UserNotFoundException(
                    "We couldn't locate your account. Please try logging in again.",
                    token.sub,
                )
            # Modify user state if necessary
            if user.state == schemas.UserState.UNVERIFIED:
                user.state = schemas.UserState.VERIFIED
                request.state["db"].add(user)
                await request.state["db"].flush()
                await request.state["db"].refresh(user)

            # Get the first ID of any pending agreements
            agreement_id = (
                await models.AgreementPolicy.get_pending_agreement_by_user_id(
                    request.state["db"], user.id
                )
            )

            request.state["session"] = schemas.SessionState(
                token=token,
                status=schemas.SessionStatus.VALID,
                error=None,
                user=user,
                profile=schemas.Profile.from_email(user.email),
                agreement_id=agreement_id,
            )
            request.state["auth_user"] = f"user:{user_id}"
        except Exception as e:
            if (
                request.state["is_anonymous"]
                and request.state["anonymous_session"].user is not None
            ):
                request.state["session"] = schemas.SessionState(
                    status=schemas.SessionStatus.ANONYMOUS,
                    user=request.state["anonymous_session"].user,
                )
            else:
                if isinstance(e, PyJWTError) or isinstance(e, TimeException):
                    request.state["session"] = schemas.SessionState(
                        status=schemas.SessionStatus.INVALID,
                        error=e.detail if isinstance(e, TimeException) else str(e),
                    )
                elif isinstance(e, UserNotFoundException):
                    logger.warning(f"parse_session_token: User not found: {e.user_id}")
                    request.state["session"] = schemas.SessionState(
                        status=schemas.SessionStatus.ERROR,
                        error=e.detail,
                    )
                else:
                    logger.exception("Error parsing session token: %s", e)
                    request.state["session"] = schemas.SessionState(
                        status=schemas.SessionStatus.ERROR,
                        error=str(e),
                    )

    return request
