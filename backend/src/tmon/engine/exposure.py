"""Engine v2 exposure layer (ADR 0003 section 5): how much of the capital is in shares today.

    exposure = clip(0.5 * (trend + abs_mom) * vol_cap * stress, 0, max_exposure)

* ``trend``   1 when the equal-weight index closes above its simple moving average, else 0;
* ``abs_mom`` 1 when the index return over ``abs_mom_days`` beats what the treasury bill earned in
  the same window, else 0;
* ``vol_cap`` target volatility / realised 20-day volatility of the index, at most 1; exactly 1 when
  no target is configured (the owner has not picked one, OPEN_QUESTIONS 85);
* ``stress``  1 minus the mean share of the universe stuck in a sell queue.

The rest of the capital sits in the fixed-income fund; there is no leverage. Every input at day
``t`` uses data up to and including the close of ``t``; the exposure is applied to the return of the
*next* day. A component that cannot be computed yet (history too short, no treasury-bill yield)
leaves ``exposure`` null for that day: nothing is filled in with a guess.
"""

from __future__ import annotations

import math

import polars as pl

from tmon.core.engine_config import ExposureCfg


def trading_days_per_year(dates: pl.Series) -> float:
    span = dates.sort().to_list()
    years = (span[-1] - span[0]).days / 365.25 if len(span) > 1 else 0.0
    return len(span) / years if years > 0 else float("nan")


def compute_exposure(
    index: pl.DataFrame,
    rf_daily: pl.DataFrame,
    sell_share: pl.DataFrame,
    cfg: ExposureCfg,
    *,
    target_vol_annual: float | str | None = "cfg",
) -> pl.DataFrame:
    """``index``: ``date, close`` of the equal-weight index. ``rf_daily``: ``date, ret`` of holding
    the treasury bill. ``sell_share``: ``date, share`` of universe symbols in a sell queue.

    ``target_vol_annual`` overrides the configured target (used by the sensitivity table); pass
    ``None`` to switch the vol cap off. Returns ``date, trend, abs_mom, vol_cap, stress,
    exposure``, sorted by date.
    """
    target = cfg.target_vol_annual if target_vol_annual == "cfg" else target_vol_annual
    per_year = trading_days_per_year(index["date"])
    d = (
        index.sort("date")
        .with_columns((pl.col("close") / pl.col("close").shift(1) - 1.0).alias("ret"))
        .join(rf_daily.rename({"ret": "rf_ret"}), on="date", how="left")
        .join(sell_share.rename({"share": "sell_share"}), on="date", how="left")
    )
    w = cfg.abs_mom_days
    d = d.with_columns(
        (pl.col("close") > pl.col("close").rolling_mean(cfg.trend_window_days)).alias("_t"),
        (pl.col("close") / pl.col("close").shift(w) - 1.0).alias("_idx_ret"),
        # compounded treasury-bill return over the same window; null unless every day has a yield
        (pl.col("rf_ret").log1p().rolling_sum(w).exp() - 1.0).alias("_rf_ret"),
        (pl.col("ret").rolling_std(cfg.vol_window_days) * math.sqrt(per_year)).alias("_vol"),
        pl.col("sell_share").rolling_mean(cfg.stress_window_days).alias("_stress"),
    )
    vol_cap = (
        pl.lit(1.0)
        if target is None
        else pl.when(pl.col("_vol") > 0)
        .then((target / pl.col("_vol")).clip(upper_bound=1.0))
        .otherwise(None)
    )
    d = d.with_columns(
        pl.col("_t").cast(pl.Float64).alias("trend"),
        pl.when(pl.col("_rf_ret").is_null() | pl.col("_idx_ret").is_null())
        .then(None)
        .otherwise((pl.col("_idx_ret") > pl.col("_rf_ret")).cast(pl.Float64))
        .alias("abs_mom"),
        vol_cap.alias("vol_cap"),
        (1.0 - pl.col("_stress")).alias("stress"),
    )
    return d.select(
        "date",
        "trend",
        "abs_mom",
        "vol_cap",
        "stress",
        (0.5 * (pl.col("trend") + pl.col("abs_mom")) * pl.col("vol_cap") * pl.col("stress"))
        .clip(0.0, cfg.max_exposure)
        .alias("exposure"),
    )
