import importlib
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from sqlalchemy import func, insert, select

from pingpong import models, schemas
from pingpong.resource_binding import get_attachment_files_for_class
from pingpong.testutil import with_authz, with_user

server = importlib.import_module("pingpong.server")

GRANTS = [
    (subject, relation, target)
    for subject in ("user:123", "anonymous_user:session", "anonymous_link:share")
    for relation, target in (
        ("can_view", "thread:20"),
        ("can_participate", "thread:20"),
        ("can_publish", "thread:20"),
        ("can_delete", "thread:20"),
        ("admin", "class:2"),
        ("supervisor", "class:2"),
        ("can_create_thread", "class:1"),
        ("can_create_assistants", "class:1"),
        ("can_interact_with", "assistant:10"),
        ("can_edit", "assistant:10"),
        ("can_view", "assistant:10"),
        ("can_publish", "assistant:10"),
        ("can_delete", "assistant:10"),
        ("can_share_assistants", "class:1"),
        ("can_share_assistants", "class:2"),
        ("can_delete", "class_file:30"),
        ("can_delete", "user_file:30"),
    )
]


async def seed_thread(db, *, version=3, assistant_class_id=1):
    async with db.async_session() as session:
        session.add_all(
            models.Class(id=id_, name=f"Class {id_}", api_key=f"key-{id_}")
            for id_ in (1, 2)
        )
        session.add(
            models.Assistant(
                id=10,
                name="Assistant",
                class_id=assistant_class_id,
                version=version,
                model="gpt-4o-mini",
                instructions="Be helpful.",
                allow_user_file_uploads=True,
                allow_user_image_uploads=True,
                tools="[]",
            )
        )
        await session.flush()
        link = await models.AnonymousLink.create(session, "share", assistant_id=10)
        anonymous = await models.User.create_anonymous_user(
            session, anonymous_link_id=link.id
        )
        await models.AnonymousSession.create(session, "session", user_id=anonymous.id)
        session.add(
            models.Thread(
                id=20,
                class_id=1,
                assistant_id=10,
                version=version,
                thread_id="remote-thread",
                name="Conversation",
                private=True,
                tools_available="[]",
                instructions="Be helpful.",
                user_message_ct=0,
            )
        )
        await session.commit()


def headers_for(principal, token):
    headers = {}
    if principal != "anonymous":
        headers["Authorization"] = f"Bearer {token}"
    if principal != "user":
        headers["X-Anonymous-Thread-Session"] = "session"
    return headers


@with_user(123)
@with_authz(grants=GRANTS)
@pytest.mark.parametrize("principal", ["user", "anonymous", "hybrid"])
@pytest.mark.parametrize("version", [2, 3])
@pytest.mark.parametrize(
    "method,suffix",
    [
        ("get", ""),
        ("get", "/messages"),
        ("get", "/last_run"),
        ("get", "/details"),
        ("get", "/recording"),
        ("get", "/recording/transcribe/download"),
        ("post", ""),
        ("post", "/run"),
        ("post", "/publish"),
        ("post", "/recording/transcribe"),
        ("delete", ""),
        ("delete", "/publish"),
    ],
)
async def test_thread_routes_reject_other_class_before_effects(
    api, db, authz, valid_user_token, monkeypatch, principal, version, method, suffix
):
    await seed_thread(db, version=version)
    provider = AsyncMock()
    monkeypatch.setattr(server, "get_openai_client_by_class_id", provider)
    transcribe = AsyncMock()
    monkeypatch.setattr(
        server, "transcribe_thread_recording_and_email_link", transcribe
    )
    before = await authz.get_all_calls()
    kwargs = {"headers": headers_for(principal, valid_user_token)}
    if method == "post":
        kwargs["json"] = {"message": "Hello"}
    response = getattr(api, method)(f"/api/v1/class/2/thread/20{suffix}", **kwargs)
    assert response.status_code == 404, response.text
    provider.assert_not_awaited()
    transcribe.assert_not_awaited()
    assert await authz.get_all_calls() == before
    async with db.async_session() as session:
        thread = await models.Thread.get_by_id(session, 20)
        assert thread.private is True
        assert thread.user_message_ct == 0
        assert await session.scalar(select(func.count()).select_from(models.Run)) == 0


