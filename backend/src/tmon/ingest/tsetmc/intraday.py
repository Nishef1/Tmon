"""Live (intraday) TSETMC ingestion on top of the ``iran-bourse-mcp`` client.

One ``GetMarketWatch`` request returns every instrument with its price, volume, daily price limits
and 5-level order book, so a poll costs one request and no per-instrument book calls. The library
owns HTTP (User-Agent, retries, 429 cool-downs); this module only maps its rows onto our tables.

Economies (docs/OPEN_QUESTIONS.md): the raw payload is kept every ``RAW_EVERY`` polls, and books are
stored for the ``book_top_n`` most traded instruments of the moment.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, time
from typing import Any

from iran_bourse_mcp.api import TseApi
from iran_bourse_mcp.client import Http
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from tmon.core.config import get_settings
from tmon.core.db import session_scope
from tmon.core.timeutil import TEHRAN, utcnow
from tmon.domain.rules import MissingRuleError, RuleBook
from tmon.ingest.tsetmc.pipeline import SOURCE
from tmon.storage.models import (
    Instrument,
    IntradaySnapshot,
    OrderBookSnapshot,
    PriceDaily,
    SectorName,
)
from tmon.storage.objectstore import ObjectStore, get_object_store, store_raw_payload
from tmon.storage.repositories import upsert

log = logging.getLogger(__name__)

RAW_EVERY = 10  # keep the raw market-watch payload on every 10th poll (~5 min at 30 s)
URL = "https://cdn.tsetmc.com/api/ClosingPrice/GetMarketWatch"


class FeedError(RuntimeError):
    """The market-watch feed returned nothing usable (layout change or outage)."""


def _hhmm(s: str) -> time:
    h, m = s.split(":")
    return time(int(h), int(m))


def in_trading_hours(rules: RuleBook, now: datetime) -> bool:
    """Whether ``now`` is inside the exchange's trading hours (``market_rules.trading_hours``,
    Tehran time). Days off are not modelled here: a closed day simply produces no new trades,
    and unchanged quotes are not stored again."""
    local = now.astimezone(TEHRAN)
    try:
        hours = rules.value("trading_hours", local.date())
    except MissingRuleError:
        return False
    return _hhmm(hours["open"]) <= local.time() <= _hhmm(hours["close"])


@dataclass
class IntradayState:
    """Carried between polls of one process so unchanged quotes are not stored again."""

    polls: int = 0
    last_volume: dict[str, float] = field(default_factory=dict)
    limits_stored: set[str] = field(default_factory=set)


def _levels(row: dict[str, Any]) -> list[dict[str, float | int]]:
    return [
        {
            "row": int(b["n"]),
            "bid_price": float(b["pmd"]),
            "bid_volume": float(b["qmd"]),
            "bid_count": int(b["zmd"]),
            "ask_price": float(b["pmo"]),
            "ask_volume": float(b["qmo"]),
            "ask_count": int(b["zmo"]),
        }
        for b in row.get("blDs") or []
    ]


def store_quotes(
    session: Session,
    store: ObjectStore,
    quotes: list[dict[str, Any]],
    state: IntradayState,
    *,
    book_top_n: int,
    fetched_at: datetime,
) -> dict[str, int]:
    """Write one market-watch poll: changed quotes, books of the most traded, daily limits."""
    if not quotes or "insCode" not in quotes[0]:
        raise FeedError("market-watch returned no rows or an unknown layout")
    if state.polls % RAW_EVERY == 0:
        store_raw_payload(
            session,
            store,
            source=SOURCE,
            source_url=URL,
            payload=json.dumps(quotes, ensure_ascii=False).encode(),
            fetched_at=fetched_at,
            ext="json",
        )
    state.polls += 1

    ids = {code: iid for iid, code in session.execute(select(Instrument.id, Instrument.ins_code))}
    rows: list[dict[str, object]] = []
    fresh: list[tuple[float, dict[str, Any], int]] = []
    for q in quotes:
        code = str(q["insCode"])
        iid = ids.get(code)
        volume = float(q.get("qTotTran5J") or 0)
        if iid is None or volume <= 0 or state.last_volume.get(code) == volume:
            continue  # unknown instrument, nothing traded, or no new trade since the last poll
        state.last_volume[code] = volume
        fresh.append((float(q.get("qTotCap") or 0), q, iid))
        rows.append(
            {
                "instrument_id": iid,
                "ts": fetched_at,
                "last_price": q.get("pDrCotVal"),
                "cum_volume": volume,
                "source_url": URL,
                "fetched_at": fetched_at,
            }
        )
    stored = upsert(session, IntradaySnapshot, rows)

    top = sorted(fresh, key=lambda t: t[0], reverse=True)[:book_top_n]
    books = upsert(
        session,
        OrderBookSnapshot,
        [
            {
                "instrument_id": iid,
                "ts": fetched_at,
                "levels": lv,
                "source_url": URL,
                "fetched_at": fetched_at,
            }
            for _, q, iid in top
            if (lv := _levels(q))
        ],
    )

    day = fetched_at.astimezone(TEHRAN).date()
    n_limits = 0
    for _, q, iid in fresh:
        code = str(q["insCode"])
        if code in state.limits_stored or not q.get("pMax") or not q.get("pMin"):
            continue
        state.limits_stored.add(code)
        res = session.execute(
            update(PriceDaily)
            .where(PriceDaily.instrument_id == iid, PriceDaily.date == day)
            .values(limit_up=float(q["pMax"]), limit_down=float(q["pMin"]))
        )
        n_limits += getattr(res, "rowcount", 0) or 0
    session.flush()
    return {"quotes": len(quotes), "snapshots": stored, "books": books, "limits": n_limits}


async def snapshot_once(
    session: Session,
    store: ObjectStore,
    api: TseApi,
    state: IntradayState | None = None,
    *,
    book_top_n: int | None = None,
) -> dict[str, int]:
    state = state or IntradayState()
    n_books = get_settings().book_top_n if book_top_n is None else book_top_n
    quotes = await api.market_watch_all()
    return store_quotes(session, store, quotes, state, book_top_n=n_books, fetched_at=utcnow())


async def sync_sector_names(session: Session, api: TseApi) -> int:
    """Store the industry-group code -> name table (one static request, rarely changes)."""
    fetched_at = utcnow()
    rows = [
        {
            "code": str(r["code"]).strip().zfill(2),
            "name": str(r["name"]).strip().replace("ي", "ی").replace("ك", "ک"),
            "source_url": "https://cdn.tsetmc.com/api/StaticData/GetStaticData",
            "fetched_at": fetched_at,
        }
        for r in await api.static_data()
        if r.get("type") == "IndustrialGroup" and r.get("code") is not None and r.get("name")
    ]
    return upsert(session, SectorName, rows)


def trading_now(session: Session) -> bool:
    return in_trading_hours(RuleBook.from_session(session), utcnow())


async def run_loop(
    *,
    once: bool = False,
    force: bool = False,
    follow: bool = False,
    interval: float | None = None,
) -> dict[str, int]:
    """Poll until the trading session ends (or once). With ``follow`` it idles outside trading
    hours and resumes at the next open instead of stopping. Each poll commits, so a crash loses
    at most one snapshot."""
    gap = get_settings().intraday_interval_seconds if interval is None else interval
    http = Http()
    api = TseApi(http)
    store = get_object_store()
    state = IntradayState()
    totals = {"polls": 0, "snapshots": 0, "books": 0, "failed": 0}
    try:
        while True:
            with session_scope() as session:
                if not force and not trading_now(session):
                    if not follow:
                        log.info("outside trading hours; stopping")
                        break
                    state = IntradayState()  # a new session starts from a clean slate
                    await asyncio.sleep(60)
                    continue
                try:
                    r = await snapshot_once(session, store, api, state)
                    totals["snapshots"] += r["snapshots"]
                    totals["books"] += r["books"]
                except Exception as exc:  # library raises its own error types
                    totals["failed"] += 1
                    log.error("intraday poll failed: %s", exc)
                totals["polls"] += 1
            if once:
                break
            await asyncio.sleep(gap)
    finally:
        await http.aclose()
    return totals


def run_intraday(**kwargs: object) -> dict[str, int]:
    return asyncio.run(run_loop(**kwargs))  # type: ignore[arg-type]
