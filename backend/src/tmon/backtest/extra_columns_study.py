"""Do the new derived columns help a model? Old D1 feature set against old plus new.

``python -m tmon.backtest.extra_columns_study --json docs/data/extra-columns-study.json``.
``--relative`` tests the trend, peer and pairwise readings of ``features/relative.py`` instead
(``docs/data/relative-columns-study.json``).
The same walk-forward, labels and round-trip costs as ``tmon.backtest.ablation``; only the column
list differs. Quality is read on all scored rows (AUC, Brier skill) and on the trades of each
variant (net of costs), each over the whole out-of-sample span and again over its first and second
half. Nothing here changes the production model: the gate is stated in the report and it only
reports. The data mostly covers one bull regime (OPEN_QUESTIONS 1)."""

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
from tmon.core.engine_config import get_engine_config
from tmon.domain.rules import RuleBook
from tmon.features.builder import KEYS, get_feature_set
from tmon.features.extra import GROUPS, build_extra, shares_frame
from tmon.features.fundamentals import load_statements
from tmon.features.relative import REL_GROUPS, build_relative
from tmon.models.lgbm import LightGBMStrategy
from tmon.storage.models import Instrument, OrderBookDaily, ShareChange


def variants(timeframe: str, relative: bool = False) -> dict[str, list[str]]:
    old = list(get_feature_set(timeframe).columns)
    out = {"old": old}
    if relative:
        rel_all = [c for cols in REL_GROUPS.values() for c in cols]
        extra_all = [c for cols in GROUPS.values() for c in cols]
        for g, cols in REL_GROUPS.items():
            out[f"old+{g}"] = old + list(cols)
        out["old+rel"] = old + rel_all
        out["old+extra+rel"] = old + extra_all + rel_all
        return out
    for g, cols in GROUPS.items():
        out[f"old+{g}"] = old + list(cols)
    out["old+all"] = old + [c for cols in GROUPS.values() for c in cols]
    return out


def _strategy(rules: RuleBook, tf: str, cols: list[str], name: str) -> LightGBMStrategy:
    s = LightGBMStrategy(rules, timeframe=tf, enforce_thresholds=False, name=name)
    s.features = list(cols)
    return s


def _trade_stats(t: pl.DataFrame) -> dict[str, Any]:
    if t.is_empty():
        return {"n": 0}
    r = t["net_return"].drop_nulls().to_numpy().astype(float)
    return {
        "n": int(r.size),
        "win_rate": float((r > 0).mean()) if r.size else None,
        "net_expectancy": float(r.mean()) if r.size else None,
        "median": float(np.median(r)) if r.size else None,
    }


def _prob(pred: pl.DataFrame, ds: pl.DataFrame) -> dict[str, Any]:
    d = pred if "y" in pred.columns else pred.join(ds.select(*KEYS, "y"), on=list(KEYS), how="left")
    d = d.drop_nulls(["p_win", "y"])
    if d.is_empty():
        return {"n": 0}
    out = probabilistic_summary(
        d["p_win"].to_numpy().astype(float), d["y"].to_numpy().astype(float)
    )
    out.pop("calibration", None)
    return out


