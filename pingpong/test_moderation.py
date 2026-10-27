import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx2
import openai
import pytest
from sqlalchemy import delete, select, update

from pingpong import models, schemas
from pingpong import moderation


pytestmark = pytest.mark.asyncio


@pytest.fixture
async def moderation_run(db):
    async with db.async_session() as session:
        thread = models.Thread(version=3)
        session.add(thread)
        await session.flush()
        run = models.Run(
            thread_id=thread.id,
            status=schemas.RunStatus.IN_PROGRESS,
            release_type=schemas.ThreadReleaseType.AFTER_INPUT_AND_OUTPUT_MODERATION,
            release_status=schemas.RunReleaseStatus.PENDING,
            moderation={"native_responses": "preserve"},
        )
        session.add(run)
        await session.flush()
        await session.commit()
        return run.id


def make_items(text, stage=schemas.ModerationCheckStage.INPUT):
    texts = [text] if isinstance(text, str) else list(text)
    first_id = 101 if stage == schemas.ModerationCheckStage.INPUT else 201
    return [
        moderation.ModerationTextItem(
            text=value,
            source_type=schemas.ModerationSourceType.MESSAGE,
            source_id=first_id + index,
        )
        for index, value in enumerate(texts)
    ]


def response_for(*flags):
    payload = {
        "id": "mod-test",
        "model": "omni-moderation-test",
        "results": [
            {
                "flagged": flag,
                "categories": {"violence": flag},
                "category_scores": {"violence": 0.9 if flag else 0.01},
            }
            for flag in flags
        ],
    }
    return SimpleNamespace(
        results=[SimpleNamespace(flagged=flag) for flag in flags],
        model=payload["model"],
        model_dump=lambda **kwargs: payload,
    ), payload


async def get_check(db, check_id):
    async with db.async_session() as session:
        return await session.get(models.RunModerationCheck, check_id)


@pytest.mark.parametrize("stage", list(schemas.ModerationCheckStage))
@pytest.mark.parametrize("flags", [(False,), (True,), (False, True)])
async def test_moderation_saves_verdict_and_preserves_run(
    db, moderation_run, stage, flags
):
    response, payload = response_for(*flags)
    create = AsyncMock(return_value=response)
    text = "User text" if len(flags) == 1 else ["First message", "Second message"]
    outcome = await moderation.moderate_run_text(
        SimpleNamespace(moderations=SimpleNamespace(create=create)),
        run_id=moderation_run,
        stage=stage,
        items=make_items(text, stage),
    )
    create.assert_awaited_once_with(
        input=[text] if isinstance(text, str) else text,
        model=moderation.MODERATION_MODEL,
        timeout=moderation.MODERATION_TIMEOUT_SECONDS,
    )
    assert outcome.flagged == any(flags)
    assert outcome.model == payload["model"]
    check = await get_check(db, outcome.check_id)
    assert check.stage == stage
    assert check.model == moderation.MODERATION_MODEL
    assert check.status == (
        schemas.ModerationCheckStatus.FLAGGED
        if any(flags)
        else schemas.ModerationCheckStatus.PASSED
    )
    assert check.result == payload
    assert check.error is None
    assert check.created is not None
    assert check.completed_at >= check.started_at
    async with db.async_session() as session:
        assert check.source_items == [
            item.model_dump(mode="json", exclude={"text"})
            for item in make_items(text, stage)
        ]
        assert [result["flagged"] for result in check.result["results"]] == list(flags)
        run = await session.get(models.Run, moderation_run)
        assert run.release_status == schemas.RunReleaseStatus.PENDING
        assert run.released_at is None
        assert run.moderation == {"native_responses": "preserve"}


async def test_moderation_persists_pending_before_call_and_cancellation(
    db, moderation_run
):
    started = asyncio.Event()

    async def create(**kwargs):
        started.set()
        await asyncio.Event().wait()

    task = asyncio.create_task(
        moderation.moderate_run_text(
            SimpleNamespace(moderations=SimpleNamespace(create=create)),
            run_id=moderation_run,
            stage=schemas.ModerationCheckStage.INPUT,
            items=make_items("User text"),
        )
    )
    await asyncio.wait_for(started.wait(), timeout=2)
    async with db.async_session() as session:
        check = await session.scalar(select(models.RunModerationCheck))
        assert check.status == schemas.ModerationCheckStatus.PENDING
        assert check.started_at is not None
        assert check.completed_at is None
        check_id = check.id
        assert check.source_items == [{"source_type": "message", "source_id": 101}]
        assert check.result is None
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    check = await get_check(db, check_id)
    assert check.status == schemas.ModerationCheckStatus.CANCELLED
    assert check.completed_at is not None
    assert check.result is None
    assert check.source_items == [{"source_type": "message", "source_id": 101}]


