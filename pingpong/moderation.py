"""Standalone input moderation, completed before response generation starts."""

import asyncio
import logging
from typing import Any

import openai
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from pingpong import models, schemas
from pingpong import moderation_telemetry as telemetry
from pingpong.config import config
from pingpong.now import utcnow

logger = logging.getLogger(__name__)

CONVERSATION_CLOSED_DETAIL = (
    "We're unable to continue this conversation. Please start a new conversation."
)
MODERATION_MODEL = "omni-moderation-latest"
MODERATION_TIMEOUT_SECONDS = 10.0


class _InvalidModerationResponse(ValueError):
    pass


async def _start_check(run_id: int) -> tuple[int, list[str]] | None:
    async with config.db.driver.async_session() as session:
        if await session.get(models.Run, run_id) is None:
            raise ValueError("Moderation requires an existing, committed run.")
        messages = await session.scalars(
            select(models.Message)
            .where(
                models.Message.run_id == run_id,
                models.Message.role == schemas.MessageRole.USER,
            )
            .options(selectinload(models.Message.content))
            .order_by(models.Message.output_index, models.Message.id)
        )
        inputs, message_ids = [], []
        for message in messages:
            text = "\n\n".join(
                part.text
                for part in sorted(message.content, key=lambda part: part.part_index)
                if part.type == schemas.MessagePartType.INPUT_TEXT
                and part.text
                and part.text.strip()
            )
            if text:
                inputs.append(text)
                message_ids.append(message.id)
        if not inputs:
            return None
        check = models.RunModerationCheck(
            run_id=run_id,
            model=MODERATION_MODEL,
            started_at=utcnow(),
            message_ids=message_ids,
        )
        session.add(check)
        await session.flush()
        check_id = check.id
        await session.commit()
        return check_id, inputs


async def _finish_check(
    check_id: int,
    status: schemas.ModerationCheckStatus,
    *,
    result: dict[str, Any] | None = None,
    error: dict[str, Any] | None = None,
) -> None:
    async def save():
        async with config.db.driver.async_session() as session:
            check = await session.get(models.RunModerationCheck, check_id)
            if check is None:
                raise LookupError("Moderation check no longer exists.")
            check.status = status
            check.result = result
            check.error = error
            check.completed_at = utcnow()
            await session.commit()

    # Finish the audit write before propagating request cancellation.
    task = asyncio.create_task(save())
    try:
        await asyncio.shield(task)
    except asyncio.CancelledError:
        await task
        raise


async def check_run_input(client: openai.AsyncOpenAI, run_id: int) -> bool:
    """Review a committed run's user text; only a flagged result stops generation.

    Empty/non-text inputs need no check. Provider errors and timeouts are recorded
    and fail open. Cancellation propagates without starting generation.
    """
    provider = "azure" if isinstance(client, openai.AsyncAzureOpenAI) else "openai"
    with telemetry.measure("check", provider) as observation:
        return await _check_run_input(client, run_id, observation)


async def _check_run_input(
    client: openai.AsyncOpenAI,
    run_id: int,
    observation: telemetry.ModerationObservation,
) -> bool:
    creation = asyncio.create_task(_start_check(run_id))
    try:
        started = await asyncio.shield(creation)
    except asyncio.CancelledError:
        started = await creation
        if started is not None:
            await _finish_check(started[0], schemas.ModerationCheckStatus.CANCELLED)
        raise
    if started is None:
        observation.outcome = "skipped"
        observation.reason = "no_text"
        return True
    check_id, inputs = started
    try:
        # Bound total time, including retries performed by the SDK.
        with telemetry.measure("provider_call", observation.provider) as provider_call:
            provider_call.reason = "provider_error"
            async with asyncio.timeout(MODERATION_TIMEOUT_SECONDS):
                response = await client.moderations.create(
                    input=inputs,
                    model=MODERATION_MODEL,
                    timeout=MODERATION_TIMEOUT_SECONDS,
                )
            provider_call.outcome = "ok"
            provider_call.reason = "none"
        result = response.model_dump(mode="json")
        if (
            not isinstance(result, dict)
            or not isinstance(result.get("results"), list)
            or len(result["results"]) != len(inputs)
            or any(
                not isinstance(item, dict) or type(item.get("flagged")) is not bool
                for item in result["results"]
            )
        ):
            raise _InvalidModerationResponse()
        flagged = any(item["flagged"] for item in result["results"])
    except asyncio.CancelledError:
        await _finish_check(check_id, schemas.ModerationCheckStatus.CANCELLED)
        raise
    except Exception as exc:
        if isinstance(exc, (TimeoutError, openai.APITimeoutError)):
            code = "moderation_timeout"
        elif isinstance(exc, (_InvalidModerationResponse, AttributeError, TypeError)):
            code = "invalid_moderation_response"
        else:
            code = "moderation_api_error"
        error: dict[str, Any] = {"code": code, "type": type(exc).__name__}
        if isinstance(exc, openai.APIStatusError):
            error["status_code"] = exc.status_code
            error["request_id"] = exc.request_id
        # Exception messages/bodies can echo input; retain only safe metadata.
        await _finish_check(
            check_id, schemas.ModerationCheckStatus.ERRORED, error=error
        )
        observation.reason = code
        logger.warning(
            "Input moderation failed for run %s (%s); continuing", run_id, code
        )
        return True
    await _finish_check(
        check_id,
        schemas.ModerationCheckStatus.FLAGGED
        if flagged
        else schemas.ModerationCheckStatus.PASSED,
        result=result,
    )
    observation.outcome = "flagged" if flagged else "passed"
    observation.reason = "none"
    return not flagged
