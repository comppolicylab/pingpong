import json
import re
from collections.abc import Sequence
from dataclasses import dataclass

from openai.types.shared_params import Reasoning
from pydantic import BaseModel

import pingpong.models as models
from pingpong.ai import get_openai_client_by_class_id
from pingpong.config import config
from pingpong.elevenlabs_config import (
    ElevenLabsComponent,
    pronunciation_cache,
    pronunciation_cache_key,
    profile_for,
    with_pronunciation_cache_entries,
)
from pingpong.schemas import ElevenLabsTTSModel


PRONUNCIATION_MODEL = "gpt-5.6-terra"
_IPA_PATTERN = re.compile(r"/[^/\s]+(?:\s+[^/\s]+)*/")
_EDGE_PUNCTUATION_PATTERN = re.compile(r"^([^\w]*)(.*?)([^\w]*)$")


@dataclass(frozen=True)
class SpeechTextItem:
    item_id: int
    display_text: str
    speech_text: str
    context: str | None = None


@dataclass(frozen=True)
class _PronunciationOccurrence:
    cache_key: str
    written: str
    authored_spoken: str
    part_index: int
    prefix: str
    suffix: str


class _IPAPronunciation(BaseModel):
    key: str
    ipa: str


class _IPAPronunciationBatch(BaseModel):
    pronunciations: list[_IPAPronunciation]


def _quote_inline_ipa(text: str) -> str:
    """Use ElevenLabs v3's documented inline IPA form: ``"/IPA/"``."""

    def replace(match: re.Match[str]) -> str:
        start, end = match.span()
        if start > 0 and end < len(text) and text[start - 1] == text[end] == '"':
            return match.group(0)
        return f'"{match.group(0)}"'

    return _IPA_PATTERN.sub(replace, text)


def _pronunciation_occurrences(
    item: SpeechTextItem,
    *,
    language_code: str | None,
) -> tuple[list[str], list[_PronunciationOccurrence]]:
    display_parts = re.findall(r"\s+|\S+", item.display_text)
    speech_parts = re.findall(r"\s+|\S+", item.speech_text)
    display_words = [part for part in display_parts if not part.isspace()]
    speech_word_indexes = [
        index for index, part in enumerate(speech_parts) if not part.isspace()
    ]
    speech_words = [speech_parts[index] for index in speech_word_indexes]
    if len(display_words) != len(speech_words):
        raise ValueError("Pronunciation display and speech word counts do not match.")

    occurrences: list[_PronunciationOccurrence] = []
    for display_word, speech_word, part_index in zip(
        display_words,
        speech_words,
        speech_word_indexes,
        strict=True,
    ):
        if display_word == speech_word or _IPA_PATTERN.search(speech_word):
            continue

        written = display_word
        authored_spoken = speech_word
        prefix = ""
        suffix = ""
        display_match = _EDGE_PUNCTUATION_PATTERN.fullmatch(display_word)
        speech_match = _EDGE_PUNCTUATION_PATTERN.fullmatch(speech_word)
        if display_match is not None and speech_match is not None:
            display_prefix, display_core, display_suffix = display_match.groups()
            speech_prefix, speech_core, speech_suffix = speech_match.groups()
            if (
                display_prefix == speech_prefix
                and display_suffix == speech_suffix
                and display_core
                and speech_core
            ):
                prefix = speech_prefix
                suffix = speech_suffix
                written = display_core
                authored_spoken = speech_core

        occurrences.append(
            _PronunciationOccurrence(
                cache_key=pronunciation_cache_key(
                    language_code=language_code,
                    written=written,
                    authored_spoken=authored_spoken,
                ),
                written=written,
                authored_spoken=authored_spoken,
                part_index=part_index,
                prefix=prefix,
                suffix=suffix,
            )
        )
    return [_quote_inline_ipa(part) for part in speech_parts], occurrences


def _normalize_ipa(value: str) -> str:
    ipa = value.strip()
    if ipa.startswith('"') and ipa.endswith('"'):
        ipa = ipa[1:-1].strip()
    if ipa.startswith("/") and ipa.endswith("/"):
        ipa = ipa[1:-1].strip()
    if not ipa:
        raise RuntimeError("IPA pronunciation conversion returned an empty value.")
    if "/" in ipa or '"' in ipa or "\n" in ipa or "\r" in ipa:
        raise RuntimeError("IPA pronunciation contains invalid delimiters.")
    return ipa


