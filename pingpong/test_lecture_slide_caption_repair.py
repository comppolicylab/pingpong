from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select

from pingpong import lecture_slide_caption_repair as repair, models, schemas

pytestmark = pytest.mark.asyncio


async def make_lesson(db, language):
    text = "この講義では人工知能の仕組みについて説明します。" * 12
    async with db.async_session() as session:
        deck = models.LectureSlideDeck(
            id=1,
            class_id=1,
            source_stored_object_id=1,
            display_name="Test",
            slide_count=1,
            status=schemas.LectureSlideDeckStatus.READY,
            transcript_data={
                "version": 4,
                "word_level_transcription": [{"id": "keep-me"}],
            },
        )
        audio = models.LectureSlideNarrationStoredObject(
            key="audio", content_type="audio/ogg", duration_ms=len(text) * 100
        )
        old_caption = models.LectureSlideCaptionStoredObject(
            key="old.vtt", content_type="text/vtt", content_length=1
        )
        session.add_all([deck, audio, old_caption])
        await session.flush()
        if language == "original":
            deck.caption_stored_object_id = old_caption.id
            narration = models.LectureSlideNarration(
                stored_object_id=audio.id,
                status=schemas.LectureSlideNarrationStatus.READY,
            )
            session.add(narration)
            await session.flush()
            page = models.LectureSlidePage(
                lecture_slide_deck_id=1,
                position=0,
                narration_id=narration.id,
                narration_text=text,
                start_offset_ms=0,
                end_offset_ms=len(text) * 100,
            )
        else:
            translation = models.LectureSlideTranslation(
                lecture_slide_deck_id=1,
                language_code=language,
                language_name="Japanese",
                openai_model="test",
                status=schemas.LectureSlideTranslationStatus.READY,
                caption_stored_object_id=old_caption.id,
            )
            session.add(translation)
            await session.flush()
            page = models.LectureSlideTranslationPage(
                translation_id=translation.id,
                position=0,
                narration_stored_object_id=audio.id,
                narration_text=text,
                word_timings=[{"word": text, "start_ms": 0, "end_ms": len(text) * 100}],
                start_offset_ms=0,
                end_offset_ms=len(text) * 100,
            )
        session.add(page)
        await session.commit()
    return text


@pytest.mark.parametrize("language", ["original", "ja"])
async def test_repair_realigns_existing_audio_and_keeps_old_artifact(
    db, config, monkeypatch, language
):
    text = await make_lesson(db, language)
    uploaded = {}

    async def get_file(key):
        assert key == "audio"
        yield b"existing-audio"

    async def put(key, content, content_type):
        uploaded[key] = content.read().decode()

    delete = AsyncMock()
    create = AsyncMock(
        return_value=SimpleNamespace(
            characters=[
                SimpleNamespace(text=char, start=i * 0.1, end=(i + 1) * 0.1)
                for i, char in enumerate(text)
            ]
        )
    )
    monkeypatch.setattr(
        config,
        "lecture_video_audio_store",
        SimpleNamespace(store=SimpleNamespace(get_file=get_file)),
    )
    monkeypatch.setattr(
        config,
        "video_store",
        SimpleNamespace(store=SimpleNamespace(put=put, delete=delete)),
    )
    monkeypatch.setattr(
        repair, "_get_elevenlabs_api_key", AsyncMock(return_value="fake-key")
    )
    monkeypatch.setattr(
        repair,
        "get_elevenlabs_client",
        lambda _: SimpleNamespace(forced_alignment=SimpleNamespace(create=create)),
    )
    assert await repair.repair_lecture_slide_captions(1, language) == 1
    create.assert_not_called()
    assert not uploaded
    assert await repair.repair_lecture_slide_captions(1, language, apply=True) == 1
    assert create.call_args.kwargs["text"] == text
    assert create.call_args.kwargs["file"][1].getvalue() == b"existing-audio"
    assert next(iter(uploaded.values())).count("-->") == 12
    delete.assert_not_called()
    async with db.async_session() as session:
        assert (
            await session.scalar(
                select(models.LectureSlideCaptionStoredObject).where(
                    models.LectureSlideCaptionStoredObject.key == "old.vtt"
                )
            )
            is not None
        )
        deck = await session.get(models.LectureSlideDeck, 1)
        await session.refresh(deck, ["transcript_data"])
        assert deck.transcript_data["word_level_transcription"] == [{"id": "keep-me"}]
        if language == "ja":
            page = await session.scalar(select(models.LectureSlideTranslationPage))
            assert len(page.word_timings) > 1
            assert any(w.get("join_left") for w in page.word_timings)


@pytest.mark.parametrize("failure", ["changed_text", "concurrent_edit"])
async def test_repair_failure_keeps_existing_caption(db, config, monkeypatch, failure):
    text = await make_lesson(db, "ja")
    uploaded = {}

    async def get_file(key):
        yield b"existing-audio"

    async def put(key, content, content_type):
        uploaded[key] = content.read()

    async def align(**kwargs):
        if failure == "concurrent_edit":
            async with db.async_session() as session:
                page = await session.scalar(select(models.LectureSlideTranslationPage))
                page.narration_text = "A changed lecture"
                await session.commit()
        returned = text if failure == "concurrent_edit" else "Different text"
        return SimpleNamespace(
            characters=[
                SimpleNamespace(text=char, start=i * 0.1, end=(i + 1) * 0.1)
                for i, char in enumerate(returned)
            ]
        )

    delete = AsyncMock()
    monkeypatch.setattr(
        config,
        "lecture_video_audio_store",
        SimpleNamespace(store=SimpleNamespace(get_file=get_file)),
    )
    monkeypatch.setattr(
        config,
        "video_store",
        SimpleNamespace(store=SimpleNamespace(put=put, delete=delete)),
    )
    monkeypatch.setattr(
        repair, "_get_elevenlabs_api_key", AsyncMock(return_value="fake-key")
    )
    monkeypatch.setattr(
        repair,
        "get_elevenlabs_client",
        lambda _: SimpleNamespace(forced_alignment=SimpleNamespace(create=align)),
    )
    with pytest.raises((ValueError, RuntimeError), match="changed text|Lesson changed"):
        await repair.repair_lecture_slide_captions(1, "ja", apply=True)
    async with db.async_session() as session:
        owner = await session.scalar(select(models.LectureSlideTranslation))
        artifact = await session.get(
            models.LectureSlideCaptionStoredObject, owner.caption_stored_object_id
        )
        assert artifact.key == "old.vtt"
        assert (
            len(
                list(
                    await session.scalars(
                        select(models.LectureSlideCaptionStoredObject)
                    )
                )
            )
            == 1
        )
    if failure == "concurrent_edit":
        delete.assert_awaited_once_with(next(iter(uploaded)))
    else:
        assert not uploaded
        delete.assert_not_called()
