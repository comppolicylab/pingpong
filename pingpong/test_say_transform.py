import json
import logging

from pingpong.ai import format_instructions
from pingpong.say_transform import (
    PuaStreamTransformer,
    SAY_MARKER_END,
    SAY_MARKER_SEPARATOR,
    SAY_MARKER_START,
    transform_say_text,
)


def snippet(marker: str, speech: str, body: str | None = None) -> str:
    payload = {"speech": speech}
    if body is not None:
        payload["content"] = body
    return (
        f"{SAY_MARKER_START}{marker}{SAY_MARKER_SEPARATOR}"
        f"{json.dumps(payload, separators=(',', ':'))}{SAY_MARKER_END}"
    )


def followup_snippet(payload: str) -> str:
    return f"{SAY_MARKER_START}followups{SAY_MARKER_SEPARATOR}{payload}{SAY_MARKER_END}"


def test_format_instructions_adds_snippet_contract_for_lecture_video_latex_only():
    instructions = format_instructions(
        "Be helpful.",
        use_latex=True,
        lecture_video_mode=True,
    )

    assert (
        "---Formatting: Lecture Video Dual Speech/Display Snippets---" in instructions
    )
    assert "---Formatting: LaTeX---" not in instructions
    assert "MUST emit that part as a private-use snippet" in instructions
    assert "JSON object with `speech` and `content` string keys" in instructions
    assert "The snippet payload must be valid JSON" in instructions
    assert "write LaTeX backslashes in `content` as `\\\\`" in instructions
    assert "`\\\\frac`, not `\\frac`" in instructions
    assert "For block-level math, use double dollar signs $$" in instructions
    assert "Do not output raw $...$ or $$...$$ math directly" in instructions
    assert "Incorrect: They have written $ 10a + 5c $" in instructions
    assert (
        f"{SAY_MARKER_START}say{SAY_MARKER_SEPARATOR}"
        '{"speech":"ten a plus five c","content":"$ 10a + 5c $"}'
        f"{SAY_MARKER_END}"
    ) in instructions
    assert "Incorrect: One has $a$, the other has $c$." in instructions
    assert (
        f"{SAY_MARKER_START}say{SAY_MARKER_SEPARATOR}"
        '{"speech":"a","content":"$a$"}'
        f"{SAY_MARKER_END}"
    ) in instructions
    assert "Correct Mermaid diagram:" in instructions
    assert (
        f"{SAY_MARKER_START}mermaid{SAY_MARKER_SEPARATOR}"
        '{"speech":"Here is a simple flow'
    ) in instructions
    assert "Correct SVG diagram:" in instructions
    assert (
        f"{SAY_MARKER_START}svg{SAY_MARKER_SEPARATOR}"
        '{"speech":"Here is a simple yellow circle.'
    ) in instructions
    assert "---Formatting: Lecture Video Follow-ups---" in instructions
    assert f"{SAY_MARKER_START}followups{SAY_MARKER_SEPARATOR}" in instructions
    assert '"responses"' in instructions


def test_format_instructions_does_not_add_snippet_contract_for_normal_latex_chat():
    instructions = format_instructions(
        "Be helpful.",
        use_latex=True,
        lecture_video_mode=False,
    )

    assert "---Formatting: LaTeX---" in instructions
    assert (
        "---Formatting: Lecture Video Dual Speech/Display Snippets---"
        not in instructions
    )
    assert "---Formatting: Lecture Video Follow-ups---" not in instructions


def test_format_instructions_does_not_add_snippet_contract_without_latex():
    instructions = format_instructions(
        "Be helpful.",
        use_latex=False,
        lecture_video_mode=True,
    )

    assert "---Formatting: LaTeX---" not in instructions
    assert (
        "---Formatting: Lecture Video Dual Speech/Display Snippets---"
        not in instructions
    )
    assert "---Formatting: Lecture Video Follow-ups---" in instructions


def test_transform_returns_body_for_display():
    text = "Use " + snippet("say", "x squared", "$ x^2 $") + " here."

    assert transform_say_text(text, "display") == "Use $ x^2 $ here."


def test_transform_decodes_json_escapes_in_content_without_latex_heuristics():
    text = (
        f"Use {SAY_MARKER_START}say{SAY_MARKER_SEPARATOR}"
        '{"speech":"x times x","content":"$ x \\times x $"}'
        f"{SAY_MARKER_END} here."
    )

    assert transform_say_text(text, "display") == "Use $ x " + "\t" + "imes x $ here."
    assert transform_say_text(text, "speech") == "Use x times x here."


