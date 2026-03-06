from datetime import datetime, timedelta, timezone

from pingpong import models, schemas
from pingpong.config import config
from pingpong.ai import (
    build_export_rows_v3,
    process_message_content_v3,
    process_reasoning_content_v3,
    process_tool_call_content_v3,
)


NOW = datetime(2024, 1, 1, tzinfo=timezone.utc)


def make_tool_call(
    tool_type: schemas.ToolCallType,
    output_index: int,
    created: datetime,
    **kwargs,
) -> models.ToolCall:
    return models.ToolCall(
        tool_call_id=f"tc_{output_index}",
        type=tool_type,
        status=kwargs.pop("status", schemas.ToolCallStatus.COMPLETED),
        run_id=kwargs.pop("run_id", 1),
        thread_id=kwargs.pop("thread_id", 1),
        output_index=output_index,
        created=created,
        **kwargs,
    )


def make_message(
    role: schemas.MessageRole,
    output_index: int,
    created: datetime,
    text: str,
    part_type: schemas.MessagePartType,
) -> models.Message:
    return models.Message(
        message_status=schemas.MessageStatus.COMPLETED,
        run_id=1,
        thread_id=1,
        output_index=output_index,
        role=role,
        created=created,
        content=[
            models.MessagePart(
                type=part_type,
                part_index=0,
                text=text,
            )
        ],
    )


def make_reasoning_step(
    output_index: int,
    created: datetime,
    updated: datetime | None = None,
    **kwargs,
) -> models.ReasoningStep:
    return models.ReasoningStep(
        id=kwargs.pop("id", output_index),
        reasoning_id=kwargs.pop("reasoning_id", f"rs_{output_index}"),
        run_id=kwargs.pop("run_id", 1),
        thread_id=kwargs.pop("thread_id", 1),
        output_index=output_index,
        status=kwargs.pop("status", schemas.ReasoningStatus.COMPLETED),
        created=created,
        updated=updated or created,
        summary_parts=kwargs.pop("summary_parts", []),
        **kwargs,
    )


def test_process_tool_call_content_v3_includes_full_mcp_input_output():
    tool_call = make_tool_call(
        schemas.ToolCallType.MCP_SERVER,
        output_index=1,
        created=NOW,
        status=schemas.ToolCallStatus.FAILED,
        mcp_server_tool=models.MCPServerTool(
            server_label="weather",
            display_name="Weather MCP",
        ),
        mcp_tool_name="lookup_weather",
        mcp_arguments='{"location":"Boston"}',
        mcp_output='{"forecast":"sunny"}',
        error='{"message":"upstream timeout"}',
    )

    assert process_tool_call_content_v3(tool_call) == (
        "[MCP Server Call]\n"
        "Called server: Weather MCP\n"
        "Used tool: lookup_weather\n\n"
        'Call arguments: {"location": "Boston"}\n'
        'Tool outputs: {"forecast": "sunny"}'
    )


def test_process_tool_call_content_v3_includes_file_search_results_and_attributes():
    tool_call = make_tool_call(
        schemas.ToolCallType.FILE_SEARCH,
        output_index=1,
        created=NOW,
        queries='["syllabus","deadline"]',
        results=[
            models.FileSearchCallResult(
                file_id="file_1",
                filename="syllabus.pdf",
                score=0.91,
                text="Week 3\r\ndeadline",
                attributes='{"page":3}',
            )
        ],
    )

    assert process_tool_call_content_v3(tool_call) == (
        "[File Search]\n"
        'Queries: "syllabus", "deadline"\n\n'
        "[Results.1]\n"
        "File name: syllabus.pdf\n"
        "Relevancy score: 0.91\n"
        "Relevant excerpt: Week 3\ndeadline"
    )


def test_process_tool_call_content_v3_includes_web_search_actions_and_sources():
    tool_call = make_tool_call(
        schemas.ToolCallType.WEB_SEARCH,
        output_index=1,
        created=NOW,
        web_search_actions=[
            models.WebSearchCallAction(
                type=schemas.WebSearchActionType.SEARCH,
                query="pingpong export",
                sources=[
                    models.WebSearchCallSearchSource(
                        url="https://example.com/report",
                        name="Example Report",
                    )
                ],
            ),
            models.WebSearchCallAction(
                type=schemas.WebSearchActionType.OPEN_PAGE,
                url="https://example.com/report",
            ),
            models.WebSearchCallAction(
                type=schemas.WebSearchActionType.FIND,
                url="https://example.com/report",
                pattern="export",
            ),
        ],
    )

    assert process_tool_call_content_v3(tool_call) == (
        "[Web Search]\n"
        "Action type: Search\n"
        "Query: pingpong export\n\n"
        "Sources:\n"
        '- "Example Report" | https://example.com/report\n\n'
        "[Web Search]\n"
        "Action type: Open Page\n"
        "URL: https://example.com/report\n\n"
        "[Web Search]\n"
        "Action type: Find\n"
        "URL: https://example.com/report\n"
        "Pattern: export"
    )


