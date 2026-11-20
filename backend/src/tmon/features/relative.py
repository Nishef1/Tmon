"""Training columns that read each derived column against a trend, a peer group and each other.

A raw level such as «net real buy is 12% of value» means little alone. The same number reads
differently when it is high against the stock's own last three months, when it is high against every
other stock today, when it goes against the price trend, or when the market itself is falling. This
module turns the columns of ``features/extra.py`` into those readings, for every (instrument, date),
from rows known at that day's close only (tests/test_relative_columns.py cuts the data to prove it).

Four groups:

* ``own``: the column now against its own history (short average minus 60-day average, in units of
  the 60-day spread), and the trend state of the stock and of the market.
* ``cross``: the column's rank among all stocks that day, and its gap to the median of its industry.
* ``pair``: columns against each other: flow with or against the price trend, volume on up days
  against down days, flow over 5 days against 20 days, relative strength against the market.
* ``fund``: P/E, P/S and P/B against the stock's own year and against its industry (null without
  statements).

Nothing here changes the production feature set (``features/builder.py``).
"""

from __future__ import annotations

import polars as pl

from tmon.features.adjustment import apply_adjustments
from tmon.features.builder import KEYS

G = "instrument_id"

# columns that move day to day and mean something against a trend or a peer group
SERIES = (
    "vol_vs_30", "val_vs_30", "val_to_mcap", "to_high_3m",
    "real_net_pct", "legal_net_pct", "real_net_vs_avg", "legal_buy_power", "idx_impact",
)  # fmt: skip
FUND_MULTIPLES = ("pe_ttm", "ps_ttm", "pb")

OWN_COLUMNS: tuple[str, ...] = (
    *(f"{c}_own" for c in SERIES),
    "stock_trend", "stock_slope", "market_trend", "market_slope",
)  # fmt: skip
CROSS_COLUMNS: tuple[str, ...] = (
    *(f"{c}_rank" for c in SERIES),
    *(f"{c}_ind" for c in SERIES),
)
PAIR_COLUMNS: tuple[str, ...] = (
    "real_net_with_trend", "legal_net_with_trend", "vol_with_trend",
    "real_net_5_vs_20", "legal_net_5_vs_20", "val_5_vs_20",
    "rel_strength_3m", "rel_strength_1m", "flow_vs_price_z", "up_down_value",
)  # fmt: skip
REL_FUND_COLUMNS: tuple[str, ...] = (
    *(f"{c}_own" for c in FUND_MULTIPLES),
    *(f"{c}_ind" for c in FUND_MULTIPLES),
)
REL_GROUPS: dict[str, tuple[str, ...]] = {
    "own": OWN_COLUMNS,
    "cross": CROSS_COLUMNS,
    "pair": PAIR_COLUMNS,
    "relfund": REL_FUND_COLUMNS,
}
REL_COLUMNS: tuple[str, ...] = tuple(c for g in REL_GROUPS.values() for c in g)


