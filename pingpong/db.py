import asyncio
import logging
from functools import wraps
from typing import Any, Awaitable, Callable, TypeVar

from sqlalchemy.ext.asyncio import AsyncSession

from pingpong.config import config

T = TypeVar("T")

logger = logging.getLogger(__name__)


def db_session_handler(
    func: Callable[..., Awaitable[T]],
) -> Callable[..., Awaitable[T]]:
    """
    A decorator that provides an async database session to a function and handles retries.

    The decorated function must be an `async def` and should accept an `AsyncSession`
    object as its first argument.

    Example:
        @db_session_handler
        async def my_database_operation(session: AsyncSession, arg1, arg2):
            # ... database logic using 'session' ...

    The decorator will:
    1. Create a new `AsyncSession`.
    2. Call the decorated function with the session and other arguments.
    3. If an exception occurs, it will log the error and attempt a single retry.
    4. If the retry also fails, the exception is re-raised.
    """

    @wraps(func)
    async def wrapper(*args: Any, **kwargs: Any) -> T:
        async def _execute(s: AsyncSession) -> T:
            return await func(s, *args, **kwargs)

        try:
            async with config.db.driver.async_session() as session:
                return await _execute(session)
        except Exception as e:
            logger.warning(f"DB operation {func.__name__} failed, retrying. Error: {e}")
            async with config.db.driver.async_session() as session:
                return await _execute(session)

    return wrapper
