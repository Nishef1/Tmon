"""Today's price range for one symbol straight from the exchange, never from a stored copy.

The daily table only has a day after the evening cycle, so while the market is open (and until
the cycle has run) the entry review and the portfolio read the day's first, highest, lowest and
last price here. Each call asks the exchange again; nothing is kept between calls.
"""

from __future__ import annotations

import datetime as dt
import logging
from dataclasses import dataclass
from typing import Any

import httpx

from tmon.ingest.tsetmc.endpoints import CDN

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
    return v if v == v and v > 0 else None


def parse_info(info: dict[str, Any], threshold: dict[str, Any] | None = None) -> Bar:
    """Build a :class:`Bar` from ``GetClosingPriceInfo`` (and the day's static price limits)."""
    d = info.get("dEven")
    day = None
    if isinstance(d, int) and d > 19000101:
        day = dt.date(d // 10000, d // 100 % 100, d % 100)
    t = threshold or {}
    return Bar(
        day=day,
        first=_pos(info.get("priceFirst")),
        high=_pos(info.get("priceMax")),
        low=_pos(info.get("priceMin")),
        last=_pos(info.get("pDrCotVal")),
        close=_pos(info.get("pClosing")),
        yesterday=_pos(info.get("priceYesterday")),
        limit_up=_pos(t.get("psGelStaMax")),
        limit_down=_pos(t.get("psGelStaMin")),
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
