"""The portfolio ledger: trades in, holdings, realized profit, dividends and history out.

Holdings are not typed in directly any more: each buy and sell is a ``PortfolioTrade`` line and
the position is the replay of those lines together with the market's own events (capital
increases, rights issues and cash dividends, read from the TSETMC price adjustments and share
count changes). That replay is what makes three things right that a "shares x average price"
row gets wrong:

* after a capital increase the price drops but the holder owns more shares, so there is no loss;
* after an AGM the price drops by the dividend, which the holder is owed, so the dividend is
  income, not a loss;
* a sale books a realized profit or loss and puts the proceeds in the cash.

A line may leave out the share count, the price, or both. The price is then the close on the
trade's date; the size is ``amount / price``, or an equal share of the portfolio when even the
amount is unknown. The portfolio's return in percent is still right; the money figures of such a
holding are flagged as estimated.
"""

from __future__ import annotations

import datetime as dt
import math
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import and_, func, inspect, select, text
from sqlalchemy.orm import Session

from tmon.core.timeutil import utcnow
from tmon.storage.models import (
    Base,
    BrokerLink,
    Holding,
    Instrument,
    MarketIndexDaily,
    MarketRule,
    Portfolio,
    PortfolioTrade,
    PriceAdjustment,
    PriceDaily,
    SectorName,
    ShareChange,
)

TEDPIX = "32097828799138957"  # شاخص کل
DEFAULT_NOTIONAL = 100_000_000.0  # rial, the size of a holding whose size is unknown and alone
# A share-count change belongs to a price adjustment when the two are this close in time ...
MATCH_BEFORE = dt.timedelta(days=45)
MATCH_AFTER = dt.timedelta(days=15)
# ... and the adjustment times the share ratio is in this band (1 = a pure bonus issue; above 1
# a rights issue the holder paid into; below 1 a dividend on the same day).
MATCH_BAND = (0.6, 1.7)
MAX_DIVIDEND_SHARE = 0.6  # a drop bigger than this without a share change is not a dividend

# Fee per side as a share of the trade value, sell tax included. Stocks and rights read the
# market_rules table; funds are exempt from the sell tax and pay a much lower commission
# (Mofid Securities fee page, learning.emofid.com/trading-fees, 2026).
FUND_FEES: dict[str, tuple[float, float]] = {
    "etf_equity": (0.00116, 0.0011875),
    "etf_leveraged": (0.00116, 0.0011875),
    "etf_mixed": (0.0006075, 0.00066125),
    "etf_fixed_income": (0.0001875, 0.0001875),
    "etf_commodity": (0.00115, 0.00115),
    "bond": (0.000725, 0.000725),
}
STOCK_FALLBACK = (0.003712, 0.0088)

CONCENTRATION_ONE = 0.25  # one holding above this share of the portfolio is a warning
CONCENTRATION_SECTOR = 0.40


# -- schema ------------------------------------------------------------------------------------
def ensure_schema(session: Session) -> None:
    """Create the ledger table and the two new holding columns on a database made before them
    (the live SQLite file is built from the models, not by Alembic)."""
    bind = session.get_bind()
    Base.metadata.create_all(bind, tables=[PortfolioTrade.__table__, BrokerLink.__table__])  # type: ignore[list-item]
    cols = {c["name"] for c in inspect(bind).get_columns("holdings")}
    if "stop_raw" not in cols:
        session.execute(text("ALTER TABLE holdings ADD COLUMN stop_raw FLOAT"))
    if "stop_set_on" not in cols:
        session.execute(text("ALTER TABLE holdings ADD COLUMN stop_set_on DATE"))
    session.commit()


def migrate_legacy(session: Session, p: Portfolio) -> None:
    """A holding typed in before the ledger existed becomes one opening buy line."""
    have = set(
        session.scalars(
            select(PortfolioTrade.instrument_id).where(PortfolioTrade.portfolio_id == p.id)
        )
    )
    for h in session.scalars(select(Holding).where(Holding.portfolio_id == p.id)):
        if h.instrument_id in have or h.shares <= 0:
            continue
        session.add(
            PortfolioTrade(
                portfolio_id=p.id,
                instrument_id=h.instrument_id,
                side="buy",
                date=h.bought_on or h.created_at.date(),
                shares=h.shares,
                price=h.avg_price,
                cash_delta=0.0,
                source="legacy",
                created_at=utcnow(),
            )
        )
        if h.stop_price and h.stop_raw is None:
            h.stop_raw, h.stop_set_on = h.stop_price, h.created_at.date()
    session.flush()


