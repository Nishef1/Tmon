"""How heavy a buy queue is: the bid volume left at the close divided by the usual daily volume.

A symbol locked at its upper limit has bids and (almost) no asks. A new buy order joins the back of
that line, so what matters is how many shares are ahead of it compared with what normally trades in
a day. The reading is the queue at the close of the latest priced day, which is the line waiting at
the next open. Nothing is cached: the stored book day must be the latest price day, otherwise the
symbol gets no reading.
"""

from __future__ import annotations

import datetime as dt
from itertools import pairwise
from statistics import median
from typing import Literal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tmon.storage.models import OrderBookDaily, PriceDaily

Level = Literal["weak", "medium", "heavy"]

WINDOW_DAYS = 20  # trading days behind "usual daily volume"
ASK_SHARE_MAX = 0.02  # a line: the ask side holds at most 2% of the bid volume
WEAK_BELOW = 0.3  # queue / usual volume: under this the line tends to clear or break in a day
HEAVY_ABOVE = 1.0  # over this the line holds more than a whole usual day of trading


def level_of(ratio: float) -> Level:
    if ratio < WEAK_BELOW:
        return "weak"
    return "medium" if ratio <= HEAVY_ABOVE else "heavy"


def queue_ratio(
    bid_volume: float | None, ask_volume: float | None, usual: float | None
) -> tuple[float, Level] | None:
    """``(ratio, level)`` for a buy line, or ``None`` when it is no line or has no basis."""
    if not bid_volume or bid_volume <= 0 or not usual or usual <= 0:
        return None
    if (ask_volume or 0.0) > ASK_SHARE_MAX * bid_volume:
        return None
    ratio = bid_volume / usual
    return ratio, level_of(ratio)


def _usual_volume(session: Session, ids: list[int], day: dt.date) -> dict[int, float]:
    days = list(
        session.scalars(
            select(PriceDaily.date)
            .where(PriceDaily.date <= day)
            .distinct()
            .order_by(PriceDaily.date.desc())
            .limit(WINDOW_DAYS)
        )
    )
    if not days:
        return {}
    per: dict[int, list[float]] = {}
    for iid, vol in session.execute(
        select(PriceDaily.instrument_id, PriceDaily.volume).where(
            PriceDaily.instrument_id.in_(ids), PriceDaily.date.in_(days)
        )
    ):
        if vol and vol > 0:  # days without trading say nothing about the usual volume
            per.setdefault(iid, []).append(float(vol))
    return {iid: median(v) for iid, v in per.items() if len(v) >= 5}


def queue_readings(
    session: Session, ids: list[int], day: dt.date
) -> dict[int, tuple[float, Level, int | None]]:
    """``{id: (queue / usual volume, level, orders in line)}`` for the buy lines of ``day``."""
    if not ids:
        return {}
    usual = _usual_volume(session, ids, day)
    out: dict[int, tuple[float, Level, int | None]] = {}
    for b in session.scalars(
        select(OrderBookDaily).where(
            OrderBookDaily.instrument_id.in_(ids), OrderBookDaily.date == day
        )
    ):
        got = queue_ratio(b.close_bid_volume, b.close_ask_volume, usual.get(b.instrument_id))
        if got is not None:
            out[b.instrument_id] = (got[0], got[1], b.close_bid_count)
    return out


# queue / usual volume edges for the history table (last edge open-ended)
ODDS_EDGES = (0.0, 0.3, 0.7, 1.5, 5.0)
_odds_memo: dict[tuple[object, ...], list[tuple[float, float | None, int, float]]] = {}


def history_odds(session: Session) -> list[tuple[float, float | None, int, float]]:
    """Per ratio bucket ``(low, high, cases, share)``: how often the next day's total volume was at
    least the whole queue. Reaching a late order needs that much selling at the limit, so it is a
    necessary condition and an upper bound on the fill chance, not the chance itself. Computed from
    every stored one-sided close book; the memo is keyed by the data fingerprint, never by time."""
    stamp = (
        session.scalar(select(func.max(OrderBookDaily.date))),
        session.scalar(select(func.count()).select_from(OrderBookDaily)),
        session.scalar(select(func.max(PriceDaily.date))),
    )
    hit = _odds_memo.get(stamp)
    if hit is not None:
        return hit
    books: dict[int, list[OrderBookDaily]] = {}
    for b in session.scalars(select(OrderBookDaily).order_by(OrderBookDaily.date)):
        books.setdefault(b.instrument_id, []).append(b)
    vols: dict[int, dict[dt.date, float]] = {}
    for iid, d, vol in session.execute(
        select(PriceDaily.instrument_id, PriceDaily.date, PriceDaily.volume).where(
            PriceDaily.instrument_id.in_(list(books))
        )
    ):
        vols.setdefault(iid, {})[d] = float(vol or 0.0)
    cases: list[tuple[float, bool]] = []
    for iid, rows in books.items():
        v = vols.get(iid, {})
        days = sorted(v)
        for cur, nxt in pairwise(rows):
            bid = cur.close_bid_volume
            if bid is None or queue_ratio(bid, cur.close_ask_volume, 1.0) is None:
                continue
            past = [v[d] for d in days if d <= cur.date and v[d] > 0][-WINDOW_DAYS:]
            if len(past) < 5:
                continue
            ratio = float(bid) / median(past)
            cases.append((ratio, v.get(nxt.date, 0.0) >= float(bid)))
    out: list[tuple[float, float | None, int, float]] = []
    for i, lo in enumerate(ODDS_EDGES):
        hi = ODDS_EDGES[i + 1] if i + 1 < len(ODDS_EDGES) else None
        grp = [ok for r, ok in cases if r >= lo and (hi is None or r < hi)]
        if grp:
            out.append((lo, hi, len(grp), sum(grp) / len(grp)))
    _odds_memo.clear()
    _odds_memo[stamp] = out
    return out


def odds_for(
    ratio: float, table: list[tuple[float, float | None, int, float]]
) -> tuple[float, int] | None:
    """``(share, cases)`` of the history bucket that holds ``ratio``."""
    for lo, hi, n, share in table:
        if ratio >= lo and (hi is None or ratio < hi):
            return share, n
    return None
