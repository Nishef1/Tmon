"""How heavy a buy queue is: the bid volume left at the close divided by the usual daily volume.

A symbol locked at its upper limit has bids and (almost) no asks. A new buy order joins the back of
that line, so what matters is how many shares are ahead of it compared with what normally trades in
a day. The reading is the queue at the close of the latest priced day, which is the line waiting at
the next open. Nothing is cached: the stored book day must be the latest price day, otherwise the
symbol gets no reading.
"""

from __future__ import annotations

import datetime as dt
from statistics import median
from typing import Literal

from sqlalchemy import select
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
