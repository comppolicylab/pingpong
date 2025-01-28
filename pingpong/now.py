import asyncio
import calendar
import logging
from datetime import datetime, timedelta, timezone
from typing import Callable, Optional

NowFn = Callable[[], datetime]


def utcnow() -> datetime:
    """Return the current UTC time with timezone info."""
    return datetime.now(timezone.utc)


def offset(now: NowFn, seconds: int = 0) -> NowFn:
    return lambda: now() + timedelta(seconds=seconds)


def _parse_cron_element(element: str) -> list[int]:
    """
    Parse a cron element into a list of valid integers.
    Handles simple numbers, lists (1,2,3), ranges (1-5), and steps (*/2, 1-5/2)
    """
    if element == "*":
        return []

    values = set[int]()
    for part in element.split(","):
        if "/" in part:
            range_part, step_str = part.split("/")
            step = int(step_str)
            if range_part == "*":
                start, end = 0, 59  # Default range for *
            else:
                if "-" in range_part:
                    start_str, end_str = range_part.split("-")
                    start, end = int(start_str), int(end_str)
                else:
                    start = end = int(range_part)
            values.update(range(start, end + 1, step))
        elif "-" in part:
            start_str, end_str = part.split("-")
            start, end = int(start_str), int(end_str)
            values.update(range(start, end + 1))
        else:
            values.add(int(part))
    return sorted(list(values))


def _matches(
    pattern: str, value: int, year: Optional[int] = None, month: Optional[int] = None
) -> bool:
    """
    Check if a value matches a cron pattern.

    Args:
        pattern: Cron pattern (e.g., "*/15", "1,2,3", "1-5", "9-17/2")
        value: Value to check
        year: Optional year for day validation
        month: Optional month for day validation

    Returns:
        bool: True if value matches pattern
    """
    # First validate the day of month if year and month are provided
    if year is not None and month is not None:
        _, last_day = calendar.monthrange(year, month)
        if value > last_day:
            raise ValueError(f"Invalid day {value} for month {month}")

    # Handle wildcard
    if pattern == "*":
        return True

    try:
        valid_values = _parse_cron_element(pattern)

        # Empty list means wildcard
        if not valid_values:
            return True

        return value in valid_values

    except ValueError as e:
        raise ValueError(f"Invalid cron pattern: {pattern}") from e


def _get_next_run_time(sched: str, ts: datetime, tz=timezone.utc) -> datetime:
    """
    Calculate the next run time based on a cron expression.

    Args:
        sched (str): The cron schedule string (e.g., "*/15 * * * *").
        ts (datetime): The current timestamp.
        tz (timezone): The timezone for the calculation (default is UTC).

    Returns:
        datetime: The next run time.

    Raises:
        ValueError: If the cron format is invalid or if unable to find next run time within MAX_ITERATIONS
    """
    MAX_ITERATIONS = 1000  # Prevent infinite loops
    iteration_count = 0

    # Split the cron schedule into its components
    try:
        minute, hour, day, month, weekday = sched.split()
    except ValueError:
        raise ValueError("Invalid cron format. Expected 5 fields.")

    # Start with the current timestamp
    ts = ts.astimezone(tz)
    ts = ts.replace(second=0, microsecond=0)
    original_ts = ts

    # If we're looking for a specific day (not *), store it
    target_day = None if day == "*" else int(day)

    while iteration_count < MAX_ITERATIONS:
        iteration_count += 1

        if target_day:
            _, last_day = calendar.monthrange(ts.year, ts.month)
            if target_day > last_day:
                # Skip to next month if target day is greater than days in current month
                if ts.month == 12:
                    ts = ts.replace(year=ts.year + 1, month=1, day=1)
                else:
                    ts = ts.replace(month=ts.month + 1, day=1)
                ts = ts.replace(hour=0, minute=0, second=0)
                continue
            elif ts.day > target_day:
                # If we've passed the target day in current month, move to next month
                if ts.month == 12:
                    ts = ts.replace(year=ts.year + 1, month=1, day=target_day)
                else:
                    ts = ts.replace(month=ts.month + 1, day=target_day)
                ts = ts.replace(hour=0, minute=0, second=0)
                continue

        # Convert weekday to cron format (0-6, where 0 is Sunday)
        cron_wday = ts.weekday()
        if weekday != "*":  # Only adjust if we're checking specific days
            cron_wday = (
                ts.weekday() + 1
            ) % 7  # Convert to cron format where 1-7 represents Mon-Sun

        matches_all = (
            _matches(minute, ts.minute)
            and _matches(hour, ts.hour)
            and _matches(day, ts.day, ts.year, ts.month)
            and _matches(month, ts.month)
            and _matches(weekday, cron_wday)
        )

        if matches_all:
            if ts <= original_ts:
                ts += timedelta(minutes=1)
                ts = ts.replace(second=0)
                continue
            return ts

        if not _matches(minute, ts.minute):
            ts += timedelta(minutes=1)
            ts = ts.replace(second=0)
            continue

        if not _matches(hour, ts.hour):
            ts += timedelta(hours=1)
            ts = ts.replace(minute=0, second=0)
            continue

        if not _matches(day, ts.day, ts.year, ts.month) or not _matches(
            weekday, cron_wday
        ):
            ts += timedelta(days=1)
            ts = ts.replace(hour=0, minute=0, second=0)
            continue

        if not _matches(month, ts.month):
            if ts.month == 12:
                ts = ts.replace(year=ts.year + 1, month=1, day=1)
            else:
                ts = ts.replace(month=ts.month + 1, day=1)
            ts = ts.replace(hour=0, minute=0, second=0)
            continue

    raise ValueError(
        f"Unable to find next run time within {MAX_ITERATIONS} iterations. Possible invalid cron expression or infinite loop detected."
    )


async def croner(
    sched: str,
    now: NowFn = utcnow,
    logger: logging.Logger = logging.getLogger(__name__),
    task_name: str | None = None,
):
    """Iterate over the given cron schedule."""
    while True:
        ts = now()
        next_run = _get_next_run_time(sched, ts)
        wait = (next_run - now()).total_seconds()
        if task_name:
            logger.info(
                f"Next run for {task_name} scheduled at: {next_run} (in {wait} seconds)"
            )
        else:
            logger.info(f"Next job scheduled at: {next_run} (in {wait} seconds)")
        await asyncio.sleep(wait)
        yield next_run
