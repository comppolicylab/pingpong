from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import openai
import orjson
import pytest
from openai.types.responses import ResponseErrorEvent, ResponseFailedEvent

from pingpong import ai, models, schemas
from pingpong.ai_error import MODEL_NOT_AVAILABLE_MESSAGE, get_ai_error_message


@pytest.mark.parametrize(
    "code", ["model_not_found", "model_unavailable", "invalid_value"]
)
@pytest.mark.parametrize(
    "stage", ["create", "stream_exception", "error_event", "response_failed"]
)
@pytest.mark.parametrize(
    "mode",
    [
        schemas.InteractionMode.CHAT,
        schemas.InteractionMode.LECTURE_VIDEO,
        schemas.InteractionMode.LECTURE_SLIDES,
    ],
)
async def test_chat_and_lecture_model_errors_are_actionable(
    db, monkeypatch, code, stage, mode
):
    class FakeAuthzDriver:
        async def init(self):
            pass

        @asynccontextmanager
        async def get_client(self):
            yield AsyncMock()

    monkeypatch.setattr(ai.config.authz, "driver", FakeAuthzDriver())
    provider_message = "Synthetic provider failure."
    error = openai.NotFoundError(
        provider_message,
        response=httpx.Response(
            404, request=httpx.Request("POST", "https://example.test/responses")
        ),
        body={
            "code": code,
            "type": "invalid_request_error",
            "message": provider_message,
        },
    )

    async def events():
        if stage == "stream_exception":
            raise error
        if stage == "error_event":
            yield ResponseErrorEvent.model_construct(
                type="error", code=code, message=provider_message, param=None
            )
        elif stage == "response_failed":
            yield ResponseFailedEvent.model_construct(
                type="response.failed",
                response=SimpleNamespace(
                    status="failed",
                    output=[],
                    usage=None,
                    moderation=None,
                    error=SimpleNamespace(code=code, message=provider_message),
                    incomplete_details=None,
                ),
            )

    client = SimpleNamespace(
        responses=SimpleNamespace(
            create=AsyncMock(
                side_effect=error if stage == "create" else None,
                return_value=events(),
            )
        )
    )
    async with db.async_session() as session:
        thread = models.Thread(version=3, tools_available="[]")
        session.add(thread)
        await session.flush()
        run = models.Run(
            status=schemas.RunStatus.QUEUED,
            thread_id=thread.id,
            model="gpt-4o-mini",
            tools_available="[]",
        )
        session.add(run)
        await session.flush()
        run_id = run.id
        await session.commit()

    chunks = [
        chunk
        async for chunk in ai.run_response(
            client, run=run, class_id="1", interaction_mode=mode
        )
    ]
    messages = [
        orjson.loads(line)
        for chunk in chunks
        for line in chunk.splitlines()
        if line.strip()
    ]
    errors = [message["detail"] for message in messages if message["type"] == "error"]
    if code in {"model_not_found", "model_unavailable"}:
        expected_message = MODEL_NOT_AVAILABLE_MESSAGE
    elif stage in {"create", "stream_exception"}:
        expected_message = (
            "OpenAI was unable to process your request. " + provider_message
        )
    else:
        expected_message = provider_message
    assert errors
    assert all(message == expected_message for message in errors)
    client.responses.create.assert_awaited_once()
    async with db.async_session() as session:
        saved_run = await session.get(models.Run, run_id)
        assert saved_run.status == schemas.RunStatus.FAILED
        if code == "invalid_value" and stage == "create":
            assert saved_run.error_message == f"Error in response stream: {error}"
        else:
            assert saved_run.error_message == expected_message


def test_other_ai_errors_keep_their_message():
    assert (
        get_ai_error_message(SimpleNamespace(code="rate_limit_exceeded"), "Try later.")
        == "Try later."
    )


@pytest.mark.parametrize("stage", ["create", "run_failed"])
@pytest.mark.parametrize("code", ["model_not_found", "model_unavailable"])
async def test_legacy_chat_model_errors_are_actionable(stage, code):
    from openai.types.beta.assistant_stream_event import ThreadRunFailed

    provider_message = "Synthetic legacy provider failure."
    error = openai.NotFoundError(
        provider_message,
        response=httpx.Response(
            404, request=httpx.Request("POST", "https://example.test/runs")
        ),
        body={
            "code": code,
            "type": "invalid_request_error",
            "message": provider_message,
        },
    )

    async def events():
        yield ThreadRunFailed.model_construct(
            data=SimpleNamespace(
                last_error=SimpleNamespace(code=code, message=provider_message)
            )
        )

    @asynccontextmanager
    async def stream(**kwargs):
        if stage == "create":
            raise error
        yield events()

    client = SimpleNamespace(
        beta=SimpleNamespace(
            threads=SimpleNamespace(runs=SimpleNamespace(stream=stream))
        )
    )
    chunks = [
        chunk
        async for chunk in ai.run_thread(
            client,
            class_id="1",
            thread_id="synthetic-thread",
            local_thread_id=1,
            assistant_id=1,
            message=[],
        )
    ]
    errors = [
        orjson.loads(line)
        for chunk in chunks
        for line in chunk.splitlines()
        if line.strip()
    ]
    assert errors[-1] == {"type": "done"}
    errors = [message for message in errors if message["type"] != "done"]
    assert errors == [
        {
            "type": "presend_error" if stage == "create" else "error",
            "detail": MODEL_NOT_AVAILABLE_MESSAGE,
        }
    ]
