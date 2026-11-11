"""Live (intraday) TSETMC ingestion: price/volume snapshots for the whole market from one
market-watch request, plus the 5-level order book for the most active instruments.

Same rules as the end-of-day pipeline: polite client, ``source_url``/``fetched_at`` on every row,
UTC storage. Two deliberate economies, listed in docs/OPEN_QUESTIONS.md:

* the raw market-watch payload (~MBs) is stored every ``RAW_EVERY`` polls, not on every poll;
* order books are fetched only for the ``book_top_n`` most traded instruments of the moment
  (one request per instrument would break the per-domain rate limit for ~700 symbols).
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import datetime, time

from sqlalchemy import select
from sqlalchemy.orm import Session

from tmon.core.config import get_settings
from tmon.core.db import session_scope
from tmon.core.timeutil import TEHRAN, utcnow
from tmon.domain.rules import MissingRuleError, RuleBook
from tmon.ingest.http import FetchError, PoliteClient
from tmon.ingest.tsetmc import endpoints, parsers
from tmon.ingest.tsetmc.classify import get_classifier
from tmon.ingest.tsetmc.pipeline import Ctx
from tmon.storage.models import Instrument, IntradaySnapshot, OrderBookSnapshot
from tmon.storage.objectstore import get_object_store
from tmon.storage.repositories import upsert

log = logging.getLogger(__name__)

RAW_EVERY = 10  # keep the raw market-watch payload on every 10th poll (~5 min at 30 s)


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


async def snapshot_once(
    ctx: Ctx, state: IntradayState | None = None, *, book_top_n: int | None = None
) -> dict[str, int]:
    state = state or IntradayState()
    n_books = get_settings().book_top_n if book_top_n is None else book_top_n
    keep_raw = state.polls % RAW_EVERY == 0
    state.polls += 1

    url = endpoints.MARKET_WATCH_INIT
    text, fetched_at = await ctx.fetch_text(url, keep_raw=keep_raw)
    quotes = parsers.parse_market_watch_quotes(text)

    ids = {
        code: iid for iid, code in ctx.session.execute(select(Instrument.id, Instrument.ins_code))
    }
    rows: list[dict[str, object]] = []
    fresh: list[parsers.WatchQuote] = []
    for q in quotes:
        iid = ids.get(q.ins_code)
        if iid is None or q.volume <= 0:
            continue
        if state.last_volume.get(q.ins_code) == q.volume:
            continue  # no new trade since the last poll
        state.last_volume[q.ins_code] = q.volume
        fresh.append(q)
        rows.append(
            {
                "instrument_id": iid,
                "ts": fetched_at,
                "last_price": q.final,
                "cum_volume": q.volume,
                "source_url": url,
                "fetched_at": fetched_at,
            }
        )
    stored = upsert(ctx.session, IntradaySnapshot, rows)

    books = 0
    for q in sorted(fresh, key=lambda x: x.value, reverse=True)[:n_books]:
        try:
            books += await _snapshot_book(ctx, ids[q.ins_code], q.ins_code)
        except (FetchError, parsers.ParseError) as exc:
            log.warning("order book failed for %s: %s", q.ins_code, exc)
    ctx.session.flush()
    return {"quotes": len(quotes), "snapshots": stored, "books": books}


async def _snapshot_book(ctx: Ctx, instrument_id: int, ins_code: str) -> int:
    url = endpoints.best_limits_live_url(ins_code)
    text, fetched_at = await ctx.fetch_text(url, ext="json", keep_raw=False)
    levels = parsers.parse_best_limits(text)
    return upsert(
        ctx.session,
        OrderBookSnapshot,
        [
            {
                "instrument_id": instrument_id,
                "ts": fetched_at,
                "levels": [lv.as_dict() for lv in levels],
                "source_url": url,
                "fetched_at": fetched_at,
            }
        ],
    )


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
    client = PoliteClient()
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
                ctx = Ctx(session, client, get_object_store(), get_classifier())
                try:
                    r = await snapshot_once(ctx, state)
                    totals["snapshots"] += r["snapshots"]
                    totals["books"] += r["books"]
                except (FetchError, parsers.ParseError) as exc:
                    totals["failed"] += 1
                    log.error("intraday poll failed: %s", exc)
                totals["polls"] += 1
            if once:
                break
            await asyncio.sleep(gap)
    finally:
        await client.aclose()
    return totals


def run_intraday(**kwargs: object) -> dict[str, int]:
    return asyncio.run(run_loop(**kwargs))  # type: ignore[arg-type]
