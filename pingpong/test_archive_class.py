from datetime import datetime, timezone

from pingpong import models
import pingpong.schemas as schemas
from pingpong.testutil import with_authz, with_institution, with_user


@with_user(123)
@with_institution(1, "Test Institution")
@with_authz(grants=[("user:123", "can_edit_info", "class:1")])
async def test_update_class_archives_with_server_timestamp_and_unarchives(
    api, db, institution, valid_user_token
):
    async with db.async_session() as session:
        session.add(
            models.Class(
                id=1,
                name="Archive Class",
                term="Spring 2026",
                institution_id=institution.id,
                private=False,
            )
        )
        await session.commit()

    archive_response = api.put(
        "/api/v1/class/1",
        json={"archived": "2026-07-08T12:00:00+00:00"},
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )

    assert archive_response.status_code == 200
    assert archive_response.json()["archived"] == "2024-01-01T00:00:00Z"

    async with db.async_session() as session:
        class_ = await models.Class.get_by_id(session, 1)
        archived = class_.archived
        if archived.tzinfo is None:
            archived = archived.replace(tzinfo=timezone.utc)
        else:
            archived = archived.astimezone(timezone.utc)
        assert archived == datetime(
            2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc
        )

    unarchive_response = api.put(
        "/api/v1/class/1",
        json={"archived": None},
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )

    assert unarchive_response.status_code == 200
    assert unarchive_response.json()["archived"] is None

    async with db.async_session() as session:
        class_ = await models.Class.get_by_id(session, 1)
        assert class_.archived is None


@with_user(123)
@with_authz(grants=[("user:123", "can_create_thread", "class:1")])
async def test_archived_class_blocks_thread_creation(api, db, valid_user_token):
    async with db.async_session() as session:
        class_ = models.Class(
            id=1,
            name="Archive Class",
            term="Spring 2026",
            api_key="sk-test",
            private=False,
            archived=datetime(2024, 1, 1, 0, 0, 0, tzinfo=timezone.utc),
        )
        assistant = models.Assistant(
            id=11,
            name="Chat Assistant",
            version=3,
            instructions="You are helpful.",
            interaction_mode=schemas.InteractionMode.CHAT,
            description="Chat assistant",
            tools="[]",
            model="gpt-4o-mini",
            class_id=class_.id,
            creator_id=123,
            use_latex=False,
            use_image_descriptions=False,
            should_record_user_information=False,
        )
        session.add_all([class_, assistant])
        await session.commit()

    response = api.post(
        "/api/v1/class/1/thread",
        json={"assistant_id": 11, "message": "Hello"},
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )

    assert response.status_code == 409
    assert response.json() == {
        "detail": "This group is archived and read-only. New content and edits are unavailable."
    }
