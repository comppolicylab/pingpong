"""Repair captions against existing narration audio without regenerating speech."""

import io
from types import SimpleNamespace
from typing import Any

from sqlalchemy import String, cast, func, select, update
from sqlalchemy.orm import selectinload

from pingpong import models, schemas
from pingpong.config import config
from pingpong.elevenlabs import _timing_words_from_alignment, get_elevenlabs_client
from pingpong.lecture_slide_processing import (
    _display_word_timings,
    _get_elevenlabs_api_key,
    generate_slide_caption_store_key,
)
from pingpong.lecture_video_service import lecture_video_words_to_webvtt


async def repair_lecture_slide_captions(
    deck_id: int, language: str = "original", *, apply: bool = False
) -> int:
    """Return page count; dry runs do not call ElevenLabs or write artifacts.

    Applying uses paid forced alignment with the existing class credential.
    Keep the previous caption artifact so rollback does not affect shared users.
    """
    async with config.db.driver.async_session() as session:
        deck = await session.get(
            models.LectureSlideDeck,
            deck_id,
        )
        if deck is None:
            raise ValueError("Lecture slide deck not found.")
        if deck.status != schemas.LectureSlideDeckStatus.READY:
            raise ValueError("Only ready decks can have captions repaired.")
        ready_status: (
            schemas.LectureSlideDeckStatus | schemas.LectureSlideTranslationStatus
        )
        if language == "original":
            owner = deck
            page_type = models.LectureSlidePage
            pages = list(
                await session.scalars(
                    select(page_type)
                    .where(page_type.lecture_slide_deck_id == deck_id)
                    .options(
                        selectinload(page_type.narration).selectinload(
                            models.LectureSlideNarration.stored_object
                        )
                    )
                    .order_by(page_type.position)
                )
            )
            ready_status = schemas.LectureSlideDeckStatus.READY
        else:
            owner = await session.scalar(
                select(models.LectureSlideTranslation).where(
                    models.LectureSlideTranslation.lecture_slide_deck_id == deck_id,
                    models.LectureSlideTranslation.language_code == language,
                )
            )
            if (
                owner is None
                or owner.status != schemas.LectureSlideTranslationStatus.READY
            ):
                raise ValueError("A ready translation is required.")
            page_type = models.LectureSlideTranslationPage
            pages = list(
                await session.scalars(
                    select(page_type)
                    .where(page_type.translation_id == owner.id)
                    .options(selectinload(page_type.narration_stored_object))
                    .order_by(page_type.position)
                )
            )
            ready_status = schemas.LectureSlideTranslationStatus.READY
        snapshots = []
        for page in pages:
            text = page.narration_text or ""
            if not text.strip():
                continue
            stored = (
                (page.narration.stored_object if page.narration else None)
                if language == "original"
                else page.narration_stored_object
            )
            if (
                stored is None
                or page.start_offset_ms is None
                or page.end_offset_ms is None
            ):
                raise ValueError(
                    f"Page {page.position} is missing audio or timeline offsets."
                )
            raw_updated = await session.scalar(
                select(cast(page_type.updated, String)).where(page_type.id == page.id)
            )
            snapshots.append(
                (page, stored, text, page.narration_tts_text or text, raw_updated)
            )
        if not snapshots:
            raise ValueError("No narrated pages to repair.")
        if not apply:
            return len(snapshots)
        if not config.lecture_video_audio_store or not config.video_store:
            raise RuntimeError("Audio and video stores must be configured.")
        owner_updated = await session.scalar(
            select(cast(type(owner).updated, String)).where(type(owner).id == owner.id)
        )
        previous_caption_id = owner.caption_stored_object_id
        client = get_elevenlabs_client(await _get_elevenlabs_api_key(deck.class_id))
        transcript = []
        page_timings = []
        for page, stored, display_text, speech_text, updated_at in snapshots:
            audio = io.BytesIO()
            async for chunk in config.lecture_video_audio_store.store.get_file(
                stored.key
            ):
                audio.write(chunk)
            audio.seek(0)
            aligned = await client.forced_alignment.create(
                file=("narration.audio", audio, stored.content_type),
                text=speech_text,
                request_options={"timeout_in_seconds": 120},
            )
            if "".join(char.text for char in aligned.characters) != speech_text:
                raise ValueError(f"Alignment changed text for page {page.position}.")
            timings = _display_word_timings(
                _timing_words_from_alignment(
                    SimpleNamespace(
                        characters=[char.text for char in aligned.characters],
                        character_start_times_seconds=[
                            char.start for char in aligned.characters
                        ],
                        character_end_times_seconds=[
                            char.end for char in aligned.characters
                        ],
                    )
                ),
                display_text=display_text,
                speech_text=speech_text,
            )
            if (
                not timings
                or timings[-1].end_ms > page.end_offset_ms - page.start_offset_ms + 250
            ):
                raise ValueError(
                    f"Invalid alignment duration for page {page.position}."
                )
            page_timings.append((page, updated_at, timings))
            for i, word in enumerate(timings):
                start = min(page.end_offset_ms, page.start_offset_ms + word.start_ms)
                end = min(page.end_offset_ms, page.start_offset_ms + word.end_ms)
                transcript.append(
                    schemas.LectureVideoManifestWordV3(
                        id=f"slide-{page.position}-word-{i}",
                        word=word.word,
                        start_offset_ms=start,
                        end_offset_ms=max(start, end),
                        join_left=word.join_left,
                    )
                )
        caption = lecture_video_words_to_webvtt(
            transcript,
            question_stop_offsets_ms=[page.end_offset_ms for page, *_ in snapshots],
        ).encode("utf-8")
        key = generate_slide_caption_store_key()
        await config.video_store.store.put(key, io.BytesIO(caption), "text/vtt")
        try:
            artifact = models.LectureSlideCaptionStoredObject(
                key=key, content_type="text/vtt", content_length=len(caption)
            )
            session.add(artifact)
            await session.flush()
            for page, updated_at, timings in page_timings:
                # Abort the whole repair if the lesson changed while aligning.
                values: dict[str, Any] = {"updated": func.now()}
                if language != "original":
                    values["word_timings"] = [
                        {
                            "word": word.word,
                            "start_ms": word.start_ms,
                            "end_ms": word.end_ms,
                            **({"join_left": True} if word.join_left else {}),
                        }
                        for word in timings
                    ]
                result = await session.execute(
                    update(page_type)
                    .where(
                        page_type.id == page.id,
                        cast(page_type.updated, String) == updated_at,
                        page_type.narration_text == page.narration_text,
                        page_type.narration_tts_text == page.narration_tts_text,
                        page_type.start_offset_ms == page.start_offset_ms,
                        page_type.end_offset_ms == page.end_offset_ms,
                    )
                    .values(**values)
                )
                if result.rowcount != 1:
                    raise RuntimeError("Lesson changed during caption repair; retry.")
            owner_type = type(owner)
            owner_values: dict[str, Any] = {"caption_stored_object_id": artifact.id}
            result = await session.execute(
                update(owner_type)
                .where(
                    owner_type.id == owner.id,
                    cast(owner_type.updated, String) == owner_updated,
                    owner_type.status == ready_status,
                    owner_type.caption_stored_object_id == previous_caption_id,
                )
                .values(**owner_values)
            )
            if result.rowcount != 1:
                raise RuntimeError("Lesson changed during caption repair; retry.")
            await session.commit()
        except BaseException:
            await session.rollback()
            await config.video_store.store.delete(key)
            raise
        return len(snapshots)
