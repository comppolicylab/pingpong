import asyncio
import importlib
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx2
import openai
import orjson
import pytest
from sqlalchemy import select

from pingpong import models, moderation, schemas
from pingpong.test_moderation import response_for
from pingpong.testutil import with_authz, with_user

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def conversation(db, path):
    async with db.async_session() as session:
        session.add(models.Class(id=1, name="Class", api_key="test-key"))
        session.add(
            models.Assistant(
                id=2,
                name="Assistant",
                class_id=1,
                version=3,
                model="gpt-4o-mini",
                instructions="Be helpful.",
                input_moderation_enabled=True,
            )
        )
        thread = models.Thread(
            id=20,
            class_id=1,
            assistant_id=2,
            version=3,
            name="Conversation",
            tools_available="[]",
            instructions="Be helpful.",
            user_message_ct=4,
            input_moderation_enabled=True,
        )
        run = models.Run.for_thread(
            thread,
            id=30,
            assistant_id=2,
            creator_id=123,
            model="gpt-4o-mini",
            status=schemas.RunStatus.PENDING
            if path == "pending_run"
            else schemas.RunStatus.COMPLETED,
        )
        if path == "pending_run":
            run.messages = [
                models.Message(
                    thread_id=20,
                    output_index=1,
                    message_status=schemas.MessageStatus.COMPLETED,
                    role=schemas.MessageRole.USER,
                    content=[
                        models.MessagePart(
                            part_index=0,
                            type=schemas.MessagePartType.INPUT_TEXT,
                            text="Hello",
                        )
                    ],
                )
            ]
            # Resuming a run must use its snapshot rather than the current setting.
            thread.input_moderation_enabled = False
        session.add_all([thread, run])
        await session.commit()


@with_user(123)
@with_authz(
    grants=[
        ("user:123", "can_participate", "thread:20"),
        ("user:123", "can_interact_with", "assistant:2"),
    ]
)
@pytest.mark.parametrize("path", ["message", "pending_run"])
@pytest.mark.parametrize("verdict", ["passed", "flagged", "errored", "disabled"])
async def test_input_review_precedes_generation_and_closes_flagged_threads(
    api, db, conversation, valid_user_token, monkeypatch, path, verdict
):
    server = importlib.import_module("pingpong.server")
    if verdict == "disabled":
        async with db.async_session() as session:
            thread = await session.get(models.Thread, 20)
            run = await session.get(models.Run, 30)
            assistant = await session.get(models.Assistant, 2)
            assistant.input_moderation_enabled = False
            thread.input_moderation_enabled = False
            run.input_moderation_enabled = False
            await session.commit()
    events = []

    async def create(**kwargs):
        assert kwargs["input"] == ["Hello"]
        # Input, reserved run, and pending check must be committed before the call.
        async with db.async_session() as session:
            check = await session.scalar(select(models.RunModerationCheck))
            assert check.status == schemas.ModerationCheckStatus.PENDING
            run = await session.get(models.Run, check.run_id)
            assert run.status == schemas.RunStatus.QUEUED
            assert len(check.message_ids) == 1
        events.append("moderation")
        if verdict == "errored":
            raise openai.APITimeoutError(
                request=httpx2.Request("POST", "https://example.invalid")
            )
        return response_for(verdict == "flagged")[0]

    client = SimpleNamespace(
        moderations=SimpleNamespace(create=AsyncMock(side_effect=create))
    )
    monkeypatch.setitem(
        server.v1.dependency_overrides,
        server.get_openai_client_for_class,
        lambda: client,
    )
    monkeypatch.setattr(server, "ensure_model_available", AsyncMock())

    async def name(*args, **kwargs):
        events.append("name")
        return "Conversation"

    monkeypatch.setattr(server, "get_thread_conversation_name", name)

    async def generate(*args, **kwargs):
        events.append("generation")
        if verdict != "disabled":
            async with db.async_session() as session:
                run = await session.get(models.Run, kwargs["run"].id)
                run.status = schemas.RunStatus.COMPLETED
                await session.commit()
        yield b'{"type":"done"}\n'

    monkeypatch.setattr(server, "run_response", generate)
    url = "/api/v1/class/1/thread/20" + ("/run" if path == "pending_run" else "")
    headers = {"Authorization": f"Bearer {valid_user_token}"}
    response = api.post(
        url, json={} if path == "pending_run" else {"message": "Hello"}, headers=headers
    )
    assert response.status_code == 200, response.text
    if verdict == "flagged":
        assert events == ["moderation"]
        assert [
            orjson.loads(line)["type"] for line in response.content.splitlines()
        ] == ["error", "done"]
        # Both turn endpoints must stay closed, even if the setting is disabled.
        async with db.async_session() as session:
            thread = await session.get(models.Thread, 20)
            thread.input_moderation_enabled = False
            await session.commit()
        for suffix, body in [("", {"message": "Again"}), ("/run", {})]:
            blocked = api.post(
                "/api/v1/class/1/thread/20" + suffix, json=body, headers=headers
            )
            assert blocked.status_code == 403, blocked.text
        async with db.async_session() as session:
            check = await session.scalar(select(models.RunModerationCheck))
            run = await session.get(models.Run, check.run_id)
            assert run.status == schemas.RunStatus.INCOMPLETE
            assert not await session.scalar(
                select(models.Message.id).where(
                    models.Message.role == schemas.MessageRole.ASSISTANT
                )
            )
    else:
        assert events[-1] == "generation"
        if verdict != "disabled":
            assert events[0] == "moderation"
        else:
            client.moderations.create.assert_not_awaited()
    async with db.async_session() as session:
        check = await session.scalar(select(models.RunModerationCheck))
        assert (check is None) == (verdict == "disabled")
        if check is not None:
            assert check.status.value == verdict


