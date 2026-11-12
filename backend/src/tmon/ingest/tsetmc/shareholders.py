"""Major shareholders of every stock that traded lately (one request per instrument)."""

from __future__ import annotations

import logging

from sqlalchemy import delete, select

from tmon.ingest.http import FetchError
from tmon.ingest.tsetmc import endpoints, parsers
from tmon.ingest.tsetmc.pipeline import Ctx
from tmon.storage.models import Instrument, PriceDaily, Shareholder
from tmon.storage.repositories import upsert

log = logging.getLogger(__name__)


async def ingest_shareholders(ctx: Ctx, *, limit: int | None = None) -> dict[str, int]:
    """Replace the stored shareholder list of each stock with a price bar. A failed fetch keeps the
    previous list; an empty reply clears it (TSETMC lists none)."""
    have_bars = set(ctx.session.scalars(select(PriceDaily.instrument_id).distinct()))
    todo = [
        i
        for i in ctx.session.scalars(
            select(Instrument).where(Instrument.instrument_type == "stock").order_by(Instrument.id)
        )
        if i.id in have_bars
    ]
    if limit:
        todo = todo[:limit]
    out = {"todo": len(todo), "with_holders": 0, "empty": 0, "rows": 0, "failed": 0}
    for n, ins in enumerate(todo, 1):
        url = endpoints.shareholders_url(ins.ins_code)
        try:
            text, fetched_at = await ctx.fetch_text(url, ext="json")
            rows = parsers.parse_shareholders(text)
        except (FetchError, parsers.ParseError) as exc:
            ctx.session.rollback()
            out["failed"] += 1
            log.warning("shareholders of %s failed: %s", ins.symbol_fa, exc)
            continue
        ctx.session.execute(delete(Shareholder).where(Shareholder.instrument_id == ins.id))
        upsert(
            ctx.session,
            Shareholder,
            [
                {
                    "instrument_id": ins.id,
                    "holder_key": r.holder_key,
                    "name": r.name,
                    "shares": r.shares,
                    "percent": r.percent,
                    "change_amount": r.change_amount,
                    "source_url": url,
                    "fetched_at": fetched_at,
                }
                for r in rows
            ],
        )
        ctx.session.commit()
        out["rows"] += len(rows)
        out["with_holders" if rows else "empty"] += 1
        if n % 50 == 0:
            log.info("shareholders %d/%d %s", n, len(todo), out)
    return out
