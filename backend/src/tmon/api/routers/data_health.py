"""Completeness of the stored data, and the button that asks for the gaps to be filled."""

from __future__ import annotations

import datetime as dt
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy.orm import Session

from tmon.core.db import get_session
from tmon.tools import data_health as dh

router = APIRouter(tags=["meta"])
SessionDep = Annotated[Session, Depends(get_session)]


class IssueOut(BaseModel):
    kind: str
    date: dt.date
    have: int | None
    expected: int | None
    first_seen: dt.date | None = None


class DayOut(BaseModel):
    date: dt.date
    prices: int
    flows: int
    price_ref: int | None
    flow_ref: int | None
    prices_ok: bool
    flows_ok: bool


class StepOut(BaseModel):
    name: str
    status: str
    detail: str


class RefillOut(BaseModel):
    state: str
    started_at: dt.datetime | None = None
    finished_at: dt.datetime | None = None
    message: str = ""
    steps: list[StepOut] = []
    open_gaps: int | None = None


class CycleStepOut(BaseModel):
    name: str
    ok: bool
    seconds: float


class CycleOut(BaseModel):
    day: dt.date
    ok: bool
    eod_mode: str
    total_seconds: float
    finished_at: dt.datetime
    steps: list[CycleStepOut]


class HealthOut(BaseModel):
    checked_at: dt.datetime
    newest: dt.date | None
    complete: bool
    issues: list[IssueOut]
    days: list[DayOut]
    refill: RefillOut | None
    last_cycle: CycleOut | None = None


def _refill() -> RefillOut | None:
    doc = dh.refill_state()
    return RefillOut(**doc) if doc else None


@router.get("/data-health", response_model=HealthOut)
def data_health(session: SessionDep) -> HealthOut:
    r = dh.check(session)
    note = {(g["kind"], g["date"]): g for g in (dh.read_note() or {}).get("gaps", [])}
    issues = [
        IssueOut(
            kind=i.kind,
            date=i.date,
            have=i.have,
            expected=i.expected,
            first_seen=(note.get((i.kind, i.date.isoformat())) or {}).get("first_seen"),
        )
        for i in r["issues"]
    ]
    return HealthOut(
        checked_at=r["checked_at"],
        newest=r["newest"],
        complete=not issues,
        issues=issues,
        days=[DayOut(**d.__dict__) for d in r["days"]],
        refill=_refill(),
        last_cycle=CycleOut(**cycles[0]) if (cycles := dh.read_timings()) else None,
    )


@router.post("/data-health/refill", response_model=RefillOut)
def refill() -> RefillOut:
    """Start the refill unless one is already running. The job is its own process; poll
    ``GET /data-health`` for ``refill.state``."""
    cur: dict[str, Any] | None = dh.refill_state()
    if cur and cur.get("state") == "running":
        return RefillOut(**cur)
    if dh.cycle_running():
        return RefillOut(**dh.BLOCKED)
    dh.start_in_background()
    return RefillOut(state="running", message="شروع شد…")
