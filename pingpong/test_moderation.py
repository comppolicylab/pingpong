from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx2
import openai
import pytest
from sqlalchemy import select

from pingpong import models, moderation, schemas

pytestmark = pytest.mark.asyncio


def response_for(*flags):
    payload = {
        "id": "mod-test",
        "model": "omni-moderation-test",
        "results": [
            {"flagged": flag, "categories": {"violence": flag}} for flag in flags
        ],
    }
    return SimpleNamespace(model_dump=lambda **kwargs: payload), payload


@pytest.fixture
async def moderation_run(db):
    async with db.async_session() as session:
        thread = models.Thread(version=3)
        session.add(thread)
        await session.flush()
        run = models.Run.for_thread(
            thread,
            status=schemas.RunStatus.QUEUED,
            moderation={"native_responses": "preserve"},
            messages=[
                models.Message(
                    thread_id=thread.id,
                    role=schemas.MessageRole.USER,
                    message_status=schemas.MessageStatus.COMPLETED,
                    output_index=index,
                    content=[
                        models.MessagePart(
                            part_index=1,
                            type=schemas.MessagePartType.INPUT_TEXT,
                            text="second",
                        ),
                        models.MessagePart(
                            part_index=0,
                            type=schemas.MessagePartType.INPUT_TEXT,
                            text=f"Message {index}",
                        ),
                    ],
                )
                for index in [2, 1]
            ],
        )
        session.add(run)
        await session.commit()
        return run.id


@pytest.mark.parametrize("flags", [(False, False), (False, True)])
async def test_input_check_preserves_order_and_provider_metadata(
    db, moderation_run, flags
):
    response, payload = response_for(*flags)
    create = AsyncMock(return_value=response)
    assert await moderation.check_run_input(
        SimpleNamespace(moderations=SimpleNamespace(create=create)), moderation_run
    ) == (not any(flags))
    create.assert_awaited_once_with(
        input=["Message 1\n\nsecond", "Message 2\n\nsecond"],
        model=moderation.MODERATION_MODEL,
        timeout=moderation.MODERATION_TIMEOUT_SECONDS,
    )
    async with db.async_session() as session:
        check = await session.scalar(select(models.RunModerationCheck))
        messages = (
            await session.scalars(
                select(models.Message).order_by(models.Message.output_index)
            )
        ).all()
        assert check.message_ids == [message.id for message in messages]
        assert check.result == payload
        assert check.status == (
            schemas.ModerationCheckStatus.FLAGGED
            if any(flags)
            else schemas.ModerationCheckStatus.PASSED
        )
        assert check.completed_at >= check.started_at
        run = await session.get(models.Run, moderation_run)
        assert run.moderation == {"native_responses": "preserve"}


@pytest.mark.parametrize(
    "failure", ["timeout", "api", "missing_results", "missing_flag", "invalid_flag"]
)
async def test_failed_checks_are_recorded_and_fail_open(
    db, moderation_run, monkeypatch, failure
):
    monkeypatch.setattr(moderation, "MODERATION_TIMEOUT_SECONDS", 0.02)

    async def create(**kwargs):
        if failure == "timeout":
            import asyncio

            await asyncio.Event().wait()
        if failure == "api":
            raise openai.APIStatusError(
                "PRIVATE INPUT MUST NOT BE SAVED",
                response=httpx2.Response(
                    429,
                    request=httpx2.Request("POST", "https://example.invalid"),
                    headers={"x-request-id": "req-test"},
                ),
                body={"input": "PRIVATE INPUT"},
            )
        response, payload = response_for(False, False)
        if failure == "missing_results":
            payload["results"] = []
        elif failure == "missing_flag":
            payload["results"][0].pop("flagged")
        else:
            payload["results"][0]["flagged"] = "false"
        return response

    assert await moderation.check_run_input(
        SimpleNamespace(moderations=SimpleNamespace(create=create)), moderation_run
    )
    async with db.async_session() as session:
        check = await session.scalar(select(models.RunModerationCheck))
        assert check.status == schemas.ModerationCheckStatus.ERRORED
        assert check.result is None
        assert check.completed_at is not None
        assert "PRIVATE INPUT" not in str(check.error)
        assert check.error["code"] == (
            "moderation_timeout"
            if failure == "timeout"
            else "moderation_api_error"
            if failure == "api"
            else "invalid_moderation_response"
        )
        if failure == "api":
            assert check.error["status_code"] == 429
            assert check.error["request_id"] == "req-test"
