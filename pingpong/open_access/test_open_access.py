import importlib
import json
import time
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import fakeredis
import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from sqlalchemy import select

from pingpong import lesson_checks, models, schemas
from pingpong.errors import OPEN_ACCESS_TAG, scrub_open_access_event
from pingpong.now import offset, utcnow
from pingpong.test_lecture_slide_runtime import _slide_transcript_data
from pingpong.testutil import with_institution, with_user

from . import limits, retention, router, store
from .settings import OpenAccessSettings, TierLimits
from .tokens import GRANT_AUDIENCE, encode_access_token

MARKER = {"X-PingPong-OA": "1"}
PRIVATE_KEY = ec.generate_private_key(ec.SECP256R1())


@pytest.fixture
def oa(config, monkeypatch):
    settings = OpenAccessSettings(
        redis_url="redis://localhost:6379/0",
        client_id="oa",
        public_key=PRIVATE_KEY.public_key()
        .public_bytes(
            serialization.Encoding.PEM,
            serialization.PublicFormat.SubjectPublicKeyInfo,
        )
        .decode(),
        origin="https://learning-ai-with-ai.example.edu",
        assistant_ids=[1, 2],
        free_assistant_id=1,
    )
    monkeypatch.setattr(config, "open_access", settings)
    fake = fakeredis.FakeAsyncRedis(decode_responses=True)

    @asynccontextmanager
    async def redis_client(_settings):
        yield fake

    monkeypatch.setattr(store, "redis_client", redis_client)
    return settings


def grant(**claims) -> str:
    now = int(time.time())
    return jwt.encode(
        {"iss": "oa", "aud": GRANT_AUDIENCE, "iat": now, "exp": now + 60, **claims},
        PRIVATE_KEY,
        algorithm="ES256",
    )


def launch_grant(sub="visitor1", tier="anonymous", assistant_id=1, launch_id=None):
    return grant(
        typ="launch",
        sub=sub,
        tier=tier,
        assistant_id=assistant_id,
        launch_id=launch_id or f"launch-{sub}-{assistant_id}-0001",
    )


@pytest.fixture
async def lessons(db, institution):
    async with db.async_session() as session:
        class_ = models.Class(
            id=1, name="OA", institution_id=institution.id, api_key="test-key"
        )
        session.add(class_)
        for assistant_id in (1, 2):
            deck = models.LectureSlideDeck(
                class_=class_,
                source_stored_object=models.LectureSlideSourceStoredObject(
                    key=f"slides-{assistant_id}.pdf",
                    original_filename="slides.pdf",
                    content_type="application/pdf",
                    content_length=128,
                ),
                display_name="Slides",
                status=schemas.LectureSlideDeckStatus.READY,
                lecture_slide_chat_available=True,
                transcript_data=_slide_transcript_data(),
                context_data={},
                context_version=4,
                slide_count=1,
                total_duration_ms=1_000,
            )
            session.add_all(
                [
                    deck,
                    models.LectureSlidePage(
                        lecture_slide_deck=deck,
                        position=0,
                        content_kind=schemas.LectureSlideContentKind.SLIDE,
                        narration_text="Narration.",
                        start_offset_ms=0,
                        end_offset_ms=1_000,
                    ),
                    models.Assistant(
                        id=assistant_id,
                        name=f"Lesson {assistant_id}",
                        class_=class_,
                        interaction_mode=schemas.InteractionMode.LECTURE_SLIDES,
                        version=3,
                        lecture_slide_deck=deck,
                        instructions="Teach.",
                        model="gpt-4o-mini",
                        tools="[]",
                        use_latex=False,
                        use_image_descriptions=False,
                        hide_prompt=False,
                    ),
                ]
            )
        await session.commit()


def launch(api, grant_token):
    return api.post("/api/v1/oa/launch", json={"grant": grant_token}, headers=MARKER)


def exchange(api, code):
    return api.post("/api/v1/oa/exchange", json={"code": code}, headers=MARKER)


def player_headers(token):
    return {**MARKER, "X-PingPong-OA-Token": token}


