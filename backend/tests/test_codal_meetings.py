"""Assembly date read from an invitation letter body."""

from __future__ import annotations

import datetime as dt

from tmon.ingest.codal.meetings import parse_meeting

LETTER = (
    "<div>مشخصات آگهی دعوت به مجمع عمومی عادی سالیانه برای سال (دوره) مالی منتهی به "
    "1405/05/31 &nbsp; الف- زمان و محل برگزاری مجمع عمومی : از کلیه سهامداران دعوت میگردد "
    "تا در جلسه مجمع عمومی این شرکت که در ساعت 10:00 روز دوشنبه مورخ 1405/09/02 در استان "
    "تهران برگزار میگردد حضور بهم رسانند. ب– دستور جلسه : تصویب صورت‌های مالی منتهی به "
    "1405/05/31</div>"
)


def test_reads_the_meeting_day_not_the_financial_period() -> None:
    m = parse_meeting(LETTER)
    assert m is not None
    assert m.day == dt.date(2026, 11, 23)
    assert m.clock == "10:00"


def test_persian_digits_and_missing_clock() -> None:
    html = "<p>الف- زمان و محل برگزاری: روز یکشنبه مورخ ۱۴۰۵/۰۹/۱۴ در تهران. ب- دستور جلسه</p>"
    m = parse_meeting(html)
    assert m is not None and m.day == dt.date(2026, 12, 5) and m.clock is None


def test_a_letter_without_a_stated_day_gives_none() -> None:
    assert parse_meeting("<p>آگهی دعوت به مجمع</p>") is None
    assert parse_meeting("<p>زمان و محل: به زودی اعلام می‌شود. دستور جلسه</p>") is None
