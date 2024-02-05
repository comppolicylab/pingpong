from datetime import datetime, timezone
from typing import Callable

NowFn = Callable[[], datetime]


def utcnow() -> datetime:
    """Return the current UTC time with timezone info."""
    return datetime.utcnow().replace(tzinfo=timezone.utc)
