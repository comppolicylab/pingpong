import importlib
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from pingpong import models, schemas
from pingpong.testutil import with_authz, with_user


@pytest.mark.asyncio
@pytest.mark.parametrize("release_type", list(schemas.ThreadReleaseType))
async def test_run_release_snapshot_survives_thread_changes(db, release_type):
    async with db.async_session() as session:
        thread = models.Thread(version=3, release_type=release_type)
        session.add(thread)
        await session.flush()
        run = models.Run.for_thread(thread, status=schemas.RunStatus.PENDING)
        session.add(run)
        await session.commit()
        run_id, thread_id = run.id, thread.id
        released_at = run.released_at
        assert (released_at is not None) == (
            release_type == schemas.ThreadReleaseType.IMMEDIATE
        )

    async with db.async_session() as session:
        thread = await session.get(models.Thread, thread_id)
        thread.release_type = (
            schemas.ThreadReleaseType.AFTER_INPUT_MODERATION
            if release_type == schemas.ThreadReleaseType.IMMEDIATE
            else schemas.ThreadReleaseType.IMMEDIATE
        )
        await session.commit()

    async with db.async_session() as session:
        run = await session.get(models.Run, run_id)
        assert run.release_type == release_type
        assert run.release_status == (
            schemas.RunReleaseStatus.RELEASED
            if release_type == schemas.ThreadReleaseType.IMMEDIATE
            else schemas.RunReleaseStatus.PENDING
        )
        assert (
            run.released_at.replace(tzinfo=timezone.utc) if run.released_at else None
        ) == released_at
        thread = await session.get(models.Thread, thread_id)
        next_run = models.Run.for_thread(thread, status=schemas.RunStatus.PENDING)
        assert next_run.release_type == thread.release_type


def test_unflushed_thread_uses_default_release_type():
    run = models.Run.for_thread(models.Thread(), status=schemas.RunStatus.PENDING)
    assert run.release_type == schemas.ThreadReleaseType.IMMEDIATE
    assert run.release_status == schemas.RunReleaseStatus.RELEASED
    assert run.released_at is not None


@with_user(123)
@with_authz(
    grants=[
        ("user:123", "can_participate", "thread:20"),
        ("user:123", "can_interact_with", "assistant:2"),
    ]
)
@pytest.mark.parametrize("release_type", list(schemas.ThreadReleaseType))
@pytest.mark.parametrize("path", ["message", "new_run", "pending_run"])
async def test_generation_run_release_snapshot(
    api, db, valid_user_token, monkeypatch, release_type, path
):
    server = importlib.import_module("pingpong.server")
    previous_release_time = datetime(2024, 1, 1, tzinfo=timezone.utc)
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
            user_message_ct=0,
            release_type=release_type,
        )
        session.add(thread)
        if path in {"pending_run", "message"}:
            if path == "pending_run":
                # The thread now differs from this already-created run's policy.
                thread.release_type = (
                    schemas.ThreadReleaseType.AFTER_INPUT_MODERATION
                    if release_type == schemas.ThreadReleaseType.IMMEDIATE
                    else schemas.ThreadReleaseType.IMMEDIATE
                )
            session.add(
                models.Run(
                    id=30,
                    thread_id=20,
                    assistant_id=2,
                    creator_id=123,
                    status=(
                        schemas.RunStatus.PENDING
                        if path == "pending_run"
                        else schemas.RunStatus.COMPLETED
                    ),
                    model="gpt-4o-mini",
                    release_type=release_type,
                    release_status=(
                        schemas.RunReleaseStatus.RELEASED
                        if release_type == schemas.ThreadReleaseType.IMMEDIATE
                        else schemas.RunReleaseStatus.PENDING
                    ),
                    released_at=(
                        previous_release_time
                        if release_type == schemas.ThreadReleaseType.IMMEDIATE
                        else None
                    ),
                )
            )
        await session.commit()

    seen = {}

    def fake_run_response(*args, **kwargs):
        run = kwargs["run"]
        seen.update(
            id=run.id,
            release_type=run.release_type,
            release_status=run.release_status,
            released_at=run.released_at,
        )

        async def stream():
            yield b'{"type":"done"}\n'

        return stream()

    monkeypatch.setitem(
        server.v1.dependency_overrides,
        server.get_openai_client_for_class,
        lambda: SimpleNamespace(),
    )
    monkeypatch.setattr(server, "run_response", fake_run_response)
    response = api.post(
        "/api/v1/class/1/thread/20" + ("" if path == "message" else "/run"),
        json={"message": "Hello"} if path == "message" else {},
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )
    assert response.status_code == 200, response.text
    expected_type = release_type
    assert seen["release_type"] == expected_type
    assert seen["release_status"] == (
        schemas.RunReleaseStatus.RELEASED
        if expected_type == schemas.ThreadReleaseType.IMMEDIATE
        else schemas.RunReleaseStatus.PENDING
    )
    assert (seen["released_at"] is not None) == (
        expected_type == schemas.ThreadReleaseType.IMMEDIATE
    )
    if path == "pending_run":
        assert seen["id"] == 30
        if expected_type == schemas.ThreadReleaseType.IMMEDIATE:
            assert (
                seen["released_at"].replace(tzinfo=timezone.utc)
                == previous_release_time
            )
    async with db.async_session() as session:
        saved = await session.get(models.Run, seen["id"])
        assert saved.release_type == seen["release_type"]
        assert saved.release_status == seen["release_status"]