# -- fees --------------------------------------------------------------------------------------
def _rule_rate(session: Session, rule: str, on: dt.date) -> float | None:
    row = session.scalar(
        select(MarketRule)
        .where(
            MarketRule.rule == rule,
            MarketRule.valid_from <= on,
            (MarketRule.valid_to.is_(None)) | (MarketRule.valid_to >= on),
        )
        .order_by(MarketRule.valid_from.desc())
        .limit(1)
    )
    if row is None:
        return None
    v = row.value if isinstance(row.value, dict) else {}
    r = v.get("rate")
    return float(r) if r is not None else None


def fee_rates(session: Session, instrument_type: str, on: dt.date) -> tuple[float, float]:
    """(buy, sell) fee per side as a share of the value; the sell side includes the tax."""
    if instrument_type in FUND_FEES:
        return FUND_FEES[instrument_type]
    buy = _rule_rate(session, "commission_buy", on)
    sell = _rule_rate(session, "commission_sell", on)
    tax = _rule_rate(session, "sell_tax", on)
    if buy is None or sell is None or tax is None:
        return STOCK_FALLBACK
    return buy, sell + tax


# -- market data -------------------------------------------------------------------------------
def close_on(session: Session, instrument_id: int, day: dt.date) -> tuple[float, dt.date] | None:
    """Close on ``day`` or the last one before it; the first one after when none is before."""
    for cond, order in (
        (PriceDaily.date <= day, PriceDaily.date.desc()),
        (PriceDaily.date > day, PriceDaily.date.asc()),
    ):
        row = session.execute(
            select(PriceDaily.close, PriceDaily.date)
            .where(PriceDaily.instrument_id == instrument_id, PriceDaily.close.is_not(None), cond)
            .order_by(order)
            .limit(1)
        ).first()
        if row and row[0]:
            return float(row[0]), row[1]
    return None


@dataclass(frozen=True)
class Action:
    """A market event that changes what one share held the day before is worth in shares and
    money: ``ratio`` new shares per old share, ``dividend`` rial per old share owed to the holder,
    ``paid_in`` rial per old share the holder put in (a rights issue they took up)."""

    date: dt.date
    kind: str  # bonus | rights | dividend | split | adjust
    ratio: float
    dividend: float
    paid_in: float
    price_factor: float  # price after / close before, for moving a stop


def corporate_actions(session: Session, instrument_id: int, since: dt.date) -> list[Action]:
    adjs = list(
        session.scalars(
            select(PriceAdjustment)
            .where(PriceAdjustment.instrument_id == instrument_id, PriceAdjustment.date > since)
            .order_by(PriceAdjustment.date)
        )
    )
    if not adjs:
        return []
    changes = [
        c
        for c in session.scalars(
            select(ShareChange).where(
                ShareChange.instrument_id == instrument_id,
                ShareChange.date > since - MATCH_AFTER,
            )
        )
        if c.shares_old > 0 and c.shares_new > 0
    ]
    used: set[int] = set()
    out: list[Action] = []
    for a in adjs:
        if not a.close_before or not a.price_after:
            continue
        before, after, factor = float(a.close_before), float(a.price_after), float(a.adj_factor)
        best: tuple[float, ShareChange] | None = None
        for c in changes:
            if c.idn in used or not (a.date - MATCH_BEFORE <= c.date <= a.date + MATCH_AFTER):
                continue
            r = c.shares_new / c.shares_old
            prod = factor * r
            if MATCH_BAND[0] <= prod <= MATCH_BAND[1]:
                dist = abs(math.log(prod))
                if best is None or dist < best[0]:
                    best = (dist, c)
        if best is not None:
            c = best[1]
            used.add(c.idn)
            r = c.shares_new / c.shares_old
            delta = r * after - before  # per old share
            if delta > 0:
                kind, div, paid = ("rights", 0.0, delta) if r > 1 else ("adjust", 0.0, 0.0)
            elif delta < -0.002 * before:
                kind, div, paid = ("bonus" if r > 1 else "split"), -delta, 0.0
            else:
                kind, div, paid = ("bonus" if r > 1 else "split"), 0.0, 0.0
            out.append(Action(a.date, kind, r, div, paid, factor))
        elif factor < 1:
            drop = before - after
            if drop <= MAX_DIVIDEND_SHARE * before:
                out.append(Action(a.date, "dividend", 1.0, drop, 0.0, factor))
            else:  # too big to be a dividend: keep the money value, flag it
                out.append(Action(a.date, "adjust", 1 / factor, 0.0, 0.0, factor))
    return out


