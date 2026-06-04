from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from pingpong import models, schemas
from pingpong.ai import BufferedResponseStreamHandler

pytestmark = pytest.mark.asyncio


class FakeModeration:
    def __init__(self, payload: dict):
        self.payload = payload

    def model_dump(self, *, mode: str) -> dict:
        assert mode == "json"
        return self.payload


async def test_response_completion_persists_moderation_payload(db):
    moderation_payload = {
        "input": {
            "type": "moderation_results",
            "model": "omni-moderation-latest",
            "results": [
                {
                    "type": "moderation_result",
                    "flagged": False,
                    "categories": {"violence": False},
                    "category_scores": {"violence": 0.01},
                    "category_applied_input_types": {"violence": ["text"]},
                    "model": "omni-moderation-latest",
                }
            ],
        },
        "output": {
            "type": "moderation_results",
            "model": "omni-moderation-latest",
            "results": [],
        },
    }

    async with db.async_session() as session:
        user = models.User(
            id=9101,
            email="moderation@test.dev",
            state=schemas.UserState.VERIFIED,
        )
        class_ = models.Class(id=9102, name="Moderation Class", api_key="sk-test")
        assistant = models.Assistant(
            id=9103,
            name="Moderation Assistant",
            class_id=class_.id,
            assistant_id="asst-moderation",
            model="gpt-4o-mini",
            creator_id=user.id,
        )
        thread = models.Thread(
            id=9104,
            thread_id="thread-moderation",
            class_id=class_.id,
            assistant_id=assistant.id,
            version=3,
            tools_available="",
            private=False,
        )
        run = models.Run(
            id=9105,
            run_id="resp-moderation",
            status=schemas.RunStatus.IN_PROGRESS,
            thread_id=thread.id,
            assistant_id=assistant.id,
            creator_id=user.id,
            created=datetime(2024, 1, 1, tzinfo=timezone.utc),
            updated=datetime(2024, 1, 1, tzinfo=timezone.utc),
        )
        session.add_all([user, class_, assistant, thread, run])
        await session.commit()

    handler = BufferedResponseStreamHandler(
        session=None,
        auth=None,
        cli=None,
        run_id=9105,
        run_status=schemas.RunStatus.IN_PROGRESS,
        prev_output_index=-1,
        file_names={},
        class_id=9102,
        thread_id=9104,
        assistant_id=9103,
        user_id=9101,
    )
    event = SimpleNamespace(
        response=SimpleNamespace(
            status=schemas.RunStatus.COMPLETED,
            error=None,
            incomplete_details=None,
            moderation=FakeModeration(moderation_payload),
        )
    )

    await handler.on_response_completed(event)

    async with db.async_session() as session:
        refreshed = await session.get(models.Run, 9105)
        assert refreshed is not None
        assert refreshed.status == schemas.RunStatus.COMPLETED
        assert refreshed.moderation == moderation_payload


async def test_mark_as_status_preserves_existing_moderation_when_omitted(db):
    moderation_payload = {
        "input": {
            "type": "moderation_results",
            "model": "omni-moderation-latest",
            "results": [],
        }
    }

    async with db.async_session() as session:
        user = models.User(
            id=9111,
            email="moderation-preserve@test.dev",
            state=schemas.UserState.VERIFIED,
        )
        class_ = models.Class(
            id=9112, name="Moderation Preserve Class", api_key="sk-test"
        )
        assistant = models.Assistant(
            id=9113,
            name="Moderation Preserve Assistant",
            class_id=class_.id,
            assistant_id="asst-moderation-preserve",
            model="gpt-4o-mini",
            creator_id=user.id,
        )
        thread = models.Thread(
            id=9114,
            thread_id="thread-moderation-preserve",
            class_id=class_.id,
            assistant_id=assistant.id,
            version=3,
            tools_available="",
            private=False,
        )
        run = models.Run(
            id=9115,
            run_id="resp-moderation-preserve",
            status=schemas.RunStatus.COMPLETED,
            thread_id=thread.id,
            assistant_id=assistant.id,
            creator_id=user.id,
            created=datetime(2024, 1, 1, tzinfo=timezone.utc),
            updated=datetime(2024, 1, 1, tzinfo=timezone.utc),
            moderation=moderation_payload,
        )
        session.add_all([user, class_, assistant, thread, run])
        await session.commit()

    async with db.async_session() as session:
        await models.Run.mark_as_status(
            session,
            9115,
            status=schemas.RunStatus.FAILED,
            error_code="retry_failed",
            error_message="Retry failed",
            incomplete_reason=None,
        )
        await session.commit()

    async with db.async_session() as session:
        refreshed = await session.get(models.Run, 9115)
        assert refreshed is not None
        assert refreshed.status == schemas.RunStatus.FAILED
        assert refreshed.moderation == moderation_payload

    handler = BufferedResponseStreamHandler(
        session=None,
        auth=None,
        cli=None,
        run_id=9115,
        run_status=schemas.RunStatus.IN_PROGRESS,
        prev_output_index=-1,
        file_names={},
        class_id=9112,
        thread_id=9114,
        assistant_id=9113,
        user_id=9111,
    )

    await handler.cleanup(
        run_status=schemas.RunStatus.FAILED,
        response_error_code="cleanup_failed",
        response_error_message="Cleanup failed",
    )

    async with db.async_session() as session:
        refreshed = await session.get(models.Run, 9115)
        assert refreshed is not None
        assert refreshed.moderation == moderation_payload

    async with db.async_session() as session:
        await models.Run.mark_as_status(
            session,
            9115,
            status=schemas.RunStatus.FAILED,
            error_code="retry_failed",
            error_message="Retry failed",
            incomplete_reason=None,
            moderation=None,
        )
        await session.commit()

    async with db.async_session() as session:
        refreshed = await session.get(models.Run, 9115)
        assert refreshed is not None
        assert refreshed.moderation is None
