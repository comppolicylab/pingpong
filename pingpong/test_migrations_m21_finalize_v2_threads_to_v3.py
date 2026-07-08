import pytest
from sqlalchemy import select

from pingpong import models, schemas
from pingpong.migrations import m21_finalize_v2_threads_to_v3 as migration

pytestmark = pytest.mark.asyncio

MIGRATION_KEY = "assistants_to_responses_api_thread_migration"
DEFAULT_MESSAGE_ID = object()


def _metadata(
    *,
    message_complete: bool = True,
    message_parts_complete: bool = True,
    attachments_complete: bool = True,
) -> dict:
    state = {}
    if message_complete:
        state["message"] = "complete"
    if message_parts_complete:
        state["message_parts"] = "complete"
    if attachments_complete:
        state["attachments"] = "complete"
    return {MIGRATION_KEY: state}


async def _seed_thread(
    session,
    *,
    id_: int,
    version: int = 2,
    interaction_mode: schemas.InteractionMode = schemas.InteractionMode.CHAT,
):
    class_id = id_
    assistant_id = id_
    session.add(models.Class(id=class_id, name=f"Class {class_id}"))
    session.add(
        models.Assistant(
            id=assistant_id,
            name=f"Assistant {assistant_id}",
            class_id=class_id,
            assistant_id=f"asst-{assistant_id}",
        )
    )
    await session.flush()

    thread = models.Thread(
        id=id_,
        thread_id=f"thread-{id_}",
        class_id=class_id,
        assistant_id=assistant_id,
        version=version,
        interaction_mode=interaction_mode,
    )
    run = models.Run(
        id=id_,
        run_id=f"run-{id_}",
        status=schemas.RunStatus.COMPLETED,
        thread_id=id_,
        assistant_id=assistant_id,
    )
    session.add_all([thread, run])
    await session.flush()
    return thread, run


async def _seed_message(
    session,
    *,
    id_: int,
    thread_id: int,
    run_id: int,
    role: schemas.MessageRole,
    metadata: dict | None,
    message_id: str | None | object = DEFAULT_MESSAGE_ID,
    output_index: int = 0,
):
    resolved_message_id = (
        f"msg-{id_}" if message_id is DEFAULT_MESSAGE_ID else message_id
    )
    message = models.Message(
        id=id_,
        message_id=resolved_message_id,
        message_status=schemas.MessageStatus.COMPLETED,
        run_id=run_id,
        thread_id=thread_id,
        output_index=output_index,
        role=role,
        message_metadata=metadata,
    )
    session.add(message)
    await session.flush()
    return message


async def _versions_by_id(session) -> dict[int, int]:
    rows = await session.execute(select(models.Thread.id, models.Thread.version))
    return dict(rows.all())


async def test_finalize_v2_threads_to_v3_only_flips_complete_chat_threads(db):
    async with db.async_session() as session:
        await _seed_thread(session, id_=1)
        await _seed_message(
            session,
            id_=101,
            thread_id=1,
            run_id=1,
            role=schemas.MessageRole.USER,
            metadata=_metadata(),
        )

        await _seed_thread(session, id_=2)
        await _seed_message(
            session,
            id_=201,
            thread_id=2,
            run_id=2,
            role=schemas.MessageRole.USER,
            metadata=_metadata(message_parts_complete=False),
        )

        await _seed_thread(session, id_=3)
        await _seed_message(
            session,
            id_=301,
            thread_id=3,
            run_id=3,
            role=schemas.MessageRole.USER,
            metadata=_metadata(attachments_complete=False),
        )

        await _seed_thread(session, id_=4)
        await _seed_message(
            session,
            id_=401,
            thread_id=4,
            run_id=4,
            role=schemas.MessageRole.ASSISTANT,
            metadata=_metadata(attachments_complete=False),
        )

        await _seed_thread(session, id_=5)
        await _seed_message(
            session,
            id_=501,
            thread_id=5,
            run_id=5,
            role=schemas.MessageRole.USER,
            metadata=_metadata(),
            message_id=None,
        )

        await _seed_thread(
            session,
            id_=6,
            interaction_mode=schemas.InteractionMode.VOICE,
        )
        await _seed_message(
            session,
            id_=601,
            thread_id=6,
            run_id=6,
            role=schemas.MessageRole.USER,
            metadata=_metadata(),
        )

        await _seed_thread(session, id_=7, version=3)
        await _seed_message(
            session,
            id_=701,
            thread_id=7,
            run_id=7,
            role=schemas.MessageRole.USER,
            metadata=_metadata(),
        )
        await session.commit()

        assert await migration._count_completely_migrated_v2_threads(session) == 2
        assert await migration._count_blocked_v2_threads(session) == 2

        await migration.finalize_v2_threads_to_v3(session)

        assert await _versions_by_id(session) == {
            1: 3,
            2: 2,
            3: 2,
            4: 3,
            5: 2,
            6: 2,
            7: 3,
        }


async def test_finalize_v2_threads_to_v3_requires_a_migrated_message(db):
    async with db.async_session() as session:
        await _seed_thread(session, id_=1)
        await session.commit()

        await migration.finalize_v2_threads_to_v3(session)

        thread = await session.get(models.Thread, 1)
        assert thread.version == 2


async def test_revert_finalized_v3_threads_to_v2_only_reverts_migrated_threads(db):
    async with db.async_session() as session:
        await _seed_thread(session, id_=1, version=3)
        await _seed_message(
            session,
            id_=101,
            thread_id=1,
            run_id=1,
            role=schemas.MessageRole.USER,
            metadata=_metadata(),
        )

        await _seed_thread(session, id_=2, version=3)
        await _seed_message(
            session,
            id_=201,
            thread_id=2,
            run_id=2,
            role=schemas.MessageRole.USER,
            metadata=_metadata(),
        )
        await _seed_message(
            session,
            id_=202,
            thread_id=2,
            run_id=2,
            role=schemas.MessageRole.ASSISTANT,
            metadata=None,
            output_index=1,
        )

        await _seed_thread(session, id_=3, version=3)
        await _seed_message(
            session,
            id_=301,
            thread_id=3,
            run_id=3,
            role=schemas.MessageRole.USER,
            metadata=None,
        )

        await _seed_thread(
            session,
            id_=4,
            version=3,
            interaction_mode=schemas.InteractionMode.VOICE,
        )
        await _seed_message(
            session,
            id_=401,
            thread_id=4,
            run_id=4,
            role=schemas.MessageRole.USER,
            metadata=_metadata(),
        )

        await _seed_thread(session, id_=5, version=2)
        await _seed_message(
            session,
            id_=501,
            thread_id=5,
            run_id=5,
            role=schemas.MessageRole.USER,
            metadata=_metadata(),
        )
        await session.commit()

        assert await migration._count_revertible_finalized_v3_threads(session) == 1
        assert await migration._count_mixed_finalized_v3_threads(session) == 1

        await migration.revert_finalized_v3_threads_to_v2(session)

        assert await _versions_by_id(session) == {
            1: 2,
            2: 3,
            3: 3,
            4: 3,
            5: 2,
        }
