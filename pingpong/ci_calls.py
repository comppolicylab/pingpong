from openai import AsyncClient
from openai.pagination import AsyncCursorPage
from openai.types.beta.assistant_tool import CodeInterpreterTool
from openai.types.beta.threads import Run
from openai.types.beta.threads.runs import RunStep
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import CodeInterpreterCall, Thread
from typing import AsyncGenerator


async def get_threads_by_class_id(
    session: AsyncSession,
    class_id: int,
) -> AsyncGenerator["Thread", None]:
    condition = Thread.class_id == int(class_id)
    stmt = select(Thread).where(condition)
    result = await session.execute(stmt)
    for row in result:
        yield row.Thread


async def migrate_thread_ci_calls(
    openai_client: AsyncClient,
    session: AsyncSession,
    thread_id: str,
    thread_obj_id: int,
) -> None:
    """
    Migrate code interpreter calls for a thread.

    Args:
        openai_client (AsyncClient): OpenAI client
        session (AsyncSession): SQLAlchemy session
        thread_id (str): thread id
    """
    runs_result = await openai_client.beta.threads.runs.list(thread_id)
    await process_runs(openai_client, session, runs_result, thread_obj_id)

    while runs_result.has_next_page():
        runs_result = await runs_result.get_next_page()
        await process_runs(openai_client, session, runs_result, thread_obj_id)


async def process_runs(
    openai_client: AsyncClient,
    session: AsyncSession,
    runs_result: AsyncCursorPage[Run],
    thread_obj_id: int,
) -> None:
    async for run in runs_result:
        if CodeInterpreterTool(type="code_interpreter") not in run.tools:
            continue
        run_steps = await openai_client.beta.threads.runs.steps.list(
            run.id, thread_id=run.thread_id, order="desc"
        )
        await process_run_steps(session, run_steps, thread_obj_id)

        while run_steps.has_next_page():
            run_steps = await run_steps.get_next_page()
            await process_run_steps(session, run_steps, thread_obj_id)


async def process_run_steps(
    session: AsyncSession,
    run_steps: AsyncCursorPage[RunStep],
    thread_obj_id: int,
) -> None:
    async for run_step in run_steps:
        if run_step.type != "tool_calls":
            continue
        for tool_call in run_step.step_details.tool_calls:
            if tool_call.type != "code_interpreter":
                continue
            data = {
                "version": 2,
                "run_id": run_step.run_id,
                "step_id": run_step.id,
                "thread_id": run_step.thread_id,
                "created_at": run_step.created_at,
            }
            await CodeInterpreterCall.create(session, data, thread_obj_id)
            await session.commit()