@with_user(123)
@with_authz(grants=GRANTS)
@pytest.mark.parametrize("suffix", ["", "/run"])
@pytest.mark.parametrize("mismatch", ["thread", "assistant"])
async def test_interaction_rejects_both_parent_mismatches_with_provider_override(
    api, db, valid_user_token, monkeypatch, suffix, mismatch
):
    await seed_thread(db, assistant_class_id=2 if mismatch == "assistant" else 1)
    provider = SimpleNamespace(
        beta=SimpleNamespace(
            threads=SimpleNamespace(runs=SimpleNamespace(list=AsyncMock()))
        )
    )
    monkeypatch.setitem(
        server.v1.dependency_overrides,
        server.get_openai_client_for_class,
        lambda: provider,
    )
    response = api.post(
        f"/api/v1/class/{2 if mismatch == 'thread' else 1}/thread/20{suffix}",
        json={"message": "Hello"},
        headers=headers_for("user", valid_user_token),
    )
    assert response.status_code == 404, response.text
    provider.beta.threads.runs.list.assert_not_awaited()


@with_user(123)
@with_authz(grants=GRANTS)
@pytest.mark.parametrize("mode", ["lecture-video", "lecture-slide"])
@pytest.mark.parametrize(
    "operation", ["control/acquire", "control/renew", "interactions"]
)
@pytest.mark.parametrize("mismatch", ["thread", "assistant"])
async def test_lesson_mutations_bind_thread_and_assistant_to_class(
    api, db, valid_user_token, monkeypatch, mode, operation, mismatch
):
    await seed_thread(db, assistant_class_id=2 if mismatch == "assistant" else 1)
    interaction_mode = (
        schemas.InteractionMode.LECTURE_VIDEO
        if mode == "lecture-video"
        else schemas.InteractionMode.LECTURE_SLIDES
    )
    async with db.async_session() as session:
        thread = await models.Thread.get_by_id(session, 20)
        assistant = await models.Assistant.get_by_id(session, 10)
        thread.interaction_mode = assistant.interaction_mode = interaction_mode
        await session.commit()
    runtime = (
        server.lecture_video_runtime
        if mode == "lecture-video"
        else server.lecture_slide_runtime
    )
    acquire = AsyncMock()
    monkeypatch.setattr(runtime, "acquire_control", acquire)
    body = {"controller_session_id": "controller"}
    if operation == "interactions":
        body.update(
            type="video_paused" if mode == "lecture-video" else "lesson_paused",
            expected_state_version=1,
            idempotency_key="paused",
            offset_ms=0,
        )
    response = api.post(
        f"/api/v1/class/{2 if mismatch == 'thread' else 1}/thread/20/{mode}/{operation}",
        json=body,
        headers=headers_for("user", valid_user_token),
    )
    assert response.status_code == 404, response.text
    acquire.assert_not_awaited()
    async with db.async_session() as session:
        for state in (models.LectureVideoThreadState, models.LectureSlideThreadState):
            assert await session.scalar(select(func.count()).select_from(state)) == 0