@pytest.mark.asyncio
@with_institution(11, "OA Institution")
async def test_launch_and_player_access(api, db, authz, oa, lessons):
    first = launch(api, launch_grant())
    assert first.status_code == 200
    retry = launch(api, launch_grant())
    assert retry.json()["session_id"] == first.json()["session_id"]

    body = exchange(api, first.json()["code"]).json()
    assert exchange(api, first.json()["code"]).status_code == 400
    assert exchange(api, retry.json()["code"]).json()["thread_id"] == body["thread_id"]

    async with db.async_session() as session:
        anonymous_session = await session.scalar(
            select(models.AnonymousSession).where(
                models.AnonymousSession.thread_id == body["thread_id"]
            )
        )
        thread = await session.get(models.Thread, body["thread_id"])
        assert anonymous_session.user_id is None
        assert thread.private is True
    subject = f"anonymous_user:{anonymous_session.session_token}"
    assert [call for call in await authz.get_all_calls() if call[0] == "grant"] == [
        ("grant", "class:1", "parent", f"thread:{body['thread_id']}"),
        ("grant", subject, "anonymous_party", f"thread:{body['thread_id']}"),
        ("grant", subject, "can_view", "assistant:1"),
    ]

    # The mock FGA server only matches direct tuples, so grant the computed view.
    await authz.reset(
        {"grants": [(subject, "can_view", f"thread:{body['thread_id']}")]}
    )
    thread_url = f"/api/v1/class/{body['class_id']}/thread/{body['thread_id']}"
    token = body["access_token"]
    avatar = api.get(f"{thread_url}/assistant-avatar", headers=player_headers(token))
    assert avatar.json()["detail"] == "Assistant avatar not found."

    def error_code(response):
        return response.json()["detail"]["error_code"]

    assert (
        error_code(
            api.get(
                f"{thread_url}/assistant-avatar",
                headers={"X-PingPong-OA-Token": token},
            )
        )
        == "open_access_token_invalid"
    )
    assert (
        error_code(api.get("/api/v1/me", headers=player_headers(token)))
        == "open_access_route_forbidden"
    )
    assert (
        error_code(
            api.get(
                f"/api/v1/class/1/thread/{body['thread_id'] + 1}/assistant-avatar",
                headers=player_headers(token),
            )
        )
        == "open_access_route_forbidden"
    )
    raw_session = api.get(
        f"{thread_url}/assistant-avatar",
        headers={"X-Anonymous-Thread-Session": anonymous_session.session_token},
    )
    assert raw_session.status_code == 403


@pytest.mark.asyncio
@with_institution(11, "OA Institution")
async def test_launch_enforces_tier_and_grant_signature(api, oa, lessons):
    assert launch(api, launch_grant(assistant_id=2)).status_code == 403
    assert launch(api, launch_grant(assistant_id=3)).status_code == 403
    forged = jwt.encode(
        {"typ": "launch"}, ec.generate_private_key(ec.SECP256R1()), algorithm="ES256"
    )
    assert launch(api, forged).status_code == 401
    registered = launch(
        api, launch_grant(sub="user1", tier="registered", assistant_id=2)
    )
    assert registered.status_code == 200
    assert launch(api, launch_grant(sub="user1", tier="anonymous")).status_code == 409
    oa.paused = True
    assert launch(api, launch_grant(sub="user1", tier="registered")).status_code == 503


@pytest.mark.asyncio
@with_institution(11, "OA Institution")
async def test_new_launch_displaces_previous_session(api, oa, lessons):
    first = launch(api, launch_grant(launch_id="launch-first-000001"))
    first_retry = launch(api, launch_grant(launch_id="launch-first-000001"))
    first_token = exchange(api, first.json()["code"]).json()
    second = launch(api, launch_grant(launch_id="launch-second-00001"))
    old_sid = first.json()["session_id"]
    new_sid = second.json()["session_id"]
    assert old_sid != new_sid

    assert exchange(api, first_retry.json()["code"]).status_code == 409
    displaced = api.get(
        f"/api/v1/class/1/thread/{first_token['thread_id']}/assistant-avatar",
        headers=player_headers(first_token["access_token"]),
    )
    assert displaced.json()["detail"]["error_code"] == "session_displaced"

    def renew(sid):
        return api.post(
            "/api/v1/oa/renew",
            json={"grant": grant(typ="renew", sub="visitor1", assistant_id=1, sid=sid)},
            headers=MARKER,
        )

    assert renew(old_sid).status_code == 409
    renewed = renew(new_sid)
    assert renewed.status_code == 200
    assert exchange(api, renewed.json()["code"]).status_code == 200


