"""Is the market still in the regime the studies saw? Read from the official index, nothing guessed.

The studies (living ranking, deep study) only know the years in the data. Their reports say so:
every verdict is for that regime. This module turns that caveat into a measurement that is redone
with every cycle, so a change of regime is noticed by the system and not by a person:

* ``stress``: the index fell by at least ``stress_drawdown`` from its peak, or lost
  ``|stress_return|`` over the last ``stress_days`` trading days;
* ``bullish_only``: none of the last ``years`` non-overlapping ``year_days`` windows ended below
  ``bear_return``. Nominal prices: the rials inflate, so this says "no nominal bear market".

Pure functions of the index series (no I/O); ``tmon.tools.adapt_cycle`` feeds them.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from typing import Any

import numpy as np

YEAR_DAYS = 250
YEARS = 4
BEAR_RETURN = -0.10


def summarize(
    dates: Sequence[date],
    close: Sequence[float],
    *,
    stress_days: int,
    stress_drawdown: float,
) -> dict[str, Any] | None:
    """The regime reading at the last date of the index, or None when the series is too short."""
    v = np.asarray(close, dtype=float)
    ok = np.isfinite(v) & (v > 0)
    v = v[ok]
    d = [x for x, keep in zip(dates, ok, strict=True) if keep]
    if len(v) <= max(stress_days, YEAR_DAYS):
        return None
    peak = float(v.max())
    drawdown = 1.0 - float(v[-1]) / peak
    ret = float(v[-1] / v[-1 - stress_days] - 1.0)
    windows = [
        float(v[i] / v[i - YEAR_DAYS] - 1.0) for i in range(len(v) - 1, YEAR_DAYS - 1, -YEAR_DAYS)
    ][:YEARS]
    bear = [r for r in windows if r <= BEAR_RETURN]
    stress = drawdown >= stress_drawdown or ret <= -abs(BEAR_RETURN)
    return {
        "as_of": str(d[-1]),
        "drawdown": round(drawdown, 4),
        "return_recent": round(ret, 4),
        "recent_days": stress_days,
        "windows": [round(r, 4) for r in windows],
        "bear_windows": len(bear),
        "bullish_only": not bear,
        "stress": bool(stress),
        "stress_drawdown": stress_drawdown,
    }
