"""Symbol search: by symbol, company name or industry group, with the one-line summary a reader
needs to choose (industry, price, decision, gauge, EPS and P/E)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tmon.api.routers.dashboard import _kind, _ranking_doc, decide, fundamental_out
from tmon.api.routers.recommendations import instrument_out
from tmon.api.schemas import SearchHit, SearchOut
from tmon.core.db import get_session
from tmon.ingest.tsetmc.parsers import normalize_fa
from tmon.storage.models import Instrument, PriceDaily, SectorName

router = APIRouter(tags=["search"])
SessionDep = Annotated[Session, Depends(get_session)]


def _rank(inst: Instrument, needle: str, sector: str | None) -> int | None:
    """Lower is a better match: exact symbol, symbol prefix, symbol part, name, then group."""
    sym = normalize_fa(inst.symbol_fa or "")
    if sym == needle:
        return 0
    if sym.startswith(needle):
        return 1
    if needle in sym:
        return 2
    if needle in normalize_fa(inst.name_fa or ""):
        return 3
    if sector and needle in sector:
        return 4
    return None


@router.get("/search", response_model=SearchOut)
def search(
    session: SessionDep,
    q: Annotated[str, Query(min_length=1, max_length=64)],
    limit: Annotated[int, Query(ge=1, le=50)] = 12,
) -> SearchOut:
    needle = normalize_fa(q)
    sectors = {
        c.strip().zfill(2): normalize_fa(n)
        for c, n in session.execute(select(SectorName.code, SectorName.name))
    }
    found: list[tuple[int, int, Instrument, str | None]] = []
    for inst in session.scalars(select(Instrument).where(Instrument.delisted_at.is_(None))):
        sec = sectors.get((inst.sector_code or "").strip().zfill(2))
        r = _rank(inst, needle, sec)
        if r is not None:
            # stocks before funds, options and bonds at the same match quality
            found.append((r, 0 if inst.instrument_type == "stock" else 1, inst, sec))
    found.sort(key=lambda t: (t[0], t[1], len(t[2].symbol_fa or ""), t[2].id))
    # a symbol that stopped trading comes after live ones of the same match quality; only the
    # best candidates are checked, because a full scan of one day's prices is slow
    head = found[: limit * 5]
    last = session.scalar(select(func.max(PriceDaily.date)))
    traded: set[int] = set()
    if last is not None and head:
        traded = set(
            session.scalars(
                select(PriceDaily.instrument_id).where(
                    PriceDaily.instrument_id.in_([t[2].id for t in head]),
                    PriceDaily.date == last,
                    PriceDaily.market_halt.is_(False),
                )
            )
        )
    head.sort(key=lambda t: (t[0], t[1], t[2].id not in traded, len(t[2].symbol_fa or ""), t[2].id))
    ranking = _ranking_doc()
    hits: list[SearchHit] = []
    for _, _, inst, sec in head[:limit]:
        p = session.scalars(
            select(PriceDaily)
            .where(PriceDaily.instrument_id == inst.id)
            .order_by(PriceDaily.date.desc())
            .limit(1)
        ).first()
        close = float(p.close) if p and p.close is not None else None
        prev = float(p.prev_close) if p and p.prev_close else None
        d = decide(inst, ranking, None)
        fa = fundamental_out(inst, close, sec) if inst.instrument_type == "stock" else None
        hits.append(
            SearchHit(
                instrument=instrument_out(inst),
                sector_name=sec,
                kind="سهام" if inst.instrument_type == "stock" else _kind(inst.instrument_type),
                close=close,
                change_pct=(close / prev - 1) if close and prev else None,
                verdict=d.verdict,
                verdict_label=d.label,
                gauge=d.gauge,
                eps=fa.eps if fa else None,
                pe=fa.pe if fa else None,
                sector_pe=fa.sector_pe if fa else None,
            )
        )
    return SearchOut(query=q, total=len(found), hits=hits)
