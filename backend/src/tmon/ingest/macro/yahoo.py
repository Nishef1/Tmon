"""World prices from Yahoo Finance's public chart endpoint (copper, Brent oil, gold, dollar index).

``query1.finance.yahoo.com/v8/finance/chart/{ticker}?period1=..&period2=..&interval=1d`` returns
``{"chart": {"result": [{"meta": {..., "gmtoffset"}, "timestamp": [...],
"indicators": {"quote": [{"open", "high", "low", "close", "volume"}]}}], "error": null}}``.
Checked on 2026-11-13; sample: ``tests/fixtures/macro/yahoo_hg.json`` (a real response, trimmed).
A timestamp is the session start in UTC; adding ``gmtoffset`` gives the exchange's own time.
Recent bars sit at midnight, older futures bars at the previous evening's session start.
These markets close after Tehran does, so a close dated D is first usable in Tehran on D+1:
``release_date`` = D + 1 day keeps every feature point-in-time.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

from tmon.ingest.tsetmc.parsers import ParseError

# explicit bounds: with range=max Yahoo silently returns monthly bars
API = (
    "https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
    "?period1=946684800&period2=4102444800&interval=1d"
)

# our series name -> Yahoo ticker (front-month futures for commodities)
SERIES: dict[str, str] = {
    "copper_usd": "HG=F",  # COMEX copper, USD per pound
    "brent_usd": "BZ=F",  # ICE Brent crude, USD per barrel
    "gold_usd": "GC=F",  # COMEX gold, USD per troy ounce
    "dxy": "DX-Y.NYB",  # ICE US dollar index
}
SOURCE = "yahoo"


@dataclass(frozen=True)
class Bar:
    date: date
    close: float


def url(ticker: str) -> str:
    return API.format(ticker=ticker)


def parse_chart(payload: bytes) -> list[Bar]:
    try:
        res = json.loads(payload)["chart"]["result"][0]
        off = int(res["meta"].get("gmtoffset") or 0)
        ts = res.get("timestamp") or []
        closes = res["indicators"]["quote"][0]["close"]
    except (ValueError, KeyError, TypeError, IndexError) as exc:
        raise ParseError(f"yahoo: not a chart payload: {payload[:120]!r}") from exc
    out: dict[date, float] = {}
    for t, c in zip(ts, closes, strict=False):
        if c is None or c <= 0:
            continue  # holidays and gaps come back as null
        local = datetime.fromtimestamp(t, UTC) + timedelta(seconds=off)
        # older futures bars are stamped at the evening session start (Sunday 18:00 for Monday)
        d = (local + timedelta(days=1)).date() if local.hour >= 12 else local.date()
        out[d] = float(c)
    return [Bar(d, c) for d, c in sorted(out.items())]


def release(d: date) -> date:
    return d + timedelta(days=1)
