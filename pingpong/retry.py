import asyncio
import random
from typing import Any, Mapping, Callable

from fastapi import HTTPException


def with_retry(
    max_retries: int = 5,
    max_delay: int = 60,
    backoff: int = 2,
) -> Callable:
    def decorator(f: Callable) -> Callable:
        async def wrapper(*args: Any, **kwargs: Mapping[str, Any]) -> Any:
            attempt = 0
            last_error: Exception | None = None
            while attempt < max_retries:
                try:
                    return await f(*args, retry_attempt=attempt, **kwargs)
                except Exception as e:
                    # Our server returned an error, so we should stop retrying
                    # We use aiohttp raise_for_status, which returns a ClientResponseError
                    if isinstance(e, HTTPException):
                        raise e
                    last_error = e
                    attempt += 1
                    t = min(max_delay, backoff**attempt)
                    jittered = random.random() * t
                    await asyncio.sleep(jittered)
            if last_error:
                raise last_error

        return wrapper

    return decorator