async def test_run_snapshots_input_moderation_setting(db):
    async with db.async_session() as session:
        thread = models.Thread(version=3, input_moderation_enabled=True)
        session.add(thread)
        await session.flush()
        run = models.Run.for_thread(thread, status=schemas.RunStatus.PENDING)
        session.add(run)
        await session.commit()
        thread.input_moderation_enabled = False
        await session.commit()
        await session.refresh(run)
        assert run.input_moderation_enabled
        assert not models.Run.for_thread(
            thread, status=schemas.RunStatus.PENDING
        ).input_moderation_enabled
    assert not models.Run.for_thread(
        models.Thread(), status=schemas.RunStatus.PENDING
    ).input_moderation_enabled


async def test_input_loader_skips_empty_and_non_user_text(db):
    async with db.async_session() as session:
        thread = models.Thread(version=3)
        session.add(thread)
        await session.flush()
        run = models.Run.for_thread(
            thread,
            status=schemas.RunStatus.QUEUED,
            messages=[
                models.Message(
                    thread_id=thread.id,
                    role=role,
                    is_hidden=hidden,
                    message_status=schemas.MessageStatus.COMPLETED,
                    output_index=index,
                    content=[
                        models.MessagePart(part_index=0, type=part_type, text=text)
                    ],
                )
                for index, (role, part_type, text, hidden) in enumerate(
                    [
                        (
                            schemas.MessageRole.USER,
                            schemas.MessagePartType.INPUT_TEXT,
                            "  ",
                            False,
                        ),
                        (
                            schemas.MessageRole.DEVELOPER,
                            schemas.MessagePartType.INPUT_TEXT,
                            "Private instructions",
                            True,
                        ),
                        (
                            schemas.MessageRole.ASSISTANT,
                            schemas.MessagePartType.OUTPUT_TEXT,
                            "Prior answer",
                            False,
                        ),
                        (
                            schemas.MessageRole.USER,
                            schemas.MessagePartType.INPUT_TEXT,
                            "Hidden system-authored context",
                            True,
                        ),
                    ]
                )
            ],
        )
        session.add(run)
        await session.commit()
        run_id = run.id
    client = SimpleNamespace(moderations=SimpleNamespace(create=AsyncMock()))
    assert await moderation.check_run_input(client, run_id)
    client.moderations.create.assert_not_awaited()


