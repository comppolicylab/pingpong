from pingpong import models
import pingpong.schemas as schemas

from .testutil import with_authz, with_institution, with_user


@with_user(123)
@with_institution(1, "Test Institution")
@with_authz(
    grants=[
        ("user:123", "can_edit", "assistant:1"),
        ("user:123", "can_share_assistants", "class:1"),
    ]
)
async def test_unshare_assistant_revokes_share_without_lazy_loading(
    api, db, institution, valid_user_token
):
    async with db.async_session() as session:
        creator = models.User(email="creator@test.org")
        session.add(creator)
        await session.flush()

        class_ = models.Class(
            id=1,
            name="Test Class",
            institution_id=institution.id,
        )
        session.add(class_)
        await session.flush()

        assistant = models.Assistant(
            id=1,
            name="Test Assistant",
            instructions="Test instructions",
            description="Test description",
            interaction_mode=schemas.InteractionMode.CHAT,
            model="gpt-4o-mini",
            temperature=0.2,
            class_id=class_.id,
            tools="[]",
            creator_id=creator.id,
            published=None,
            version=3,
        )
        session.add(assistant)
        await session.flush()

        share_link = await models.AnonymousLink.create(
            session,
            share_token="share-token-123",
            assistant_id=assistant.id,
        )
        await session.commit()

    response = api.delete(
        f"/api/v1/class/{class_.id}/assistant/{assistant.id}/share/{share_link.id}",
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}

    async with db.async_session() as session:
        updated_share_link = await models.AnonymousLink.get_by_id(
            session, share_link.id
        )
        assert updated_share_link.active is False
        assert updated_share_link.revoked_at is not None
