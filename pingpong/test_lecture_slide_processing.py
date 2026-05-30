import json
from datetime import timedelta
from types import SimpleNamespace

import pytest
from pingpong import lecture_slide_processing, models, schemas
from pingpong.now import utcnow

pytestmark = pytest.mark.asyncio


def _minimal_pdf(text: str) -> bytes:
    stream = f"BT /F1 24 Tf 72 720 Td ({text}) Tj ET".encode("ascii")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Length "
        + str(len(stream)).encode("ascii")
        + b" >>\nstream\n"
        + stream
        + b"\nendstream",
    ]
    output = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for index, obj in enumerate(objects, start=1):
        offsets.append(len(output))
        output.extend(f"{index} 0 obj\n".encode("ascii"))
        output.extend(obj)
        output.extend(b"\nendobj\n")
    xref_offset = len(output)
    output.extend(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    output.extend(b"0000000000 65535 f \n")
    for offset in offsets[1:]:
        output.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    output.extend(
        f"trailer << /Size {len(objects) + 1} /Root 1 0 R >>\n"
        f"startxref\n{xref_offset}\n%%EOF\n".encode("ascii")
    )
    return bytes(output)


def _deck(
    *,
    class_id: int = 1,
    deck_id: int = 1,
    status: schemas.LectureSlideDeckStatus = schemas.LectureSlideDeckStatus.UPLOADED,
    slide_count: int = 1,
) -> models.LectureSlideDeck:
    source = models.LectureSlideSourceStoredObject(
        key=f"slides-{deck_id}.pdf",
        original_filename=f"slides-{deck_id}.pdf",
        content_type="application/pdf",
        content_length=100,
    )
    return models.LectureSlideDeck(
        id=deck_id,
        class_id=class_id,
        source_stored_object=source,
        display_name=f"Slides {deck_id}",
        voice_id="voice-test",
        generation_prompt="Manifest prompt",
        narration_prompt="Narration prompt",
        status=status,
        slide_count=slide_count,
    )


async def _create_class_and_deck(
    db, *, deck_id: int = 1, slide_count: int = 1
) -> models.LectureSlideDeck:
    async with db.async_session() as session:
        class_ = models.Class(id=1, name="Slide Class", api_key="sk-test")
        deck = _deck(deck_id=deck_id, slide_count=slide_count)
        session.add_all([class_, deck])
        await session.commit()
        return deck


async def test_queue_lecture_slide_processing_run_reuses_active_run(db):
    await _create_class_and_deck(db)
    async with db.async_session() as session:
        deck = await session.get(models.LectureSlideDeck, 1)
        assert deck is not None

        first = await lecture_slide_processing.queue_lecture_slide_processing_run(
            session, deck, requested_by_assistant_id=42
        )
        second = await lecture_slide_processing.queue_lecture_slide_processing_run(
            session, deck, requested_by_assistant_id=42
        )
        await session.commit()

        assert first is not None
        assert second is not None
        assert first.id == second.id
        assert deck.status == schemas.LectureSlideDeckStatus.PROCESSING
        assert first.stage == schemas.LectureSlideProcessingStage.SLIDE_ASSET_EXTRACTION
        assert first.attempt_number == 1


async def test_claim_next_processing_run_recovers_expired_lease(db):
    await _create_class_and_deck(db)
    async with db.async_session() as session:
        deck = await session.get(models.LectureSlideDeck, 1)
        assert deck is not None
        run = await lecture_slide_processing.queue_lecture_slide_processing_run(
            session, deck
        )
        assert run is not None
        run.status = schemas.LectureSlideProcessingRunStatus.RUNNING
        run.lease_token = "old-token"
        run.leased_by = "old-worker"
        run.lease_expires_at = utcnow() - timedelta(minutes=1)
        await session.commit()

    claimed = await lecture_slide_processing.claim_next_processing_run(
        leased_by="worker"
    )
    assert claimed is not None
    run_id, lease_token = claimed
    assert lease_token != "old-token"

    async with db.async_session() as session:
        run = await session.get(models.LectureSlideProcessingRun, run_id)
        assert run is not None
        assert run.status == schemas.LectureSlideProcessingRunStatus.RUNNING
        assert run.lease_token == lease_token
        assert run.leased_by == "worker"


async def test_recover_failed_processing_run_marks_deck_failed(db):
    await _create_class_and_deck(db)
    async with db.async_session() as session:
        deck = await session.get(models.LectureSlideDeck, 1)
        assert deck is not None
        run = await lecture_slide_processing.queue_lecture_slide_processing_run(
            session, deck
        )
        assert run is not None
        run.status = schemas.LectureSlideProcessingRunStatus.RUNNING
        run.lease_token = "lease"
        await session.commit()
        run_id = run.id

    recovered = await lecture_slide_processing.recover_failed_processing_run(
        run_id, "lease", error_message="failed"
    )

    assert recovered
    async with db.async_session() as session:
        run = await session.get(models.LectureSlideProcessingRun, run_id)
        deck = await session.get(models.LectureSlideDeck, 1)
        assert run is not None
        assert deck is not None
        assert run.status == schemas.LectureSlideProcessingRunStatus.FAILED
        assert run.error_message == "failed"
        assert deck.status == schemas.LectureSlideDeckStatus.FAILED
        assert deck.error_message == "failed"


async def test_extract_slide_assets_from_pdf_reads_text_and_dimensions(tmp_path):
    pdf_path = tmp_path / "slides.pdf"
    pdf_path.write_bytes(_minimal_pdf("Hello Slides"))

    assets = lecture_slide_processing.extract_slide_assets_from_pdf(str(pdf_path))

    assert len(assets) == 1
    assert assets[0].position == 0
    assert assets[0].width_px > 0
    assert assets[0].height_px > 0
    assert "Hello Slides" in (assets[0].extracted_text or "")


async def test_generate_narration_text_requires_exact_slide_count(
    db, monkeypatch, tmp_path
):
    await _create_class_and_deck(db, slide_count=2)
    async with db.async_session() as session:
        run = models.LectureSlideProcessingRun(
            lecture_slide_deck_id=1,
            lecture_slide_deck_id_snapshot=1,
            class_id=1,
            stage=schemas.LectureSlideProcessingStage.NARRATION_TEXT,
            attempt_number=1,
            status=schemas.LectureSlideProcessingRunStatus.RUNNING,
            lease_token="lease",
        )
        session.add(run)
        await session.commit()
        run_id = run.id

    captured: dict[str, object] = {}

    class FakeResponses:
        async def parse(self, **kwargs):
            captured.update(kwargs)
            response_model = kwargs["text_format"]
            return SimpleNamespace(
                output_parsed=response_model(
                    slides=[
                        lecture_slide_processing.GeneratedSlideNarration(
                            slide_position=0,
                            narration_text="First slide narration.",
                        ),
                        lecture_slide_processing.GeneratedSlideNarration(
                            slide_position=1,
                            narration_text="Second slide narration.",
                        ),
                    ]
                )
            )

    class FakeFiles:
        async def delete(self, file_id):
            captured["deleted_file_id"] = file_id

    fake_client = SimpleNamespace(responses=FakeResponses(), files=FakeFiles())
    monkeypatch.setattr(
        lecture_slide_processing,
        "_upload_openai_input_pdf",
        lambda _client, _path: _async_value("file-pdf"),
    )
    pdf_path = tmp_path / "slides.pdf"
    pdf_path.write_bytes(b"%PDF-1.4")

    narration_set = await lecture_slide_processing._generate_narration_text(
        run_id,
        "lease",
        1,
        str(pdf_path),
        "assistant-chat-model",
        fake_client,
    )

    assert narration_set is not None
    assert len(narration_set.slides) == 2
    assert captured["instructions"] == "Narration prompt"
    response_model = captured["text_format"]
    assert issubclass(
        response_model, lecture_slide_processing.GeneratedSlideNarrationSet
    )
    slides_schema = response_model.model_json_schema()["properties"]["slides"]
    assert slides_schema["minItems"] == 2
    assert slides_schema["maxItems"] == 2
    payload = json.dumps(captured["input"])
    assert "Generate narration for exactly 2 slides" in payload
    assert "Narration prompt" not in payload


async def test_generate_slide_manifest_uses_pdf_and_transcript_not_extracted_text(
    db, monkeypatch, tmp_path
):
    await _create_class_and_deck(db)
    async with db.async_session() as session:
        page = models.LectureSlidePage(
            lecture_slide_deck_id=1,
            position=0,
            extracted_text="DO NOT SEND EXTRACTED TEXT",
            start_offset_ms=0,
            end_offset_ms=1000,
        )
        run = models.LectureSlideProcessingRun(
            lecture_slide_deck_id=1,
            lecture_slide_deck_id_snapshot=1,
            class_id=1,
            stage=schemas.LectureSlideProcessingStage.MANIFEST_GENERATION,
            attempt_number=1,
            status=schemas.LectureSlideProcessingRunStatus.RUNNING,
            lease_token="lease",
        )
        session.add_all([page, run])
        await session.commit()
        run_id = run.id

    captured: dict[str, object] = {}

    class FakeResponses:
        async def parse(self, **kwargs):
            captured.update(kwargs)
            return SimpleNamespace(
                output_parsed=lecture_slide_processing.GeneratedSlideManifest(
                    questions=[
                        lecture_slide_processing.GeneratedSlideQuestion(
                            slide_position=0,
                            slide_offset_ms=0,
                            stop_offset_ms=1000,
                            question_text="What is shown?",
                            intro_text="Try this.",
                            options=[
                                lecture_slide_processing.GeneratedSlideChoice(
                                    option_text="Slides",
                                    post_answer_text="Right.",
                                    continue_offset_ms=1000,
                                    correct=True,
                                ),
                                lecture_slide_processing.GeneratedSlideChoice(
                                    option_text="Video",
                                    post_answer_text="Not quite.",
                                    continue_offset_ms=1000,
                                    correct=False,
                                ),
                            ],
                        )
                    ],
                    summary_checkpoints=[
                        schemas.LectureVideoManifestSummaryCheckpointV4(
                            end_offset_ms=1000,
                            summary="The slide introduces the topic.",
                        )
                    ],
                    moment_contexts=[
                        schemas.LectureVideoManifestMomentContextV4(
                            start_offset_ms=0,
                            center_offset_ms=500,
                            end_offset_ms=1000,
                            before="The lesson begins.",
                            at="The slide is being discussed.",
                            after="The lesson continues.",
                        )
                    ],
                )
            )

    class FakeFiles:
        async def delete(self, file_id):
            captured["deleted_file_id"] = file_id

    fake_client = SimpleNamespace(responses=FakeResponses(), files=FakeFiles())
    monkeypatch.setattr(
        lecture_slide_processing,
        "_upload_openai_input_pdf",
        lambda _client, _path: _async_value("file-pdf"),
    )
    transcript = [
        schemas.LectureVideoManifestWordV3(
            id="w1", word="transcript-token", start_offset_ms=0, end_offset_ms=500
        )
    ]
    pdf_path = tmp_path / "slides.pdf"
    pdf_path.write_bytes(b"%PDF-1.4")

    manifest = await lecture_slide_processing._generate_slide_manifest(
        run_id,
        "lease",
        1,
        str(pdf_path),
        transcript,
        "assistant-chat-model",
        fake_client,
    )

    assert manifest is not None
    assert captured["model"] == "assistant-chat-model"
    instructions = str(captured["instructions"])
    assert "Manifest prompt" in instructions
    assert "TO-DO's FOR SUCCESSFUL QUIZ-GENERATION" in instructions
    assert "QUALITY EXAMPLES:" in instructions
    assert "FINAL VERIFICATION BEFORE OUTPUT:" in instructions
    assert "SLIDE LESSON MANIFEST ADAPTATION:" in instructions
    assert captured["text_format"] is lecture_slide_processing.GeneratedSlideManifest
    assert captured["deleted_file_id"] == "file-pdf"
    payload = json.dumps(captured["input"])
    assert "file-pdf" in payload
    assert "transcript-token" in payload
    assert "SLIDE TIMING SOURCE DATA:" in payload
    assert "WORD-LEVEL TRANSCRIPT SOURCE DATA:" in payload
    assert "return only the schema-valid JSON object" in payload
    assert "Manifest prompt" not in payload
    assert "DO NOT SEND EXTRACTED TEXT" not in payload
    assert [moment.center_offset_ms for moment in manifest.moment_contexts] == [0, 1000]


async def test_generate_slide_manifest_rejects_multiple_correct_options(
    db, monkeypatch, tmp_path
):
    await _create_class_and_deck(db)
    async with db.async_session() as session:
        page = models.LectureSlidePage(
            lecture_slide_deck_id=1,
            position=0,
            start_offset_ms=0,
            end_offset_ms=1000,
        )
        run = models.LectureSlideProcessingRun(
            lecture_slide_deck_id=1,
            lecture_slide_deck_id_snapshot=1,
            class_id=1,
            stage=schemas.LectureSlideProcessingStage.MANIFEST_GENERATION,
            attempt_number=1,
            status=schemas.LectureSlideProcessingRunStatus.RUNNING,
            lease_token="lease",
        )
        session.add_all([page, run])
        await session.commit()
        run_id = run.id

    class FakeResponses:
        async def parse(self, **_kwargs):
            return SimpleNamespace(
                output_parsed=lecture_slide_processing.GeneratedSlideManifest(
                    questions=[
                        lecture_slide_processing.GeneratedSlideQuestion(
                            slide_position=0,
                            slide_offset_ms=0,
                            stop_offset_ms=1000,
                            question_text="What is shown?",
                            options=[
                                lecture_slide_processing.GeneratedSlideChoice(
                                    option_text="Slides",
                                    continue_offset_ms=1000,
                                    correct=True,
                                ),
                                lecture_slide_processing.GeneratedSlideChoice(
                                    option_text="Also slides",
                                    continue_offset_ms=1000,
                                    correct=True,
                                ),
                            ],
                        )
                    ],
                    summary_checkpoints=[
                        schemas.LectureVideoManifestSummaryCheckpointV4(
                            end_offset_ms=1000,
                            summary="The slide introduces the topic.",
                        )
                    ],
                    moment_contexts=[
                        schemas.LectureVideoManifestMomentContextV4(
                            start_offset_ms=0,
                            center_offset_ms=0,
                            end_offset_ms=1000,
                            before="The lesson begins.",
                            at="The slide is being discussed.",
                            after="The lesson continues.",
                        )
                    ],
                )
            )

    class FakeFiles:
        async def delete(self, _file_id):
            return None

    fake_client = SimpleNamespace(responses=FakeResponses(), files=FakeFiles())
    monkeypatch.setattr(
        lecture_slide_processing,
        "_upload_openai_input_pdf",
        lambda _client, _path: _async_value("file-pdf"),
    )
    transcript = [
        schemas.LectureVideoManifestWordV3(
            id="w1", word="token", start_offset_ms=0, end_offset_ms=1000
        )
    ]
    pdf_path = tmp_path / "slides.pdf"
    pdf_path.write_bytes(b"%PDF-1.4")

    with pytest.raises(ValueError, match="exactly one correct"):
        await lecture_slide_processing._generate_slide_manifest(
            run_id,
            "lease",
            1,
            str(pdf_path),
            transcript,
            "assistant-chat-model",
            fake_client,
        )


async def test_parse_responses_output_retries_transient_openai_failure(monkeypatch):
    attempts = 0

    async def fake_sleep(_delay):
        return None

    class FakeResponses:
        async def parse(self, **kwargs):
            nonlocal attempts
            attempts += 1
            if attempts == 1:
                raise RuntimeError("503 temporarily unavailable")
            return SimpleNamespace(
                output_parsed=lecture_slide_processing.GeneratedSlideNarrationSet(
                    slides=[
                        lecture_slide_processing.GeneratedSlideNarration(
                            slide_position=0,
                            narration_text="Recovered.",
                        )
                    ]
                ),
                kwargs=kwargs,
            )

    monkeypatch.setattr(lecture_slide_processing.asyncio, "sleep", fake_sleep)
    fake_client = SimpleNamespace(responses=FakeResponses())

    narration_set = await lecture_slide_processing._parse_responses_output(
        fake_client,
        model="assistant-chat-model",
        instructions="Narrate.",
        response_model=lecture_slide_processing.GeneratedSlideNarrationSet,
        input_messages=[{"role": "user", "content": "source"}],
    )

    assert attempts == 2
    assert narration_set.slides[0].narration_text == "Recovered."


async def _async_value(value):
    return value


async def test_transcribe_audio_words_enriches_punctuation_from_segments(tmp_path):
    class FakeTranscriptions:
        async def create(self, **_kwargs):
            return SimpleNamespace(
                words=[
                    SimpleNamespace(word="hello", start=0.0, end=0.2),
                    SimpleNamespace(word="world", start=0.2, end=0.5),
                ],
                segments=[
                    SimpleNamespace(text="Hello, world!", start=0.0, end=0.5),
                ],
            )

    audio_path = tmp_path / "slide.ogg"
    audio_path.write_bytes(b"audio")
    fake_client = SimpleNamespace(
        audio=SimpleNamespace(transcriptions=FakeTranscriptions())
    )

    words = await lecture_slide_processing.transcribe_audio_words(
        str(audio_path), fake_client
    )

    assert [word.word for word in words] == ["Hello,", "world!"]
    assert [word.start_offset_ms for word in words] == [0, 200]
    assert [word.end_offset_ms for word in words] == [200, 500]


async def test_transcribe_and_persist_slide_audio_offsets_words(
    db, monkeypatch, tmp_path
):
    await _create_class_and_deck(db)
    async with db.async_session() as session:
        pages = [
            models.LectureSlidePage(lecture_slide_deck_id=1, position=0),
            models.LectureSlidePage(lecture_slide_deck_id=1, position=1),
        ]
        run = models.LectureSlideProcessingRun(
            lecture_slide_deck_id=1,
            lecture_slide_deck_id_snapshot=1,
            class_id=1,
            stage=schemas.LectureSlideProcessingStage.NARRATION_TRANSCRIPTION,
            attempt_number=1,
            status=schemas.LectureSlideProcessingRunStatus.RUNNING,
            lease_token="lease",
        )
        session.add_all([*pages, run])
        await session.commit()
        page_ids = [page.id for page in pages]
        run_id = run.id

    async def fake_transcribe_audio_words(_path, _client):
        return [
            schemas.LectureVideoManifestWordV3(
                id="w", word="hello", start_offset_ms=100, end_offset_ms=300
            )
        ]

    monkeypatch.setattr(
        lecture_slide_processing, "transcribe_audio_words", fake_transcribe_audio_words
    )
    artifacts = [
        lecture_slide_processing.SlideAudioArtifact(
            page_id=page_ids[0],
            page_position=0,
            content_type="audio/ogg",
            audio=b"audio-1",
            duration_ms=1000,
            store_key="a1",
            stored_object_id=1,
        ),
        lecture_slide_processing.SlideAudioArtifact(
            page_id=page_ids[1],
            page_position=1,
            content_type="audio/ogg",
            audio=b"audio-2",
            duration_ms=2000,
            store_key="a2",
            stored_object_id=2,
        ),
    ]

    words = await lecture_slide_processing._transcribe_and_persist_slide_audio(
        run_id,
        "lease",
        1,
        artifacts,
        SimpleNamespace(),
        str(tmp_path),
    )

    assert [word.start_offset_ms for word in words or []] == [100, 1100]
    async with db.async_session() as session:
        deck = await models.LectureSlideDeck.get_by_id_with_processing_context(
            session, 1
        )
        assert deck is not None
        assert deck.total_duration_ms == 3000
        assert [page.start_offset_ms for page in deck.pages] == [0, 1000]
        assert [page.end_offset_ms for page in deck.pages] == [1000, 3000]
        assert deck.transcript_data is not None
        assert len(deck.transcript_data["word_level_transcription"]) == 2


async def test_claim_next_any_processing_run_returns_negative_id_for_older_video_run(
    db,
):
    async with db.async_session() as session:
        class_ = models.Class(id=1, name="Class", api_key="sk-test")
        video_object = models.LectureVideoStoredObject(
            key="video.mp4",
            original_filename="video.mp4",
            content_type="video/mp4",
            content_length=100,
        )
        session.add_all([class_, video_object])
        await session.flush()
        video = await models.LectureVideo.create(
            session,
            class_id=1,
            stored_object_id=video_object.id,
            user_id=None,
            status=schemas.LectureVideoStatus.PROCESSING,
        )
        deck = _deck(deck_id=1)
        session.add(deck)
        await session.flush()
        video_run = await models.LectureVideoProcessingRun.create(
            session,
            lecture_video_id=video.id,
            lecture_video_id_snapshot=video.id,
            class_id=1,
            assistant_id_at_start=None,
            stage=schemas.LectureVideoProcessingStage.MANIFEST_GENERATION,
            attempt_number=1,
            status=schemas.LectureVideoProcessingRunStatus.QUEUED,
        )
        slide_run = await models.LectureSlideProcessingRun.create(
            session,
            lecture_slide_deck_id=deck.id,
            lecture_slide_deck_id_snapshot=deck.id,
            class_id=1,
            assistant_id_at_start=None,
            stage=schemas.LectureSlideProcessingStage.SLIDE_ASSET_EXTRACTION,
            attempt_number=1,
            status=schemas.LectureSlideProcessingRunStatus.QUEUED,
        )
        video_run.created = utcnow() - timedelta(minutes=2)
        slide_run.created = utcnow() - timedelta(minutes=1)
        await session.commit()

    claimed = await lecture_slide_processing.claim_next_any_processing_run(
        leased_by="worker"
    )

    assert claimed is not None
    run_id, _lease_token = claimed
    assert run_id < 0
