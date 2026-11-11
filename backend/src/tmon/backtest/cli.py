"""``python -m tmon.backtest.cli``: run the D1 backtest and write reports.

Real data comes from the database; ``--synthetic`` runs on a generated market and is labelled as
such in the report (a pipeline check, not a market result).
"""

from __future__ import annotations

import argparse
from pathlib import Path

import polars as pl

from tmon.backtest.baseline import BaselineD1
from tmon.backtest.report import write_reports
from tmon.backtest.runner import (
    StrategyFactory,
    prepare_dataset,
    prepare_label_sets,
    run_backtest,
)
from tmon.backtest.synthetic import make_market
from tmon.domain.rules import RuleBook
from tmon.engine.gating import evaluate_gate
from tmon.models.lgbm import LightGBMStrategy
from tmon.storage.seed import seed_rulebook


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="tmon-backtest")
    ap.add_argument("--timeframe", default="D1")
    ap.add_argument("--synthetic", action="store_true", help="generated market, not real data")
    ap.add_argument("--edge", type=float, default=0.0, help="planted edge (synthetic only)")
    ap.add_argument("--days", type=int, default=900)
    ap.add_argument("--instruments", type=int, default=40)
    ap.add_argument("--md", type=Path, help="metrics-only Markdown summary (docs/reports)")
    ap.add_argument("--json", type=Path)
    ap.add_argument("--html", type=Path, help="full HTML report (not committed)")
    ap.add_argument("--title", default=None)
    ap.add_argument("--model", action="store_true", help="also evaluate the LightGBM engine")
    ap.add_argument(
        "--diag", action="store_true", help="also run the diagnostic (no thresholds) variant"
    )
    ap.add_argument(
        "--no-grid",
        action="store_true",
        help="fixed default barrier pair instead of the nested grid",
    )
    args = ap.parse_args(argv)

    if args.synthetic:
        prices, clients, sectors = make_market(args.days, args.instruments, edge=args.edge)
        rules: RuleBook = seed_rulebook()
        index_daily: pl.DataFrame | None = None
        rf: pl.DataFrame | None = None
    else:
        from tmon.core.db import session_scope
        from tmon.features.store import load_benchmark_inputs, load_inputs

        with session_scope() as session:
            prices, clients, sectors = load_inputs(session)
            index_daily, rf = load_benchmark_inputs(session)
            rules = RuleBook.from_session(session)
        if prices.is_empty():
            print("no price data in the database: run the ingestion first (docs/OPEN_QUESTIONS.md)")
            return 2

    ds = prepare_dataset(prices, clients, rules, sectors=sectors, timeframe=args.timeframe)
    tf = args.timeframe
    strategies: dict[str, StrategyFactory] = {
        "baseline_d1": lambda: BaselineD1(rules=rules, timeframe=tf)
    }
    if args.model:
        strategies["lgbm_d1"] = lambda: LightGBMStrategy(rules, timeframe=args.timeframe)
        if args.diag:
            strategies["lgbm_diag"] = lambda: LightGBMStrategy(
                rules, timeframe=args.timeframe, enforce_thresholds=False, name="lgbm_diag"
            )
    label_sets = None if args.no_grid else prepare_label_sets(prices, rules, timeframe=tf)
    run = run_backtest(
        ds,
        rules,
        strategies,
        timeframe=tf,
        label_sets=label_sets,
        index_daily=index_daily,
        rf=rf,
    )
    title = args.title or (
        f"بک‌تست مدل در برابر baseline ({args.timeframe})"
        if args.model
        else f"بک‌تست baseline ({args.timeframe})"
    )
    gate = None
    notes: list[str] = []
    if args.model and "lgbm_d1" in run.strategies:
        gate = evaluate_gate(
            run.strategies["lgbm_d1"].summary,
            run.strategies["baseline_d1"].summary if "baseline_d1" in run.strategies else None,
        ).to_dict()
    if args.model:
        notes.append(
            "lgbm_d1 = موتور با آستانه‌های ADR 0002 "
            "(p_min = max(سربه‌سر + ۰٫۰۵، ۰٫۳۵)، EV خالص ≥ ۰٫۵٪، حداقل ۲۰۰ نمونه در سطل). "
            "جفت مانع (k_tp, k_sl) در هر پنجرهٔ آموزش از شبکه انتخاب می‌شود. "
            "lgbm_diag (فقط با --diag) = تشخیصی: هر ردیف با EV مثبت و سطل پر؛ "
            "هرگز منتشر نمی‌شود."
        )
    write_reports(
        run,
        title=title,
        md_path=args.md,
        json_path=args.json,
        html_path=args.html,
        synthetic=args.synthetic,
        challenger="lgbm_d1" if args.model else None,
        gate=gate,
        notes=notes,
    )
    for name, s in run.strategies.items():
        print(name, s.summary["trades"], s.summary["portfolio"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
