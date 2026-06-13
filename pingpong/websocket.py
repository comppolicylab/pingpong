from functools import cache, wraps
import logging
import os
import re
import subprocess
import tomllib
from typing import Any, cast
from pathlib import Path
from urllib.parse import urlparse

from sqlalchemy import select

from pingpong import models, schemas
from pingpong.ai_models import get_reasoning_effort_map
from pingpong.ai import (
    OpenAIClientType,
    build_openai_safety_identifier,
    get_openai_client_by_class_id,
    inject_timestamp_to_instructions,
)
from pingpong.session import populate_request
from pingpong.state_types import StateWebSocket
from pingpong.log_utils import sanitize_for_log
from .config import config

browser_connection_logger = logging.getLogger("realtime_browser")
openai_connection_logger = logging.getLogger("realtime_openai")

VOICE_SESSION_ACTIVE_MESSAGE = (
    "This voice session is already active in another connection."
)
VOICE_SESSION_FINAL_MESSAGE = (
    "This voice session has already ended. Start a new thread to continue."
)


def _coerce_realtime_enum(enum_type, value, default):
    if value is None:
        return default
    if isinstance(value, enum_type):
        return value
    return enum_type.__members__.get(value) or enum_type(value)


def build_realtime_reasoning(assistant: models.Assistant) -> dict[str, str] | None:
    reasoning_effort_map = get_reasoning_effort_map(assistant.model)
    if not reasoning_effort_map:
        return None

    reasoning_effort = (
        assistant.reasoning_effort if assistant.reasoning_effort is not None else 0
    )
    if reasoning_effort not in reasoning_effort_map:
        raise ValueError(
            f"Invalid realtime reasoning effort {reasoning_effort} for model {assistant.model}."
        )

    return {"effort": reasoning_effort_map[reasoning_effort]}


REALTIME_TRACE_WORKFLOW_NAME = "PingPong Voice Mode"
REALTIME_TRACE_METADATA_VERSION = "1"
REALTIME_TRACE_GROUP_ID_DISALLOWED_PATTERN = re.compile(r"[^A-Za-z0-9_-]+")
PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _stringify_trace_metadata(value: Any) -> str | None:
    if value is None:
        return None
    if hasattr(value, "value"):
        value = value.value
    text = str(value).strip()
    return text or None


def _add_trace_metadata(metadata: dict[str, str], key: str, value: Any) -> None:
    text = _stringify_trace_metadata(value)
    if text is not None:
        metadata[key] = text


def _sanitize_trace_group_id_part(value: Any) -> str:
    text = _stringify_trace_metadata(value) or "unknown"
    sanitized = REALTIME_TRACE_GROUP_ID_DISALLOWED_PATTERN.sub("_", text).strip("_-")
    return sanitized or "unknown"


def _get_pyproject_version() -> str | None:
    try:
        pyproject = tomllib.loads(
            (PROJECT_ROOT / "pyproject.toml").read_text(encoding="utf-8")
        )
    except (OSError, tomllib.TOMLDecodeError):
        return None

    project = pyproject.get("project")
    if not isinstance(project, dict):
        return None
    return _stringify_trace_metadata(project.get("version"))


def _run_git_command(*args: str) -> str | None:
    try:
        output = subprocess.check_output(
            ["git", *args],
            cwd=PROJECT_ROOT,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=1,
        )
    except (
        OSError,
        subprocess.CalledProcessError,
        subprocess.TimeoutExpired,
    ):
        return None
    return _stringify_trace_metadata(output)


def _get_local_dev_version_suffix() -> str:
    short_sha = _run_git_command("rev-parse", "--short", "HEAD")
    if short_sha is None:
        return "dev"

    suffix = f"dev.{short_sha}"
    if _run_git_command("status", "--short"):
        suffix += ".dirty"
    return suffix


@cache
def _get_pingpong_version() -> str | None:
    sentry_release = _stringify_trace_metadata(os.environ.get("SENTRY_RELEASE"))
    if sentry_release is not None:
        return sentry_release

    pyproject_version = _get_pyproject_version()
    if pyproject_version is None:
        return None
    return f"pingpong@{pyproject_version}+{_get_local_dev_version_suffix()}"