@pytest.mark.parametrize(
    "failure",
    ["timeout", "sdk_timeout", "api", "malformed", "missing_results", "missing_fields"],
)
async def test_moderation_errors_never_return_approval(db, moderation_run, failure):
    request = httpx2.Request("POST", "https://example.invalid/moderations")
    response, _ = response_for()

    async def create(**kwargs):
        if failure == "timeout":
            await asyncio.Event().wait()
        if failure == "sdk_timeout":
            raise openai.APITimeoutError(request=request)
        if failure == "api":
            raise openai.APIStatusError(
                "PRIVATE INPUT MUST NOT BE SAVED",
                response=httpx2.Response(
                    429, request=request, headers={"x-request-id": "req-test"}
                ),
                body={"input": "PRIVATE INPUT"},
            )
        if failure == "malformed":
            response.results = [SimpleNamespace(flagged="false")]
        if failure == "missing_fields":
            return SimpleNamespace()
        return response

    with pytest.raises(moderation.ModerationCheckError) as error:
        await moderation.moderate_run_text(
            SimpleNamespace(moderations=SimpleNamespace(create=create)),
            run_id=moderation_run,
            stage=schemas.ModerationCheckStage.OUTPUT,
            items=make_items("User text", schemas.ModerationCheckStage.OUTPUT),
            timeout_seconds=0.02,
        )
    check = await get_check(db, error.value.check_id)
    assert check.status == schemas.ModerationCheckStatus.ERRORED
    assert check.result is None
    assert check.source_items == [{"source_type": "message", "source_id": 201}]
    assert check.completed_at is not None
    expected = (
        "moderation_timeout"
        if "timeout" in failure
        else "moderation_api_error"
        if failure == "api"
        else "invalid_moderation_response"
    )
    assert check.error["code"] == expected
    assert error.value.code == expected
    assert "PRIVATE INPUT" not in str(check.error)
    assert "PRIVATE INPUT" not in str(error.value)
    if failure == "api":
        assert check.error["status_code"] == 429
        assert check.error["request_id"] == "req-test"


@pytest.mark.parametrize("text", ["", "   ", [], ["valid", ""], [123]])
async def test_invalid_input_does_not_call_api(db, moderation_run, text):
    create = AsyncMock()
    with pytest.raises(ValueError):
        await moderation.moderate_run_text(
            SimpleNamespace(moderations=SimpleNamespace(create=create)),
            run_id=moderation_run,
            stage=schemas.ModerationCheckStage.INPUT,
            items=make_items(text),
        )
    create.assert_not_awaited()
    async with db.async_session() as session:
        assert await session.scalar(select(models.RunModerationCheck.id)) is None


async def test_missing_run_does_not_call_api(db):
    create = AsyncMock()
    with pytest.raises(ValueError, match="committed run"):
        await moderation.moderate_run_text(
            SimpleNamespace(moderations=SimpleNamespace(create=create)),
            run_id=999,
            stage=schemas.ModerationCheckStage.INPUT,
            items=make_items("User text"),
        )
    create.assert_not_awaited()


async def test_cancellation_during_result_save_preserves_verdict(
    db, moderation_run, monkeypatch
):
    saving = asyncio.Event()
    finish = asyncio.Event()
    original = moderation._finish_check

    async def delayed_save(*args, **kwargs):
        saving.set()
        await finish.wait()
        await original(*args, **kwargs)

    monkeypatch.setattr(moderation, "_finish_check", delayed_save)
    response, payload = response_for(False)
    task = asyncio.create_task(
        moderation.moderate_run_text(
            SimpleNamespace(
                moderations=SimpleNamespace(create=AsyncMock(return_value=response))
            ),
            run_id=moderation_run,
            stage=schemas.ModerationCheckStage.INPUT,
            items=make_items("User text"),
        )
    )
    await asyncio.wait_for(saving.wait(), timeout=2)
    task.cancel()
    finish.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    async with db.async_session() as session:
        check = await session.scalar(select(models.RunModerationCheck))
        assert check.status == schemas.ModerationCheckStatus.PASSED
        assert check.result == payload


