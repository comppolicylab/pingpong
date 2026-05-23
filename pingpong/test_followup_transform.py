import logging

from pingpong.followup_transform import (
    extract_followup_suggestions,
    strip_followup_snippets,
)
from pingpong.say_transform import (
    SAY_MARKER_END,
    SAY_MARKER_SEPARATOR,
    SAY_MARKER_START,
)


def followup_payload(payload: str) -> str:
    return f"{SAY_MARKER_START}followups{SAY_MARKER_SEPARATOR}{payload}{SAY_MARKER_END}"


def say_payload(speech: str, body: str) -> str:
    return (
        f"{SAY_MARKER_START}say{SAY_MARKER_SEPARATOR}"
        f'{{"speech":"{speech}","content":"{body}"}}{SAY_MARKER_END}'
    )


def test_strip_followup_snippets_removes_private_payload():
    text = "Done. " + followup_payload('{"responses":["Explain more."]}')

    assert strip_followup_snippets(text) == "Done. "


def test_strip_followup_snippets_preserves_say_snippets():
    say = say_payload("x squared", "$ x^2 $")
    text = "Use " + say + " then " + followup_payload('{"responses":["More?"]}')

    assert strip_followup_snippets(text) == "Use " + say + " then "


def test_extract_followup_suggestions_caps_trims_and_dedupes():
    text = followup_payload(
        '{"responses":[" Explain more. ","Show an example.","Explain more.",'
        '"Quiz me.","Extra ignored."]}'
    )

    assert extract_followup_suggestions(text) == [
        "Explain more.",
        "Show an example.",
        "Quiz me.",
    ]


def test_extract_followup_suggestions_drops_malformed_json(caplog):
    text = "Before " + followup_payload('{"responses":') + " after"

    with caplog.at_level(logging.DEBUG, logger="pingpong.say_transform"):
        assert extract_followup_suggestions(text) == []

    assert "Dropping malformed followups snippet with invalid JSON" in caplog.text


def test_strip_followup_snippets_drops_incomplete_followup_marker():
    text = f'Before {SAY_MARKER_START}followups{SAY_MARKER_SEPARATOR}{{"responses"'

    assert strip_followup_snippets(text) == "Before "


def test_strip_followup_snippets_drops_truncated_followup_marker_prefix():
    text = f"Before {SAY_MARKER_START}follow"

    assert strip_followup_snippets(text) == "Before "
