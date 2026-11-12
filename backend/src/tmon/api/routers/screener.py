from __future__ import annotations

import datetime as dt
import json
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tmon.api.routers.dashboard import _ranking_doc, decide, fundamental_out
from tmon.api.routers.market import _latest_full
from tmon.api.routers.recommendations import instrument_out
from tmon.api.schemas import Reason, ScreenerOut, ScreenerRow, Timeframe
from tmon.core.config import get_settings
from tmon.core.db import get_session
from tmon.features.builder import get_feature_set
from tmon.ingest.tsetmc.parsers import normalize_fa
from tmon.storage.models import (
    ClientTypeDaily,
    FeatureRow,
    Instrument,
    ModelRun,
    PriceDaily,
    SectorName,
)
from tmon.storage.objectstore import get_object_store

router = APIRouter(tags=["screener"])
SessionDep = Annotated[Session, Depends(get_session)]

SortKey = Literal[
    "ev",
    "p_win",
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


def _latest_scores(
    session: Session, timeframe: str
) -> tuple[dict[str, Any] | None, ModelRun | None]:
    run = session.scalars(
        select(ModelRun)
        .where(ModelRun.timeframe == timeframe)
        .order_by(ModelRun.created_at.desc())
        .limit(1)
    ).first()
    uri = (run.metrics or {}).get("scores_uri") if run else None
    if not uri:
        return None, run
    try:
        data = get_object_store().get(get_settings().minio_artifact_bucket, uri)
    except (FileNotFoundError, KeyError, OSError):
        return None, run
    return json.loads(data), run


@router.get("/screener", response_model=ScreenerOut)
def screener(
    session: SessionDep,
    timeframe: Timeframe = "D1",
    sort: SortKey = "ev",
    q: Annotated[str | None, Query(max_length=64)] = None,
    verdict: Literal["buy", "hold", "sell", "none"] | None = None,
    stocks_only: bool = False,
    limit: Annotated[int, Query(ge=1, le=3000)] = 200,
) -> ScreenerOut:
    """Every symbol that traded on the latest stored day, with its market data, a few features
    and the latest model output for ``timeframe``. The model output is a diagnostic: only rows
    on /recommendations are published recommendations."""
    last = session.scalar(select(func.max(PriceDaily.date)))
    if last is None:
        return ScreenerOut(timeframe=timeframe, total=0, rows=[])
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

    doc, run = _latest_scores(session, timeframe)
    scores = {int(r["instrument_id"]): r for r in (doc or {}).get("rows", [])}
    gate = ((run.metrics or {}).get("gate") or {}) if run else {}

    prior = _prior_volumes(session, last)
    fd = _latest_full(session, ClientTypeDaily.date)
    flows: dict[int, ClientTypeDaily] = {}
    if fd is not None:
        flows = {
            c.instrument_id: c
            for c in session.scalars(select(ClientTypeDaily).where(ClientTypeDaily.date == fd))
        }
    ranking = _ranking_doc()

    sectors = {
        c.strip().zfill(2): normalize_fa(n)
        for c, n in session.execute(select(SectorName.code, SectorName.name))
    }
    needle = normalize_fa((q or "").strip())
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
        sc = scores.get(inst.id, {})
        close = None if p.close is None else float(p.close)
        prev = None if p.prev_close is None else float(p.prev_close)
        c = flows.get(inst.id)
        pcb = c.buy_value_i / c.buy_count_i if c and c.buy_value_i and c.buy_count_i else None
        pcs = c.sell_value_i / c.sell_count_i if c and c.sell_value_i and c.sell_count_i else None
        pv = prior.get(inst.id)
        d = decide(inst, ranking, None)
        fa = fundamental_out(inst, close, sec) if inst.instrument_type == "stock" else None
        counts[d.verdict] = counts.get(d.verdict, 0) + 1
        if verdict and d.verdict != verdict:
            continue
        rows.append(
            ScreenerRow(
                instrument=instrument_out(inst),
                close=close,
                change_pct=(close / prev - 1) if close and prev else None,
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
                rank=d.rank,
                gauge=d.gauge,
                sector_name=sec,
                eps=fa.eps if fa else None,
                pe=fa.pe if fa else None,
                sector_pe=fa.sector_pe if fa else None,
                **{k: _num(f.get(k)) for k in FEATURES},
                p_win=_num(sc.get("p_win")),
                ev=_num(sc.get("ev")),
                p_min=_num(sc.get("p_min")),
                signal=sc.get("signal"),
                reasons=[Reason(**r) for r in sc["reasons"]] if sc.get("reasons") else None,
            )
        )
    sign = 1.0 if sort in ("rank", "pe") else -1.0  # rank 1 and the cheapest P/E come first
    rows.sort(key=lambda r: (getattr(r, sort) is None, sign * (getattr(r, sort) or 0.0)))
    return ScreenerOut(
        timeframe=timeframe,
        prices_date=last,
        scores_date=dt.date.fromisoformat(doc["date"]) if doc else None,
        model_version=doc.get("model_version") if doc else None,
        tier_a_allowed=gate.get("tier_a_allowed"),
        gate_reasons=list(gate.get("reasons") or []),
        verdict_counts=counts,
        flow_date=fd,
        ranking_date=dt.date.fromisoformat(ranking["as_of"]) if ranking else None,
        total=len(rows),
        rows=rows[:limit],
    )


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