# -- replay ------------------------------------------------------------------------------------
@dataclass
class Event:
    date: dt.date
    kind: str  # buy | sell | bonus | rights | dividend | split | adjust
    shares: float  # change in shares
    price: float | None
    amount: float  # rial: buy cost with fee, sale proceeds after fee, dividend, paid-in
    fee: float = 0.0
    realized: float = 0.0
    trade_id: int | None = None
    estimated: bool = False


@dataclass
class Position:
    instrument_id: int
    shares: float = 0.0
    cost: float = 0.0  # open lot cost basis with buy fees and paid-in money
    realized: float = 0.0  # closed profit after fees
    dividends: float = 0.0
    fees: float = 0.0
    bought: float = 0.0  # every buy with fee (for the money return)
    opened_on: dt.date | None = None
    price_estimated: bool = False
    size_estimated: bool = False
    stop_factor_since: dict[dt.date, float] = field(default_factory=dict)
    events: list[Event] = field(default_factory=list)
    last_close: float | None = None
    last_close_date: dt.date | None = None


def _resolved(
    session: Session, trades: list[PortfolioTrade], instruments: dict[int, Instrument]
) -> list[tuple[PortfolioTrade, float | None, float | None, bool, bool]]:
    """(trade, shares, price, price_estimated, size_estimated); shares None for a sell = all."""
    out = []
    sized_amounts: list[float] = []
    for t in trades:
        if t.side == "buy" and t.shares and t.price:
            sized_amounts.append(t.shares * t.price)
        elif t.side == "buy" and t.amount:
            sized_amounts.append(t.amount)
    notional = sum(sized_amounts) / len(sized_amounts) if sized_amounts else DEFAULT_NOTIONAL
    for t in trades:
        price, p_est = t.price, False
        if not price:
            if t.shares and t.amount:
                price = t.amount / t.shares
            else:
                c = close_on(session, t.instrument_id, t.date)
                price, p_est = (c[0] if c else None), True
        shares, s_est = t.shares, False
        if not shares and price:
            if t.amount:
                shares = t.amount / price
            elif t.side == "buy":
                shares, s_est = notional / price, True
        out.append((t, shares, price, p_est, s_est))
    return out


