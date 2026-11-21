"""Industries as the consensus of their symbols: candles, returns, breadth, money flow and a
row per symbol. End-of-day only; the candles are described in ``tmon.api.industry_series``."""

from __future__ import annotations

import datetime as dt
import threading
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tmon.api.industry_series import (
    HORIZONS,
    Composite,
    Trend,
    composites,
    horizon_return,
    load_adjusted,
    member_moves,
    spark,
    trend_table,
)
from tmon.api.returns import day_change, period_table
from tmon.api.routers.dashboard import _ranking_doc, _turning_doc, decide
from tmon.api.routers.market import _latest_full
from tmon.api.schemas import (
    Candle,
    IndustryBreadth,
    IndustryCard,
    IndustryDetail,
    IndustryFlowDay,
    IndustryMember,
    IndustryOverview,
    IndustryReturn,
    MarketBlock,
)
from tmon.api.slugs import sector_slug, slugify
from tmon.core.db import get_session
from tmon.core.engine_config import get_engine_config
from tmon.core.memory import release_memory
from tmon.features import columns as colmod
from tmon.storage.models import (
    ClientTypeDaily,
    Instrument,
    MarketIndexDaily,
    PriceDaily,
    SectorName,
)

# The overview is kept while the data behind it is unchanged (a fingerprint, never a clock).
_overview_cache: dict[str, object] = {}
_overview_lock = threading.Lock()

router = APIRouter(tags=["industries"])
SessionDep = Annotated[Session, Depends(get_session)]

FLOW_DAYS = 30
NEAR_HIGH = -0.03  # "near the year's high": within 3%
# derived columns every member row carries, and the ones whose industry median is shown
DETAIL_COLUMNS = [c.key for c in colmod.CATALOG if c.kind != "text"]
OVERVIEW_MEDIANS = ["pe_ttm", "pb", "roe", "beta_90d", "vol_vs_30", "real_net_pct"]
MEDIAN_COLUMNS = [
    "pe_ttm", "pb", "ps_ttm", "roe", "net_margin", "beta_90d", "vol_vs_30",
    "real_net_pct", "ret_1m", "ret_1y", "to_high_1y", "float_pct", "debt_to_assets",
]  # fmt: skip


def _names(session: Session) -> dict[str, str]:
    rows = session.execute(select(SectorName.code, SectorName.name))
    return {c.strip().zfill(2): n for c, n in rows}


def _code(code: str) -> str:
    return code.strip().zfill(2)


def _market_returns(
    session: Session, last: dt.date
) -> tuple[float | None, dict[str, float | None]]:
    """The exchange's equal-weight index: its move on the last day and over each horizon."""
    code = get_engine_config().benchmarks.indices.get("equal_weight")
    if code is None:
        return None, {}
    rows = session.execute(
        select(MarketIndexDaily.date, MarketIndexDaily.close)
        .where(
            MarketIndexDaily.index_code == code,
            MarketIndexDaily.date <= last,
            MarketIndexDaily.date >= last - dt.timedelta(days=400),
        )
        .order_by(MarketIndexDaily.date)
    ).all()
    if len(rows) < 2 or rows[-1][0] != last:
        return None, {}
    day = rows[-1][1] / rows[-2][1] - 1.0
    out: dict[str, float | None] = {}
    for key, (_label, back) in HORIZONS.items():
        target = last - dt.timedelta(days=back)
        base = [r for r in rows if r[0] <= target]
        ok = bool(base) and target - base[-1][0] <= dt.timedelta(days=10)
        out[key] = rows[-1][1] / base[-1][1] - 1.0 if ok else None
    return day, out


def _flows(session: Session, sector_of: dict[int, str]) -> dict[str, float]:
    """Net real-investor money on the latest day with broad coverage, per sector."""
    fd = _latest_full(session, ClientTypeDaily.date)
    if fd is None:
        return {}
    net: dict[str, float] = {}
    for c in session.scalars(select(ClientTypeDaily).where(ClientTypeDaily.date == fd)):
        sec = sector_of.get(c.instrument_id)
        if sec and c.buy_value_i is not None and c.sell_value_i is not None:
            net[sec] = net.get(sec, 0.0) + float(c.buy_value_i) - float(c.sell_value_i)
    return net


def _candles(c: Composite | None, days: int) -> list[Candle]:
    if c is None:
        return []
    # the shown open is the previous close, kept inside the day's range (as on the index page):
    # the members' own average open can sit above a close that is still above yesterday's, and a
    # red candle on a rising day reads as a contradiction
    out: list[Candle] = []
    for i, (d, o, h, lo, cl) in enumerate(
        zip(c.dates, c.open, c.high, c.low, c.close, strict=True)
    ):
        hi_, lo_ = max(h, cl), min(lo, cl)
        opened = min(max(c.close[i - 1], lo_), hi_) if i else o
        out.append(Candle(date=d, open=opened, high=hi_, low=lo_, close=cl, volume=None))
    return out[-days:]


