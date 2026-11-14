"""Short-horizon (1 to 5 day) score from the order book, validated by ``backtest.book_study``.

The long-horizon product score is untouched: on the 255-day study the book added nothing that
held up at 20 days. At 1 to 5 days the features below raised the IC of the four-signal score in
both halves of the sample and when chosen on one half and tested on the other.
"""

from __future__ import annotations

import polars as pl

KEYS = ("instrument_id", "date")

# (column, sign) in the order forward selection picked them; weights are equal after ranking.
SHORT_FEATURES: tuple[tuple[str, int], ...] = (
    ("tw_imbalance", 1),
    ("close_imbalance", 1),
    ("tw_size_ratio", 1),
    ("open_imbalance", 1),
    ("last_close_gap", 1),
)

# Looked at and dropped: no gain at any horizon, or a gain only on one half.
DROPPED: tuple[str, ...] = (
    "tw_spread",
    "rel_volume",
    "queue_flip",
    "tw_depth_value",
    "depth_to_median",
    "ind_net_flow_z",
    "intraday_range_pos",
    "frac_sell_queue",
)

# Positive alone but absorbed once the chosen ones are in (correlated with them).
REDUNDANT: tuple[str, ...] = (
    "early_imbalance",
    "frac_buy_queue",
    "peak_queue_volume",
    "queue_to_median",
    "days_in_queue",
    "ret_1_norm",
    "ind_net_flow_ratio",
    "vol_to_base",
)


def _rank(col: str) -> pl.Expr:
    r = pl.col(col).rank("average").over("date")
    return (r - 0.5) / pl.col(col).count().over("date") - 0.5


def short_score(df: pl.DataFrame) -> pl.DataFrame:
    """``df`` plus ``book_score``: mean of the date-ranked features (missing counts as neutral)."""
    parts = [(_rank(c) * s).fill_null(0.0).fill_nan(0.0) for c, s in SHORT_FEATURES]
    return df.with_columns((pl.sum_horizontal(parts) / len(parts)).alias("book_score"))
