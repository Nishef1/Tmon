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
