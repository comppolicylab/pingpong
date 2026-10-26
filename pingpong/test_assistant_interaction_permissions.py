import pytest
from sqlalchemy import func, select

from pingpong import models, schemas
from pingpong.test_lecture_slide_runtime import _create_slide_runtime_fixture
from pingpong.test_lecture_video_server import create_ready_lecture_video_assistant
from pingpong.testutil import with_authz, with_institution, with_user


async def seed_lesson(db, institution, mode):
    async with db.async_session() as session:
        if mode == "lecture-video":
            _, video, _ = await create_ready_lecture_video_assistant(
                session, institution
            )
            thread = models.Thread(
                id=1,
                class_id=1,
                assistant_id=1,
                lecture_video_id=video.id,
                interaction_mode=schemas.InteractionMode.LECTURE_VIDEO,
                version=3,
            )
            session.add(thread)
        else:
            _, _, assistant, thread, _ = await _create_slide_runtime_fixture(
                session, institution
            )
            assistant.interaction_mode = schemas.InteractionMode.LECTURE_SLIDES
            thread.interaction_mode = schemas.InteractionMode.LECTURE_SLIDES
        link = await models.AnonymousLink.create(
            session, share_token="share", assistant_id=1
        )
        anonymous_user = await models.User.create_anonymous_user(
            session, anonymous_link_id=link.id
        )
        await models.AnonymousSession.create(
            session, "session", user_id=anonymous_user.id
        )
        await session.commit()


def principal_context(principal, token):
    headers = {}
    if principal != "anonymous":
        headers["Authorization"] = f"Bearer {token}"
    if principal != "user":
        headers["X-Anonymous-Thread-Session"] = "session"
    return (
        headers,
        "user:123" if principal == "user" else "anonymous_user:session",
        "anonymous_link:share" if principal == "anonymous" else "user:123",
    )


@with_user(123)
@with_institution(11, "Institution")
@with_authz(grants=[])
@pytest.mark.parametrize("mode", ["lecture-video", "lecture-slide"])
@pytest.mark.parametrize(
    "operation", ["control/acquire", "control/renew", "interactions"]
)
@pytest.mark.parametrize("principal", ["user", "anonymous", "hybrid"])
async def test_lesson_interactions_require_current_assistant_access(
    api, db, config, institution, valid_user_token, mode, operation, principal
):
    await seed_lesson(db, institution, mode)
    headers, thread_subject, assistant_subject = principal_context(
        principal, valid_user_token
    )
    grant = (assistant_subject, "can_interact_with", "assistant:1")
    async with config.authz.driver.get_client() as client:
        await client.write_safe(
            grant=[
                grant,
                (thread_subject, "can_participate", "thread:1"),
                (thread_subject, "can_view", "thread:1"),
            ]
        )
    base = f"/api/v1/class/1/thread/1/{mode}"
    acquired = api.post(f"{base}/control/acquire", headers=headers)
    assert acquired.status_code == 200, acquired.text
    controller = acquired.json()["controller_session_id"]
    session_key = (
        "lecture_video_session"
        if mode == "lecture-video"
        else "interactive_lesson_session"
    )
    body = (
        None
        if operation == "control/acquire"
        else {"controller_session_id": controller}
    )
    if operation == "interactions":
        body.update(
            type="video_paused" if mode == "lecture-video" else "lesson_paused",
            expected_state_version=acquired.json()[session_key]["state_version"],
            idempotency_key="paused",
            offset_ms=0,
        )
    allowed = api.post(f"{base}/{operation}", json=body, headers=headers)
    assert allowed.status_code == 200, allowed.text
    if operation == "control/acquire":
        controller = allowed.json()["controller_session_id"]
    state_model = (
        models.LectureVideoThreadState
        if mode == "lecture-video"
        else models.LectureSlideThreadState
    )
    interaction_model = (
        models.LectureVideoInteraction
        if mode == "lecture-video"
        else models.LectureSlideInteraction
    )
    async with db.async_session() as session:
        before_version = await session.scalar(
            select(state_model.version).where(state_model.thread_id == 1)
        )
        before_count = await session.scalar(
            select(func.count()).select_from(interaction_model)
        )
    async with config.authz.driver.get_client() as client:
        await client.write_safe(
            revoke=[grant],
            grant=[(assistant_subject, "can_interact_with", "assistant:999")],
        )

    denied = api.post(f"{base}/{operation}", json=body, headers=headers)

    assert denied.status_code == 403, denied.text
    assert (
        denied.json()["detail"]
        == "You do not have permission to interact with this assistant."
    )
    async with db.async_session() as session:
        assert (
            await session.scalar(
                select(state_model.version).where(state_model.thread_id == 1)
            )
            == before_version
        )
        assert (
            await session.scalar(select(func.count()).select_from(interaction_model))
            == before_count
        )
    # Revocation must still let the controller release its lease and read history.
    assert (
        api.post(
            f"{base}/control/release",
            json={"controller_session_id": controller},
            headers=headers,
        ).status_code
        == 200
    )
    assert (
        api.get("/api/v1/class/1/thread/1/lesson/history", headers=headers).status_code
        == 200
    )


@with_user(123)
@with_institution(11, "Institution")
@with_authz(grants=[])
@pytest.mark.parametrize(
    "suffix", ["languages", "translations/original", "translations/es"]
)
@pytest.mark.parametrize("principal", ["user", "anonymous", "hybrid"])
async def test_translation_metadata_requires_selected_assistant_access(
    api, db, config, institution, valid_user_token, suffix, principal
):
    await seed_lesson(db, institution, "lecture-slide")
    headers, _, assistant_subject = principal_context(principal, valid_user_token)
    class_subject = "user:123" if principal == "user" else "anonymous_link:share"
    async with config.authz.driver.get_client() as client:
        await client.write_safe(
            grant=[
                (class_subject, "can_create_thread", "class:1"),
                (assistant_subject, "can_interact_with", "assistant:999"),
            ]
        )
    url = f"/api/v1/class/1/assistant/1/lecture-slides/{suffix}"
    assert api.get(url, headers=headers).status_code == 403
    async with config.authz.driver.get_client() as client:
        await client.write_safe(
            grant=[(assistant_subject, "can_interact_with", "assistant:1")]
        )
    allowed = api.get(url, headers=headers)
    assert allowed.status_code == 200, allowed.text
