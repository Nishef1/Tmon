"""Board-reading ("تابلوخوانی") features, docs/04 table.

Inputs are *raw* exchange columns (``close``, ``last``, ``prev_close``, ``volume``,
``value``, client-type columns, ``base_volume``) plus ``adj_volume`` for the volume ratios and
a per-row ``limit_pct`` (from ``market_rules``, never a literal here).

Queue state is derived from where the day closed relative to the price limit. Historical
queue *volume* (``queue_to_base``) and book imbalance need order-book snapshots, which exist
only from the day capture started; they are ``null`` before that (docs/OPEN_QUESTIONS.md).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import polars as pl

G = "instrument_id"

QUEUE_NONE, QUEUE_BUY, QUEUE_SELL = 0, 1, -1
QUEUE_LABELS = {QUEUE_BUY: "buy_queue", QUEUE_SELL: "sell_queue", QUEUE_NONE: "none"}

REL_VOLUME_WINDOW = 20
FLOW_Z_WINDOW = 60
FLOW_Z_MIN_SAMPLES = 30
SMART_MONEY_POWER = 2.0
SMART_MONEY_REL_VOLUME = 2.0
QUEUE_TOLERANCE_RIALS = 1.0
BOOK_LEVELS = 5


def _safe_div(num: pl.Expr, den: pl.Expr) -> pl.Expr:
    return pl.when(den > 0).then(num / den).otherwise(None)


def fill_estimated_values(df: pl.DataFrame) -> pl.DataFrame:
    """Real/legal traded *values* are not always published. Where missing, estimate
    ``volume_side x (value / volume)`` and mark the row ``client_value_estimated``."""
    avg_price = _safe_div(pl.col("value"), pl.col("volume"))
    d = df.with_columns(
        pl.col("buy_value_i").is_null().alias("client_value_estimated"),
    )
    return d.with_columns(
        [
            pl.col(f"{side}_value_{kind}").fill_null(pl.col(f"{side}_volume_{kind}") * avg_price)
            for side in ("buy", "sell")
            for kind in ("i", "n")
        ]
    )


def add_board_features(df: pl.DataFrame) -> pl.DataFrame:
    """Add the docs/04 board features. ``df`` must be sorted by ``(instrument_id, date)``."""
    d = fill_estimated_values(df)
    close, last, prev = pl.col("close"), pl.col("last"), pl.col("prev_close")

    d = d.with_columns(
        _safe_div(pl.col("buy_value_i"), pl.col("buy_count_i")).alias("ind_buy_per_capita"),
        _safe_div(pl.col("sell_value_i"), pl.col("sell_count_i")).alias("ind_sell_per_capita"),
        (pl.col("buy_value_i") - pl.col("sell_value_i")).alias("ind_net_flow"),
    )
    d = d.with_columns(
        _safe_div(pl.col("ind_buy_per_capita"), pl.col("ind_sell_per_capita")).alias(
            "ind_buy_power"
        ),
        _safe_div(pl.col("ind_net_flow"), pl.col("value")).alias("ind_net_flow_ratio"),
        (
            (
                pl.col("ind_net_flow")
                - pl.col("ind_net_flow").rolling_mean(FLOW_Z_WINDOW, min_samples=FLOW_Z_MIN_SAMPLES)
            )
            / pl.col("ind_net_flow").rolling_std(FLOW_Z_WINDOW, min_samples=FLOW_Z_MIN_SAMPLES)
        )
        .over(G)
        .alias("ind_net_flow_z"),
        # net legal->real transfer of ownership as a share of the day's volume
        _safe_div(pl.col("sell_volume_n") - pl.col("buy_volume_n"), pl.col("volume")).alias(
            "inst_to_ind"
        ),
        _safe_div(
            pl.col("adj_volume"),
            pl.col("adj_volume").rolling_mean(REL_VOLUME_WINDOW).shift(1).over(G),
        ).alias("rel_volume"),
        _safe_div(pl.col("volume"), pl.col("base_volume")).alias("vol_to_base"),
        ((last - close) / close).alias("last_close_gap"),
        _safe_div(close - pl.col("low"), pl.col("high") - pl.col("low")).alias(
            "intraday_range_pos"
        ),
        ((close / prev - 1.0) / pl.col("limit_pct")).alias("ret_1_norm"),
    )
    d = d.with_columns(
        (
            (pl.col("ind_buy_power") > SMART_MONEY_POWER)
            & (pl.col("rel_volume") > SMART_MONEY_REL_VOLUME)
            & (pl.col("ind_net_flow") > 0)
        )
        .fill_null(False)
        .cast(pl.Int8)
        .alias("smart_money_flag"),
    )
    return add_queue_features(d)


def add_queue_features(df: pl.DataFrame, tolerance: float = QUEUE_TOLERANCE_RIALS) -> pl.DataFrame:
    """``queue_state`` from the close vs. the price limit, ``days_in_queue`` = run length."""
    close, prev, pct = pl.col("close"), pl.col("prev_close"), pl.col("limit_pct")
    limit_up = prev * (1.0 + pct)
    limit_down = prev * (1.0 - pct)
    code = (
        pl.when(pct.is_null() | prev.is_null() | close.is_null())
        .then(None)
        .when(close >= limit_up - tolerance)
        .then(pl.lit(QUEUE_BUY))
        .when(close <= limit_down + tolerance)
        .then(pl.lit(QUEUE_SELL))
        .otherwise(pl.lit(QUEUE_NONE))
    )
    d = df.with_columns(code.cast(pl.Int8).alias("queue_code"))
    d = d.with_columns(
        pl.col("queue_code")
        .replace_strict(QUEUE_LABELS, default=None, return_dtype=pl.Utf8)
        .alias("queue_state"),
        (pl.col("queue_code") != pl.col("queue_code").shift(1))
        .fill_null(True)
        .cum_sum()
        .over(G)
        .alias("_run_id"),
    )
    d = d.with_columns((pl.int_range(pl.len()).over([G, "_run_id"]) + 1).alias("_run_len"))
    return d.with_columns(
        pl.when(pl.col("queue_code").is_null())
        .then(None)
        .when(pl.col("queue_code") == QUEUE_NONE)
        .then(0)
        .otherwise(pl.col("_run_len"))
        .cast(pl.Int32)
        .alias("days_in_queue"),
        pl.lit(None, dtype=pl.Float64).alias("queue_to_base"),
    ).drop("_run_id", "_run_len")


# --------------------------------------------------------------------------- #
# Order-book depth (live snapshots only)
# --------------------------------------------------------------------------- #


def order_book_imbalance(
    levels: Sequence[dict[str, Any]], depth: int = BOOK_LEVELS
) -> float | None:
    """``(sum bid volume - sum ask volume) / (sum bid volume + sum ask volume)`` over the top
    ``depth`` rows. ``None`` when the book is empty."""
    rows = [r for i, r in enumerate(levels) if 1 <= int(r.get("row", i + 1)) <= depth]
    bid = sum(float(r.get("bid_volume") or 0) for r in rows)
    ask = sum(float(r.get("ask_volume") or 0) for r in rows)
    return (bid - ask) / (bid + ask) if bid + ask > 0 else None


def add_order_book(df: pl.DataFrame, imbalance_by_day: pl.DataFrame | None) -> pl.DataFrame:
    """Left-join the close-of-day imbalance (``instrument_id, date, ob_imbalance``)."""
    if imbalance_by_day is None or imbalance_by_day.is_empty():
        return df.with_columns(pl.lit(None, dtype=pl.Float64).alias("ob_imbalance"))
    return df.join(imbalance_by_day.select(G, "date", "ob_imbalance"), on=[G, "date"], how="left")
