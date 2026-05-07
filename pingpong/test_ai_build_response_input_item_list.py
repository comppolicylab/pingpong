from datetime import timedelta

import pytest

from pingpong import models, schemas
from pingpong import ai
from pingpong.ai import build_response_input_item_list
from pingpong.now import utcnow


@pytest.mark.asyncio
async def test_build_response_input_item_list_drops_reasoning_for_expired_ci(db):
    async with db.async_session() as session:
        thread = models.Thread(thread_id="thread_expired_ci", version=3)
        session.add(thread)
        await session.flush()

        run = models.Run(status=schemas.RunStatus.COMPLETED, thread_id=thread.id)
        session.add(run)
        await session.flush()

        base_time = utcnow() - timedelta(hours=1)

        message = models.Message(
            message_status=schemas.MessageStatus.COMPLETED,
            run_id=run.id,
            thread_id=thread.id,
            output_index=1,
            role=schemas.MessageRole.ASSISTANT,
            created=base_time + timedelta(minutes=1),
        )
        reasoning_one = models.ReasoningStep(
            run_id=run.id,
            thread_id=thread.id,
            reasoning_id="rst-1",
            output_index=2,
            status=schemas.ReasoningStatus.COMPLETED,
            created=base_time + timedelta(minutes=2),
        )
        reasoning_two = models.ReasoningStep(
            run_id=run.id,
            thread_id=thread.id,
            reasoning_id="rst-2",
            output_index=3,
            status=schemas.ReasoningStatus.COMPLETED,
            created=base_time + timedelta(minutes=3),
        )
        tool_call = models.ToolCall(
            tool_call_id="tc_1",
            type=schemas.ToolCallType.CODE_INTERPRETER,
            status=schemas.ToolCallStatus.COMPLETED,
            run_id=run.id,
            thread_id=thread.id,
            output_index=4,
            code="print('hi')",
            container_id="container-1",
            created=base_time + timedelta(minutes=4),
            completed=base_time + timedelta(minutes=5),
        )

        session.add_all([message, reasoning_one, reasoning_two, tool_call])
        await session.commit()

        thread_id = thread.id

    async with db.async_session() as session:
        items = await build_response_input_item_list(
            session, thread_id=thread_id, uses_reasoning=True
        )

    item_types = [item.get("type") for item in items if "type" in item]
    assert "code_interpreter_call" not in item_types
    assert "reasoning" not in item_types

    summary_messages = [item for item in items if isinstance(item.get("content"), str)]
    assert len(summary_messages) == 1
    assert "code interpreter tool" in summary_messages[0]["content"]


@pytest.mark.asyncio
async def test_build_response_input_item_list_keeps_reasoning_for_active_ci(db):
    async with db.async_session() as session:
        thread = models.Thread(thread_id="thread_active_ci", version=3)
        session.add(thread)
        await session.flush()

        run = models.Run(status=schemas.RunStatus.COMPLETED, thread_id=thread.id)
        session.add(run)
        await session.flush()

        base_time = utcnow() - timedelta(minutes=5)

        message = models.Message(
            message_status=schemas.MessageStatus.COMPLETED,
            run_id=run.id,
            thread_id=thread.id,
            output_index=1,
            role=schemas.MessageRole.ASSISTANT,
            created=base_time + timedelta(minutes=1),
        )
        reasoning = models.ReasoningStep(
            run_id=run.id,
            thread_id=thread.id,
            reasoning_id="rst-active",
            output_index=2,
            status=schemas.ReasoningStatus.COMPLETED,
            created=base_time + timedelta(minutes=2),
        )
        tool_call = models.ToolCall(
            tool_call_id="tc_active",
            type=schemas.ToolCallType.CODE_INTERPRETER,
            status=schemas.ToolCallStatus.COMPLETED,
            run_id=run.id,
            thread_id=thread.id,
            output_index=3,
            code="print('ok')",
            container_id="container-active",
            created=base_time + timedelta(minutes=3),
            completed=base_time + timedelta(minutes=4),
        )

        session.add_all([message, reasoning, tool_call])
        await session.commit()

        thread_id = thread.id

    async with db.async_session() as session:
        items = await build_response_input_item_list(
            session, thread_id=thread_id, uses_reasoning=True
        )

    item_types = [item.get("type") for item in items if "type" in item]
    assert "code_interpreter_call" in item_types
    assert "reasoning" in item_types
    assert not any(
        isinstance(item.get("content"), str)
        and "code interpreter tool" in item["content"]
        for item in items
    )


