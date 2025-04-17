from functools import wraps
import logging

from fastapi import WebSocket
from jwt import PyJWTError
from pingpong import models, schemas
from pingpong.ai import (
    OpenAIClientType,
    format_instructions,
    get_openai_client_by_class_id,
)
from pingpong.auth import TimeException, decode_session_token
from .config import config
from pingpong.users import UserNotFoundException

browser_connection_logger = logging.getLogger("realtime_browser")
openai_connection_logger = logging.getLogger("realtime_openai")


def ws_auth_middleware(func):
    @wraps(func)
    async def wrapper(websocket: WebSocket, *args, **kwargs):
        async with config.authz.driver.get_client() as c:
            websocket.state.authz = c
            await func(websocket, *args, **kwargs)
            await c.close()

    return wrapper


def ws_db_middleware(func):
    @wraps(func)
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
    @wraps(func)
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
                    browser_connection_logger.warning(error_msg)
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
                browser_connection_logger.warning(
                    f"parse_session_token: User not found: {e.user_id}"
                )
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
                browser_connection_logger.exception(
                    "Error parsing session token: %s", e
                )
                websocket.state.session = schemas.SessionState(
                    status=schemas.SessionStatus.ERROR,
                    error=str(e),
                )
        finally:
            return await func(websocket, *args, **kwargs)

    return wrapper


async def check_realtime_permissions(ws: WebSocket, thread_id: str):
    if ws.state.session.status != schemas.SessionStatus.VALID:
        raise ValueError("Your session token is invalid. Try logging in again.")
    if not await ws.state.authz.test(
        f"user:{ws.state.session.user.id}", "can_participate", f"thread:{thread_id}"
    ):
        raise ValueError("You are not allowed to participate in this thread.")


def ws_check_realtime_permissions(func):
    @wraps(func)
    async def wrapper(
        browser_connection: WebSocket, class_id: str, thread_id: str, *args, **kwargs
    ):
        await browser_connection.accept()
        try:
            await check_realtime_permissions(browser_connection, thread_id)
        except ValueError as e:
            await browser_connection.send_json(
                {
                    "type": "error",
                    "error": {
                        "type": "invalid_request_error",
                        "code": "permissions",
                        "message": str(e),
                    },
                }
            )
            await browser_connection.close()
            raise e
        return await func(browser_connection, class_id, thread_id, *args, **kwargs)

    return wrapper


def ws_with_openai_client(func):
    @wraps(func)
    async def wrapper(
        browser_connection: WebSocket, class_id: str, thread_id: str, *args, **kwargs
    ):
        try:
            openai_client: OpenAIClientType = await get_openai_client_by_class_id(
                browser_connection.state.db, int(class_id)
            )
        except Exception:
            await browser_connection.send_json(
                {
                    "type": "error",
                    "error": {
                        "type": "invalid_request_error",
                        "code": "openai_client",
                        "message": "We were unable to connect to OpenAI.",
                    },
                }
            )
            await browser_connection.close()
            raise
        browser_connection.state.openai_client = openai_client
        return await func(browser_connection, class_id, thread_id, *args, **kwargs)

    return wrapper


def ws_with_thread_assistant_prompt(func):
    @wraps(func)
    async def wrapper(
        browser_connection: WebSocket, class_id: str, thread_id: str, *args, **kwargs
    ):
        browser_connection.state.thread = await models.Thread.get_by_id_with_assistant(
            browser_connection.state.db,
            int(thread_id),
        )
        browser_connection.state.assistant = browser_connection.state.thread.assistant
        browser_connection.state.conversation_instructions = format_instructions(
            browser_connection.state.assistant.instructions,
            interaction_mode=schemas.InteractionMode.VOICE,
        )
        return await func(browser_connection, class_id, thread_id, *args, **kwargs)

    return wrapper


def ws_with_realtime_connection(func):
    @wraps(func)
    async def wrapper(browser_connection: WebSocket, *args, **kwargs):
        openai_client: OpenAIClientType = browser_connection.state.openai_client
        assistant: models.Assistant = browser_connection.state.assistant
        conversation_instructions: str = (
            browser_connection.state.conversation_instructions
        )
        try:
            async with openai_client.beta.realtime.connect(
                model=assistant.model,
            ) as realtime_connection:
                browser_connection.state.realtime_connection = realtime_connection
                await realtime_connection.session.update(
                    session={
                        "input_audio_transcription": {
                            "model": "gpt-4o-transcribe",
                            "language": "en",
                        },
                        "temperature": assistant.temperature,
                        "tool_choice": "none",
                        "voice": "alloy",
                        "turn_detection": {
                            "type": "semantic_vad",
                            "eagerness": "medium",
                        },
                        "instructions": conversation_instructions,
                    }
                )
                await func(browser_connection, *args, **kwargs)
        except Exception as e:
            openai_connection_logger.exception(f"Error in Realtime connection: {e}")
            await browser_connection.send_json(
                {
                    "type": "error",
                    "error": {
                        "type": "invalid_request_error",
                        "code": "openai_realtime_connection",
                        "message": "We were unable to connect to OpenAI.",
                    },
                }
            )
            await browser_connection.close()
            raise e

    return wrapper
