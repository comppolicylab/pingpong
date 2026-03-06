import json
from datetime import datetime, timedelta, timezone

from pingpong import models, schemas
from pingpong.ai import build_export_rows_v3, process_tool_call_content_v3


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

    report = json.loads(process_tool_call_content_v3(tool_call))

    assert report["server_label"] == "weather"
    assert report["server_name"] == "Weather MCP"
    assert report["tool_name"] == "lookup_weather"
    assert report["arguments"] == {"location": "Boston"}
    assert report["output"] == {"forecast": "sunny"}
    assert report["error"] == {"message": "upstream timeout"}


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
                text="Week 3 deadline",
                attributes='{"page":3}',
            )
        ],
    )

    report = json.loads(process_tool_call_content_v3(tool_call))

    assert report["queries"] == ["syllabus", "deadline"]
    assert report["results"] == [
        {
            "attributes": {"page": 3},
            "file_id": "file_1",
            "filename": "syllabus.pdf",
            "score": 0.91,
            "text": "Week 3 deadline",
        }
    ]


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
        ],
    )

    report = json.loads(process_tool_call_content_v3(tool_call))

    assert report["actions"] == [
        {
            "query": "pingpong export",
            "sources": [
                {
                    "name": "Example Report",
                    "url": "https://example.com/report",
                }
            ],
            "type": "search",
        },
        {
            "sources": [],
            "type": "open_page",
            "url": "https://example.com/report",
        },
    ]


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

    report = json.loads(process_tool_call_content_v3(tool_call))

    assert report["server_label"] == "weather"
    assert report["server_name"] == "Weather MCP"
    assert report["tools"] == [
        {
            "annotations": {"readOnlyHint": True},
            "description": "Look up current weather",
            "input_schema": {
                "properties": {"location": {"type": "string"}},
                "type": "object",
            },
            "name": "lookup_weather",
        }
    ]


def test_build_export_rows_v3_interleaves_messages_and_tool_calls():
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
    assistant_message = make_message(
        role=schemas.MessageRole.ASSISTANT,
        output_index=3,
        created=NOW + timedelta(seconds=2),
        text="The answer is 42.",
        part_type=schemas.MessagePartType.OUTPUT_TEXT,
    )

    rows = build_export_rows_v3(
        [assistant_message, user_message], [tool_call], file_names={}
    )

    assert [row[0] for row in rows] == [
        "user",
        "code_interpreter_call",
        "assistant",
    ]
    assert rows[0][2] == "What is 6 * 7?"
    assert rows[2][2] == "The answer is 42."

    tool_report = json.loads(rows[1][2])
    assert tool_report["code"] == "print(6 * 7)"
    assert tool_report["container_id"] == "container_1"
    assert tool_report["outputs"] == [
        {"logs": "42", "type": "logs"},
        {"type": "image", "url": "https://example.com/chart.png"},
    ]
