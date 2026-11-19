"""What the leveraged funds did against the market (docs/reports/leveraged-funds-2026-11.md).

Pure functions over aligned daily closes. A fund's row answers four plain questions: how much it
moves per unit of market move (beta), how often a month ended at +10% or better and how often it
ended below zero, how far it fell from a peak, and what the last month looked like. Descriptive;
nothing here is a forecast or a signal.
"""

from __future__ import annotations

from typing import Any

import numpy as np

MONTH = 21  # sessions in a month
TRADING_DAYS = 250
MIN_DAYS = 250  # a fund with fewer common days is left out
TARGET = 0.10  # the owner's "10% a month"


def _forward(x: np.ndarray, h: int = MONTH) -> np.ndarray:
    """Return over the next ``h`` sessions where both ends exist."""
    out: np.ndarray = x[h:] / x[:-h] - 1.0
    kept: np.ndarray = out[np.isfinite(out)]
    return kept


def _max_drawdown(x: np.ndarray) -> float:
    ok = x[np.isfinite(x)]
    if ok.size == 0:
        return 0.0
    return float((ok / np.maximum.accumulate(ok) - 1.0).min())


def fund_row(closes: np.ndarray, index: np.ndarray) -> dict[str, Any] | None:
    """Stats of one fund. ``closes`` and ``index`` are aligned on the same days (NaN where the
    fund had no price), oldest first. None when the common history is too short."""
    r = closes[1:] / closes[:-1] - 1.0
    m = index[1:] / index[:-1] - 1.0
    ok = np.isfinite(r) & np.isfinite(m)
    if ok.sum() < MIN_DAYS or np.nanvar(m[ok]) == 0:
        return None
    rf, rm = r[ok], m[ok]
    beta = float(np.cov(rf, rm)[0, 1] / rm.var(ddof=1))
    alpha = float(rf.mean() - beta * rm.mean())
    resid = rf - alpha - beta * rm
    f = _forward(closes)
    live = closes[np.isfinite(closes)]
    last = np.isfinite(closes[-1 - MONTH]) if len(closes) > MONTH else False
    return {
        "days": int(ok.sum()),
        "beta": beta,
        "corr": float(np.corrcoef(rf, rm)[0, 1]),
        "vol_year": float(rf.std(ddof=1) * np.sqrt(TRADING_DAYS)),
        "alpha_year": alpha * TRADING_DAYS,
        "alpha_t": float(alpha / (resid.std(ddof=1) / np.sqrt(len(rf)))),
        "months": int(f.size),
        "month_median": float(np.median(f)),
        "month_mean": float(f.mean()),
        "share_ge_target": float((f >= TARGET).mean()),
        "share_below_zero": float((f < 0).mean()),
        "share_below_minus_target": float((f < -TARGET).mean()),
        "worst_month": float(f.min()),
        "max_drawdown": _max_drawdown(closes),
        "compound_month": float((live[-1] / live[0]) ** (MONTH / max(len(live) - 1, 1)) - 1.0),
        "last_month": float(closes[-1] / closes[-1 - MONTH] - 1.0) if last else None,
        "last_month_index": float(index[-1] / index[-1 - MONTH] - 1.0),
    }


def basket_row(closes: np.ndarray) -> dict[str, Any] | None:
    """Same-weight basket of several funds (rows = days, columns = funds), rebalanced daily.
    Daily moves beyond ±20% are clipped: they are a unit change or a bad print, not a return."""
    r = closes[1:] / closes[:-1] - 1.0
    r = np.where(np.isfinite(r), np.clip(r, -0.2, 0.2), np.nan)
    n = np.isfinite(r).sum(axis=1)
    day = np.where(n > 0, np.nansum(r, axis=1) / np.maximum(n, 1), 0.0)
    eq = np.r_[1.0, np.cumprod(1.0 + day)]
    if eq.size <= MONTH + MIN_DAYS // 5:
        return None
    f = _forward(eq)
    return {
        "funds": int(closes.shape[1]),
        "month_median": float(np.median(f)),
        "month_mean": float(f.mean()),
        "share_ge_target": float((f >= TARGET).mean()),
        "share_below_zero": float((f < 0).mean()),
        "worst_month": float(f.min()),
        "max_drawdown": _max_drawdown(eq),
        "compound_month": float(eq[-1] ** (MONTH / (eq.size - 1)) - 1.0),
    }