def _own(x: pl.Expr, short: int = 5, long: int = 60) -> pl.Expr:
    """Short average minus long average, in units of the long spread (0 = in line with its past)."""
    mean_s = x.rolling_mean(short, min_samples=3).over(G)
    mean_l = x.rolling_mean(long, min_samples=long // 2).over(G)
    sd = x.rolling_std(long, min_samples=long // 2).over(G)
    return pl.when(sd > 0).then((mean_s - mean_l) / sd).otherwise(None)


def build_relative(
    prices: pl.DataFrame,
    client_types: pl.DataFrame | None,
    extra: pl.DataFrame,
    *,
    sectors: pl.DataFrame | None = None,
    index_close: pl.DataFrame | None = None,
) -> pl.DataFrame:
    """``KEYS`` plus ``REL_COLUMNS`` for every row of ``extra`` (the output of ``build_extra``)."""
    d = apply_adjustments(prices.sort(KEYS)).select(
        *KEYS, "adj_close", "adj_volume", "value", "close"
    )
    d = d.join(extra, on=list(KEYS), how="left")
    c = pl.col("adj_close")
    d = d.with_columns((c / c.shift(1).over(G) - 1.0).alias("_r"))

    if index_close is not None and not index_close.is_empty():
        ix = index_close.sort("date").select("date", pl.col("close").alias("_ix").cast(pl.Float64))
        ix = ix.with_columns(
            (pl.col("_ix") / pl.col("_ix").rolling_mean(100, min_samples=60) - 1.0).alias(
                "market_trend"
            ),
            (pl.col("_ix").rolling_mean(20, min_samples=15) / pl.col("_ix").shift(20)
             .rolling_mean(20, min_samples=15) - 1.0).alias("market_slope"),
            (pl.col("_ix") / pl.col("_ix").shift(60) - 1.0).alias("_ix_3m"),
            (pl.col("_ix") / pl.col("_ix").shift(20) - 1.0).alias("_ix_1m"),
        )  # fmt: skip
        d = d.join(ix.drop("_ix"), on="date", how="left")
    else:
        d = d.with_columns(
            [pl.lit(None, dtype=pl.Float64).alias(k)
             for k in ("market_trend", "market_slope", "_ix_3m", "_ix_1m")]
        )  # fmt: skip

    ma20 = c.rolling_mean(20, min_samples=15).over(G)
    d = d.with_columns(
        (c / c.rolling_mean(60, min_samples=40).over(G) - 1.0).alias("stock_trend"),
        (ma20 / ma20.shift(20).over(G) - 1.0).alias("stock_slope"),
        (c / c.shift(60).over(G) - 1.0).alias("_ret_3m"),
        (c / c.shift(20).over(G) - 1.0).alias("_ret_1m"),
    )
    d = d.with_columns(
        (pl.col("_ret_3m") - pl.col("_ix_3m")).alias("rel_strength_3m"),
        (pl.col("_ret_1m") - pl.col("_ix_1m")).alias("rel_strength_1m"),
    )

    if client_types is not None and not client_types.is_empty():
        ct = client_types.select(
            *KEYS, "buy_value_i", "sell_value_i", "buy_value_n", "sell_value_n"
        )
        d = d.join(ct, on=list(KEYS), how="left")
        d = d.with_columns(
            (pl.col("buy_value_i") - pl.col("sell_value_i")).alias("_rn"),
            (pl.col("buy_value_n") - pl.col("sell_value_n")).alias("_ln"),
        )
    else:
        d = d.with_columns(
            pl.lit(None, dtype=pl.Float64).alias("_rn"), pl.lit(None, dtype=pl.Float64).alias("_ln")
        )
    val = pl.col("value")

    def flow(col: str, n: int) -> pl.Expr:
        mp = max(n // 2, 2)
        return pl.col(col).rolling_sum(n, min_samples=mp).over(G) / val.rolling_sum(
            n, min_samples=mp
        ).over(G)

    up = pl.col("_r") > 0
    up_val = pl.when(up).then(val).otherwise(0.0).rolling_sum(20, min_samples=10).over(G)
    dn_val = pl.when(~up).then(val).otherwise(0.0).rolling_sum(20, min_samples=10).over(G)
    trend_sign = pl.when(pl.col("stock_trend") > 0).then(1.0).otherwise(-1.0)
    d = d.with_columns(
        *(_own(pl.col(x)).alias(f"{x}_own") for x in SERIES),
        (pl.col("real_net_pct") * trend_sign).alias("real_net_with_trend"),
        (pl.col("legal_net_pct") * trend_sign).alias("legal_net_with_trend"),
        ((pl.col("vol_vs_30") - 1.0) * trend_sign).alias("vol_with_trend"),
        (flow("_rn", 5) - flow("_rn", 20)).alias("real_net_5_vs_20"),
        (flow("_ln", 5) - flow("_ln", 20)).alias("legal_net_5_vs_20"),
        (
            val.rolling_sum(5, min_samples=3).over(G)
            / 5
            / (val.rolling_sum(20, min_samples=10).over(G) / 20)
        ).alias("val_5_vs_20"),
        (up_val / (up_val + dn_val)).alias("up_down_value"),
    )
    d = d.with_columns((pl.col("real_net_pct_own") - _own(c)).alias("flow_vs_price_z"))
    d = d.with_columns(
        *(
            (pl.col(x).rank().over("date") / pl.col(x).count().over("date")).alias(f"{x}_rank")
            for x in SERIES
        )
    )

    if sectors is not None and "sector_code" in sectors.columns:
        d = d.join(sectors.select(G, "sector_code"), on=G, how="left")
        grp = ("date", "sector_code")
        d = d.with_columns(
            *((pl.col(x) - pl.col(x).median().over(*grp)).alias(f"{x}_ind") for x in SERIES),
            *(
                (pl.col(m).log() - pl.col(m).log().median().over(*grp)).alias(f"{m}_ind")
                for m in FUND_MULTIPLES
            ),
        )
    else:
        d = d.with_columns(
            [pl.lit(None, dtype=pl.Float64).alias(f"{x}_ind") for x in (*SERIES, *FUND_MULTIPLES)]
        )
    d = d.with_columns(
        *(
            (pl.col(m).log() - pl.col(m).log().rolling_median(250, min_samples=100).over(G)).alias(
                f"{m}_own"
            )
            for m in FUND_MULTIPLES
        )
    )
    out = d.select(*KEYS, *REL_COLUMNS).sort(KEYS)
    # a zero denominator (no trading in the window) is "no reading", not infinity
    return out.with_columns(
        [
            pl.when(pl.col(k).is_infinite() | pl.col(k).is_nan()).then(None).otherwise(pl.col(k))
            .alias(k)
            for k in REL_COLUMNS
        ]
    )  # fmt: skip
