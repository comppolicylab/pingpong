from types import SimpleNamespace

import pytest

from pingpong import lecture_slide_processing, models, schemas
from pingpong.migrations import m13_remux_lecture_slide_narration_to_webm as migration

pytestmark = pytest.mark.asyncio


async def _make_deck(session, *, deck_id: int, content_type: str, key: str) -> None:
    class_ = await session.get(models.Class, 1)
    if class_ is None:
        session.add(models.Class(id=1, name="Class", api_key="sk-test"))
        await session.flush()
    source = models.LectureSlideSourceStoredObject(
        key=f"slides-{deck_id}.pdf",
        original_filename=f"slides-{deck_id}.pdf",
        content_type="application/pdf",
        content_length=100,
    )
    stored_object = models.LectureSlideNarrationStoredObject(
        key=key,
        content_type=content_type,
        content_length=10,
        duration_ms=1000,
    )
    session.add_all([source, stored_object])
    await session.flush()
    deck = models.LectureSlideDeck(
        id=deck_id,
        class_id=1,
        source_stored_object_id=source.id,
        continuous_narration_stored_object_id=stored_object.id,
        display_name=f"Slides {deck_id}",
        voice_id="voice-test",
        generation_prompt="Manifest prompt",
        narration_prompt="Narration prompt",
        status=schemas.LectureSlideDeckStatus.READY,
        slide_count=1,
    )
    session.add(deck)
    await session.flush()


async def test_remux_backfills_ogg_decks_and_skips_webm(db, config, monkeypatch):
    async with db.async_session() as session:
        await _make_deck(session, deck_id=1, content_type="audio/ogg", key="old.ogg")
        await _make_deck(session, deck_id=2, content_type="audio/webm", key="new.webm")
        await session.commit()

    read_keys: list[str] = []
    deleted_keys: list[str] = []

    class FakeAudioStore:
        async def get_file(self, key, chunk_size=1024 * 1024):
            read_keys.append(key)
            yield b"ogg-bytes"

    monkeypatch.setattr(
        config, "lecture_video_audio_store", SimpleNamespace(store=FakeAudioStore())
    )

    async def fake_remux(ogg_audio: bytes) -> bytes:
        assert ogg_audio == b"ogg-bytes"
        return b"webm-bytes"

    async def fake_store_audio(store_key, content_type, audio):
        assert content_type == "audio/webm"
        assert store_key.endswith(".webm")
        assert audio == b"webm-bytes"
        return store_key, len(audio)

    async def fake_delete(key):
        deleted_keys.append(key)

    monkeypatch.setattr(
        lecture_slide_processing, "remux_continuous_narration_to_webm", fake_remux
    )
    monkeypatch.setattr(lecture_slide_processing, "_store_audio", fake_store_audio)
    monkeypatch.setattr(
        lecture_slide_processing, "_delete_audio_key_quietly", fake_delete
    )

    async with db.async_session() as session:
        result = await migration.remux_lecture_slide_narration_to_webm(session)

    assert result.remuxed == 1
    assert result.skipped == 1
    assert result.failed == 0
    assert read_keys == ["old.ogg"]
    assert deleted_keys == ["old.ogg"]

    async with db.async_session() as session:
        deck = await session.get(models.LectureSlideDeck, 1)
        stored_object = await session.get(
            models.LectureSlideNarrationStoredObject,
            deck.continuous_narration_stored_object_id,
        )
        assert stored_object.content_type == "audio/webm"
        assert stored_object.key.endswith(".webm")
        assert stored_object.content_length == len(b"webm-bytes")
        # Duration bookkeeping is unchanged by the container swap.
        assert stored_object.duration_ms == 1000


async def test_remux_records_failures_without_mutating_row(db, config, monkeypatch):
    async with db.async_session() as session:
        await _make_deck(session, deck_id=1, content_type="audio/ogg", key="old.ogg")
        await session.commit()

    class FakeAudioStore:
        async def get_file(self, key, chunk_size=1024 * 1024):
            yield b"ogg-bytes"

    monkeypatch.setattr(
        config, "lecture_video_audio_store", SimpleNamespace(store=FakeAudioStore())
    )

    async def fake_remux(_ogg_audio: bytes) -> bytes:
        raise RuntimeError("ffmpeg unavailable")

    monkeypatch.setattr(
        lecture_slide_processing, "remux_continuous_narration_to_webm", fake_remux
    )

    async with db.async_session() as session:
        result = await migration.remux_lecture_slide_narration_to_webm(session)

    assert result.remuxed == 0
    assert result.failed == 1

    async with db.async_session() as session:
        deck = await session.get(models.LectureSlideDeck, 1)
        stored_object = await session.get(
            models.LectureSlideNarrationStoredObject,
            deck.continuous_narration_stored_object_id,
        )
        assert stored_object.content_type == "audio/ogg"
        assert stored_object.key == "old.ogg"