@pytest.mark.asyncio
@with_institution(11, "OA Institution")
async def test_launch_replaces_thread_after_lesson_update(api, db, oa, lessons):
    first = exchange(api, launch(api, launch_grant()).json()["code"]).json()
    assert launch(api, launch_grant(sub="visitor2")).status_code == 200
    async with db.async_session() as session:
        lesson, other = [await session.get(models.Assistant, i) for i in (1, 2)]
        deck_id, other.lecture_slide_deck_id = other.lecture_slide_deck_id, None
        await session.flush()
        lesson.lecture_slide_deck_id = deck_id
        await session.commit()

    second = exchange(
        api, launch(api, launch_grant(launch_id="launch-updated-0001")).json()["code"]
    ).json()
    assert second["thread_id"] != first["thread_id"]
    async with db.async_session() as session:
        assert await session.get(models.Thread, first["thread_id"]) is None


@pytest.mark.asyncio
@with_institution(11, "OA Institution")
async def test_transfer_keeps_existing_thread_on_conflict(
    api, db, oa, lessons, monkeypatch
):
    exchange(api, launch(api, launch_grant()).json()["code"])
    exchange(
        api, launch(api, launch_grant(sub="member1", tier="registered")).json()["code"]
    )
    async with db.async_session() as session:
        target_id = await session.scalar(
            select(models.ExternalPrincipal.id).where(
                models.ExternalPrincipal.subject == "member1"
            )
        )
    lookup = router.get_principal_thread

    async def missing_target(db, principal_id, assistant_id):
        if principal_id == target_id:
            return None
        return await lookup(db, principal_id, assistant_id)

    monkeypatch.setattr(router, "get_principal_thread", missing_target)
    response = api.post(
        "/api/v1/oa/transfer",
        json={"grant": grant(typ="transfer", sub="visitor1", to="member1")},
        headers=MARKER,
    )
    assert response.json() == {"thread_moved": False}


@pytest.mark.asyncio
@with_institution(11, "OA Institution")
async def test_transfer_moves_free_thread_and_usage_once(api, db, now, oa, lessons):
    anonymous = exchange(api, launch(api, launch_grant()).json()["code"]).json()
    async with db.async_session() as session:
        source_id = await session.scalar(
            select(models.ExternalPrincipal.id).where(
                models.ExternalPrincipal.subject == "visitor1"
            )
        )
    today = now()
    async with store.redis_client(oa) as redis:
        await redis.zadd(
            store.principal_key(oa, source_id, "turns"), {"t1": limits._ms(today)}
        )
        await redis.set(
            store.principal_key(oa, source_id, "tokens", limits._day(today)), 50
        )

    def transfer(to="member1"):
        return api.post(
            "/api/v1/oa/transfer",
            json={"grant": grant(typ="transfer", sub="visitor1", to=to)},
            headers=MARKER,
        )

    exchange(api, launch(api, launch_grant(sub="visitor2")).json()["code"])
    assert transfer("visitor2").status_code == 409
    assert transfer().json() == {"thread_moved": True}
    assert transfer().json() == {"thread_moved": False}
    assert transfer("member2").json() == {"thread_moved": False}
    registered = exchange(
        api, launch(api, launch_grant(sub="member1", tier="registered")).json()["code"]
    ).json()
    assert registered["thread_id"] == anonymous["thread_id"]
    async with db.async_session() as session:
        target_id = await session.scalar(
            select(models.ExternalPrincipal.id).where(
                models.ExternalPrincipal.subject == "member1"
            )
        )
    async with store.redis_client(oa) as redis:
        assert await redis.zcard(store.principal_key(oa, target_id, "turns")) == 1
        assert (
            await redis.get(
                store.principal_key(oa, target_id, "tokens", limits._day(today))
            )
            == "50"
        )


