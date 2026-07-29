from types import SimpleNamespace

import pytest
from sqlalchemy import inspect

import pingpong.schemas as schemas
from pingpong import assistant_service, models

from .testutil import with_authz, with_institution, with_user


class FakeAvatarStore:
    def __init__(self):
        self.stored_files: dict[str, bytes] = {}
        self.deleted_keys: list[str] = []

    async def put(self, key: str, file, content_type: str):
        self.stored_files[key] = file.read()

    async def get(self, name: str, chunk_size: int = 1024 * 1024):
        yield self.stored_files[name]

    async def delete(self, key: str):
        self.deleted_keys.append(key)
        self.stored_files.pop(key, None)


async def _create_assistant(db, institution) -> None:
    async with db.async_session() as session:
        class_ = models.Class(
            id=1,
            name="Avatar Test Class",
            institution_id=institution.id,
        )
        session.add(class_)
        session.add(
            models.Assistant(
                id=1,
                name="Avatar Test Assistant",
                instructions="Test instructions",
                description="Test description",
                interaction_mode=schemas.InteractionMode.CHAT,
                model="gpt-4o-mini",
                temperature=0.2,
                class_id=class_.id,
                tools="[]",
                creator_id=123,
                published=None,
                version=3,
            )
        )
        session.add(
            models.Thread(
                id=20,
                thread_id="avatar-test-thread",
                version=3,
                class_id=class_.id,
                assistant_id=1,
                private=False,
            )
        )
        await session.commit()


@with_user(123)
@with_institution(1, "Test Institution")
@with_authz(
    grants=[
        ("user:123", "can_edit", "assistant:1"),
        ("user:123", "can_view", "assistant:1"),
        ("user:123", "can_view", "thread:20"),
    ]
)
async def test_assistant_avatar_upload_replace_download_and_delete(
    api, db, institution, valid_user_token, config, monkeypatch
):
    await _create_assistant(db, institution)
    store = FakeAvatarStore()
    monkeypatch.setattr(config, "file_store", SimpleNamespace(store=store))
    original_response_builder = assistant_service.assistant_response_from_model

    async def assert_relationships_loaded(session, assistant):
        unloaded = inspect(assistant).unloaded
        assert "lecture_video" not in unloaded
        assert "lecture_slide_deck" not in unloaded
        return await original_response_builder(session, assistant)

    monkeypatch.setattr(
        assistant_service,
        "assistant_response_from_model",
        assert_relationships_loaded,
    )
    headers = {"Authorization": f"Bearer {valid_user_token}"}
    avatar_url = "/api/v1/class/1/assistant/1/avatar"

    response = api.post(
        avatar_url,
        headers=headers,
        files={
            "upload": (
                "first.png",
                b"\x89PNG\r\n\x1a\nfirst-image",
                "image/png",
            )
        },
    )
    assert response.status_code == 200
    assert response.json()["avatar_url"].startswith(f"{avatar_url}?v=")
    first_key = next(iter(store.stored_files))

    response = api.get(avatar_url, headers=headers)
    assert response.status_code == 200
    assert response.content == b"\x89PNG\r\n\x1a\nfirst-image"
    assert response.headers["content-type"] == "image/png"

    response = api.get("/api/v1/class/1/thread/20/assistant-avatar", headers=headers)
    assert response.status_code == 200
    assert response.content == b"\x89PNG\r\n\x1a\nfirst-image"

    response = api.post(
        avatar_url,
        headers=headers,
        files={
            "upload": (
                "second.webp",
                b"RIFF\x0c\x00\x00\x00WEBPsecond-image",
                "image/webp",
            )
        },
    )
    assert response.status_code == 200
    assert first_key in store.deleted_keys
    assert list(store.stored_files.values()) == [
        b"RIFF\x0c\x00\x00\x00WEBPsecond-image"
    ]

    response = api.delete(avatar_url, headers=headers)
    assert response.status_code == 200
    assert response.json()["avatar_url"] is None
    assert store.stored_files == {}

    response = api.get(avatar_url, headers=headers)
    assert response.status_code == 404

    async with db.async_session() as session:
        assistant = await models.Assistant.get_by_id(session, 1)
        assert assistant.avatar_file_id is None


@with_user(123)
@with_institution(1, "Test Institution")
@with_authz(grants=[("user:123", "can_edit", "assistant:1")])
@pytest.mark.parametrize(
    ("filename", "content_type"),
    [
        ("avatar.svg", "image/svg+xml"),
        ("avatar.txt", "text/plain"),
    ],
)
async def test_assistant_avatar_rejects_unsupported_file_types(
    api,
    db,
    institution,
    valid_user_token,
    config,
    monkeypatch,
    filename,
    content_type,
):
    await _create_assistant(db, institution)
    store = FakeAvatarStore()
    monkeypatch.setattr(config, "file_store", SimpleNamespace(store=store))

    response = api.post(
        "/api/v1/class/1/assistant/1/avatar",
        headers={"Authorization": f"Bearer {valid_user_token}"},
        files={"upload": (filename, b"not-an-avatar", content_type)},
    )

    assert response.status_code == 415
    assert store.stored_files == {}


@with_user(123)
@with_institution(1, "Test Institution")
@with_authz(grants=[("user:123", "can_edit", "assistant:1")])
async def test_assistant_avatar_rejects_mismatched_image_contents(
    api, db, institution, valid_user_token, config, monkeypatch
):
    await _create_assistant(db, institution)
    store = FakeAvatarStore()
    monkeypatch.setattr(config, "file_store", SimpleNamespace(store=store))

    response = api.post(
        "/api/v1/class/1/assistant/1/avatar",
        headers={"Authorization": f"Bearer {valid_user_token}"},
        files={"upload": ("avatar.png", b"<script>", "image/png")},
    )

    assert response.status_code == 415
    assert store.stored_files == {}
