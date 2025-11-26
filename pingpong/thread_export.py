import io
import logging
from datetime import datetime, timedelta, timezone

from fpdf import FPDF
import openai
from sqlalchemy.ext.asyncio import AsyncSession

import pingpong.models as models
import pingpong.schemas as schemas
from pingpong.ai import process_message_content, process_message_content_v3
from pingpong.config import config
from pingpong.time import utcnow

logger = logging.getLogger(__name__)

OpenAIClientType = openai.AsyncClient | openai.AsyncAzureOpenAI


async def _collect_messages_v1_v2(
    openai_client: OpenAIClientType,
    thread: models.Thread,
) -> list[schemas.ThreadMessage]:
    messages: list[schemas.ThreadMessage] = []
    after: str | None = None

    while True:
        response = await openai_client.beta.threads.messages.list(
            thread.thread_id, limit=100, order="asc", after=after
        )
        messages.extend(
            schemas.ThreadMessage.model_validate(msg.model_dump())
            for msg in response.data
        )
        if not response.has_more:
            break
        after = response.last_id

    return messages


async def _collect_messages_v3(
    session: AsyncSession,
    thread: models.Thread,
) -> tuple[list[models.Message], list[models.ToolCall], list[models.ReasoningStep]]:
    run_ids = [run.id async for run in models.Run.get_runs_by_thread_id(session, thread.id)]
    return await models.Thread.list_messages_tool_calls(
        session,
        thread.id,
        run_ids=run_ids,
        order="asc",
    )


def _render_pdf(
    thread: models.Thread,
    transcript: list[tuple[str, datetime, str]],
    generated_at: datetime,
) -> bytes:
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 16)
    pdf.cell(0, 10, "Thread Conversation Export", ln=True)
    pdf.set_font("Helvetica", size=11)
    pdf.cell(0, 8, f"Thread: {thread.name or 'Untitled'}", ln=True)
    pdf.cell(0, 8, f"Generated: {generated_at.isoformat()}", ln=True)
    pdf.ln(4)

    for role, created, content in transcript:
        pdf.set_font("Helvetica", "B", 12)
        timestamp = created.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
        pdf.multi_cell(0, 8, f"{role} — {timestamp}")
        pdf.set_font("Helvetica", size=11)
        pdf.multi_cell(0, 7, content or "[No content provided]")
        pdf.ln(3)

    pdf_bytes = pdf.output(dest="S").encode("latin-1")
    return pdf_bytes


def _format_v3_attachments(message: models.Message) -> str | None:
    attachments: list[str] = []

    if message.file_search_attachments:
        attachments.extend(
            f"File search attachment: {file.name or file.file_id}"
            for file in message.file_search_attachments
        )
    if message.code_interpreter_attachments:
        attachments.extend(
            f"Code interpreter attachment: {file.name or file.file_id}"
            for file in message.code_interpreter_attachments
        )

    if not attachments:
        return None

    return "\n".join(attachments)


def _format_tool_call(tool_call: models.ToolCall) -> str:
    header = f"Tool call ({tool_call.type.value.replace('_', ' ').title()}) — Status: {tool_call.status.value}"

    if tool_call.type == schemas.ToolCallType.FILE_SEARCH:
        details = [f"Query: {tool_call.queries or 'N/A'}"]
        for result in tool_call.results:
            summary = result.text or ""
            filename = result.filename or result.file_id or "Unknown file"
            prefix = f"Result: {filename}"
            if result.score is not None:
                prefix += f" (score: {result.score:.2f})"
            details.append(f"{prefix}\n{summary}" if summary else prefix)
        return "\n".join([header, *details])

    if tool_call.type == schemas.ToolCallType.CODE_INTERPRETER:
        details = []
        if tool_call.code:
            details.append(f"Code:\n{tool_call.code}")
        for output in tool_call.outputs:
            match output.output_type:
                case schemas.CodeInterpreterOutputType.LOGS:
                    details.append(f"Logs:\n{output.logs or ''}")
                case schemas.CodeInterpreterOutputType.IMAGE:
                    details.append(f"Image output URL: {output.url or 'Unavailable'}")
        return "\n".join([header, *details]) if details else header

    if tool_call.type == schemas.ToolCallType.WEB_SEARCH:
        details = []
        for action in tool_call.web_search_actions:
            action_line = f"Action: {action.type.value.replace('_', ' ').title()}"
            if action.query:
                action_line += f" — Query: {action.query}"
            if action.pattern:
                action_line += f" — Pattern: {action.pattern}"
            if action.url:
                action_line += f" — URL: {action.url}"
            details.append(action_line)
            for source in action.sources:
                details.append(f"  Source: {source.name or source.url or 'Unknown source'}")
        return "\n".join([header, *details]) if details else header

    return header