def replay(session: Session, p: Portfolio, until: dt.date | None = None) -> dict[int, Position]:
    trades = list(
        session.scalars(
            select(PortfolioTrade)
            .where(PortfolioTrade.portfolio_id == p.id)
            .order_by(PortfolioTrade.date, PortfolioTrade.id)
        )
    )
    ids = {t.instrument_id for t in trades}
    instruments = {
        i.id: i for i in session.scalars(select(Instrument).where(Instrument.id.in_(ids)))
    }
    by_inst: dict[int, list[tuple[PortfolioTrade, float | None, float | None, bool, bool]]]
    by_inst = defaultdict(list)
    for row in _resolved(session, trades, instruments):
        by_inst[row[0].instrument_id].append(row)

    out: dict[int, Position] = {}
    for iid, rows in by_inst.items():
        inst = instruments.get(iid)
        itype = inst.instrument_type if inst else "stock"
        pos = Position(iid)
        first = rows[0][0].date
        actions = corporate_actions(session, iid, first)
        timeline: list[tuple[dt.date, int, Any]] = [(a.date, 0, a) for a in actions]
        timeline += [(r[0].date, 1, r) for r in rows]  # events on day D before that day's trades
        timeline.sort(key=lambda x: (x[0], x[1]))
        for day, _, item in timeline:
            if until and day > until:
                break
            if isinstance(item, Action):
                if pos.shares <= 0:
                    continue
                old = pos.shares
                pos.shares *= item.ratio
                paid = item.paid_in * old
                div = item.dividend * old
                pos.cost += paid
                pos.bought += paid
                pos.dividends += div
                for k in pos.stop_factor_since:
                    pos.stop_factor_since[k] *= item.price_factor
                if item.kind != "dividend":
                    pos.events.append(
                        Event(day, item.kind, pos.shares - old, None, paid, estimated=True)
                    )
                if div:
                    pos.events.append(Event(day, "dividend", 0.0, item.dividend, div))
                continue
            t, shares, price, p_est, s_est = item
            buy_rate, sell_rate = fee_rates(session, itype, t.date)
            if price is None:
                continue  # no price at all for this instrument yet
            if t.side == "buy":
                if not shares:
                    continue
                gross = shares * price
                fee = t.fee if t.fee is not None else gross * buy_rate
                if pos.shares <= 0:
                    pos.opened_on = t.date
                    pos.cost = 0.0
                pos.shares += shares
                pos.cost += gross + fee
                pos.fees += fee
                pos.bought += gross + fee
                pos.price_estimated |= p_est
                pos.size_estimated |= s_est
                pos.events.append(
                    Event(t.date, "buy", shares, price, gross + fee, fee, 0.0, t.id, p_est or s_est)
                )
            else:
                q = pos.shares if not shares else min(shares, pos.shares)
                if q <= 0:
                    continue
                gross = q * price
                fee = t.fee if t.fee is not None else gross * sell_rate
                basis = pos.cost * q / pos.shares
                realized = gross - fee - basis
                pos.shares -= q
                pos.cost -= basis
                pos.realized += realized
                pos.fees += fee
                if pos.shares <= 1e-9:
                    pos.shares, pos.cost = 0.0, 0.0
                pos.events.append(
                    Event(t.date, "sell", -q, price, gross - fee, fee, realized, t.id, p_est)
                )
        out[iid] = pos
    return out


def sync_holdings(session: Session, p: Portfolio, positions: dict[int, Position]) -> None:
    """Write the replayed positions into ``holdings`` for the monitor, advice and forecast."""
    rows = {
        h.instrument_id: h
        for h in session.scalars(select(Holding).where(Holding.portfolio_id == p.id))
    }
    for iid, pos in positions.items():
        h = rows.pop(iid, None)
        if pos.shares <= 0:
            if h is not None:
                session.delete(h)
            continue
        if h is None:
            h = Holding(portfolio_id=p.id, instrument_id=iid, created_at=utcnow())
            session.add(h)
        h.shares = pos.shares
        h.avg_price = pos.cost / pos.shares
        h.bought_on = pos.opened_on
        if h.stop_raw and h.stop_set_on:
            f = 1.0
            for a in corporate_actions(session, iid, h.stop_set_on):
                f *= a.price_factor
            h.stop_price = h.stop_raw * f
    for h in rows.values():  # a holding with no ledger lines left
        session.delete(h)
    session.flush()


def rebuild(session: Session, p: Portfolio) -> dict[int, Position]:
    migrate_legacy(session, p)
    positions = replay(session, p)
    sync_holdings(session, p, positions)
    return positions


# -- summary -----------------------------------------------------------------------------------
def market_date(session: Session) -> dt.date | None:
    return session.scalar(
        select(func.max(MarketIndexDaily.date)).where(MarketIndexDaily.index_code == TEDPIX)
    ) or session.scalar(select(func.max(PriceDaily.date)))


