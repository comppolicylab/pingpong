from types import SimpleNamespace

import pytest
from glowplug import DbDriver

from pingpong import models
from pingpong.migrations import m20_migrate_voice_mode_threads_to_v3 as migration

pytestmark = pytest.mark.asyncio


def _user_message(user_id: int) -> SimpleNamespace:
    return SimpleNamespace(
        id=f"msg_user_{user_id}",
        role="user",
        metadata={"user_id": str(user_id)},
    )


async def test_resolve_user_id_uses_current_or_merged_user(db: DbDriver) -> None:
    async with db.async_session() as session:
        current_user = models.User(id=16480, email="current@example.com")
        session.add(current_user)
        await session.flush()
        await session.execute(
            models.user_merge_association.insert().values(
                user_id=current_user.id,
                merged_user_id=7041,
            )
        )

        assert (
            await migration._resolve_user_id(session, _user_message(current_user.id))
            == current_user.id
        )
        assert (
            await migration._resolve_user_id(session, _user_message(7041))
            == current_user.id
        )
        assert await migration._resolve_user_id(session, _user_message(99999)) is None