@pytest.mark.asyncio
@with_institution(11, "OA Institution")
async def test_admin_grants_end_session_reset_and_pause(api, db, oa, lessons):
    body = exchange(api, launch(api, launch_grant()).json()["code"]).json()
    thread_url = f"/api/v1/class/{body['class_id']}/thread/{body['thread_id']}"

    def admin(typ, **claims):
        return api.post(
            f"/api/v1/oa/{typ.replace('_', '-')}",
            json={"grant": grant(typ=typ, **claims)},
            headers=MARKER,
        )

    def player_error():
        response = api.get(
            f"{thread_url}/assistant-avatar",
            headers=player_headers(body["access_token"]),
        )
        return response.json()["detail"]["error_code"]

    assert admin("end_session", sub="visitor1").status_code == 204
    assert player_error() == "session_displaced"

    assert admin("pause", paused=True).status_code == 204
    assert (
        launch(api, launch_grant(launch_id="launch-visitor1-1-0002")).status_code == 503
    )
    assert admin("pause", paused=False).status_code == 204

    assert admin("reset", sub="visitor1", assistant_id=1).json() == {"reset": True}
    assert admin("reset", sub="visitor1", assistant_id=1).json() == {"reset": False}
    async with db.async_session() as session:
        assert await session.get(models.Thread, body["thread_id"]) is None


@pytest.mark.asyncio
@with_user(123)
@with_institution(11, "OA Institution")
async def test_expired_or_missing_token_rejected_with_valid_login(
    api, oa, lessons, now, valid_user_token
):
    body = exchange(api, launch(api, launch_grant()).json()["code"]).json()
    expired = encode_access_token(
        oa,
        principal_id=1,
        thread_id=body["thread_id"],
        class_id=body["class_id"],
        session_id=body["session_id"],
        nowfn=offset(now, seconds=-3600),
    )
    thread_url = f"/api/v1/class/{body['class_id']}/thread/{body['thread_id']}"
    login = {"Authorization": f"Bearer {valid_user_token}"}
    for headers in ({**player_headers(expired), **login}, {**MARKER, **login}):
        response = api.get(thread_url, headers=headers)
        assert response.status_code == 401
        assert response.json()["detail"]["error_code"] == "open_access_token_invalid"


@pytest.mark.asyncio
@with_institution(11, "OA Institution")
async def test_catalogue_lists_configured_lessons(api, db, oa, lessons):
    async with db.async_session() as session:
        decks = [
            (await session.get(models.Assistant, i)).lecture_slide_deck_id
            for i in (1, 2)
        ]
    response = api.post(
        "/api/v1/oa/catalogue",
        json={"grant": grant(typ="catalogue")},
        headers=MARKER,
    )
    assert response.status_code == 200
    assert response.json()["lessons"] == [
        {
            "assistant_id": 1,
            "name": "Lesson 1",
            "free": True,
            "thumbnail_version": decks[0],
        },
        {
            "assistant_id": 2,
            "name": "Lesson 2",
            "free": False,
            "thumbnail_version": decks[1],
        },
    ]


async def start_player(api, db, authz):
    body = exchange(api, launch(api, launch_grant()).json()["code"]).json()
    async with db.async_session() as session:
        session_token = await session.scalar(
            select(models.AnonymousSession.session_token).where(
                models.AnonymousSession.thread_id == body["thread_id"]
            )
        )
    subject = f"anonymous_user:{session_token}"
    thread = f"thread:{body['thread_id']}"
    # The mock FGA server only matches direct tuples, so grant the computed ones.
    await authz.reset(
        {
            "grants": [
                (subject, "can_view", thread),
                (subject, "can_participate", thread),
                (subject, "can_interact_with", "assistant:1"),
            ]
        }
    )
    url = f"/api/v1/class/{body['class_id']}/thread/{body['thread_id']}"
    return body, url, player_headers(body["access_token"])


