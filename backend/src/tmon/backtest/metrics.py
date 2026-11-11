"""Backtest metrics (docs/10 section 9). Every function works on Polars/NumPy arrays."""

from __future__ import annotations

import math
from datetime import date
from typing import Any

import numpy as np
import polars as pl

# Below this many calendar years annualised figures are noise and are reported as null.
MIN_YEARS_FOR_ANNUALISING = 0.5


def _nan_to_none(v: float) -> float | None:
    return None if v is None or not math.isfinite(v) else float(v)


def max_drawdown(equity: np.ndarray) -> float:
    if equity.size == 0:
        return 0.0
    peak = np.maximum.accumulate(np.r_[1.0, equity])[1:]
    return float(np.min(equity / peak - 1.0))


def portfolio_metrics(
    daily: pl.DataFrame, *, risk_free_annual: float | None = None
) -> dict[str, Any]:
    """Return/risk statistics of a daily return series (``date``, ``ret``)."""
    n = daily.height
    if n < 2:
        return {"days": n}
    r = daily["ret"].to_numpy().astype(float)
    first, last = daily["date"].min(), daily["date"].max()
    assert isinstance(first, date) and isinstance(last, date)
    years = (last - first).days / 365.25
    per_year = n / years if years > 0 else float("nan")
    equity = np.cumprod(1.0 + r)
    total = float(equity[-1] - 1.0)
    rf_daily = 0.0 if risk_free_annual is None else (1 + risk_free_annual) ** (1 / per_year) - 1
    ex = r - rf_daily
    sd = float(np.std(r, ddof=1))
    dd = float(np.sqrt(np.mean(np.minimum(ex, 0.0) ** 2)))
    annualise = years >= MIN_YEARS_FOR_ANNUALISING and total > -1
    return {
        "days": n,
        "start": first.isoformat(),
        "end": last.isoformat(),
        "years": _nan_to_none(years),
        "total_return": total,
        "annualized_return": _nan_to_none((1 + total) ** (1 / years) - 1) if annualise else None,
        "annualized_volatility": _nan_to_none(sd * math.sqrt(per_year)) if annualise else None,
        "sharpe": _nan_to_none(float(np.mean(ex)) / sd * math.sqrt(per_year))
        if annualise and sd > 0
        else None,
        "sortino": _nan_to_none(float(np.mean(ex)) / dd * math.sqrt(per_year))
        if annualise and dd > 0
        else None,
        "max_drawdown": max_drawdown(equity),
        "risk_free_annual": risk_free_annual,
        "sharpe_uses_zero_risk_free": risk_free_annual is None,
    }


def trade_metrics(trades: pl.DataFrame) -> dict[str, Any]:
    """Per-trade statistics on ``net_return`` (after costs) and ``realized_return`` (gross)."""
    n = trades.height
    if n == 0:
        return {"n_trades": 0}
    net = trades["net_return"].to_numpy().astype(float)
    gross = trades["realized_return"].to_numpy().astype(float)
    wins, losses = net[net > 0], net[net <= 0]
    avg_win = float(wins.mean()) if wins.size else None
    avg_loss = float(losses.mean()) if losses.size else None
    return {
        "n_trades": n,
        "win_rate": float((net > 0).mean()),
        "barrier_hit_rate": _nan_to_none(
            float(np.nanmean(trades["y"].cast(pl.Float64).to_numpy()))
        ),
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "payoff_ratio": abs(avg_win / avg_loss) if avg_win and avg_loss else None,
        "expectancy_net": float(net.mean()),
        "expectancy_gross": float(gross.mean()),
        "avg_round_trip_cost": float(trades["round_trip_cost"].to_numpy().mean()),
        "median_holding_days": float(
            np.median(trades["exit_idx"].to_numpy() - trades["entry_idx"].to_numpy())
        ),
        "share_exit_delayed": float(trades["exit_delayed"].to_numpy().mean()),
    }


def calibration_table(p: np.ndarray, y: np.ndarray, n_buckets: int = 10) -> list[dict[str, Any]]:
    """Reliability table over equal-width probability buckets of [0, 1]."""
    edges = np.linspace(0.0, 1.0, n_buckets + 1)
    which = np.clip(np.digitize(p, edges[1:-1]), 0, n_buckets - 1)
    out = []
    for b in range(n_buckets):
        m = which == b
        out.append(
            {
                "bucket": f"{edges[b]:.1f}-{edges[b + 1]:.1f}",
                "n": int(m.sum()),
                "mean_p": float(p[m].mean()) if m.any() else None,
                "hit_rate": float(y[m].mean()) if m.any() else None,
            }
        )
    return out


def brier_score(p: np.ndarray, y: np.ndarray) -> float | None:
    return _nan_to_none(float(np.mean((p - y) ** 2))) if p.size else None


def probabilistic_summary(p: np.ndarray, y: np.ndarray, n_buckets: int = 10) -> dict[str, Any]:
    """Quality of probability forecasts over *all* out-of-sample rows (not only the traded ones).

    ``brier_skill`` compares with always forecasting the sample's base rate (positive = better).
    """
    from sklearn.metrics import roc_auc_score

    n = int(p.size)
    if n == 0 or len(np.unique(y)) < 2:
        return {"n": n}
    brier = float(np.mean((p - y) ** 2))
    base = float(np.mean((y.mean() - y) ** 2))
    return {
        "n": n,
        "base_rate": float(y.mean()),
        "auc": float(roc_auc_score(y, p)),
        "brier": brier,
        "brier_base_rate": base,
        "brier_skill": _nan_to_none(1.0 - brier / base) if base > 0 else None,
        "calibration": calibration_table(p, y, n_buckets),
    }


def summarise(
    trades: pl.DataFrame,
    daily: pl.DataFrame,
    *,
    risk_free_annual: float | None,
    by_regime: bool = True,
) -> dict[str, Any]:
    """Overall metrics plus the same split by regime (normal / halt / post_reopen)."""
    out: dict[str, Any] = {
        "trades": trade_metrics(trades),
        "portfolio": portfolio_metrics(daily, risk_free_annual=risk_free_annual),
    }
    if "p_win" in trades.columns and trades.height:
        p = trades["p_win"].to_numpy().astype(float)
        y = trades["y"].to_numpy().astype(float)
        out["brier"] = brier_score(p, y)
    if by_regime:
        regimes: dict[str, Any] = {}
        for name in sorted(set(daily["regime"].drop_nulls().to_list())):
            t = trades.filter(pl.col("regime") == name)
            d = daily.filter(pl.col("regime") == name)
            regimes[name] = {
                "trades": trade_metrics(t),
                "portfolio": portfolio_metrics(d, risk_free_annual=risk_free_annual),
            }
        out["by_regime"] = regimes
    return out
