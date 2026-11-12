"""End to end over REAL sockets against the synthetic TSETMC stand-in (tmon.devtools.fake_tsetmc):
HTTP client -> parsers -> backfill -> features -> model -> intraday poller -> probe.

This proves our code against the documented payload formats. It is not evidence about the real
service or the market (docs/OPEN_QUESTIONS.md items 48-50)."""

from __future__ import annotations

import asyncio
from datetime import datetime

import httpx
import pytest
from sqlalchemy import func, select

from tmon.core.timeutil import TEHRAN
from tmon.devtools.fake_tsetmc import serve
from tmon.ingest.http import DomainRateLimiter, PoliteClient, RetryPolicy
from tmon.ingest.tsetmc import endpoints
from tmon.ingest.tsetmc.classify import load_classifier
from tmon.ingest.tsetmc.pipeline import Ctx, backfill
from tmon.ingest.tsetmc.probe import run_probe
from tmon.storage.models import (
    ClientTypeDaily,
    Instrument,
    PriceDaily,
)
from tmon.storage.objectstore import MemoryStore


def _point_endpoints_at(monkeypatch: pytest.MonkeyPatch, base: str) -> None:
    for name in (
        "MARKET_WATCH_INIT",
        "DAILY_HISTORY",
        "CLIENT_TYPES",
        "INSTRUMENT_INFO",
        "BEST_LIMITS",
        "BEST_LIMITS_LIVE",
    ):
        url = getattr(endpoints, name)
        for real in (endpoints.OLD, endpoints.CDN):
            url = url.replace(real, base)
        monkeypatch.setattr(endpoints, name, url)


def _client() -> PoliteClient:
    return PoliteClient(
        limiter=DomainRateLimiter(0.0),
        retry=RetryPolicy(max_retries=0, jitter=0.0),
        client=httpx.AsyncClient(timeout=20),
    )


@pytest.fixture
def closed_market(monkeypatch):
    server = serve(0, live=False, n_inst=12, n_days=300)
    _point_endpoints_at(monkeypatch, f"http://127.0.0.1:{server.server_port}")
    yield
    server.shutdown()


@pytest.fixture
def live_market(monkeypatch):
    server = serve(0, live=True, n_inst=12, n_days=300)
    _point_endpoints_at(monkeypatch, f"http://127.0.0.1:{server.server_port}")
    yield
    server.shutdown()


def test_backfill_over_http_then_probe_cross_check(session, closed_market):
    store = MemoryStore()

    async def go():
        client = _client()
        try:
            ctx = Ctx(session, client, store, load_classifier())
            totals = await backfill(ctx)
            checks = await run_probe(client)
            return totals, checks
        finally:
            await client.aclose()

    totals, checks = asyncio.run(go())
    assert totals["failed"] == 0 and totals["instruments"] == 12
    assert session.scalar(select(func.count()).select_from(Instrument)) == 12
    assert session.scalar(select(func.count()).select_from(PriceDaily)) > 12 * 250
    assert session.scalar(select(func.count()).select_from(ClientTypeDaily)) > 12 * 250
    # enrichment ran: sector and board come from the instrument-info endpoint
    assert all(i.sector_code for i in session.scalars(select(Instrument)))

    by_name = {c.name.split(" (")[0]: c for c in checks}
    bad = [c for c in checks if c.ok is False]
    assert not bad, [(c.name, c.detail) for c in bad]
    cross = next(c for c in checks if c.name.startswith("cross-check"))
    # closed market: the watch equals today's bar, so the column mapping is actually compared.
    # The synthetic calendar has no bar on Thursday/Friday; there the probe rightly says it cannot
    # compare, which is the only acceptable non-True answer.
    if datetime.now(TEHRAN).date().weekday() in (3, 4):
        assert cross.ok is None and "not comparable" in cross.detail, cross.detail
    else:
        assert cross.ok is True, cross.detail
    assert by_name["live order book"].ok is True


def test_limited_backfill_takes_the_most_liquid_instruments(session, closed_market):
    async def go():
        client = _client()
        try:
            ctx = Ctx(session, client, MemoryStore(), load_classifier())
            totals = await backfill(ctx, limit=3)
            return totals, dict(ctx.liquidity)
        finally:
            await client.aclose()

    totals, liquidity = asyncio.run(go())
    assert totals["instruments"] == 3
    done = {
        c
        for (c,) in session.execute(
            select(Instrument.ins_code).join(PriceDaily, PriceDaily.instrument_id == Instrument.id)
        )
    }
    top3 = sorted(liquidity, key=liquidity.__getitem__, reverse=True)[:3]
    assert done == set(top3)
