"""Exercise moderation with real lecture preparation and knowledge-check state."""

import importlib
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx2
import openai
import orjson
import pytest
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from pingpong import lesson_checks, models, schemas
from pingpong.test_lecture_slide_runtime import (
    _create_slide_runtime_fixture,
    _slide_transcript_data,
)
from pingpong.test_lecture_video_server import (
    create_ready_lecture_video_assistant,
    lecture_video_manifest_v4,
)
from pingpong.test_moderation import response_for
from pingpong.testutil import with_authz, with_institution, with_user

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def lecture_conversation(db, institution, mode, active_check, verdict):
    async with db.async_session() as session:
        if mode == "video":
            manifest = lecture_video_manifest_v4()
            manifest["questions"] = [
                {
                    "type": "open_ended",
                    "question_text": "Explain why latency matters.",
                    "intro_text": "Explain why latency matters.",
                    "passing_criteria": "Explain how latency affects response time.",
                    "stop_offset_ms": 1000,
                    "options": [],
                }
            ]
            _, video, assistant = await create_ready_lecture_video_assistant(
                session, institution, manifest=manifest
            )
            thread = models.Thread(
                id=1,
                class_id=1,
                assistant=assistant,
                version=3,
                interaction_mode=schemas.InteractionMode.LECTURE_VIDEO,
                lecture_video_id=video.id,
                name="Lecture Lesson",
                tools_available="[]",
                instructions="You are a lecture assistant.",
                user_message_ct=3,
                private=False,
                display_user_info=False,
            )
            session.add(thread)
            question = await session.scalar(
                select(models.LectureVideoQuestion).where(
                    models.LectureVideoQuestion.lecture_video_id == video.id
                )
            )
            state = models.LectureVideoThreadState(thread=thread)
        else:
            _, deck, assistant, thread, _ = await _create_slide_runtime_fixture(
                session, institution, with_questions=False
            )
            assistant.interaction_mode = schemas.InteractionMode.LECTURE_SLIDES
            thread.interaction_mode = schemas.InteractionMode.LECTURE_SLIDES
            thread.instructions = assistant.instructions
            thread.user_message_ct = 3
            deck.transcript_data = _slide_transcript_data()
            deck.context_data = {}
            deck.context_version = 4
            deck.lecture_slide_chat_available = True
            source_file = models.File(
                file_id="pdf-file-id", name="slides.pdf", content_type="application/pdf"
            )
            session.add(source_file)
            await session.flush()
            deck.source_stored_object.openai_file_object_id = source_file.id
            session.add(
                models.LectureSlidePage(
                    lecture_slide_deck=deck,
                    position=0,
                    narration_text="Latency affects response time.",
                    start_offset_ms=0,
                    end_offset_ms=10000,
                )
            )
            question = models.LectureSlideQuestion(
                lecture_slide_deck=deck,
                position=0,
                slide_position=0,
                slide_offset_ms=1000,
                stop_offset_ms=1000,
                question_type=schemas.LectureSlideQuestionType.OPEN_ENDED,
                question_text="Explain why latency matters.",
                intro_text="Explain why latency matters.",
                passing_criteria="Explain how latency affects response time.",
            )
            session.add(question)
            state = models.LectureSlideThreadState(thread=thread)
        assistant.input_moderation_enabled = verdict != "disabled"
        thread.input_moderation_enabled = assistant.input_moderation_enabled
        state.state = (
            schemas.InteractiveLessonSessionState.AWAITING_ANSWER
            if active_check
            else schemas.InteractiveLessonSessionState.PLAYING
        )
        state.current_question = question
        state.last_known_offset_ms = 1000
        state.furthest_offset_ms = 1000
        state.version = 1
        session.add_all([thread, state])
        await session.flush()
        if active_check:
            await lesson_checks.start_check(session, state, question, 123)
        attempt_id = state.check_attempt_id
        await session.commit()
        return attempt_id