@pytest.mark.asyncio
async def test_build_response_input_item_list_drops_only_contiguous_reasoning(db):
    async with db.async_session() as session:
        thread = models.Thread(thread_id="thread_contiguous_reasoning", version=3)
        session.add(thread)
        await session.flush()

        run = models.Run(status=schemas.RunStatus.COMPLETED, thread_id=thread.id)
        session.add(run)
        await session.flush()

        base_time = utcnow() - timedelta(hours=1)

        message_one = models.Message(
            message_status=schemas.MessageStatus.COMPLETED,
            run_id=run.id,
            thread_id=thread.id,
            output_index=1,
            role=schemas.MessageRole.ASSISTANT,
            created=base_time + timedelta(minutes=1),
        )
        reasoning_keep = models.ReasoningStep(
            run_id=run.id,
            thread_id=thread.id,
            reasoning_id="rst-keep",
            output_index=2,
            status=schemas.ReasoningStatus.COMPLETED,
            created=base_time + timedelta(minutes=2),
        )
        message_two = models.Message(
            message_status=schemas.MessageStatus.COMPLETED,
            run_id=run.id,
            thread_id=thread.id,
            output_index=3,
            role=schemas.MessageRole.ASSISTANT,
            created=base_time + timedelta(minutes=3),
        )
        reasoning_drop = models.ReasoningStep(
            run_id=run.id,
            thread_id=thread.id,
            reasoning_id="rst-drop",
            output_index=4,
            status=schemas.ReasoningStatus.COMPLETED,
            created=base_time + timedelta(minutes=4),
        )
        tool_call = models.ToolCall(
            tool_call_id="tc_expired",
            type=schemas.ToolCallType.CODE_INTERPRETER,
            status=schemas.ToolCallStatus.COMPLETED,
            run_id=run.id,
            thread_id=thread.id,
            output_index=5,
            code="print('expired')",
            container_id="container-expired",
            created=base_time + timedelta(minutes=5),
            completed=base_time + timedelta(minutes=6),
        )

        session.add_all(
            [message_one, reasoning_keep, message_two, reasoning_drop, tool_call]
        )
        await session.commit()

        thread_id = thread.id

    async with db.async_session() as session:
        items = await build_response_input_item_list(
            session, thread_id=thread_id, uses_reasoning=True
        )

    reasoning_ids = [
        item.get("id") for item in items if item.get("type") == "reasoning"
    ]
    assert "rst-keep" in reasoning_ids
    assert "rst-drop" not in reasoning_ids


@pytest.mark.asyncio
async def test_build_response_input_item_list_preserves_assistant_phase_only(db):
    async with db.async_session() as session:
        thread = models.Thread(thread_id="thread_message_phase", version=3)
        session.add(thread)
        await session.flush()

        run = models.Run(status=schemas.RunStatus.COMPLETED, thread_id=thread.id)
        session.add(run)
        await session.flush()

        base_time = utcnow() - timedelta(minutes=5)

        user_message = models.Message(
            message_status=schemas.MessageStatus.COMPLETED,
            run_id=run.id,
            thread_id=thread.id,
            output_index=1,
            role=schemas.MessageRole.USER,
            created=base_time + timedelta(minutes=1),
        )
        assistant_message = models.Message(
            message_status=schemas.MessageStatus.COMPLETED,
            run_id=run.id,
            thread_id=thread.id,
            output_index=2,
            role=schemas.MessageRole.ASSISTANT,
            phase=schemas.MessagePhase.COMMENTARY.value,
            created=base_time + timedelta(minutes=2),
        )

        session.add_all([user_message, assistant_message])
        await session.commit()

        thread_id = thread.id

    async with db.async_session() as session:
        items = await build_response_input_item_list(session, thread_id=thread_id)

    assert len(items) == 2
    assert items[0]["role"] == "user"
    assert "phase" not in items[0] or items[0]["phase"] is None
    assert items[1]["role"] == "assistant"
    assert items[1]["phase"] == "commentary"


@pytest.mark.asyncio
async def test_build_response_input_item_list_preserves_unknown_assistant_phase(db):
    async with db.async_session() as session:
        thread = models.Thread(thread_id="thread_invalid_message_phase", version=3)
        session.add(thread)
        await session.flush()

        run = models.Run(status=schemas.RunStatus.COMPLETED, thread_id=thread.id)
        session.add(run)
        await session.flush()

        message = models.Message(
            message_status=schemas.MessageStatus.COMPLETED,
            run_id=run.id,
            thread_id=thread.id,
            output_index=1,
            role=schemas.MessageRole.ASSISTANT,
            phase="not_supported",
            created=utcnow(),
        )

        session.add(message)
        await session.commit()

        thread_id = thread.id

    async with db.async_session() as session:
        items = await build_response_input_item_list(session, thread_id=thread_id)

    assert len(items) == 1
    assert items[0]["role"] == "assistant"
    assert items[0]["phase"] == "not_supported"


