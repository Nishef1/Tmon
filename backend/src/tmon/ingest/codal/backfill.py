"""Codal coverage backfill: the full letter index of every equity issuer, resumable.

``python -m tmon.ingest.codal.backfill`` walks every distinct stock symbol (listed or delisted),
or with ``--basket`` only the liquid basket (most liquid first),
pages its letter index to the end and records the symbol in a state file when its last page was
a short one. Codal answers HTTP 429 once its request quota is used up; the run then waits
``--cooldown`` seconds and resumes the same page, giving up after ``--max-waits`` consecutive
refusals (the state file keeps the position, so a later run continues). The index is read at
the site's own polite rate (``codal_min_interval_seconds``); nothing is routed around a refusal.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from tmon.core.db import session_scope
from tmon.core.logging import configure_logging
from tmon.domain.enums import InstrumentType
from tmon.ingest.codal.pipeline import CodalCtx, codal_client, sync_letters
from tmon.storage.models import Instrument
from tmon.storage.objectstore import get_object_store

log = logging.getLogger(__name__)
PAGE_CAP = 400  # 8 000 letters per issuer is far above any real issuer


def basket_symbols(path: Path) -> list[str]:
    """Symbols written by ``tmon.tools.liquid_basket`` (most liquid first)."""
    return [str(x) for x in json.loads(path.read_text("utf-8"))["symbols"]]


def stock_symbols(session: Session) -> list[str]:
    rows = session.execute(
        select(Instrument.symbol_fa)
        .where(Instrument.instrument_type == InstrumentType.STOCK.value)
        .order_by(Instrument.id)
    ).all()
    seen: dict[str, None] = {}
    for (sym,) in rows:
        seen.setdefault(sym, None)
    return list(seen)


async def run(
    state_path: Path,
    cooldown: int,
    max_waits: int,
    limit: int | None,
    basket: Path | None = None,
) -> dict[str, Any]:
    state = json.loads(state_path.read_text("utf-8")) if state_path.exists() else {}
    done: set[str] = set(state.get("done", []))
    stats: dict[str, Any] = {"symbols": 0, "pages": 0, "letters": 0, "waits": 0, "gave_up_at": None}
    client = codal_client()
    try:
        with session_scope() as s:
            ctx = CodalCtx(s, client, get_object_store())
            order = basket_symbols(basket) if basket else stock_symbols(s)
            todo = [x for x in order if x not in done]
            if limit:
                todo = todo[:limit]
            log.info("codal backfill: %d symbols to go, %d done", len(todo), len(done))
            for sym in todo:
                page, waits = state.get("resume", {}).get(sym, 1), 0
                while True:
                    out = await sync_letters(
                        ctx, symbol=sym, max_pages=PAGE_CAP, start_page=page, stop_at_known=False
                    )
                    stats["pages"] += out["pages"]
                    stats["letters"] += out["letters"]
                    if "stopped_at_page" not in out:
                        break
                    page = out["stopped_at_page"]
                    state.setdefault("resume", {})[sym] = page
                    state["done"] = sorted(done)
                    state_path.write_text(json.dumps(state, ensure_ascii=False), "utf-8")
                    waits += 1
                    stats["waits"] += 1
                    if waits > max_waits:
                        stats["gave_up_at"] = f"{sym}:{page}"
                        return stats
                    log.warning("codal refused at %s page %d; waiting %ds", sym, page, cooldown)
                    await asyncio.sleep(cooldown)
                done.add(sym)
                state.get("resume", {}).pop(sym, None)
                stats["symbols"] += 1
                state["done"] = sorted(done)
                state_path.write_text(json.dumps(state, ensure_ascii=False), "utf-8")
                log.info("codal backfill %s ok %s", sym, stats)
    finally:
        await client.aclose()
    return stats


def main() -> None:
    configure_logging()
    ap = argparse.ArgumentParser(prog="tmon-codal-backfill")
    ap.add_argument("--state", default="data/codal-backfill.json")
    ap.add_argument("--cooldown", type=int, default=900)
    ap.add_argument("--max-waits", type=int, default=6)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--basket", default=None, help="liquid_basket JSON; only its symbols")
    a = ap.parse_args()
    basket = Path(a.basket) if a.basket else None
    print(asyncio.run(run(Path(a.state), a.cooldown, a.max_waits, a.limit, basket)))


if __name__ == "__main__":
    main()
