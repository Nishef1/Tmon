"""Triple-barrier labels (docs/10 section 2).

For a decision at the close of day ``t``:

* entry ``P0``: D1 buys at the open of ``t+1``; W1/M1 at the close of ``t`` (config
  ``entry``); all prices are *adjusted*, so a capital event inside the window is not a loss;
* ``TP = P0 + k_tp * ATR14(t) * sqrt(scale)`` and ``SL = P0 - k_sl * ATR14(t) * sqrt(scale)``;
* the window is the ``horizon`` trading days after ``t`` (D1: ``t+1..t+3``);
* ``y = 1`` only if TP is touched on a strictly earlier day than SL; a day touching both is
  conservatively ``y = 0``; expiry without TP is ``y = 0``.

Labels use the future by construction. They are the target, never an input. Everything here
is vectorised over flat arrays sorted by ``(instrument, date)``; the only Python loop runs over
the horizon (at most 60 iterations), never over rows.

Rows get ``valid = False`` (and ``y = null``) when the sample cannot be used for training or
evaluation: the horizon runs past the last known bar, it crosses an exchange-wide halt, the
entry bar is unknown, or ATR is not yet defined. ``executable = False`` marks entries that
could not have been bought (the entry day is a locked limit-up, i.e. a buy queue). Exits that
fall on a locked limit-down day cannot be sold that day; their exit is moved to the next open
(``exit_delayed``).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
import polars as pl

from tmon.core.engine_config import EngineConfig, get_engine_config
from tmon.domain.calendar import halt_windows
from tmon.domain.rules import RuleBook
from tmon.features.adjustment import apply_adjustments
from tmon.features.builder import limit_pct_expr
from tmon.features.indicators import add_volatility

G = "instrument_id"

# A bar is a locked limit bar when it never traded away from one price and closed at the limit
# (within a rounding allowance for tick-rounded limit prices).
LOCK_TOLERANCE = 0.002

ENTRY_MODES = {"D1": "next_open", "W1": "close", "M1": "close"}

LABEL_SCHEMA: dict[str, pl.DataType] = {
    "instrument_id": pl.Int64(),
    "date": pl.Date(),
    "entry_date": pl.Date(),
    "exit_date": pl.Date(),
    "entry_price": pl.Float64(),
    "tp_price": pl.Float64(),
    "sl_price": pl.Float64(),
    "y": pl.Int8(),
    "exit_reason": pl.Utf8(),
    "exit_day": pl.Int32(),
    "realized_return": pl.Float64(),
    "executable": pl.Boolean(),
    "exit_delayed": pl.Boolean(),
    "valid": pl.Boolean(),
}


@dataclass(frozen=True)
class BarrierSpec:
    timeframe: str
    horizon: int
    atr_scale: float  # sqrt of the ATR scaling in days
    k_tp: float
    k_sl: float
    entry: str  # "next_open" | "close"

    @classmethod
    def from_config(
        cls,
        timeframe: str,
        cfg: EngineConfig | None = None,
        *,
        k_tp: float | None = None,
        k_sl: float | None = None,
    ) -> BarrierSpec:
        """Barrier spec from the config; ``k_tp``/``k_sl`` override the default pair (the grid)."""
        c = cfg or get_engine_config()
        tf = c.labeling.timeframes[timeframe]
        return cls(
            timeframe=timeframe,
            horizon=tf.horizon_days,
            atr_scale=math.sqrt(tf.atr_scale_days),
            k_tp=c.labeling.k_tp if k_tp is None else k_tp,
            k_sl=c.labeling.k_sl if k_sl is None else k_sl,
            entry=ENTRY_MODES[timeframe],
        )


def prepare_bars(
    prices: pl.DataFrame, rules: RuleBook, cfg: EngineConfig | None = None
) -> pl.DataFrame:
    """Adjusted OHLC + ATR(14) + limit fraction, sorted by (instrument, date).

    Halt rows are dropped so that "t+k" always means the k-th *trading* day; samples whose
    window straddles a halt are invalidated in :func:`triple_barrier_labels`.
    """
    c = cfg or get_engine_config()
    d = prices
    if "market_halt" not in d.columns:
        d = d.with_columns(pl.lit(False).alias("market_halt"))
    d = d.with_columns(pl.col("market_halt").fill_null(False))
    d = apply_adjustments(d)
    d = add_volatility(d, atr_n=c.labeling.atr_period)
    d = d.with_columns(limit_pct_expr(rules).alias("limit_pct"))
    return d.filter(~pl.col("market_halt")).sort(G, "date")


def _shift(a: np.ndarray, k: int, fill: float) -> np.ndarray:
    out = np.full_like(a, fill)
    if k < len(a):
        out[: len(a) - k] = a[k:]
    return out


def triple_barrier_labels(
    prices: pl.DataFrame,
    rules: RuleBook,
    timeframe: str = "D1",
    cfg: EngineConfig | None = None,
    *,
    k_tp: float | None = None,
    k_sl: float | None = None,
    bars: pl.DataFrame | None = None,
) -> pl.DataFrame:
    """One label row per (instrument, trading day). ``prices`` is the raw price frame used by
    the feature builder. ``k_tp``/``k_sl`` pick a barrier pair of the grid; ``bars`` is a
    :func:`prepare_bars` result to reuse across pairs."""
    c = cfg or get_engine_config()
    spec = BarrierSpec.from_config(timeframe, c, k_tp=k_tp, k_sl=k_sl)
    bars = prepare_bars(prices, rules, c) if bars is None else bars
    if bars.is_empty():
        return pl.DataFrame(schema=LABEL_SCHEMA)

    n = bars.height
    inst = bars[G].to_numpy()
    dates = bars["date"].to_numpy()
    o = bars["adj_open"].to_numpy().astype(float)
    h = bars["adj_high"].to_numpy().astype(float)
    lo = bars["adj_low"].to_numpy().astype(float)
    cl = bars["adj_close"].to_numpy().astype(float)
    pc = bars["adj_prev_close"].to_numpy().astype(float)
    atr = bars[f"atr_{c.labeling.atr_period}"].to_numpy().astype(float)
    lim = bars["limit_pct"].to_numpy().astype(float)

    pos = np.arange(n)
    last_of_inst = np.empty(n, dtype=np.int64)
    # index of the last bar of each instrument block (rows are sorted by instrument)
    change = np.flatnonzero(np.r_[inst[1:] != inst[:-1], True])
    starts = np.r_[0, change[:-1] + 1]
    for s, e in zip(starts, change, strict=True):  # loop over instruments, not rows
        last_of_inst[s : e + 1] = e

    def at(k: int) -> tuple[np.ndarray, np.ndarray]:
        """Row index of the bar ``k`` trading days ahead and whether it exists."""
        idx = pos + k
        ok = idx <= last_of_inst
        return np.where(ok, idx, 0), ok

    ret_prev = cl / pc - 1.0
    locked = (np.abs(h - lo) <= 1e-9 * np.maximum(cl, 1.0)) & np.isfinite(lim)
    locked_up = locked & (ret_prev >= lim - LOCK_TOLERANCE)
    locked_down = locked & (ret_prev <= -lim + LOCK_TOLERANCE)

    # entry
    if spec.entry == "next_open":
        e_idx, e_ok = at(1)
        entry = np.where(e_ok, o[e_idx], np.nan)
        window_first = 1
    else:
        e_idx, e_ok = pos, np.ones(n, dtype=bool)
        entry = cl.copy()
        window_first = 1
    executable = ~locked_up[e_idx] & e_ok

    width = spec.atr_scale * atr
    tp = entry + spec.k_tp * width
    sl = entry - spec.k_sl * width
    base_ok = e_ok & np.isfinite(entry) & np.isfinite(width) & (width > 0) & (sl > 0)

    big = spec.horizon + 1
    first_tp = np.full(n, big, dtype=np.int64)
    first_sl = np.full(n, big, dtype=np.int64)
    exists_all = np.ones(n, dtype=bool)  # whole window available
    for k in range(window_first, spec.horizon + 1):
        idx, ok = at(k)
        exists_all &= ok
        hit_tp = ok & (h[idx] >= tp) & (first_tp == big)
        hit_sl = ok & (lo[idx] <= sl) & (first_sl == big)
        first_tp = np.where(hit_tp, k, first_tp)
        first_sl = np.where(hit_sl, k, first_sl)

    tp_wins = first_tp < first_sl  # strictly earlier; same day -> SL wins (conservative)
    sl_hit = first_sl <= first_tp
    sl_hit &= first_sl < big
    exit_day = np.where(tp_wins, first_tp, np.where(sl_hit, first_sl, spec.horizon))
    x_idx = np.where(base_ok, pos + exit_day, 0)
    x_idx = np.minimum(x_idx, n - 1)

    # raw exit price on the exit bar
    gap_tp = np.maximum(o[x_idx], tp)  # open above TP fills at the open
    gap_sl = np.minimum(o[x_idx], sl)  # open below SL fills at the open (worse than SL)
    exit_price = np.where(tp_wins, gap_tp, np.where(sl_hit, gap_sl, cl[x_idx]))

    # a locked limit-down exit bar cannot be sold into: the exit slips to the next open
    blocked = locked_down[x_idx] & ~tp_wins
    nxt = np.minimum(x_idx + 1, n - 1)
    nxt_ok = (nxt <= last_of_inst) & (nxt != x_idx)
    delayed = blocked & nxt_ok
    exit_price = np.where(delayed, o[nxt], exit_price)
    unresolved_delay = blocked & ~nxt_ok  # cannot say where it exits

    # halts: invalidate windows that contain a halt (rows were dropped, so look at the gap in
    # the calendar and at the rule windows)
    exit_bar_idx = np.where(delayed, nxt, x_idx)
    start_date = dates
    end_date = dates[exit_bar_idx]
    crosses_halt = np.zeros(n, dtype=bool)
    for w in halt_windows(rules):
        crosses_halt |= (start_date <= np.datetime64(w.end)) & (end_date >= np.datetime64(w.start))

    # warm-up and tail rows carry no label
    valid = base_ok & exists_all & ~crosses_halt & ~unresolved_delay
    with np.errstate(divide="ignore", invalid="ignore"):  # rows with entry <= 0 are not valid
        gross = exit_price / entry - 1.0
    y = np.where(tp_wins, 1, 0).astype(np.int8)

    reason = np.where(
        tp_wins,
        "tp",
        np.where(sl_hit, np.where(first_sl == first_tp, "sl_same_day", "sl"), "expiry"),
    )
    out = pl.DataFrame(
        {
            "instrument_id": inst,
            "date": bars["date"],
            "entry_date": pl.Series(dates[e_idx]).cast(pl.Date),
            "exit_date": pl.Series(dates[exit_bar_idx]).cast(pl.Date),
            "entry_price": entry,
            "tp_price": tp,
            "sl_price": sl,
            "y": y,
            "exit_reason": reason,
            "exit_day": exit_day.astype(np.int32),
            "realized_return": gross,
            "executable": executable,
            "exit_delayed": delayed,
            "valid": valid,
        }
    )
    # unusable rows: blank the outcome so nothing can train on a half-known label
    return out.with_columns(
        pl.when(pl.col("valid")).then(pl.col("y")).otherwise(None).cast(pl.Int8).alias("y"),
        pl.when(pl.col("valid"))
        .then(pl.col("realized_return"))
        .otherwise(None)
        .alias("realized_return"),
        pl.when(pl.col("valid")).then(pl.col("exit_reason")).otherwise(None).alias("exit_reason"),
    ).select(list(LABEL_SCHEMA))