@pytest.mark.asyncio
async def test_build_response_input_item_list_replays_developer_and_system_messages_as_input(
    db,
):
    async with db.async_session() as session:
        thread = models.Thread(thread_id="thread_developer_replay", version=3)
        session.add(thread)
        await session.flush()

        run = models.Run(status=schemas.RunStatus.COMPLETED, thread_id=thread.id)
        session.add(run)
        await session.flush()

        developer_message = models.Message(
            message_status=schemas.MessageStatus.COMPLETED,
            run_id=run.id,
            thread_id=thread.id,
            output_index=1,
            role=schemas.MessageRole.DEVELOPER,
            is_hidden=True,
            content=[
                models.MessagePart(
                    part_index=0,
                    type=schemas.MessagePartType.INPUT_TEXT,
                    text="Lecture chat context",
                )
            ],
            created=utcnow() - timedelta(minutes=3),
        )
        system_message = models.Message(
            message_status=schemas.MessageStatus.COMPLETED,
            run_id=run.id,
            thread_id=thread.id,
            output_index=2,
            role=schemas.MessageRole.SYSTEM,
            is_hidden=True,
            content=[
                models.MessagePart(
                    part_index=0,
                    type=schemas.MessagePartType.INPUT_TEXT,
                    text="Prioritize lecture transcript grounding.",
                )
            ],
            created=utcnow() - timedelta(minutes=2, seconds=45),
        )
        hidden_image_message = models.Message(
            message_status=schemas.MessageStatus.COMPLETED,
            run_id=run.id,
            thread_id=thread.id,
            output_index=3,
            role=schemas.MessageRole.USER,
            is_hidden=True,
            content=[
                models.MessagePart(
                    part_index=0,
                    type=schemas.MessagePartType.INPUT_IMAGE,
                    input_image_file_id="frame-file-id",
                )
            ],
            created=utcnow() - timedelta(minutes=2, seconds=30),
        )
        user_message = models.Message(
            message_status=schemas.MessageStatus.COMPLETED,
            run_id=run.id,
            thread_id=thread.id,
            output_index=4,
            role=schemas.MessageRole.USER,
            content=[
                models.MessagePart(
                    part_index=0,
                    type=schemas.MessagePartType.INPUT_TEXT,
                    text="Why switch protocols?",
                )
            ],
            created=utcnow() - timedelta(minutes=2),
        )
        assistant_message = models.Message(
            message_status=schemas.MessageStatus.COMPLETED,
            run_id=run.id,
            thread_id=thread.id,
            output_index=5,
            role=schemas.MessageRole.ASSISTANT,
            content=[
                models.MessagePart(
                    part_index=0,
                    type=schemas.MessagePartType.OUTPUT_TEXT,
                    text="Latency matters more here.",
                )
            ],
            created=utcnow() - timedelta(minutes=1),
        )

        session.add_all(
            [
                developer_message,
                system_message,
                hidden_image_message,
                user_message,
                assistant_message,
            ]
        )
        await session.commit()

        thread_id = thread.id

    async with db.async_session() as session:
        items = await build_response_input_item_list(session, thread_id=thread_id)

    assert [item["role"] for item in items] == [
        "developer",
        "system",
        "user",
        "user",
        "assistant",
    ]
    assert items[0]["content"][0]["type"] == "input_text"
    assert items[1]["content"][0]["type"] == "input_text"
    assert items[2]["content"][0]["type"] == "input_image"
    assert items[3]["content"][0]["type"] == "input_text"
    assert items[4]["content"][0]["type"] == "output_text"


@pytest.mark.asyncio
async def test_build_response_input_item_list_keeps_only_file_citations_when_present(
    db,
):
    async with db.async_session() as session:
        thread = models.Thread(
            thread_id="thread_mixed_output_text_annotations", version=3
        )
        session.add(thread)
        await session.flush()

        run = models.Run(status=schemas.RunStatus.COMPLETED, thread_id=thread.id)
        session.add(run)
        await session.flush()

        message = models.Message(
            message_status=schemas.MessageStatus.COMPLETED,
            run_id=run.id,
            thread_id=thread.id,
            output_index=1,
            role=schemas.MessageRole.ASSISTANT,
            content=[
                models.MessagePart(
                    part_index=0,
                    type=schemas.MessagePartType.OUTPUT_TEXT,
                    text="See the cited source.",
                    annotations=[
                        models.Annotation(
                            annotation_index=0,
                            type=schemas.AnnotationType.URL_CITATION,
                            url="https://example.com",
                            title="Example",
                            start_index=4,
                            end_index=9,
                        ),
                        models.Annotation(
                            annotation_index=1,
                            type=schemas.AnnotationType.FILE_CITATION,
                            file_id="file_123",
                            filename="source.pdf",
                            index=14,
                        ),
                    ],
                )
            ],
            created=utcnow(),
        )
        session.add(message)
        await session.commit()

        thread_id = thread.id

    async with db.async_session() as session:
        items = await build_response_input_item_list(session, thread_id=thread_id)

    annotations = items[0]["content"][0]["annotations"]
    assert annotations == [
        {
            "file_id": "file_123",
            "filename": "source.pdf",
            "index": 14,
            "type": "file_citation",
        }
    ]


