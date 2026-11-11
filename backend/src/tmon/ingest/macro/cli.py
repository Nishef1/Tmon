"""``python -m tmon.ingest.macro.cli``: free-market prices, fund NAV, inflation CSV import."""

from __future__ import annotations

import argparse
from pathlib import Path

from tmon.core.db import session_scope
from tmon.core.logging import configure_logging
from tmon.ingest.macro.pipeline import import_inflation, run_macro


def main() -> None:
    configure_logging()
    ap = argparse.ArgumentParser(prog="tmon-macro")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("sync", help="tgju USD/gold/coin history and fipiran fund NAV")
    inf = sub.add_parser("inflation", help="import an inflation CSV (see ingest/macro/inflation)")
    inf.add_argument("path", type=Path)
    args = ap.parse_args()
    if args.cmd == "sync":
        print(run_macro())
    else:
        with session_scope() as session:
            print({"rows": import_inflation(session, args.path)})


if __name__ == "__main__":
    main()