def test_transform_preserves_json_escaped_latex_commands_in_content():
    text = (
        f"{SAY_MARKER_START}say{SAY_MARKER_SEPARATOR}"
        '{"speech":"the expression",'
        '"content":"$ \\\\frac{\\\\beta}{\\\\nu} + \\\\nabla f + '
        '\\\\rangle + \\\\rightarrow $"}'
        f"{SAY_MARKER_END}"
    )

    assert (
        transform_say_text(text, "display")
        == "$ \\frac{\\beta}{\\nu} + \\nabla f + \\rangle + \\rightarrow $"
    )


def test_transform_leaves_invalid_content_escape_literal():
    text = (
        f"{SAY_MARKER_START}say{SAY_MARKER_SEPARATOR}"
        '{"speech":"alpha","content":"$ \\alpha $"}'
        f"{SAY_MARKER_END}"
    )

    assert transform_say_text(text, "display") == "$ \\alpha $"


def test_transform_still_decodes_escaped_newlines_in_content():
    text = (
        f"{SAY_MARKER_START}mermaid{SAY_MARKER_SEPARATOR}"
        '{"speech":"A flow.","content":"```mermaid\\ngraph TD\\n  A-->B\\n```"}'
        f"{SAY_MARKER_END}"
    )

    assert transform_say_text(text, "display") == "```mermaid\ngraph TD\n  A-->B\n```"


def test_transform_decodes_json_newline_before_letter():
    text = (
        f"{SAY_MARKER_START}say{SAY_MARKER_SEPARATOR}"
        '{"speech":"two lines","content":"first\\nuser input"}'
        f"{SAY_MARKER_END}"
    )

    assert transform_say_text(text, "display") == "first\nuser input"


def test_transform_returns_speech_for_speech_target():
    text = "Use " + snippet("say", "x squared", "$ x^2 $") + " here."

    assert transform_say_text(text, "speech") == "Use x squared here."


def test_transform_falls_back_to_speech_for_single_line_snippet():
    text = "Use " + snippet("say", "alpha") + " here."

    assert transform_say_text(text, "display") == "Use alpha here."
    assert transform_say_text(text, "speech") == "Use alpha here."


def test_transform_can_wrap_svg_block_for_dual_display_and_speech():
    svg_block = (
        "```svg\n"
        "<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 100 100'>\n"
        "  <circle cx='50' cy='50' r='40' fill='gold'/>\n"
        "</svg>\n"
        "```"
    )
    text = "Here: " + snippet("svg", "Here is a simple yellow circle.", svg_block)

    assert transform_say_text(text, "display") == "Here: " + svg_block
    assert transform_say_text(text, "speech") == "Here: Here is a simple yellow circle."


def test_display_streams_body_chars_immediately():
    """The whole point of the redesign: body chars come out as they arrive."""
    transformer = PuaStreamTransformer("display")
    full = snippet(
        "mermaid",
        "A simple flow.",
        "```mermaid\ngraph TD\n  A-->B\n```",
    )
    emitted: list[str] = []
    for ch in full:
        chunk = transformer.add(ch)
        if chunk:
            emitted.append(chunk)
    emitted.append(transformer.flush())

    body = "```mermaid\ngraph TD\n  A-->B\n```"
    assert "".join(emitted) == body
    assert len([e for e in emitted if e]) > 1


def test_display_transformer_streams_svg_body_then_drops_followups():
    """A mixed stream containing svg followed by followups behaves correctly."""
    transformer = PuaStreamTransformer("display")
    body = "```svg\n<svg viewBox='0 0 10 10'></svg>\n```"
    full = snippet("svg", "A simple circle.", body) + followup_snippet(
        '{"responses":["Try a smaller example."]}'
    )

    emitted: list[str] = []
    for ch in full:
        delta = transformer.add(ch)
        if delta:
            emitted.append(delta)
    emitted.append(transformer.flush())

    assert "".join(emitted) == body
    assert len([e for e in emitted if e]) > 1
    assert transformer.consume_followup_suggestions() == ["Try a smaller example."]


def test_display_transformer_strips_followup_snippets_and_collects_suggestions():
    transformer = PuaStreamTransformer("display")
    payload = followup_snippet('{"responses":["Try a smaller example."]}')

    out = ""
    for ch in "before " + payload + " after":
        out += transformer.add(ch)
    out += transformer.flush()

    assert out == "before  after"
    assert transformer.consume_followup_suggestions() == ["Try a smaller example."]