@pytest.mark.asyncio
async def test_build_response_input_item_list_keeps_non_file_citations_when_no_file_citation(
    db,
):
    async with db.async_session() as session:
        thread = models.Thread(
            thread_id="thread_non_file_output_text_annotations", version=3
        )
        session.add(thread)
        await session.flush()

        run = models.Run(status=schemas.RunStatus.COMPLETED, thread_id=thread.id)
        session.add(run)
        await session.flush()

        message = models.Message(
            message_status=schemas.MessageStatus.COMPLETED,
            run_id=run.id,
            thread_id=thread.id,
            output_index=1,
            role=schemas.MessageRole.ASSISTANT,
            content=[
                models.MessagePart(
                    part_index=0,
                    type=schemas.MessagePartType.OUTPUT_TEXT,
                    text="See the cited page.",
                    annotations=[
                        models.Annotation(
                            annotation_index=0,
                            type=schemas.AnnotationType.URL_CITATION,
                            url="https://example.com",
                            title="Example",
                            start_index=4,
                            end_index=9,
                        ),
                    ],
                )
            ],
            created=utcnow(),
        )
        session.add(message)
        await session.commit()

        thread_id = thread.id

    async with db.async_session() as session:
        items = await build_response_input_item_list(session, thread_id=thread_id)

    annotations = items[0]["content"][0]["annotations"]
    assert [annotation["type"] for annotation in annotations] == ["url_citation"]


@pytest.mark.asyncio
async def test_build_response_input_item_list_prefers_active_container_file_citations(
    db,
):
    async with db.async_session() as session:
        thread = models.Thread(
            thread_id="thread_container_output_text_annotations", version=3
        )
        session.add(thread)
        await session.flush()

        run = models.Run(status=schemas.RunStatus.COMPLETED, thread_id=thread.id)
        session.add(run)
        await session.flush()

        base_time = utcnow() - timedelta(minutes=5)
        message = models.Message(
            message_status=schemas.MessageStatus.COMPLETED,
            run_id=run.id,
            thread_id=thread.id,
            output_index=1,
            role=schemas.MessageRole.ASSISTANT,
            content=[
                models.MessagePart(
                    part_index=0,
                    type=schemas.MessagePartType.OUTPUT_TEXT,
                    text="See the generated file.",
                    annotations=[
                        models.Annotation(
                            annotation_index=0,
                            type=schemas.AnnotationType.URL_CITATION,
                            url="https://example.com",
                            title="Example",
                            start_index=4,
                            end_index=9,
                        ),
                        models.Annotation(
                            annotation_index=1,
                            type=schemas.AnnotationType.FILE_CITATION,
                            file_id="file_search_123",
                            filename="source.pdf",
                            index=14,
                        ),
                        models.Annotation(
                            annotation_index=2,
                            type=schemas.AnnotationType.CONTAINER_FILE_CITATION,
                            file_id="cfile_123",
                            container_id="container-active-citation",
                            filename="output.csv",
                            start_index=14,
                            end_index=18,
                        ),
                    ],
                )
            ],
            created=base_time,
        )
        tool_call = models.ToolCall(
            tool_call_id="tc_active_citation",
            type=schemas.ToolCallType.CODE_INTERPRETER,
            status=schemas.ToolCallStatus.COMPLETED,
            run_id=run.id,
            thread_id=thread.id,
            output_index=2,
            code="print('ok')",
            container_id="container-active-citation",
            created=base_time + timedelta(minutes=1),
            completed=base_time + timedelta(minutes=2),
        )

        session.add_all([message, tool_call])
        await session.commit()

        thread_id = thread.id

    async with db.async_session() as session:
        items = await build_response_input_item_list(session, thread_id=thread_id)

    annotations = items[0]["content"][0]["annotations"]
    assert annotations == [
        {
            "container_id": "container-active-citation",
            "end_index": 18,
            "file_id": "cfile_123",
            "filename": "output.csv",
            "start_index": 14,
            "type": "container_file_citation",
        }
    ]


@pytest.mark.asyncio
async def test_build_response_input_item_list_skips_expired_container_file_citations(
    db,
):
    async with db.async_session() as session:
        thread = models.Thread(
            thread_id="thread_expired_container_output_text_annotations", version=3
        )
        session.add(thread)
        await session.flush()

        run = models.Run(status=schemas.RunStatus.COMPLETED, thread_id=thread.id)
        session.add(run)
        await session.flush()

        base_time = utcnow() - timedelta(hours=1)
        message = models.Message(
            message_status=schemas.MessageStatus.COMPLETED,
            run_id=run.id,
            thread_id=thread.id,
            output_index=1,
            role=schemas.MessageRole.ASSISTANT,
            content=[
                models.MessagePart(
                    part_index=0,
                    type=schemas.MessagePartType.OUTPUT_TEXT,
                    text="See the generated file.",
                    annotations=[
                        models.Annotation(
                            annotation_index=0,
                            type=schemas.AnnotationType.URL_CITATION,
                            url="https://example.com",
                            title="Example",
                            start_index=4,
                            end_index=9,
                        ),
                        models.Annotation(
                            annotation_index=1,
                            type=schemas.AnnotationType.FILE_CITATION,
                            file_id="file_search_456",
                            filename="source.pdf",
                            index=14,
                        ),
                        models.Annotation(
                            annotation_index=2,
                            type=schemas.AnnotationType.CONTAINER_FILE_CITATION,
                            file_id="cfile_456",
                            container_id="container-expired-citation",
                            filename="output.csv",
                            start_index=14,
                            end_index=18,
                        ),
                    ],
                )
            ],
            created=base_time,
        )
        tool_call = models.ToolCall(
            tool_call_id="tc_expired_citation",
            type=schemas.ToolCallType.CODE_INTERPRETER,
            status=schemas.ToolCallStatus.COMPLETED,
            run_id=run.id,
            thread_id=thread.id,
            output_index=2,
            code="print('expired')",
            container_id="container-expired-citation",
            created=base_time + timedelta(minutes=1),
            completed=base_time + timedelta(minutes=2),
        )

        session.add_all([message, tool_call])
        await session.commit()

        thread_id = thread.id

    async with db.async_session() as session:
        items = await build_response_input_item_list(session, thread_id=thread_id)

    annotations = items[0]["content"][0]["annotations"]
    assert annotations == [
        {
            "file_id": "file_search_456",
            "filename": "source.pdf",
            "index": 14,
            "type": "file_citation",
        }
    ]