def _day(c: Composite | None) -> float | None:
    return c.close[-1] / c.close[-2] - 1.0 if c is not None and len(c.close) > 1 else None


@router.get("/industries/overview", response_model=IndustryOverview)
def overview(session: SessionDep) -> IndustryOverview:
    """One card per industry: the consensus move of its symbols, breadth, value and money."""
    last = _latest_full(session, PriceDaily.date)
    if last is None:
        return IndustryOverview(available=False)
    fd = _latest_full(session, ClientTypeDaily.date)
    key = colmod.data_key(session, last, fd)
    with _overview_lock:  # one request builds it; the others wait and then find it kept
        if _overview_cache.get("key") != key:
            _overview_cache["key"], _overview_cache["doc"] = key, _build_overview(session, last)
            release_memory()
        return _overview_cache["doc"]  # type: ignore[return-value]


def _build_overview(session: Session, last: dt.date) -> IndustryOverview:
    adj, sector = load_adjusted(session, last)
    moves = member_moves(adj)
    eq = composites(moves, sector, "equal")
    va = composites(moves, sector, "value")
    trend = trend_table(adj, last)
    names = _names(session)
    value_today = {
        int(i): float(v or 0.0)
        for i, v in adj.filter(adj["date"] == last).select("instrument_id", "value").iter_rows()
    }
    total = sum(value_today.values()) or 1.0
    flow = _flows(session, sector)
    mday, _ = _market_returns(session, last)
    table = colmod.compute(session, last, _latest_full(session, ClientTypeDaily.date))

    cards: list[IndustryCard] = []
    for sec, c in eq.items():
        if not sec or not c.dates or c.dates[-1] != last:
            continue
        ids = [i for i, s in sector.items() if s == sec and i in trend]
        v = sum(value_today.get(i, 0.0) for i in ids)
        cards.append(
            IndustryCard(
                code=sec,
                slug=sector_slug(names.get(_code(sec))),
                name=names.get(_code(sec), sec),
                n=sum(1 for s in sector.values() if s == sec),
                n_traded=c.members[-1],
                day=_day(c),
                day_value=_day(va.get(sec)),
                week=horizon_return(c, last, HORIZONS["week"][1]),
                month=horizon_return(c, last, HORIZONS["month"][1]),
                m3=horizon_return(c, last, HORIZONS["m3"][1]),
                year=horizon_return(c, last, HORIZONS["year"][1]),
                value=v,
                value_share=v / total,
                net_real_flow=flow.get(sec),
                up=c.up[-1],
                down=c.down[-1],
                flat=c.flat[-1],
                above_sma20=sum(1 for i in ids if trend[i].above_sma20),
                n_trend=sum(1 for i in ids if trend[i].above_sma20 is not None),
                spark=spark(c),
                medians=colmod.medians(
                    [table.rows[i] for i in ids if i in table.rows], OVERVIEW_MEDIANS
                ),
            )
        )
    cards.sort(key=lambda x: -x.value)
    return IndustryOverview(
        available=True,
        as_of=str(last),
        market_day=mday,
        industries=cards,
        market=MarketBlock.model_validate(colmod.market_summary(session, table)),
    )


