"""``python -m tmon.backtest.cli``: run the D1 backtest and write reports.

Real data comes from the database; ``--synthetic`` runs on a generated market and is labelled as
such in the report (a pipeline check, not a market result).
"""

from __future__ import annotations

import argparse
from pathlib import Path

from tmon.backtest.baseline import BaselineD1
from tmon.backtest.report import write_reports
from tmon.backtest.runner import prepare_dataset, run_backtest
from tmon.backtest.synthetic import make_market
from tmon.domain.rules import RuleBook
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
    args = ap.parse_args(argv)

    if args.synthetic:
        prices, clients, sectors = make_market(args.days, args.instruments, edge=args.edge)
        rules: RuleBook = seed_rulebook()
    else:
        from tmon.core.db import session_scope
        from tmon.features.store import load_inputs

        with session_scope() as session:
            prices, clients, sectors = load_inputs(session)
            rules = RuleBook.from_session(session)
        if prices.is_empty():
            print("no price data in the database: run the ingestion first (docs/OPEN_QUESTIONS.md)")
            return 2

    ds = prepare_dataset(prices, clients, rules, sectors=sectors, timeframe=args.timeframe)
    run = run_backtest(ds, rules, {"baseline_d1": BaselineD1}, timeframe=args.timeframe)
    title = args.title or f"بک‌تست baseline ({args.timeframe})"
    write_reports(
        run,
        title=title,
        md_path=args.md,
        json_path=args.json,
        html_path=args.html,
        synthetic=args.synthetic,
    )
    for name, s in run.strategies.items():
        print(name, s.summary["trades"], s.summary["portfolio"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
