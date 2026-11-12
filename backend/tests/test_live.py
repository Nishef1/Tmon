"""Live-ingestion tests on SYNTHETIC payloads that follow the reference column layout. They test
our logic (parsing, change detection, trading hours, probe verdicts, the file store), not the
real service; the real service is checked by ``pytest -m network`` and the probe."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

import httpx
import pytest
import respx
from sqlalchemy import select

from tmon.core.timeutil import TEHRAN
from tmon.domain.rules import RuleBook
from tmon.ingest.http import DomainRateLimiter, PoliteClient, RetryPolicy
from tmon.ingest.tsetmc import endpoints, parsers
from tmon.ingest.tsetmc.intraday import (
    FeedError,
    IntradayState,
    in_trading_hours,
    store_quotes,
    sync_sector_names,
)
from tmon.ingest.tsetmc.probe import format_report, run_probe
from tmon.storage.models import (
    Instrument,
    IntradaySnapshot,
    OrderBookSnapshot,
    PriceDaily,
    RawPayload,
    SectorName,
)
from tmon.storage.objectstore import FileStore, MemoryStore
from tmon.storage.seed import seed_market_rules, seed_rulebook


def row(code: str, symbol: str, *, volume: int, value: int, final: int = 1010) -> str:
    # 0 id,1 isin,2 symbol,3 name,4 time,5 first,6 final,7 close,8 trades,9 volume,10 value,
    # 11 low,12 high,13 yesterday
    f = [code, f"IRO1{code}", symbol, f"شرکت {symbol}", "10:15:30", "1000", str(final), "1005"]
    f += ["30", str(volume), str(value), "990", "1030", "1000", "0", "1000"]
    return ",".join(f)


def watch(*rows: str) -> str:
    return "h@x@" + ";".join(rows)


BOOK = {
    "bestLimits": [
        {
            "number": i,
            "pMeDem": 1000 - i,
            "qTitMeDem": 100 * i,
            "zOrdMeDem": i,
            "pMeOf": 1000 + i,
            "qTitMeOf": 90 * i,
            "zOrdMeOf": i,
        }
        for i in range(1, 6)
    ]
}


def test_quotes_parse_and_reject_a_changed_layout():
    qs = parsers.parse_market_watch_quotes(
        watch(row("111", "الف", volume=500, value=5_000_000), row("112", "ب", volume=0, value=0))
    )
    assert [q.ins_code for q in qs] == ["111", "112"]
    assert qs[0].final == 1010 and qs[0].volume == 500 and qs[0].yesterday == 1000

    with pytest.raises(parsers.ParseError):  # columns shifted: high < low everywhere
        bad = ",".join(["111", "I", "s", "n", "t", "1", "2", "3", "4", "5", "6", "9", "8", "7"])
        parsers.parse_market_watch_quotes(watch(*[bad.replace("111", str(c)) for c in range(5)]))
    with pytest.raises(parsers.ParseError):
        parsers.parse_market_watch_quotes("nothing")


def _client() -> PoliteClient:
    async def nosleep(_: float) -> None:
        return None

    return PoliteClient(
        limiter=DomainRateLimiter(0.0),
        retry=RetryPolicy(max_retries=0, jitter=0.0),
        client=httpx.AsyncClient(),
        sleep=nosleep,
    )


def mw(code: str, *, volume: float, value: float, pmax: float = 1050, pmin: float = 950) -> dict:
    return {
        "insCode": code,
        "pDrCotVal": 1010,
        "qTotTran5J": volume,
        "qTotCap": value,
        "pMax": pmax,
        "pMin": pmin,
        "blDs": [
            {
                "n": i,
                "qmd": 100 * i,
                "zmd": i,
                "pmd": 1000 - i,
                "pmo": 1000 + i,
                "qmo": 90 * i,
                "zmo": i,
            }
            for i in range(1, 6)
        ],
    }


def test_snapshot_stores_changed_quotes_books_limits_and_samples_raw(session):
    seed_market_rules(session)
    for code, sym in (("111", "الف"), ("112", "ب"), ("113", "ج")):
        session.add(Instrument(ins_code=code, symbol_fa=sym, instrument_type="stock"))
    session.flush()
    now = datetime(2026, 11, 10, 7, 0, tzinfo=UTC)
    day = now.astimezone(TEHRAN).date()
    for iid in session.scalars(select(Instrument.id)):
        session.add(PriceDaily(instrument_id=iid, date=day, close=1000))
    session.flush()
    store = MemoryStore()
    state = IntradayState()
    poll1 = [
        mw("111", volume=500, value=9_000_000),
        mw("112", volume=300, value=1_000_000),
        mw("113", volume=0, value=0),  # nothing traded: no snapshot
        mw("999", volume=10, value=10),  # not in our instrument table
    ]
    poll2 = [mw("111", volume=650, value=9_500_000), *poll1[1:]]

    r1 = store_quotes(session, store, poll1, state, book_top_n=1, fetched_at=now)
    assert r1 == {"quotes": 4, "snapshots": 2, "books": 1, "limits": 2}
    r2 = store_quotes(session, store, poll2, state, book_top_n=1, fetched_at=now.replace(minute=1))
    assert r2["snapshots"] == 1 and r2["limits"] == 0  # limits are written once per day

    snaps = session.scalars(select(IntradaySnapshot)).all()
    assert len(snaps) == 3 and all(s.source_url and s.fetched_at for s in snaps)
    assert {s.cum_volume for s in snaps} == {500, 300, 650}
    book = session.scalars(select(OrderBookSnapshot)).first()
    assert book is not None and len(book.levels) == 5 and book.levels[0]["bid_price"] == 999
    px = session.scalars(select(PriceDaily).where(PriceDaily.limit_up.is_not(None))).all()
    assert len(px) == 2 and all(p.limit_up == 1050 and p.limit_down == 950 for p in px)
    assert len(session.scalars(select(RawPayload)).all()) == 1  # raw kept for poll #0 only


def test_feed_with_unknown_layout_is_refused(session):
    with pytest.raises(FeedError):
        store_quotes(
            session,
            MemoryStore(),
            [{"x": 1}],
            IntradayState(),
            book_top_n=1,
            fetched_at=datetime(2026, 11, 10, tzinfo=UTC),
        )
    with pytest.raises(FeedError):
        store_quotes(
            session,
            MemoryStore(),
            [],
            IntradayState(),
            book_top_n=1,
            fetched_at=datetime(2026, 11, 10, tzinfo=UTC),
        )


def test_sector_names_come_from_static_data(session):
    class Api:
        async def static_data(self):
            return [
                {"type": "IndustrialGroup", "code": "1", "name": " زراعت "},
                {"type": "IndustrialGroup", "code": "27", "name": "فلزات اساسی"},
                {"type": "Other", "code": "5", "name": "x"},
            ]

    assert asyncio.run(sync_sector_names(session, Api())) == 2
    got = {s.code: s.name for s in session.scalars(select(SectorName))}
    assert got == {"01": "زراعت", "27": "فلزات اساسی"}


def test_trading_hours_follow_the_rule_not_a_constant(session):
    rules = seed_rulebook()
    # 2026-07-01 is after the seeded rule becomes valid (2026-06-06); 09:00-12:30 Tehran = 05:30-09:00 UTC
    assert in_trading_hours(rules, datetime(2026, 7, 1, 6, 0, tzinfo=UTC))
    assert not in_trading_hours(rules, datetime(2026, 7, 1, 3, 0, tzinfo=UTC))
    assert not in_trading_hours(rules, datetime(2026, 7, 1, 10, 0, tzinfo=UTC))
    assert not in_trading_hours(RuleBook([]), datetime(2026, 7, 1, 6, 0, tzinfo=UTC))


def test_probe_reports_unreachable_network_honestly():
    async def go():
        client = _client()
        try:
            with respx.mock:
                respx.get(endpoints.MARKET_WATCH_INIT).mock(side_effect=httpx.ConnectTimeout("t"))
                return await run_probe(client)
        finally:
            await client.aclose()

    checks = asyncio.run(go())
    assert len(checks) == 1 and checks[0].ok is False
    assert "not reachable" in checks[0].detail and "TMON_HTTP_PROXY" in checks[0].detail
    assert "0/1" in format_report(checks)


def test_probe_cross_checks_columns_against_history():
    today = datetime.now(UTC).astimezone(
        __import__("tmon.core.timeutil", fromlist=["TEHRAN"]).TEHRAN
    )
    d = today.strftime("%Y%m%d")
    hist = "\n".join(
        [
            "<TICKER>,<DTYYYYMMDD>,<FIRST>,<HIGH>,<LOW>,<CLOSE>,<VALUE>,<VOL>,<OPENINT>,<PER>,<OPEN>,<LAST>",
            f"S,{d},1000,1030,990,1005,5000000,500,30,D,1000,1010",
        ]
    )
    clients = f"{d},10,2,8,3,1000,200,900,300,5000,1000,4500,1500"
    info = {
        "instrumentInfo": {
            "insCode": "111",
            "lVal18AFC": "الف",
            "lVal30": "شرکت الف",
            "cIsin": "IRO1111",
            "sector": {"cSecVal": "27", "lSecVal": "فلزات"},
            "cgrValCot": "N1",
            "lVal18": "x",
            "flow": 1,
            "flowTitle": "بازار اول",
            "zTitad": 1000,
            "baseVol": 100,
        }
    }

    async def go():
        client = _client()
        try:
            with respx.mock:
                respx.get(endpoints.MARKET_WATCH_INIT).mock(
                    return_value=httpx.Response(
                        200, text=watch(row("111", "الف", volume=500, value=5_000_000))
                    )
                )
                respx.get(endpoints.daily_history_url("111")).mock(
                    return_value=httpx.Response(200, text=hist)
                )
                respx.get(endpoints.client_types_url("111")).mock(
                    return_value=httpx.Response(200, text=clients)
                )
                respx.get(endpoints.instrument_info_url("111")).mock(
                    return_value=httpx.Response(200, json=info)
                )
                respx.get(endpoints.best_limits_live_url("111")).mock(
                    return_value=httpx.Response(200, json=BOOK)
                )
                return await run_probe(client)
        finally:
            await client.aclose()

    checks = {c.name.split(" (")[0]: c for c in asyncio.run(go())}
    cc = next(c for c in checks.values() if c.name.startswith("cross-check"))
    assert cc.ok is True and "yesterday==prev_close:True" in cc.detail
    assert "final==last:True" in cc.detail  # tells the operator which column is which
    assert checks["live order book"].ok is True


def test_file_store_round_trip_and_refuses_path_escape(tmp_path):
    s = FileStore(tmp_path)
    s.put("raw", "tsetmc/2026/a.json", b"{}", "application/json")
    assert s.get("raw", "tsetmc/2026/a.json") == b"{}"
    with pytest.raises(ValueError):
        s.put("raw", "../../escape.txt", b"x", "text/plain")
