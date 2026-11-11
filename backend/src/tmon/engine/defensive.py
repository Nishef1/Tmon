"""Defensive mode (docs/10 section 8): raise the probability bar when the market is weak.

A day is defensive when market breadth is below ``breadth_floor`` *or* real investors have been
net sellers of the whole market for ``market_net_flow_negative_days`` trading days in a row.
Everything uses data up to and including the day itself, so the flag is point-in-time.
"""

from __future__ import annotations

import polars as pl

from tmon.core.engine_config import EngineConfig, get_engine_config


def defensive_flags(ds: pl.DataFrame, cfg: EngineConfig | None = None) -> pl.DataFrame:
    """``date, defensive`` for every trading date of ``ds`` (needs ``breadth`` and
    ``mkt_ind_net_flow``)."""
    c = (cfg or get_engine_config()).defensive_mode
    daily = (
        ds.group_by("date")
        .agg(
            pl.col("breadth").first(),
            pl.col("mkt_ind_net_flow").first(),
        )
        .sort("date")
    )
    if not c.enabled:
        return daily.select("date", pl.lit(False).alias("defensive"))
    n = c.market_net_flow_negative_days
    negative = (pl.col("mkt_ind_net_flow") < 0).fill_null(False).cast(pl.Int32)
    return daily.select(
        "date",
        (
            (pl.col("breadth") < c.breadth_floor).fill_null(False)
            | (negative.rolling_sum(n) == n).fill_null(False)
        ).alias("defensive"),
    )


def add_defensive_flag(ds: pl.DataFrame, cfg: EngineConfig | None = None) -> pl.DataFrame:
    return ds.join(defensive_flags(ds, cfg), on="date", how="left").with_columns(
        pl.col("defensive").fill_null(False)
    )
