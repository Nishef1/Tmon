"""Market overview computed from the daily tables only (no intraday, no order book).

Everything here is end-of-day: breadth, the change-band histogram, real/legal money flow and the
mover tables. Each table uses the latest date whose coverage is broad, because the most recent day
is often only partially ingested.
"""

from __future__ import annotations

import datetime as dt
import statistics
import threading
from itertools import pairwise
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tmon.api.returns import MAX_DAY_MOVE
from tmon.api.schemas import (
    BreadthDay,
    Candle,
    IndexReturn,
    IndexSeries,
    MarketBand,
    MarketFlow,
    MarketIndexOut,
    MarketIndexPoint,
    MarketMover,
    MarketOverviewOut,
    MarketSector,
)
from tmon.core.db import get_session
from tmon.core.engine_config import get_engine_config
from tmon.features import columns as colmod
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
MAX_CHANGE = MAX_DAY_MOVE  # larger one-day moves are stale reference prices, not returns
NEAR_LIMIT = 0.029  # daily limits are not stored; the usual +-3% band is used instead
BANDS: list[tuple[str, float, float]] = [
    ("کمتر از −۴٪", -9.0, -0.04),
    ("−۴٪ تا −۲٪", -0.04, -0.02),
    ("−۲٪ تا −۰.۵٪", -0.02, -0.005),
    ("نزدیک صفر", -0.005, 0.005),
    ("۰.۵٪ تا ۲٪", 0.005, 0.02),
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


def _mover(
    i: Instrument, sector: str | None, close: float | None, **kw: float | None
) -> MarketMover:
    return MarketMover(
        instrument_id=i.id,
        symbol=i.symbol_fa,
        name=i.name_fa,
        sector_name=sector,
        close=close,
        **kw,
    )


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

    names = {s.code: s.name for s in session.scalars(select(SectorName))}
    close = {i.id: float(p.close) if p.close else None for i, p in rows}

    def mv(k: int, **kw: float | None) -> MarketMover:
        return _mover(ins[k], names.get(ins[k].sector_code or ""), close[k], **kw)

    traded = sorted((k for k in chg if val[k] > 0), key=lambda k: chg[k])
    out.gainers = [mv(k, change=chg[k], value=val[k]) for k in reversed(traded[-TOP:])]
    out.losers = [mv(k, change=chg[k], value=val[k]) for k in traded[:TOP]]
    out.by_value = [
        mv(k, change=chg.get(k), value=val[k]) for k in sorted(val, key=lambda k: -val[k])[:TOP]
    ]
    ranked = sorted(nets, key=lambda k: nets[k])
    out.inflow = [
        mv(k, change=chg.get(k), value=val[k], net_real_flow=nets[k])
        for k in reversed(ranked[-TOP:])
        if nets[k] > 0
    ]
    out.outflow = [
        mv(k, change=chg.get(k), value=val[k], net_real_flow=nets[k])
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
    out.sectors = sorted(sectors, key=lambda x: -x.value)

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


INDEX_KEYS: list[tuple[str, str]] = [("tedpix", "شاخص کل"), ("equal_weight", "شاخص کل (هم‌وزن)")]
INDEX_RETURNS = [("هفته", 7), ("ماه", 30), ("سه ماه", 90), ("سال", 365)]
BREADTH_DAYS = 30


def _index_series(
    session: Session, key: str, name: str, days: int, value_by_day: dict[dt.date, float]
) -> IndexSeries | None:
    code = get_engine_config().benchmarks.indices.get(key)
    if code is None:
        return None
    rows = list(
        reversed(
            session.execute(
                select(
                    MarketIndexDaily.date,
                    MarketIndexDaily.close,
                    MarketIndexDaily.high,
                    MarketIndexDaily.low,
                )
                .where(MarketIndexDaily.index_code == code)
                .order_by(MarketIndexDaily.date.desc())
                .limit(max(days, 300) + 1)
            ).all()
        )
    )
    if len(rows) < 2:
        return None
    candles = []
    for (_, prev_close, _, _), (d, close, high, low) in pairwise(rows):
        # the feed has no open: it is the previous close, or the nearest edge of the day when the
        # index gapped past it, so a gap shows as a gap between candles and not as a long shadow
        hi = max(x for x in (high, close) if x is not None)
        lo = min(x for x in (low, close) if x is not None)
        opened = min(max(prev_close, lo), hi)
        candles.append(
            Candle(
                date=d,
                open=opened,
                high=hi,
                low=lo,
                close=close,
                volume=value_by_day.get(d),
            )
        )
    last_d, last_c, last_h, last_l = rows[-1]
    prev_c = rows[-2][1]
    year = [r for r in rows if r[0] > last_d - dt.timedelta(days=365)]
    y_hi = max(r[2] if r[2] is not None else r[1] for r in year)
    y_lo = min(r[3] if r[3] is not None else r[1] for r in year)

    def back(days_back: int) -> float | None:
        target = last_d - dt.timedelta(days=days_back)
        base = [r for r in rows if r[0] <= target]
        if not base or target - base[-1][0] > dt.timedelta(days=10):
            return None
        return last_c / base[-1][1] - 1.0

    span = (last_h - last_l) if last_h is not None and last_l is not None else None
    return IndexSeries(
        key="tedpix" if key == "tedpix" else "equal_weight",
        name=name,
        date=str(last_d),
        close=last_c,
        prev_close=prev_c,
        change=last_c / prev_c - 1.0 if prev_c else None,
        high=last_h,
        low=last_l,
        range_pct=(last_h / last_l - 1.0) if last_h and last_l else None,
        position=((last_c - last_l) / span) if span and last_l is not None else None,
        year_high=y_hi,
        year_low=y_lo,
        from_year_high=last_c / y_hi - 1.0,
        above_year_low=last_c / y_lo - 1.0,
        returns=[IndexReturn(label=lb, value=back(n)) for lb, n in INDEX_RETURNS],
        candles=candles[-days:],
    )


_index_cache: dict[int, tuple[tuple[object, ...], MarketIndexOut]] = {}
_index_lock = threading.Lock()


@router.get("/market/index", response_model=MarketIndexOut)
def index_detail(
    session: SessionDep, days: Annotated[int, Query(ge=20, le=1500)] = 250
) -> MarketIndexOut:
    """The two official indices with candles, the day's range and period returns, plus breadth,
    value and median move of the last full days. End-of-day only. The answer is kept while the
    stored bars and index rows are unchanged (a fingerprint, never a clock)."""
    last = _latest_full(session, PriceDaily.date)
    if last is None:
        return MarketIndexOut(available=False)
    idx = session.execute(
        select(func.count(), func.max(MarketIndexDaily.date), func.sum(MarketIndexDaily.close))
    ).one()
    key = (*colmod.price_fingerprint(session, last), *idx, get_engine_config().benchmarks.indices)
    with _index_lock:
        hit = _index_cache.get(days)
        if hit is not None and hit[0] == key:
            return hit[1]
    out = _build_index(session, days, last)
    with _index_lock:
        if len(_index_cache) >= 8:
            _index_cache.clear()
        _index_cache[days] = (key, out)
    return out


def _build_index(session: Session, days: int, last: dt.date) -> MarketIndexOut:
    since = last - dt.timedelta(days=int(max(days, 300) * 1.6) + 10)
    by_day = session.execute(
        select(PriceDaily.date, func.sum(PriceDaily.value))
        .join(Instrument, Instrument.id == PriceDaily.instrument_id)
        .where(Instrument.instrument_type == "stock", PriceDaily.date >= since)
        .group_by(PriceDaily.date)
    ).all()
    value_by_day = {d: float(v or 0.0) for d, v in by_day}
    series = [
        s
        for key, name in INDEX_KEYS
        if (s := _index_series(session, key, name, days, value_by_day)) is not None
    ]
    if not series:
        return MarketIndexOut(available=False)

    rows = session.execute(
        select(PriceDaily.date, PriceDaily.close, PriceDaily.prev_close, PriceDaily.market_halt)
        .join(Instrument, Instrument.id == PriceDaily.instrument_id)
        .where(
            Instrument.instrument_type == "stock",
            PriceDaily.date > last - dt.timedelta(days=BREADTH_DAYS * 2 + 10),
            PriceDaily.date <= last,
        )
    ).all()
    per: dict[dt.date, list[float]] = {}
    seen: dict[dt.date, int] = {}
    for d, close, prev, halt in rows:
        seen[d] = seen.get(d, 0) + 1
        if close and prev and prev > 0 and not halt:
            move = float(close) / float(prev) - 1.0
            if abs(move) <= MAX_CHANGE:
                per.setdefault(d, []).append(move)
    biggest = max(seen.values(), default=0)
    days_out = [
        BreadthDay(
            date=str(d),
            n=len(ch),
            up=sum(c > 0.0005 for c in ch),
            down=sum(c < -0.0005 for c in ch),
            flat=sum(abs(c) <= 0.0005 for c in ch),
            value=value_by_day.get(d, 0.0),
            median_change=statistics.median(ch) if ch else None,
        )
        for d, ch in sorted(per.items())
        if seen[d] >= MIN_COVERAGE * biggest
    ][-BREADTH_DAYS:]
    return MarketIndexOut(
        available=True, as_of=max(s.date for s in series), series=series, days=days_out
    )
