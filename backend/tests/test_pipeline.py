"""Pipeline integration test: mocked HTTP, SQLite, in-memory object store.

Payloads are synthetic and follow the documented field layout; they exercise the
orchestration (raw-first storage, provenance, adjustments, halt flagging, calendar)."""

from __future__ import annotations

import asyncio
from datetime import date

import httpx
import respx
from sqlalchemy import select

from tmon.ingest.http import DomainRateLimiter, PoliteClient, RetryPolicy
from tmon.ingest.tsetmc import endpoints
from tmon.ingest.tsetmc.classify import load_classifier
from tmon.ingest.tsetmc.pipeline import Ctx, backfill
from tmon.storage.models import (
    ClientTypeDaily,
    Instrument,
    PriceAdjustment,
    PriceDaily,
    RawPayload,
    TradingCalendar,
)
from tmon.storage.objectstore import MemoryStore

STOCK_CODES = ["111", "112", "113", "114", "115", "116"]  # calendar needs >=5 traded names
WATCH = "h@x@" + ";".join(
    [f"{c},IRO1AAA{c},فولاد{c},شرکت فولاد {c}" for c in STOCK_CODES]
    + ["222,IRO1BBB0001,حاAAA,حق تقدم شرکت x"]
)
HEADER = (
    "<TICKER>,<DTYYYYMMDD>,<FIRST>,<HIGH>,<LOW>,<CLOSE>,<VALUE>,<VOL>,<OPENINT>,<PER>,<OPEN>,<LAST>"
)
# day 3 opens at 510 against a prior close of 1020 -> a 2:1 capital event
HISTORY = "\n".join(
    [
        HEADER,
        "SYM,20260225,1000,1030,990,1020,5000000,5000,12,D,1000,1015",
        "SYM,20260226,510,530,505,520,6000000,6000,15,D,510,525",
        "SYM,20260301,520,540,510,530,6000000,6000,15,D,520,535",  # inside the halt window
        "SYM,20260519,530,540,520,535,6000000,6000,15,D,530,534",
    ]
)
CLIENTS = "20260225,10,2,8,3,1000,200,900,300,5000,1000,4500,1500"


def _run(session):
    store = MemoryStore()

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
            ctx = Ctx(session, client, store, load_classifier())
            return await backfill(ctx, enrich=False)
        finally:
            await client.aclose()

    with respx.mock:
        respx.get(endpoints.MARKET_WATCH_INIT).mock(return_value=httpx.Response(200, text=WATCH))
        for code in STOCK_CODES:
            # a distinct symbol per instrument keeps every payload (and its hash) unique
            respx.get(endpoints.daily_history_url(code)).mock(
                return_value=httpx.Response(200, text=HISTORY.replace("SYM", f"S{code}"))
            )
            respx.get(endpoints.client_types_url(code)).mock(
                return_value=httpx.Response(200, text=CLIENTS + f",{code}")
            )
        totals = asyncio.run(go())
    return totals, store