@pytest.mark.asyncio
async def test_build_response_input_item_list_skips_legacy_container_file_citations(
    db,
):
    async with db.async_session() as session:
        thread = models.Thread(
            thread_id="thread_legacy_container_output_text_annotations", version=3
        )
        session.add(thread)
        await session.flush()

        run = models.Run(status=schemas.RunStatus.COMPLETED, thread_id=thread.id)
        session.add(run)
        await session.flush()

        base_time = utcnow() - timedelta(minutes=5)
        message = models.Message(
            message_status=schemas.MessageStatus.COMPLETED,
            run_id=run.id,
            thread_id=thread.id,
            output_index=1,
            role=schemas.MessageRole.ASSISTANT,
            content=[
                models.MessagePart(
                    part_index=0,
                    type=schemas.MessagePartType.OUTPUT_TEXT,
                    text="See the generated file.",
                    annotations=[
                        models.Annotation(
                            annotation_index=0,
                            type=schemas.AnnotationType.URL_CITATION,
                            url="https://example.com",
                            title="Example",
                            start_index=4,
                            end_index=9,
                        ),
                        models.Annotation(
                            annotation_index=1,
                            type=schemas.AnnotationType.FILE_CITATION,
                            file_id="file_search_legacy",
                            filename="source.pdf",
                            index=14,
                        ),
                        models.Annotation(
                            annotation_index=2,
                            type=schemas.AnnotationType.CONTAINER_FILE_CITATION,
                            file_id="file-uploaded-copy",
                            container_id="container-legacy-citation",
                            filename="output.csv",
                            start_index=14,
                            end_index=18,
                        ),
                    ],
                )
            ],
            created=base_time,
        )
        tool_call = models.ToolCall(
            tool_call_id="tc_legacy_citation",
            type=schemas.ToolCallType.CODE_INTERPRETER,
            status=schemas.ToolCallStatus.COMPLETED,
            run_id=run.id,
            thread_id=thread.id,
            output_index=2,
            code="print('legacy')",
            container_id="container-legacy-citation",
            created=base_time + timedelta(minutes=1),
            completed=base_time + timedelta(minutes=2),
        )

        session.add_all([message, tool_call])
        await session.commit()

        thread_id = thread.id

    async with db.async_session() as session:
        items = await build_response_input_item_list(session, thread_id=thread_id)

    annotations = items[0]["content"][0]["annotations"]
    assert annotations == [
        {
            "file_id": "file_search_legacy",
            "filename": "source.pdf",
            "index": 14,
            "type": "file_citation",
        }
    ]


@pytest.mark.asyncio
async def test_build_response_input_item_list_keeps_file_citation_before_file_path(
    db,
):
    async with db.async_session() as session:
        thread = models.Thread(
            thread_id="thread_file_path_with_citation_annotations", version=3
        )
        session.add(thread)
        await session.flush()

        run = models.Run(status=schemas.RunStatus.COMPLETED, thread_id=thread.id)
        session.add(run)
        await session.flush()

        message = models.Message(
            message_status=schemas.MessageStatus.COMPLETED,
            run_id=run.id,
            thread_id=thread.id,
            output_index=1,
            role=schemas.MessageRole.ASSISTANT,
            content=[
                models.MessagePart(
                    part_index=0,
                    type=schemas.MessagePartType.OUTPUT_TEXT,
                    text="See the generated file and cited source.",
                    annotations=[
                        models.Annotation(
                            annotation_index=0,
                            type=schemas.AnnotationType.FILE_PATH,
                            file_id="file_path_123",
                            index=8,
                        ),
                        models.Annotation(
                            annotation_index=1,
                            type=schemas.AnnotationType.URL_CITATION,
                            url="https://example.com",
                            title="Example",
                            start_index=31,
                            end_index=37,
                        ),
                        models.Annotation(
                            annotation_index=2,
                            type=schemas.AnnotationType.FILE_CITATION,
                            file_id="file_789",
                            filename="source.pdf",
                            index=31,
                        ),
                    ],
                )
            ],
            created=utcnow(),
        )
        session.add(message)
        await session.commit()

        thread_id = thread.id

    async with db.async_session() as session:
        items = await build_response_input_item_list(session, thread_id=thread_id)

    annotations = items[0]["content"][0]["annotations"]
    assert annotations == [
        {
            "file_id": "file_789",
            "filename": "source.pdf",
            "index": 31,
            "type": "file_citation",
        },
    ]


