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
from tmon.portfolio import keys, ledger, mofid
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
    PortfolioTrade,
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
    """A position already owned. Any of shares, price and amount may be left out: the price is
    then the close of ``bought_on`` (today when that is missing too) and the size comes from the
    amount, or is an equal share of the portfolio."""

    symbol: str | None = None
    instrument_id: int | None = None
    shares: float | None = Field(default=None, gt=0)
    avg_price: float | None = Field(default=None, gt=0)
    amount: float | None = Field(default=None, gt=0)  # rial put in
    bought_on: dt.date | None = None
    stop_price: float | None = Field(default=None, ge=0)
    note: str | None = None


class TradeIn(BaseModel):
    symbol: str | None = None
    instrument_id: int | None = None
    side: Literal["buy", "sell"]
    date: dt.date | None = None  # today when missing
    shares: float | None = Field(default=None, gt=0)  # a sale without shares sells all
    price: float | None = Field(default=None, gt=0)
    amount: float | None = Field(default=None, gt=0)
    fee: float | None = Field(default=None, ge=0)  # actual fee; standard rate when missing
    use_cash: bool | None = None  # buy: pay from the portfolio cash (auto: if it is enough)
    note: str | None = None


class TradeOut(ApiModel):
    id: int
    instrument_id: int
    symbol: str
    side: str
    date: dt.date
    shares: float | None = None
    price: float | None = None
    amount: float | None = None
    fee: float | None = None
    cash_delta: float
    source: str
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
    pnl: float  # unrealized, after the fees of buying and of selling today
    pnl_pct: float | None = None
    liquidation_value: float = 0.0
    realized: float = 0.0
    dividends: float = 0.0
    total_pnl: float = 0.0
    weight: float | None = None
    sector: str | None = None
    instrument_type: str | None = None
    stale: bool = False
    price_missing: bool = False
    size_estimated: bool = False
    price_estimated: bool = False
    events: list[dict[str, Any]] = Field(default_factory=list)


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
    liquidation_value: float = 0.0
    realized: float = 0.0
    dividends: float = 0.0
    fees: float = 0.0
    total_pnl: float = 0.0
    total_pnl_pct: float | None = None
    estimated: bool = False
    as_of: str | None = None
    warnings: list[dict[str, Any]] = Field(default_factory=list)
    sector_weights: list[dict[str, Any]] = Field(default_factory=list)
    closed: list[dict[str, Any]] = Field(default_factory=list)


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
_schema_ready = False


def _auth(session: Session, pid: int, key: str | None) -> Portfolio:
    global _schema_ready
    if not _schema_ready:
        ledger.ensure_schema(session)
        _schema_ready = True
    p = session.get(Portfolio, pid)
    if p is None or not key or not keys.matches(key, p.key_hash):
        raise HTTPException(404, "portfolio not found or key does not match")
    return p


Auth = Annotated[str | None, Header(alias="X-Portfolio-Key")]


def _norm(s: str) -> str:
    return s.replace("ي", "ی").replace("ك", "ک").replace("‌", "").strip()


def _instrument(session: Session, h: HoldingIn | TradeIn) -> Instrument:
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
    positions = ledger.rebuild(session, p)
    session.commit()
    doc = ledger.summarize(session, p, positions)
    rows = {
        h.instrument_id: h
        for h in session.scalars(select(Holding).where(Holding.portfolio_id == p.id))
    }
    hs: list[HoldingOut] = []
    for x in doc["holdings"]:
        h = rows.get(x["instrument_id"])
        if h is None:
            continue
        hs.append(
            HoldingOut(
                id=h.id,
                instrument_id=x["instrument_id"],
                symbol=x["symbol"],
                name=x["name"],
                shares=x["shares"],
                avg_price=x["avg_cost"],
                bought_on=h.bought_on,
                stop_price=h.stop_price,
                note=h.note,
                close=x["close"],
                close_date=x["close_date"],
                market_value=x["market_value"],
                cost=x["cost"],
                pnl=x["unrealized"],
                pnl_pct=x["unrealized_pct"],
                liquidation_value=x["liquidation_value"],
                realized=x["realized"],
                dividends=x["dividends"],
                total_pnl=x["total_pnl"],
                weight=x["weight"],
                sector=x["sector"],
                instrument_type=x["instrument_type"],
                stale=x["stale"],
                price_missing=x["price_missing"],
                size_estimated=x["size_estimated"],
                price_estimated=x["price_estimated"],
                events=x["events"],
            )
        )
    t = doc["totals"]
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
        market_value=t["market_value"],
        cost=t["cost"],
        total_value=t["total_value"],
        pnl=t["unrealized"],
        pnl_pct=t["unrealized_pct"],
        liquidation_value=t["liquidation_value"],
        realized=t["realized"],
        dividends=t["dividends"],
        fees=t["fees"],
        total_pnl=t["total_pnl"],
        total_pnl_pct=t["total_pnl_pct"],
        estimated=doc["estimated"],
        as_of=doc["as_of"],
        warnings=doc["warnings"],
        sector_weights=doc["sector_weights"],
        closed=doc["closed"],
    )


