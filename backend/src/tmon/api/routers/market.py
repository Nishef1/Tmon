"""Market overview computed from the daily tables only (no intraday, no order book).

Everything here is end-of-day: breadth, the change-band histogram, real/legal money flow and the
mover tables. Each table uses the latest date whose coverage is broad, because the most recent day
is often only partially ingested.
"""

from __future__ import annotations

import datetime as dt
import statistics
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tmon.api.schemas import (
    MarketBand,
    MarketFlow,
    MarketIndexPoint,
    MarketMover,
    MarketOverviewOut,
    MarketSector,
)
from tmon.core.db import get_session
from tmon.core.engine_config import get_engine_config
from tmon.storage.models import (
    ClientTypeDaily,
    Instrument,
    MarketIndexDaily,
    PriceDaily,
    SectorName,
)

router = APIRouter(tags=["market"])
SessionDep = Annotated[Session, Depends(get_session)]

MIN_COVERAGE = 0.6  # a date counts as complete with this share of the busiest recent day's rows
TOP = 10
INDEX_NAMES = {
    get_engine_config().benchmarks.indices["tedpix"]: "شاخص کل",
    get_engine_config().benchmarks.indices["equal_weight"]: "شاخص کل (هم‌وزن)",
}
MAX_CHANGE = 0.5  # larger one-day moves are stale reference prices (reopening), not returns
NEAR_LIMIT = 0.029  # daily limits are not stored; the usual +-3% band is used instead
BANDS: list[tuple[str, float, float]] = [
    ("کمتر از −۴٪", -9.0, -0.04),
    ("−۴٪ تا −۲٪", -0.04, -0.02),
    ("−۲٪ تا −۰٫۵٪", -0.02, -0.005),
    ("نزدیک صفر", -0.005, 0.005),
    ("۰٫۵٪ تا ۲٪", 0.005, 0.02),
    ("۲٪ تا ۴٪", 0.02, 0.04),
    ("بیش از ۴٪", 0.04, 9.0),
]


def _latest_full(session: Session, date_col: Any) -> dt.date | None:
    """Latest date with broad coverage among stocks (funds and bonds are far more numerous)."""
    rows = session.execute(
        select(date_col, func.count())
        .join(Instrument, Instrument.id == date_col.class_.instrument_id)
        .where(Instrument.instrument_type == "stock")
        .group_by(date_col)
        .order_by(date_col.desc())
        .limit(15)
    ).all()
    if not rows:
        return None
    biggest = max(n for _, n in rows)
    for d, n in rows:
        if n >= MIN_COVERAGE * biggest:
            return d  # type: ignore[no-any-return]
    return None


def _mover(i: Instrument, **kw: float | None) -> MarketMover:
    return MarketMover(symbol=i.symbol_fa, name=i.name_fa, **kw)


