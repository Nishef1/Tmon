"""Official TSETMC index histories (TEDPIX and the equal-weight index): the benchmarks of
ADR 0002 section 6. Codes live in ``config/engine.yaml`` (``benchmarks.indices``)."""

from __future__ import annotations

import logging

from tmon.core.engine_config import get_engine_config
from tmon.ingest.tsetmc import endpoints, parsers
from tmon.ingest.tsetmc.pipeline import Ctx
from tmon.storage.models import MarketIndexDaily
from tmon.storage.repositories import upsert

log = logging.getLogger(__name__)


async def ingest_indices(ctx: Ctx) -> dict[str, int]:
    """Fetch the full daily history of every configured index; returns rows per index name."""
    out: dict[str, int] = {}
    for name, code in get_engine_config().benchmarks.indices.items():
        url = endpoints.index_history_url(code)
        text, fetched_at = await ctx.fetch_text(url, ext="json")
        bars = parsers.parse_index_history(text)
        out[name] = upsert(
            ctx.session,
            MarketIndexDaily,
            [
                {
                    "index_code": code,
                    "date": b.day,
                    "close": b.close,
                    "high": b.high,
                    "low": b.low,
                    "source_url": url,
                    "fetched_at": fetched_at,
                }
                for b in bars
            ],
        )
        ctx.session.commit()
        log.info("index %s (%s): %d days", name, code, out[name])
    return out
