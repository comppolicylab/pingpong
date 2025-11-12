from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from pingpong import models, schemas
from pingpong.ai import BufferedResponseStreamHandler
from pingpong.testutil import with_authz, with_user

pytestmark = pytest.mark.asyncio


async def _setup_handler_with_initial_message(db):
    base_time = datetime(2024, 1, 1, tzinfo=timezone.utc)
    user_id = 9001
    class_id = 3001
    assistant_id = 6001
    thread_id = 4001
    run_id = 5001

    async with db.async_session() as session:
        user = models.User(
            id=user_id,
            email="multi-message@test.dev",
            state=schemas.UserState.VERIFIED,
        )
        class_ = models.Class(
            id=class_id, name="Multi Message Class", api_key="sk-test"
        )
        assistant = models.Assistant(
            id=assistant_id,
            name="Handler Assistant",
            class_id=class_id,
            assistant_id="asst-handler",
            model="gpt-4o-mini",
            creator_id=user_id,
        )
        thread = models.Thread(
            id=thread_id,
            thread_id="thread-handler",
            class_id=class_id,
            assistant_id=assistant_id,
            version=3,
            tools_available="",
            private=False,
        )
        run = models.Run(
            id=run_id,
            run_id="run-handler",
            status=schemas.RunStatus.IN_PROGRESS,
            thread_id=thread_id,
            assistant_id=assistant_id,
            creator_id=user_id,
            created=base_time,
            updated=base_time,
        )

        session.add_all([user, class_, assistant, thread, run])
        await session.commit()

    handler = BufferedResponseStreamHandler(
        auth=AsyncMock(),
        cli=AsyncMock(),
        run_id=run_id,
        run_status=schemas.RunStatus.IN_PROGRESS,
        prev_output_index=0,
        file_names={},
        class_id=class_id,
        thread_id=thread_id,
        assistant_id=assistant_id,
        user_id=user_id,
    )
    first_event = SimpleNamespace(
        id="msg-1",
        status=schemas.MessageStatus.IN_PROGRESS.value,
        role="assistant",
    )
    await handler.on_output_message_created(first_event)
    assert handler.message_id is not None
    return handler, run_id, handler.message_id


async def _create_thread_with_duplicate_assistant_messages(
    db,
    *,
    class_id: int,
    thread_id: int,
    run_id: int,
    assistant_id: int,
    older_output_index: int,
    newer_output_index: int,
) -> None:
    base_time = datetime(2024, 1, 1, tzinfo=timezone.utc)
    async with db.async_session() as session:
        class_ = models.Class(id=class_id, name=f"Class {class_id}", api_key="sk-test")
        assistant = models.Assistant(
            id=assistant_id,
            name=f"Assistant {assistant_id}",
            class_id=class_id,
            assistant_id=f"asst-{assistant_id}",
            model="gpt-4o-mini",
        )
        thread = models.Thread(
            id=thread_id,
            thread_id=f"thread-{thread_id}",
            class_id=class_id,
            assistant_id=assistant_id,
            version=3,
            tools_available="",
            private=False,
        )
        run = models.Run(
            id=run_id,
            run_id=f"run-{run_id}",
            status=schemas.RunStatus.COMPLETED,
            thread_id=thread_id,
            assistant_id=assistant_id,
            created=base_time,
            updated=base_time,
        )
        older_message = models.Message(
            message_status=schemas.MessageStatus.COMPLETED,
            run_id=run_id,
            thread_id=thread_id,
            assistant_id=assistant_id,
            role=schemas.MessageRole.ASSISTANT,
            output_index=older_output_index,
            created=base_time,
        )
        newer_message = models.Message(
            message_status=schemas.MessageStatus.COMPLETED,
            run_id=run_id,
            thread_id=thread_id,
            assistant_id=assistant_id,
            role=schemas.MessageRole.ASSISTANT,
            output_index=newer_output_index,
            created=base_time + timedelta(seconds=1),
        )

        session.add_all([class_, assistant, thread, run, older_message, newer_message])
        await session.commit()


async def _create_server_thread(db, *, class_id: int, thread_id: int, run_id: int):
    await _create_thread_with_duplicate_assistant_messages(
        db,
        class_id=class_id,
        thread_id=thread_id,
        run_id=run_id,
        assistant_id=run_id * 2,
        older_output_index=2,
        newer_output_index=8,
    )


async def _create_server_thread_alt(db, *, class_id: int, thread_id: int, run_id: int):
    await _create_thread_with_duplicate_assistant_messages(
        db,
        class_id=class_id,
        thread_id=thread_id,
        run_id=run_id,
        assistant_id=run_id * 3,
        older_output_index=3,
        newer_output_index=7,
    )


async def test_buffered_handler_truncates_after_duplicate_messages(db):
    handler, run_id, first_message_id = await _setup_handler_with_initial_message(db)
    done_event = SimpleNamespace(
        id="msg-1",
        status=schemas.MessageStatus.COMPLETED.value,
    )
    await handler.on_output_message_done(done_event)
    second_event = SimpleNamespace(
        id="msg-2",
        status=schemas.MessageStatus.IN_PROGRESS.value,
        role="assistant",
    )

    await handler.on_output_message_created(second_event)

    assert handler.force_stopped is True
    assert handler.run_id is None
    assert handler.run_status is None
    assert handler.output_message_created_count == 1
    assert handler.force_stop_incomplete_reason is None

    async with db.async_session() as session:
        message = await session.get(models.Message, first_message_id)
        run = await session.get(models.Run, run_id)

    assert message is not None
    assert message.message_status == schemas.MessageStatus.COMPLETED
    assert message.completed is not None
    assert run is not None
    assert run.status == schemas.RunStatus.COMPLETED
    assert run.incomplete_reason == "multi_message_truncate"


@with_user(111)
@with_authz(grants=[("user:111", "can_view", "thread:2101")])
async def test_get_thread_skips_duplicate_assistant_messages(api, db, valid_user_token):
    class_id = 2001
    thread_id = 2101
    run_id = 2201
    await _create_server_thread(
        db,
        class_id=class_id,
        thread_id=thread_id,
        run_id=run_id,
    )

    response = api.get(
        f"/api/v1/class/{class_id}/thread/{thread_id}",
        cookies={"session": valid_user_token},
    )

    assert response.status_code == 200
    messages = response.json()["messages"]
    assert len(messages) == 1
    assert messages[0]["output_index"] == 2
    assert messages[0]["run_id"] == str(run_id)


@with_user(333)
@with_authz(grants=[("user:333", "can_view", "thread:3101")])
async def test_list_thread_messages_deduplicates_extra_assistant_messages(
    api, db, valid_user_token
):
    class_id = 3001
    thread_id = 3101
    run_id = 3201
    await _create_server_thread_alt(
        db,
        class_id=class_id,
        thread_id=thread_id,
        run_id=run_id,
    )

    response = api.get(
        f"/api/v1/class/{class_id}/thread/{thread_id}/messages",
        cookies={"session": valid_user_token},
    )

    assert response.status_code == 200
    messages = response.json()["messages"]
    assert len(messages) == 1
    assert messages[0]["output_index"] == 3
    assert messages[0]["run_id"] == str(run_id)
