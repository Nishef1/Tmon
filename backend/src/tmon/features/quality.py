"""Daily rows the model must not read as they are (docs/reports/indicator-zoo-2026-11.md,
"ممیزی داده"). Found by ``research/data_audit.py`` over the whole history:

Dropped price rows:
* a price <= 0;
* a copied day: the same open/high/low/close/volume as the symbol's previous row (volume > 0);
* a spike: an unadjusted close-to-close move beyond the day's limit band + 1% that comes
  straight back the next day (a bad tick); judged only on days with 30+ symbols, the band
  being the 99th percentile of high / prev_close - 1 that day (at least 2%);
* a closing price outside [min(low, prev_close), max(high, prev_close)]: the Tehran closing
  price may leave the day's range when volume is under the base volume, but only towards
  ``prev_close``.
When a dropped row sat between two good ones and was not itself an adjustment day, the next
row's ``prev_close`` is set to the previous good close, so the drop does not create a fake
adjustment event.

Repaired price fields: a ``prev_close`` <= 0 (a symbol's first days in old history) becomes
unknown (null); ``open`` / ``last`` outside [low, high] are clipped into the range, and a
``value`` whose average price (value / volume) is outside the range becomes volume * close.

Dropped client-type rows (the flows of that day are unknown, not zero): buy (or sell) value or
volume of individuals + institutions that differs from the day's total by more than 3%, or a
side with value but no traders (or the reverse).
"""

from __future__ import annotations

import polars as pl

C = pl.col
G = "instrument_id"
BAND_SLACK = 0.01
MIN_BAND = 0.02  # the Tehran limit has not been narrower than this
MIN_SYMBOLS_FOR_BAND = 30
FLOW_TOL = 0.03
_TMP = ("_pc_row", "_r", "_band", "_bad")


def _bad_price_rows() -> pl.Expr:
    pc_row = C("close").shift(1).over(G)
    no_event = (C("prev_close") - pc_row).abs() <= 0.005 * pc_row
    r = C("close") / pc_row - 1
    r_next = C("close").shift(-1).over(G) / C("close") - 1
    back = C("close").shift(-1).over(G) / pc_row - 1
    band = C("_band")
    same = pl.all_horizontal(
        [C(k) == C(k).shift(1).over(G) for k in ("open", "high", "low", "close", "volume")]
    )
    spike = (
        (r.abs() > band + BAND_SLACK)
        & (r * r_next < 0)
        & (back.abs() < band)
        & no_event
        & (C("prev_close").shift(-1).over(G) == C("close"))  # the next day is no event either
    )
    close_out = ~C("close").is_between(
        pl.min_horizontal("low", "prev_close") * 0.999,
        pl.max_horizontal("high", "prev_close") * 1.001,
    )
    return (
        (pl.min_horizontal("open", "high", "low", "close") <= 0)
        | (same & (C("volume") > 0))
        | spike
        | close_out
    ).fill_null(False)


def clean_prices(prices: pl.DataFrame) -> pl.DataFrame:
    """``prices`` (raw, unadjusted) without the bad rows and with the repairable fields fixed."""
    if prices.is_empty():
        return prices
    d = prices.sort(G, "date").with_columns(
        prev_close=pl.when(C("prev_close") > 0).then(C("prev_close")).otherwise(None)
    )
    d = d.with_columns(
        # the day's limit band, read from the market: only when enough symbols traded that day
        _band=pl.when(pl.len().over("date") >= MIN_SYMBOLS_FOR_BAND)
        .then(
            pl.max_horizontal(
                (C("high") / C("prev_close") - 1).quantile(0.99).over("date"), pl.lit(MIN_BAND)
            )
        )
        .otherwise(None)
    )
    d = d.with_columns(_bad=_bad_price_rows())
    # the next good row must not see the dropped row's close as its reference
    prev_bad = C("_bad").shift(1).over(G).fill_null(False)
    ref_was_bad_close = (C("prev_close") - C("close").shift(1).over(G)).abs() <= 0.005 * C(
        "close"
    ).shift(1).over(G)
    d = d.with_columns(_fix=prev_bad & ref_was_bad_close.fill_null(False))
    d = d.filter(~C("_bad"))
    d = d.with_columns(
        prev_close=pl.when(C("_fix") & C("close").shift(1).over(G).is_not_null())
        .then(C("close").shift(1).over(G))
        .otherwise(C("prev_close"))
    )
    lo, hi = C("low"), C("high")
    d = d.with_columns(
        open=pl.when(C("open").is_between(lo, hi))
        .then(C("open"))
        .otherwise(C("open").clip(lo, hi)),
        last=pl.when(C("last").is_null() | C("last").is_between(lo, hi))
        .then(C("last"))
        .otherwise(C("last").clip(lo, hi)),
        value=pl.when(
            (C("volume") > 0) & ~(C("value") / C("volume")).is_between(lo * 0.98, hi * 1.02)
        )
        .then(C("volume") * C("close"))
        .otherwise(C("value")),
    )
    return d.drop([c for c in (*_TMP, "_fix") if c in d.columns])


def clean_clients(clients: pl.DataFrame, prices: pl.DataFrame) -> pl.DataFrame:
    """``clients`` without the days whose individual/institutional split does not add up."""
    if clients.is_empty():
        return clients
    q = clients.join(prices.select(G, "date", "value", "volume"), on=[G, "date"], how="left")

    def off(a: pl.Expr, b: pl.Expr) -> pl.Expr:
        return ((a / b - 1).abs() > FLOW_TOL) & (b > 0)

    def mismatch(v: str, n: str) -> pl.Expr:
        return (C(v) > 0) != (C(n) > 0)

    bad = (
        off(C("buy_value_i") + C("buy_value_n"), C("value"))
        | off(C("sell_value_i") + C("sell_value_n"), C("value"))
        | off(C("buy_volume_i") + C("buy_volume_n"), C("volume"))
        | off(C("sell_volume_i") + C("sell_volume_n"), C("volume"))
        | mismatch("buy_value_i", "buy_count_i")
        | mismatch("sell_value_i", "sell_count_i")
        | mismatch("buy_value_n", "buy_count_n")
        | mismatch("sell_value_n", "sell_count_n")
    ).fill_null(False)
    return q.filter(~bad).select(clients.columns)
