"""Price adjustment for dividends and capital increases (docs/04, "پیش‌نیاز").

At an event day ``s`` the exchange resets the reference price: ``prev_close_s`` differs
from the previous row's ``close``. The event factor is::

    adj_factor_s = prev_close_s / close_before          (< 1 for dividends / increases)
    adjusted_price_t = raw_price_t * prod_{s > t} adj_factor_s

A gap is only taken as an event when its factor is plausible. A factor in (1, ``MIN_UP``) would
mean the exchange raised the reference price by a few percent, which no corporate action does
(a capital decrease raises it by much more); such gaps are days missing from the history, and
treating them as events would erase a real price move. A factor below ``MIN_FACTOR`` (a 20x
drop) is bad data. Both are left out (docs/reports/indicator-zoo-2026-11.md, "ممیزی داده").

Fixed-income funds that pay cash each month are different: on the payout day the price falls about
2% and the exchange does NOT reset ``prev_close``, so the gap test above never sees it. For the
ids passed as ``payout_ids`` a close-to-close fall of at least ``PAYOUT_DROP`` with an unchanged
``prev_close`` is taken as a payout with factor ``close / close_before``. Of 1,275 such falls in
fixed-income funds only 3.8% were half recovered the next day, so they are not noise
(docs/reports/fund-research-2026-11.md, "سود نقدی صندوق درآمد ثابت").

All code is vectorised Polars; there is no per-row Python loop.
"""

from __future__ import annotations

from collections.abc import Collection

import polars as pl

PRICE_COLS = ("open", "high", "low", "close", "last", "prev_close")
MIN_UP = 1.2  # upward factors below this are missing days, not a capital decrease
MIN_FACTOR = 0.05
PAYOUT_DROP = -0.01  # a fixed-income fund's one-day fall this deep is a cash payout


def detect_adjustments(prices: pl.DataFrame) -> pl.DataFrame:
    """Derive adjustment events from ``prev_close`` gaps.

    Input columns: ``instrument_id, date, close, prev_close``.
    Output columns: ``instrument_id, date, close_before, price_after, adj_factor``.
    """
    d = prices.sort(["instrument_id", "date"]).with_columns(
        close_before=pl.col("close").shift(1).over("instrument_id")
    )
    return (
        d.filter(
            pl.col("close_before").is_not_null()
            & (pl.col("close_before") > 0)
            & (pl.col("prev_close") > 0)
            & (pl.col("prev_close") != pl.col("close_before"))
        )
        .with_columns(_f=pl.col("prev_close") / pl.col("close_before"))
        .filter(((pl.col("_f") < 1) | (pl.col("_f") >= MIN_UP)) & (pl.col("_f") >= MIN_FACTOR))
        .select(
            "instrument_id",
            "date",
            "close_before",
            pl.col("prev_close").alias("price_after"),
            (pl.col("prev_close") / pl.col("close_before")).alias("adj_factor"),
        )
    )


def detect_fund_payouts(prices: pl.DataFrame, payout_ids: Collection[int]) -> pl.DataFrame:
    """Cash payouts of fixed-income funds, in the output schema of ``detect_adjustments``."""
    d = (
        prices.filter(pl.col("instrument_id").is_in(list(payout_ids)))
        .sort(["instrument_id", "date"])
        .with_columns(close_before=pl.col("close").shift(1).over("instrument_id"))
    )
    return d.filter(
        (pl.col("close_before") > 0)
        & (pl.col("prev_close") == pl.col("close_before"))
        & (pl.col("close") / pl.col("close_before") - 1 <= PAYOUT_DROP)
        & (pl.col("close") / pl.col("close_before") >= MIN_FACTOR)
    ).select(
        "instrument_id",
        "date",
        "close_before",
        pl.col("close").alias("price_after"),
        (pl.col("close") / pl.col("close_before")).alias("adj_factor"),
    )


def apply_adjustments(
    prices: pl.DataFrame,
    events: pl.DataFrame | None = None,
    payout_ids: Collection[int] = (),
) -> pl.DataFrame:
    """Return ``prices`` with ``adj_*`` price columns, ``adj_factor_cum`` and ``adj_volume``.

    ``events`` defaults to the events derived from ``prices`` itself, plus the cash payouts of
    the fixed-income funds in ``payout_ids``. Rows keep their order by (instrument_id, date).
    """
    if events is None:
        events = detect_adjustments(prices)
        if payout_ids:
            events = pl.concat([events, detect_fund_payouts(prices, payout_ids)])
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
