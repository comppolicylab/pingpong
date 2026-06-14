from types import SimpleNamespace

import pytest

from pingpong import lecture_slide_processing, models, schemas
from pingpong.migrations import m14_migrate_lecture_slide_v4_context_to_v5 as migration

pytestmark = pytest.mark.asyncio


class FakeVideoStore:
    def __init__(self, payloads: dict[str, bytes]):
        self.payloads = payloads
        self.seen_keys: list[str] = []

    async def stream_video(self, key: str):
        self.seen_keys.append(key)
        yield self.payloads[key]


class FakeOpenAIFiles:
    def __init__(self, *, uploaded_file_id: str = "uploaded-file"):
        self.created_files: list[tuple[tuple[str, bytes, str], str]] = []
        self.retrieved_file_ids: list[str] = []
        self.uploaded_file_id = uploaded_file_id

    async def retrieve(self, file_id: str):
        self.retrieved_file_ids.append(file_id)
        return SimpleNamespace(id=file_id)

    async def create(self, *, file, purpose: str):
        self.created_files.append((file, purpose))
        return SimpleNamespace(id=self.uploaded_file_id)


def _context_v5() -> schemas.LectureSlideContextV5:
    return schemas.LectureSlideContextV5.model_validate(
        {
            "version": 5,
            "deck_summary": "Migrated lesson summary.",
            "slides": [
                {
                    "slide_position": 0,
                    "title": "Opening",
                    "start_offset_ms": 0,
                    "end_offset_ms": 1000,
                    "visible_text": "Opening slide",
                    "visual_context": "The first slide introduces the lesson.",
                    "narration_summary": "The narration opens the topic.",
                    "key_points": ["Opening point"],
                    "diagrams": [],
                    "equations_or_symbols": [],
                }
            ],
            "summary_checkpoints": [
                {
                    "end_offset_ms": 1000,
                    "end_slide_position": 0,
                    "summary": "The lesson has introduced the topic.",
                }
            ],
            "moment_contexts": [
                {
                    "start_offset_ms": 0,
                    "center_offset_ms": 500,
                    "end_offset_ms": 1000,
                    "slide_position": 0,
                    "before": "The lesson begins.",
                    "at": "The opening idea is explained.",
                    "after": "The next slide will continue.",
                }
            ],
        }
    )


def _transcript_data() -> dict:
    return lecture_slide_processing.transcript_data_from_words(
        [
            schemas.LectureVideoManifestWordV3(
                id="word-0",
                word="hello",
                start_offset_ms=0,
                end_offset_ms=100,
            )
        ]
    )


def _add_ready_v4_deck(
    *,
    class_: models.Class,
    user: models.User,
    file_id: str,
    source_key: str,
    page_start_offset_ms: int | None = 0,
    page_end_offset_ms: int | None = 1000,
) -> models.LectureSlideDeck:
    source_file = models.File(
        file_id=file_id,
        name="slides.pdf",
        content_type="application/pdf",
        private=True,
        uploader_id=user.id,
    )
    source = models.LectureSlideSourceStoredObject(
        key=source_key,
        original_filename="slides.pdf",
        content_type="application/pdf",
        content_length=128,
        openai_file=source_file,
    )
    deck = models.LectureSlideDeck(
        class_=class_,
        source_stored_object=source,
        uploader_id=user.id,
        display_name="slides.pdf",
        status=schemas.LectureSlideDeckStatus.READY,
        slide_count=1,
        generation_prompt="Existing generation prompt",
        transcript_data=_transcript_data(),
        context_data={},
        context_version=4,
        lecture_slide_chat_available=True,
        total_duration_ms=1000,
    )
    models.LectureSlidePage(
        lecture_slide_deck=deck,
        position=0,
        start_offset_ms=page_start_offset_ms,
        end_offset_ms=page_end_offset_ms,
        narration_text="Opening narration.",
    )
    models.Assistant(
        name=f"Slide Assistant {source_key}",
        class_=class_,
        interaction_mode=schemas.InteractionMode.LECTURE_SLIDES,
        version=3,
        lecture_slide_deck=deck,
        instructions="You are a slide assistant.",
        model="gpt-test",
        tools="[]",
    )
    return deck


