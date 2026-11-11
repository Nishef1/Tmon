"""``python -m tmon.ingest.tsetmc.cli backfill --since 2021-01-01`` (run from a network that
can reach TSETMC)."""

from __future__ import annotations

import argparse
from datetime import date

from tmon.core.logging import configure_logging
from tmon.ingest.tsetmc.pipeline import ingest_end_of_day, run_backfill


def main() -> None:
    configure_logging()
    parser = argparse.ArgumentParser(prog="tmon-ingest")
    sub = parser.add_subparsers(dest="cmd", required=True)
    bf = sub.add_parser("backfill", help="instrument list + full daily history")
    bf.add_argument("--since", type=date.fromisoformat, default=None)
    bf.add_argument("--limit", type=int, default=None, help="only the first N instruments")
    sub.add_parser("eod", help="incremental end-of-day refresh")
    args = parser.parse_args()
    result = (
        run_backfill(since=args.since, limit=args.limit)
        if args.cmd == "backfill"
        else ingest_end_of_day()
    )
    print(result)


if __name__ == "__main__":
    main()