def load_columns() -> dict[str, Any]:
    """Stored inputs and the extra columns built from them (point in time); shared by the studies
    that test the columns (this one and ``research/market_method/khak_columns.py``)."""
    from tmon.core.db import session_scope
    from tmon.features.store import load_benchmark_inputs, load_inputs

    cfg = get_engine_config()
    with session_scope() as session:
        prices, clients, sectors = load_inputs(session)
        index_daily, rf = load_benchmark_inputs(session)
        rules = RuleBook.from_session(session)
        stmts = load_statements(session)
        changes = [
            (r.instrument_id, r.date, r.shares_old, r.shares_new)
            for r in session.scalars(select(ShareChange))
            if r.instrument_id is not None
        ]
        tags = {
            i: float((t or {}).get("shares") or 0)
            for i, t in session.execute(select(Instrument.id, Instrument.tags))
        }
        ob = pl.DataFrame(
            [
                (r.instrument_id, r.date, r.close_bid_price, r.close_bid_volume,
                 r.close_ask_price, r.close_ask_volume)
                for r in session.scalars(select(OrderBookDaily))
            ],
            schema={
                "instrument_id": pl.Int64, "date": pl.Date,
                "close_bid_price": pl.Float64, "close_bid_volume": pl.Float64,
                "close_ask_price": pl.Float64, "close_ask_volume": pl.Float64,
            },
            orient="row",
        )  # fmt: skip
    tedpix = cfg.benchmarks.indices.get("tedpix")
    ix = index_daily.filter(pl.col("index_code") == tedpix).select("date", "close")
    extra = build_extra(
        prices,
        clients,
        rules,
        sectors=sectors,
        index_close=ix,
        shares=shares_frame(changes, tags),
        stmts=stmts,
        order_book=ob,
    )
    return {
        "prices": prices, "clients": clients, "sectors": sectors, "index_daily": index_daily,
        "rf": rf, "rules": rules, "extra": extra, "ix": ix,
    }  # fmt: skip


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="tmon-extra-columns-study")
    ap.add_argument("--timeframe", default="D1")
    ap.add_argument("--json", type=Path)
    ap.add_argument("--relative", action="store_true")
    args = ap.parse_args(argv)
    tf = args.timeframe

    w = load_columns()
    prices, clients, sectors = w["prices"], w["clients"], w["sectors"]
    index_daily, rf, rules, extra, ix = w["index_daily"], w["rf"], w["rules"], w["extra"], w["ix"]
    ds = prepare_dataset(prices, clients, rules, sectors=sectors, timeframe=tf).join(
        extra, on=list(KEYS), how="left"
    )
    if args.relative:
        rel = build_relative(prices, clients, extra, sectors=sectors, index_close=ix)
        ds = ds.join(rel, on=list(KEYS), how="left")
    vs = variants(tf, args.relative)
    strategies = {n: (lambda n=n, c=c: _strategy(rules, tf, c, n)) for n, c in vs.items()}
    run = run_backtest(ds, rules, strategies, timeframe=tf, index_daily=index_daily, rf=rf)
    out: dict[str, Any] = {"timeframe": tf, "folds": len(run.folds), "variants": {}}
    groups = REL_GROUPS if args.relative else GROUPS
    coverage = {c: float(ds[c].is_not_null().sum()) / ds.height for g in groups.values() for c in g}
    out["coverage"] = coverage
    # One cut for every variant: the median entry date of the old set's trades. Predictions exist
    # for far more dates than trades (thin early years), so the cut is set by where trading is.
    base = run.strategies["old"].sim.trades
    bcol = "entry_date" if "entry_date" in base.columns else "date"
    cut = base[bcol].sort()[base.height // 2]
    for n, s in run.strategies.items():
        pred = s.predictions.sort("date")
        first, second = pred.filter(pl.col("date") < cut), pred.filter(pl.col("date") >= cut)
        trades = s.sim.trades
        tcol = "entry_date" if "entry_date" in trades.columns else "date"
        out["variants"][n] = {
            "n_features": len(vs[n]),
            "split_date": str(cut),
            "all": {"prob": _prob(pred, ds), "trades": _trade_stats(trades)},
            "first_half": {
                "prob": _prob(first, ds),
                "trades": _trade_stats(trades.filter(pl.col(tcol) < cut)),
            },
            "second_half": {
                "prob": _prob(second, ds),
                "trades": _trade_stats(trades.filter(pl.col(tcol) >= cut)),
            },
            "portfolio": {
                k: s.summary["portfolio"].get(k) for k in ("total_return", "sharpe", "max_drawdown")
            },
        }
    text = json.dumps(out, ensure_ascii=False, indent=2, default=str)
    if args.json:
        args.json.write_text(text, encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
