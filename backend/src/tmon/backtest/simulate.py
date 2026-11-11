"""Turn predictions into trades and a daily portfolio return series.

Execution model (all vectorised; see docs/OPEN_QUESTIONS.md for its limits):

* a signal at the close of ``t`` buys at the label's entry price (D1: open of ``t+1``);
* each day the ``max_new_positions_per_day`` highest scores are taken; picks whose entry was a
  locked limit-up (buy queue) are *not filled* and simply drop out (they still used a slot, as
  they would have in practice);
* size = ``min(max_position_pct, risk_per_trade / (k_sl * ATR%))`` unless the strategy supplies
  its own ``weight``; total gross exposure is capped by ``max_gross_exposure`` by shrinking the
  trades that overlap an over-subscribed day;
* P&L is booked on the exit date as ``weight * net_return`` of current equity, with the buy and
  sell costs from ``market_rules`` plus the slippage allowance. Equity is therefore marked at
  exits, which understates intra-trade drawdowns slightly.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date

import numpy as np
import polars as pl

from tmon.backtest.costs import add_costs
from tmon.core.engine_config import EngineConfig, get_engine_config
from tmon.domain.rules import RuleBook
from tmon.features.builder import KEYS

TRADE_COLUMNS = (
    "entry_date", "exit_date", "realized_return", "y", "exit_reason", "exit_delayed",
    "executable", "valid", "atr_14_pct",
)  # fmt: skip


@dataclass
class SimResult:
    trades: pl.DataFrame
    daily: pl.DataFrame  # date, ret, equity, regime
    counts: dict[str, int] = field(default_factory=dict)


def regime_frame(dates: list[date], cfg: EngineConfig) -> pl.DataFrame:
    """``date -> regime`` for the unique calendar dates (one small loop over days)."""
    return pl.DataFrame(
        {"date": dates, "regime": [cfg.regime_of(d) for d in dates]},
        schema={"date": pl.Date, "regime": pl.Utf8},
    )


def simulate(
    preds: pl.DataFrame,
    ds: pl.DataFrame,
    rules: RuleBook,
    timeframe: str = "D1",
    cfg: EngineConfig | None = None,
) -> SimResult:
    c = cfg or get_engine_config()
    bt = c.backtest
    tf = c.labeling.timeframes[timeframe]
    calendar = ds["date"].unique().sort()
    cal = pl.DataFrame({"date": calendar, "idx": np.arange(calendar.len())})
    n_days = calendar.len()

    sig = preds.filter(pl.col("signal")).sort(
        ["date", "score", "instrument_id"], descending=[False, True, False]
    )
    counts = {"signals": sig.height}
    sig = sig.with_columns(
        pl.col("score").rank("ordinal", descending=True).over("date").alias("_r")
    )
    sig = sig.filter(pl.col("_r") <= bt.max_new_positions_per_day).drop("_r")
    counts["selected"] = sig.height

    extra = [c_ for c_ in ("p_win", "ev", "weight") if c_ in sig.columns]
    cand = sig.select(*KEYS, "score", *extra).join(
        ds.select(*KEYS, *TRADE_COLUMNS), on=list(KEYS), how="left"
    )
    counts["unresolved"] = int((~cand["valid"].fill_null(False)).sum())
    cand = cand.filter(pl.col("valid").fill_null(False))
    counts["unfilled_buy_queue"] = int((~cand["executable"]).sum())
    cand = cand.filter(pl.col("executable"))

    risk_w = pl.lit(c.sizing.risk_per_trade) / (
        c.labeling.k_sl * math.sqrt(tf.atr_scale_days) * pl.col("atr_14_pct")
    )
    size = pl.col("weight") if "weight" in cand.columns else risk_w
    cand = cand.with_columns(
        pl.min_horizontal(pl.lit(c.sizing.max_position_pct), size).fill_null(0.0).alias("weight")
    ).filter(pl.col("weight") > 0)

    cand = add_costs(cand, rules, c.costs.slippage_fraction)
    cand = (
        cand.join(cal.rename({"date": "entry_date", "idx": "entry_idx"}), on="entry_date")
        .join(cal.rename({"date": "exit_date", "idx": "exit_idx"}), on="exit_date")
        .sort("date", "instrument_id")
    )

    e = cand["entry_idx"].to_numpy().astype(np.int64)
    x = cand["exit_idx"].to_numpy().astype(np.int64)
    w = cand["weight"].to_numpy().astype(float)
    life = (x - e) if cand.height else np.zeros(0, dtype=np.int64)

    gross = np.zeros(n_days)
    max_life = int(life.max()) if life.size else 0
    for k in range(max_life + 1):  # loop over holding days, not over trades
        live = life >= k
        np.add.at(gross, (e + k)[live], w[live])
    peak = np.zeros_like(w)
    for k in range(max_life + 1):
        live = life >= k
        peak = np.where(live, np.maximum(peak, gross[np.minimum(e + k, n_days - 1)]), peak)
    scale = np.where(
        peak > bt.max_gross_exposure, bt.max_gross_exposure / np.maximum(peak, 1e-12), 1.0
    )
    weight = w * scale
    contrib = weight * cand["net_return"].to_numpy().astype(float) if cand.height else w

    daily_ret = np.zeros(n_days)
    if cand.height:
        np.add.at(daily_ret, x, contrib)
    start_idx = int(e.min()) if cand.height else 0
    if preds.height:
        first_pred = preds["date"].min()
        start_idx = int(cal.filter(pl.col("date") == first_pred)["idx"][0])
    daily = pl.DataFrame(
        {
            "date": calendar[start_idx:],
            "ret": daily_ret[start_idx:],
        }
    ).with_columns(((1 + pl.col("ret")).cum_prod()).alias("equity"))
    reg = regime_frame(calendar.to_list(), c)
    daily = daily.join(reg, on="date", how="left")

    trades = cand.with_columns(
        pl.Series("weight_applied", weight),
        pl.Series("pnl_frac", contrib),
    ).join(reg.rename({"date": "entry_date", "regime": "regime"}), on="entry_date", how="left")
    counts["trades"] = trades.height
    return SimResult(trades, daily, counts)