def test_backfill_end_to_end(session):
    totals, store = _run(session)

    # rights issues are not tradable instruments -> only the stock is ingested
    assert totals == {"instruments": 6, "bars": 24, "client_rows": 6, "failed": 0}
    codes = {i.ins_code: i.instrument_type for i in session.scalars(select(Instrument))}
    assert codes["222"] == "right"

    # raw payloads were stored and indexed (watch + history + clients)
    raws = session.scalars(select(RawPayload)).all()
    assert len(raws) == 1 + 2 * 6  # watch + (history, clients) per stock
    assert len(store.objects) == 1 + 2 * 6
    assert all(r.source_url and r.fetched_at for r in raws)

    first_id = session.scalar(select(Instrument.id).where(Instrument.ins_code == "111"))
    # provenance on every stored record
    bars = session.scalars(
        select(PriceDaily).where(PriceDaily.instrument_id == first_id).order_by(PriceDaily.date)
    ).all()
    assert [b.date for b in bars] == [
        date(2026, 2, 25),
        date(2026, 2, 26),
        date(2026, 3, 1),
        date(2026, 5, 19),
    ]
    assert all(b.source_url.startswith(endpoints.OLD) for b in bars)
    assert all(b.fetched_at is not None for b in bars)
    assert all(c.source_url for c in session.scalars(select(ClientTypeDaily)))

    # the 2:1 event is derived and the halt-window bar is flagged, not dropped
    adj = session.scalars(
        select(PriceAdjustment).where(PriceAdjustment.instrument_id == first_id)
    ).one()
    assert adj.date == date(2026, 2, 26)
    assert float(adj.adj_factor) == 0.5
    assert [b.market_halt for b in bars] == [False, False, True, False]

    # calendar: halt window is closed with a reason, reopening day is open
    cal = {c.date: c for c in session.scalars(select(TradingCalendar))}
    assert cal[date(2026, 3, 1)].is_open is False
    assert cal[date(2026, 3, 1)].halt_reason == "war_closure"
    assert cal[date(2026, 5, 19)].is_open is True


def test_backfill_is_idempotent(session):
    _run(session)
    _run(session)
    assert len(session.scalars(select(PriceDaily)).all()) == 24
    assert len(session.scalars(select(PriceAdjustment)).all()) == 6


def test_reclassify_backfills_type_code_from_stored_info_payloads(session):
    """Instruments enriched before ``yVal``/``faraDesc`` were kept get them from the raw store."""
    import json
    from datetime import UTC, datetime

    from tmon.domain.enums import InstrumentType as T
    from tmon.ingest.tsetmc.pipeline import backfill_info_tags, reclassify_instruments
    from tmon.storage.objectstore import store_raw_payload

    store = MemoryStore()
    when = datetime(2026, 11, 1, tzinfo=UTC)
    funds = {
        "901": ("صندوق س. ثابت نامی", "نوع صندوق : در اوراق بهادار با درآمد ثابت"),
        "902": ("صندوق طلای x", None),
    }
    codes = {"901": "305", "902": "380"}
    for code, (name, desc) in funds.items():
        session.add(Instrument(ins_code=code, symbol_fa=f"s{code}", name_fa=name,
                               instrument_type="etf_equity", tags={"group_title": "x"}))  # fmt: skip
        body = {"instrumentInfo": {"insCode": code, "lVal30": name, "yVal": codes[code],
                                   "faraDesc": desc}}  # fmt: skip
        store_raw_payload(
            session, store, source="tsetmc",
            source_url=endpoints.instrument_info_url(code),
            payload=json.dumps(body, ensure_ascii=False).encode(), fetched_at=when, ext="json",
        )  # fmt: skip
    session.flush()

    assert backfill_info_tags(session, store) == 2
    assert backfill_info_tags(session, store) == 0  # idempotent
    out = reclassify_instruments(session, load_classifier())
    assert out["changed"] == 2
    got = dict(session.execute(select(Instrument.ins_code, Instrument.instrument_type)).all())
    assert got["901"] == T.ETF_FIXED_INCOME and got["902"] == T.ETF_COMMODITY


ALL_TODAY = (
    '{"clientTypeAllDto":[{"insCode":"111","buy_I_Volume":800.0,"buy_N_Volume":200.0,'
    '"buy_DDD_Volume":0.0,"buy_CountI":40,"buy_CountN":1,"buy_CountDDD":0,'
    '"sell_I_Volume":300.0,"sell_N_Volume":700.0,"sell_CountI":10,"sell_CountN":2},'
    '{"insCode":"112","buy_I_Volume":5.0,"buy_N_Volume":0.0,"buy_DDD_Volume":0.0,'
    '"buy_CountI":1,"buy_CountN":0,"buy_CountDDD":0,"sell_I_Volume":5.0,"sell_N_Volume":0.0,'
    '"sell_CountI":1,"sell_CountN":0}]}'
)


