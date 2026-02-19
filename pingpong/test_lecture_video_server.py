from datetime import datetime

from pingpong import models
import pingpong.schemas as schemas

from .testutil import with_authz, with_user, with_institution


@with_user(123)
@with_institution(11, "Test Institution")
@with_authz(
    grants=[
        ("user:123", "can_create_thread", "class:1"),
    ]
)
async def test_create_lecture_thread_success(
    api, db, institution, valid_user_token
):
    async with db.async_session() as session:
        class_ = models.Class(
            name="Test Class",
            institution_id=institution.id,
        )
        session.add(class_)
        await session.commit()
        await session.refresh(class_)

        lecture_video = models.LectureVideo(
            key="test-video-key",
            name="Test Video",
        )
        session.add(lecture_video)
        await session.flush()

        assistant = models.Assistant(
            id=1,
            name="Lecture Assistant",
            class_id=class_.id,
            interaction_mode=schemas.InteractionMode.LECTURE_VIDEO,
            version=3,
            lecture_video_id=lecture_video.id,
            instructions="You are a lecture assistant.",
        )
        session.add(assistant)
        await session.commit()

    response = api.post(
        f"/api/v1/class/{class_.id}/thread/lecture",
        json={"assistant_id": 1},
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["thread"]["class_id"] == class_.id
    assert data["thread"]["assistant_id"] == 1
    assert data["thread"]["interaction_mode"] == "lecture_video"
    assert data["thread"]["lecture_video_id"] == lecture_video.id
    assert data["thread"]["name"] == "Lecture Presentation"
    assert data["thread"]["private"] is True
    assert data["session_token"] is None


@with_user(123)
@with_institution(11, "Test Institution")
@with_authz(
    grants=[
        ("user:123", "can_edit", "assistant:1"),
        ("user:123", "can_share_assistants", "class:1"),
    ]
)
async def test_share_lecture_video_assistant_blocked(
    api, db, institution, valid_user_token
):
    async with db.async_session() as session:
        class_ = models.Class(
            name="Test Class",
            institution_id=institution.id,
        )
        session.add(class_)
        await session.commit()
        await session.refresh(class_)

        assistant = models.Assistant(
            id=1,
            name="Lecture Assistant",
            class_id=class_.id,
            interaction_mode=schemas.InteractionMode.LECTURE_VIDEO,
            version=3,
            published=datetime.now(),
        )
        session.add(assistant)
        await session.commit()

    response = api.post(
        f"/api/v1/class/{class_.id}/assistant/1/share",
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )
    assert response.status_code == 403
    assert response.json()["detail"] == "Lecture Video assistants cannot be shared."


@with_user(123)
@with_institution(11, "Test Institution")
@with_authz(
    grants=[
        ("user:123", "can_create_thread", "class:1"),
    ]
)
async def test_create_thread_rejects_lecture_video_assistant(
    api, db, institution, valid_user_token
):
    async with db.async_session() as session:
        class_ = models.Class(
            name="Test Class",
            institution_id=institution.id,
            api_key="test-key",
        )
        session.add(class_)
        await session.commit()
        await session.refresh(class_)

        assistant = models.Assistant(
            id=1,
            name="Lecture Assistant",
            class_id=class_.id,
            interaction_mode=schemas.InteractionMode.LECTURE_VIDEO,
            version=3,
        )
        session.add(assistant)
        await session.commit()

    response = api.post(
        f"/api/v1/class/{class_.id}/thread",
        json={"assistant_id": 1, "message": "hello"},
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "This assistant requires a dedicated thread creation endpoint."


@with_user(123)
@with_institution(11, "Test Institution")
@with_authz(
    grants=[
        ("anonymous_link:anon-share-token", "can_create_thread", "class:1"),
    ]
)
async def test_anonymous_cannot_create_lecture_thread(
    api, db, institution
):
    async with db.async_session() as session:
        class_ = models.Class(
            name="Test Class",
            institution_id=institution.id,
        )
        session.add(class_)
        await session.commit()
        await session.refresh(class_)

        link = models.AnonymousLink(
            id=1,
            share_token="anon-share-token",
            active=True,
        )
        session.add(link)
        await session.flush()

        anon_user = models.User(
            id=999,
            email="anon@test.org",
            anonymous_link_id=link.id,
        )
        session.add(anon_user)
        await session.commit()

        assistant = models.Assistant(
            id=1,
            name="Lecture Assistant",
            class_id=class_.id,
            interaction_mode=schemas.InteractionMode.LECTURE_VIDEO,
            version=3,
        )
        session.add(assistant)
        await session.commit()

    response = api.post(
        f"/api/v1/class/{class_.id}/thread/lecture",
        json={"assistant_id": 1},
        headers={"X-Anonymous-Link-Share": "anon-share-token"},
    )
    assert response.status_code == 403
    assert "anonymous session" in response.json()["detail"].lower()


@with_user(123)
@with_institution(11, "Test Institution")
@with_authz(
    grants=[
        ("user:123", "can_create_thread", "class:1"),
    ]
)
async def test_non_v3_assistants_rejected(
    api, db, institution, valid_user_token
):
    async with db.async_session() as session:
        class_ = models.Class(
            name="Test Class",
            institution_id=institution.id,
        )
        session.add(class_)
        await session.commit()
        await session.refresh(class_)

        lecture_video = models.LectureVideo(
            key="test-video-key",
            name="Test Video",
        )
        session.add(lecture_video)
        await session.flush()

        assistant = models.Assistant(
            id=1,
            name="Lecture Assistant",
            class_id=class_.id,
            interaction_mode=schemas.InteractionMode.LECTURE_VIDEO,
            version=2,
            lecture_video_id=lecture_video.id,
        )
        session.add(assistant)
        await session.commit()

    response = api.post(
        f"/api/v1/class/{class_.id}/thread/lecture",
        json={"assistant_id": 1},
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "Lecture presentation can only be created using v3 assistants."

@with_user(123)
@with_institution(11, "Test Institution")
@with_authz(
    grants=[
        ("user:123", "can_create_thread", "class:1"),
    ]
)
async def test_lecture_thread_rejected_without_attached_video(
    api, db, institution, valid_user_token
):
    async with db.async_session() as session:
        class_ = models.Class(
            name="Test Class",
            institution_id=institution.id,
        )
        session.add(class_)
        await session.commit()
        await session.refresh(class_)

        assistant = models.Assistant(
            id=1,
            name="Lecture Assistant",
            class_id=class_.id,
            interaction_mode=schemas.InteractionMode.LECTURE_VIDEO,
            version=3,
            lecture_video_id=None,
        )
        session.add(assistant)
        await session.commit()

    response = api.post(
        f"/api/v1/class/{class_.id}/thread/lecture",
        json={"assistant_id": 1},
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "This assistant does not have a lecture video attached. Unable to create Lecture Presentation"


@with_user(123)
@with_institution(11, "Test Institution")
@with_authz(
    grants=[
        ("user:123", "can_create_thread", "class:1"),
    ]
)
async def test_lecture_endpoint_rejects_non_lecture_video_assistant(
    api, db, institution, valid_user_token
):
    async with db.async_session() as session:
        class_ = models.Class(
            name="Test Class",
            institution_id=institution.id,
        )
        session.add(class_)
        await session.commit()
        await session.refresh(class_)

        assistant = models.Assistant(
            id=1,
            name="Chat Assistant",
            class_id=class_.id,
            interaction_mode=schemas.InteractionMode.VOICE,
            version=3,
        )
        session.add(assistant)
        await session.commit()

    response = api.post(
        f"/api/v1/class/{class_.id}/thread/lecture",
        json={"assistant_id": 1},
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "This assistant is not compatible with this thread creation endpoint. Provide a lecture_video assistant."