async def test_migrate_lecture_slide_v4_context_to_v5_preserves_questions(
    db, monkeypatch
):
    files = FakeOpenAIFiles()

    async def fake_generate_slide_context_v5(**kwargs):
        assert kwargs["model"] == "gpt-test"
        assert kwargs["file_id"] == "file-slides"
        assert kwargs["generation_prompt"] == "Existing generation prompt"
        assert kwargs["page_ranges"] == [
            {"slide_position": 0, "start_offset_ms": 0, "end_offset_ms": 1000}
        ]
        assert [word.word for word in kwargs["transcript"]] == ["hello"]
        return _context_v5()

    async def fake_get_openai_client_by_class_id(session, class_id: int):
        assert class_id == 1
        return SimpleNamespace(files=files)

    monkeypatch.setattr(
        lecture_slide_processing,
        "generate_slide_context_v5",
        fake_generate_slide_context_v5,
    )
    monkeypatch.setattr(
        migration,
        "get_openai_client_by_class_id",
        fake_get_openai_client_by_class_id,
    )

    async with db.async_session() as session:
        user = models.User(id=123, email="owner@example.com")
        class_ = models.Class(id=1, name="Slide Class", api_key="sk-test")
        source_file = models.File(
            file_id="file-slides",
            name="slides.pdf",
            content_type="application/pdf",
            private=True,
            uploader_id=user.id,
        )
        source = models.LectureSlideSourceStoredObject(
            key="slides.pdf",
            original_filename="slides.pdf",
            content_type="application/pdf",
            content_length=128,
            openai_file=source_file,
        )
        deck = models.LectureSlideDeck(
            class_=class_,
            source_stored_object=source,
            uploader_id=user.id,
            display_name="slides.pdf",
            status=schemas.LectureSlideDeckStatus.READY,
            slide_count=1,
            generation_prompt="Existing generation prompt",
            transcript_data=_transcript_data(),
            context_data={},
            context_version=4,
            lecture_slide_chat_available=True,
            total_duration_ms=1000,
        )
        page = models.LectureSlidePage(
            lecture_slide_deck=deck,
            position=0,
            start_offset_ms=0,
            end_offset_ms=1000,
            narration_text="Opening narration.",
        )
        intro_narration = models.LectureSlideNarration(
            status=schemas.LectureSlideNarrationStatus.READY
        )
        post_narration = models.LectureSlideNarration(
            status=schemas.LectureSlideNarrationStatus.READY
        )
        question = models.LectureSlideQuestion(
            lecture_slide_deck=deck,
            position=0,
            slide_position=0,
            slide_offset_ms=1000,
            stop_offset_ms=1000,
            question_type=schemas.LectureSlideQuestionType.SINGLE_SELECT,
            question_text="Existing question?",
            intro_text="Answer this.",
            intro_narration=intro_narration,
            options=[
                models.LectureSlideQuestionOption(
                    position=0,
                    option_text="Correct answer",
                    post_answer_text="Correct.",
                    post_narration=post_narration,
                    continue_slide_position=0,
                    continue_slide_offset_ms=1000,
                    continue_offset_ms=1000,
                ),
                models.LectureSlideQuestionOption(
                    position=1,
                    option_text="Incorrect answer",
                    post_answer_text="Try again.",
                    continue_slide_position=0,
                    continue_slide_offset_ms=1000,
                    continue_offset_ms=1000,
                ),
            ],
        )
        assistant = models.Assistant(
            id=1,
            name="Slide Assistant",
            class_=class_,
            interaction_mode=schemas.InteractionMode.LECTURE_SLIDES,
            version=3,
            lecture_slide_deck=deck,
            instructions="You are a slide assistant.",
            model="gpt-test",
            tools="[]",
        )
        session.add_all([user, page, question, assistant])
        await session.flush()
        question_id = question.id
        option_ids = [option.id for option in question.options]
        intro_narration_id = intro_narration.id
        post_narration_id = post_narration.id
        deck_id = deck.id
        await session.commit()

    async with db.async_session() as session:
        result = await migration.migrate_lecture_slide_v4_context_to_v5(session)

    assert result == migration.MigrateLectureSlideV4ContextToV5Result(
        updated=1,
        skipped=0,
        failed=0,
    )

    async with db.async_session() as session:
        deck = await models.LectureSlideDeck.get_by_id_with_processing_context(
            session, deck_id
        )
        assert deck is not None
        assert deck.context_version == 5
        assert deck.context_data is not None
        assert deck.context_data["version"] == 5
        assert deck.context_data["deck_summary"] == "Migrated lesson summary."
        assert deck.lecture_slide_chat_available is True
        assert len(deck.questions) == 1
        question = deck.questions[0]
        assert question.id == question_id
        assert question.question_text == "Existing question?"
        assert question.intro_narration_id == intro_narration_id
        assert [option.id for option in question.options] == option_ids
        assert question.options[0].post_narration_id == post_narration_id
    assert files.retrieved_file_ids == ["file-slides"]