async def test_interrupted_input_review_settles_run(db):
    server = importlib.import_module("pingpong.server")
    started = asyncio.Event()

    async def create(**kwargs):
        started.set()
        await asyncio.Event().wait()

    client = SimpleNamespace(moderations=SimpleNamespace(create=create))
    async with db.async_session() as session:
        thread = models.Thread(version=3, input_moderation_enabled=True)
        session.add(thread)
        await session.flush()
        run = models.Run.for_thread(
            thread,
            status=schemas.RunStatus.PENDING,
            messages=[
                models.Message(
                    thread_id=thread.id,
                    output_index=1,
                    role=schemas.MessageRole.USER,
                    message_status=schemas.MessageStatus.COMPLETED,
                    content=[
                        models.MessagePart(
                            part_index=0,
                            type=schemas.MessagePartType.INPUT_TEXT,
                            text="Hello",
                        )
                    ],
                )
            ],
        )
        session.add(run)
        await session.flush()
        task = asyncio.create_task(
            server._moderate_run_input(
                SimpleNamespace(state={"db": session}), client, run
            )
        )
        await asyncio.wait_for(started.wait(), timeout=2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            _ = await task
        await session.refresh(run)
        assert run.status == schemas.RunStatus.INCOMPLETE
        check = await session.scalar(select(models.RunModerationCheck))
        assert check.status == schemas.ModerationCheckStatus.CANCELLED


@with_user(123)
@with_authz(
    grants=[
        ("user:123", "can_participate", "thread:20"),
        ("user:123", "can_interact_with", "assistant:2"),
    ]
)
@pytest.mark.parametrize("path", ["message"])
@pytest.mark.parametrize("naming_error", [False, True])
async def test_chat_naming_uses_previous_messages_and_preserves_title_on_exception(
    api, db, conversation, valid_user_token, monkeypatch, path, naming_error
):
    from pingpong import ai

    server = importlib.import_module("pingpong.server")
    async with db.async_session() as session:
        thread = await session.get(models.Thread, 20)
        thread.user_message_ct = 3
        assistant = await session.get(models.Assistant, 2)
        assistant.input_moderation_enabled = False
        assistant.allow_user_image_uploads = True
        await models.File.create(
            session,
            {
                "file_id": "file-image",
                "name": "image.png",
                "content_type": "image/png",
                "private": False,
            },
            class_id=1,
        )
        await session.commit()

    def empty_client():
        return SimpleNamespace()

    monkeypatch.setitem(
        server.v1.dependency_overrides,
        server.get_openai_client_for_class,
        empty_client,
    )
    monkeypatch.setattr(server, "ensure_model_available", AsyncMock())
    generate_name = AsyncMock(
        return_value="New title",
        side_effect=RuntimeError("Title generation failed") if naming_error else None,
    )
    monkeypatch.setattr(ai, "generate_thread_name", generate_name)

    async def generate(*args, **kwargs):
        yield b'{"type":"done"}\n'

    monkeypatch.setattr(server, "run_response", generate)
    response = api.post(
        "/api/v1/class/1/thread/20",
        json={"message": "Hello", "vision_file_ids": ["file-image"]},
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )
    assert response.status_code == (500 if naming_error else 200), response.text
    generate_name.assert_awaited_once()
    transcript = generate_name.await_args.args[2]
    assert transcript.count("USER: Uploaded an image file") == 1
    assert "Hello" not in transcript
    async with db.async_session() as session:
        thread = await session.get(models.Thread, 20)
        assert thread.name == ("Conversation" if naming_error else "New title")