@pytest.mark.asyncio
async def test_build_response_input_item_list_preserves_file_path_when_no_citation(
    db,
):
    async with db.async_session() as session:
        thread = models.Thread(thread_id="thread_file_path_only_annotation", version=3)
        session.add(thread)
        await session.flush()

        run = models.Run(status=schemas.RunStatus.COMPLETED, thread_id=thread.id)
        session.add(run)
        await session.flush()

        message = models.Message(
            message_status=schemas.MessageStatus.COMPLETED,
            run_id=run.id,
            thread_id=thread.id,
            output_index=1,
            role=schemas.MessageRole.ASSISTANT,
            content=[
                models.MessagePart(
                    part_index=0,
                    type=schemas.MessagePartType.OUTPUT_TEXT,
                    text="See the generated file.",
                    annotations=[
                        models.Annotation(
                            annotation_index=0,
                            type=schemas.AnnotationType.FILE_PATH,
                            file_id="file_path_456",
                            index=8,
                        ),
                    ],
                )
            ],
            created=utcnow(),
        )
        session.add(message)
        await session.commit()

        thread_id = thread.id

    async with db.async_session() as session:
        items = await build_response_input_item_list(session, thread_id=thread_id)

    assert items[0]["content"][0]["annotations"] == [
        {
            "file_id": "file_path_456",
            "index": 8,
            "type": "file_path",
        }
    ]


@pytest.mark.asyncio
async def test_build_response_input_item_list_drops_expired_container_only_citation(
    db,
):
    async with db.async_session() as session:
        thread = models.Thread(
            thread_id="thread_expired_container_only_annotation", version=3
        )
        session.add(thread)
        await session.flush()

        run = models.Run(status=schemas.RunStatus.COMPLETED, thread_id=thread.id)
        session.add(run)
        await session.flush()

        base_time = utcnow() - timedelta(hours=1)
        message = models.Message(
            message_status=schemas.MessageStatus.COMPLETED,
            run_id=run.id,
            thread_id=thread.id,
            output_index=1,
            role=schemas.MessageRole.ASSISTANT,
            content=[
                models.MessagePart(
                    part_index=0,
                    type=schemas.MessagePartType.OUTPUT_TEXT,
                    text="See the generated file.",
                    annotations=[
                        models.Annotation(
                            annotation_index=0,
                            type=schemas.AnnotationType.CONTAINER_FILE_CITATION,
                            file_id="cfile_expired_only",
                            container_id="container-expired-only",
                            filename="output.csv",
                            start_index=8,
                            end_index=22,
                        ),
                    ],
                )
            ],
            created=base_time,
        )
        tool_call = models.ToolCall(
            tool_call_id="tc_expired_only",
            type=schemas.ToolCallType.CODE_INTERPRETER,
            status=schemas.ToolCallStatus.COMPLETED,
            run_id=run.id,
            thread_id=thread.id,
            output_index=2,
            code="print('expired')",
            container_id="container-expired-only",
            created=base_time + timedelta(minutes=1),
            completed=base_time + timedelta(minutes=2),
        )

        session.add_all([message, tool_call])
        await session.commit()

        thread_id = thread.id

    async with db.async_session() as session:
        items = await build_response_input_item_list(session, thread_id=thread_id)

    assert items[0]["content"][0]["annotations"] == []


