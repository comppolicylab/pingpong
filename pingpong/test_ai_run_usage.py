from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from openai.types.responses import (
    Response,
    ResponseCompletedEvent,
    ResponseFailedEvent,
    ResponseIncompleteEvent,
    ResponseUsage,
)

from sqlalchemy import event as sqlalchemy_event

from pingpong import models, schemas
from pingpong.ai import BufferedResponseStreamHandler
from pingpong.authz import AuthzClient

pytestmark = pytest.mark.asyncio


def make_handler(run_id: int) -> BufferedResponseStreamHandler:
    return BufferedResponseStreamHandler(
        session=None,
        auth=AsyncMock(spec=AuthzClient),
        cli=None,
        run_id=run_id,
        run_status=schemas.RunStatus.IN_PROGRESS,
        prev_output_index=-1,
        file_names={},
        class_id=1,
        thread_id=1,
        assistant_id=1,
        user_id=1,
    )


@pytest.mark.parametrize(
    ("event_type", "status"),
    [
        (ResponseCompletedEvent, schemas.RunStatus.COMPLETED),
        (ResponseFailedEvent, schemas.RunStatus.FAILED),
        (ResponseIncompleteEvent, schemas.RunStatus.INCOMPLETE),
    ],
)
async def test_terminal_response_persists_full_usage(db, event_type, status):
    payload = {
        "input_tokens": 120,
        "input_tokens_details": {"cached_tokens": 60, "cache_write_tokens": 20},
        "output_tokens": 30,
        "output_tokens_details": {"reasoning_tokens": 10},
        "total_tokens": 150,
        "additional_usage_detail": {"tokens": 5},
    }
    async with db.async_session() as session:
        run = models.Run(status=schemas.RunStatus.IN_PROGRESS)
        session.add(run)
        await session.flush()
        run_id = run.id
        await session.commit()

    event = event_type.model_construct(
        response=Response.model_construct(
            status=status.value,
            output=[],
            usage=ResponseUsage.model_validate(payload),
        )
    )
    await make_handler(run_id).on_response_completed(event)

    async with db.async_session() as session:
        run = await session.get(models.Run, run_id)
        assert run.usage == payload
        assert run.status == status
        assert run.completed is not None
        assert run.provider_metadata is None


@pytest.mark.parametrize("completion", ["cleanup", "missing_usage", "forced_stop"])
async def test_completion_without_usage_preserves_saved_usage(db, completion):
    payload = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
    async with db.async_session() as session:
        run = models.Run(status=schemas.RunStatus.IN_PROGRESS, usage=payload)
        session.add(run)
        await session.flush()
        run_id = run.id
        await session.commit()

    handler = make_handler(run_id)
    if completion == "cleanup":
        await handler.cleanup(run_status=schemas.RunStatus.FAILED)
    elif completion == "forced_stop":
        await handler.on_response_completed(None)
    else:
        await handler.on_response_completed(
            ResponseCompletedEvent.model_construct(
                response=Response.model_construct(
                    status="completed", output=[], usage=None
                )
            )
        )

    async with db.async_session() as session:
        run = await session.get(models.Run, run_id)
        assert run.usage == payload


async def test_run_without_reported_usage_stays_null(db):
    async with db.async_session() as session:
        run = models.Run(status=schemas.RunStatus.IN_PROGRESS)
        session.add(run)
        await session.flush()
        run_id = run.id
        await session.commit()

    await make_handler(run_id).cleanup(run_status=schemas.RunStatus.FAILED)

    async with db.async_session() as session:
        run = await session.get(models.Run, run_id)
        assert run.usage is None


@pytest.mark.parametrize("code", [4013, 0, "provider_error", None])
async def test_text_run_error_code_is_text_before_database_binding(db, code):
    async with db.async_session() as session:
        run = models.Run(status=schemas.RunStatus.IN_PROGRESS)
        session.add(run)
        await session.flush()
        run_id = run.id
        await session.commit()

    async with db.async_session() as session:
        connection = await session.connection()
        bound_codes = []

        def check_error_code(conn, cursor, statement, parameters, context, executemany):
            for values in context.compiled_parameters or []:
                if "error_code" in values:
                    bound_codes.append(values["error_code"])
                    assert values["error_code"] is None or isinstance(
                        values["error_code"], str
                    )

        sqlalchemy_event.listen(
            connection.sync_connection, "before_cursor_execute", check_error_code
        )
        await models.Run.mark_as_status(
            session,
            run_id,
            status=schemas.RunStatus.FAILED,
            error_code=code,
            error_message="Synthetic provider failure.",
            incomplete_reason=None,
        )
        assert bound_codes == [str(code) if code is not None else None]
        await session.commit()

    async with db.async_session() as session:
        run = await session.get(models.Run, run_id)
        assert run.error_code == (str(code) if code is not None else None)
        assert run.status == schemas.RunStatus.FAILED
