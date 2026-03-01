import asyncio
import random
from aiohttp import ClientResponseError
from typing import Any, Mapping, Callable


def with_retry(
    max_retries: int = 5,
    max_delay: int = 60,
    backoff: int = 2,
    raise_custom_errors: dict[int, Exception] = {},
) -> Callable:
    def decorator(f: Callable) -> Callable:
        async def wrapper(*args: Any, **kwargs: Mapping[str, Any]) -> Any:
            attempt = 0
            last_error: ClientResponseError | None = None
            while attempt < max_retries:
                try:
                    return await f(*args, retry_attempt=attempt, **kwargs)
                # Our server returned an error, so we should stop retrying
                # Our network requests use aiohttp raise_for_status,
                # which returns a ClientResponseError
                except ClientResponseError as e:
                    last_error = e
                    attempt += 1
                    t = min(max_delay, backoff**attempt)
                    jittered = random.random() * t
                    await asyncio.sleep(jittered)
                except Exception as e:
                    raise e
            if last_error:
                if last_error.status in raise_custom_errors:
                    raise raise_custom_errors[last_error.status]
                raise last_error
            raise RuntimeError(
                "Retry loop exited without returning or capturing an error"
            )

        return wrapper

    return decorator