def build_realtime_tracing_config(
    thread: models.Thread,
    assistant: models.Assistant,
    class_id: str,
    safety_identifier: str | None = None,
) -> dict[str, Any]:
    deployment_identifier = config.deployment_identifier
    group_deployment_identifier = _sanitize_trace_group_id_part(deployment_identifier)
    group_assistant_identifier = _sanitize_trace_group_id_part(
        getattr(assistant, "id", None)
    )
    deployment_hostname = urlparse(config.public_url).hostname

    metadata = {
        "metadata_version": REALTIME_TRACE_METADATA_VERSION,
        "deployment_identifier": deployment_identifier,
    }
    _add_trace_metadata(metadata, "pingpong_version", _get_pingpong_version())
    _add_trace_metadata(metadata, "deployment_url", deployment_hostname)
    _add_trace_metadata(metadata, "class", class_id)
    _add_trace_metadata(metadata, "assistant", getattr(assistant, "id", None))
    _add_trace_metadata(metadata, "thread", getattr(thread, "id", None))
    _add_trace_metadata(metadata, "model", assistant.model)
    _add_trace_metadata(metadata, "safety_identifier", safety_identifier)

    return {
        "workflow_name": REALTIME_TRACE_WORKFLOW_NAME,
        "group_id": f"pp_{group_deployment_identifier}_assistant_{group_assistant_identifier}!!!!",
        "metadata": metadata,
    }


