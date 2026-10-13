"""Unicode text boundaries shared by speech alignment and caption generation."""

import unicodedata

import regex

_NO_SPACE_SCRIPT = regex.compile(
    r"[\p{Han}\p{Hiragana}\p{Katakana}\p{Thai}\p{Lao}\p{Khmer}\p{Myanmar}。！？]"
)
SENTENCE_ENDINGS = (".", "?", "!", "。", "？", "！", "۔", "…")


def caption_token_spans(text: str) -> list[tuple[int, int]]:
    """Keep spaced words intact; retain grapheme boundaries in unspaced scripts.

    Offsets refer to the original text, so provider character timestamps and
    whitespace can be retained rather than approximated from a passage duration.
    """
    spans: list[tuple[int, int]] = []
    for run in regex.finditer(r"\S+", text):
        if (
            not _NO_SPACE_SCRIPT.search(run.group())
            and caption_display_length(run.group()) <= 84
        ):
            spans.append(run.span())
            continue
        split_long_run = caption_display_length(run.group()) > 84
        pending_start: int | None = None
        pending_end = run.start()
        for cluster in regex.finditer(r"\X", text, pos=run.start(), endpos=run.end()):
            if (
                split_long_run
                or _NO_SPACE_SCRIPT.search(cluster.group())
                or not any(char.isalnum() for char in cluster.group())
            ):
                if pending_start is not None:
                    spans.append((pending_start, pending_end))
                    pending_start = None
                spans.append(cluster.span())
            else:
                if pending_start is None:
                    pending_start = cluster.start()
                pending_end = cluster.end()
        if pending_start is not None:
            spans.append((pending_start, pending_end))
    return spans


def caption_display_length(text: str) -> int:
    """Count wide CJK graphemes as two columns within the caption budget."""
    return sum(
        2 if any(unicodedata.east_asian_width(c) in {"W", "F"} for c in cluster) else 1
        for cluster in regex.findall(r"\X", text)
    )
