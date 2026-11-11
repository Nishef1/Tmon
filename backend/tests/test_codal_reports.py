"""Codal report bodies: the Excel export parser and its ingestion, on exports captured from
excel.codal.ir on 2026-11-11 (tests/fixtures/codal/report_*)."""

from __future__ import annotations

import asyncio
import gzip
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
import respx
from sqlalchemy import func, select

from tmon.ingest.codal import endpoints
from tmon.ingest.codal.pipeline import CodalCtx, sync_reports
from tmon.ingest.codal.reports import (
    format_signature,
    is_correction,
    parse_number,
    parse_report,
    period_end,
    row_label,
    subsidiary_of,
)
from tmon.ingest.http import DomainRateLimiter, PoliteClient, RetryPolicy
from tmon.ingest.tsetmc.parsers import ParseError
from tmon.storage.models import CodalLetter, CodalReport, CodalReportCell, Instrument
from tmon.storage.objectstore import MemoryStore

FIXTURES = Path(__file__).parent / "fixtures" / "codal"
N30 = (FIXTURES / "report_n30_famli_1405-07.xls").read_bytes()
N10 = gzip.decompress((FIXTURES / "report_n10_famli_1405-06.xls.gz").read_bytes())
N30_URL = (
    "https://www.codal.ir/Reports/Decision.aspx?LetterSerial=JBfVmcnpL78zPxQXZY2VzQ%3d%3d"
    "&rt=0&let=58&ct=0&ft=-1"
)


def _row(table, label):
    return next(r for r in table.rows if row_label(r) == label)


def test_monthly_activity_tables():
    tables = parse_report(N30)
    assert len(tables) == 5
    sales = tables[0]
    assert sales.title == "گزارش فعالیت ماهانه تولید و فروش کلیه مبالغ به میلیون ریال است"
    # two header rows joined into one path per column
    assert sales.columns[0] == "شرح / نام محصول"
    assert sales.columns[2] == "از ابتدای سال مالی تا تاریخ ۱۴۰۵/۰۶/۳۱ / تعداد تولید"
    molybdenum = _row(sales, "کنسانتره مولیبدن")  # «موليبدن» with an Arabic yeh in the source
    assert molybdenum[1] == "تن"
    assert [parse_number(x) for x in molybdenum[2:6]] == [5481, 5043, 39391401745, 198650839]
    # a negative amount, written in parentheses
    assert parse_number(_row(sales, "سنگ سولفور")[5]) == -3014
    assert sum(1 for t in tables for r in t.rows for c in r if c) == 1006


def test_financial_statement_tables():
    tables = parse_report(N10)
    assert len(tables) == 62
    income = tables[0]
    assert income.title == "صورت سود و زیان تلفیقی"  # the export repeats the title; kept once
    assert income.columns[1] == "دوره منتهی به ۱۴۰۵/۰۶/۳۱ / حسابرسی نشده"
    assert parse_number(_row(income, "درآمدهای عملیاتی")[1]) == 3298998075
    titles = {t.title for t in tables}
    assert {"صورت وضعیت مالی تلفیقی", "صورت جریان های نقدی تلفیقی"} <= titles


def test_format_signature_is_per_template():
    assert format_signature(parse_report(N30)) == format_signature(parse_report(N30))
    assert format_signature(parse_report(N30)) != format_signature(parse_report(N10))


def test_captcha_page_is_refused():
    # what www.codal.ir/Reports/Decision.aspx served after a few report views
    with pytest.raises(ParseError, match="CAPTCHA"):
        parse_report((FIXTURES / "decision_captcha.html").read_bytes())


def test_no_tables_is_refused():
    with pytest.raises(ParseError):
        parse_report(b"<html><body>nothing</body></html>")


@pytest.mark.parametrize(
    ("text", "value"),
    [
        ("۳۹,۳۹۱,۴۰۱,۷۴۵", 39391401745),
        ("(۳,۰۱۴)", -3014),
        ("-12", -12),
        ("۱۲.۵%", 12.5),
        ("۰", 0),
        ("-", None),
        ("", None),
        ("تن", None),
    ],
)
def test_parse_number(text, value):
    assert parse_number(text) == value


