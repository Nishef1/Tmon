from __future__ import annotations

from typing import Annotated, Any

import numpy as np
from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session

from tmon.api.routers.recommendations import latest_run
from tmon.api.schemas import (
    SUPPORTED_TIMEFRAMES,
    CalibrationBlock,
    CalibrationBucket,
    CalibrationOut,
    GateOut,
    Timeframe,
)
from tmon.backtest.metrics import calibration_table
from tmon.core.db import get_session
from tmon.storage.models import Signal

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
        select(Signal.p_win, Signal.outcome).where(
            Signal.timeframe == timeframe, Signal.outcome != "pending"
        )
    ).all()
    live = empty
    if resolved:
        p = np.array([r.p_win for r in resolved], dtype=float)
        y = np.array([1.0 if r.outcome == "tp" else 0.0 for r in resolved])
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