@router.get("/industries/{code}/detail", response_model=IndustryDetail)
def detail(
    code: str, session: SessionDep, days: Annotated[int, Query(ge=20, le=400)] = 250
) -> IndustryDetail:
    """One industry: consensus candles of all its symbols and a row for each symbol."""
    sec = code.strip()
    last = _latest_full(session, PriceDaily.date)
    names = _names(session)
    if not sec.isdigit():  # the readable address: the industry's name
        want = slugify(sec)
        sec = next((k for k, n in names.items() if want and sector_slug(n) == want), "")
    if last is None or not sec.isdigit() or _code(sec) not in names:
        raise HTTPException(404, "industry not found")
    insts = list(
        session.scalars(
            select(Instrument).where(
                Instrument.instrument_type == "stock", Instrument.sector_code == sec
            )
        )
    )
    adj, sector = load_adjusted(session, last, [sec])
    moves = member_moves(adj)
    eq = composites(moves, sector, "equal").get(sec)
    va = composites(moves, sector, "value").get(sec)
    if eq is None or not eq.dates or eq.dates[-1] != last:
        raise HTTPException(404, "industry has no trades on the last day")
    trend: dict[int, Trend] = trend_table(adj, last)

    total = float(
        session.scalar(
            select(func.sum(PriceDaily.value))
            .join(Instrument, Instrument.id == PriceDaily.instrument_id)
            .where(Instrument.instrument_type == "stock", PriceDaily.date == last)
        )
        or 0.0
    )
    day_value = {
        int(i): float(v or 0.0)
        for i, v in adj.filter(adj["date"] == last).select("instrument_id", "value").iter_rows()
    }
    value = sum(day_value.values())

    fd = _latest_full(session, ClientTypeDaily.date)
    nets: dict[int, float] = {}
    flow_days: dict[dt.date, float] = {}
    for c in session.scalars(
        select(ClientTypeDaily).where(
            ClientTypeDaily.instrument_id.in_([i.id for i in insts]),
            ClientTypeDaily.date >= last - dt.timedelta(days=FLOW_DAYS * 2),
            ClientTypeDaily.date <= last,
        )
    ):
        if c.buy_value_i is None or c.sell_value_i is None:
            continue
        net = float(c.buy_value_i) - float(c.sell_value_i)
        flow_days[c.date] = flow_days.get(c.date, 0.0) + net
        if c.date == fd:
            nets[c.instrument_id] = net

    _mday, mret = _market_returns(session, last)
    returns: list[IndustryReturn] = []
    for key, (label, back) in HORIZONS.items():
        r = horizon_return(eq, last, back)
        m = mret.get(key)
        gap = None if r is None or m is None else r - m
        returns.append(IndustryReturn(label=label, value=r, vs_market=gap))

    # today's move of each symbol, and the points it added to the equal-weight industry move
    today = moves.filter(moves["date"] == last)
    rc = {int(i): float(x) - 1.0 for i, x in today.select("instrument_id", "rc").iter_rows()}
    n_today = len(rc) or 1
    periods = period_table(session, last)
    ranking, turning = _ranking_doc(), _turning_doc()
    bars = {
        p.instrument_id: p
        for p in session.scalars(
            select(PriceDaily).where(
                PriceDaily.date == last, PriceDaily.instrument_id.in_([i.id for i in insts])
            )
        )
    }
    table = colmod.compute(session, last, fd)
    members: list[IndustryMember] = []
    for inst in insts:
        tr = trend.get(inst.id)
        if tr is None:
            continue
        p = bars.get(inst.id)
        close = float(p.close) if p and p.close else None
        prev = float(p.prev_close) if p and p.prev_close else None
        pr = periods.get(inst.id)
        d = decide(inst, ranking, None, turning)
        members.append(
            IndustryMember(
                instrument_id=inst.id,
                symbol=inst.symbol_fa,
                symbol_slug=slugify(inst.symbol_fa) or str(inst.id),
                name=inst.name_fa,
                close=close,
                day=day_change(close, prev),
                week=pr.ret_week if pr else None,
                month=pr.ret_month if pr else None,
                m3=pr.ret_3m if pr else None,
                year=pr.ret_year if pr else None,
                value=day_value.get(inst.id),
                value_share=(day_value.get(inst.id, 0.0) / value) if value > 0 else None,
                net_real_flow=nets.get(inst.id),
                contrib=(rc[inst.id] / n_today) if inst.id in rc else None,
                verdict=d.verdict,
                verdict_label=d.label,
                gauge=d.gauge,
                from_year_high=tr.from_year_high,
                above_sma20=tr.above_sma20,
                spark=tr.spark,
                cols={k: table.rows.get(inst.id, {}).get(k) for k in DETAIL_COLUMNS},
            )
        )
    members.sort(key=lambda m: -(m.value or 0.0))
    ts = [trend[m.instrument_id] for m in members]
    return IndustryDetail(
        code=sec,
        slug=sector_slug(names[_code(sec)]),
        name=names[_code(sec)],
        as_of=str(last),
        n_members=len(insts),
        n_traded=len(members),
        day=_day(eq),
        day_value=_day(va),
        value=value,
        value_share=value / total if total > 0 else 0.0,
        net_real_flow=sum(nets.values()) if nets else None,
        flow_date=str(fd) if fd else None,
        returns=returns,
        medians=colmod.medians(
            [table.rows[m.instrument_id] for m in members if m.instrument_id in table.rows],
            MEDIAN_COLUMNS,
        ),
        market_medians=colmod.medians(list(table.rows.values()), MEDIAN_COLUMNS),
        breadth=IndustryBreadth(
            n=eq.members[-1],
            up=eq.up[-1],
            down=eq.down[-1],
            flat=eq.flat[-1],
            above_sma20=sum(1 for t in ts if t.above_sma20),
            above_sma50=sum(1 for t in ts if t.above_sma50),
            near_year_high=sum(
                1 for t in ts if t.from_year_high is not None and t.from_year_high >= NEAR_HIGH
            ),
            n_trend=sum(1 for t in ts if t.above_sma20 is not None),
        ),
        flow=[IndustryFlowDay(date=str(d), net_real=v) for d, v in sorted(flow_days.items())][
            -FLOW_DAYS:
        ],
        candles=_candles(eq, days),
        candles_value=_candles(va, days),
        members=members,
    )
