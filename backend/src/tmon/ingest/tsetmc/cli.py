"""Ingestion CLI (run from a network that can reach TSETMC):

python -m tmon.ingest.tsetmc.cli probe                    # verify endpoints and parsers
python -m tmon.ingest.tsetmc.cli backfill --since 2021-01-01
python -m tmon.ingest.tsetmc.cli eod                      # incremental end-of-day refresh
python -m tmon.ingest.tsetmc.cli intraday [--once]        # live snapshots in trading hours
"""

from __future__ import annotations

import argparse
import sys
from datetime import date

from tmon.core.logging import configure_logging
from tmon.ingest.tsetmc.pipeline import ingest_end_of_day, run_backfill, run_reclassify


def main() -> None:
    configure_logging()
    parser = argparse.ArgumentParser(prog="tmon-ingest")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("probe", help="check reachability, parsers and column mappings")
    bf = sub.add_parser("backfill", help="instrument list + full daily history")
    bf.add_argument("--since", type=date.fromisoformat, default=None)
    bf.add_argument("--limit", type=int, default=None, help="only the first N instruments")
    sub.add_parser("eod", help="incremental end-of-day refresh")
    sub.add_parser("reclassify", help="re-run the type classifier over stored instruments")
    live = sub.add_parser("intraday", help="live price/volume snapshots and order books")
    live.add_argument("--once", action="store_true", help="a single poll")
    live.add_argument("--force", action="store_true", help="ignore trading hours")
    live.add_argument("--follow", action="store_true", help="idle outside hours, resume at open")
    live.add_argument("--interval", type=float, default=None, help="seconds between polls")
    args = parser.parse_args()

    if args.cmd == "probe":
        from tmon.ingest.tsetmc.probe import probe_cli

        sys.exit(probe_cli())
    if args.cmd == "intraday":
        from tmon.ingest.tsetmc.intraday import run_intraday

        print(
            run_intraday(
                once=args.once, force=args.force, follow=args.follow, interval=args.interval
            )
        )
        return
    if args.cmd == "reclassify":
        print(run_reclassify())
        return
    result = (
        run_backfill(since=args.since, limit=args.limit)
        if args.cmd == "backfill"
        else ingest_end_of_day()
    )
    print(result)


if __name__ == "__main__":
    main()
