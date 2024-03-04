from datetime import datetime, timedelta, timezone
from typing import Callable

NowFn = Callable[[], datetime]


def utcnow() -> datetime:
    """Return the current UTC time with timezone info."""
    return datetime.utcnow().replace(tzinfo=timezone.utc)


def offset(now: NowFn, seconds: int = 0) -> NowFn:
    return lambda: now() + timedelta(seconds=seconds)
