import importlib

from pingpong import models, schemas

server_module = importlib.import_module("pingpong.server")


def test_build_run_instructions_for_lecture_video_with_latex_includes_say_and_followups():
    thread = models.Thread(
        id=42,
        interaction_mode=schemas.InteractionMode.LECTURE_VIDEO,
        instructions=None,
    )
    assistant = models.Assistant(
        instructions="Be helpful.",
        use_latex=True,
        use_image_descriptions=False,
        disable_prompt_randomization=True,
    )

    instructions = server_module._build_run_instructions(thread, assistant, user_id=1)

    assert instructions is not None
    assert "Be helpful." in instructions
    assert "---Formatting: Lecture Video LaTeX---" in instructions
    assert "---Formatting: LaTeX---" not in instructions
    assert "---Formatting: Lecture Video Follow-ups---" in instructions


def test_build_run_instructions_for_lecture_video_without_latex_skips_say_contract():
    thread = models.Thread(
        id=42,
        interaction_mode=schemas.InteractionMode.LECTURE_VIDEO,
        instructions=None,
    )
    assistant = models.Assistant(
        instructions="Be helpful.",
        use_latex=False,
        use_image_descriptions=False,
        disable_prompt_randomization=True,
    )

    instructions = server_module._build_run_instructions(thread, assistant, user_id=1)

    assert instructions is not None
    assert "Be helpful." in instructions
    assert "---Formatting: Lecture Video LaTeX---" not in instructions
    assert "---Formatting: LaTeX---" not in instructions


def test_build_run_instructions_for_non_lecture_video_uses_stored_instructions():
    thread = models.Thread(
        id=43,
        interaction_mode=schemas.InteractionMode.CHAT,
        instructions="Stored chat instructions.",
    )
    assistant = models.Assistant(
        instructions="Different assistant instructions.",
        use_latex=True,
        use_image_descriptions=False,
        disable_prompt_randomization=True,
    )

    instructions = server_module._build_run_instructions(thread, assistant, user_id=1)

    assert instructions == "Stored chat instructions."
