from __future__ import annotations

from typing import Annotated, Any

import numpy as np
from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tmon.api.routers.recommendations import latest_run
from tmon.api.schemas import (
    SUPPORTED_TIMEFRAMES,
    CalibrationBlock,
    CalibrationBucket,
    CalibrationOut,
    GateOut,
    LiveAccuracyOut,
    LiveDayOut,
    Timeframe,
)
from tmon.backtest.metrics import calibration_table
from tmon.core.db import get_session
from tmon.engine.gating import BRIER_DEGRADATION_LIMIT, BRIER_RECENT_DAYS, brier_degraded
from tmon.engine.service import recent_resolved, signal_hit
from tmon.storage.models import Signal, SignalNote

router = APIRouter(tags=["metrics"])
SessionDep = Annotated[Session, Depends(get_session)]


def _block(prob: dict[str, Any] | None) -> CalibrationBlock | None:
    if not prob or "auc" not in prob:
        return None
    return CalibrationBlock(
        n=prob["n"],
        base_rate=prob.get("base_rate"),
        auc=prob.get("auc"),
        brier=prob.get("brier"),
        brier_base_rate=prob.get("brier_base_rate"),
        brier_skill=prob.get("brier_skill"),
        buckets=[CalibrationBucket(**b) for b in prob.get("calibration", [])],
    )


def _model_probabilistic(metrics: dict[str, Any]) -> dict[str, Any] | None:
    """The probabilistic summary of the model strategy (the one that carries ``p_win``)."""
    for summary in (metrics.get("backtest") or {}).values():
        if isinstance(summary, dict) and summary.get("probabilistic"):
            return dict(summary["probabilistic"])
    return None


@router.get("/metrics/calibration", response_model=CalibrationOut)
def calibration(session: SessionDep, timeframe: Timeframe = "D1") -> CalibrationOut:
    """Calibration of the latest model: out-of-sample (walk-forward backtest) and live (the
    signals actually published and since resolved)."""
    empty = CalibrationBlock(n=0)
    if timeframe not in SUPPORTED_TIMEFRAMES:
        return CalibrationOut(
            timeframe=timeframe,
            supported=False,
            model_version=None,
            trained_through=None,
            backtest=None,
            live=empty,
            gate=None,
            warnings=["مدل این تایم‌فریم در فاز ۱ ساخته نشده است."],
        )
    resolved = session.execute(
        select(Signal.p_win, Signal.outcome, Signal.hit).where(
            Signal.timeframe == timeframe, Signal.outcome != "pending"
        )
    ).all()
    live = empty
    if resolved:
        p = np.array([r.p_win for r in resolved], dtype=float)
        y = np.array([signal_hit(r.outcome, r.hit) for r in resolved])
        live = CalibrationBlock(
            n=len(resolved),
            base_rate=float(y.mean()),
            brier=float(np.mean((p - y) ** 2)),
            buckets=[CalibrationBucket(**b) for b in calibration_table(p, y, 10)],
        )
    run = latest_run(session, timeframe)
    if run is None:
        return CalibrationOut(
            timeframe=timeframe,
            supported=True,
            model_version=None,
            trained_through=None,
            backtest=None,
            live=live,
            gate=None,
            warnings=["هنوز مدلی آموزش داده نشده است."],
        )
    m = run.metrics or {}
    g = m.get("gate")
    return CalibrationOut(
        timeframe=timeframe,
        supported=True,
        model_version=run.version,
        trained_through=(run.train_window or {}).get("end"),
        backtest=_block(_model_probabilistic(m)),
        live=live,
        gate=GateOut(**g) if g else None,
        warnings=[str(w) for w in m.get("warnings", [])],
    )


@router.get("/metrics/live", response_model=LiveAccuracyOut)
def live_accuracy(session: SessionDep, timeframe: Timeframe = "D1") -> LiveAccuracyOut:
    """Live accuracy of published signals by signal date, and the state of the Brier kill
    switch (docs/10 section 9) and defensive mode (section 10)."""
    rows = session.execute(
        select(Signal.date, Signal.p_win, Signal.outcome, Signal.hit).where(
            Signal.timeframe == timeframe
        )
    ).all()
    done = [r for r in rows if r.outcome != "pending"]
    by_day: dict[Any, list[tuple[float, float]]] = {}
    for r in done:
        by_day.setdefault(r.date, []).append((r.p_win, signal_hit(r.outcome, r.hit)))
    days = []
    for d in sorted(by_day, reverse=True):
        p = np.array([a for a, _ in by_day[d]])
        y = np.array([b for _, b in by_day[d]])
        days.append(
            LiveDayOut(
                date=d,
                n=int(p.size),
                hits=int(y.sum()),
                mean_p=float(p.mean()),
                brier=float(np.mean((p - y) ** 2)),
            )
        )
    run = latest_run(session, timeframe)
    prob = _model_probabilistic(run.metrics or {}) if run else None
    bt = prob.get("brier") if prob else None
    rp, ry = recent_resolved(session, timeframe)
    note = session.scalars(
        select(SignalNote).where(SignalNote.timeframe == timeframe).order_by(SignalNote.date.desc())
    ).first()
    y_all = np.array([signal_hit(r.outcome, r.hit) for r in done])
    return LiveAccuracyOut(
        timeframe=timeframe,
        as_of=session.scalar(select(func.max(Signal.date)).where(Signal.timeframe == timeframe)),
        resolved=len(done),
        pending=len(rows) - len(done),
        hit_rate=float(y_all.mean()) if done else None,
        mean_p=float(np.mean([r.p_win for r in done])) if done else None,
        backtest_brier=bt,
        recent_days=BRIER_RECENT_DAYS,
        recent_n=int(rp.size),
        recent_brier=float(np.mean((rp - ry) ** 2)) if rp.size else None,
        degradation_limit=BRIER_DEGRADATION_LIMIT,
        kill_switch_active=bt is not None and brier_degraded(rp, ry, bt),
        defensive_mode=note.defensive_mode if note else None,
        days=days,
    )