@with_user(123)
@with_institution(11, "Test Institution")
@with_authz(
    grants=[
        ("user:123", "can_participate", "thread:1"),
        ("user:123", "can_view", "thread:1"),
        ("user:123", "can_interact_with", "assistant:1"),
        ("user:123", "student", "class:1"),
    ]
)
@pytest.mark.parametrize("mode", ["video", "slides"])
@pytest.mark.parametrize("active_check", [False, True])
@pytest.mark.parametrize("verdict", ["passed", "flagged", "errored", "disabled"])
async def test_lecture_input_moderation(
    api,
    db,
    lecture_conversation,
    mode,
    active_check,
    verdict,
    monkeypatch,
    valid_user_token,
):
    server = importlib.import_module("pingpong.server")
    events = []

    async def moderate(**kwargs):
        assert kwargs["input"] == ["Latency affects response time."]
        async with db.async_session() as session:
            check = await session.scalar(select(models.RunModerationCheck))
            assert check.status == schemas.ModerationCheckStatus.PENDING
            run = await session.get(models.Run, check.run_id)
            assert run.status == schemas.RunStatus.QUEUED
            reviewed = await session.get(models.Message, check.message_ids[0])
            assert not reviewed.is_hidden
            assert reviewed.message_metadata is not None
            if active_check:
                assert (
                    reviewed.message_metadata["check_attempt_id"]
                    == lecture_conversation
                )
                assert "Private passing criteria:" in run.instructions
        events.append("moderation")
        if verdict == "errored":
            raise openai.APITimeoutError(
                request=httpx2.Request("POST", "https://example.invalid")
            )
        return response_for(verdict == "flagged")[0]

    client = SimpleNamespace(
        moderations=SimpleNamespace(create=AsyncMock(side_effect=moderate))
    )
    monkeypatch.setitem(
        server.v1.dependency_overrides,
        server.get_openai_client_for_class,
        lambda: client,
    )
    monkeypatch.setattr(server, "ensure_model_available", AsyncMock())
    name = AsyncMock()
    monkeypatch.setattr(server, "get_thread_conversation_name", name)

    async def generate(*args, **kwargs):
        events.append("generation")
        yield b'{"type":"done"}\n'

    monkeypatch.setattr(server, "run_response", generate)
    headers = {"Authorization": f"Bearer {valid_user_token}"}
    response = api.post(
        "/api/v1/class/1/thread/1",
        json={
            "message": "Latency affects response time.",
            "lecture_video_playback_position_ms": 1000,
            "generate_speech": False,
        },
        headers=headers,
    )
    assert response.status_code == 200, response.text
    name.assert_not_awaited()
    assert events == (
        ["moderation"]
        if verdict == "flagged"
        else ["generation"]
        if verdict == "disabled"
        else ["moderation", "generation"]
    )
    async with db.async_session() as session:
        run = await session.scalar(
            select(models.Run)
            .order_by(models.Run.id.desc())
            .limit(1)
            .options(
                selectinload(models.Run.messages).selectinload(models.Message.content)
            )
        )
        assert any(message.is_hidden for message in run.messages)
        if mode == "slides" and not active_check:
            assert any(
                message.is_hidden and message.role == schemas.MessageRole.USER
                for message in run.messages
            )
        check = await session.scalar(select(models.RunModerationCheck))
        if verdict == "disabled":
            assert check is None
        else:
            assert check.status.value == verdict
            assert check.message_ids == [
                message.id
                for message in run.messages
                if not message.is_hidden and message.role == schemas.MessageRole.USER
            ]
        if verdict == "flagged":
            assert run.status == schemas.RunStatus.INCOMPLETE
            assert not any(
                message.role == schemas.MessageRole.ASSISTANT
                for message in run.messages
            )
        if active_check:
            state_class = (
                models.LectureVideoThreadState
                if mode == "video"
                else models.LectureSlideThreadState
            )
            state = await session.scalar(select(state_class))
            assert state.state == schemas.InteractiveLessonSessionState.AWAITING_ANSWER
            assert state.check_attempt_id == lecture_conversation
            assert state.check_outcome is None
    if verdict == "flagged":
        chunks = [orjson.loads(line) for line in response.content.splitlines()]
        assert [chunk["type"] for chunk in chunks] == ["error", "done"]
        assert chunks[0]["read_only"] is True
        for suffix, body in [("", {"message": "Again"}), ("/run", {})]:
            blocked = api.post(
                "/api/v1/class/1/thread/1" + suffix, json=body, headers=headers
            )
            assert blocked.status_code == 403, blocked.text
        fetched = api.get("/api/v1/class/1/thread/1", headers=headers)
        assert fetched.status_code == 200, fetched.text
        assert fetched.json()["read_only"] is True
