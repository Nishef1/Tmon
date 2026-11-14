"""Portfolios: each one created by its own owner and reached with its own key.

``POST /portfolios`` returns the id and a key once; every other call sends the key in the
``X-Portfolio-Key`` header. Only a hash of the key is stored. Channel tokens and URLs are never
returned in full.
"""

from __future__ import annotations

import datetime as dt
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from tmon.api.schemas import ApiModel
from tmon.core.config import get_settings
from tmon.core.db import get_session
from tmon.core.timeutil import utcnow
from tmon.portfolio import alerts as alert_store
from tmon.portfolio import keys
from tmon.portfolio.advice import advise, last_closes
from tmon.portfolio.briefing import run_one
from tmon.portfolio.forecast import Position, portfolio_forecast
from tmon.portfolio.notify import Message, deliver, masked, validate
from tmon.portfolio.watch import DEFAULTS, settings_for
from tmon.storage.models import (
    Holding,
    Instrument,
    Portfolio,
    PortfolioAlert,
    PortfolioBriefing,
)

router = APIRouter(prefix="/portfolios", tags=["portfolios"])
SessionDep = Annotated[Session, Depends(get_session)]


# -- models ------------------------------------------------------------------------------------
class PortfolioCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    owner: str | None = Field(default=None, max_length=120)
    cash: float = Field(default=0, ge=0)


