import logging

from pingpong.followup_transform import (
    FollowupTransformer,
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


def say_payload(payload: str) -> str:
    return f"{SAY_MARKER_START}say{SAY_MARKER_SEPARATOR}{payload}{SAY_MARKER_END}"


def test_strip_followup_snippets_removes_private_payload():
    text = "Done. " + followup_payload('{"responses":["Explain more."]}')

    assert strip_followup_snippets(text) == "Done. "


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


def test_followup_transformer_buffers_split_deltas_and_preserves_say_snippets():
    transformer = FollowupTransformer()
    snippet = followup_payload('{"responses":["What happens next?"]}')
    say_snippet = say_payload('{"speech":"x squared","display":"$ x^2 $"}')

    assert transformer.add("Use " + say_snippet + " " + snippet[:12]) == (
        "Use " + say_snippet + " "
    )
    assert transformer.add(snippet[12:25]) == ""
    assert transformer.add(snippet[25:] + ".") == "."
    assert transformer.flush() == ""
    assert transformer.suggestions == ["What happens next?"]


def test_followup_transformer_drops_malformed_json(caplog):
    text = "Before " + followup_payload('{"responses":') + " after"

    with caplog.at_level(logging.DEBUG, logger="pingpong.followup_transform"):
        assert strip_followup_snippets(text) == "Before  after"

    assert "Dropping malformed followups snippet with invalid JSON" in caplog.text


def test_followup_transformer_drops_incomplete_followup_on_flush(caplog):
    transformer = FollowupTransformer()

    assert transformer.add('Before \ue200followups\ue202{"responses"') == "Before "
    with caplog.at_level(logging.WARNING, logger="pingpong.followup_transform"):
        assert transformer.flush() == ""

    assert "Dropping incomplete followups snippet buffer" in caplog.text
