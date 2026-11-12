"""R0 (ADR 0003): reduce survivorship bias by discovering instruments that are no longer in the
market watch (delisted, merged, suspended for good), then loading their history.

``MarketWatchInit`` only lists today's instruments, so a history built from it has no losers that
left. ``GetInstrumentSearch`` matches a substring of the symbol or name and returns at most about
40 rows, so the crawl walks prefixes of growing length and only descends where a query was
saturated. Every query, the saturation of each and the number of unresolved prefixes are kept so
the report can state exactly how complete the sweep was. Nothing here asserts completeness.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import select

from tmon.ingest.http import FetchError
from tmon.ingest.tsetmc import endpoints
from tmon.ingest.tsetmc.parsers import ParseError, normalize_fa
from tmon.ingest.tsetmc.pipeline import Ctx
from tmon.storage.models import Instrument
from tmon.storage.repositories import upsert

log = logging.getLogger(__name__)

ALPHABET = "ابپتثجچحخدذرزژسشصضطظعغفقکگلمنوهی"
SATURATION = 40  # observed cap of the endpoint
MAX_DEPTH = 4


@dataclass(frozen=True)
class SearchHit:
    ins_code: str
    symbol: str
    name: str
    board: str | None


def parse_search(text: str) -> list[SearchHit]:
    try:
        data = json.loads(text)["instrumentSearch"]
    except (ValueError, KeyError, TypeError) as exc:
        raise ParseError(f"unexpected search payload: {exc}") from exc
    return [
        SearchHit(
            ins_code=str(d["insCode"]),
            symbol=str(d.get("lVal18AFC") or ""),
            name=str(d.get("lVal30") or ""),
            board=d.get("flowTitle"),
        )
        for d in data
        if d.get("insCode")
    ]


@dataclass
class CrawlState:
    done: dict[str, int] = field(default_factory=dict)  # query -> rows returned
    frontier: list[str] = field(default_factory=list)
    found: dict[str, dict[str, str | None]] = field(default_factory=dict)  # ins_code -> row

    @classmethod
    def load(cls, path: Path) -> CrawlState:
        if not path.exists():
            return cls(frontier=[a + b for a in ALPHABET for b in ALPHABET])
        raw = json.loads(path.read_text(encoding="utf-8"))
        return cls(raw["done"], raw["frontier"], raw["found"])

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(
                {"done": self.done, "frontier": self.frontier, "found": self.found},
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

    def summary(self) -> dict[str, int]:
        saturated = [q for q, n in self.done.items() if n >= SATURATION]
        unresolved = [q for q in saturated if len(q) >= MAX_DEPTH]
        return {
            "queries": len(self.done),
            "saturated": len(saturated),
            "unresolved_at_max_depth": len(unresolved),
            "frontier_left": len(self.frontier),
            "found": len(self.found),
        }


async def crawl(
    ctx: Ctx, state: CrawlState, path: Path, *, max_queries: int | None = None
) -> CrawlState:
    known = set(ctx.session.scalars(select(Instrument.ins_code)))
    n = 0
    while state.frontier and (max_queries is None or n < max_queries):
        q = state.frontier.pop(0)
        if q in state.done:
            continue
        try:
            text, _ = await ctx.fetch_text(endpoints.instrument_search_url(q), ext="json")
            hits = parse_search(text)
        except (FetchError, ParseError) as exc:
            log.error("search %r failed: %s", q, exc)
            state.frontier.append(q)  # retried at the end of the queue
            n += 1
            continue
        state.done[q] = len(hits)
        for h in hits:
            if h.ins_code not in known and h.ins_code not in state.found:
                state.found[h.ins_code] = {"symbol": h.symbol, "name": h.name, "board": h.board}
        if len(hits) >= SATURATION and len(q) < MAX_DEPTH:
            state.frontier.extend(q + c for c in ALPHABET)
        n += 1
        if n % 50 == 0:
            state.save(path)
            log.info("crawl %s", state.summary())
    state.save(path)
    return state


def is_candidate_symbol(symbol: str) -> bool:
    """Rights issues (suffix ``ح``), and bonds, sukuk and options (digits in the symbol) never
    enter the equity universe; skipping them saves one enrichment request each."""
    return bool(symbol) and not symbol.endswith("ح") and not any(c.isdigit() for c in symbol)


def register_found(ctx: Ctx, state: CrawlState) -> int:
    """Insert discovered instruments (type refined later by enrichment)."""
    rows = []
    for code, r in state.found.items():
        if not is_candidate_symbol(r["symbol"] or ""):
            continue
        itype, matched = ctx.classifier.classify(group_title=None, name_fa=r["name"])
        rows.append(
            {
                "ins_code": code,
                "symbol_fa": normalize_fa(r["symbol"] or ""),
                "name_fa": normalize_fa(r["name"] or ""),
                "market": "IR",
                "instrument_type": itype.value,
                "tags": {"discovered_by": "search"} | ({} if matched else {"unclassified": True}),
                "source_url": endpoints.INSTRUMENT_SEARCH.format(text="*"),
            }
        )
    return upsert(ctx.session, Instrument, rows, conflict_columns=["ins_code"]) if rows else 0


async def load_history(ctx: Ctx, *, limit: int | None = None) -> dict[str, int]:
    """Enrich discovered instruments, keep stocks, load their history and date their exit."""
    from sqlalchemy import func

    from tmon.ingest.tsetmc.pipeline import enrich_instrument, ingest_history
    from tmon.storage.models import PriceDaily

    latest = ctx.session.scalar(select(func.max(PriceDaily.date)))
    todo = [
        i
        for i in ctx.session.scalars(select(Instrument))
        if (i.tags or {}).get("discovered_by") == "search"
        and not (i.tags or {}).get("hist_done")
        and is_candidate_symbol(i.symbol_fa)
    ]
    if limit:
        todo = todo[:limit]
    out = {"processed": 0, "stocks": 0, "bars": 0, "delisted": 0, "failed": 0}
    for ins in todo:
        try:
            await enrich_instrument(ctx, ins)
            tags = dict(ins.tags or {})
            if ctx.classifier.is_tradable(ins.instrument_type):
                s = await ingest_history(ctx, ins, since=None)
                out["stocks"] += 1
                out["bars"] += s["bars"]
                last = ctx.session.scalar(
                    select(func.max(PriceDaily.date)).where(PriceDaily.instrument_id == ins.id)
                )
                if last is not None and latest is not None and (latest - last).days > 10:
                    ins.delisted_at = last
                    out["delisted"] += 1
            tags["hist_done"] = True
            ins.tags = tags
            ctx.session.commit()
            out["processed"] += 1
        except (FetchError, ParseError) as exc:
            ctx.session.rollback()
            out["failed"] += 1
            log.error("history failed for %s: %s", ins.symbol_fa, exc)
    return out


def main() -> None:
    import argparse
    import asyncio

    from tmon.core.db import session_scope
    from tmon.core.logging import configure_logging
    from tmon.ingest.http import PoliteClient
    from tmon.ingest.tsetmc.classify import get_classifier
    from tmon.storage.objectstore import get_object_store

    configure_logging()
    ap = argparse.ArgumentParser()
    ap.add_argument("--state", default="data/delisted-crawl.json")
    ap.add_argument("--max-queries", type=int, default=None)
    ap.add_argument("--skip-crawl", action="store_true")
    ap.add_argument("--history-limit", type=int, default=None)
    a = ap.parse_args()

    async def run() -> None:
        client = PoliteClient()
        try:
            with session_scope() as s:
                ctx = Ctx(s, client, get_object_store(), get_classifier())
                path = Path(a.state)
                st = CrawlState.load(path)
                if not a.skip_crawl:
                    st = await crawl(ctx, st, path, max_queries=a.max_queries)
                print("crawl", st.summary())
                print("registered", register_found(ctx, st))
                s.commit()
                print("history", await load_history(ctx, limit=a.history_limit))
        finally:
            await client.aclose()

    asyncio.run(run())


if __name__ == "__main__":
    main()