@with_user(123)
@with_authz(grants=GRANTS)
@pytest.mark.parametrize("method", ["put", "delete"])
@pytest.mark.parametrize("mismatch", ["class", "assistant"])
async def test_assistant_share_requires_both_parents(
    api, db, authz, valid_user_token, method, mismatch
):
    await seed_thread(db)
    async with db.async_session() as session:
        session.add(models.Assistant(id=11, class_id=1, name="Other assistant"))
        await session.flush()
        share = await models.AnonymousLink.create(
            session, "another-share", assistant_id=11 if mismatch == "assistant" else 10
        )
        share.name = "Original"
        await session.commit()
        share_id = share.id
    before = await authz.get_all_calls()
    kwargs = {"headers": headers_for("user", valid_user_token)}
    if method == "put":
        kwargs["json"] = {"name": "Changed"}
    response = getattr(api, method)(
        f"/api/v1/class/{2 if mismatch == 'class' else 1}/assistant/10/share/{share_id}",
        **kwargs,
    )
    assert response.status_code == (
        400 if method == "delete" and mismatch == "assistant" else 404
    ), response.text
    assert await authz.get_all_calls() == before
    async with db.async_session() as session:
        share = await models.AnonymousLink.get_by_id(session, share_id)
        assert share.name == "Original"
        assert share.active


@with_user(123)
@with_authz(grants=GRANTS)
@pytest.mark.parametrize("operation", ["read", "delete"])
async def test_historical_thread_without_assistant_remains_accessible(
    api, db, valid_user_token, monkeypatch, operation
):
    await seed_thread(db)
    async with db.async_session() as session:
        thread = await models.Thread.get_by_id(session, 20)
        thread.assistant_id = None
        await session.commit()
    provider = SimpleNamespace()
    monkeypatch.setattr(
        server, "get_openai_client_by_class_id", AsyncMock(return_value=provider)
    )
    path = "/api/v1/class/1/thread/20"
    response = (
        api.get(path + "/last_run", headers=headers_for("user", valid_user_token))
        if operation == "read"
        else api.delete(path, headers=headers_for("user", valid_user_token))
    )
    assert response.status_code == 200, response.text


@with_user(123)
@with_authz(grants=GRANTS)
@pytest.mark.parametrize(
    "method,suffix",
    [
        ("get", "/files"),
        ("get", "/mcp_servers"),
        ("get", "/avatar"),
        ("post", "/publish"),
        ("post", "/lock"),
        ("post", "/share"),
        ("post", "/copy"),
        ("post", "/copy/check"),
        ("put", ""),
        ("delete", ""),
        ("delete", "/publish"),
        ("delete", "/lock"),
    ],
)
async def test_assistant_routes_reject_other_class(
    api, db, authz, valid_user_token, monkeypatch, method, suffix
):
    await seed_thread(db)
    provider = AsyncMock()
    monkeypatch.setattr(server, "get_openai_client_by_class_id", provider)
    kwargs = {"headers": headers_for("user", valid_user_token)}
    if method in ("post", "put"):
        kwargs["json"] = {"name": "Changed", "target_class_id": 2}
    before = await authz.get_all_calls()
    response = getattr(api, method)(f"/api/v1/class/2/assistant/10{suffix}", **kwargs)
    assert response.status_code == 404, response.text
    provider.assert_not_awaited()
    assert await authz.get_all_calls() == before
    async with db.async_session() as session:
        assistant = await models.Assistant.get_by_id(session, 10)
        assert assistant.name == "Assistant"
        assert assistant.published is None


