"""Today's daily bars from the exchange's per-symbol closing endpoint.

TSETMC's bulk history feed (``t=ClosingPrices``, used by the evening cycle) can publish a day hours
after the market closed. The per-symbol endpoint ``api/ClosingPrice/GetClosingPriceInfo`` already
holds the final figures, so when the bulk feed has no bar for the exchange day yet this fills it
from there. It writes only the same columns the bulk feed writes; the next bulk run replaces each
row with the official one (same primary key), so nothing here is kept as a second truth.

Never run while the market is open: the figures are then still moving.
"""

from __future__ import annotations

import datetime as dt
import logging
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import httpx
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tmon.core.timeutil import to_tehran, utcnow
from tmon.ingest.tsetmc.endpoints import CDN
from tmon.storage.models import Instrument, PriceDaily
from tmon.storage.repositories import upsert

log = logging.getLogger(__name__)

HEADERS = {"User-Agent": "Mozilla/5.0", "Accept": "application/json", "Cache-Control": "no-store"}
TIMEOUT = 15.0
WORKERS = 8
MARKET_CLOSED_AFTER = dt.time(12, 45)  # Tehran; the continuous session ends at 12:30
SOURCE = "api/ClosingPrice/GetClosingPriceInfo"


def _num(x: Any) -> float | None:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if v == v else None


def parse_info(info: dict[str, Any]) -> tuple[dt.date, dict[str, Any]] | None:
    """``(day, column values)`` of one reply, or None when it holds no traded day."""
    d = info.get("dEven")
    if not isinstance(d, int) or d < 19000101:
        return None
    day = dt.date(d // 10000, d // 100 % 100, d % 100)
    trades, volume = _num(info.get("zTotTran")), _num(info.get("qTotTran5J"))
    if not trades or not volume:
        return None
    cols = {
        "open": _num(info.get("priceFirst")),
        "high": _num(info.get("priceMax")),
        "low": _num(info.get("priceMin")),
        "close": _num(info.get("pClosing")),
        "last": _num(info.get("pDrCotVal")),
        "prev_close": _num(info.get("priceYesterday")),
        "volume": volume,
        "value": _num(info.get("qTotCap")),
        "trades": int(trades),
    }
    if any(not cols[k] or cols[k] <= 0 for k in ("open", "high", "low", "close", "last")):  # type: ignore[operator]
        return None
    return day, cols


def _fetch(ins_code: str) -> tuple[dt.date, dict[str, Any]] | None:
    try:
        r = httpx.get(
            f"{CDN}/api/ClosingPrice/GetClosingPriceInfo/{ins_code}",
            headers=HEADERS,
            timeout=TIMEOUT,
        )
        r.raise_for_status()
        info = (r.json() or {}).get("closingPriceInfo") or {}
    except (httpx.HTTPError, ValueError):
        log.info("closing info for %s unavailable", ins_code)
        return None
    return parse_info(info)


def fill_today(session: Session, *, now: dt.datetime | None = None) -> dict[str, int]:
    """Store today's bar for every instrument the bulk feed has not stored it for. Only the
    exchange day that equals today in Tehran, and only after the market has closed."""
    t = to_tehran(now or utcnow())
    today = t.date()
    out = {"asked": 0, "stored": 0, "skipped_open_market": 0}
    if t.time() < MARKET_CLOSED_AFTER:
        out["skipped_open_market"] = 1
        return out
    have = set(session.scalars(select(PriceDaily.instrument_id).where(PriceDaily.date == today)))
    # only symbols that still trade: those with a bar in the last 10 stored days
    latest = session.scalar(select(func.max(PriceDaily.date)).where(PriceDaily.date < today))
    if latest is None:
        return out
    recent = set(
        session.scalars(
            select(PriceDaily.instrument_id).where(
                PriceDaily.date >= latest - dt.timedelta(days=10), PriceDaily.date < today
            )
        )
    )
    todo = {
        i.id: i.ins_code
        for i in session.scalars(select(Instrument).where(Instrument.id.in_(recent - have)))
        if i.ins_code
    }
    out["asked"] = len(todo)
    if not todo:
        return out
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        replies = list(pool.map(_fetch, todo.values()))
    fetched_at = utcnow()
    rows = [
        {
            "instrument_id": iid,
            "date": day,
            **cols,
            "source_url": SOURCE,
            "fetched_at": fetched_at,
        }
        for iid, reply in zip(todo, replies, strict=True)
        if reply is not None and (day := reply[0]) == today and (cols := reply[1])
    ]
    out["stored"] = upsert(session, PriceDaily, rows)
    session.commit()
    return out