def test_title_fields():
    assert period_end("گزارش فعالیت ماهانه دوره ۱ ماهه منتهی به ۱۴۰۵/۰۷/۳۰") == "1405/07/30"
    assert period_end("آگهی دعوت به مجمع") is None
    assert is_correction("گزارش فعالیت ماهانه دوره ۱ ماهه منتهی به ۱۴۰۵/۰۶/۳۱(اصلاحیه)")
    assert not is_correction("گزارش فعالیت ماهانه دوره ۱ ماهه منتهی به ۱۴۰۵/۰۶/۳۱")
    # titles as published under فملی for its subsidiaries
    assert (
        subsidiary_of(
            "صورت های مالی سال مالی منتهی به ۱۴۰۴/۱۲/۲۹ (حسابرسی شده) "
            "(شرکت نیروگاهی سیکل ترکیبی کرمانیان)"
        )
        == "شرکت نیروگاهی سیکل ترکیبی کرمانیان"
    )
    assert (
        subsidiary_of(
            "صورت وضعیت پورتفوی دوره ۳ ماهه منتهی به ۱۴۰۴/۱۲/۲۹ "
            "(شرکت سرمایه گذاری گروه مالی کیمیا مس ایرانیان)(اصلاحیه)"
        )
        == "شرکت سرمایه گذاری گروه مالی کیمیا مس ایرانیان"
    )
    assert subsidiary_of("اطلاعات و صورت های مالی میاندوره ای دوره ۳ ماهه (حسابرسی نشده)") is None


def test_excel_url_from_report_url():
    serial = endpoints.letter_serial(N30_URL)
    assert serial == "JBfVmcnpL78zPxQXZY2VzQ=="
    assert endpoints.excel_url(serial) == (
        "https://excel.codal.ir/service/Excel/GetAll/JBfVmcnpL78zPxQXZY2VzQ%3D%3D/0"
    )
    assert endpoints.letter_serial(None) is None


def _letter(session) -> CodalLetter:
    share = Instrument(ins_code="35425587644337450", symbol_fa="فملی", instrument_type="stock")
    session.add(share)
    session.flush()
    letter = CodalLetter(
        tracing_no=1621020,
        instrument_id=share.id,
        symbol="فملی",
        letter_code="ن-۳۰",
        title="گزارش فعالیت ماهانه دوره ۱ ماهه منتهی به ۱۴۰۵/۰۷/۳۰",
        published_at=datetime(2026, 10, 25, 12, 0, tzinfo=UTC),
        url=N30_URL,
        has_excel=True,
    )
    session.add(letter)
    session.flush()
    return letter


def _sync(session, store, **kwargs):
    async def go():
        async def nosleep(_: float) -> None:
            return None

        client = PoliteClient(
            limiter=DomainRateLimiter(0.0),
            retry=RetryPolicy(max_retries=0, jitter=0.0),
            client=httpx.AsyncClient(),
            sleep=nosleep,
        )
        try:
            return await sync_reports(CodalCtx(session, client, store), **kwargs)
        finally:
            await client.aclose()

    return asyncio.run(go())


def test_sync_reports_stores_raw_then_cells(session):
    letter = _letter(session)
    store = MemoryStore()
    url = endpoints.excel_url(endpoints.letter_serial(letter.url) or "")
    with respx.mock:
        route = respx.get(url).mock(return_value=httpx.Response(200, content=N30))
        first = _sync(session, store, letter_code="ن-۳۰")
        again = _sync(session, store, letter_code="ن-۳۰")
    assert first == {"reports": 1, "cells": 1006, "skipped": 0}
    assert again == {"reports": 0, "cells": 0, "skipped": 0}  # already parsed: not fetched again
    assert route.call_count == 1
    assert N30 in store.objects.values()  # raw body kept byte for byte before parsing
    rep = session.get(CodalReport, 1621020)
    assert rep is not None
    assert (rep.period_end, rep.is_correction, rep.n_tables, rep.n_cells) == (
        "1405/07/30",
        False,
        5,
        1006,
    )
    assert rep.instrument_id == letter.instrument_id
    assert rep.subsidiary is None
    assert rep.format_signature == format_signature(parse_report(N30))
    cell = session.scalars(
        select(CodalReportCell).where(
            CodalReportCell.row_label == "کنسانتره مولیبدن",
            CodalReportCell.col_header.like("%۱۴۰۵/۰۶/۳۱ / تعداد فروش"),
        )
    ).one()
    assert (cell.text, cell.value) == ("۵,۰۴۳", 5043)


def test_sync_reports_stops_on_captcha(session):
    letter = _letter(session)
    url = endpoints.excel_url(endpoints.letter_serial(letter.url) or "")
    with respx.mock:
        respx.get(url).mock(
            return_value=httpx.Response(
                200, content=(FIXTURES / "decision_captcha.html").read_bytes()
            )
        )
        out = _sync(session, MemoryStore(), letter_code="ن-۳۰")
    assert out == {"reports": 0, "cells": 0, "skipped": 0, "stopped_at": 1621020}
    assert session.scalar(select(func.count()).select_from(CodalReport)) == 0
