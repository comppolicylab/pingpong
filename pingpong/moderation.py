"""Standalone moderation checks; callers own activation and content release."""

import asyncio
import math
from collections.abc import Sequence
from typing import Any

import openai
from pydantic import BaseModel, ConfigDict, Field

from pingpong import models, schemas
from pingpong.config import config
from pingpong.now import utcnow


MODERATION_MODEL = "omni-moderation-latest"
MODERATION_TIMEOUT_SECONDS = 10.0


class ModerationTextItem(BaseModel):
    """Text plus a local source reference; only text is sent to the provider."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    text: str
    source_type: schemas.ModerationSourceType
    source_id: int = Field(gt=0)


class ModerationOutcome(BaseModel):
    model_config = ConfigDict(frozen=True)

    check_id: int
    flagged: bool
    model: str


class ModerationCheckError(Exception):
    """A persisted check failure. Messages contain no submitted content."""

    def __init__(self, check_id: int, code: str):
        self.check_id = check_id
        self.code = code
        super().__init__(f"Moderation check {check_id} failed ({code}).")


class _InvalidModerationResponse(ValueError):
    pass


async def _create_check(
    run_id: int,
    stage: schemas.ModerationCheckStage,
    model: str,
    items: Sequence[ModerationTextItem],
) -> int:
    async with config.db.driver.async_session() as session:
        if await session.get(models.Run, run_id) is None:
            raise ValueError("Moderation requires an existing, committed run.")
        check = models.RunModerationCheck(
            run_id=run_id,
            stage=stage,
            status=schemas.ModerationCheckStatus.PENDING,
            model=model,
            started_at=utcnow(),
            source_items=[
                item.model_dump(mode="json", exclude={"text"}) for item in items
            ],
        )
        session.add(check)
        await session.flush()
        check_id = check.id
        await session.commit()
        return check_id


async def _finish_check(
    check_id: int,
    status: schemas.ModerationCheckStatus,
    *,
    result: dict[str, Any] | None = None,
    error: dict[str, Any] | None = None,
) -> None:
    async with config.db.driver.async_session() as session:
        check = await session.get(
            models.RunModerationCheck, check_id, with_for_update=True
        )
        if check is None:
            raise LookupError("Moderation check no longer exists.")
        if result is not None and len(check.source_items) != len(result["results"]):
            raise ValueError(
                "Moderation source mapping no longer matches the response."
            )
        check.status = status
        check.result = result
        check.error = error
        check.completed_at = utcnow()
        await session.commit()


async def _save_terminal_check(
    check_id: int,
    status: schemas.ModerationCheckStatus,
    **kwargs: Any,
) -> None:
    # Keep a strong task reference and finish the write before propagating cancellation.
    task = asyncio.create_task(_finish_check(check_id, status, **kwargs))
    try:
        await asyncio.shield(task)
    except asyncio.CancelledError:
        await task
        raise


async def moderate_run_text(
    client: openai.AsyncOpenAI,
    *,
    run_id: int,
    stage: schemas.ModerationCheckStage,
    items: Sequence[ModerationTextItem],
    model: str = MODERATION_MODEL,
    timeout_seconds: float = MODERATION_TIMEOUT_SECONDS,
) -> ModerationOutcome:
    """Moderate text with the supplied class-scoped client and persist the verdict.

    Items identify user/assistant messages or individual reasoning-summary parts.
    The caller establishes source provenance. The ordered source mapping is saved
    before the call, without copying text.
    Any flagged item flags the check. All API moderation categories are respected.
    The run must already be committed. Native Responses moderation and release
    fields are untouched. API failures raise ModerationCheckError after saving
    ERRORED; task cancellation saves CANCELLED and propagates CancelledError.
    """
    stage = schemas.ModerationCheckStage(stage)
    items = tuple(ModerationTextItem.model_validate(item) for item in items)
    inputs = [item.text for item in items]
    if not inputs or any(
        not isinstance(item, str) or not item.strip() for item in inputs
    ):
        raise ValueError("Moderation requires non-empty text inputs.")
    if not model.strip():
        raise ValueError("Moderation requires a model.")
    if not math.isfinite(timeout_seconds) or timeout_seconds <= 0:
        raise ValueError("Moderation timeout must be finite and positive.")

    creation = asyncio.create_task(_create_check(run_id, stage, model, items))
    try:
        check_id = await asyncio.shield(creation)
    except asyncio.CancelledError:
        check_id = await creation
        await _save_terminal_check(check_id, schemas.ModerationCheckStatus.CANCELLED)
        raise

    try:
        # Also bound total wall time, including retries performed by the SDK.
        async with asyncio.timeout(timeout_seconds):
            response = await client.moderations.create(
                input=inputs,
                model=model,
                timeout=timeout_seconds,
            )
        try:
            if (
                not isinstance(response.results, list)
                or len(response.results) != len(inputs)
                or any(type(item.flagged) is not bool for item in response.results)
                or not isinstance(response.model, str)
                or not response.model.strip()
            ):
                raise _InvalidModerationResponse()
            flagged = any(item.flagged for item in response.results)
            result = response.model_dump(mode="json")
            if (
                not isinstance(result, dict)
                or not isinstance(result.get("results"), list)
                or len(result["results"]) != len(inputs)
                or any(
                    not isinstance(item, dict) or type(item.get("flagged")) is not bool
                    for item in result["results"]
                )
                or [item["flagged"] for item in result["results"]]
                != [item.flagged for item in response.results]
            ):
                raise _InvalidModerationResponse()
        except (AttributeError, TypeError, ValueError):
            raise _InvalidModerationResponse() from None
    except asyncio.CancelledError:
        await _save_terminal_check(check_id, schemas.ModerationCheckStatus.CANCELLED)
        raise
    except Exception as exc:
        if isinstance(exc, (TimeoutError, openai.APITimeoutError)):
            code = "moderation_timeout"
        elif isinstance(exc, _InvalidModerationResponse):
            code = "invalid_moderation_response"
        else:
            code = "moderation_api_error"
        error: dict[str, Any] = {"code": code, "type": type(exc).__name__}
        if isinstance(exc, openai.APIStatusError):
            error["status_code"] = exc.status_code
            error["request_id"] = exc.request_id
        # Provider exception messages/bodies can echo input; retain only safe metadata.
        await _save_terminal_check(
            check_id, schemas.ModerationCheckStatus.ERRORED, error=error
        )
        raise ModerationCheckError(check_id, code) from None

    await _save_terminal_check(
        check_id,
        schemas.ModerationCheckStatus.FLAGGED
        if flagged
        else schemas.ModerationCheckStatus.PASSED,
        result=result,
    )
    return ModerationOutcome(check_id=check_id, flagged=flagged, model=response.model)