def test_process_tool_call_content_v3_includes_mcp_list_tools_details():
    tool_call = make_tool_call(
        schemas.ToolCallType.MCP_LIST_TOOLS,
        output_index=1,
        created=NOW,
        mcp_server_tool=models.MCPServerTool(
            server_label="weather",
            display_name="Weather MCP",
        ),
        mcp_tools_listed=[
            models.MCPListToolsTool(
                name="lookup_weather",
                description="Look up current weather",
                input_schema='{"type":"object","properties":{"location":{"type":"string"}}}',
                annotations='{"readOnlyHint":true}',
            )
        ],
    )

    assert process_tool_call_content_v3(tool_call) == (
        "[MCP List Tools Call]\n"
        "Called server: Weather MCP\n"
        'Tools returned: "lookup_weather"\n\n'
        'Tool details: [{"name": "lookup_weather", "description": "Look up current weather", "input_schema": {"type": "object", "properties": {"location": {"type": "string"}}}, "annotations": {"readOnlyHint": true}}]'
    )


def test_process_tool_call_content_v3_formats_code_interpreter_block():
    tool_call = make_tool_call(
        schemas.ToolCallType.CODE_INTERPRETER,
        output_index=2,
        created=NOW,
        code="print(6 * 7)",
        outputs=[
            models.CodeInterpreterCallOutput(
                output_type=schemas.CodeInterpreterOutputType.LOGS,
                logs="42",
            ),
            models.CodeInterpreterCallOutput(
                output_type=schemas.CodeInterpreterOutputType.IMAGE,
                url="https://example.com/chart.png",
            ),
        ],
    )

    assert process_tool_call_content_v3(
        tool_call,
        [("report.csv", "https://example.com/report.csv")],
    ) == (
        "[Code Interpreter Call]\n"
        "Code run:\n"
        "print(6 * 7)\n\n"
        "Outputs:\n"
        "Logs: 42\n"
        "Image: [Generated Image]\n"
        "File: report.csv (https://example.com/report.csv)"
    )


def test_process_reasoning_content_v3_includes_time_spent_and_sorted_summaries():
    reasoning_step = make_reasoning_step(
        output_index=4,
        created=NOW,
        updated=NOW + timedelta(minutes=2, seconds=5),
        summary_parts=[
            models.ReasoningSummaryPart(
                id=42,
                part_index=1,
                summary_text="Second summary",
            ),
            models.ReasoningSummaryPart(
                id=41,
                part_index=0,
                summary_text="First summary",
            ),
        ],
    )

    assert process_reasoning_content_v3(reasoning_step) == (
        "[Reasoning]\nThought for 2 minutes\nSummary: First summary\nSecond summary"
    )


def test_process_message_content_v3_links_container_file_citations():
    message = models.Message(
        message_status=schemas.MessageStatus.COMPLETED,
        run_id=1,
        thread_id=20,
        output_index=1,
        role=schemas.MessageRole.ASSISTANT,
        created=NOW,
        content=[
            models.MessagePart(
                type=schemas.MessagePartType.OUTPUT_TEXT,
                part_index=0,
                text="Generated chart",
                annotations=[
                    models.Annotation(
                        type=schemas.AnnotationType.CONTAINER_FILE_CITATION,
                        annotation_index=0,
                        filename="chart.png",
                        vision_file_object_id=77,
                    )
                ],
            )
        ],
    )

    assert process_message_content_v3(
        message,
        file_names={},
        class_id=10,
        thread_id=20,
    ) == ("Generated chart\n [Code Interpreter Output File Annotation: chart.png] ")


