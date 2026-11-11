"""Price adjustment for dividends and capital increases (docs/04, "پیش‌نیاز").

At an event day ``s`` the exchange resets the reference price: ``prev_close_s`` differs
from the previous row's ``close``. The event factor is::

    adj_factor_s = prev_close_s / close_before          (< 1 for dividends / increases)
    adjusted_price_t = raw_price_t * prod_{s > t} adj_factor_s

All code is vectorised Polars; there is no per-row Python loop.
"""

from __future__ import annotations

import polars as pl

PRICE_COLS = ("open", "high", "low", "close", "last", "prev_close")


def detect_adjustments(prices: pl.DataFrame) -> pl.DataFrame:
    """Derive adjustment events from ``prev_close`` gaps.

    Input columns: ``instrument_id, date, close, prev_close``.
    Output columns: ``instrument_id, date, close_before, price_after, adj_factor``.
    """
    d = prices.sort(["instrument_id", "date"]).with_columns(
        close_before=pl.col("close").shift(1).over("instrument_id")
    )
    return d.filter(
        pl.col("close_before").is_not_null()
        & (pl.col("close_before") > 0)
        & (pl.col("prev_close") > 0)
        & (pl.col("prev_close") != pl.col("close_before"))
    ).select(
        "instrument_id",
        "date",
        "close_before",
        pl.col("prev_close").alias("price_after"),
        (pl.col("prev_close") / pl.col("close_before")).alias("adj_factor"),
    )


def apply_adjustments(prices: pl.DataFrame, events: pl.DataFrame | None = None) -> pl.DataFrame:
    """Return ``prices`` with ``adj_*`` price columns, ``adj_factor_cum`` and ``adj_volume``.

    ``events`` defaults to the events derived from ``prices`` itself. Rows keep their order
    by (instrument_id, date).
    """
    if events is None:
        events = detect_adjustments(prices)
    ev = events.select("instrument_id", "date", pl.col("adj_factor").alias("_event_factor"))

    d = (
        prices.sort(["instrument_id", "date"])
        .join(ev, on=["instrument_id", "date"], how="left")
        .with_columns(pl.col("_event_factor").fill_null(1.0))
    )
    # prod_{s >= t} f_s via reversed cumprod; shift to make it strict (s > t).
    d = d.with_columns(
        _incl=pl.col("_event_factor").reverse().cum_prod().reverse().over("instrument_id")
    ).with_columns(adj_factor_cum=pl.col("_incl").shift(-1).over("instrument_id").fill_null(1.0))

    exprs = [
        (pl.col(c) * pl.col("adj_factor_cum")).alias(f"adj_{c}")
        for c in PRICE_COLS
        if c in d.columns
    ]
    if "volume" in d.columns:
        exprs.append((pl.col("volume") / pl.col("adj_factor_cum")).alias("adj_volume"))
    return d.with_columns(exprs).drop("_event_factor", "_incl")
