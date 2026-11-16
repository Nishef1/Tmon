"""Time handling: store UTC, display Asia/Tehran and Jalali dates."""

from __future__ import annotations

from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

import jdatetime

TEHRAN = ZoneInfo("Asia/Tehran")


def utcnow() -> datetime:
    return datetime.now(UTC)


def ensure_utc(dt: datetime) -> datetime:
    """Return ``dt`` as an aware UTC datetime; naive values are rejected."""
    if dt.tzinfo is None:
        raise ValueError("naive datetime is not allowed; attach a timezone")
    return dt.astimezone(UTC)


def to_tehran(dt: datetime) -> datetime:
    return ensure_utc(dt).astimezone(TEHRAN)


def tehran_today() -> date:
    """Today's date on the exchange's clock, whatever the machine's timezone."""
    return to_tehran(utcnow()).date()


def from_jalali(year: int, month: int, day: int) -> date:
    result: date = jdatetime.date(year, month, day).togregorian()
    return result


def yyyymmdd_to_date(value: int | str) -> date:
    s = str(value)
    return date(int(s[0:4]), int(s[4:6]), int(s[6:8]))
