import pytest
from datetime import datetime, timezone
from pingpong.now import _get_next_run_time, _matches


@pytest.fixture
def tz():
    """Fixture for UTC timezone."""
    return timezone.utc


def test_matching_function():
    assert _matches("*/15", 15) is True
    assert _matches("*/15", 14) is False
    assert _matches("9-17/2", 9) is True
    assert _matches("9-17/2", 11) is True
    assert _matches("9-17/2", 10) is False
    assert _matches("1,2,3", 2) is True
    assert _matches("1,2,3", 4) is False
    assert _matches("1-5", 3) is True
    assert _matches("1-5", 6) is False
    assert _matches("*", 42) is True


def test_simple_cron(tz):
    """Test a simple cron expression (e.g., every minute)."""
    ts = datetime(2025, 1, 7, 12, 0, 0, tzinfo=tz)
    next_run = _get_next_run_time("* * * * *", ts)
    expected_next_run = datetime(2025, 1, 7, 12, 1, 0, tzinfo=tz)
    assert next_run == expected_next_run


def test_cron_every_15_minutes(tz):
    """Test a cron expression for every 15 minutes."""
    ts = datetime(2025, 1, 7, 12, 7, 0, tzinfo=tz)
    next_run = _get_next_run_time("*/15 * * * *", ts)
    expected_next_run = datetime(2025, 1, 7, 12, 15, 0, tzinfo=tz)
    assert next_run == expected_next_run


def test_cron_every_hour(tz):
    """Test a cron expression for every hour."""
    ts = datetime(2025, 1, 7, 12, 30, 0, tzinfo=tz)
    next_run = _get_next_run_time("0 * * * *", ts)
    expected_next_run = datetime(2025, 1, 7, 13, 0, 0, tzinfo=tz)
    assert next_run == expected_next_run


def test_cron_on_weekdays(tz):
    """Test a cron expression for weekdays (Monday to Friday)."""
    ts = datetime(2025, 1, 7, 12, 0, 0, tzinfo=tz)  # This is a Tuesday.
    next_run = _get_next_run_time("* * * * 1-5", ts)
    expected_next_run = datetime(
        2025, 1, 7, 12, 1, 0, tzinfo=tz
    )  # Should be the same day.
    assert next_run == expected_next_run


def test_invalid_cron_expression(tz):
    """Test invalid cron expression."""
    ts = datetime(2025, 1, 7, 12, 0, 0, tzinfo=tz)
    with pytest.raises(ValueError):
        _get_next_run_time("*/15 * *", ts)  # Incorrect cron format


def test_cron_on_last_day_of_month(tz):
    """Test a cron expression for the last day of the month."""
    ts = datetime(2025, 1, 31, 12, 0, 0, tzinfo=tz)
    next_run = _get_next_run_time("0 0 31 * *", ts)
    expected_next_run = datetime(
        2025, 3, 31, 0, 0, 0, tzinfo=tz
    )  # February 28th, 2025, not 29th
    assert next_run == expected_next_run


def test_cron_sundays(tz):
    ts = datetime(2025, 1, 5, 10, 0, 0, tzinfo=tz)  # Sunday
    next_run = _get_next_run_time("0 12 * * 0", ts)
    expected_next_run = datetime(2025, 1, 5, 12, 0, 0, tzinfo=tz)
    assert next_run == expected_next_run


def test_cron_specific_time_day_of_month(tz):
    ts = datetime(2025, 1, 1, 9, 0, 0, tzinfo=tz)
    next_run = _get_next_run_time("0 10 1 * *", ts)
    expected_next_run = datetime(2025, 1, 1, 10, 0, 0, tzinfo=tz)
    assert next_run == expected_next_run


def test_cron_year_rollover(tz):
    """Test cron expression handling year rollover."""
    ts = datetime(2025, 12, 31, 23, 59, 0, tzinfo=tz)
    next_run = _get_next_run_time("0 0 1 1 *", ts)
    expected_next_run = datetime(2026, 1, 1, 0, 0, 0, tzinfo=tz)
    assert next_run == expected_next_run


def test_cron_specific_days_and_hours(tz):
    """Test cron expression for specific days and hours."""
    ts = datetime(2025, 1, 7, 14, 0, 0, tzinfo=tz)
    next_run = _get_next_run_time("0 9,17 * * 1-5", ts)  # 9 AM and 5 PM on weekdays
    expected_next_run = datetime(2025, 1, 7, 17, 0, 0, tzinfo=tz)
    assert next_run == expected_next_run


def test_cron_last_minute_of_hour(tz):
    """Test cron expression for the last minute of every hour."""
    ts = datetime(2025, 1, 7, 14, 30, 0, tzinfo=tz)
    next_run = _get_next_run_time("59 * * * *", ts)
    expected_next_run = datetime(2025, 1, 7, 14, 59, 0, tzinfo=tz)
    assert next_run == expected_next_run


def test_cron_multiple_day_of_week(tz):
    """Test cron expression for multiple specific days of the week."""
    ts = datetime(2025, 1, 7, 12, 0, 0, tzinfo=tz)  # Tuesday
    next_run = _get_next_run_time("0 12 * * 2,4,6", ts)  # Tue, Thu, Sat at noon
    expected_next_run = datetime(2025, 1, 9, 12, 0, 0, tzinfo=tz)  # Thursday
    assert next_run == expected_next_run


def test_cron_step_values_hours(tz):
    """Test cron expression with step values for hours."""
    ts = datetime(2025, 1, 7, 13, 0, 0, tzinfo=tz)
    next_run = _get_next_run_time("0 */4 * * *", ts)  # Every 4 hours
    expected_next_run = datetime(2025, 1, 7, 16, 0, 0, tzinfo=tz)
    assert next_run == expected_next_run


def test_cron_february_29_non_leap_year(tz):
    """Test cron expression handling February 29 in a non-leap year."""
    ts = datetime(2025, 2, 28, 12, 0, 0, tzinfo=tz)  # 2025 is not a leap year
    next_run = _get_next_run_time("0 0 29 2 *", ts)  # Every February 29
    expected_next_run = datetime(2028, 2, 29, 0, 0, 0, tzinfo=tz)  # Next leap year
    assert next_run == expected_next_run


def test_cron_range_with_step(tz):
    """Test cron expression with range and step values."""
    ts = datetime(2025, 1, 7, 9, 0, 0, tzinfo=tz)
    next_run = _get_next_run_time(
        "0 9-17/2 * * *", ts
    )  # Every 2 hours from 9 AM to 5 PM
    expected_next_run = datetime(2025, 1, 7, 11, 0, 0, tzinfo=tz)
    assert next_run == expected_next_run


def test_cron_invalid_day_of_month(tz):
    """Test cron expression with invalid day of month."""
    ts = datetime(2025, 4, 1, 0, 0, 0, tzinfo=tz)
    with pytest.raises(ValueError):
        _get_next_run_time("0 0 31 4 *", ts)  # April has 30 days


def test_cron_lists_and_ranges(tz):
    """Test cron expression with lists and ranges combined."""
    ts = datetime(2025, 1, 7, 8, 0, 0, tzinfo=tz)
    next_run = _get_next_run_time(
        "0 9,13-17/2 * * 1-5", ts
    )  # 9 AM and every 2 hours from 1-5 PM weekdays
    expected_next_run = datetime(2025, 1, 7, 9, 0, 0, tzinfo=tz)
    assert next_run == expected_next_run
