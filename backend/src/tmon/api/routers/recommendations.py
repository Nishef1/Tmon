from __future__ import annotations

from datetime import date
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from tmon.api.schemas import (
    SUPPORTED_TIMEFRAMES,
    GateOut,
    InstrumentOut,
    Reason,
    RecommendationsOut,
    RunOut,
    SignalOut,
    Timeframe,
)
from tmon.core.db import get_session
from tmon.storage.models import Instrument, ModelRun, Signal, SignalNote

router = APIRouter(tags=["recommendations"])
SessionDep = Annotated[Session, Depends(get_session)]

NOT_SUPPORTED = "این تایم‌فریم پشتیبانی نمی‌شود."
NO_RUN = "هنوز اجرایی برای این تاریخ ثبت نشده است."


def instrument_out(i: Instrument) -> InstrumentOut:
    return InstrumentOut(
        id=i.id,
        symbol=i.symbol_fa,
        name=i.name_fa,
        sector_code=i.sector_code,
        instrument_type=i.instrument_type,
    )


def signal_out(s: Signal, inst: Instrument) -> SignalOut:
    return SignalOut(
        id=s.id,
        date=s.date,
        timeframe=s.timeframe,
        rank=s.rank,
        instrument=instrument_out(inst),
        entry_price=float(s.entry_price),
        entry_rule=s.entry_rule,
        take_profit=float(s.take_profit),
        stop_loss=float(s.stop_loss),
        horizon_days=s.horizon_days,
        p_win=s.p_win,
        ev=s.ev,
        confidence_tier=s.confidence_tier,
        position_pct=s.position_pct,
        top_reasons=[Reason(**r) for r in (s.top_reasons or [])],
        risks=[str(r) for r in (s.risks or [])],
        model_version=s.model_version,
        data_snapshot_id=s.data_snapshot_id,
        outcome=s.outcome,
        realized_return=s.realized_return,
        outcome_date=s.outcome_date,
    )


def latest_run(session: Session, timeframe: str, version: str | None = None) -> ModelRun | None:
    q = select(ModelRun).where(ModelRun.timeframe == timeframe)
    if version:
        q = q.where(ModelRun.version == version)
    return session.scalars(q.order_by(ModelRun.created_at.desc())).first()


def gate_of(session: Session, timeframe: str, version: str | None = None) -> GateOut | None:
    run = latest_run(session, timeframe, version) or latest_run(session, timeframe)
    g: dict[str, Any] | None = (run.metrics or {}).get("gate") if run else None
    return GateOut(**g) if g else None


@router.get("/recommendations", response_model=RecommendationsOut)
def recommendations(
    session: SessionDep,
    timeframe: Timeframe = "D1",
    date_: Annotated[date | None, Query(alias="date")] = None,
) -> RecommendationsOut:
    """The day's ranked list, or an explicit "no recommendation" (the normal outcome whenever
    nothing passes the thresholds). ``date`` defaults to the latest day with a recorded run."""
    if timeframe not in SUPPORTED_TIMEFRAMES:
        return RecommendationsOut(
            timeframe=timeframe,
            supported=False,
            date=None,
            available_dates=[],
            no_recommendation=True,
            message=NOT_SUPPORTED,
            signals=[],
        )
    dates = list(
        session.scalars(
            select(SignalNote.date)
            .where(SignalNote.timeframe == timeframe)
            .distinct()
            .order_by(SignalNote.date.desc())
            .limit(60)
        )
    )
    day = date_ or (dates[0] if dates else None)
    if day is None:
        return RecommendationsOut(
            timeframe=timeframe,
            supported=True,
            date=None,
            available_dates=dates,
            no_recommendation=True,
            message=NO_RUN,
            signals=[],
        )
    note = session.scalars(
        select(SignalNote)
        .where(SignalNote.timeframe == timeframe, SignalNote.date == day)
        .order_by(SignalNote.created_at.desc())
    ).first()
    rows = session.execute(
        select(Signal, Instrument)
        .join(Instrument, Instrument.id == Signal.instrument_id)
        .where(Signal.timeframe == timeframe, Signal.date == day)
        .order_by(Signal.rank)
    ).all()
    signals = [signal_out(s, i) for s, i in rows]
    run = (
        RunOut(
            date=note.date,
            model_version=note.model_version,
            data_snapshot_id=note.data_snapshot_id,
            n_candidates=int(note.n_candidates),
            n_recommended=note.n_recommended,
            defensive_mode=note.defensive_mode,
            message=note.message,
            created_at=note.created_at,
        )
        if note
        else None
    )
    message = (
        f"{len(signals)} توصیه" if signals else (note.message if note and note.message else NO_RUN)
    )
    return RecommendationsOut(
        timeframe=timeframe,
        supported=True,
        date=day,
        available_dates=dates,
        no_recommendation=not signals,
        message=message or NO_RUN,
        run=run,
        gate=gate_of(session, timeframe, note.model_version if note else None),
        signals=signals,
    )