@pytest.mark.asyncio
async def test_build_response_input_item_list_selects_citation_type_per_message_part(
    db,
):
    async with db.async_session() as session:
        thread = models.Thread(
            thread_id="thread_per_part_annotation_selection", version=3
        )
        session.add(thread)
        await session.flush()

        run = models.Run(status=schemas.RunStatus.COMPLETED, thread_id=thread.id)
        session.add(run)
        await session.flush()

        base_time = utcnow() - timedelta(minutes=5)
        message = models.Message(
            message_status=schemas.MessageStatus.COMPLETED,
            run_id=run.id,
            thread_id=thread.id,
            output_index=1,
            role=schemas.MessageRole.ASSISTANT,
            content=[
                models.MessagePart(
                    part_index=0,
                    type=schemas.MessagePartType.OUTPUT_TEXT,
                    text="See the cited source.",
                    annotations=[
                        models.Annotation(
                            annotation_index=0,
                            type=schemas.AnnotationType.URL_CITATION,
                            url="https://example.com/one",
                            title="Example One",
                            start_index=8,
                            end_index=14,
                        ),
                        models.Annotation(
                            annotation_index=1,
                            type=schemas.AnnotationType.FILE_CITATION,
                            file_id="file_part_one",
                            filename="source.pdf",
                            index=8,
                        ),
                    ],
                ),
                models.MessagePart(
                    part_index=1,
                    type=schemas.MessagePartType.OUTPUT_TEXT,
                    text="See the generated file.",
                    annotations=[
                        models.Annotation(
                            annotation_index=0,
                            type=schemas.AnnotationType.URL_CITATION,
                            url="https://example.com/two",
                            title="Example Two",
                            start_index=8,
                            end_index=17,
                        ),
                        models.Annotation(
                            annotation_index=1,
                            type=schemas.AnnotationType.CONTAINER_FILE_CITATION,
                            file_id="cfile_part_two",
                            container_id="container-per-part",
                            filename="output.csv",
                            start_index=8,
                            end_index=22,
                        ),
                    ],
                ),
            ],
            created=base_time,
        )
        tool_call = models.ToolCall(
            tool_call_id="tc_per_part",
            type=schemas.ToolCallType.CODE_INTERPRETER,
            status=schemas.ToolCallStatus.COMPLETED,
            run_id=run.id,
            thread_id=thread.id,
            output_index=2,
            code="print('ok')",
            container_id="container-per-part",
            created=base_time + timedelta(minutes=1),
            completed=base_time + timedelta(minutes=2),
        )

        session.add_all([message, tool_call])
        await session.commit()

        thread_id = thread.id

    async with db.async_session() as session:
        items = await build_response_input_item_list(session, thread_id=thread_id)

    assert [
        annotation["type"] for annotation in items[0]["content"][0]["annotations"]
    ] == ["file_citation"]
    assert [
        annotation["type"] for annotation in items[0]["content"][1]["annotations"]
    ] == ["container_file_citation"]


@pytest.mark.asyncio
async def test_build_response_input_item_list_treats_exact_19_minute_container_as_active(
    db,
    monkeypatch,
):
    fixed_now = utcnow()
    monkeypatch.setattr(ai, "utcnow", lambda: fixed_now)

    async with db.async_session() as session:
        thread = models.Thread(
            thread_id="thread_exact_container_expiration_boundary", version=3
        )
        session.add(thread)
        await session.flush()

        run = models.Run(status=schemas.RunStatus.COMPLETED, thread_id=thread.id)
        session.add(run)
        await session.flush()

        completed_time = fixed_now - timedelta(minutes=19)
        message = models.Message(
            message_status=schemas.MessageStatus.COMPLETED,
            run_id=run.id,
            thread_id=thread.id,
            output_index=1,
            role=schemas.MessageRole.ASSISTANT,
            content=[
                models.MessagePart(
                    part_index=0,
                    type=schemas.MessagePartType.OUTPUT_TEXT,
                    text="See the generated file.",
                    annotations=[
                        models.Annotation(
                            annotation_index=0,
                            type=schemas.AnnotationType.URL_CITATION,
                            url="https://example.com",
                            title="Example",
                            start_index=8,
                            end_index=17,
                        ),
                        models.Annotation(
                            annotation_index=1,
                            type=schemas.AnnotationType.FILE_CITATION,
                            file_id="file_boundary",
                            filename="source.pdf",
                            index=8,
                        ),
                        models.Annotation(
                            annotation_index=2,
                            type=schemas.AnnotationType.CONTAINER_FILE_CITATION,
                            file_id="cfile_boundary",
                            container_id="container-boundary",
                            filename="output.csv",
                            start_index=8,
                            end_index=22,
                        ),
                    ],
                )
            ],
            created=completed_time - timedelta(minutes=1),
        )
        tool_call = models.ToolCall(
            tool_call_id="tc_boundary",
            type=schemas.ToolCallType.CODE_INTERPRETER,
            status=schemas.ToolCallStatus.COMPLETED,
            run_id=run.id,
            thread_id=thread.id,
            output_index=2,
            code="print('boundary')",
            container_id="container-boundary",
            created=completed_time - timedelta(minutes=1),
            completed=completed_time,
        )

        session.add_all([message, tool_call])
        await session.commit()

        thread_id = thread.id

    async with db.async_session() as session:
        items = await build_response_input_item_list(session, thread_id=thread_id)

    annotations = items[0]["content"][0]["annotations"]
    assert annotations == [
        {
            "container_id": "container-boundary",
            "end_index": 22,
            "file_id": "cfile_boundary",
            "filename": "output.csv",
            "start_index": 8,
            "type": "container_file_citation",
        }
    ]


