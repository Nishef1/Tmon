"""Bought symbols and the check of the frozen forecast against the candles that followed.

The user marks a symbol as bought; the model forecast of that day (score, verdict per holding
period, the range of the next candles) is stored as it was. Each later request compares it with
the adjusted closes after the snapshot day, so every miss is visible and can be studied.
"""

from __future__ import annotations

import datetime as dt
from typing import Annotated, Any, cast

import polars as pl
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import Table, select
from sqlalchemy.orm import Session

from tmon.api.routers.dashboard import dashboard
from tmon.api.schemas import ApiModel
from tmon.core.db import get_session
from tmon.features.adjustment import apply_adjustments
from tmon.storage.models import Base, Instrument, PriceDaily, TrackedPick

router = APIRouter(tags=["picks"])
SessionDep = Annotated[Session, Depends(get_session)]

COST = 0.017512  # round trip: commissions and tax
HORIZON_DAYS = {"D1": 1, "W1": 5, "M1": 20, "Q1": 60}
HORIZON_FA = {"D1": "فردا", "W1": "یک هفته", "M1": "یک ماه", "Q1": "سه ماه"}


class PickIn(BaseModel):
    instrument_id: int
    entered_on: dt.date | None = None
    paid_price: float | None = Field(default=None, gt=0)
    note: str | None = Field(default=None, max_length=300)


class CandleCheck(ApiModel):
    """The forecast for ``h`` candles after the snapshot day next to what happened."""

    h: int
    up: float | None = None  # forecast share of cases above the entry close
    q10: float | None = None
    q50: float | None = None
    q90: float | None = None
    actual: float | None = None  # realized return, None while the candle has not happened
    date: dt.date | None = None
    status: str = "pending"  # pending | inside | above | below
    direction_ok: bool | None = None  # actual > 0 agrees with up > 0.5


class VerdictCheck(ApiModel):
    key: str
    label: str
    verdict: str
    verdict_label: str
    days: int
    actual: float | None = None
    net: float | None = None  # actual minus the round-trip cost
    right: bool | None = None  # buy: net > 0; wait or sell: net <= 0


class PickOut(ApiModel):
    id: int
    instrument_id: int
    symbol: str
    name: str
    entered_on: dt.date
    as_of: dt.date  # the data day the forecast was frozen on
    paid_price: float | None
    note: str | None
    last_date: dt.date | None
    last_return: float | None  # since the snapshot close
    gauge: float | None
    candles: list[CandleCheck]
    verdicts: list[VerdictCheck]
    resolved: int  # candle forecasts that have happened
    inside: int  # of those, how many fell in the 80% range
    direction_ok: int


def _ensure(session: Session) -> None:
    Base.metadata.create_all(session.get_bind(), tables=[cast(Table, TrackedPick.__table__)])


def _closes(session: Session, instrument_id: int) -> list[tuple[dt.date, float]]:
    """Adjusted closes, oldest first, so a split or capital increase never fakes a move."""
    rows = list(
        session.scalars(
            select(PriceDaily)
            .where(PriceDaily.instrument_id == instrument_id)
            .order_by(PriceDaily.date)
        )
    )
    if not rows:
        return []
    fields = ["open", "high", "low", "last", "close", "prev_close", "volume", "value"]
    data: dict[str, list[Any]] = {"instrument_id": [], "date": [], **{f: [] for f in fields}}
    for r in rows:
        data["instrument_id"].append(r.instrument_id)
        data["date"].append(r.date)
        for f in fields:
            v = getattr(r, f)
            data[f].append(None if v is None else float(v))
    raw = pl.DataFrame(
        data,
        schema={
            "instrument_id": pl.Int64,
            "date": pl.Date,
            **dict.fromkeys(fields, pl.Float64),
        },
    )
    adj = apply_adjustments(raw)
    return [(d, c) for d, c in adj.select("date", "adj_close").iter_rows() if c is not None]


def _snapshot(session: Session, instrument_id: int) -> dict[str, Any]:
    d = dashboard(instrument_id, session)
    odds = d.entry.own if d.entry else []
    as_of = (
        d.entry.as_of.isoformat() if d.entry else (d.decision.as_of or dt.date.today().isoformat())
    )
    return {
        "as_of": as_of,
        "gauge": d.decision.gauge,
        "verdict": d.decision.verdict,
        "horizons": [
            {"key": h.key, "label": h.label, "verdict": h.verdict, "verdict_label": h.verdict_label}
            for h in d.decision.horizons
        ],
        "candles": [
            {"h": o.h, "up": o.up, "q10": o.q10, "q50": o.q50, "q90": o.q90}
            for o in odds
            if o.q10 is not None and o.q90 is not None
        ],
    }