async def test_migrate_lecture_slide_v4_context_to_v5_continues_after_commit(
    db, monkeypatch
):
    files = FakeOpenAIFiles()
    generated_file_ids: list[str] = []

    async def fake_generate_slide_context_v5(**kwargs):
        generated_file_ids.append(kwargs["file_id"])
        return _context_v5()

    async def fake_get_openai_client_by_class_id(session, class_id: int):
        return SimpleNamespace(files=files)

    monkeypatch.setattr(
        lecture_slide_processing,
        "generate_slide_context_v5",
        fake_generate_slide_context_v5,
    )
    monkeypatch.setattr(
        migration,
        "get_openai_client_by_class_id",
        fake_get_openai_client_by_class_id,
    )

    async with db.async_session() as session:
        user = models.User(id=123, email="owner@example.com")
        class_ = models.Class(id=1, name="Slide Class", api_key="sk-test")
        first_deck = _add_ready_v4_deck(
            class_=class_,
            user=user,
            file_id="file-slides-1",
            source_key="slides-1.pdf",
        )
        second_deck = _add_ready_v4_deck(
            class_=class_,
            user=user,
            file_id="file-slides-2",
            source_key="slides-2.pdf",
        )
        session.add_all([user, first_deck, second_deck])
        await session.commit()
        deck_ids = [first_deck.id, second_deck.id]

    async with db.async_session() as session:
        result = await migration.migrate_lecture_slide_v4_context_to_v5(
            session, batch_size=2
        )

    assert result == migration.MigrateLectureSlideV4ContextToV5Result(
        updated=2,
        skipped=0,
        failed=0,
    )
    assert generated_file_ids == ["file-slides-1", "file-slides-2"]

    async with db.async_session() as session:
        decks = [
            await models.LectureSlideDeck.get_by_id_with_processing_context(
                session, deck_id
            )
            for deck_id in deck_ids
        ]
    assert [deck.context_version for deck in decks if deck is not None] == [5, 5]


async def test_migrate_lecture_slide_v4_context_to_v5_skips_untimed_pages(
    db, monkeypatch
):
    async def fake_generate_slide_context_v5(**kwargs):
        raise AssertionError("untimed page deck should not generate v5 context")

    monkeypatch.setattr(
        lecture_slide_processing,
        "generate_slide_context_v5",
        fake_generate_slide_context_v5,
    )

    async with db.async_session() as session:
        user = models.User(id=123, email="owner@example.com")
        class_ = models.Class(id=1, name="Slide Class", api_key="sk-test")
        deck = _add_ready_v4_deck(
            class_=class_,
            user=user,
            file_id="file-slides",
            source_key="slides.pdf",
            page_start_offset_ms=None,
            page_end_offset_ms=None,
        )
        session.add_all([user, deck])
        await session.commit()

    async with db.async_session() as session:
        result = await migration.migrate_lecture_slide_v4_context_to_v5(session)

    assert result == migration.MigrateLectureSlideV4ContextToV5Result(
        updated=0,
        skipped=1,
        failed=0,
    )


