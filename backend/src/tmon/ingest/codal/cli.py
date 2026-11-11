"""Codal ingestion CLI:

python -m tmon.ingest.codal.cli letters --symbol فملی --pages 60   # one company's letter history
python -m tmon.ingest.codal.cli letters --code ن-۵۲ --pages 5       # one letter type, market-wide
python -m tmon.ingest.codal.cli events [--pages 1]                  # newest page per event code
"""

from __future__ import annotations

import argparse

from tmon.core.logging import configure_logging
from tmon.ingest.codal.pipeline import run_events, run_letters


def main() -> None:
    configure_logging()
    parser = argparse.ArgumentParser(prog="tmon-codal")
    sub = parser.add_subparsers(dest="cmd", required=True)
    let = sub.add_parser("letters", help="page through the letter index")
    let.add_argument("--symbol", default=None)
    let.add_argument("--code", default=None, help="letter code, e.g. ن-۵۲")
    let.add_argument("--pages", type=int, default=1)
    let.add_argument("--start-page", type=int, default=1, help="resume a deep backfill")
    let.add_argument("--all", action="store_true", help="do not stop at already-stored pages")
    ev = sub.add_parser("events", help="scan every AGM / capital-increase letter code")
    ev.add_argument("--pages", type=int, default=1)
    args = parser.parse_args()
    if args.cmd == "events":
        print(run_events(max_pages=args.pages))
        return
    print(
        run_letters(
            symbol=args.symbol,
            letter_code=args.code,
            max_pages=args.pages,
            start_page=args.start_page,
            stop_at_known=not args.all,
        )
    )


if __name__ == "__main__":
    main()