async def speech_texts_for_elevenlabs(
    *,
    assistant_id: int,
    component: ElevenLabsComponent,
    scope: str,
    language_code: str | None,
    items: Sequence[SpeechTextItem],
) -> dict[int, str]:
    """Prepare every item together, making at most one Terra request."""
    if not items:
        return {}
    if len({item.item_id for item in items}) != len(items):
        raise ValueError("Pronunciation item IDs must be unique.")

    async with config.db.driver.async_session() as session:
        assistant = await models.Assistant.get_by_id(session, assistant_id)
        if (
            assistant is None
            or profile_for(assistant, component).model != ElevenLabsTTSModel.V3
        ):
            return {item.item_id: item.speech_text for item in items}

        prepared_parts: dict[int, list[str]] = {}
        occurrences_by_item: dict[int, list[_PronunciationOccurrence]] = {}
        unresolved: dict[str, dict[str, object]] = {}
        cached_pronunciations = pronunciation_cache(assistant.elevenlabs_config)

        for item in items:
            speech_parts, occurrences = _pronunciation_occurrences(
                item,
                language_code=language_code,
            )
            prepared_parts[item.item_id] = speech_parts
            occurrences_by_item[item.item_id] = occurrences
            for occurrence in occurrences:
                if occurrence.cache_key in cached_pronunciations:
                    continue
                entry = unresolved.setdefault(
                    occurrence.cache_key,
                    {
                        "key": occurrence.cache_key,
                        "written": occurrence.written,
                        "authored_spoken": occurrence.authored_spoken,
                        "contexts": [],
                    },
                )
                contexts = entry["contexts"]
                assert isinstance(contexts, list)
                context = item.context or item.display_text
                if context not in contexts:
                    contexts.append(context)

        if unresolved:
            openai_client = await get_openai_client_by_class_id(
                session, assistant.class_id
            )
            response = await openai_client.responses.parse(
                model=PRONUNCIATION_MODEL,
                reasoning=Reasoning(effort="low", summary=None),
                instructions=(
                    "Convert every authored pronunciation spelling to IPA for "
                    "ElevenLabs v3. Use each item's written form, authored spoken "
                    "spelling, language, and contexts to infer the intended "
                    "pronunciation. Return exactly one result for every supplied key. "
                    "Return only the IPA pronunciation in `ipa`, without slash "
                    "delimiters, surrounding words, commentary, or line breaks."
                ),
                input=json.dumps(
                    {
                        "version": 1,
                        "language_code": language_code,
                        "scope": scope,
                        "items": list(unresolved.values()),
                    },
                    ensure_ascii=False,
                ),
                text_format=_IPAPronunciationBatch,
                store=False,
            )
            parsed = response.output_parsed
            if parsed is None:
                raise RuntimeError("IPA pronunciation conversion returned no results.")
            returned: dict[str, str] = {}
            for pronunciation in parsed.pronunciations:
                if pronunciation.key in returned:
                    raise RuntimeError(
                        "IPA pronunciation conversion returned a duplicate key."
                    )
                returned[pronunciation.key] = _normalize_ipa(pronunciation.ipa)
            if set(returned) != set(unresolved):
                raise RuntimeError(
                    "IPA pronunciation conversion did not return every requested key."
                )

            await session.refresh(assistant)
            assistant.elevenlabs_config = with_pronunciation_cache_entries(
                assistant.elevenlabs_config,
                entries=returned,
            )
            session.add(assistant)
            await session.commit()
            cached_pronunciations.update(returned)

        prepared: dict[int, str] = {}
        for item in items:
            parts = prepared_parts[item.item_id]
            for occurrence in occurrences_by_item[item.item_id]:
                ipa = cached_pronunciations.get(occurrence.cache_key)
                if ipa is None:
                    raise RuntimeError("IPA pronunciation is missing from the cache.")
                parts[occurrence.part_index] = (
                    f'{occurrence.prefix}"/{ipa}/"{occurrence.suffix}'
                )
            prepared[item.item_id] = "".join(parts)
        return prepared