def summarize(session: Session, p: Portfolio, positions: dict[int, Position]) -> dict[str, Any]:
    """Money and percent figures for each holding and the whole portfolio, every number net of
    the fees it took to buy and would take to sell today."""
    ids = list(positions)
    instruments = {
        i.id: i for i in session.scalars(select(Instrument).where(Instrument.id.in_(ids)))
    }
    sectors = {s.code: s.name for s in session.scalars(select(SectorName))}
    latest = market_date(session)
    today = utcnow().date()
    holdings: list[dict[str, Any]] = []
    closed: list[dict[str, Any]] = []
    tot: defaultdict[str, float] = defaultdict(float)
    any_estimated = False
    for iid, pos in positions.items():
        inst = instruments.get(iid)
        c = close_on(session, iid, today)
        realized_row = {
            "instrument_id": iid,
            "symbol": inst.symbol_fa if inst else str(iid),
            "realized": pos.realized,
            "dividends": pos.dividends,
            "fees": pos.fees,
        }
        tot["realized"] += pos.realized
        tot["dividends"] += pos.dividends
        tot["fees"] += pos.fees
        tot["bought"] += pos.bought
        if pos.shares <= 0:
            closed.append(realized_row)
            continue
        itype = inst.instrument_type if inst else "stock"
        _, sell_rate = fee_rates(session, itype, today)
        price = c[0] if c else None
        price_missing = price is None
        mark = price if price is not None else pos.cost / pos.shares
        mv = pos.shares * mark
        net = mv * (1 - sell_rate)
        unreal = net - pos.cost
        estimated = pos.size_estimated or pos.price_estimated
        any_estimated |= estimated
        stale = bool(c and latest and c[1] < latest)
        sector = inst.sector_code if inst else None
        holdings.append(
            {
                "instrument_id": iid,
                "symbol": inst.symbol_fa if inst else str(iid),
                "name": inst.name_fa if inst else None,
                "instrument_type": itype,
                "sector": sectors.get((sector or "").zfill(2)) if sector else None,
                "shares": pos.shares,
                "avg_cost": pos.cost / pos.shares,
                "cost": pos.cost,
                "close": price,
                "close_date": c[1].isoformat() if c else None,
                "stale": stale,
                "price_missing": price_missing,
                "market_value": mv,
                "liquidation_value": net,
                "unrealized": unreal,
                "unrealized_pct": unreal / pos.cost if pos.cost else None,
                "realized": pos.realized,
                "dividends": pos.dividends,
                "total_pnl": unreal + pos.realized + pos.dividends,
                "opened_on": pos.opened_on.isoformat() if pos.opened_on else None,
                "size_estimated": pos.size_estimated,
                "price_estimated": pos.price_estimated,
                "events": [
                    {
                        "date": e.date.isoformat(),
                        "kind": e.kind,
                        "shares": e.shares,
                        "price": e.price,
                        "amount": e.amount,
                    }
                    for e in pos.events
                    if e.kind not in ("buy", "sell")
                ],
            }
        )
        tot["market_value"] += mv
        tot["liquidation_value"] += net
        tot["cost"] += pos.cost
        tot["unrealized"] += unreal

    mv_all = tot["market_value"]
    by_sector: dict[str, float] = defaultdict(float)
    for h in holdings:
        h["weight"] = h["market_value"] / mv_all if mv_all else None
        by_sector[h["sector"] or "نامعلوم"] += h["market_value"]
    shares_by_sector = sorted(
        ((k, v / mv_all) for k, v in by_sector.items() if mv_all), key=lambda x: -x[1]
    )
    sector_weights: list[dict[str, Any]] = [{"sector": k, "weight": w} for k, w in shares_by_sector]
    warnings: list[dict[str, Any]] = []
    for h in holdings:
        one_cap = max(CONCENTRATION_ONE, 1.5 / max(len(holdings), 1))  # 1.5x an equal share
        if h["weight"] and h["weight"] > one_cap and len(holdings) > 1:
            warnings.append({"kind": "concentration", "symbol": h["symbol"], "weight": h["weight"]})
        if h["price_missing"]:
            warnings.append({"kind": "price_missing", "symbol": h["symbol"]})
        elif h["stale"]:
            warnings.append(
                {"kind": "stale_price", "symbol": h["symbol"], "close_date": h["close_date"]}
            )
    for name, w in shares_by_sector:
        sector_cap = max(CONCENTRATION_SECTOR, 1.5 / max(len(shares_by_sector), 1))
        if w > sector_cap and len(shares_by_sector) > 1:
            warnings.append({"kind": "sector_concentration", "sector": name, "weight": w})

    total_pnl = tot["unrealized"] + tot["realized"] + tot["dividends"]
    holdings.sort(key=lambda h: -h["market_value"])
    return {
        "as_of": latest.isoformat() if latest else None,
        "holdings": holdings,
        "closed": closed,
        "sector_weights": sector_weights,
        "warnings": warnings,
        "estimated": any_estimated,
        "totals": {
            "cash": p.cash,
            "cost": tot["cost"],
            "market_value": mv_all,
            "liquidation_value": tot["liquidation_value"],
            "total_value": tot["liquidation_value"] + p.cash,
            "unrealized": tot["unrealized"],
            "unrealized_pct": tot["unrealized"] / tot["cost"] if tot["cost"] else None,
            "realized": tot["realized"],
            "dividends": tot["dividends"],
            "fees": tot["fees"],
            "total_pnl": total_pnl,
            "total_pnl_pct": total_pnl / tot["bought"] if tot["bought"] else None,
            "in_profit": total_pnl > 0,
        },
    }