def build_realtime_session(
    assistant: models.Assistant,
    conversation_instructions: str,
    tracing_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    realtime_vad_mode = _coerce_realtime_enum(
        schemas.RealtimeVadMode,
        assistant.realtime_vad_mode,
        schemas.RealtimeVadMode.SEMANTIC_VAD,
    )
    realtime_eagerness = _coerce_realtime_enum(
        schemas.RealtimeEagerness,
        assistant.realtime_eagerness,
        schemas.RealtimeEagerness.AUTO,
    )
    realtime_voice = _coerce_realtime_enum(
        schemas.RealtimeVoice,
        assistant.realtime_voice,
        schemas.RealtimeVoice.MARIN,
    )
    realtime_noise_reduction = _coerce_realtime_enum(
        schemas.RealtimeNoiseReduction,
        assistant.realtime_noise_reduction,
        schemas.RealtimeNoiseReduction.FAR_FIELD,
    )
    realtime_transcription_model = _coerce_realtime_enum(
        schemas.RealtimeTranscriptionModel,
        assistant.realtime_transcription_model,
        schemas.RealtimeTranscriptionModel.WHISPER_1,
    )
    turn_detection: dict[str, Any] = {
        "create_response": True,
        "type": realtime_vad_mode.value,
        "interrupt_response": True,
    }
    if realtime_vad_mode == schemas.RealtimeVadMode.SEMANTIC_VAD:
        turn_detection["eagerness"] = realtime_eagerness.value
    else:
        turn_detection["threshold"] = (
            assistant.realtime_vad_threshold
            if assistant.realtime_vad_threshold is not None
            else 0.5
        )
        turn_detection["prefix_padding_ms"] = (
            assistant.realtime_vad_prefix_padding_ms
            if assistant.realtime_vad_prefix_padding_ms is not None
            else 300
        )
        turn_detection["silence_duration_ms"] = (
            assistant.realtime_vad_silence_duration_ms
            if assistant.realtime_vad_silence_duration_ms is not None
            else 500
        )
        if assistant.realtime_vad_idle_timeout_ms is not None:
            turn_detection["idle_timeout_ms"] = assistant.realtime_vad_idle_timeout_ms
    noise_reduction = (
        None
        if realtime_noise_reduction == schemas.RealtimeNoiseReduction.NONE
        else {"type": realtime_noise_reduction.value}
    )
    session = {
        "type": "realtime",
        "audio": {
            "input": {
                "noise_reduction": noise_reduction,
                "transcription": {
                    "model": realtime_transcription_model.value,
                    "language": "en",
                },
                "turn_detection": turn_detection,
            },
            "output": {
                "voice": realtime_voice.value,
                "speed": (
                    assistant.realtime_speed
                    if assistant.realtime_speed is not None
                    else 1.0
                ),
            },
        },
        "instructions": conversation_instructions,
        "output_modalities": ["audio"],
        "tool_choice": "none",
        "tools": [],
    }
    reasoning = build_realtime_reasoning(assistant)
    if reasoning is not None:
        session["reasoning"] = reasoning
    if tracing_config is not None:
        session["tracing"] = tracing_config

    return session


def build_realtime_extra_headers(
    safety_identifier: str | None,
) -> dict[str, str]:
    if safety_identifier is None:
        return {}

    return {"OpenAI-Safety-Identifier": safety_identifier}


async def _thread_has_messages(db, thread_id: int) -> bool:
    message_id = await db.scalar(
        select(models.Message.id).where(models.Message.thread_id == thread_id).limit(1)
    )
    return message_id is not None


async def _reject_realtime_session(
    browser_connection: StateWebSocket, message: str
) -> None:
    await browser_connection.send_json(
        {
            "type": "error",
            "error": {
                "type": "invalid_request_error",
                "code": "voice_session_unavailable",
                "message": message,
            },
        }
    )
    await browser_connection.close()


def ws_auth_middleware(func):
    @wraps(func)
    async def wrapper(websocket: StateWebSocket, *args, **kwargs):
        async with config.authz.driver.get_client() as c:
            websocket.state["authz"] = c
            await func(websocket, *args, **kwargs)
            await c.close()

    return wrapper


def ws_db_middleware(func):
    @wraps(func)
    async def wrapper(websocket: StateWebSocket, *args, **kwargs):
        async with config.db.driver.async_session_with_args(pool_pre_ping=True)() as db:
            websocket.state["db"] = db
            try:
                await func(websocket, *args, **kwargs)
                await db.commit()
            except Exception as e:
                await db.rollback()
                raise e

    return wrapper


def ws_parse_session_token(func):
    @wraps(func)
    async def wrapper(websocket: StateWebSocket, *args, **kwargs):
        websocket = cast(StateWebSocket, await populate_request(websocket))
        return await func(websocket, *args, **kwargs)

    return wrapper


async def check_realtime_permissions(ws: StateWebSocket, thread_id: str):
    if not (
        ws.state["session"].status == schemas.SessionStatus.VALID
        or ws.state["session"].status == schemas.SessionStatus.ANONYMOUS
    ):
        raise ValueError("Your session token is invalid. Try logging in again.")

    permission_checks: list[bool] = []
    # If the user is anonymous, check their anonymous permissions.
    if ws.state["is_anonymous"]:
        grants_to_check = []
        if ws.state["anonymous_share_token_auth"]:
            grants_to_check.append(
                (
                    ws.state["anonymous_share_token_auth"],
                    "can_participate",
                    f"thread:{thread_id}",
                )
            )
        if ws.state["anonymous_session_token_auth"]:
            grants_to_check.append(
                (
                    ws.state["anonymous_session_token_auth"],
                    "can_participate",
                    f"thread:{thread_id}",
                )
            )
        if grants_to_check:
            results = await ws.state["authz"].check(grants_to_check)
            permission_checks.extend(results)

    # If the user is logged in, check their permissions.
    if ws.state["auth_user"]:
        permission_checks.append(
            await ws.state["authz"].test(
                ws.state["auth_user"],
                "can_participate",
                f"thread:{thread_id}",
            )
        )
    if not any(permission_checks):
        raise ValueError("You are not allowed to participate in this thread.")


def ws_check_realtime_permissions(func):
    @wraps(func)
    async def wrapper(
        browser_connection: StateWebSocket,
        class_id: str,
        thread_id: str,
        *args,
        **kwargs,
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
        browser_connection: StateWebSocket,
        class_id: str,
        thread_id: str,
        *args,
        **kwargs,
    ):
        try:
            openai_client: OpenAIClientType = await get_openai_client_by_class_id(
                browser_connection.state["db"], int(class_id)
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
        browser_connection.state["openai_client"] = openai_client
        return await func(browser_connection, class_id, thread_id, *args, **kwargs)

    return wrapper


def ws_with_thread_assistant_prompt(func):
    @wraps(func)
    async def wrapper(
        browser_connection: StateWebSocket,
        class_id: str,
        thread_id: str,
        *args,
        **kwargs,
    ):
        browser_connection.state[
            "thread"
        ] = await models.Thread.get_by_id_with_assistant(
            browser_connection.state["db"],
            int(thread_id),
        )
        browser_connection.state["assistant"] = browser_connection.state[
            "thread"
        ].assistant
        browser_connection.state["conversation_instructions"] = (
            inject_timestamp_to_instructions(
                browser_connection.state["thread"].instructions,
                browser_connection.state["thread"].timezone,
            )
        )
        return await func(browser_connection, class_id, thread_id, *args, **kwargs)

    return wrapper


def ws_with_single_realtime_session(func):
    @wraps(func)
    async def wrapper(
        browser_connection: StateWebSocket,
        class_id: str,
        thread_id: str,
        *args,
        **kwargs,
    ):
        thread_pk = int(thread_id)
        # The row lock intentionally spans the websocket transaction so a second
        # concurrent connection to the same unfinished voice session waits here.
        thread = await models.Thread.get_by_id_with_assistant(
            browser_connection.state["db"],
            thread_pk,
            for_update=True,
            include_voice_mode_recording=True,
        )
        if thread is None:
            await _reject_realtime_session(
                browser_connection, "This voice session was not found."
            )
            return None

        has_messages = await _thread_has_messages(
            browser_connection.state["db"], thread.id
        )
        if thread.voice_mode_recording or has_messages:
            existing_recording_id = (
                thread.voice_mode_recording.recording_id
                if thread.voice_mode_recording
                else None
            )
            browser_connection_logger.warning(
                "Rejecting realtime session for finalized thread. "
                "thread_id=%s, existing_recording_id=%s, has_messages=%s",
                thread.id,
                sanitize_for_log(existing_recording_id, max_len=256),
                has_messages,
            )
            await _reject_realtime_session(
                browser_connection, VOICE_SESSION_FINAL_MESSAGE
            )
            return None

        browser_connection.state["thread"] = thread
        browser_connection.state["assistant"] = thread.assistant
        browser_connection.state["conversation_instructions"] = (
            inject_timestamp_to_instructions(
                thread.instructions,
                thread.timezone,
            )
        )
        return await func(browser_connection, class_id, thread_id, *args, **kwargs)

    return wrapper


def ws_with_realtime_connection(func):
    @wraps(func)
    async def wrapper(
        browser_connection: StateWebSocket,
        class_id: str,
        thread_id: str,
        *args,
        **kwargs,
    ):
        openai_client: OpenAIClientType = browser_connection.state["openai_client"]
        assistant: models.Assistant = browser_connection.state["assistant"]
        thread: models.Thread = browser_connection.state["thread"]
        conversation_instructions: str = browser_connection.state[
            "conversation_instructions"
        ]
        response_safety_identifier = getattr(
            browser_connection.state, "response_safety_identifier", None
        )
        if not (
            isinstance(response_safety_identifier, str) and response_safety_identifier
        ):
            safety_identifier = None
        else:
            safety_identifier = build_openai_safety_identifier(
                response_safety_identifier
            )
        tracing_config = build_realtime_tracing_config(
            thread,
            assistant,
            class_id,
            safety_identifier,
        )
        session = build_realtime_session(
            assistant,
            conversation_instructions,
            tracing_config,
        )
        extra_headers = build_realtime_extra_headers(safety_identifier)
        try:
            async with openai_client.realtime.connect(
                model=assistant.model,
                extra_headers=extra_headers,
            ) as realtime_connection:
                browser_connection.state["realtime_connection"] = realtime_connection
                await realtime_connection.session.update(session=session)
                if assistant.assistant_should_message_first:
                    await realtime_connection.response.create()
                await func(browser_connection, class_id, thread_id, *args, **kwargs)
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