@pytest.mark.asyncio
async def test_build_response_input_item_list_ignores_incomplete_tool_calls_for_container_freshness(
    db,
):
    async with db.async_session() as session:
        thread = models.Thread(
            thread_id="thread_incomplete_container_freshness", version=3
        )
        session.add(thread)
        await session.flush()

        run = models.Run(status=schemas.RunStatus.COMPLETED, thread_id=thread.id)
        session.add(run)
        await session.flush()

        now = utcnow()
        message = models.Message(
            message_status=schemas.MessageStatus.COMPLETED,
            run_id=run.id,
            thread_id=thread.id,
            output_index=1,
            role=schemas.MessageRole.ASSISTANT,
            content=[
                models.MessagePart(
                    part_index=0,
                    type=schemas.MessagePartType.OUTPUT_TEXT,
                    text="See the generated file.",
                    annotations=[
                        models.Annotation(
                            annotation_index=0,
                            type=schemas.AnnotationType.CONTAINER_FILE_CITATION,
                            file_id="cfile_incomplete",
                            container_id="container-incomplete",
                            filename="output.csv",
                            start_index=8,
                            end_index=22,
                        ),
                    ],
                )
            ],
            created=now,
        )
        tool_call = models.ToolCall(
            tool_call_id="tc_incomplete_freshness",
            type=schemas.ToolCallType.CODE_INTERPRETER,
            status=schemas.ToolCallStatus.INCOMPLETE,
            run_id=run.id,
            thread_id=thread.id,
            output_index=2,
            code="print('still running')",
            container_id="container-incomplete",
            created=now,
        )

        session.add_all([message, tool_call])
        await session.commit()

        thread_id = thread.id

    async with db.async_session() as session:
        items = await build_response_input_item_list(session, thread_id=thread_id)

    assert items[0]["content"][0]["annotations"] == []


@pytest.mark.asyncio
async def test_build_response_input_item_list_can_build_user_assistant_messages_only(
    db,
):
    async with db.async_session() as session:
        thread = models.Thread(thread_id="thread_v4_context_filter", version=3)
        session.add(thread)
        await session.flush()

        prior_run = models.Run(status=schemas.RunStatus.COMPLETED, thread_id=thread.id)
        current_run = models.Run(status=schemas.RunStatus.PENDING, thread_id=thread.id)
        session.add_all([prior_run, current_run])
        await session.flush()

        prior_developer_message = models.Message(
            message_status=schemas.MessageStatus.COMPLETED,
            run_id=prior_run.id,
            thread_id=thread.id,
            output_index=1,
            role=schemas.MessageRole.DEVELOPER,
            is_hidden=True,
            content=[
                models.MessagePart(
                    part_index=0,
                    type=schemas.MessagePartType.INPUT_TEXT,
                    text="Prior lecture context",
                )
            ],
            created=utcnow() - timedelta(minutes=3),
        )
        current_developer_message = models.Message(
            message_status=schemas.MessageStatus.COMPLETED,
            run_id=current_run.id,
            thread_id=thread.id,
            output_index=5,
            role=schemas.MessageRole.DEVELOPER,
            is_hidden=True,
            content=[
                models.MessagePart(
                    part_index=0,
                    type=schemas.MessagePartType.INPUT_TEXT,
                    text="Current lecture context",
                )
            ],
            created=utcnow() - timedelta(minutes=2),
        )
        prior_hidden_image_message = models.Message(
            message_status=schemas.MessageStatus.COMPLETED,
            run_id=prior_run.id,
            thread_id=thread.id,
            output_index=3,
            role=schemas.MessageRole.USER,
            is_hidden=True,
            content=[
                models.MessagePart(
                    part_index=0,
                    type=schemas.MessagePartType.INPUT_IMAGE,
                    input_image_file_id="prior-frame-file-id",
                )
            ],
            created=utcnow() - timedelta(minutes=1, seconds=30),
        )
        user_message = models.Message(
            message_status=schemas.MessageStatus.COMPLETED,
            run_id=current_run.id,
            thread_id=thread.id,
            output_index=4,
            role=schemas.MessageRole.USER,
            content=[
                models.MessagePart(
                    part_index=0,
                    type=schemas.MessagePartType.INPUT_TEXT,
                    text="What is happening here?",
                )
            ],
            created=utcnow() - timedelta(minutes=1),
        )
        session.add_all(
            [
                prior_developer_message,
                current_developer_message,
                prior_hidden_image_message,
                user_message,
            ]
        )
        await session.commit()

        thread_id = thread.id
        current_run_id = current_run.id

    async with db.async_session() as session:
        items = await build_response_input_item_list(
            session,
            thread_id=thread_id,
            current_run_id=current_run_id,
            user_assistant_messages_only=True,
        )

    assert [item["role"] for item in items] == ["developer", "user", "user"]
    assert items[0]["content"][0]["text"] == "Current lecture context"
    assert items[1]["content"][0]["type"] == "input_image"
    assert items[2]["content"][0]["text"] == "What is happening here?"


def test_get_known_response_message_phase_returns_known_phase_only():
    assert (
        ai.get_known_response_message_phase("commentary")
        == schemas.MessagePhase.COMMENTARY
    )
    assert ai.get_known_response_message_phase("future_phase") is None


def test_get_response_message_phase_value_preserves_unknown_sdk_phase():
    assert ai.get_response_message_phase_value("future_phase") == "future_phase"
    assert ai.get_response_message_phase_value(None) is None
