from pingpong.files import _file_grants
import pingpong.schemas as schemas
from pingpong import models

from .testutil import with_authz


@with_authz(grants=[])
async def test_anonymous_share_file_delete_permission_revoked_on_thread_create(
    api, authz, config, db, monkeypatch
):
    async def fake_generate_name(*_args, **_kwargs):
        return schemas.ThreadName(name="Test Thread", can_generate=True)

    monkeypatch.setattr("pingpong.ai.generate_name", fake_generate_name)

    share_token = "share-token-123"
    async with db.async_session() as session:
        creator = models.User(email="creator@test.org")
        session.add(creator)
        await session.flush()

        class_ = models.Class(name="Test Class", api_key="test-key")
        session.add(class_)
        await session.flush()

        assistant = models.Assistant(
            name="Test Assistant",
            instructions="Test instructions",
            model="gpt-4o-mini",
            class_id=class_.id,
            creator_id=creator.id,
            assistant_should_message_first=False,
            version=3,
            interaction_mode=schemas.InteractionMode.CHAT,
        )
        session.add(assistant)
        await session.flush()

        share_link = await models.AnonymousLink.create(
            session,
            share_token=share_token,
            assistant_id=assistant.id,
        )
        anonymous_user = await models.User.create_anonymous_user(
            session, anonymous_link_id=share_link.id
        )

        file = await models.File.create(
            session,
            data={
                "file_id": "file_abc123",
                "private": True,
                "uploader_id": anonymous_user.id,
                "name": "notes.txt",
                "content_type": "text/plain",
                "class_id": class_.id,
                "anonymous_link_id": share_link.id,
            },
            class_id=class_.id,
        )
        await session.commit()

    async with config.authz.driver.get_client() as authz_client:
        await authz_client.write_safe(
            grant=_file_grants(
                file, class_.id, None, f"anonymous_link:{share_token}", None
            )
        )

        await authz_client.write_safe(
            grant=[
                (
                    f"anonymous_link:{share_token}",
                    "can_create_thread",
                    f"class:{class_.id}",
                )
            ]
        )

    response = api.post(
        f"/api/v1/class/{class_.id}/thread",
        json={
            "message": "hello",
            "assistant_id": assistant.id,
            "code_interpreter_file_ids": [file.file_id],
        },
        headers={"X-Anonymous-Link-Share": share_token},
    )
    assert response.status_code == 200

    calls = await authz.get_all_calls()
    assert (
        "revoke",
        f"anonymous_link:{share_token}",
        "can_delete",
        f"user_file:{file.id}",
    ) in calls