# -- history -----------------------------------------------------------------------------------
def history(session: Session, p: Portfolio, positions: dict[int, Position]) -> dict[str, Any]:
    """Daily value and profit of the portfolio next to the total index.

    ``return`` on a day is the profit so far (value after selling fees + sales + dividends -
    every rial put in) over every rial put in: the same figure as ``total_pnl_pct`` on the last
    day, so buying more never counts as a gain and selling never as a loss."""
    ids = [iid for iid, pos in positions.items() if pos.events]
    if not ids:
        return {"points": [], "return": None, "index_return": None}
    start = min(e.date for iid in ids for e in positions[iid].events)
    today = utcnow().date()
    types = dict(
        session.execute(
            select(Instrument.id, Instrument.instrument_type).where(Instrument.id.in_(ids))
        ).all()
    )
    keep = {i: 1 - fee_rates(session, types.get(i, "stock"), today)[1] for i in ids}
    closes: dict[int, dict[dt.date, float]] = defaultdict(dict)
    for iid, d, c in session.execute(
        select(PriceDaily.instrument_id, PriceDaily.date, PriceDaily.close).where(
            and_(PriceDaily.instrument_id.in_(ids), PriceDaily.date >= start),
            PriceDaily.close.is_not(None),
        )
    ):
        closes[int(iid)][d] = float(c or 0.0)
    index = dict(
        session.execute(
            select(MarketIndexDaily.date, MarketIndexDaily.close).where(
                MarketIndexDaily.index_code == TEDPIX, MarketIndexDaily.date >= start
            )
        ).all()
    )
    by_day: dict[dt.date, list[tuple[int, Event]]] = defaultdict(list)
    for iid in ids:
        for e in positions[iid].events:
            by_day[e.date].append((iid, e))
    # a trade on a holiday still counts: its day is in the walk even with no prices
    market_days = set(index) | {d for v in closes.values() for d in v}
    days = sorted({d for d in market_days | set(by_day) if d >= start})
    shares: dict[int, float] = defaultdict(float)
    last_px: dict[int, float] = {}
    put_in = 0.0
    taken_out = 0.0
    base_index: float | None = None
    points = []
    ret: float | None = None
    for d in days:
        for iid, e in by_day.get(d, []):
            shares[iid] += e.shares
            if e.kind in ("buy", "rights"):
                put_in += e.amount
            elif e.kind in ("sell", "dividend"):
                taken_out += e.amount
        for iid in ids:
            if d in closes[iid]:
                last_px[iid] = closes[iid][d]
        value = sum(max(shares[i], 0.0) * last_px.get(i, 0.0) * keep[i] for i in ids)
        ret = (value + taken_out - put_in) / put_in if put_in else None
        if base_index is None and d in index:
            base_index = float(index[d])
        points.append(
            {
                "date": d.isoformat(),
                "value": value,
                "return": ret,
                "index_return": (float(index[d]) / base_index - 1)
                if base_index and d in index
                else None,
            }
        )
    last_idx = next(
        (pt["index_return"] for pt in reversed(points) if pt["index_return"] is not None), None
    )
    return {"points": points, "return": ret, "index_return": last_idx}