def test_speech_transformer_streams_speech_and_flushes_for_diagrams():
    transformer = PuaStreamTransformer("speech")
    full = snippet("svg", "A simple circle.", "```svg\n<svg/>\n```")

    emitted: list[str] = []
    flushes = 0
    for ch in full:
        delta = transformer.add(ch)
        if delta:
            emitted.append(delta)
        flushes += transformer.consume_flush_signals()
    emitted.append(transformer.flush())

    assert "".join(emitted) == "A simple circle."
    assert len([e for e in emitted if e]) >= len("A simple circle.")
    assert flushes == 1


def test_speech_transformer_drops_followup_snippets():
    transformer = PuaStreamTransformer("speech")
    payload = followup_snippet('{"responses":["Try a smaller example."]}')

    out = ""
    flushes = 0
    for ch in "before " + payload + " after":
        out += transformer.add(ch)
        flushes += transformer.consume_flush_signals()
    out += transformer.flush()

    assert out == "before  after"
    assert flushes == 1


def test_speech_streams_chars_immediately():
    transformer = PuaStreamTransformer("speech")
    full = snippet("say", "ten a plus five c", "$ 10a + 5c $")
    emitted: list[str] = []
    for ch in full:
        chunk = transformer.add(ch)
        if chunk:
            emitted.append(chunk)
    emitted.append(transformer.flush())

    assert "".join(emitted) == "ten a plus five c"
    assert len([e for e in emitted if e]) >= len("ten a plus five c")


def test_flush_signal_fires_for_mermaid_at_speech_to_body_transition():
    transformer = PuaStreamTransformer("speech")
    full = snippet("mermaid", "A flow.", "```mermaid\ngraph TD\n  A-->B\n```")

    flushes_before_body = 0
    content_marker = ',"content":"'
    pre_content, _, rest = full.partition(content_marker)
    transformer.add(pre_content)
    flushes_before_body += transformer.consume_flush_signals()
    assert flushes_before_body == 0

    transformer.add(content_marker)
    assert transformer.consume_flush_signals() == 1

    transformer.add(rest)
    assert transformer.consume_flush_signals() == 0


def test_flush_signal_fires_for_svg():
    transformer = PuaStreamTransformer("speech")
    transformer.add(snippet("svg", "A circle.", "```svg\n<svg/>\n```"))
    assert transformer.consume_flush_signals() == 1


def test_flush_signal_does_not_fire_for_say():
    transformer = PuaStreamTransformer("speech")
    transformer.add(snippet("say", "x squared", "$ x^2 $"))
    assert transformer.consume_flush_signals() == 0


def test_flush_signal_does_not_fire_for_single_line_snippet():
    transformer = PuaStreamTransformer("speech")
    transformer.add(snippet("mermaid", "A flow."))
    assert transformer.consume_flush_signals() == 0


def test_pua_transformer_buffers_split_deltas():
    transformer = PuaStreamTransformer("display")
    full = snippet("say", "alpha", "$\\alpha$")

    pieces = [full[:5], full[5:12], full[12:]]
    out = "".join(transformer.add(p) for p in pieces) + transformer.flush()
    assert out == "$\\alpha$"


def test_pua_transformer_drops_unknown_markers():
    transformer = PuaStreamTransformer("display")
    payload = (
        f"{SAY_MARKER_START}unknown{SAY_MARKER_SEPARATOR}arbitrary content"
        f"{SAY_MARKER_END}"
    )
    text = "before " + payload + " after"

    out = transformer.add(text) + transformer.flush()
    assert out == "before  after"


def test_pua_transformer_drops_malformed_snippet_but_keeps_followups_afterward():
    transformer = PuaStreamTransformer("display")
    assert (
        transformer.add(
            f'{SAY_MARKER_START}say{SAY_MARKER_SEPARATOR}{{"speech":"x","extra":99}}'
        )
        == ""
    )
    assert (
        transformer.add(
            f"{SAY_MARKER_START}followups{SAY_MARKER_SEPARATOR}"
            '{"responses":["Try X"]}'
            f"{SAY_MARKER_END} next sentence"
        )
        == " next sentence"
    )
    assert transformer.consume_followup_suggestions() == ["Try X"]


def test_pua_transformer_keeps_followups_after_malformed_snippet_in_same_delta():
    transformer = PuaStreamTransformer("display")
    text = (
        f"{SAY_MARKER_START}say{SAY_MARKER_SEPARATOR}x"
        f"{SAY_MARKER_START}followups{SAY_MARKER_SEPARATOR}"
        '{"responses":["Try X"]}'
        f"{SAY_MARKER_END} next sentence"
    )

    assert transformer.add(text) + transformer.flush() == " next sentence"
    assert transformer.consume_followup_suggestions() == ["Try X"]