@pytest.mark.asyncio
@with_institution(11, "OA Institution")
async def test_player_controls_lesson_without_user(api, db, authz, oa, lessons):
    body, url, headers = await start_player(api, db, authz)

    loaded = api.get(url, headers=headers)
    assert loaded.status_code == 200, loaded.text

    await limits.set_paused(oa, True)
    paused = api.get(url, headers=headers)
    assert paused.json()["detail"]["error_code"] == "open_access_paused"
    await limits.set_paused(oa, False)

    cookie = {"Cookie": f"pp_oa_token={body['access_token']}"}
    captions_url = f"{url}/lecture-slides/captions.vtt"
    assert api.get(captions_url, params={"pp_oa": "1"}).status_code == 401
    captions = api.get(captions_url, params={"pp_oa": "1"}, headers=cookie)
    assert captions.json()["detail"] == "No Video Store exists."
    assert api.get(url, headers={**MARKER, **cookie}).status_code == 401

    first = api.post(f"{url}/lecture-slide/control/acquire", headers=headers).json()
    second = api.post(f"{url}/lecture-slide/control/acquire", headers=headers)
    assert second.status_code == 200
    second_id = second.json()["controller_session_id"]
    assert second_id != first["controller_session_id"]
    assert second.json()["interactive_lesson_session"]["controller"]["has_control"]

    def renew(controller_session_id):
        return api.post(
            f"{url}/lecture-slide/control/renew",
            json={"controller_session_id": controller_session_id},
            headers=headers,
        )

    assert renew(first["controller_session_id"]).status_code == 409
    assert renew(second_id).status_code == 200

    paused = api.post(
        f"{url}/lecture-slide/interactions",
        json={
            "type": "lesson_paused",
            "controller_session_id": second_id,
            "expected_state_version": second.json()["interactive_lesson_session"][
                "state_version"
            ],
            "idempotency_key": "pause-1",
            "offset_ms": 0,
        },
        headers=headers,
    )
    assert paused.status_code == 200, paused.text

    history = api.get(f"{url}/lesson/history", headers=headers)
    assert history.status_code == 200, history.text
    assert all(item["actor_name"] == "Me" for item in history.json()["interactions"])

    released = api.post(
        f"{url}/lecture-slide/control/release",
        json={"controller_session_id": second_id},
        headers=headers,
    )
    assert released.status_code == 200
    async with db.async_session() as session:
        state = await session.scalar(
            select(models.LectureSlideThreadState).where(
                models.LectureSlideThreadState.thread_id == body["thread_id"]
            )
        )
        assert state.controller_anonymous_session_id is None
        assert state.controller_user_id is None


@pytest.mark.asyncio
@with_institution(11, "OA Institution")
async def test_player_sends_message_without_user(
    api, db, authz, oa, lessons, monkeypatch
):
    server = importlib.import_module("pingpong.server")

    def openai_client():
        return SimpleNamespace()

    monkeypatch.setitem(
        server.v1.dependency_overrides,
        server.get_openai_client_for_class,
        openai_client,
    )
    monkeypatch.setattr(server, "ensure_model_available", AsyncMock())
    monkeypatch.setattr(server, "get_thread_conversation_name", AsyncMock())

    calls = []

    async def generate(*args, **kwargs):
        calls.append(kwargs)
        yield b'{"type":"done"}\n'

    monkeypatch.setattr(server, "run_response", generate)
    oa.limits.anonymous = TierLimits(thread_turns_per_day=1, principal_turns_per_day=5)
    body, url, headers = await start_player(api, db, authz)

    attachment = api.post(
        url,
        json={"message": "Hi", "vision_file_ids": ["file-1"]},
        headers=headers,
    )
    assert attachment.json()["detail"]["error_code"] == "open_access_uploads_disabled"

    sent = api.post(
        url,
        json={
            "message": "Why does latency matter?",
            "lecture_video_playback_position_ms": 0,
            "generate_speech": False,
        },
        headers=headers,
    )
    assert sent.status_code == 200, sent.text
    assert calls[0]["store"] is False

    messages = api.get(f"{url}/messages", headers=headers)
    assert messages.status_code == 200, messages.text
    mine = [
        message for message in messages.json()["messages"] if message["role"] == "user"
    ]
    assert [message["metadata"]["name"] for message in mine] == ["Me"]
    async with db.async_session() as session:
        run = await session.scalar(
            select(models.Run).where(models.Run.thread_id == body["thread_id"])
        )
        assert run.creator_id is None
        run.status = schemas.RunStatus.COMPLETED
        thread = await session.get(models.Thread, body["thread_id"])
        question = models.LectureSlideQuestion(
            lecture_slide_deck_id=thread.lecture_slide_deck_id,
            position=0,
            slide_position=0,
            slide_offset_ms=500,
            stop_offset_ms=500,
            question_type=schemas.LectureSlideQuestionType.OPEN_ENDED,
            question_text="Why does latency matter?",
            intro_text="Why does latency matter?",
            passing_criteria="Mentions response time.",
        )
        state = await session.scalar(
            select(models.LectureSlideThreadState).where(
                models.LectureSlideThreadState.thread_id == thread.id
            )
        )
        state.state = schemas.InteractiveLessonSessionState.AWAITING_ANSWER
        state.current_question = question
        await session.flush()
        await lesson_checks.start_check(session, state, question, None)
        await session.commit()

    def send(message):
        return api.post(
            url,
            json={"message": message, "generate_speech": False},
            headers=headers,
        )

    too_long = send("x" * (oa.limits.message_max_characters + 1))
    assert too_long.json()["detail"]["error_code"] == "open_access_message_too_long"
    limited = send("Because it is slow.")
    assert limited.status_code == 429
    assert limited.json()["detail"]["error_code"] == "open_access_thread_turn_limit"
    assert api.get(url, headers=headers).json()["read_only"] is True

    def check_state(session):
        return session.scalar(
            select(models.LectureSlideThreadState).where(
                models.LectureSlideThreadState.thread_id == body["thread_id"]
            )
        )

    async with db.async_session() as session:
        state = await check_state(session)
        assert state.check_outcome == "passed"
        await session.refresh(state, ["thread"])
        state.state = schemas.InteractiveLessonSessionState.AWAITING_ANSWER
        question = await session.get(
            models.LectureSlideQuestion, state.current_question_id
        )
        await lesson_checks.start_check(session, state, question, None)
        await session.commit()
    assert api.get(url, headers=headers).json()["read_only"] is True
    async with db.async_session() as session:
        assert (await check_state(session)).check_outcome == "passed"


