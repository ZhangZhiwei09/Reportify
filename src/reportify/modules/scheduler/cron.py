"""Cron expression parsing and evaluation (5-field subset).

Deliberately dependency- and I/O-free: the scheduler service owns persistence and
the application loop, this module owns only "when does it fire". Tests pin the
reference instant, so time never has to be mocked.

Supported syntax per field: ``*``, ``n``, ``a-b``, ``*/n``, ``a-b/n``, ``n/step``
and comma-separated lists of those. Day-of-week uses the Vixie convention
(0 or 7 = Sunday); when both day-of-month and day-of-week are restricted the
match is an OR, as in standard cron.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

MAX_SEARCH_DAYS = 366 * 5

_FIELD_BOUNDS: dict[str, tuple[int, int]] = {
    "minute": (0, 59),
    "hour": (0, 23),
    "day": (1, 31),
    "month": (1, 12),
    "weekday": (0, 7),
}


class CronError(ValueError):
    """A malformed expression, an unknown timezone, or one that never fires."""


def resolve_timezone(name: str) -> ZoneInfo:
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise CronError(f"unknown timezone: {name}") from exc


@dataclass(frozen=True)
class CronExpression:
    """A parsed expression; all fields are materialised value sets."""

    minutes: frozenset[int]
    hours: frozenset[int]
    days: frozenset[int]
    months: frozenset[int]
    weekdays: frozenset[int]
    day_restricted: bool
    weekday_restricted: bool

    @classmethod
    def parse(cls, expression: str) -> CronExpression:
        fields = expression.split()
        if len(fields) != 5:
            raise CronError(
                f"cron expression must have exactly 5 fields, got {len(fields)}"
            )
        minutes = _parse_field(fields[0], "minute")
        hours = _parse_field(fields[1], "hour")
        days = _parse_field(fields[2], "day")
        months = _parse_field(fields[3], "month")
        raw_weekdays = _parse_field(fields[4], "weekday")
        # normalise 7 -> 0 (Sunday), then map cron weekday to date.weekday().
        weekdays = frozenset(
            (0 if value == 7 else value) for value in raw_weekdays
        )
        normalised = frozenset((value + 6) % 7 for value in weekdays)
        return cls(
            minutes=minutes,
            hours=hours,
            days=days,
            months=months,
            weekdays=normalised,
            day_restricted=fields[2] != "*",
            weekday_restricted=fields[4] != "*",
        )

    def matches(self, local: datetime) -> bool:
        """Whether this expression fires at ``local`` (minute precision)."""
        return (
            local.minute in self.minutes
            and local.hour in self.hours
            and self._day_matches(local.date())
        )

    def next_after(self, after: datetime, tz: ZoneInfo) -> datetime:
        """First firing instant strictly after ``after``, as aware UTC."""
        if after.tzinfo is None:
            raise CronError("reference time must be timezone aware")
        after_utc = after.astimezone(UTC)
        start_local = (after_utc.astimezone(tz) + timedelta(minutes=1)).replace(
            second=0,
            microsecond=0,
        )
        start_day = start_local.date()
        for offset in range(MAX_SEARCH_DAYS):
            day = start_day + timedelta(days=offset)
            if not self._day_matches(day):
                continue
            for hour in sorted(self.hours):
                for minute in sorted(self.minutes):
                    candidate = datetime.combine(day, time(hour, minute), tzinfo=tz)
                    if candidate < start_local:
                        continue
                    instant = candidate.astimezone(UTC)
                    if instant > after_utc:
                        return instant
        raise CronError(f"cron expression never fires: {self!r}")

    def _day_matches(self, day: date) -> bool:
        if day.month not in self.months:
            return False
        day_ok = day.day in self.days
        weekday_ok = day.weekday() in self.weekdays
        if self.day_restricted and self.weekday_restricted:
            # Vixie cron: either field matching is enough.
            return day_ok or weekday_ok
        if self.day_restricted:
            return day_ok
        if self.weekday_restricted:
            return weekday_ok
        return True


def _parse_field(spec: str, name: str) -> frozenset[int]:
    low, high = _FIELD_BOUNDS[name]
    if not spec:
        raise CronError(f"empty {name} field")
    values: set[int] = set()
    for part in spec.split(","):
        if not part:
            raise CronError(f"empty entry in {name} field: {spec!r}")
        values.update(_parse_part(part, low, high, name))
    if not values:
        raise CronError(f"{name} field selects nothing: {spec!r}")
    return frozenset(values)


def _parse_part(part: str, low: int, high: int, name: str) -> range:
    base, _, step_text = part.partition("/")
    step = 1
    if step_text:
        step = _to_int(step_text, name)
        if step <= 0:
            raise CronError(f"{name} step must be positive: {part!r}")
    if base == "*":
        start, end = low, high
    elif "-" in base:
        left, _, right = base.partition("-")
        start, end = _to_int(left, name), _to_int(right, name)
        if start > end:
            raise CronError(f"{name} range is inverted: {part!r}")
    else:
        start = _to_int(base, name)
        end = high if step > 1 else start
    if not (low <= start <= high and low <= end <= high):
        raise CronError(f"{name} value out of range {low}-{high}: {part!r}")
    return range(start, end + 1, step)


def _to_int(text: str, name: str) -> int:
    try:
        return int(text)
    except ValueError as exc:
        raise CronError(f"{name} value is not a number: {text!r}") from exc
