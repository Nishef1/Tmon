"""Feature-group ablation (T7): the same walk-forward with one group removed or added.

``python -m tmon.backtest.ablation --timeframe W1 --json out.json``. Each variant trains the
LightGBM engine on a different column list; folds, labels and costs are shared. Out-of-sample
quality is read from every scored row (AUC, Brier skill) and from the trades each variant takes
(net expectancy)."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
import polars as pl
from sqlalchemy import select

from tmon.backtest.metrics import probabilistic_summary
from tmon.backtest.runner import prepare_dataset, run_backtest
from tmon.domain.rules import RuleBook
from tmon.features.builder import (
    BOARD_COLUMNS,
    KEYS,
    MARKET_COLUMNS,
    SLOW_BOARD_COLUMNS,
    get_feature_set,
)
from tmon.models.lgbm import LightGBMStrategy
from tmon.storage.models import MacroSeries

MACRO_SERIES = ("usd_free", "gold_18k")
MACRO_WINDOWS = (5, 20, 60)
MACRO_COLUMNS = tuple(f"{s}_chg_{w}" for s in MACRO_SERIES for w in MACRO_WINDOWS)


def macro_frame(rows: list[tuple[str, Any, Any, float]]) -> pl.DataFrame:
    """Per release day, the change of each series over 5/20/60 observations. Keyed by
    ``release_date`` so a row is joined only from the day it was public (docs/08)."""
    df = pl.DataFrame(
        rows,
        schema={"series": pl.Utf8, "date": pl.Date, "rel": pl.Date, "value": pl.Float64},
        orient="row",
    )
    out: pl.DataFrame | None = None
    for s in MACRO_SERIES:
        one = df.filter(pl.col("series") == s).sort("rel")
        one = one.select(
            pl.col("rel").alias("date"),
            *[
                (pl.col("value") / pl.col("value").shift(w) - 1).alias(f"{s}_chg_{w}")
                for w in MACRO_WINDOWS
            ],
        )
        out = one if out is None else out.join(one, on="date", how="full", coalesce=True)
    assert out is not None
    return out.sort("date")


def add_macro(ds: pl.DataFrame, macro: pl.DataFrame) -> pl.DataFrame:
    return ds.sort("date").join_asof(macro, on="date", strategy="backward").sort(list(KEYS))


def variants(timeframe: str) -> dict[str, list[str]]:
    full = list(get_feature_set(timeframe).columns)
    board = set(BOARD_COLUMNS) | set(SLOW_BOARD_COLUMNS)
    return {
        "full": full,
        "minus_board": [c for c in full if c not in board],
        # W1 dropped the market group after this report; re-test it by adding it back.
        **(
            {"minus_market": [c for c in full if c not in MARKET_COLUMNS]}
            if set(MARKET_COLUMNS) <= set(full)
            else {"plus_market": full + list(MARKET_COLUMNS)}
        ),
        "plus_macro": full + list(MACRO_COLUMNS),
    }


def _strategy(rules: RuleBook, timeframe: str, cols: list[str], name: str) -> LightGBMStrategy:
    s = LightGBMStrategy(rules, timeframe=timeframe, enforce_thresholds=False, name=name)
    s.features = list(cols)
    return s


def _probabilistic(pred: pl.DataFrame, ds: pl.DataFrame) -> dict[str, Any]:
    d = pred if "y" in pred.columns else pred.join(ds.select(*KEYS, "y"), on=list(KEYS), how="left")
    d = d.drop_nulls(["p_win", "y"])
    return probabilistic_summary(
        d["p_win"].to_numpy().astype(float), d["y"].to_numpy().astype(float)
    )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="tmon-ablation")
    ap.add_argument("--timeframe", default="W1")
    ap.add_argument("--json", type=Path)
    args = ap.parse_args(argv)
    tf = args.timeframe

    from tmon.core.db import session_scope
    from tmon.features.store import load_benchmark_inputs, load_inputs

    with session_scope() as session:
        prices, clients, sectors = load_inputs(session)
        index_daily, rf = load_benchmark_inputs(session)
        rules = RuleBook.from_session(session)
        mrows = [
            (r.series, r.ref_period, r.release_date or r.ref_period, r.value)
            for r in session.scalars(
                select(MacroSeries).where(MacroSeries.series.in_(MACRO_SERIES))
            )
        ]
    ds = add_macro(
        prepare_dataset(prices, clients, rules, sectors=sectors, timeframe=tf), macro_frame(mrows)
    )
    vs = variants(tf)
    strategies = {n: (lambda n=n, c=c: _strategy(rules, tf, c, n)) for n, c in vs.items()}
    run = run_backtest(ds, rules, strategies, timeframe=tf, index_daily=index_daily, rf=rf)
    out: dict[str, Any] = {"timeframe": tf, "folds": len(run.folds), "variants": {}}
    for n, s in run.strategies.items():
        prob = _probabilistic(s.predictions, ds)
        prob.pop("calibration", None)
        out["variants"][n] = {
            "n_features": len(vs[n]),
            "prob": prob,
            "trades": s.summary["trades"],
            "portfolio": {
                k: s.summary["portfolio"].get(k) for k in ("total_return", "sharpe", "max_drawdown")
            },
        }
    macro_cov = float(np.mean(ds["usd_free_chg_20"].is_not_null().to_numpy()))
    out["macro_coverage"] = macro_cov
    text = json.dumps(out, ensure_ascii=False, indent=2, default=str)
    if args.json:
        args.json.write_text(text, encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
