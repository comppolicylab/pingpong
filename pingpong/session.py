from fastapi import Request
from jwt import PyJWTError
from pingpong import models, schemas
from pingpong.auth import TimeException, decode_session_token
from .now import NowFn, utcnow
from pingpong.users import UserNotFoundException

import logging

logger = logging.getLogger(__name__)


def get_now_fn(req: Request) -> NowFn:
    """Get the current time function for the request."""
    return getattr(req.app.state, "now", utcnow)


async def populate_anonymous_tokens(request):
    isRequest = isinstance(request, Request)
    user: models.User | None = None

    # Default values for anonymous session state
    request.state.is_anonymous = False
    request.state.anonymous_share_token_auth = None
    request.state.anonymous_session_token_auth = None
    request.state.anonymous_session = schemas.SessionState(
        status=schemas.SessionStatus.MISSING,
    )

    if isRequest:
        request.state.anonymous_share_token = request.query_params.get("share_token")
        request.state.anonymous_session_token = request.headers.get(
            "X-Anonymous-Thread-Session"
        )

    if (
        request.state.anonymous_share_token is None
        and request.state.anonymous_session_token is None
    ):
        return request
    else:
        if request.state.anonymous_session_token:
            user, anonymous_session = await models.User.get_by_session_token(
                request.state.db, request.state.anonymous_session_token
            )
            if user:
                request.state.anonymous_share_token = user.anonymous_link.share_token
                request.state.anonymous_session_id = (
                    anonymous_session.id if anonymous_session else None
                )
                request.state.anonymous_link_id = (
                    user.anonymous_link.id if user else None
                )
        else:
            user = await models.User.get_by_share_token(
                request.state.db, request.state.anonymous_share_token
            )
            request.state.anonymous_link_id = user.anonymous_link.id if user else None
        if not user:
            return request

        request.state.is_anonymous = True
        request.state.anonymous_share_token_auth = (
            f"anonymous_link:{request.state.anonymous_share_token}"
            if request.state.anonymous_share_token
            else None
        )
        request.state.anonymous_session_token_auth = (
            f"anonymous_user:{request.state.anonymous_session_token}"
            if request.state.anonymous_session_token
            else None
        )
        request.state.anonymous_session = schemas.SessionState(
            status=schemas.SessionStatus.ANONYMOUS,
            user=user,
        )

    return request


async def populate_request(request):
    try:
        request = await populate_anonymous_tokens(request)
        session_token = request.cookies["session"]
    except KeyError:
        if (
            request.state.is_anonymous
            and request.state.anonymous_session.user is not None
        ):
            request.state.session = schemas.SessionState(
                status=schemas.SessionStatus.ANONYMOUS,
                user=request.state.anonymous_session.user,
            )
        else:
            request.state.session = schemas.SessionState(
                status=schemas.SessionStatus.MISSING,
            )
    else:
        try:
            if isinstance(request, Request):
                token = decode_session_token(session_token, nowfn=get_now_fn(request))
            else:
                token = decode_session_token(session_token)
            user_id = int(token.sub)
            user = await models.User.get_by_id(request.state.db, user_id)
            if not user:
                raise UserNotFoundException(
                    "We couldn't locate your account. Please try logging in again.",
                    token.sub,
                )
            # Modify user state if necessary
            if user.state == schemas.UserState.UNVERIFIED:
                user.state = schemas.UserState.VERIFIED
                request.state.db.add(user)
                await request.state.db.flush()
                await request.state.db.refresh(user)

            # Get the first ID of any pending agreements
            agreement_id = (
                await models.AgreementPolicy.get_pending_agreement_by_user_id(
                    request.state.db, user.id
                )
            )

            request.state.session = schemas.SessionState(
                token=token,
                status=schemas.SessionStatus.VALID,
                error=None,
                user=user,
                profile=schemas.Profile.from_email(user.email),
                agreement_id=agreement_id,
            )
            request.state.auth_user = f"user:{user_id}"
        except Exception as e:
            if (
                request.state.is_anonymous
                and request.state.anonymous_session.user is not None
            ):
                request.state.session = schemas.SessionState(
                    status=schemas.SessionStatus.ANONYMOUS,
                    user=user,
                )
            else:
                if isinstance(e, PyJWTError) or isinstance(e, TimeException):
                    request.state.session = schemas.SessionState(
                        status=schemas.SessionStatus.INVALID,
                        error=e.detail if isinstance(e, TimeException) else str(e),
                    )
                elif isinstance(e, UserNotFoundException):
                    logger.warning(f"parse_session_token: User not found: {e.user_id}")
                    request.state.session = schemas.SessionState(
                        status=schemas.SessionStatus.ERROR,
                        error=e.detail,
                    )
                else:
                    logger.exception("Error parsing session token: %s", e)
                    request.state.session = schemas.SessionState(
                        status=schemas.SessionStatus.ERROR,
                        error=str(e),
                    )

    return request