@router.get("/market/overview", response_model=MarketOverviewOut)
def overview(session: SessionDep) -> MarketOverviewOut:
    pd_ = _latest_full(session, PriceDaily.date)
    if pd_ is None:
        return MarketOverviewOut(available=False)

    rows = session.execute(
        select(Instrument, PriceDaily)
        .join(PriceDaily, PriceDaily.instrument_id == Instrument.id)
        .where(PriceDaily.date == pd_, Instrument.instrument_type == "stock")
    ).all()
    fd = _latest_full(session, ClientTypeDaily.date)
    cl: dict[int, ClientTypeDaily] = {}
    if fd is not None:
        cl = {
            c.instrument_id: c
            for c in session.scalars(select(ClientTypeDaily).where(ClientTypeDaily.date == fd))
        }

    chg: dict[int, float] = {}
    outliers = 0
    for i, p in rows:
        if p.close and p.prev_close and p.prev_close > 0 and not p.market_halt:
            move = float(p.close) / float(p.prev_close) - 1.0
            if abs(move) <= MAX_CHANGE:
                chg[i.id] = move
            else:
                outliers += 1
    ch = list(chg.values())
    out = MarketOverviewOut(
        available=True,
        price_date=str(pd_),
        n_stocks=len(ch),
        up=sum(c > 0.0005 for c in ch),
        down=sum(c < -0.0005 for c in ch),
        flat=sum(abs(c) <= 0.0005 for c in ch),
        total_value=sum(float(p.value or 0) for _, p in rows),
        median_change=statistics.median(ch) if ch else None,
    )
    with_limits = [
        p for i, p in rows if i.id in chg and p.limit_up and p.limit_down and p.close is not None
    ]
    out.limits_exact = len(with_limits) >= 0.8 * len(ch) > 0
    if out.limits_exact:  # real daily price limits stored by the poller / threshold backfill
        out.at_limit_up = sum(float(p.close or 0) >= float(p.limit_up or 0) for p in with_limits)
        out.at_limit_down = sum(
            float(p.close or 0) <= float(p.limit_down or 0) for p in with_limits
        )
    else:
        out.at_limit_up = sum(c >= NEAR_LIMIT for c in ch)
        out.at_limit_down = sum(c <= -NEAR_LIMIT for c in ch)
    out.n_outliers = outliers
    out.bands = [MarketBand(label=lb, count=sum(lo < c <= hi for c in ch)) for lb, lo, hi in BANDS]

    ins = {i.id: i for i, _ in rows}
    val = {i.id: float(p.value or 0) for i, p in rows}
    nets: dict[int, float] = {}
    for k, c in cl.items():
        if k in ins and c.buy_value_i is not None and c.sell_value_i is not None:
            nets[k] = float(c.buy_value_i) - float(c.sell_value_i)

    traded = sorted((k for k in chg if val[k] > 0), key=lambda k: chg[k])
    out.gainers = [_mover(ins[k], change=chg[k], value=val[k]) for k in reversed(traded[-TOP:])]
    out.losers = [_mover(ins[k], change=chg[k], value=val[k]) for k in traded[:TOP]]
    out.by_value = [
        _mover(ins[k], change=chg.get(k), value=val[k])
        for k in sorted(val, key=lambda k: -val[k])[:TOP]
    ]
    ranked = sorted(nets, key=lambda k: nets[k])
    out.inflow = [
        _mover(ins[k], change=chg.get(k), value=val[k], net_real_flow=nets[k])
        for k in reversed(ranked[-TOP:])
        if nets[k] > 0
    ]
    out.outflow = [
        _mover(ins[k], change=chg.get(k), value=val[k], net_real_flow=nets[k])
        for k in ranked[:TOP]
        if nets[k] < 0
    ]

    if fd is not None and nets:
        ids = list(nets)

        def tot(a: str) -> float:
            return sum(float(getattr(cl[k], a) or 0) for k in ids)

        bc, sc = tot("buy_count_i"), tot("sell_count_i")
        pcb = tot("buy_value_i") / bc if bc else None
        pcs = tot("sell_value_i") / sc if sc else None
        out.flow = MarketFlow(
            date=str(fd),
            n_symbols=len(ids),
            real_buy_value=tot("buy_value_i"),
            real_sell_value=tot("sell_value_i"),
            legal_buy_value=tot("buy_value_n"),
            legal_sell_value=tot("sell_value_n"),
            real_net=tot("buy_value_i") - tot("sell_value_i"),
            per_capita_buy=pcb,
            per_capita_sell=pcs,
            power=(pcb / pcs) if pcb and pcs else None,
        )

    grp: dict[str, list[int]] = {}
    for k, i in ins.items():
        if i.sector_code:
            grp.setdefault(i.sector_code, []).append(k)
    names = {s.code: s.name for s in session.scalars(select(SectorName))}
    sectors = []
    for code, ks in grp.items():
        cs = [chg[k] for k in ks if k in chg]
        ns = [nets[k] for k in ks if k in nets]
        sectors.append(
            MarketSector(
                sector_code=code,
                name=names.get(code.zfill(2)),
                n=len(ks),
                avg_change=sum(cs) / len(cs) if cs else None,
                value=sum(val[k] for k in ks),
                net_real_flow=sum(ns) if ns else None,
            )
        )
    out.sectors = sorted(sectors, key=lambda x: -x.value)[:15]

    for code in session.scalars(select(MarketIndexDaily.index_code).distinct()):
        last = session.execute(
            select(MarketIndexDaily.date, MarketIndexDaily.close)
            .where(MarketIndexDaily.index_code == code)
            .order_by(MarketIndexDaily.date.desc())
            .limit(2)
        ).all()
        if last:
            prev = last[1][1] if len(last) > 1 else None
            out.indices.append(
                MarketIndexPoint(
                    code=INDEX_NAMES.get(code, code),
                    close=last[0][1],
                    change=(last[0][1] / prev - 1) if prev else None,
                    date=str(last[0][0]),
                )
            )
    return out
