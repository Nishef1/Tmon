"""Do the four ranking signals rank funds? (docs/reports/fund-verdict-2026-11.md)

The stock ranking gives no verdict to funds. Before giving one, test on the funds themselves what
the stock model claims: that the composite of the four equal-weight signals (buy power, calm,
distance from the 52-week high, 12-1 momentum) orders what comes next. Judged only among liquid
tradable funds (median value of the last 20 sessions at or above 1 billion toman), in both halves
of time, from the next open (the panel's own forward returns start at t+1), with a round-trip cost.

Per horizon and half: mean rank IC with t (non-overlapping days), top third minus bottom third of
the day's funds, and top third minus the median fund, before and after cost. Each signal alone is
shown too, and the composite is repeated on each fund type. A circular shift of the fund labels is
not needed here: the IC itself is the placebo-free statistic, and the spread is compared with the
share of days it was positive.

Run from backend/ with the live env: python research/market_method/fund_signals.py
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import polars as pl
from sqlalchemy import select

from tmon.backtest.signal_decay import SIGNALS, adjusted_close, build_panel
from tmon.core.db import session_scope
from tmon.core.engine_config import get_engine_config
from tmon.domain.enums import InstrumentType as T
from tmon.domain.rules import RuleBook
from tmon.features.builder import build_features
from tmon.features.store import load_inputs
from tmon.storage.models import Instrument

OUT = Path(__file__).parent / "results_fund_signals.json"
FUND_TYPES = {
    T.ETF_EQUITY.value: "equity",
    T.ETF_MIXED.value: "mixed",
    T.ETF_COMMODITY.value: "commodity",
    T.ETF_LEVERAGED.value: "leveraged",
}
HORIZONS = (5, 20)
RUNS = (1, 3, 5, 10, 20)  # sessions of the fund's own recent run
COST = 0.003  # round trip for a fund, rounded up
MIN_VALUE = 1e10  # rials a day
MIN_FUNDS = 12  # funds a day needs to have a cross-section


def rank(x: pl.Expr) -> pl.Expr:
    return x.rank("average") / x.count()


def stats(panel: pl.DataFrame, col: str, h: int) -> dict[str, float | int | None]:
    """IC and spreads of ``col`` (higher = buy) for the days of ``panel``."""
    f = f"fwd_{h}"
    d = panel.filter(pl.col(f).is_not_null() & pl.col(col).is_not_null())
    by = d.group_by("date").agg(
        pl.len().alias("n"),
        pl.corr(pl.col(col).rank(), pl.col(f).rank()).alias("ic"),
        pl.col(f).median().alias("med"),
        pl.col(f).filter(pl.col(col) > 2 / 3).mean().alias("top"),
        pl.col(f).filter(pl.col(col) <= 1 / 3).mean().alias("bot"),
    )
    by = by.filter(pl.col("n") >= MIN_FUNDS).sort("date").drop_nulls()
    if by.height < 30:
        return {"days": by.height}
    # keep every h-th day so overlapping windows do not inflate t
    ind = by.gather_every(h)
    ic = ind["ic"].to_numpy()
    top_med = (by["top"] - by["med"]).to_numpy()
    spread = (by["top"] - by["bot"]).to_numpy()
    t = float(ic.mean() / (ic.std(ddof=1) / np.sqrt(len(ic)))) if len(ic) > 2 else None
    ts = (ind["top"] - ind["bot"]).to_numpy()
    t_sp = float(ts.mean() / (ts.std(ddof=1) / np.sqrt(len(ts)))) if len(ts) > 2 else None
    return {
        "days": int(by.height),
        "ic": float(by["ic"].mean()),
        "ic_t": t,
        "top_minus_median": float(top_med.mean()),
        "top_minus_median_net": float(top_med.mean() - COST),
        "top_minus_bottom": float(spread.mean()),
        "top_minus_bottom_t": t_sp,
        "share_days_top_beats_bottom": float((spread > 0).mean()),
        "top_mean": float(by["top"].mean()),
    }


def main() -> None:
    cfg = get_engine_config()
    with session_scope() as s:
        prices, clients, sectors = load_inputs(s)
        rules = RuleBook.from_session(s)
        types = {i.id: i.instrument_type for i in s.scalars(select(Instrument))}
    feats = build_features(prices, clients, rules, sectors=sectors)
    adj = adjusted_close(prices)
    panel = build_panel(feats, adj, cfg, horizons=HORIZONS)
    # the fund's own recent run: return over the last k sessions, to test "ran ahead, then gave back"
    back = adj.sort("instrument_id", "date").with_columns(
        *[
            (pl.col("adj_close") / pl.col("adj_close").shift(k).over("instrument_id") - 1.0).alias(
                f"ret_{k}"
            )
            for k in RUNS
        ]
    )
    panel = panel.join(
        back.select("instrument_id", "date", *[f"ret_{k}" for k in RUNS]),
        on=["instrument_id", "date"],
        how="left",
    )
    liq = feats.select("instrument_id", "date", "median_value_20")
    panel = panel.join(liq, on=["instrument_id", "date"], how="left")
    kind = {i: FUND_TYPES[t] for i, t in types.items() if t in FUND_TYPES}
    funds = panel.filter(
        pl.col("instrument_id").is_in(list(kind)) & (pl.col("median_value_20") >= MIN_VALUE)
    )
    funds = funds.with_columns(
        pl.col("instrument_id").replace_strict(kind, default=None).alias("kind")
    )
    # ranks inside the day's funds, not inside all symbols
    funds = funds.with_columns(
        *[
            (
                rank(pl.col(s).over("date")) if sign > 0 else 1.0 - rank(pl.col(s).over("date"))
            ).alias(f"f_{s}")
            for s, sign in SIGNALS.items()
        ]
    )
    funds = funds.with_columns(
        pl.mean_horizontal([f"f_{s}" for s in SIGNALS]).alias("f_comp")
    ).with_columns(rank(pl.col("f_comp").over("date")).alias("f_comp_r"))
    dates = sorted(funds["date"].unique().to_list())
    mid = dates[len(dates) // 2]
    result: dict = {
        "n_rows": funds.height,
        "first": str(dates[0]),
        "last": str(dates[-1]),
        "mid": str(mid),
    }
    halves = {
        "all": funds,
        "first": funds.filter(pl.col("date") < mid),
        "second": funds.filter(pl.col("date") >= mid),
    }
    rows: dict = {}
    for h in HORIZONS:
        for hn, d in halves.items():
            rows[f"composite_h{h}_{hn}"] = stats(d, "f_comp_r", h)
            for sig in SIGNALS:
                rows[f"{sig}_h{h}_{hn}"] = stats(
                    d.with_columns(rank(pl.col(f"f_{sig}").over("date")).alias("x")), "x", h
                )
    for k in RUNS:
        # a fund that ran the most lately is ranked lowest: higher = buy
        g = funds.with_columns((1.0 - rank(pl.col(f"ret_{k}").over("date"))).alias("rev"))
        for h in HORIZONS:
            for hn, d in {
                "all": g,
                "first": g.filter(pl.col("date") < mid),
                "second": g.filter(pl.col("date") >= mid),
            }.items():
                rows[f"reversal_{k}_h{h}_{hn}"] = stats(d, "rev", h)
    for k in ("equity", "mixed", "commodity", "leveraged"):
        sub = funds.filter(pl.col("kind") == k)
        n_funds = sub["instrument_id"].n_unique()
        rows[f"type_{k}"] = {"funds": n_funds}
    result["rows"] = rows
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=1))
    for k, v in rows.items():
        print(k, {a: (round(b, 4) if isinstance(b, float) else b) for a, b in v.items()})


if __name__ == "__main__":
    main()