class PortfolioPatch(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    owner: str | None = None
    cash: float | None = Field(default=None, ge=0)
    settings: dict[str, Any] | None = None
    channels: list[dict[str, Any]] | None = None  # full list; a masked entry keeps its secret


class HoldingIn(BaseModel):
    symbol: str | None = None
    instrument_id: int | None = None
    shares: float = Field(gt=0)
    avg_price: float = Field(gt=0)
    bought_on: dt.date | None = None
    stop_price: float | None = Field(default=None, ge=0)
    note: str | None = None


class HoldingPatch(BaseModel):
    shares: float | None = Field(default=None, ge=0)
    avg_price: float | None = Field(default=None, gt=0)
    stop_price: float | None = Field(default=None, ge=0)
    note: str | None = None


class AnswerIn(BaseModel):
    answer: Literal["exit", "reduce", "hold"]


class CreatedOut(ApiModel):
    id: int
    key: str
    name: str


class HoldingOut(ApiModel):
    id: int
    instrument_id: int
    symbol: str
    name: str | None = None
    shares: float
    avg_price: float
    bought_on: dt.date | None = None
    stop_price: float | None = None
    note: str | None = None
    close: float | None = None
    close_date: str | None = None
    market_value: float
    cost: float
    pnl: float
    pnl_pct: float | None = None


class PortfolioOut(ApiModel):
    id: int
    name: str
    owner: str | None = None
    cash: float
    created_at: dt.datetime
    settings: dict[str, Any]
    defaults: dict[str, Any]
    channels: list[dict[str, Any]]
    holdings: list[HoldingOut]
    market_value: float
    cost: float
    total_value: float
    pnl: float
    pnl_pct: float | None = None


class AlertOut(ApiModel):
    id: int
    instrument_id: int | None = None
    symbol: str | None = None
    kind: str
    severity: int
    title: str
    body: str
    data: dict[str, Any]
    ask_exit: bool
    created_at: dt.datetime
    delivered: list[dict[str, Any]]
    answer: str | None = None
    answered_at: dt.datetime | None = None


class BriefingOut(ApiModel):
    id: int
    kind: str
    created_at: dt.datetime
    method: str
    doc: dict[str, Any]


# -- helpers -----------------------------------------------------------------------------------
def _auth(session: Session, pid: int, key: str | None) -> Portfolio:
    p = session.get(Portfolio, pid)
    if p is None or not key or not keys.matches(key, p.key_hash):
        raise HTTPException(404, "portfolio not found or key does not match")
    return p


Auth = Annotated[str | None, Header(alias="X-Portfolio-Key")]


def _norm(s: str) -> str:
    return s.replace("ي", "ی").replace("ك", "ک").replace("‌", "").strip()


def _instrument(session: Session, h: HoldingIn) -> Instrument:
    if h.instrument_id is not None:
        inst = session.get(Instrument, h.instrument_id)
    elif h.symbol:
        want = _norm(h.symbol)
        cands = list(session.scalars(select(Instrument).where(Instrument.symbol_fa == want)))
        if not cands:
            cands = [i for i in session.scalars(select(Instrument)) if _norm(i.symbol_fa) == want]
        inst = cands[0] if cands else None
    else:
        raise HTTPException(422, "symbol or instrument_id is required")
    if inst is None:
        raise HTTPException(404, "symbol not found")
    return inst


def _holdings(session: Session, p: Portfolio) -> list[tuple[Holding, Instrument]]:
    return [
        (h, i)
        for h, i in session.execute(
            select(Holding, Instrument)
            .join(Instrument, Instrument.id == Holding.instrument_id)
            .where(Holding.portfolio_id == p.id)
            .order_by(Holding.id)
        )
    ]


def _out(session: Session, p: Portfolio) -> PortfolioOut:
    rows = _holdings(session, p)
    closes = last_closes(session, [h.instrument_id for h, _ in rows])
    hs: list[HoldingOut] = []
    for h, i in rows:
        c = closes.get(h.instrument_id)
        price = c[0] if c else h.avg_price
        mv, cost = price * h.shares, h.avg_price * h.shares
        hs.append(
            HoldingOut(
                id=h.id,
                instrument_id=i.id,
                symbol=i.symbol_fa,
                name=i.name_fa,
                shares=h.shares,
                avg_price=h.avg_price,
                bought_on=h.bought_on,
                stop_price=h.stop_price,
                note=h.note,
                close=c[0] if c else None,
                close_date=c[1] if c else None,
                market_value=mv,
                cost=cost,
                pnl=mv - cost,
                pnl_pct=(mv / cost - 1) if cost else None,
            )
        )
    mv = sum(x.market_value for x in hs)
    cost = sum(x.cost for x in hs)
    return PortfolioOut(
        id=p.id,
        name=p.name,
        owner=p.owner,
        cash=p.cash,
        created_at=p.created_at,
        settings=dict(p.settings or {}),
        defaults=dict(DEFAULTS),
        channels=[masked(c) for c in p.channels or []],
        holdings=hs,
        market_value=mv,
        cost=cost,
        total_value=mv + p.cash,
        pnl=mv - cost,
        pnl_pct=(mv / cost - 1) if cost else None,
    )


def _merge_channels(old: list[dict[str, Any]], new: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """A channel sent back as the API showed it (masked) keeps its stored secret."""
    out = []
    for i, ch in enumerate(new):
        ch = {k: v for k, v in ch.items() if v is not None}
        prev = old[i] if i < len(old) and old[i].get("type") == ch.get("type") else None
        for secret in ("token", "url"):
            if prev and "…" in str(ch.get(secret, "…")):
                ch[secret] = prev.get(secret)
        if err := validate(ch):
            raise HTTPException(422, f"channel {i + 1}: {err}")
        out.append(ch)
    return out


# -- routes ------------------------------------------------------------------------------------
@router.post("", response_model=CreatedOut, status_code=201)
def create_portfolio(body: PortfolioCreate, session: SessionDep) -> CreatedOut:
    key = keys.new_key()
    p = Portfolio(
        name=body.name,
        owner=body.owner,
        key_hash=keys.hash_key(key),
        cash=body.cash,
        settings={},
        channels=[],
        created_at=utcnow(),
    )
    session.add(p)
    session.commit()
    return CreatedOut(id=p.id, key=key, name=p.name)


@router.get("/{portfolio_id}", response_model=PortfolioOut)
def get_portfolio(portfolio_id: int, session: SessionDep, key: Auth = None) -> PortfolioOut:
    return _out(session, _auth(session, portfolio_id, key))


@router.patch("/{portfolio_id}", response_model=PortfolioOut)
def patch_portfolio(
    portfolio_id: int, body: PortfolioPatch, session: SessionDep, key: Auth = None
) -> PortfolioOut:
    p = _auth(session, portfolio_id, key)
    if body.name is not None:
        p.name = body.name
    if body.owner is not None:
        p.owner = body.owner or None
    if body.cash is not None:
        p.cash = body.cash
    if body.settings is not None:
        unknown = set(body.settings) - set(DEFAULTS)
        if unknown:
            raise HTTPException(422, f"unknown settings: {sorted(unknown)}")
        p.settings = {k: v for k, v in body.settings.items() if v is not None}
        settings_for(p.settings)
    if body.channels is not None:
        p.channels = _merge_channels(list(p.channels or []), body.channels)
    session.commit()
    return _out(session, p)


@router.delete("/{portfolio_id}", status_code=204)
def delete_portfolio(portfolio_id: int, session: SessionDep, key: Auth = None) -> None:
    p = _auth(session, portfolio_id, key)
    for model in (Holding, PortfolioAlert, PortfolioBriefing):
        for row in session.scalars(select(model).where(model.portfolio_id == p.id)):
            session.delete(row)
    session.delete(p)
    session.commit()


@router.post("/{portfolio_id}/holdings", response_model=PortfolioOut)
def add_holding(
    portfolio_id: int, body: HoldingIn, session: SessionDep, key: Auth = None
) -> PortfolioOut:
    """Adding a symbol already held averages the price in (a second buy)."""
    p = _auth(session, portfolio_id, key)
    inst = _instrument(session, body)
    h = session.scalar(
        select(Holding).where(Holding.portfolio_id == p.id, Holding.instrument_id == inst.id)
    )
    if h is None:
        session.add(
            Holding(
                portfolio_id=p.id,
                instrument_id=inst.id,
                shares=body.shares,
                avg_price=body.avg_price,
                bought_on=body.bought_on,
                stop_price=body.stop_price,
                note=body.note,
                created_at=utcnow(),
            )
        )
    else:
        total = h.shares + body.shares
        h.avg_price = (h.avg_price * h.shares + body.avg_price * body.shares) / total
        h.shares = total
        if body.stop_price is not None:
            h.stop_price = body.stop_price
    session.commit()
    return _out(session, p)


@router.patch("/{portfolio_id}/holdings/{holding_id}", response_model=PortfolioOut)
def patch_holding(
    portfolio_id: int, holding_id: int, body: HoldingPatch, session: SessionDep, key: Auth = None
) -> PortfolioOut:
    p = _auth(session, portfolio_id, key)
    h = session.get(Holding, holding_id)
    if h is None or h.portfolio_id != p.id:
        raise HTTPException(404, "holding not found")
    for f in ("shares", "avg_price", "note"):
        v = getattr(body, f)
        if v is not None:
            setattr(h, f, v)
    if "stop_price" in body.model_fields_set:
        h.stop_price = body.stop_price or None
    if h.shares == 0:
        session.delete(h)
    session.commit()
    return _out(session, p)


@router.delete("/{portfolio_id}/holdings/{holding_id}", response_model=PortfolioOut)
def delete_holding(
    portfolio_id: int, holding_id: int, session: SessionDep, key: Auth = None
) -> PortfolioOut:
    p = _auth(session, portfolio_id, key)
    h = session.get(Holding, holding_id)
    if h is None or h.portfolio_id != p.id:
        raise HTTPException(404, "holding not found")
    session.delete(h)
    session.commit()
    return _out(session, p)


@router.get("/{portfolio_id}/alerts", response_model=list[AlertOut])
def list_alerts(
    portfolio_id: int, session: SessionDep, key: Auth = None, after: int = 0, limit: int = 100
) -> list[AlertOut]:
    """Newest first; ``after`` returns only alerts with a larger id (for polling)."""
    p = _auth(session, portfolio_id, key)
    rows = list(
        session.scalars(
            select(PortfolioAlert)
            .where(PortfolioAlert.portfolio_id == p.id, PortfolioAlert.id > after)
            .order_by(PortfolioAlert.id.desc())
            .limit(max(1, min(limit, 500)))
        )
    )
    ids = {a.instrument_id for a in rows if a.instrument_id}
    symbols = {
        i.id: i.symbol_fa for i in session.scalars(select(Instrument).where(Instrument.id.in_(ids)))
    }
    return [AlertOut(**alert_store.alert_out(a, symbols)) for a in rows]


@router.post("/{portfolio_id}/alerts/{alert_id}/answer", response_model=AlertOut)
def answer_alert(
    portfolio_id: int, alert_id: int, body: AnswerIn, session: SessionDep, key: Auth = None
) -> AlertOut:
    p = _auth(session, portfolio_id, key)
    a = session.get(PortfolioAlert, alert_id)
    if a is None or a.portfolio_id != p.id:
        raise HTTPException(404, "alert not found")
    alert_store.answer(session, alert_id, body.answer)
    session.commit()
    symbols = {}
    if a.instrument_id:
        inst = session.get(Instrument, a.instrument_id)
        symbols = {inst.id: inst.symbol_fa} if inst else {}
    return AlertOut(**alert_store.alert_out(a, symbols))


@router.get("/{portfolio_id}/advice")
def get_advice(portfolio_id: int, session: SessionDep, key: Auth = None) -> dict[str, Any]:
    """Keep / weak / sell per holding, switches that beat the round-trip cost, buys for the cash."""
    return advise(session, _auth(session, portfolio_id, key))


@router.get("/{portfolio_id}/forecast")
def get_forecast(portfolio_id: int, session: SessionDep, key: Auth = None) -> dict[str, Any]:
    """Return bands for a week to a year, for the portfolio and each holding, with the coverage
    of those bands measured on the portfolio's own history."""
    p = _auth(session, portfolio_id, key)
    rows = [(h, i) for h, i in _holdings(session, p) if h.shares > 0]
    closes = last_closes(session, [h.instrument_id for h, _ in rows])
    positions = [
        Position(h.instrument_id, i.symbol_fa, h.shares, closes[h.instrument_id][0], h.avg_price)
        for h, i in rows
        if h.instrument_id in closes
    ]
    doc = portfolio_forecast(session, positions)
    missing = [i.symbol_fa for h, i in rows if h.instrument_id not in closes]
    if missing:
        doc = {**doc, "skipped": [*doc.get("skipped", []), *missing]}
    return doc


@router.get("/{portfolio_id}/briefing", response_model=BriefingOut | None)
def get_briefing(portfolio_id: int, session: SessionDep, key: Auth = None) -> BriefingOut | None:
    p = _auth(session, portfolio_id, key)
    b = session.scalar(
        select(PortfolioBriefing)
        .where(PortfolioBriefing.portfolio_id == p.id)
        .order_by(PortfolioBriefing.id.desc())
        .limit(1)
    )
    if b is None:
        return None
    return BriefingOut(id=b.id, kind=b.kind, created_at=b.created_at, method=b.method, doc=b.doc)


@router.post("/{portfolio_id}/briefing", response_model=BriefingOut)
async def run_briefing(portfolio_id: int, session: SessionDep, key: Auth = None) -> BriefingOut:
    """Run the review now (with the news and letters already collected) and push its alerts."""
    p = _auth(session, portfolio_id, key)
    b, findings = run_one(session, p, "manual")
    new = alert_store.record(session, p.id, findings, b.created_at)
    await alert_store.dispatch(session, p, new, get_settings().public_web_url)
    session.commit()
    return BriefingOut(id=b.id, kind=b.kind, created_at=b.created_at, method=b.method, doc=b.doc)


@router.post("/{portfolio_id}/notify-test")
async def notify_test(
    portfolio_id: int, session: SessionDep, key: Auth = None
) -> list[dict[str, Any]]:
    """Send a test message (with the answer buttons) to every channel."""
    p = _auth(session, portfolio_id, key)
    if not p.channels:
        raise HTTPException(422, "no channels configured")
    msg = Message(0, 2, f"{p.name}: پیام آزمایشی", "اگر این پیام رسید، هشدارها هم می‌رسند.", True)
    return await deliver(list(p.channels), msg)
