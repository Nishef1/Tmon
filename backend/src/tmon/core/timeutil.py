"""Time handling: store UTC, display Asia/Tehran and Jalali dates."""

from __future__ import annotations

from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

import jdatetime

TEHRAN = ZoneInfo("Asia/Tehran")

_PERSIAN_DIGITS = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")

JALALI_MONTHS = (
    "فروردین",
    "اردیبهشت",
    "خرداد",
    "تیر",
    "مرداد",
    "شهریور",
    "مهر",
    "آبان",
    "آذر",
    "دی",
    "بهمن",
    "اسفند",
)


def utcnow() -> datetime:
    return datetime.now(UTC)


def ensure_utc(dt: datetime) -> datetime:
    """Return ``dt`` as an aware UTC datetime; naive values are rejected."""
    if dt.tzinfo is None:
        raise ValueError("naive datetime is not allowed; attach a timezone")
    return dt.astimezone(UTC)


def to_tehran(dt: datetime) -> datetime:
    return ensure_utc(dt).astimezone(TEHRAN)


def to_jalali(d: date | datetime) -> jdatetime.date:
    if isinstance(d, datetime):
        d = d.date()
    return jdatetime.date.fromgregorian(date=d)


def from_jalali(year: int, month: int, day: int) -> date:
    result: date = jdatetime.date(year, month, day).togregorian()
    return result


def parse_jalali(text: str) -> date:
    """Parse ``1405/02/29`` or ``1405-02-29`` into a Gregorian date."""
    normalized = text.strip().replace("-", "/")
    y, m, d = (int(p) for p in normalized.split("/"))
    return from_jalali(y, m, d)


def format_jalali(d: date | datetime, *, persian_digits: bool = False) -> str:
    j = to_jalali(d)
    out = f"{j.year:04d}/{j.month:02d}/{j.day:02d}"
    return out.translate(_PERSIAN_DIGITS) if persian_digits else out


def format_jalali_long(d: date | datetime) -> str:
    j = to_jalali(d)
    return f"{j.day} {JALALI_MONTHS[j.month - 1]} {j.year}".translate(_PERSIAN_DIGITS)


def yyyymmdd_to_date(value: int | str) -> date:
    s = str(value)
    return date(int(s[0:4]), int(s[4:6]), int(s[6:8]))


def date_to_yyyymmdd(d: date) -> int:
    return d.year * 10000 + d.month * 100 + d.day
