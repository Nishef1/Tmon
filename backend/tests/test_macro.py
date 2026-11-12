"""Macro sources on real payloads captured 2026-11-12 (tests/fixtures/macro)."""

from __future__ import annotations

import asyncio
from datetime import date
from pathlib import Path

import httpx
import pytest
import respx
from sqlalchemy import select

from tmon.ingest.http import DomainRateLimiter, PoliteClient, RetryPolicy
from tmon.ingest.macro import fipiran, inflation, tgju
from tmon.ingest.macro.pipeline import import_inflation, sync_funds, sync_tgju
from tmon.ingest.tsetmc.parsers import ParseError
from tmon.storage.models import FundNav, Instrument, MacroSeries
from tmon.storage.objectstore import MemoryStore

FIX = Path(__file__).parent / "fixtures" / "macro"
USD = (FIX / "tgju_price_dollar_rl.json").read_bytes()
FUNDS = (FIX / "fipiran_fundcompare.json").read_bytes()


def test_tgju_history_columns():
    bars = tgju.parse_history(USD)
    assert len(bars) == 40
    b = bars[0]
    assert (b.date, b.open, b.low, b.high, b.close, b.jalali) == (
        date(2026, 11, 11), 2607900, 2589000, 2641100, 2640700, "1405/08/20",
    )  # fmt: skip
    # the published change (41,700) is close minus the previous close: confirms the column order
    assert b.close - bars[1].close == 41700
    assert all(x.low <= min(x.open, x.close) and x.high >= max(x.open, x.close) for x in bars)


def test_tgju_rejects_other_payloads():
    with pytest.raises(ParseError):
        tgju.parse_history(b"<html></html>")


def test_fipiran_fund_rows():
    rows = fipiran.parse_compare(FUNDS)
    assert len(rows) == 6
    etf = rows[0]
    assert etf.type_of_invest == "Negotiable" and etf.ins_code
    assert etf.cancel_nav and etf.issue_nav and etf.issue_nav >= etf.cancel_nav
    assert {r.type_of_invest for r in rows} == {"Negotiable", "IssuanceAndCancellation"}


def test_bubble():
    assert fipiran.bubble(103.0, 100.0) == pytest.approx(0.03)
    assert fipiran.bubble(None, 100.0) is None
    assert fipiran.bubble(100.0, None) is None


def _client() -> PoliteClient:
    async def nosleep(_: float) -> None:
        return None

    return PoliteClient(
        limiter=DomainRateLimiter(0.0),
        retry=RetryPolicy(max_retries=0, jitter=0.0),
        client=httpx.AsyncClient(),
        sleep=nosleep,
    )


def test_sync_tgju_and_funds(session):
    rows = fipiran.parse_compare(FUNDS)
    session.add(Instrument(ins_code=rows[0].ins_code, symbol_fa="ETF", instrument_type="etf"))
    session.flush()
    store = MemoryStore()

    async def go():
        client = _client()
        try:
            return await sync_tgju(session, client, store), await sync_funds(session, client, store)
        finally:
            await client.aclose()

    with respx.mock:
        for key in tgju.SERIES.values():
            respx.get(tgju.url(key)).mock(return_value=httpx.Response(200, content=USD))
        respx.post(fipiran.COMPARE_URL).mock(return_value=httpx.Response(200, content=FUNDS))
        t, f = asyncio.run(go())
    assert t == {"usd_free": 40, "gold_18k": 40, "coin_emami": 40}
    assert f == {"funds": 6, "linked": 1}
    assert USD in store.objects.values() and FUNDS in store.objects.values()
    row = session.get(MacroSeries, ("usd_free", "tgju", date(2026, 11, 11)))
    assert row is not None and row.value == 2640700 and row.release_date == date(2026, 11, 11)
    linked = session.scalars(select(FundNav).where(FundNav.instrument_id.is_not(None))).all()
    assert len(linked) == 1


GOOD = """series,source,ref_period,value,release_date,source_url
cpi_mom,sci,2026-10-22,0.044,2026-10-28,https://example.org/sci/1405-07
"""


def test_inflation_csv(session, tmp_path):
    p = tmp_path / "inf.csv"
    p.write_text(GOOD, encoding="utf-8")
    assert import_inflation(session, p) == 1
    row = session.get(MacroSeries, ("cpi_mom", "sci", date(2026, 10, 22)))
    assert row is not None
    assert (row.value, row.release_date, row.source_url) == (
        0.044,
        date(2026, 10, 28),
        "https://example.org/sci/1405-07",
    )


@pytest.mark.parametrize(
    "bad",
    [
        GOOD.replace("https://example.org/sci/1405-07", ""),  # no source URL
        GOOD.replace("2026-10-28", "2026-10-01"),  # released before the period
        GOOD.replace("0.044", "4.4"),  # a percent, not a fraction
        GOOD.replace("cpi_mom", "cpi_x"),
        "series,source,value\ncpi_mom,sci,0.04\n",  # no release_date column
    ],
)
def test_inflation_csv_rejects(bad):
    with pytest.raises(ParseError):
        inflation.parse_csv(bad)


def test_yahoo_chart_parses_daily_closes() -> None:
    from tmon.ingest.macro import yahoo

    bars = yahoo.parse_chart((FIX / "yahoo_hg.json").read_bytes())
    assert [b.date for b in bars][:2] == [date(2025, 11, 5), date(2025, 11, 6)]
    assert bars[0].close == pytest.approx(4.963, abs=1e-3)
    assert yahoo.release(bars[0].date) == date(2025, 11, 6)


def test_yahoo_evening_session_start_belongs_to_the_next_day() -> None:
    import json

    from tmon.ingest.macro import yahoo

    sunday_6pm_ny = 1262646000  # 2010-01-04 23:00 UTC = 18:00 New York, Monday's session
    doc = {"chart": {"result": [{"meta": {"gmtoffset": -18000}, "timestamp": [sunday_6pm_ny - 86400],
           "indicators": {"quote": [{"close": [3.3]}]}}]}}  # fmt: skip
    assert yahoo.parse_chart(json.dumps(doc).encode())[0].date == date(2010, 1, 4)
