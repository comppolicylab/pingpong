from functools import wraps
import logging

from fastapi import WebSocket
from pingpong import models, schemas
from pingpong.ai import (
    OpenAIClientType,
    get_openai_client_by_class_id,
    inject_timestamp_to_instructions,
)
from pingpong.session import populate_request
from .config import config

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
        websocket = await populate_request(websocket)
        return await func(websocket, *args, **kwargs)

    return wrapper


async def check_realtime_permissions(ws: WebSocket, thread_id: str):
    if not (
        ws.state.session.status == schemas.SessionStatus.VALID
        or ws.state.session.status == schemas.SessionStatus.ANONYMOUS
    ):
        raise ValueError("Your session token is invalid. Try logging in again.")

    permission_checks: list[bool] = []
    # If the user is anonymous, check their anonymous permissions.
    if ws.state.is_anonymous:
        grants_to_check = []
        if ws.state.anonymous_share_token_auth:
            grants_to_check.append(
                (
                    ws.state.anonymous_share_token_auth,
                    "can_participate",
                    f"thread:{thread_id}",
                )
            )
        if ws.state.anonymous_session_token_auth:
            grants_to_check.append(
                (
                    ws.state.anonymous_session_token_auth,
                    "can_participate",
                    f"thread:{thread_id}",
                )
            )
        if grants_to_check:
            results = await ws.state.authz.check(grants_to_check)
            permission_checks.extend(results)

    # If the user is logged in, check their permissions.
    if hasattr(ws.state, "auth_user") and ws.state.auth_user:
        permission_checks.append(
            await ws.state.authz.test(
                ws.state.auth_user,
                "can_participate",
                f"thread:{thread_id}",
            )
        )
    if not any(permission_checks):
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
        browser_connection.state.conversation_instructions = (
            inject_timestamp_to_instructions(
                browser_connection.state.thread.instructions,
                browser_connection.state.thread.timezone,
            )
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
            async with openai_client.realtime.connect(
                model=assistant.model,
            ) as realtime_connection:
                browser_connection.state.realtime_connection = realtime_connection
                await realtime_connection.session.update(
                    session={
                        "type": "realtime",
                        "audio": {
                            "input": {
                                "noise_reduction": {"type": "far_field"},
                                "transcription": {
                                    "model": "whisper-1",
                                    "language": "en",
                                },
                                "turn_detection": {
                                    "create_response": True,
                                    "eagerness": "high",
                                    "type": "semantic_vad",
                                    "interrupt_response": False,
                                },
                            },
                            "output": {"voice": "alloy", "speed": 1.2},
                        },
                        "instructions": conversation_instructions,
                        "output_modalities": ["audio"],
                        "tool_choice": "none",
                        "tools": [],
                    }
                )
                if assistant.assistant_should_message_first:
                    await realtime_connection.response.create()
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
