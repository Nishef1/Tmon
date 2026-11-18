from __future__ import annotations

import datetime as dt
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tmon.api.returns import day_change, period_table
from tmon.api.routers.dashboard import (
    INVITATION_STAGES,
    _ranking_doc,
    _stored_doc,
    _turning_doc,
    decide,
    decision_fields,
    fundamental_out,
)
from tmon.api.routers.market import _latest_full
from tmon.api.schemas import IndustryMapOut, ScreenerOut, ScreenerRow, instrument_out
from tmon.core.db import get_session
from tmon.features.builder import get_feature_set
from tmon.ingest.tsetmc.parsers import normalize_fa
from tmon.storage.models import (
    ClientTypeDaily,
    CorporateEvent,
    FeatureRow,
    Instrument,
    PriceDaily,
    SectorName,
)
from tmon.tools.industry_map import KEY as INDUSTRY_MAP_KEY

router = APIRouter(tags=["screener"])
SessionDep = Annotated[Session, Depends(get_session)]

SortKey = Literal[
    "value",
    "change_pct",
    "ind_buy_power",
    "rsi_14",
    "rank",
    "gauge",
    "power",
    "net_real_value",
    "volume_ratio_30",
    "pe",
    "eps",
]
FEATURES = ("rsi_14", "rel_volume", "atr_14_pct", "ind_buy_power", "ind_net_flow_ratio")


@router.get("/industries/map", response_model=IndustryMapOut)
def industry_map() -> IndustryMapOut:
    """Export-domestic axis, dollar tie, beta and cohesion per industry (PC cycle artifact)."""
    doc = _stored_doc(INDUSTRY_MAP_KEY)
    if doc is None:
        raise HTTPException(404, "industry map not built yet")
    return IndustryMapOut.model_validate(doc)


