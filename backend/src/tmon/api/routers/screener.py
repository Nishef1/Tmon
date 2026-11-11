from __future__ import annotations

import datetime as dt
import json
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tmon.api.routers.recommendations import instrument_out
from tmon.api.schemas import Reason, ScreenerOut, ScreenerRow, Timeframe
from tmon.core.config import get_settings
from tmon.core.db import get_session
from tmon.features.builder import get_feature_set
from tmon.storage.models import FeatureRow, Instrument, ModelRun, PriceDaily
from tmon.storage.objectstore import get_object_store

router = APIRouter(tags=["screener"])
SessionDep = Annotated[Session, Depends(get_session)]

SortKey = Literal["ev", "p_win", "value", "change_pct", "ind_buy_power", "rsi_14"]
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

    needle = (q or "").strip()
    rows: list[ScreenerRow] = []
    for p, inst in prices:  # one row per symbol on one day
        if needle and needle not in (inst.symbol_fa or "") and needle not in (inst.name_fa or ""):
            continue
        f = feats.get(inst.id, {})
        sc = scores.get(inst.id, {})
        close = None if p.close is None else float(p.close)
        prev = None if p.prev_close is None else float(p.prev_close)
        rows.append(
            ScreenerRow(
                instrument=instrument_out(inst),
                close=close,
                change_pct=(close / prev - 1) if close and prev else None,
                value=None if p.value is None else float(p.value),
                trades=p.trades,
                **{k: _num(f.get(k)) for k in FEATURES},
                p_win=_num(sc.get("p_win")),
                ev=_num(sc.get("ev")),
                p_min=_num(sc.get("p_min")),
                signal=sc.get("signal"),
                reasons=[Reason(**r) for r in sc["reasons"]] if sc.get("reasons") else None,
            )
        )
    rows.sort(key=lambda r: (getattr(r, sort) is None, -(getattr(r, sort) or 0.0)))
    return ScreenerOut(
        timeframe=timeframe,
        prices_date=last,
        scores_date=dt.date.fromisoformat(doc["date"]) if doc else None,
        model_version=doc.get("model_version") if doc else None,
        tier_a_allowed=gate.get("tier_a_allowed"),
        gate_reasons=list(gate.get("reasons") or []),
        total=len(rows),
        rows=rows[:limit],
    )


def _num(v: Any) -> float | None:
    return None if v is None or isinstance(v, bool) else float(v)
