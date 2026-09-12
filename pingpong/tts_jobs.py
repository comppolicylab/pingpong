import asyncio
from collections.abc import Callable, Coroutine, Sequence
from typing import Any, TypeVar

TTS_REQUESTS_PER_JOB = 4

_TTSItem = TypeVar("_TTSItem")
_TTSResult = TypeVar("_TTSResult")


async def map_tts_job(
    items: Sequence[_TTSItem],
    operation: Callable[[_TTSItem], Coroutine[Any, Any, _TTSResult | None]],
) -> list[_TTSResult | None]:
    """Run at most four operations per job and drain tasks on failure/cancellation."""
    semaphore = asyncio.Semaphore(TTS_REQUESTS_PER_JOB)
    stopped = asyncio.Event()

    async def run(item: _TTSItem) -> _TTSResult | None:
        async with semaphore:
            if stopped.is_set():
                return None
            try:
                result = await operation(item)
            except BaseException:
                stopped.set()
                raise
            if result is None:
                stopped.set()
            return result

    tasks = [asyncio.create_task(run(item)) for item in items]
    try:
        return await asyncio.gather(*tasks)
    finally:
        for task in tasks:
            if not task.done():
                task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