async def test_cancellation_during_creation_finishes_check(
    db, moderation_run, monkeypatch
):
    created = asyncio.Event()
    finish = asyncio.Event()
    original = moderation._create_check

    async def delayed_create(*args):
        check_id = await original(*args)
        created.set()
        await finish.wait()
        return check_id

    monkeypatch.setattr(moderation, "_create_check", delayed_create)
    create = AsyncMock()
    task = asyncio.create_task(
        moderation.moderate_run_text(
            SimpleNamespace(moderations=SimpleNamespace(create=create)),
            run_id=moderation_run,
            stage=schemas.ModerationCheckStage.INPUT,
            items=make_items("User text"),
        )
    )
    await asyncio.wait_for(created.wait(), timeout=2)
    task.cancel()
    finish.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    create.assert_not_awaited()
    async with db.async_session() as session:
        check = await session.scalar(select(models.RunModerationCheck))
        assert check.status == schemas.ModerationCheckStatus.CANCELLED
        assert check.completed_at is not None


async def test_deleted_check_cannot_return_approval(db, moderation_run):
    async def create(**kwargs):
        async with db.async_session() as session:
            await session.execute(delete(models.RunModerationCheck))
            await session.commit()
        return response_for(False)[0]

    with pytest.raises(LookupError, match="no longer exists"):
        await moderation.moderate_run_text(
            SimpleNamespace(moderations=SimpleNamespace(create=create)),
            run_id=moderation_run,
            stage=schemas.ModerationCheckStage.INPUT,
            items=make_items("User text"),
        )


async def test_output_maps_assistant_and_summary_results(db, moderation_run):
    items = [
        moderation.ModerationTextItem(
            text="Assistant answer",
            source_type=schemas.ModerationSourceType.MESSAGE,
            source_id=201,
        ),
        moderation.ModerationTextItem(
            text="Reasoning summary",
            source_type=schemas.ModerationSourceType.REASONING_SUMMARY,
            source_id=301,
        ),
    ]
    response, payload = response_for(False, True)
    create = AsyncMock(return_value=response)
    outcome = await moderation.moderate_run_text(
        SimpleNamespace(moderations=SimpleNamespace(create=create)),
        run_id=moderation_run,
        stage=schemas.ModerationCheckStage.OUTPUT,
        items=items,
    )
    assert create.await_args.kwargs["input"] == [
        "Assistant answer",
        "Reasoning summary",
    ]
    assert outcome.flagged
    saved = await get_check(db, outcome.check_id)
    assert saved.source_items == [
        item.model_dump(mode="json", exclude={"text"}) for item in items
    ]
    assert saved.result == payload
    assert [
        (source["source_type"], source["source_id"], result["flagged"])
        for source, result in zip(
            saved.source_items, saved.result["results"], strict=True
        )
    ] == [("message", 201, False), ("reasoning_summary", 301, True)]


@pytest.mark.parametrize(
    "source",
    [
        {"source_type": "unknown", "source_id": 101},
        {"source_type": "message", "source_id": 0},
        {"source_type": "message", "source_id": -1},
        {"source_type": "message"},
        {"source_type": "message", "source_id": 101, "extra": "unexpected"},
    ],
)
async def test_invalid_source_structure_is_rejected_before_api(
    db, moderation_run, source
):
    create = AsyncMock()
    with pytest.raises(ValueError):
        await moderation.moderate_run_text(
            SimpleNamespace(moderations=SimpleNamespace(create=create)),
            run_id=moderation_run,
            stage=schemas.ModerationCheckStage.INPUT,
            items=[{"text": "Text", **source}],
        )
    create.assert_not_awaited()
    async with db.async_session() as session:
        assert await session.scalar(select(models.RunModerationCheck.id)) is None


async def test_source_mapping_mismatch_does_not_save_verdict(db, moderation_run):
    async def create(**kwargs):
        async with db.async_session() as session:
            await session.execute(
                update(models.RunModerationCheck).values(source_items=[])
            )
            await session.commit()
        return response_for(False, True)[0]

    with pytest.raises(ValueError, match="mapping"):
        await moderation.moderate_run_text(
            SimpleNamespace(moderations=SimpleNamespace(create=create)),
            run_id=moderation_run,
            stage=schemas.ModerationCheckStage.OUTPUT,
            items=make_items(["First", "Second"], schemas.ModerationCheckStage.OUTPUT),
        )
    async with db.async_session() as session:
        check = await session.scalar(select(models.RunModerationCheck))
        assert check.status == schemas.ModerationCheckStatus.PENDING
        assert check.result is None
        assert check.completed_at is None
        assert check.source_items == []
