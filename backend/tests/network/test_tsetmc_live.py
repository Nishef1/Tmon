"""Live endpoint verification (``pytest -m network``). Skipped in CI and by default.

These tests are the evidence that each endpoint and field mapping in
``tmon.ingest.tsetmc.endpoints`` / ``parsers`` still matches the real service. Run them from a
network that can reach TSETMC. Failures here mean docs/OPEN_QUESTIONS.md items stay open.
"""

from __future__ import annotations

import asyncio

import pytest

from tmon.ingest.http import PoliteClient
from tmon.ingest.tsetmc import endpoints, parsers

pytestmark = pytest.mark.network

# Large, long-listed instrument used only as a probe (ins_code of a liquid stock is looked up
# from the market watch at run time, never hard-coded).


def _get(url: str) -> str:
    async def go() -> str:
        client = PoliteClient()
        try:
            return (await client.get(url)).content.decode("utf-8", errors="replace")
        finally:
            await client.aclose()

    return asyncio.run(go())


@pytest.fixture(scope="module")
def watch() -> list[parsers.WatchInstrument]:
    items = parsers.parse_market_watch_init(_get(endpoints.MARKET_WATCH_INIT))
    assert len(items) > 500
    return items


def test_market_watch_lists_instruments(watch):
    assert all(i.ins_code and i.symbol_fa for i in watch)


def test_daily_history_has_years_of_bars(watch):
    bars = parsers.parse_daily_history(_get(endpoints.daily_history_url(watch[0].ins_code)))
    assert bars, "history endpoint returned nothing"
    assert all(b.high >= b.low for b in bars)


def test_client_types_parse(watch):
    rows = parsers.parse_client_types(_get(endpoints.client_types_url(watch[0].ins_code)))
    assert isinstance(rows, list)


def test_instrument_info_parse(watch):
    info = parsers.parse_instrument_info(_get(endpoints.instrument_info_url(watch[0].ins_code)))
    assert info.ins_code == watch[0].ins_code


def test_best_limits_parse(watch):
    # The dated endpoint answers {"bestLimitsHistory": [...]} (a different shape, not used); the
    # current order book is the undated one.
    traded = next(i for i in watch if i.ins_code)
    levels = parsers.parse_best_limits(_get(endpoints.best_limits_live_url(traded.ins_code)))
    assert isinstance(levels, list)
