import logging
from collections.abc import AsyncGenerator, AsyncIterable, AsyncIterator
from typing import TypeVar

StoreErrorT = TypeVar("StoreErrorT", bound=Exception)


async def _empty_stream() -> AsyncGenerator[bytes, None]:
    if False:
        yield b""


async def prefetch_stream(
    stream: AsyncIterable[bytes],
    *,
    store_error: type[StoreErrorT],
    logger: logging.Logger,
    store_error_log: str,
    unexpected_error_log: str,
) -> AsyncIterator[bytes]:
    iterator = stream.__aiter__()
    try:
        first = await iterator.__anext__()
    except StopAsyncIteration:
        return _empty_stream()
    except store_error:
        raise

    async def _wrapped() -> AsyncGenerator[bytes, None]:
        yield first
        try:
            async for chunk in iterator:
                yield chunk
        except store_error:
            logger.info(store_error_log)
            return
        except Exception:
            logger.exception(unexpected_error_log)
            return

    return _wrapped()
