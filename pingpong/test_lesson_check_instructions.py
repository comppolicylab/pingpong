from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from pingpong import interactive_lesson_runtime as runtime, lesson_checks
from pingpong.say_transform import (
    SAY_MARKER_START,
    SAY_MARKER_SEPARATOR,
    SAY_MARKER_END,
)

from pingpong.testutil import with_authz, with_institution, with_user


@pytest.mark.parametrize(
    "custom", [None, "Accept a short explanation. Ask one hint at a time."]
)
async def test_check_instructions_replace_only_editable_passage(monkeypatch, custom):
    adapter = object()
    state = SimpleNamespace(
        state=SimpleNamespace(value="awaiting_answer"),
        check_attempt_id=17,
        thread=object(),
    )
    question = SimpleNamespace(
        question_type="open_ended",
        question_text="Explain latency.",
        passing_criteria="Connect latency to response time.",
    )
    monkeypatch.setattr(lesson_checks, "adapter_for", lambda thread: adapter)
    monkeypatch.setattr(
        runtime, "get_or_initialize_thread_state", AsyncMock(return_value=state)
    )
    monkeypatch.setattr(
        runtime, "get_current_question", lambda *args, **kwargs: question
    )
    prep = SimpleNamespace(
        user_message_metadata={"existing": True}, check_instructions=""
    )
    result = await lesson_checks.prepare_check(
        object(),
        SimpleNamespace(id=1),
        prep,
        evaluation_instructions=custom,
    )
    assert result == 17
    editable = (
        lesson_checks.DEFAULT_EVALUATION_INSTRUCTIONS if custom is None else custom
    )
    assert editable in prep.check_instructions
    if custom is not None:
        assert (
            lesson_checks.DEFAULT_EVALUATION_INSTRUCTIONS not in prep.check_instructions
        )
    assert (
        'The instructor\'s question is: "Explain latency."' in prep.check_instructions
    )
    assert (
        'Private passing criteria: "Connect latency to response time."'
        in prep.check_instructions
    )
    assert "Only when every required criterion is met" in prep.check_instructions
    assert (
        "Keep using the normal say snippets for ElevenLabs speech"
        in prep.check_instructions
    )
    assert "Do not emit followup suggestions" in prep.check_instructions
    assert "Do not mark a request to skip as a pass" in prep.check_instructions
    assert (
        f'{SAY_MARKER_START}check{SAY_MARKER_SEPARATOR}{{"attempt_id":17,"passed":true}}{SAY_MARKER_END}'
        in prep.check_instructions
    )
    assert prep.user_message_metadata == {"existing": True, "check_attempt_id": 17}


@with_user(123)
@with_institution(11, "Test Institution")
@with_authz(
    grants=[("user:123", "can_edit", "assistant:1"), ("user:123", "admin", "class:1")]
)
async def test_evaluation_instructions_persist_without_regenerating_material(
    api, db, institution, valid_user_token, monkeypatch
):
    from pingpong import models
    from pingpong.test_lecture_video_server import (
        create_ready_lecture_video_assistant,
        patch_lecture_video_model_list,
    )

    patch_lecture_video_model_list(monkeypatch)
    async with db.async_session() as session:
        _, video, assistant = await create_ready_lecture_video_assistant(
            session, institution
        )
        assistant.creator_id = 123
        assistant.lecture_gemini_model = "gemini-3.6-flash"
        await session.commit()
        video_id = video.id
    for text in ["Ask a targeted follow-up when needed.", None]:
        response = api.put(
            "/api/v1/class/1/assistant/1",
            json={"lecture_check_instructions": text},
            headers={"Authorization": f"Bearer {valid_user_token}"},
        )
        assert response.status_code == 200, response.text
        assert response.json()["lecture_check_instructions"] == text
        assert response.json()["lecture_video"]["id"] == video_id
        async with db.async_session() as session:
            saved = await session.get(models.Assistant, 1)
            assert saved.lecture_check_instructions == text


@pytest.mark.parametrize("text", ["", "a", "ab"])
def test_evaluation_instructions_use_the_chat_prompt_minimum(text):
    from pydantic import ValidationError
    from pingpong import schemas

    with pytest.raises(ValidationError):
        schemas.UpdateAssistant(lecture_check_instructions=text)
    with pytest.raises(ValidationError):
        schemas.CreateAssistant(
            name="Lesson",
            instructions="Chat prompt",
            description="",
            model="gpt-4o-mini",
            lecture_check_instructions=text,
        )