def test_today_client_types_fill_only_missing_rows(session):
    """The evening run must not score today on yesterday's flow: instruments that traded today
    but whose history lacks today get today's split from the market-wide endpoint; rows that
    already exist are left alone."""
    from tmon.ingest.tsetmc.pipeline import fill_today_client_types

    _run(session)
    day = date(2026, 5, 19)
    a, b = (
        session.scalar(select(Instrument).where(Instrument.ins_code == c)) for c in ("111", "112")
    )
    session.add(ClientTypeDaily(instrument_id=b.id, date=day, buy_count_i=9, source_url="x"))
    session.flush()

    async def go():
        client = PoliteClient(
            limiter=DomainRateLimiter(0.0),
            retry=RetryPolicy(max_retries=0, jitter=0.0),
            client=httpx.AsyncClient(),
        )
        try:
            return await fill_today_client_types(
                Ctx(session, client, MemoryStore(), load_classifier()), today=day
            )
        finally:
            await client.aclose()

    with respx.mock:
        respx.get(endpoints.CLIENT_TYPES_ALL).mock(return_value=httpx.Response(200, text=ALL_TODAY))
        n = asyncio.run(go())
    assert n == 1  # 111 filled; 112 already had a row; others are absent from the payload
    got = session.get(ClientTypeDaily, (a.id, day))
    assert (got.buy_volume_i, got.sell_volume_n, got.buy_count_i, got.buy_value_i) == (
        800,
        700,
        40,
        None,
    )
    assert session.get(ClientTypeDaily, (b.id, day)).buy_count_i == 9


def _closing_reply(request: httpx.Request, day: date) -> httpx.Response:
    """A ClosingPrices answer: one block per requested item, one bar of ``day`` in each."""
    items = request.url.params["a"].split(";")
    row = f"x,{day:%Y%m%d},1100,1090,30,2000,2200000,1050,1120,1000,1010"
    return httpx.Response(200, text="@".join(row for _ in items))


def test_fast_end_of_day_batches_prices_and_heals_only_missing_flows(session):
    """The default daily update reads prices 50 instruments per request (no per-instrument
    history call: none is mocked), and fetches flows one by one only for days that lack them."""
    from datetime import timedelta

    from tmon.core.timeutil import to_tehran, utcnow
    from tmon.ingest.tsetmc.pipeline import end_of_day

    _run(session)
    day = to_tehran(utcnow()).date() - timedelta(days=2)
    flows_asked: list[str] = []

    def client_reply(request: httpx.Request) -> httpx.Response:
        flows_asked.append(str(request.url))
        return httpx.Response(
            200, text=f"{day:%Y%m%d},10,2,8,3,1000,200,900,300,5000,1000,4500,1500"
        )

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
            return await end_of_day(Ctx(session, client, MemoryStore(), load_classifier()))
        finally:
            await client.aclose()

    with respx.mock:
        respx.get(endpoints.MARKET_WATCH_INIT).mock(return_value=httpx.Response(200, text=WATCH))
        batch = respx.get(url__startswith=endpoints.SERVICE).mock(
            side_effect=lambda r: _closing_reply(r, day)
        )
        for code in STOCK_CODES:
            respx.get(endpoints.client_types_url(code)).mock(side_effect=client_reply)
        respx.get(endpoints.CLIENT_TYPES_ALL).mock(
            return_value=httpx.Response(200, text='{"clientTypeAllDto":[]}')
        )
        first = asyncio.run(go())
        asked_first = len(flows_asked)
        asyncio.run(go())  # nothing is missing any more: no flow is fetched again
    assert batch.call_count == 2  # six instruments fit one request per run
    assert first["failed"] == 0 and first["instruments"] == len(STOCK_CODES)
    assert asked_first == len(STOCK_CODES) and len(flows_asked) == asked_first
    for code in STOCK_CODES:
        iid = session.scalar(select(Instrument.id).where(Instrument.ins_code == code))
        assert session.get(PriceDaily, (iid, day)).volume == 2000
        assert session.get(ClientTypeDaily, (iid, day)).buy_count_i == 10
