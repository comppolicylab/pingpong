import logging

from fastapi import WebSocket
from jwt import PyJWTError
from pingpong import models, schemas
from pingpong.auth import TimeException, decode_session_token
from .config import config
from pingpong.users import UserNotFoundException

logger = logging.getLogger(__name__)


def ws_auth_middleware(func):
    async def wrapper(websocket: WebSocket, *args, **kwargs):
        async with config.authz.driver.get_client() as c:
            websocket.state.authz = c
            await func(websocket, *args, **kwargs)
            await c.close()

    return wrapper


def ws_db_middleware(func):
    async def wrapper(websocket: WebSocket, *args, **kwargs):
        async with config.db.driver.async_session_with_args(pool_pre_ping=True)() as db:
            websocket.state.db = db
            try:
                await func(websocket, *args, **kwargs)
                await db.commit()
            except Exception as e:
                await db.rollback()
                raise e

    return wrapper


def ws_parse_session_token(func):
    async def wrapper(websocket: WebSocket, *args, **kwargs):
        try:
            session_token = websocket.cookies["session"]
        except KeyError:
            websocket.state.session = schemas.SessionState(
                status=schemas.SessionStatus.MISSING,
            )
        else:
            try:
                token = decode_session_token(session_token)
                user_id = int(token.sub)
                user = await models.User.get_by_id(websocket.state.db, user_id)
                if not user:
                    error_msg = f"parse_session_token: User not found: {user_id}"
                    logger.warning(error_msg)
                    websocket.state.session = schemas.SessionState(
                        status=schemas.SessionStatus.ERROR,
                        error=error_msg,
                    )
                    await func(websocket, *args, **kwargs)
                    return
                # Modify user state if necessary
                if user.state == schemas.UserState.UNVERIFIED:
                    user.state = schemas.UserState.VERIFIED
                    websocket.state.db.add(user)
                    await websocket.state.db.flush()
                    await websocket.state.db.refresh(user)

                # Get the first ID of any pending agreements
                agreement_id = (
                    await models.AgreementPolicy.get_pending_agreement_by_user_id(
                        websocket.state.db, user.id
                    )
                )

                websocket.state.session = schemas.SessionState(
                    token=token,
                    status=schemas.SessionStatus.VALID,
                    error=None,
                    user=user,
                    profile=schemas.Profile.from_email(user.email),
                    agreement_id=agreement_id,
                )

            except TimeException as e:
                websocket.state.session = schemas.SessionState(
                    status=schemas.SessionStatus.INVALID,
                    error=e.detail,
                )
            except UserNotFoundException as e:
                logger.warning(f"parse_session_token: User not found: {e.user_id}")
                websocket.state.session = schemas.SessionState(
                    status=schemas.SessionStatus.ERROR,
                    error=e.detail,
                )
            except PyJWTError as e:
                websocket.state.session = schemas.SessionState(
                    status=schemas.SessionStatus.INVALID,
                    error=str(e),
                )
            except Exception as e:
                logger.exception("Error parsing session token: %s", e)
                websocket.state.session = schemas.SessionState(
                    status=schemas.SessionStatus.ERROR,
                    error=str(e),
                )
        finally:
            await func(websocket, *args, **kwargs)

    return wrapper