@with_user(123)
@with_authz(grants=GRANTS)
@pytest.mark.parametrize(
    "operation,file_field",
    [
        (operation, field)
        for operation in (
            "create_thread",
            "send",
            "create_assistant",
            "update_assistant",
        )
        for field in (
            "file_search_file_ids",
            "code_interpreter_file_ids",
            "vision_file_ids",
        )
        if field != "vision_file_ids" or not operation.endswith("assistant")
    ],
)
@pytest.mark.parametrize("file_id", ["foreign", "unknown"])
async def test_attachment_class_validation_precedes_remote_work_and_edits(
    api, db, valid_user_token, monkeypatch, operation, file_field, file_id
):
    await seed_thread(db)
    async with db.async_session() as session:
        await models.File.create(
            session,
            {
                "file_id": "foreign",
                "class_id": 2,
                "name": "Foreign",
                "uploader_id": 123,
            },
            2,
        )
        await session.commit()
    remote = AsyncMock()
    provider = SimpleNamespace(
        beta=SimpleNamespace(threads=SimpleNamespace(runs=SimpleNamespace(list=remote)))
    )
    monkeypatch.setattr(
        server, "get_openai_client_by_class_id", AsyncMock(return_value=provider)
    )
    vector_store = AsyncMock()
    monkeypatch.setattr(server, "create_vector_store", vector_store)
    body = {file_field: [file_id], "message": "Hello", "assistant_id": 10}
    if operation == "create_thread":
        method, path = "post", "/thread"
    elif operation == "send":
        method, path = "post", "/thread/20"
    else:
        method, path = (
            ("post", "/assistant")
            if operation == "create_assistant"
            else ("put", "/assistant/10")
        )
        body.update(
            name="Changed",
            description="Description",
            instructions="Instructions",
            model="gpt-4o-mini",
        )
    # A completed run lets message sending reach attachment validation.
    async with db.async_session() as session:
        session.add(
            models.Run(
                thread_id=20,
                assistant_id=10,
                creator_id=123,
                status=schemas.RunStatus.COMPLETED,
            )
        )
        await session.commit()
    response = getattr(api, method)(
        "/api/v1/class/1" + path,
        json=body,
        headers=headers_for("user", valid_user_token),
    )
    assert response.status_code == 404, response.text
    vector_store.assert_not_awaited()
    remote.assert_not_awaited()
    async with db.async_session() as session:
        assistant = await models.Assistant.get_by_id(session, 10)
        assert assistant.name == "Assistant"
        thread = await models.Thread.get_by_id(session, 20)
        assert thread.user_message_ct == 0


@with_user(123)
@with_authz(grants=GRANTS)
@pytest.mark.parametrize("path", ["/file/30", "/user/123/file/30"])
async def test_delete_file_rejects_class_without_association(
    api, db, authz, valid_user_token, monkeypatch, path
):
    await seed_thread(db)
    async with db.async_session() as session:
        await models.File.create(
            session,
            {
                "id": 30,
                "file_id": "file-30",
                "class_id": 1,
                "name": "Owned",
                "uploader_id": 123,
            },
            1,
        )
        await session.commit()
    provider = SimpleNamespace(files=SimpleNamespace(delete=AsyncMock()))
    resolve_provider = AsyncMock(return_value=provider)
    monkeypatch.setattr(server, "get_openai_client_by_class_id", resolve_provider)
    before = await authz.get_all_calls()
    response = api.delete(
        "/api/v1/class/2" + path, headers=headers_for("user", valid_user_token)
    )
    assert response.status_code == 404, response.text
    resolve_provider.assert_not_awaited()
    provider.files.delete.assert_not_awaited()
    assert await authz.get_all_calls() == before
    async with db.async_session() as session:
        assert await models.File.get_file_ids_for_class(session, 1, [30]) == {30}