@pytest.mark.asyncio
@with_institution(11, "OA Institution")
async def test_retention_purges_inactive_threads_and_principals(
    api, db, authz, oa, lessons, caplog
):
    body = exchange(api, launch(api, launch_grant()).json()["code"]).json()
    async with db.async_session() as session:
        token = await session.scalar(
            select(models.AnonymousSession.session_token).where(
                models.AnonymousSession.thread_id == body["thread_id"]
            )
        )
    subject = f"anonymous_user:{token}"
    tuples = [
        ("class:1", "parent", f"thread:{body['thread_id']}"),
        (subject, "anonymous_party", f"thread:{body['thread_id']}"),
        (subject, "can_view", "assistant:1"),
    ]
    await authz.reset({"grants": tuples})

    assert await retention.purge_inactive(utcnow()) == (0, 0)
    assert await retention.purge_inactive(utcnow() + retention.INACTIVITY) == (1, 1)

    async with db.async_session() as session:
        assert await session.get(models.Thread, body["thread_id"]) is None
        assert await session.scalar(select(models.ExternalPrincipal)) is None
    assert await authz.get_all_calls() == [("revoke", *t) for t in tuples]
    events = [
        json.loads(record.getMessage())
        for record in caplog.records
        if record.name == "pingpong.audit" and "retention" in record.getMessage()
    ]
    assert [
        (event["audit"], event.get("thread_id"), event.get("principal_id"))
        for event in events
    ] == [
        ("oa.retention.run", None, None),
        ("oa.retention.thread_delete", body["thread_id"], 1),
        ("oa.retention.principal_delete", None, 1),
        ("oa.retention.run", None, None),
    ]


def test_sentry_scrubs_open_access_requests():
    event = {
        "tags": {OPEN_ACCESS_TAG: "true"},
        "request": {
            "data": {"message": "secret"},
            "query_string": "pp_oa=1",
            "cookies": {"pp_oa_token": "token"},
            "headers": {"X-PingPong-OA-Token": "token", "User-Agent": "test"},
        },
        "exception": {
            "values": [{"stacktrace": {"frames": [{"vars": {"data": "secret"}}]}}]
        },
        "breadcrumbs": {"values": [{"message": "secret"}]},
    }
    scrubbed = scrub_open_access_event(event, None)
    assert scrubbed["request"] == {"headers": {"User-Agent": "test"}}
    assert scrubbed["exception"]["values"][0]["stacktrace"]["frames"] == [{}]
    assert "breadcrumbs" not in scrubbed
