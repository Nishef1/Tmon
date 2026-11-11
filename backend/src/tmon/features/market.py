"""Cross-sectional market and sector features (docs/04, "بازار").

Everything is aggregated per ``date`` from the rows of that same date (plus trailing windows
over the aggregated series), so values are point-in-time. The official total index is not
ingested in M1; ``mkt_ret_ew`` (equal weight) and ``mkt_ret_vw`` (weighted by traded value) are
used as proxies and stated as such in docs/OPEN_QUESTIONS.md.
"""

from __future__ import annotations

import polars as pl

G = "instrument_id"
Z_WINDOW = 60
Z_MIN_SAMPLES = 30


def add_market_features(df: pl.DataFrame, sectors: pl.DataFrame | None = None) -> pl.DataFrame:
    """``df``: per-instrument features incl. ``ret_1``, ``value``, ``buy_value_i``,
    ``ind_net_flow``. ``sectors``: optional ``instrument_id, sector_code``."""
    d = df
    if sectors is not None:
        d = d.join(sectors.select(G, "sector_code"), on=G, how="left")

    has_ret = pl.col("ret_1").is_not_null()
    by_date = (
        d.group_by("date")
        .agg(
            pl.col("ret_1").mean().alias("mkt_ret_ew"),
            (
                (pl.col("ret_1") * pl.col("value")).filter(has_ret).sum()
                / pl.col("value").filter(has_ret).sum()
            ).alias("mkt_ret_vw"),
            (pl.col("ret_1").filter(has_ret) > 0).cast(pl.Float64).mean().alias("breadth"),
            pl.col("value").sum().alias("mkt_value"),
            pl.col("buy_value_i").sum().alias("mkt_retail_buy_value"),
            pl.col("ind_net_flow").sum().alias("mkt_ind_net_flow"),
        )
        .sort("date")
    )
    by_date = by_date.with_columns(
        (pl.col("mkt_ind_net_flow") / pl.col("mkt_value")).alias("mkt_ind_net_flow_ratio"),
        pl.col("mkt_ret_ew").rolling_sum(5).alias("mkt_ret_ew_5d"),
        pl.col("mkt_ret_ew").rolling_sum(20).alias("mkt_ret_ew_20d"),
    )
    by_date = by_date.with_columns(
        (
            (
                pl.col("mkt_ind_net_flow")
                - pl.col("mkt_ind_net_flow").rolling_mean(Z_WINDOW, min_samples=Z_MIN_SAMPLES)
            )
            / pl.col("mkt_ind_net_flow").rolling_std(Z_WINDOW, min_samples=Z_MIN_SAMPLES)
        ).alias("mkt_ind_net_flow_z"),
        pl.col("mkt_ind_net_flow_ratio").rolling_sum(5).alias("mkt_ind_net_flow_ratio_5d"),
    )
    d = d.join(by_date, on="date", how="left")

    if sectors is not None:
        sec = d.group_by(["date", "sector_code"]).agg(pl.col("ret_1").mean().alias("sector_ret_ew"))
        d = d.join(sec, on=["date", "sector_code"], how="left")
        d = d.with_columns((pl.col("ret_1") - pl.col("sector_ret_ew")).alias("rel_ret_sector"))
    else:
        d = d.with_columns(
            pl.lit(None, dtype=pl.Float64).alias("sector_ret_ew"),
            pl.lit(None, dtype=pl.Float64).alias("rel_ret_sector"),
        )
    return d.with_columns((pl.col("ret_1") - pl.col("mkt_ret_ew")).alias("rel_ret_market"))