def test_pua_transformer_drops_invalid_snippet_in_speech_phase_on_flush(caplog):
    transformer = PuaStreamTransformer("display")
    text = (
        f'Before {SAY_MARKER_START}say{SAY_MARKER_SEPARATOR}{{"speech":"partial speech"'
    )
    assert transformer.add(text) == "Before "
    with caplog.at_level(logging.WARNING, logger="pingpong.say_transform"):
        assert transformer.flush() == "partial speech"
    assert "Flushing incomplete snippet JSON" in caplog.text


def test_pua_transformer_discards_malformed_snippet_across_split_deltas():
    transformer = PuaStreamTransformer("display")
    assert (
        transformer.add(f"Before {SAY_MARKER_START}say{SAY_MARKER_SEPARATOR}x")
        == "Before "
    )
    assert transformer.add(f" squared\n$ x^2 ${SAY_MARKER_END} after") == " after"
    assert transformer.flush() == ""


def test_display_speech_fallback_overflow_does_not_leak_before_content(caplog):
    transformer = PuaStreamTransformer("display", max_speech_buffer_chars=4)
    text = (
        f"{SAY_MARKER_START}say{SAY_MARKER_SEPARATOR}"
        '{"speech":"spoken words","content":"$ x $"}'
        f"{SAY_MARKER_END}"
    )

    with caplog.at_level(logging.WARNING, logger="pingpong.say_transform"):
        assert transformer.add(text) + transformer.flush() == "$ x $"

    assert "Speech fallback buffer exceeded cap; dropping fallback" in caplog.text


def test_display_drops_non_string_content_instead_of_falling_back_to_speech():
    text = (
        f"{SAY_MARKER_START}say{SAY_MARKER_SEPARATOR}"
        '{"speech":"x","content":null}'
        f"{SAY_MARKER_END}"
    )

    assert transform_say_text(text, "display") == ""


def test_display_keeps_empty_content_instead_of_falling_back_to_speech():
    text = snippet("say", "hello", "")

    assert transform_say_text(text, "display") == ""
    assert transform_say_text(text, "speech") == "hello"


def test_content_first_diagram_flushes_after_speech_not_before():
    transformer = PuaStreamTransformer("speech")
    text = (
        f"{SAY_MARKER_START}mermaid{SAY_MARKER_SEPARATOR}"
        '{"content":"```mermaid\\ngraph TD\\n  A-->B\\n```","speech":"A flow."}'
        f"{SAY_MARKER_END}"
    )
    flushes_by_delta: list[int] = []
    emitted = ""
    for ch in text:
        emitted += transformer.add(ch)
        flushes_by_delta.append(transformer.consume_flush_signals())

    assert emitted == "A flow."
    assert sum(flushes_by_delta) == 1
    first_flush_index = next(i for i, flushes in enumerate(flushes_by_delta) if flushes)
    assert first_flush_index > text.index('"speech"')


def test_embedded_end_marker_inside_json_string_recovers_downstream_text():
    transformer = PuaStreamTransformer("display")
    text = (
        f"{SAY_MARKER_START}say{SAY_MARKER_SEPARATOR}"
        f'{{"speech":"hello","content":"x{SAY_MARKER_END}y"}}'
        f"{SAY_MARKER_END} more text"
    )

    assert transformer.add(text) + transformer.flush() == "x more text"


def test_pua_transformer_emits_oversized_marker_buffer(caplog):
    transformer = PuaStreamTransformer("display", max_marker_chars=4)

    with caplog.at_level(logging.WARNING, logger="pingpong.say_transform"):
        out = transformer.add(f"Before {SAY_MARKER_START}toolongmarker")

    assert out.startswith("Before ")
    assert "oversized marker name buffer" in caplog.text


def test_pua_transformer_drops_incomplete_followup_payload_on_flush(caplog):
    transformer = PuaStreamTransformer("display")
    text = f'Before {SAY_MARKER_START}followups{SAY_MARKER_SEPARATOR}{{"responses"'
    assert transformer.add(text) == "Before "
    with caplog.at_level(logging.WARNING, logger="pingpong.say_transform"):
        assert transformer.flush() == ""
    assert "Dropping incomplete followups snippet buffer" in caplog.text
    assert transformer.consume_followup_suggestions() == []