def _check(p: TrackedPick, inst: Instrument, closes: list[tuple[dt.date, float]]) -> PickOut:
    snap = p.snapshot
    as_of = dt.date.fromisoformat(snap["as_of"])
    base_i = next((i for i, (d, _) in enumerate(closes) if d >= as_of), None)
    has_base = base_i is not None and closes[base_i][0] == as_of
    base = closes[base_i][1] if has_base and base_i is not None else None
    after = closes[(base_i or 0) + (1 if has_base else 0) :] if base_i is not None else []

    def at(k: int) -> tuple[float | None, dt.date | None]:
        if base is None or k > len(after):
            return None, None
        d, c = after[k - 1]
        return c / base - 1, d

    candles: list[CandleCheck] = []
    for c in snap.get("candles", []):
        a, d = at(c["h"])
        status = "pending"
        ok: bool | None = None
        if a is not None:
            status = "inside" if c["q10"] <= a <= c["q90"] else "above" if a > c["q90"] else "below"
            ok = (a > 0) == ((c.get("up") or 0.5) > 0.5)
        candles.append(CandleCheck(**c, actual=a, date=d, status=status, direction_ok=ok))

    verdicts: list[VerdictCheck] = []
    for h in snap.get("horizons", []):
        days = HORIZON_DAYS.get(h["key"])
        if days is None:
            continue
        a, _ = at(days)
        net = None if a is None else a - COST
        right = None if net is None else (net > 0 if h["verdict"] == "buy" else net <= 0)
        verdicts.append(
            VerdictCheck(
                key=h["key"],
                label=HORIZON_FA.get(h["key"], h["label"]),
                verdict=h["verdict"],
                verdict_label=h["verdict_label"],
                days=days,
                actual=a,
                net=net,
                right=right,
            )
        )
    last_ret: float | None = None
    last_date: dt.date | None = None
    if base is not None and after:
        last_ret, last_date = after[-1][1] / base - 1, after[-1][0]
    done = [c for c in candles if c.status != "pending"]
    return PickOut(
        id=p.id,
        instrument_id=p.instrument_id,
        symbol=inst.symbol_fa,
        name=inst.name_fa,
        entered_on=p.entered_on,
        as_of=as_of,
        paid_price=p.paid_price,
        note=p.note,
        last_date=last_date,
        last_return=last_ret,
        gauge=snap.get("gauge"),
        candles=candles,
        verdicts=verdicts,
        resolved=len(done),
        inside=sum(1 for c in done if c.status == "inside"),
        direction_ok=sum(1 for c in done if c.direction_ok),
    )


@router.post("/picks", response_model=PickOut)
def add_pick(body: PickIn, session: SessionDep) -> PickOut:
    _ensure(session)
    inst = session.get(Instrument, body.instrument_id)
    if inst is None:
        raise HTTPException(status_code=404, detail="نماد پیدا نشد")
    snap = _snapshot(session, body.instrument_id)
    pick = TrackedPick(
        instrument_id=body.instrument_id,
        entered_on=body.entered_on or dt.date.fromisoformat(snap["as_of"]),
        paid_price=body.paid_price,
        note=body.note,
        snapshot=snap,
        created_at=dt.datetime.now(dt.UTC),
    )
    session.add(pick)
    session.commit()
    return _check(pick, inst, _closes(session, body.instrument_id))


@router.get("/picks", response_model=list[PickOut])
def list_picks(session: SessionDep, instrument_id: int | None = None) -> list[PickOut]:
    _ensure(session)
    q = select(TrackedPick).order_by(TrackedPick.created_at.desc())
    if instrument_id is not None:
        q = q.where(TrackedPick.instrument_id == instrument_id)
    out: list[PickOut] = []
    cache: dict[int, list[tuple[dt.date, float]]] = {}
    for p in session.scalars(q):
        inst = session.get(Instrument, p.instrument_id)
        if inst is None:
            continue
        if p.instrument_id not in cache:
            cache[p.instrument_id] = _closes(session, p.instrument_id)
        out.append(_check(p, inst, cache[p.instrument_id]))
    return out


@router.delete("/picks/{pick_id}")
def delete_pick(pick_id: int, session: SessionDep) -> dict[str, bool]:
    _ensure(session)
    p = session.get(TrackedPick, pick_id)
    if p is None:
        raise HTTPException(status_code=404, detail="مورد پیدا نشد")
    session.delete(p)
    session.commit()
    return {"deleted": True}