def test_process_message_content_v3_notes_user_uploads():
    message = models.Message(
        message_status=schemas.MessageStatus.COMPLETED,
        run_id=1,
        thread_id=20,
        output_index=1,
        role=schemas.MessageRole.USER,
        created=NOW,
        content=[
            models.MessagePart(
                type=schemas.MessagePartType.INPUT_TEXT,
                part_index=0,
                text="Here are my files",
                annotations=[],
            )
        ],
        file_search_attachments=[
            models.File(id=11, name="policy.pdf"),
        ],
        code_interpreter_attachments=[
            models.File(id=12, name="data.csv"),
            models.File(id=11, name="policy.pdf"),
        ],
    )

    assert process_message_content_v3(
        message,
        file_names={},
        class_id=10,
        thread_id=20,
    ) == (
        "Here are my files\n\n"
        "[Uploads]\n"
        "- data.csv [code_interpreter]\n"
        "- policy.pdf [code_interpreter, file_search]"
    )


def test_build_export_rows_v3_interleaves_messages_tool_calls_and_reasoning():
    user_message = make_message(
        role=schemas.MessageRole.USER,
        output_index=1,
        created=NOW,
        text="What is 6 * 7?",
        part_type=schemas.MessagePartType.INPUT_TEXT,
    )
    tool_call = make_tool_call(
        schemas.ToolCallType.CODE_INTERPRETER,
        output_index=2,
        created=NOW + timedelta(seconds=1),
        code="print(6 * 7)",
        container_id="container_1",
        outputs=[
            models.CodeInterpreterCallOutput(
                output_type=schemas.CodeInterpreterOutputType.LOGS,
                logs="42",
            ),
            models.CodeInterpreterCallOutput(
                output_type=schemas.CodeInterpreterOutputType.IMAGE,
                url="https://example.com/chart.png",
            ),
        ],
    )
    reasoning_step = make_reasoning_step(
        output_index=3,
        created=NOW + timedelta(seconds=2),
        updated=NOW + timedelta(seconds=7),
        summary_parts=[
            models.ReasoningSummaryPart(
                id=301,
                part_index=0,
                summary_text="Calculated the multiplication directly.",
            )
        ],
    )
    assistant_message = make_message(
        role=schemas.MessageRole.ASSISTANT,
        output_index=4,
        created=NOW + timedelta(seconds=3),
        text="The answer is 42.",
        part_type=schemas.MessagePartType.OUTPUT_TEXT,
    )

    rows = build_export_rows_v3(
        [assistant_message, user_message],
        [tool_call],
        [reasoning_step],
        class_id=10,
        thread_id=1,
        file_names={},
    )

    assert [row[0] for row in rows] == [
        "user",
        "assistant",
        "assistant",
        "assistant",
    ]
    assert rows[0][2] == "What is 6 * 7?"
    assert rows[3][2] == "The answer is 42."

    assert rows[1][2] == (
        "[Code Interpreter Call]\n"
        "Code run:\n"
        "print(6 * 7)\n\n"
        "Outputs:\n"
        "Logs: 42\n"
        "Image: [Generated Image]"
    )

    assert rows[2][2] == (
        "[Reasoning]\n"
        "Thought for 5 seconds\n"
        "Summary: Calculated the multiplication directly."
    )


def test_build_export_rows_v3_includes_code_interpreter_file_download_links():
    tool_call = make_tool_call(
        schemas.ToolCallType.CODE_INTERPRETER,
        output_index=2,
        created=NOW,
        code="print('done')",
        outputs=[],
    )
    assistant_message = models.Message(
        message_status=schemas.MessageStatus.COMPLETED,
        run_id=1,
        thread_id=20,
        output_index=2,
        role=schemas.MessageRole.ASSISTANT,
        created=NOW + timedelta(seconds=1),
        content=[
            models.MessagePart(
                type=schemas.MessagePartType.OUTPUT_TEXT,
                part_index=0,
                text="Generated report",
                annotations=[
                    models.Annotation(
                        type=schemas.AnnotationType.CONTAINER_FILE_CITATION,
                        annotation_index=0,
                        filename="report.csv",
                        file_object_id=99,
                    )
                ],
            )
        ],
    )

    rows = build_export_rows_v3(
        [assistant_message],
        [tool_call],
        [],
        class_id=10,
        thread_id=20,
        file_names={},
    )

    assert rows[0][2] == (
        "[Code Interpreter Call]\n"
        "Code run:\n"
        "print('done')\n\n"
        "Outputs:\n"
        f"File: report.csv ({config.url('/api/v1/class/10/thread/20/file/99')})"
    )


def test_process_reasoning_content_v3_uses_none_generated_when_summary_missing():
    reasoning_step = make_reasoning_step(
        output_index=5,
        created=NOW,
        updated=NOW + timedelta(seconds=3),
        summary_parts=[],
    )

    assert process_reasoning_content_v3(reasoning_step) == (
        "[Reasoning]\nThought for 3 seconds\nSummary: None generated"
    )
