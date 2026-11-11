from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tmon.api.routers.recommendations import signal_out
from tmon.api.schemas import HistoryOut, HistorySummary, Timeframe
from tmon.core.db import get_session
from tmon.storage.models import Instrument, Signal

router = APIRouter(tags=["signals"])
SessionDep = Annotated[Session, Depends(get_session)]


@router.get("/signals/history", response_model=HistoryOut)
def signal_history(
    session: SessionDep,
    timeframe: Timeframe = "D1",
    instrument_id: int | None = None,
    outcome: Annotated[str | None, Query(pattern="^(pending|tp|sl|sl_same_day|expiry)$")] = None,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> HistoryOut:
    """Published signals, newest first, each with its realised outcome once the label window
    has closed. ``realized_return`` is the gross barrier return, before costs."""
    scope = [Signal.timeframe == timeframe]
    if instrument_id is not None:
        scope.append(Signal.instrument_id == instrument_id)
    shown = [*scope, Signal.outcome == outcome] if outcome else scope

    total = session.scalar(select(func.count()).select_from(Signal).where(*shown)) or 0
    rows = session.execute(
        select(Signal, Instrument)
        .join(Instrument, Instrument.id == Signal.instrument_id)
        .where(*shown)
        .order_by(Signal.date.desc(), Signal.rank)
        .limit(limit)
        .offset(offset)
    ).all()

    counts = {
        outcome_: n
        for outcome_, n in session.execute(
            select(Signal.outcome, func.count()).where(*scope).group_by(Signal.outcome)
        )
    }
    mean_ret = session.scalar(
        select(func.avg(Signal.realized_return)).where(*scope, Signal.outcome != "pending")
    )
    n_total = sum(counts.values())
    pending = counts.get("pending", 0)
    summary = HistorySummary(
        total=n_total,
        resolved=n_total - pending,
        pending=pending,
        take_profit=counts.get("tp", 0),
        stop_loss=counts.get("sl", 0) + counts.get("sl_same_day", 0),
        expired=counts.get("expiry", 0),
        mean_realized_return=float(mean_ret) if mean_ret is not None else None,
    )
    return HistoryOut(
        timeframe=timeframe,
        items=[signal_out(s, i) for s, i in rows],
        total=int(total),
        limit=limit,
        offset=offset,
        summary=summary,
    )