def _trade_out(t: PortfolioTrade, symbol: str) -> TradeOut:
    return TradeOut(
        id=t.id,
        instrument_id=t.instrument_id,
        symbol=symbol,
        side=t.side,
        date=t.date,
        shares=t.shares,
        price=t.price,
        amount=t.amount,
        fee=t.fee,
        cash_delta=t.cash_delta,
        source=t.source,
        note=t.note,
    )


def _held(session: Session, p: Portfolio, instrument_id: int, on: dt.date) -> float:
    pos = ledger.replay(session, p, until=on).get(instrument_id)
    return pos.shares if pos else 0.0


def add_trade(
    session: Session,
    p: Portfolio,
    inst: Instrument,
    body: TradeIn,
    source: str = "manual",
    external_id: str | None = None,
) -> PortfolioTrade:
    """Validate one ledger line, move the cash and store it."""
    day = body.date or utcnow().date()
    price = body.price
    if price is None and body.shares and body.amount:
        price = body.amount / body.shares
    if price is None:
        c = ledger.close_on(session, inst.id, day)
        price = c[0] if c else None
    if body.side == "sell":
        held = _held(session, p, inst.id, day)
        if held <= 0:
            raise HTTPException(422, f"{inst.symbol_fa} is not held on {day}")
        if body.shares and body.shares > held * (1 + 1e-9):
            raise HTTPException(422, f"only {held:,.0f} shares of {inst.symbol_fa} are held")
    buy_rate, sell_rate = ledger.fee_rates(session, inst.instrument_type, day)
    cash_delta = 0.0
    if price is not None:
        if body.side == "buy":
            shares = body.shares or (body.amount / price if body.amount else None)
            if shares:
                gross = shares * price
                need = gross + (body.fee if body.fee is not None else gross * buy_rate)
                use = body.use_cash if body.use_cash is not None else p.cash >= need
                if use:
                    cash_delta = -min(need, p.cash)
        elif body.use_cash is not False:
            shares = body.shares or _held(session, p, inst.id, day)
            gross = shares * price
            cash_delta = gross - (body.fee if body.fee is not None else gross * sell_rate)
    p.cash = max(0.0, p.cash + cash_delta)
    t = PortfolioTrade(
        portfolio_id=p.id,
        instrument_id=inst.id,
        side=body.side,
        date=day,
        shares=body.shares,
        price=body.price,
        amount=body.amount,
        fee=body.fee,
        cash_delta=cash_delta,
        source=source,
        external_id=external_id,
        note=body.note,
        created_at=utcnow(),
    )
    session.add(t)
    session.flush()
    return t


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
    mofid.unlink(session, p.id)
    for model in (PortfolioTrade, Holding, PortfolioAlert, PortfolioBriefing):
        for row in session.scalars(select(model).where(model.portfolio_id == p.id)):
            session.delete(row)
    session.delete(p)
    session.commit()


@router.post("/{portfolio_id}/holdings", response_model=PortfolioOut)
def add_holding(
    portfolio_id: int, body: HoldingIn, session: SessionDep, key: Auth = None
) -> PortfolioOut:
    """A position already owned: an opening buy that does not touch the cash. A second one for
    the same symbol averages in."""
    p = _auth(session, portfolio_id, key)
    inst = _instrument(session, body)
    ledger.migrate_legacy(session, p)
    add_trade(
        session,
        p,
        inst,
        TradeIn(
            instrument_id=inst.id,
            side="buy",
            date=body.bought_on,
            shares=body.shares,
            price=body.avg_price,
            amount=body.amount,
            use_cash=False,
            note=body.note,
        ),
    )
    ledger.rebuild(session, p)
    h = session.scalar(
        select(Holding).where(Holding.portfolio_id == p.id, Holding.instrument_id == inst.id)
    )
    if h is not None:
        if body.stop_price is not None:
            h.stop_raw = h.stop_price = body.stop_price or None
            h.stop_set_on = utcnow().date()
        if body.note is not None:
            h.note = body.note
    session.commit()
    return _out(session, p)


@router.patch("/{portfolio_id}/holdings/{holding_id}", response_model=PortfolioOut)
def patch_holding(
    portfolio_id: int, holding_id: int, body: HoldingPatch, session: SessionDep, key: Auth = None
) -> PortfolioOut:
    """Stop and note in place. A new share count or average price replaces the symbol's ledger
    with one opening line (record a sale as a trade instead, so its profit is kept)."""
    p = _auth(session, portfolio_id, key)
    h = session.get(Holding, holding_id)
    if h is None or h.portfolio_id != p.id:
        raise HTTPException(404, "holding not found")
    ledger.migrate_legacy(session, p)
    if body.note is not None:
        h.note = body.note
    if "stop_price" in body.model_fields_set:
        h.stop_raw = h.stop_price = body.stop_price or None
        h.stop_set_on = utcnow().date()
    if body.shares is not None or body.avg_price is not None:
        trades = list(
            session.scalars(
                select(PortfolioTrade).where(
                    PortfolioTrade.portfolio_id == p.id,
                    PortfolioTrade.instrument_id == h.instrument_id,
                )
            )
        )
        first = min((t.date for t in trades), default=h.bought_on or utcnow().date())
        for t in trades:
            session.delete(t)
        shares = h.shares if body.shares is None else body.shares
        if shares > 0:
            session.add(
                PortfolioTrade(
                    portfolio_id=p.id,
                    instrument_id=h.instrument_id,
                    side="buy",
                    date=first,
                    shares=shares,
                    price=body.avg_price or h.avg_price,
                    fee=0.0,  # an average typed in is already the full cost
                    cash_delta=0.0,
                    source="manual",
                    created_at=utcnow(),
                )
            )
        session.flush()
    session.commit()
    return _out(session, p)


