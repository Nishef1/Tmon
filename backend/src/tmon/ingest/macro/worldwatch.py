"""Daily snapshots of two world-risk feeds without history: Polymarket and Forex Factory.

Polymarket: ``gamma-api.polymarket.com/public-search?q=..`` lists events with their markets;
``outcomePrices`` is a JSON string such as ``'["0.62","0.38"]'`` and the first price is the
probability of the first outcome. A market's own price history starts the day it was created, so
the only way to get a long series is to save it every day from now on. Each snapshot becomes one
``macro_series`` row per market: series ``pm:<slug>``, ``value`` = probability of the first
outcome, ``release_date`` = the day it was read. Checked 2026-11-20.

Forex Factory: ``nfs.faireconomy.media/ff_calendar_thisweek.json`` is a list of
``{"title","country","date" (ISO with offset),"impact","forecast","previous"}`` for the current
week only, with no actual value. The whole payload is saved as a raw payload each run, which keeps
forecast and previous as they were published.

Both feeds are for study. No feature or weight reads them.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from urllib.parse import quote

from tmon.ingest.tsetmc.parsers import ParseError

SEARCH = "https://gamma-api.polymarket.com/public-search?q={q}&limit_per_type=5"
FF_WEEK = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
SOURCE_PM = "polymarket"
SOURCE_FF = "forexfactory"
QUERIES = ("Iran", "oil", "Fed decision", "rate cut")
MIN_VOLUME = 1_000_000  # dollars; thinner markets are noise


@dataclass(frozen=True)
class Market:
    slug: str
    question: str
    prob: float
    volume: float
    end: str | None


def search_url(q: str) -> str:
    return SEARCH.format(q=quote(q))


def parse_search(payload: bytes) -> list[Market]:
    try:
        events = json.loads(payload).get("events") or []
    except (ValueError, AttributeError) as exc:
        raise ParseError(f"polymarket: not a search payload: {payload[:120]!r}") from exc
    out: list[Market] = []
    for ev in events:
        for m in ev.get("markets") or []:
            try:
                if m.get("closed") or not m.get("slug"):
                    continue
                prob = float(json.loads(m["outcomePrices"])[0])
                vol = float(m.get("volumeNum") or m.get("volume") or 0)
            except (KeyError, ValueError, TypeError, IndexError):
                continue
            if vol >= MIN_VOLUME:
                out.append(
                    Market(m["slug"], str(m.get("question", "")), prob, vol, m.get("endDate"))
                )
    return out


def parse_calendar(payload: bytes) -> list[dict[str, str]]:
    keys = ("title", "country", "date", "impact", "forecast", "previous")
    try:
        return [{k: str(r.get(k, "")) for k in keys} for r in json.loads(payload)]
    except (ValueError, AttributeError, TypeError) as exc:
        raise ParseError(f"forexfactory: not a calendar payload: {payload[:120]!r}") from exc


def snapshot_row(m: Market, day: date) -> dict[str, object]:
    return {
        "series": f"pm:{m.slug}"[:64],
        "source": SOURCE_PM,
        "ref_period": day,
        "value": m.prob,
        "release_date": day,
        "meta": {"question": m.question, "volume": m.volume, "end": m.end},
    }