async def test_migrate_lecture_slide_v4_context_to_v5_reuploads_stale_cached_file(
    db, config, monkeypatch
):
    video_store = FakeVideoStore({"slides.pdf": b"%PDF slide bytes"})
    files = FakeOpenAIFiles(uploaded_file_id="file-reuploaded")
    monkeypatch.setattr(config, "video_store", SimpleNamespace(store=video_store))

    async def fake_cached_openai_file_exists(openai_client, file_id: str):
        assert file_id == "file-stale"
        return False

    async def fake_generate_slide_context_v5(**kwargs):
        assert kwargs["file_id"] == "file-reuploaded"
        return _context_v5()

    async def fake_get_openai_client_by_class_id(session, class_id: int):
        return SimpleNamespace(files=files)

    monkeypatch.setattr(
        migration,
        "_cached_openai_file_exists",
        fake_cached_openai_file_exists,
    )
    monkeypatch.setattr(
        lecture_slide_processing,
        "generate_slide_context_v5",
        fake_generate_slide_context_v5,
    )
    monkeypatch.setattr(
        migration,
        "get_openai_client_by_class_id",
        fake_get_openai_client_by_class_id,
    )
    monkeypatch.setattr(
        migration.lecture_slide_service,
        "get_openai_client_by_class_id",
        fake_get_openai_client_by_class_id,
    )

    async with db.async_session() as session:
        user = models.User(id=123, email="owner@example.com")
        class_ = models.Class(id=1, name="Slide Class", api_key="sk-test")
        deck = _add_ready_v4_deck(
            class_=class_,
            user=user,
            file_id="file-stale",
            source_key="slides.pdf",
        )
        session.add_all([user, deck])
        await session.commit()
        deck_id = deck.id

    async with db.async_session() as session:
        result = await migration.migrate_lecture_slide_v4_context_to_v5(session)

    assert result == migration.MigrateLectureSlideV4ContextToV5Result(
        updated=1,
        skipped=0,
        failed=0,
    )
    assert video_store.seen_keys == ["slides.pdf"]
    assert files.created_files == [
        (("slides.pdf", b"%PDF slide bytes", "application/pdf"), "user_data")
    ]

    async with db.async_session() as session:
        deck = await models.LectureSlideDeck.get_by_id_with_processing_context(
            session, deck_id
        )
        assert deck is not None
        file = await session.get(
            models.File, deck.source_stored_object.openai_file_object_id
        )
        assert file is not None
        assert file.file_id == "file-reuploaded"


async def test_migrate_lecture_slide_v4_context_to_v5_skips_already_v5(db):
    async with db.async_session() as session:
        user = models.User(id=123, email="owner@example.com")
        class_ = models.Class(id=1, name="Slide Class", api_key="sk-test")
        source = models.LectureSlideSourceStoredObject(
            key="slides.pdf",
            original_filename="slides.pdf",
            content_type="application/pdf",
            content_length=128,
        )
        deck = models.LectureSlideDeck(
            class_=class_,
            source_stored_object=source,
            uploader_id=user.id,
            display_name="slides.pdf",
            status=schemas.LectureSlideDeckStatus.READY,
            slide_count=1,
            context_data=_context_v5().model_dump(),
            context_version=5,
            lecture_slide_chat_available=True,
        )
        session.add_all([user, deck])
        await session.commit()

    async with db.async_session() as session:
        result = await migration.migrate_lecture_slide_v4_context_to_v5(session)

    assert result == migration.MigrateLectureSlideV4ContextToV5Result()
