"""Backfill of the monthly activity reports (ن-۳۰) for the liquid basket, in yearly batches.

``python -m tmon.ingest.codal.backfill_monthly`` works in rounds. Round 1 stores, for every basket
symbol, the reports published in the last 12 months; round 2 the 12 months before; round 3 the
12 before that. Each round finishes for all symbols before the next starts, so the newest data
is complete first and a partial run is still usable. The letter index is read once per symbol
(``--letter-pages`` pages of 20). Each letter's ``published_at`` is kept, so a test can use a
figure only from the day Codal published it. The state file records finished symbols per round
and a rerun continues from there. Codal answers HTTP 429 once its quota is used up; the run waits
``--cooldown`` seconds and carries on, giving up after ``--max-waits`` refusals in a row. Nothing
is routed around a refusal or a CAPTCHA (docs/OPEN_QUESTIONS 99).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from tmon.core.db import session_scope
from tmon.core.logging import configure_logging
from tmon.ingest.codal.backfill import basket_symbols
from tmon.ingest.codal.pipeline import CodalCtx, codal_client, sync_letters, sync_reports
from tmon.storage.objectstore import get_object_store

log = logging.getLogger(__name__)
LETTER_CODE = "ن-۳۰"


async def run(
    state_path: Path,
    basket: Path,
    rounds: int,
    letter_pages: int,
    cooldown: int,
    max_waits: int,
    now: datetime,
) -> dict[str, Any]:
    state = json.loads(state_path.read_text("utf-8")) if state_path.exists() else {}
    stats: dict[str, Any] = {"symbols": 0, "reports": 0, "waits": 0, "gave_up_at": None}
    client = codal_client()

    def save() -> None:
        state_path.write_text(json.dumps(state, ensure_ascii=False), "utf-8")

    try:
        with session_scope() as s:
            ctx = CodalCtx(s, client, get_object_store())
            symbols = basket_symbols(basket)
            for rnd in range(1, rounds + 1):
                since = now - timedelta(days=365 * rnd)
                until = now - timedelta(days=365 * (rnd - 1))
                done = set(state.setdefault("rounds", {}).setdefault(str(rnd), []))
                for sym in [x for x in symbols if x not in done]:
                    waits = 0
                    if sym not in state.setdefault("letters", []):
                        while True:
                            out = await sync_letters(
                                ctx,
                                symbol=sym,
                                letter_code=LETTER_CODE,
                                max_pages=letter_pages,
                                stop_at_known=False,
                            )
                            if "stopped_at_page" not in out:
                                break
                            waits += 1
                            stats["waits"] += 1
                            if waits > max_waits:
                                stats["gave_up_at"] = f"round {rnd} {sym}: letters"
                                return stats
                            await asyncio.sleep(cooldown)
                        state["letters"].append(sym)
                        save()
                    while True:
                        out = await sync_reports(
                            ctx, letter_code=LETTER_CODE, symbol=sym, limit=60, since=since
                        )
                        stats["reports"] += out["reports"]
                        if "stopped_at" not in out:
                            break
                        waits += 1
                        stats["waits"] += 1
                        if waits > max_waits:
                            stats["gave_up_at"] = f"round {rnd} {sym}: reports"
                            return stats
                        log.warning("codal refused at %s; waiting %ds", sym, cooldown)
                        await asyncio.sleep(cooldown)
                    done.add(sym)
                    stats["symbols"] += 1
                    state["rounds"][str(rnd)] = sorted(done)
                    save()
                    log.info(
                        "codal monthly round %d (%s..%s) %s ok %s",
                        rnd,
                        since.date(),
                        until.date(),
                        sym,
                        stats,
                    )
    finally:
        await client.aclose()
    return stats


def main() -> None:
    configure_logging()
    ap = argparse.ArgumentParser(prog="tmon-codal-monthly")
    ap.add_argument("--state", default="data/codal-monthly.json")
    ap.add_argument("--basket", default="data/liquid-basket.json")
    ap.add_argument("--rounds", type=int, default=3, help="years back, one round per year")
    ap.add_argument("--letter-pages", type=int, default=6)
    ap.add_argument("--cooldown", type=int, default=900)
    ap.add_argument("--max-waits", type=int, default=6)
    a = ap.parse_args()
    print(
        asyncio.run(
            run(
                Path(a.state),
                Path(a.basket),
                a.rounds,
                a.letter_pages,
                a.cooldown,
                a.max_waits,
                datetime.now(),
            )
        )
    )


if __name__ == "__main__":
    main()