@router.delete("/{portfolio_id}/holdings/{holding_id}", response_model=PortfolioOut)
def delete_holding(
    portfolio_id: int, holding_id: int, session: SessionDep, key: Auth = None
) -> PortfolioOut:
    """Remove a symbol with its whole ledger (a mistake, not a sale: a sale is a trade)."""
    p = _auth(session, portfolio_id, key)
    h = session.get(Holding, holding_id)
    if h is None or h.portfolio_id != p.id:
        raise HTTPException(404, "holding not found")
    for t in session.scalars(
        select(PortfolioTrade).where(
            PortfolioTrade.portfolio_id == p.id, PortfolioTrade.instrument_id == h.instrument_id
        )
    ):
        p.cash = max(0.0, p.cash - t.cash_delta)
        session.delete(t)
    session.delete(h)
    session.commit()
    return _out(session, p)


@router.get("/{portfolio_id}/trades", response_model=list[TradeOut])
def list_trades(portfolio_id: int, session: SessionDep, key: Auth = None) -> list[TradeOut]:
    p = _auth(session, portfolio_id, key)
    ledger.migrate_legacy(session, p)
    session.commit()
    rows = session.execute(
        select(PortfolioTrade, Instrument.symbol_fa)
        .join(Instrument, Instrument.id == PortfolioTrade.instrument_id)
        .where(PortfolioTrade.portfolio_id == p.id)
        .order_by(PortfolioTrade.date.desc(), PortfolioTrade.id.desc())
    ).all()
    return [_trade_out(t, sym) for t, sym in rows]


@router.post("/{portfolio_id}/trades", response_model=PortfolioOut)
def post_trade(
    portfolio_id: int, body: TradeIn, session: SessionDep, key: Auth = None
) -> PortfolioOut:
    """A buy or a sale. A sale books its realized profit; with cash tracking the money moves."""
    p = _auth(session, portfolio_id, key)
    ledger.migrate_legacy(session, p)
    add_trade(session, p, _instrument(session, body), body)
    session.commit()
    return _out(session, p)


@router.delete("/{portfolio_id}/trades/{trade_id}", response_model=PortfolioOut)
def delete_trade(
    portfolio_id: int, trade_id: int, session: SessionDep, key: Auth = None
) -> PortfolioOut:
    p = _auth(session, portfolio_id, key)
    t = session.get(PortfolioTrade, trade_id)
    if t is None or t.portfolio_id != p.id:
        raise HTTPException(404, "trade not found")
    p.cash = max(0.0, p.cash - t.cash_delta)
    session.delete(t)
    session.commit()
    return _out(session, p)


@router.get("/{portfolio_id}/history")
def get_history(portfolio_id: int, session: SessionDep, key: Auth = None) -> dict[str, Any]:
    """Daily value and time-weighted return next to the total index."""
    p = _auth(session, portfolio_id, key)
    positions = ledger.rebuild(session, p)
    session.commit()
    return ledger.history(session, p, positions)


@router.get("/{portfolio_id}/mofid")
def mofid_status(portfolio_id: int, session: SessionDep, key: Auth = None) -> dict[str, Any]:
    """The Mofid link: status, token expiry and the last sync (never the token itself)."""
    p = _auth(session, portfolio_id, key)
    return mofid.status(session, p.id)


@router.post("/{portfolio_id}/mofid/connect")
def mofid_connect(portfolio_id: int, session: SessionDep, key: Auth = None) -> dict[str, Any]:
    """Open Chrome on this portfolio's own profile for the owner to log in to Mofid (a saved
    login is used without a window), then sync. Runs in the background: poll ``GET mofid``."""
    p = _auth(session, portfolio_id, key)
    mofid.start_connect(p.id)
    return mofid.status(session, p.id)


@router.post("/{portfolio_id}/mofid/sync", response_model=PortfolioOut)
def mofid_sync(portfolio_id: int, session: SessionDep, key: Auth = None) -> PortfolioOut:
    """Copy Mofid's positions and buying power into this portfolio now."""
    p = _auth(session, portfolio_id, key)
    try:
        mofid.sync(session, p)
    except mofid.MofidError as e:
        raise HTTPException(409, str(e)) from None
    return _out(session, p)


@router.delete("/{portfolio_id}/mofid", status_code=204)
def mofid_unlink(portfolio_id: int, session: SessionDep, key: Auth = None) -> None:
    p = _auth(session, portfolio_id, key)
    mofid.unlink(session, p.id)
    session.commit()


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
