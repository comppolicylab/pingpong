import time
from contextlib import asynccontextmanager

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from sqlalchemy import select

from pingpong import models, schemas
from pingpong.now import offset
from pingpong.testutil import with_institution, with_user

from . import store
from .settings import OpenAccessSettings
from .tokens import GRANT_AUDIENCE, encode_access_token

MARKER = {"X-PingPong-OA": "1"}
PRIVATE_KEY = ec.generate_private_key(ec.SECP256R1())


class FakeRedis:
    def __init__(self):
        self.values: dict[str, str] = {}

    async def set(self, key, value, ex=None, nx=False):
        if nx and key in self.values:
            return None
        self.values[key] = value
        return True

    async def get(self, key):
        return self.values.get(key)

    async def getdel(self, key):
        return self.values.pop(key, None)

    async def expire(self, key, seconds):
        return key in self.values


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
    fake = FakeRedis()

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
async def test_launch_exchange_and_player_access(api, db, authz, oa, lessons):
    first = launch(api, launch_grant())
    assert first.status_code == 200
    retry = launch(api, launch_grant())
    assert retry.json()["session_id"] == first.json()["session_id"]

    access = exchange(api, first.json()["code"])
    assert access.status_code == 200
    body = access.json()
    assert exchange(api, first.json()["code"]).status_code == 400
    assert exchange(api, retry.json()["code"]).json()["thread_id"] == body["thread_id"]

    async with db.async_session() as session:
        session_token = await session.scalar(
            select(models.AnonymousSession.session_token).where(
                models.AnonymousSession.thread_id == body["thread_id"]
            )
        )
    await authz.reset(
        {
            "grants": [
                (
                    f"anonymous_user:{session_token}",
                    "can_view",
                    f"thread:{body['thread_id']}",
                )
            ]
        }
    )

    thread_url = f"/api/v1/class/{body['class_id']}/thread/{body['thread_id']}"
    player = api.get(thread_url, headers=player_headers(body["access_token"]))
    assert player.status_code == 200
    no_marker = api.get(
        thread_url, headers={"X-PingPong-OA-Token": body["access_token"]}
    )
    assert no_marker.status_code == 401
    raw_session = api.get(
        thread_url, headers={"X-Anonymous-Thread-Session": session_token}
    )
    assert raw_session.status_code == 403


@pytest.mark.asyncio
@with_institution(11, "OA Institution")
async def test_launch_enforces_tier_and_grant_signature(api, oa, lessons):
    assert launch(api, launch_grant(assistant_id=2)).status_code == 403
    assert launch(api, launch_grant(assistant_id=3)).status_code == 404
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
    second = launch(api, launch_grant(launch_id="launch-second-00001"))
    old_sid = first.json()["session_id"]
    new_sid = second.json()["session_id"]
    assert old_sid != new_sid

    assert exchange(api, first.json()["code"]).status_code == 409

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
@with_user(123)
@with_institution(11, "OA Institution")
async def test_expired_access_token_rejected_with_valid_login(
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
    response = api.get(
        f"/api/v1/class/{body['class_id']}/thread/{body['thread_id']}",
        headers={
            **player_headers(expired),
            "Authorization": f"Bearer {valid_user_token}",
        },
    )
    assert response.status_code == 401
    assert response.json()["detail"]["error_code"] == "open_access_token_invalid"


@pytest.mark.asyncio
@with_institution(11, "OA Institution")
async def test_catalogue_lists_configured_lessons(api, oa, lessons):
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
            "languages": [{"code": "original", "name": "Original"}],
        },
        {
            "assistant_id": 2,
            "name": "Lesson 2",
            "free": False,
            "languages": [{"code": "original", "name": "Original"}],
        },
    ]