@with_user(123)
async def test_shared_and_duplicate_remote_file_ids_resolve_within_class(db, user):
    await seed_thread(db)
    async with db.async_session() as session:
        local = await models.File.create(
            session, {"file_id": "duplicate", "name": "Local", "class_id": 1}, 1
        )
        foreign = await models.File.create(
            session, {"file_id": "duplicate", "name": "Foreign", "class_id": 2}, 2
        )
        shared = await models.File.create(
            session, {"file_id": "shared", "name": "Shared", "class_id": 2}, 2
        )
        await session.execute(
            insert(models.file_class_association).values(class_id=1, file_id=shared.id)
        )
        resolved = await get_attachment_files_for_class(
            session, 1, ["duplicate", "shared", "duplicate"]
        )
        assert {f.id for f in resolved} == {local.id, shared.id}
        # The later association writers must use the same scope as the precheck.
        await models.Thread.add_code_interpreter_files(
            session, 20, ["duplicate", "shared"]
        )
        await models.Thread.add_image_files(session, 20, ["duplicate", "shared"])
        store_id = await models.VectorStore.create(
            session,
            {
                "class_id": 1,
                "vector_store_id": "vs",
                "type": schemas.VectorStoreType.THREAD,
            },
            ["duplicate"],
        )
        await models.VectorStore.add_files(session, store_id, ["shared"])
        await models.VectorStore.sync_files(session, store_id, ["duplicate", "shared"])
        await models.Thread.create(
            session,
            {
                "id": 21,
                "class_id": 1,
                "version": 3,
                "code_interpreter_file_ids": ["duplicate", "shared"],
                "image_file_ids": ["duplicate", "shared"],
            },
        )
        data = schemas.CreateAssistant(
            name="Created",
            description="Description",
            instructions="Be helpful.",
            model="gpt-4o-mini",
            code_interpreter_file_ids=["duplicate", "shared"],
        )
        # Match the API's separation of configuration-only fields from model data.
        for field in (
            "file_search_file_ids",
            "generation_prompt",
            "video_description_duration_ms",
            "overwrite_manifest",
            "deleted_private_files",
            "create_classic_assistant",
            "mcp_servers",
        ):
            delattr(data, field)
        assistant = await models.Assistant.create(
            session, data, class_id=1, user_id=123, version=3
        )
        for table, column, owner in (
            (models.code_interpreter_file_thread_association, "thread_id", 20),
            (models.image_file_thread_association, "thread_id", 20),
            (models.file_vector_store_association, "vector_store_id", store_id),
            (models.code_interpreter_file_thread_association, "thread_id", 21),
            (models.image_file_thread_association, "thread_id", 21),
            (
                models.code_interpreter_file_assistant_association,
                "assistant_id",
                assistant.id,
            ),
        ):
            ids = set(
                await session.scalars(
                    select(table.c.file_id).where(table.c[column] == owner)
                )
            )
            assert ids == {local.id, shared.id}
            assert foreign.id not in ids
        with pytest.raises(HTTPException) as error:
            await get_attachment_files_for_class(session, 1, ["shared", "unknown"])
        assert error.value.status_code == 404


@with_user(123)
@with_authz(grants=GRANTS + [("user:123", "can_create_assistants", "class:2")])
async def test_assistant_copy_preserves_private_file_search_files(
    api, db, valid_user_token, monkeypatch
):
    await seed_thread(db)
    async with db.async_session() as session:
        target = await models.Class.get_by_id(session, 2)
        target.api_key = "key-1"
        file = await models.File.create(
            session,
            {
                "name": "Private source",
                "file_id": "file-private-source",
                "class_id": 1,
                "private": True,
                "uploader_id": 123,
            },
            1,
        )
        source = models.VectorStore(
            class_id=1,
            vector_store_id="vs-source",
            files=[file],
            type=schemas.VectorStoreType.ASSISTANT,
        )
        session.add(source)
        await session.flush()
        assistant = await models.Assistant.get_by_id(session, 10)
        assistant.vector_store_id = source.id
        assistant.creator_id = 123
        file_id = file.id
        assert await models.File.get_file_ids_for_class(session, 2, [file_id]) == set()
        await session.commit()
    provider = SimpleNamespace(
        vector_stores=SimpleNamespace(
            create=AsyncMock(return_value=SimpleNamespace(id="vs-copy")),
            delete=AsyncMock(),
            file_batches=SimpleNamespace(create_and_poll=AsyncMock()),
        )
    )
    monkeypatch.setattr(
        server, "get_openai_client_by_class_id", AsyncMock(return_value=provider)
    )
    response = api.post(
        "/api/v1/class/1/assistant/10/copy",
        json={"target_class_id": 2},
        headers=headers_for("user", valid_user_token),
    )
    assert response.status_code == 200, response.text
    copied_id = response.json()["id"]
    async with db.async_session() as session:
        copied = await models.Assistant.get_by_id(session, copied_id)
        assert copied.class_id == 2
        assert await models.File.get_file_ids_for_class(session, 2, [file_id]) == {
            file_id
        }
        files = await models.VectorStore.get_files_by_id(
            session, copied.vector_store_id
        )
        assert [file.id for file in files] == [file_id]
