import logging

logger = logging.getLogger(__name__)


async def safe_task(func, *args, **kwargs):
    try:
        await func(*args, **kwargs)
    except Exception as e:
        logger.exception(f"Background task {func.__name__} failed: {e}")
