from pingpong import models
from pingpong.config import LocalVideoStoreSettings
import pingpong.schemas as schemas

from .testutil import with_authz, with_user, with_institution


@with_user(123)
@with_institution(11, "Test Institution")
@with_authz(
    grants=[
        ("user:123", "can_create_thread", "class:1"),
    ]
)
async def test_create_lecture_thread_success(api, db, institution, valid_user_token):
    async with db.async_session() as session:
        class_ = models.Class(
            id=1,
            name="Test Class",
            institution_id=institution.id,
            api_key="test-key",
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
async def test_share_lecture_video_assistant_allowed(
    api, db, institution, valid_user_token, now
):
    async with db.async_session() as session:
        class_ = models.Class(
            id=1,
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
            published=now(),
        )
        session.add(assistant)
        await session.commit()

    response = api.post(
        f"/api/v1/class/{class_.id}/assistant/1/share",
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


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
            id=1,
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
    assert (
        response.json()["detail"]
        == "This assistant requires a dedicated thread creation endpoint."
    )


@with_user(123)
@with_institution(11, "Test Institution")
@with_authz(
    grants=[
        ("anonymous_link:anon-share-token", "can_create_thread", "class:1"),
    ]
)
async def test_anonymous_can_create_lecture_thread(api, db, institution):
    async with db.async_session() as session:
        class_ = models.Class(
            id=1,
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

        lecture_video = models.LectureVideo(
            key="anon-test-video-key",
            name="Anonymous Test Video",
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
        headers={"X-Anonymous-Link-Share": "anon-share-token"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["thread"]["class_id"] == class_.id
    assert data["thread"]["assistant_id"] == 1
    assert data["thread"]["interaction_mode"] == "lecture_video"
    assert data["thread"]["lecture_video_id"] == lecture_video.id
    assert data["thread"]["private"] is True
    assert data["session_token"] is not None


@with_user(123)
@with_institution(11, "Test Institution")
@with_authz(
    grants=[
        ("user:123", "can_create_thread", "class:1"),
    ]
)
async def test_non_v3_assistants_rejected(api, db, institution, valid_user_token):
    async with db.async_session() as session:
        class_ = models.Class(
            id=1,
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
    assert (
        response.json()["detail"]
        == "Lecture presentation can only be created using v3 assistants."
    )


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
            id=1,
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
    assert (
        response.json()["detail"]
        == "This assistant does not have a lecture video attached. Unable to create Lecture Presentation"
    )


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
            id=1,
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
    assert (
        response.json()["detail"]
        == "This assistant is not compatible with this thread creation endpoint. Provide a lecture_video assistant."
    )


@with_user(123)
@with_institution(11, "Test Institution")
@with_authz(
    grants=[
        ("user:123", "can_view", "thread:109"),
    ]
)
async def test_get_thread_video_stream_and_range(
    api, db, institution, valid_user_token, config, monkeypatch, tmp_path
):
    video_key = "lecture-video.mp4"
    video_bytes = b"0123456789abcdef"
    (tmp_path / video_key).write_bytes(video_bytes)
    monkeypatch.setattr(
        config,
        "video_store",
        LocalVideoStoreSettings(type="local", save_target=str(tmp_path)),
    )

    async with db.async_session() as session:
        class_ = models.Class(
            id=1,
            name="Test Class",
            institution_id=institution.id,
        )
        session.add(class_)
        await session.flush()

        lecture_video = models.LectureVideo(
            key=video_key,
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
        )
        session.add(assistant)
        await session.flush()

        thread = models.Thread(
            id=109,
            name="Lecture Presentation",
            version=3,
            thread_id="thread-video-109",
            class_id=class_.id,
            assistant_id=assistant.id,
            interaction_mode=schemas.InteractionMode.LECTURE_VIDEO,
            lecture_video_id=lecture_video.id,
            private=True,
            tools_available="[]",
        )
        session.add(thread)
        await session.commit()

    response = api.get(
        "/api/v1/class/1/thread/109/video",
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )
    assert response.status_code == 200
    assert response.headers["accept-ranges"] == "bytes"
    assert response.headers["content-length"] == str(len(video_bytes))
    assert response.headers["content-type"].startswith("video/mp4")
    assert response.content == video_bytes

    partial = api.get(
        "/api/v1/class/1/thread/109/video",
        headers={"Authorization": f"Bearer {valid_user_token}", "Range": "bytes=2-5"},
    )
    assert partial.status_code == 206
    assert partial.headers["accept-ranges"] == "bytes"
    assert partial.headers["content-range"] == f"bytes 2-5/{len(video_bytes)}"
    assert partial.headers["content-length"] == "4"
    assert partial.content == video_bytes[2:6]


@with_user(123)
@with_institution(11, "Test Institution")
@with_authz(
    grants=[
        ("user:123", "can_view", "thread:109"),
    ]
)
async def test_get_thread_video_invalid_range_returns_416(
    api, db, institution, valid_user_token, config, monkeypatch, tmp_path
):
    video_key = "lecture-video.mp4"
    video_bytes = b"0123456789"
    (tmp_path / video_key).write_bytes(video_bytes)
    monkeypatch.setattr(
        config,
        "video_store",
        LocalVideoStoreSettings(type="local", save_target=str(tmp_path)),
    )

    async with db.async_session() as session:
        class_ = models.Class(
            id=1,
            name="Test Class",
            institution_id=institution.id,
        )
        session.add(class_)
        await session.flush()

        lecture_video = models.LectureVideo(
            key=video_key,
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
        )
        session.add(assistant)
        await session.flush()

        thread = models.Thread(
            id=109,
            name="Lecture Presentation",
            version=3,
            thread_id="thread-video-109",
            class_id=class_.id,
            assistant_id=assistant.id,
            interaction_mode=schemas.InteractionMode.LECTURE_VIDEO,
            lecture_video_id=lecture_video.id,
            private=True,
            tools_available="[]",
        )
        session.add(thread)
        await session.commit()

    response = api.get(
        "/api/v1/class/1/thread/109/video",
        headers={
            "Authorization": f"Bearer {valid_user_token}",
            "Range": "bytes=100-200",
        },
    )
    assert response.status_code == 416
    assert response.headers["accept-ranges"] == "bytes"
    assert response.headers["content-range"] == f"bytes */{len(video_bytes)}"


@with_institution(11, "Test Institution")
@with_authz(
    grants=[
        ("anonymous_user:anon-session-token", "can_view", "thread:109"),
    ]
)
async def test_get_thread_video_with_anonymous_query_token(
    api, db, institution, config, monkeypatch, tmp_path
):
    video_key = "lecture-video.mp4"
    video_bytes = b"anonymous-video-bytes"
    (tmp_path / video_key).write_bytes(video_bytes)
    monkeypatch.setattr(
        config,
        "video_store",
        LocalVideoStoreSettings(type="local", save_target=str(tmp_path)),
    )

    async with db.async_session() as session:
        class_ = models.Class(
            id=1,
            name="Test Class",
            institution_id=institution.id,
        )
        session.add(class_)
        await session.flush()

        lecture_video = models.LectureVideo(
            key=video_key,
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
        )
        session.add(assistant)
        await session.flush()

        thread = models.Thread(
            id=109,
            name="Lecture Presentation",
            version=3,
            thread_id="thread-video-109",
            class_id=class_.id,
            assistant_id=assistant.id,
            interaction_mode=schemas.InteractionMode.LECTURE_VIDEO,
            lecture_video_id=lecture_video.id,
            private=True,
            tools_available="[]",
        )
        session.add(thread)
        await session.flush()

        anon_link = models.AnonymousLink(
            id=1,
            share_token="anon-share-token",
            active=True,
        )
        session.add(anon_link)
        await session.flush()

        anon_user = models.User(
            id=999,
            email="anon-user@test.org",
            anonymous_link_id=anon_link.id,
        )
        session.add(anon_user)
        await session.flush()

        anon_session = models.AnonymousSession(
            session_token="anon-session-token",
            thread_id=thread.id,
            user_id=anon_user.id,
        )
        session.add(anon_session)
        await session.commit()

    response = api.get(
        "/api/v1/class/1/thread/109/video?anonymous_session_token=anon-session-token",
    )
    assert response.status_code == 200
    assert response.content == video_bytes


@with_user(123)
@with_institution(11, "Test Institution")
@with_authz(
    grants=[
        ("user:123", "can_view", "thread:109"),
    ]
)
async def test_get_thread_video_with_lti_session_query_token(
    api, db, institution, valid_user_token, config, monkeypatch, tmp_path
):
    video_key = "lecture-video.mp4"
    video_bytes = b"lti-video-bytes"
    (tmp_path / video_key).write_bytes(video_bytes)
    monkeypatch.setattr(
        config,
        "video_store",
        LocalVideoStoreSettings(type="local", save_target=str(tmp_path)),
    )

    async with db.async_session() as session:
        class_ = models.Class(
            id=1,
            name="Test Class",
            institution_id=institution.id,
        )
        session.add(class_)
        await session.flush()

        lecture_video = models.LectureVideo(
            key=video_key,
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
        )
        session.add(assistant)
        await session.flush()

        thread = models.Thread(
            id=109,
            name="Lecture Presentation",
            version=3,
            thread_id="thread-video-109",
            class_id=class_.id,
            assistant_id=assistant.id,
            interaction_mode=schemas.InteractionMode.LECTURE_VIDEO,
            lecture_video_id=lecture_video.id,
            private=True,
            tools_available="[]",
        )
        session.add(thread)
        await session.commit()

    response = api.get(
        f"/api/v1/class/1/thread/109/video?lti_session={valid_user_token}",
    )
    assert response.status_code == 200
    assert response.content == video_bytes


@with_user(123)
@with_institution(11, "Test Institution")
@with_authz(
    grants=[
        ("user:123", "can_view", "thread:109"),
    ]
)
async def test_get_thread_video_rejects_assistant_mismatch(
    api, db, institution, valid_user_token, config, monkeypatch, tmp_path
):
    (tmp_path / "thread-video.mp4").write_bytes(b"thread-video")
    (tmp_path / "assistant-video.mp4").write_bytes(b"assistant-video")
    monkeypatch.setattr(
        config,
        "video_store",
        LocalVideoStoreSettings(type="local", save_target=str(tmp_path)),
    )

    async with db.async_session() as session:
        class_ = models.Class(
            id=1,
            name="Test Class",
            institution_id=institution.id,
            api_key="test-key",
        )
        session.add(class_)
        await session.flush()

        thread_video = models.LectureVideo(
            key="thread-video.mp4",
            name="Thread Video",
        )
        assistant_video = models.LectureVideo(
            key="assistant-video.mp4",
            name="Assistant Video",
        )
        session.add(thread_video)
        session.add(assistant_video)
        await session.flush()

        assistant = models.Assistant(
            id=1,
            name="Lecture Assistant",
            class_id=class_.id,
            interaction_mode=schemas.InteractionMode.LECTURE_VIDEO,
            version=3,
            model="gpt-4o",
            lecture_video_id=assistant_video.id,
        )
        session.add(assistant)
        await session.flush()

        thread = models.Thread(
            id=109,
            name="Lecture Presentation",
            version=3,
            thread_id="thread-video-109",
            class_id=class_.id,
            assistant_id=assistant.id,
            interaction_mode=schemas.InteractionMode.LECTURE_VIDEO,
            lecture_video_id=thread_video.id,
            private=True,
            tools_available="[]",
        )
        session.add(thread)
        await session.commit()

    video_response = api.get(
        "/api/v1/class/1/thread/109/video",
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )
    assert video_response.status_code == 404
    assert (
        video_response.json()["detail"]
        == "This thread's lecture video no longer matches the assistant configuration."
    )

    thread_response = api.get(
        "/api/v1/class/1/thread/109",
        headers={"Authorization": f"Bearer {valid_user_token}"},
    )
    assert thread_response.status_code == 200
    assert thread_response.json()["lecture_video_matches_assistant"] is False
