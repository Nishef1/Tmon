"""Today's price range for one symbol straight from the exchange, never from a stored copy.

The daily table only has a day after the evening cycle, so while the market is open (and until
the cycle has run) the entry review and the portfolio read the day's first, highest, lowest and
last price here. Each call asks the exchange again; nothing is kept between calls.
"""

from __future__ import annotations

import datetime as dt
import logging
import math
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from tmon.ingest.tsetmc.endpoints import CDN
from tmon.storage.models import Instrument

log = logging.getLogger(__name__)

HEADERS = {"User-Agent": "Mozilla/5.0", "Accept": "application/json", "Cache-Control": "no-store"}
TIMEOUT = 8.0


@dataclass(frozen=True)
class Bar:
    """One trading day's price range. ``last`` is the last trade (آخرین), ``close`` the official
    final price (پایانی, a volume-weighted average)."""

    day: dt.date | None
    first: float | None
    high: float | None
    low: float | None
    last: float | None
    close: float | None
    yesterday: float | None
    limit_up: float | None = None
    limit_down: float | None = None
    volume: float | None = None

    @property
    def gap(self) -> float | None:
        return self.first / self.yesterday - 1 if self.first and self.yesterday else None

    def range_pos(self, price: float) -> float | None:
        """Where ``price`` sits in the day's range: 0 at the low, 1 at the high."""
        if not self.high or not self.low or self.high <= self.low:
            return None
        return min(1.0, max(0.0, (price - self.low) / (self.high - self.low)))


def _pos(x: Any) -> float | None:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if not math.isnan(v) and v > 0 else None


def parse_info(info: dict[str, Any], threshold: dict[str, Any] | None = None) -> Bar:
    """Build a :class:`Bar` from ``GetClosingPriceInfo`` (and the day's static price limits)."""
    d = info.get("dEven")
    day = None
    if isinstance(d, int) and d > 19000101:
        day = dt.date(d // 10000, d // 100 % 100, d % 100)
    t = threshold or {}
    ref = _pos(info.get("priceYesterday"))
    up, down = _pos(t.get("psGelStaMax")), _pos(t.get("psGelStaMin"))
    # Options, rights and uncapped symbols report a huge band (up to 1,000,000 and down to 1); that
    # is no daily limit, so a band wider than 15% around yesterday's close is not used as one.
    if ref and up and not ref * 0.85 <= up <= ref * 1.15:
        up = None
    if ref and down and not ref * 0.85 <= down <= ref * 1.15:
        down = None
    return Bar(
        day=day,
        first=_pos(info.get("priceFirst")),
        high=_pos(info.get("priceMax")),
        low=_pos(info.get("priceMin")),
        last=_pos(info.get("pDrCotVal")),
        close=_pos(info.get("pClosing")),
        yesterday=_pos(info.get("priceYesterday")),
        limit_up=up,
        limit_down=down,
        volume=_pos(info.get("qTotTran5J")),
    )


def fetch(ins_code: str) -> Bar | None:
    """Today's range for ``ins_code``; None when the exchange cannot be reached or has no trade."""
    try:
        with httpx.Client(headers=HEADERS, timeout=TIMEOUT) as c:
            r = c.get(f"{CDN}/api/ClosingPrice/GetClosingPriceInfo/{ins_code}")
            r.raise_for_status()
            info = (r.json() or {}).get("closingPriceInfo") or {}
            if not info or not _pos(info.get("priceYesterday")):
                return None
            threshold: dict[str, Any] | None = None
            deven = info.get("dEven")
            if deven:
                try:
                    t = c.get(f"{CDN}/api/MarketData/GetStaticThreshold/{ins_code}/{deven}")
                    rows = (t.json() or {}).get("staticThreshold") or []
                    threshold = rows[-1] if rows else None
                except (httpx.HTTPError, ValueError):
                    threshold = None
    except (httpx.HTTPError, ValueError):
        log.info("live price for %s unavailable", ins_code, exc_info=True)
        return None
    return parse_info(info, threshold)


def fetch_many(codes: dict[int, str], *, workers: int = 8) -> dict[int, Bar]:
    """Today's bar for several instruments at once, ``{instrument id: bar}``; symbols the
    exchange cannot answer for are left out."""
    if not codes:
        return {}
    with ThreadPoolExecutor(max_workers=min(workers, len(codes))) as pool:
        bars = list(pool.map(fetch, codes.values()))
    return {iid: b for iid, b in zip(codes, bars, strict=True) if b is not None}


def live_marks(
    session: Session, stored: dict[int, dt.date | None]
) -> dict[int, tuple[float, float | None, dt.date]]:
    """``(last trade, official close, day)`` for the instruments whose exchange day is newer than
    the stored one (the market is open, or the evening cycle has not stored the day yet).

    ``stored`` maps instrument id to the date of its newest stored price. An instrument whose
    stored day is already today's is left out: the stored row is then the final word."""
    if not stored:
        return {}
    codes = {
        i.id: i.ins_code
        for i in session.scalars(select(Instrument).where(Instrument.id.in_(list(stored))))
        if i.ins_code
    }
    out: dict[int, tuple[float, float | None, dt.date]] = {}
    for iid, bar in fetch_many(codes).items():
        have = stored.get(iid)
        price = bar.last or bar.close
        if bar.day is None or not price or (have is not None and bar.day <= have):
            continue
        out[iid] = (price, bar.close, bar.day)
    return out
