from pingpong.ai import format_instructions
from pingpong.say_transform import (
    SAY_MARKER_END,
    SAY_MARKER_SEPARATOR,
    SAY_MARKER_START,
    SayTransformer,
    transform_say_text,
)


def say_payload(payload: str) -> str:
    return f"{SAY_MARKER_START}say{SAY_MARKER_SEPARATOR}{payload}{SAY_MARKER_END}"


def test_format_instructions_adds_say_contract_for_latex_lecture_video_only():
    instructions = format_instructions(
        "Be helpful.",
        use_latex=True,
        lecture_video_mode=True,
    )

    assert "---Formatting: LaTeX---" in instructions
    assert "---Lecture Video: Spoken and Written Output---" in instructions
    assert "overrides the general LaTeX formatting rule" in instructions
    assert "MUST be emitted as a private-use `say`" in instructions
    assert "Do not output raw $...$ or $$...$$ math directly" in instructions
    assert "Incorrect: They have written $ 10a + 5c $" in instructions
    assert '"speech":"ten a plus five c"' in instructions
    assert "Incorrect: One has $a$, the other has $c$." in instructions
    assert '"speech":"a","display":"$a$"' in instructions
    assert '"speech"' in instructions
    assert '"display"' in instructions


def test_format_instructions_does_not_add_say_contract_for_normal_latex_chat():
    instructions = format_instructions(
        "Be helpful.",
        use_latex=True,
        lecture_video_mode=False,
    )

    assert "---Formatting: LaTeX---" in instructions
    assert "---Lecture Video: Spoken and Written Output---" not in instructions


def test_format_instructions_does_not_add_say_contract_without_latex():
    instructions = format_instructions(
        "Be helpful.",
        use_latex=False,
        lecture_video_mode=True,
    )

    assert "---Formatting: LaTeX---" not in instructions
    assert "---Lecture Video: Spoken and Written Output---" not in instructions


def test_transform_say_text_returns_display_string():
    text = "Use " + say_payload('{"speech":"x squared","display":"$ x^2 $"}') + " here."

    assert transform_say_text(text, "display") == "Use $ x^2 $ here."


def test_transform_say_text_returns_speech_string():
    text = "Use " + say_payload('{"speech":"x squared","display":"$ x^2 $"}') + " here."

    assert transform_say_text(text, "speech") == "Use x squared here."


def test_say_transformer_buffers_split_deltas():
    transformer = SayTransformer("display")
    snippet = say_payload('{"speech":"alpha","display":"α"}')

    assert transformer.add("Greek " + snippet[:8]) == "Greek "
    assert transformer.add(snippet[8:20]) == ""
    assert transformer.add(snippet[20:] + ".") == "α."
    assert transformer.flush() == ""


def test_say_transformer_suppresses_malformed_json():
    text = "Before " + say_payload('{"speech":') + " after"

    assert transform_say_text(text, "display") == "Before  after"


def test_say_transformer_suppresses_non_string_display():
    text = (
        "Before "
        + say_payload('{"speech":"x squared","display":{"type":"math_inline"}}')
        + " after"
    )

    assert transform_say_text(text, "display") == "Before  after"


def test_say_transformer_suppresses_incomplete_snippet_on_flush():
    transformer = SayTransformer("display")

    assert transformer.add('Before \ue200say\ue202{"speech":"x"') == "Before "
    assert transformer.flush() == ""