def _format_reasoning_step(reasoning_step: models.ReasoningStep) -> str:
    header = "Reasoning"
    duration = models.ReasoningStep.format_thought_for(
        reasoning_step.created, reasoning_step.updated
    )
    if duration:
        header += f" — Took {duration}"

    summaries = [part.summary_text for part in reasoning_step.summary_parts if part.summary_text]
    contents = [
        part.content_text for part in reasoning_step.content_parts if part.content_text
    ]
    details: list[str] = []
    if summaries:
        details.append("Summary:\n" + "\n".join(summaries))
    if contents:
        details.append("Details:\n" + "\n".join(contents))

    return "\n".join([header, *details]) if details else header


def _format_message_content_v3(
    message: models.Message, file_names: dict[str, str]
) -> str:
    content = process_message_content_v3(message.content, file_names)
    attachments = _format_v3_attachments(message)
    if attachments:
        return "\n\n".join([content, attachments]) if content else attachments
    return content


async def _build_transcript(
    session: AsyncSession,
    thread: models.Thread,
    openai_client: OpenAIClientType,
) -> list[tuple[str, datetime, str]]:
    _, file_names, _ = await models.Thread.get_thread_components(session, thread.id)

    if thread.version <= 2:
        messages = await _collect_messages_v1_v2(openai_client, thread)
        transcript: list[tuple[str, datetime, str]] = []
        for message in messages:
            created = datetime.fromtimestamp(message.created_at, tz=timezone.utc)
            content = process_message_content(message.content, file_names)
            transcript.append((message.role.title(), created, content))
        return transcript

    messages_v3, tool_calls, reasoning_steps = await _collect_messages_v3(
        session, thread
    )
    tool_calls_by_index: dict[int, list[models.ToolCall]] = {}
    for tool_call in tool_calls:
        tool_calls_by_index.setdefault(tool_call.output_index, []).append(tool_call)

    reasoning_by_index: dict[int, list[models.ReasoningStep]] = {}
    for reasoning in reasoning_steps:
        reasoning_by_index.setdefault(reasoning.output_index, []).append(reasoning)

    transcript_v3: list[tuple[str, datetime, str]] = []
    for message in messages_v3:
        created = message.created
        base_content = _format_message_content_v3(message, file_names)
        extras: list[str] = []
        for tool_call in tool_calls_by_index.get(message.output_index, []):
            extras.append(_format_tool_call(tool_call))
        for reasoning in reasoning_by_index.get(message.output_index, []):
            extras.append(_format_reasoning_step(reasoning))

        combined_content_parts = [part for part in [base_content, *extras] if part]
        combined_content = "\n\n".join(combined_content_parts)

        role = message.role.title() if isinstance(message.role, str) else str(message.role)
        transcript_v3.append((role, created, combined_content))

    return transcript_v3


async def generate_thread_pdf_export(
    export_id: int,
    openai_client: OpenAIClientType,
    nowfn=utcnow,
) -> None:
    async with config.db.driver.async_session() as session:
        export = await models.ThreadExport.get_by_id(session, export_id)
        if not export:
            return

        await models.ThreadExport.mark_processing(session, export_id)
        await session.commit()

        try:
            thread = await models.Thread.get_by_id(session, export.thread_id)
            if not thread:
                raise ValueError("Thread not found for export")

            transcript = await _build_transcript(session, thread, openai_client)
            pdf_bytes = _render_pdf(thread, transcript, nowfn())

            filename = f"thread_{thread.id}_export_{export.id}.pdf"
            await config.artifact_store.store.put(
                filename, io.BytesIO(pdf_bytes), "application/pdf"
            )
            s3_file = await models.S3File.create(session, key=filename)

            await models.ThreadExport.mark_ready(
                session,
                export_id,
                s3_file.id,
                completed_at=nowfn(),
                expires_at=nowfn() + timedelta(hours=23),
            )
            await session.commit()
        except Exception:
            await models.ThreadExport.mark_failed(session, export_id)
            await session.commit()
            logger.exception("Failed to generate PDF export for thread %s", export.thread_id)
            return


async def expire_export_if_needed(
    export: models.ThreadExport,
    session: AsyncSession,
    now: datetime,
) -> models.ThreadExport:
    if export.status == schemas.ThreadExportStatus.EXPIRED:
        return export

    if export.expires_at and now >= export.expires_at:
        await models.ThreadExport.mark_expired(session, export.id)
        await session.refresh(export)

    return export