@router.get("/screener", response_model=ScreenerOut)
def screener(
    session: SessionDep,
    sort: SortKey = "value",
    q: Annotated[str | None, Query(max_length=64)] = None,
    verdict: Literal["buy", "candidate", "hold", "sell", "none"] | None = None,
    stocks_only: bool = False,
    limit: Annotated[int, Query(ge=1, le=3000)] = 200,
) -> ScreenerOut:
    """Every symbol that traded on the latest stored day, with its market data, a few features
    and the verdict of the v2 ranking."""
    last = session.scalar(select(func.max(PriceDaily.date)))
    if last is None:
        return ScreenerOut(total=0, rows=[])
    prices = session.execute(
        select(PriceDaily, Instrument)
        .join(Instrument, Instrument.id == PriceDaily.instrument_id)
        .where(PriceDaily.date == last, PriceDaily.market_halt.is_(False))
    ).all()

    fs = get_feature_set("D1")
    f_date = session.scalar(
        select(func.max(FeatureRow.date)).where(FeatureRow.feature_set_version == fs.key)
    )
    feats: dict[int, dict[str, Any]] = {}
    if f_date is not None:
        for fr in session.scalars(
            select(FeatureRow).where(
                FeatureRow.feature_set_version == fs.key, FeatureRow.date == f_date
            )
        ):
            feats[fr.instrument_id] = fr.values or {}

    prior = _prior_volumes(session, last)
    fd = _latest_full(session, ClientTypeDaily.date)
    flows: dict[int, ClientTypeDaily] = {}
    if fd is not None:
        flows = {
            c.instrument_id: c
            for c in session.scalars(select(ClientTypeDaily).where(ClientTypeDaily.date == fd))
        }
    ranking = _ranking_doc()
    turning = _turning_doc()

    sectors = {
        c.strip().zfill(2): normalize_fa(n)
        for c, n in session.execute(select(SectorName.code, SectorName.name))
    }
    needle = normalize_fa((q or "").strip())
    periods = period_table(session, last)
    meetings = _next_meetings(session, last)
    rows: list[ScreenerRow] = []
    counts: dict[str, int] = {}
    for p, inst in prices:  # one row per symbol on one day
        if stocks_only and inst.instrument_type != "stock":
            continue
        sec = sectors.get((inst.sector_code or "").strip().zfill(2))
        if needle and not any(
            needle in normalize_fa(t or "") for t in (inst.symbol_fa, inst.name_fa, sec)
        ):
            continue
        f = feats.get(inst.id, {})
        close = None if p.close is None else float(p.close)
        prev = None if p.prev_close is None else float(p.prev_close)
        c = flows.get(inst.id)
        pcb = c.buy_value_i / c.buy_count_i if c and c.buy_value_i and c.buy_count_i else None
        pcs = c.sell_value_i / c.sell_count_i if c and c.sell_value_i and c.sell_count_i else None
        pv = prior.get(inst.id)
        d = decide(inst, ranking, None, turning)
        fa = fundamental_out(inst, close, sec) if inst.instrument_type == "stock" else None
        pr = periods.get(inst.id)
        tags = inst.tags or {}
        shares = _num(tags.get("shares"))
        base_vol = _num(tags.get("base_volume"))
        counts[d.verdict] = counts.get(d.verdict, 0) + 1
        if verdict and d.verdict != verdict:
            continue
        rows.append(
            ScreenerRow(
                instrument=instrument_out(inst),
                close=close,
                change_pct=day_change(close, prev),
                value=None if p.value is None else float(p.value),
                trades=p.trades,
                volume_ratio_30=(float(p.volume) / pv) if pv and p.volume else None,
                per_capita_buy=None if pcb is None else float(pcb),
                per_capita_sell=None if pcs is None else float(pcs),
                power=float(pcb / pcs) if pcb and pcs else None,
                net_real_value=(
                    float(c.buy_value_i - c.sell_value_i)
                    if c and c.buy_value_i is not None and c.sell_value_i is not None
                    else None
                ),
                verdict=d.verdict,
                verdict_label=d.label,
                **decision_fields(d),
                rank=d.rank,
                gauge=d.gauge,
                gauge_note=d.headline if d.gauge is None else None,
                sector_name=sec,
                sector_code=(inst.sector_code or "").strip() or None,
                ret_week=pr.ret_week if pr else None,
                ret_month=pr.ret_month if pr else None,
                ret_3m=pr.ret_3m if pr else None,
                ret_year=pr.ret_year if pr else None,
                from_year_high=(close / pr.year_high - 1)
                if pr and pr.year_high and close
                else None,
                from_year_low=(close / pr.year_low - 1) if pr and pr.year_low and close else None,
                volume=None if p.volume is None else float(p.volume),
                market_cap=(shares * close) if shares and close else None,
                shares=shares,
                base_volume=base_vol if base_vol and base_vol > 1 else None,
                meeting_date=meetings.get(inst.id),
                eps=fa.eps if fa else None,
                pe=fa.pe if fa else None,
                sector_pe=fa.sector_pe if fa else None,
                **{k: _num(f.get(k)) for k in FEATURES},
            )
        )
    sign = 1.0 if sort in ("rank", "pe") else -1.0  # rank 1 and the cheapest P/E come first
    rows.sort(key=lambda r: (getattr(r, sort) is None, sign * (getattr(r, sort) or 0.0)))
    return ScreenerOut(
        prices_date=last,
        verdict_counts=counts,
        flow_date=fd,
        ranking_date=dt.date.fromisoformat(ranking["as_of"]) if ranking else None,
        total=len(rows),
        rows=rows[:limit],
    )


def _next_meetings(session: Session, last: dt.date) -> dict[int, dt.date]:
    """Day of the nearest announced assembly per instrument (Codal invitation letters)."""
    rows = session.execute(
        select(CorporateEvent.instrument_id, CorporateEvent.event_date)
        .where(CorporateEvent.stage.in_(INVITATION_STAGES), CorporateEvent.event_date >= last)
        .order_by(CorporateEvent.event_date.desc())
    )
    # descending order: the last write per instrument is the nearest day
    return {iid: day for iid, day in rows if day is not None}


def _num(v: Any) -> float | None:
    return None if v is None or isinstance(v, bool) else float(v)


def _prior_volumes(session: Session, last: dt.date) -> dict[int, float]:
    """Mean volume of up to 30 trading days before ``last``, per instrument (zero days skipped)."""
    days = list(
        session.scalars(
            select(PriceDaily.date)
            .where(PriceDaily.date < last)
            .group_by(PriceDaily.date)
            .order_by(PriceDaily.date.desc())
            .limit(30)
        )
    )
    if not days:
        return {}
    rows = session.execute(
        select(PriceDaily.instrument_id, func.avg(PriceDaily.volume))
        .where(PriceDaily.date.in_(days), PriceDaily.volume > 0)
        .group_by(PriceDaily.instrument_id)
    ).all()
    return {i: float(v) for i, v in rows if v}
