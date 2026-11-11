"""Portfolio constraints applied to a day's accepted signals (docs/10 section 6).

Greedy by expected value, best first:

1. **liquidity**: a position may not exceed ``liquidity_cap_of_median_value`` of the stock's
   20-day median traded value (``median_value_20``), measured against the capital;
2. **correlation**: a candidate whose 60-day return correlation with an already selected
   position exceeds ``correlation_max`` is dropped (the higher EV was kept first);
3. **sector cap**: the summed weight of one sector is limited to ``sector_cap_pct``; the last
   position is trimmed to fit, and dropped when nothing is left.

The loop runs over a day's candidates (tens of rows at most), never over market data.
"""

from __future__ import annotations

import numpy as np
import polars as pl

from tmon.core.engine_config import EngineConfig, get_engine_config

MIN_WEIGHT = 1e-4  # below 0.01% of capital a position is not worth opening


def correlation_matrix(returns: pl.DataFrame, ids: list[int], window: int) -> np.ndarray:
    """Pairwise Pearson correlation of daily returns over the last ``window`` dates, in the
    order of ``ids``. Missing history gives 0 (no evidence of correlation)."""
    n = len(ids)
    if n == 0:
        return np.zeros((0, 0))
    last = returns["date"].unique().sort().tail(window)
    wide = (
        returns.filter(pl.col("date").is_in(last.to_list()) & pl.col("instrument_id").is_in(ids))
        .pivot(on="instrument_id", index="date", values="ret_1")
        .sort("date")
    )
    cols = [str(i) for i in ids]
    mat = np.full((wide.height, n), np.nan)
    for j, name in enumerate(cols):
        if name in wide.columns:
            mat[:, j] = wide[name].cast(pl.Float64).to_numpy()
    masked = np.ma.masked_invalid(mat)
    corr = np.ma.corrcoef(masked, rowvar=False)
    out = np.ma.filled(np.ma.asarray(corr), 0.0)
    return np.asarray(np.atleast_2d(out), dtype=float)


def select_portfolio(
    cands: pl.DataFrame,
    returns: pl.DataFrame,
    *,
    capital: float,
    cfg: EngineConfig | None = None,
    max_positions: int | None = None,
) -> tuple[pl.DataFrame, pl.DataFrame]:
    """Apply the constraints. ``cands`` needs ``instrument_id, ev, weight, sector_code,
    median_value_20``; ``returns`` needs ``instrument_id, date, ret_1`` up to the decision date.

    Returns ``(selected, dropped)``: ``selected`` gains ``position_pct`` (fraction of capital) and
    ``rank``; ``dropped`` gains ``reason`` (``liquidity``, ``correlation``, ``sector_cap``,
    ``max_positions``).
    """
    c = cfg or get_engine_config()
    sz = c.sizing
    limit = max_positions if max_positions is not None else c.backtest.max_new_positions_per_day
    ordered = cands.sort("ev", descending=True)
    ids = ordered["instrument_id"].to_list()
    corr = correlation_matrix(returns, ids, sz.correlation_window_days)

    liq = (
        (sz.liquidity_cap_of_median_value * ordered["median_value_20"] / capital)
        .fill_null(0.0)
        .to_numpy()
    )
    weight = np.minimum(ordered["weight"].fill_null(0.0).to_numpy(), liq)
    sectors = ordered["sector_code"].fill_null("?").to_list()

    keep: list[int] = []
    final_w: dict[int, float] = {}
    reason: dict[int, str] = {}
    used: dict[str, float] = {}
    for i in range(len(ids)):
        if weight[i] < MIN_WEIGHT:
            reason[i] = "liquidity"
        elif len(keep) >= limit:
            reason[i] = "max_positions"
        elif any(corr[i, j] > sz.correlation_max for j in keep):
            reason[i] = "correlation"
        else:
            room = sz.sector_cap_pct - used.get(sectors[i], 0.0)
            w = min(float(weight[i]), room)
            if w < MIN_WEIGHT:
                reason[i] = "sector_cap"
                continue
            keep.append(i)
            final_w[i] = w
            used[sectors[i]] = used.get(sectors[i], 0.0) + w

    sel = ordered[keep].with_columns(
        pl.Series("position_pct", [final_w[i] for i in keep], dtype=pl.Float64),
        pl.Series("rank", list(range(1, len(keep) + 1)), dtype=pl.Int64),
    )
    drop_idx = sorted(reason)
    dropped = ordered[drop_idx].with_columns(
        pl.Series("reason", [reason[i] for i in drop_idx], dtype=pl.Utf8)
    )
    return sel, dropped
