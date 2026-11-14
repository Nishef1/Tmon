"""Historical 5-level order book, reduced to one row per instrument and day.

``cdn.tsetmc.com/api/BestLimits/{ins}/{yyyymmdd}`` returns the day's whole change log of the five
best limits (about 10 000 to 30 000 events, 2 to 5 MB). This module downloads it, rebuilds the book
after every event, and keeps only what the models use: the closing book, the book at the start of
trading, time-weighted averages over the continuous session and the share of the session spent in
a buy or sell queue (``OrderBookDaily``). The raw log is not stored.

``python -m tmon.ingest.tsetmc.book_history --top 100 --days 300`` fills the table for the most
traded names. It is resumable: days already stored are skipped.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
from collections.abc import Iterable, Sequence
from datetime import date
from typing import Any

import httpx
import numpy as np
from sqlalchemy import text

from tmon.core.db import session_scope
from tmon.core.timeutil import utcnow
from tmon.ingest.tsetmc.endpoints import BEST_LIMITS
from tmon.storage.models import OrderBookDaily
from tmon.storage.repositories import upsert

log = logging.getLogger(__name__)

SESSION_START = 9 * 3600  # 09:00:00, continuous trading
SESSION_END = 12 * 3600 + 30 * 60  # 12:30:00
EARLY_END = SESSION_START + 30 * 60
CLOSE_GRACE = 5 * 60  # closing auction events up to 12:35 still belong to the closing book
LEVELS = 5
HEADERS = {"User-Agent": "Mozilla/5.0", "Accept-Encoding": "gzip"}


def _seconds(hhmmss: np.ndarray[Any, Any]) -> np.ndarray[Any, Any]:
    h = hhmmss.astype(np.int64)
    out: np.ndarray[Any, Any] = (h // 10000) * 3600 + (h // 100 % 100) * 60 + h % 100
    return out


def _levels(
    rows: Sequence[dict[str, Any]],
) -> tuple[np.ndarray[Any, Any], dict[str, np.ndarray[Any, Any]]]:
    """Event times (seconds) and, for each of ``bv bp bn av ap an``, a ``(events, 5)`` array with
    the state of every level after each event (NaN until a level has been seen)."""
    order = sorted(range(len(rows)), key=lambda i: (rows[i]["hEven"], rows[i]["refID"]))
    r = [rows[i] for i in order]
    n = len(r)
    t = _seconds(np.array([x["hEven"] for x in r]))
    lvl = np.array([x["number"] for x in r])
    src = {
        "bv": "qTitMeDem",
        "bp": "pMeDem",
        "bn": "zOrdMeDem",
        "av": "qTitMeOf",
        "ap": "pMeOf",
        "an": "zOrdMeOf",
    }
    raw = {k: np.array([float(x[v]) for x in r]) for k, v in src.items()}
    out = {k: np.full((n, LEVELS), np.nan) for k in src}
    idx = np.arange(n)
    for k in range(1, LEVELS + 1):
        mask = lvl == k
        if not mask.any():
            continue
        last = np.maximum.accumulate(np.where(mask, idx, -1))
        seen = last >= 0
        for key in src:
            out[key][seen, k - 1] = raw[key][last[seen]]
    return t, out


def _imbalance(bv: np.ndarray[Any, Any], av: np.ndarray[Any, Any]) -> np.ndarray[Any, Any]:
    b = np.nan_to_num(bv).sum(axis=1)
    a = np.nan_to_num(av).sum(axis=1)
    tot = b + a
    with np.errstate(invalid="ignore", divide="ignore"):
        return np.where(tot > 0, (b - a) / tot, np.nan)


def _wmean(x: np.ndarray[Any, Any], w: np.ndarray[Any, Any]) -> float | None:
    ok = np.isfinite(x) & (w > 0)
    s = w[ok].sum()
    return float((x[ok] * w[ok]).sum() / s) if s > 0 else None


def reduce_day(rows: Sequence[dict[str, Any]]) -> dict[str, Any] | None:
    """The ``OrderBookDaily`` columns (without keys and provenance) of one day's change log, or
    ``None`` for a day without any events."""
    if not rows:
        return None
    t, s = _levels(rows)
    n = t.size
    bv, bp, bn = s["bv"], s["bp"], s["bn"]
    av, ap, an = s["av"], s["ap"], s["an"]
    imb = _imbalance(bv, av)
    nxt = np.append(t[1:], SESSION_END)
    lo = np.maximum(t, SESSION_START)
    hi = np.minimum(nxt, SESSION_END)
    w = np.clip(hi - lo, 0, None).astype(float)
    w_early = np.clip(np.minimum(nxt, EARLY_END) - np.maximum(t, SESSION_START), 0, None).astype(
        float
    )
    b1, a1 = np.nan_to_num(bv[:, 0]), np.nan_to_num(av[:, 0])
    bp1, ap1 = np.nan_to_num(bp[:, 0]), np.nan_to_num(ap[:, 0])
    two_sided = (b1 > 0) & (a1 > 0) & (bp1 > 0) & (ap1 > 0)
    mid = (ap1 + bp1) / 2
    with np.errstate(invalid="ignore", divide="ignore"):
        spread = np.where(two_sided, (ap1 - bp1) / mid, np.nan)
        bsz = bv[:, 0] / bn[:, 0]
        asz = av[:, 0] / an[:, 0]
        size_ratio = np.where(two_sided & (bsz > 0) & (asz > 0), np.log(bsz / asz), np.nan)
    depth = (np.nan_to_num(bv * bp) + np.nan_to_num(av * ap)).sum(axis=1)
    buy_q = (a1 <= 0) & (b1 > 0)
    sell_q = (b1 <= 0) & (a1 > 0)
    span = float(SESSION_END - SESSION_START)
    in_session = w > 0
    peak_buy = float(b1[buy_q & in_session].max()) if (buy_q & in_session).any() else 0.0
    peak_sell = float(a1[sell_q & in_session].max()) if (sell_q & in_session).any() else 0.0
    close_i = int(np.searchsorted(t, SESSION_END + CLOSE_GRACE, side="right")) - 1
    open_i = int(np.searchsorted(t, SESSION_START, side="right")) - 1

    def at(i: int, arr: np.ndarray[Any, Any]) -> float | None:
        if i < 0:
            return None
        v = arr[i]
        return float(v) if np.isfinite(v) else None

    def at_count(i: int, arr: np.ndarray[Any, Any]) -> int | None:
        v = at(i, arr)
        return None if v is None else int(v)

    return {
        "n_events": int(n),
        "close_bid_price": at(close_i, bp[:, 0]),
        "close_ask_price": at(close_i, ap[:, 0]),
        "close_bid_volume": at(close_i, bv[:, 0]),
        "close_ask_volume": at(close_i, av[:, 0]),
        "close_bid_count": at_count(close_i, bn[:, 0]),
        "close_ask_count": at_count(close_i, an[:, 0]),
        "close_imbalance": at(close_i, imb),
        "open_imbalance": at(open_i, imb),
        "early_imbalance": _wmean(imb, w_early),
        "tw_imbalance": _wmean(imb, w),
        "tw_spread": _wmean(spread, w),
        "tw_depth_value": _wmean(depth, w),
        "tw_size_ratio": _wmean(size_ratio, w),
        "frac_buy_queue": float((w * buy_q).sum() / span),
        "frac_sell_queue": float((w * sell_q).sum() / span),
        "peak_queue_volume": peak_buy if peak_buy >= peak_sell else -peak_sell,
    }


async def _fetch(
    client: httpx.AsyncClient, ins_code: str, day: date, tries: int = 5
) -> list[dict[str, Any]] | None:
    url = BEST_LIMITS.format(ins_code=ins_code, date=day.strftime("%Y%m%d"))
    for k in range(tries):
        try:
            r = await client.get(url)
            if r.status_code == 200:
                rows = r.json().get("bestLimitsHistory")
                return rows if isinstance(rows, list) else None
            if r.status_code not in (429, 500, 502, 503, 504):
                return None
        except (httpx.TimeoutException, httpx.TransportError, ValueError):
            pass
        await asyncio.sleep(2.0 * (k + 1))
    return None


async def collect(
    jobs: Iterable[tuple[int, str, date]], concurrency: int = 6, batch: int = 200
) -> int:
    """Download and store ``(instrument_id, ins_code, day)`` jobs; returns the rows written."""
    todo = list(jobs)
    sem = asyncio.Semaphore(concurrency)
    written = 0
    failed = 0
    async with httpx.AsyncClient(headers=HEADERS, timeout=90, follow_redirects=True) as client:

        async def one(job: tuple[int, str, date]) -> dict[str, Any] | None:
            iid, code, day = job
            async with sem:
                rows = await _fetch(client, code, day)
            if rows is None:
                return {"_failed": True}
            red = reduce_day(rows)
            if red is None:
                return {"_empty": True, "instrument_id": iid, "date": day}
            return {
                "instrument_id": iid,
                "date": day,
                **red,
                "source_url": BEST_LIMITS.format(ins_code=code, date=day.strftime("%Y%m%d")),
                "fetched_at": utcnow(),
            }

        for i in range(0, len(todo), batch):
            res = await asyncio.gather(*[one(j) for j in todo[i : i + batch]])
            good = [r for r in res if r and "_failed" not in r and "_empty" not in r]
            failed += sum(1 for r in res if r and "_failed" in r)
            with session_scope() as s:
                written += upsert(s, OrderBookDaily, good)
            log.info(
                "book_history %d/%d stored=%d failed=%d", i + len(res), len(todo), written, failed
            )
            print(f"{i + len(res)}/{len(todo)} stored={written} failed={failed}", flush=True)
    return written


def plan_jobs(top: int, days: int) -> list[tuple[int, str, date]]:
    """The ``top`` most traded stocks (median traded value of their last 20 days) and their
    last ``days`` trading days, minus the days already stored."""
    q = text(
        """
        with last as (
            select max(date) as d from prices_daily where volume > 0
        ), liq as (
            select p.instrument_id, avg(p.value) as v
            from prices_daily p, last, instruments ii
            where ii.id = p.instrument_id and ii.instrument_type = 'stock'
              and p.date > date(last.d, '-30 day') and p.volume > 0
            group by p.instrument_id
            order by v desc limit :top
        )
        select i.id, i.ins_code, p.date
        from liq
        join instruments i on i.id = liq.instrument_id
        join prices_daily p on p.instrument_id = i.id
        where p.volume > 0 and p.date in (
            select distinct date from prices_daily
            where date <= (select d from last) order by date desc limit :days
        )
        and not exists (
            select 1 from order_book_daily b where b.instrument_id = i.id and b.date = p.date
        )
        order by p.date desc, liq.v desc
        """
    )
    with session_scope() as s:
        rows = s.execute(q, {"top": top, "days": days}).all()
    return [(int(r[0]), str(r[1]), date.fromisoformat(str(r[2])[:10])) for r in rows]


def run_daily(top: int = 100, days: int = 5, concurrency: int = 6) -> dict[str, int]:
    """The daily cycle step: fill the missing book days of the most traded names (resumable)."""
    jobs = plan_jobs(top, days)
    written = asyncio.run(collect(jobs, concurrency)) if jobs else 0
    return {"jobs": len(jobs), "stored": written}


def main() -> None:
    ap = argparse.ArgumentParser(prog="tmon-book-history")
    ap.add_argument("--top", type=int, default=100)
    ap.add_argument("--days", type=int, default=300)
    ap.add_argument("--concurrency", type=int, default=6)
    args = ap.parse_args()
    jobs = plan_jobs(args.top, args.days)
    print("jobs", len(jobs), flush=True)
    asyncio.run(collect(jobs, args.concurrency))


if __name__ == "__main__":
    main()
