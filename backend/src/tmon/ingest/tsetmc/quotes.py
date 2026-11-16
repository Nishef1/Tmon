"""One reading of a ``GetMarketWatch`` row, whichever field names the exchange uses.

The feed carries the same numbers under two sets of names. The older set (``pDrCotVal``,
``pClosing``, ``priceYesterday``, ``qTotTran5J``, ``qTotCap``) is still present in every row but
filled with zeros; the live values sit under the short names (``pdv``, ``pcl``, ``py``, ``qtj``,
``qtc``, ``pmx``, ``pmn``, ``pf``). Reading only the older names made every price 0 and every
volume 0, so nothing was stored and no alert could fire. A value counts only when it is above
zero, and the first name that has one wins, so either layout works.

Naming (TSETMC): ``last`` is the last trade price (آخرین), ``close`` the official final price
(پایانی, a volume-weighted average near the end), ``first`` the first trade of the day.
"""

from __future__ import annotations

import math
from typing import Any

# field -> names to try, live layout first
_NAMES: dict[str, tuple[str, ...]] = {
    "last": ("pdv", "pDrCotVal"),
    "close": ("pcl", "pClosing"),
    "yesterday": ("py", "priceYesterday"),
    "first": ("pf", "priceFirst"),
    "high": ("pmx", "priceMax"),
    "low": ("pmn", "priceMin"),
    "volume": ("qtj", "qTotTran5J"),
    "value": ("qtc", "qTotCap"),
    "trades": ("ztt", "zTotTran"),
    "limit_up": ("pMax",),
    "limit_down": ("pMin",),
}


def _num(x: Any) -> float | None:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if not math.isnan(v) and v > 0 else None


def read(row: dict[str, Any]) -> dict[str, Any]:
    """The row's numbers as ``{last, close, yesterday, first, high, low, volume, value, trades,
    limit_up, limit_down, symbol}``; a missing or zero number is None."""
    out: dict[str, Any] = {}
    for key, names in _NAMES.items():
        out[key] = next((v for n in names if (v := _num(row.get(n))) is not None), None)
    out["symbol"] = str(row.get("lva") or row.get("lVal18AFC") or "").strip()
    return out
