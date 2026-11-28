from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

import pytest

from reportify.modules.scheduler.cron import (
    CronError,
    CronExpression,
    resolve_timezone,
)

UTC_TZ = ZoneInfo("UTC")


def test_parses_common_expressions() -> None:
    expression = CronExpression.parse("0 9 * * 1-5")
    assert expression.minutes == frozenset({0})
    assert expression.hours == frozenset({9})
    assert expression.weekdays == frozenset({0, 1, 2, 3, 4})
    assert expression.day_restricted is False
    assert expression.weekday_restricted is True


def test_steps_ranges_and_lists() -> None:
    expression = CronExpression.parse("*/15 8-10/2 1,15 * *")
    assert expression.minutes == frozenset({0, 15, 30, 45})
    assert expression.hours == frozenset({8, 10})
    assert expression.days == frozenset({1, 15})
    assert expression.day_restricted is True


@pytest.mark.parametrize(
    "expression",
    [
        "",
        "* * * *",
        "60 * * * *",
        "* 24 * * *",
        "* * 0 * *",
        "* * * 13 *",
        "* * * * 8",
        "*/0 * * * *",
        "5-1 * * * *",
        "abc * * * *",
        "1,,2 * * * *",
        "* * * * 1-",
    ],
)
def test_rejects_bad_expressions(expression: str) -> None:
    with pytest.raises(CronError):
        CronExpression.parse(expression)


def test_sunday_accepts_zero_and_seven() -> None:
    sunday = datetime(2026, 11, 29, 9, 0, tzinfo=UTC_TZ)  # 2026-11-29 is a Sunday
    for expression in ("0 9 * * 0", "0 9 * * 7"):
        assert CronExpression.parse(expression).matches(sunday)


def test_next_minute() -> None:
    expression = CronExpression.parse("* * * * *")
    after = datetime(2026, 11, 28, 10, 0, 30, tzinfo=UTC)
    assert expression.next_after(after, UTC_TZ) == datetime(
        2026, 11, 28, 10, 1, tzinfo=UTC
    )


def test_step_jumps_to_the_next_boundary() -> None:
    expression = CronExpression.parse("*/15 * * * *")
    after = datetime(2026, 11, 28, 10, 7, tzinfo=UTC)
    assert expression.next_after(after, UTC_TZ) == datetime(
        2026, 11, 28, 10, 15, tzinfo=UTC
    )


def test_weekdays_skip_the_weekend() -> None:
    expression = CronExpression.parse("0 9 * * 1-5")
    friday = datetime(2026, 11, 27, 10, 0, tzinfo=UTC)
    assert expression.next_after(friday, UTC_TZ) == datetime(
        2026, 11, 30, 9, 0, tzinfo=UTC
    )


def test_timezone_shifts_the_utc_instant() -> None:
    expression = CronExpression.parse("0 9 * * *")
    shanghai = ZoneInfo("Asia/Shanghai")
    after = datetime(2026, 11, 28, 0, 0, tzinfo=UTC)
    # 09:00 in UTC+8 is 01:00 UTC.
    assert expression.next_after(after, shanghai) == datetime(
        2026, 11, 28, 1, 0, tzinfo=UTC
    )


def test_day_and_weekday_are_or_ed() -> None:
    expression = CronExpression.parse("0 0 1 * 1")
    # 2026-12-01 is a Tuesday; OR semantics still fire the following Monday.
    after = datetime(2026, 12, 1, 0, 1, tzinfo=UTC)
    assert expression.next_after(after, UTC_TZ) == datetime(
        2026, 12, 7, 0, 0, tzinfo=UTC
    )


def test_spring_forward_gap_still_yields_an_instant() -> None:
    expression = CronExpression.parse("30 2 * * *")
    new_york = ZoneInfo("America/New_York")
    # 2026-03-08 02:30 local does not exist; it resolves to 03:30 EDT.
    after = datetime(2026, 3, 7, 12, 0, tzinfo=UTC)
    result = expression.next_after(after, new_york)
    assert result == datetime(2026, 3, 8, 7, 30, tzinfo=UTC)
    assert result > after


def test_fall_back_uses_the_first_occurrence() -> None:
    expression = CronExpression.parse("30 1 * * *")
    new_york = ZoneInfo("America/New_York")
    # 2026-11-01 01:30 is ambiguous; fold=0 means EDT (UTC-4).
    after = datetime(2026, 11, 1, 4, 0, tzinfo=UTC)
    assert expression.next_after(after, new_york) == datetime(
        2026, 11, 1, 5, 30, tzinfo=UTC
    )


def test_expression_that_never_fires_is_rejected() -> None:
    expression = CronExpression.parse("0 0 30 2 *")
    with pytest.raises(CronError):
        expression.next_after(datetime(2026, 1, 1, tzinfo=UTC), UTC_TZ)


def test_naive_reference_is_rejected() -> None:
    with pytest.raises(CronError):
        CronExpression.parse("0 9 * * *").next_after(datetime(2026, 1, 1), UTC_TZ)


def test_resolve_timezone() -> None:
    assert str(resolve_timezone("Asia/Shanghai")) == "Asia/Shanghai"
    with pytest.raises(CronError):
        resolve_timezone("Mars/Base")
