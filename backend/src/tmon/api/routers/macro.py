"""Comparison with inflation (reads ``macro_series`` only) and fund NAV / ETF bubble."""

from __future__ import annotations

import logging
from datetime import date, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tmon.api.returns import period_table
from tmon.api.schemas import (
    CompareOut,
    CompareRow,
    FundOut,
    FundsOut,
    GoldOilOut,
    GoldRatioOut,
    InflationOut,
    InflationReleaseOut,
    LeveragedFundsOut,
    RightOut,
    RightsOut,
    SymbolsValueOut,
    SymbolValueOut,
)
from tmon.core.db import get_session
from tmon.domain import gold_ratio as gr
from tmon.domain.bubbles import RIGHT_NOMINAL, fund_kind, right_base_symbol, right_bubble
from tmon.domain.compare import (
    PeriodInflation,
    Release,
    annualised,
    months_back,
    period_inflation,
    real_return,
    value_on_or_before,
)
from tmon.ingest.macro.fipiran import bubble
from tmon.ingest.tsetmc.parsers import normalize_fa
from tmon.ingest.tsetmc.risk_free import SERIES as RF_SERIES
from tmon.storage.models import FundNav, Instrument, MacroSeries, PriceDaily, SectorName
from tmon.storage.objectstore import read_artifact
from tmon.tools.leveraged_funds import KEY as LEVERAGED_KEY

log = logging.getLogger(__name__)
router = APIRouter(tags=["macro"])
SessionDep = Annotated[Session, Depends(get_session)]

ASSETS: tuple[tuple[str, str, str], ...] = (
    ("usd_free", "tgju", "دلار بازار آزاد"),
    ("gold_18k", "tgju", "طلای ۱۸ عیار (گرم)"),
    ("coin_emami", "tgju", "سکه امامی"),
    ("coin_bahar", "tgju", "سکه بهار آزادی"),
)
# leveraged funds list their leveraged unit, whose NAV the fund-level figure is not
LEVERAGED_FUND_TYPE = 22
SUSPECT_BUBBLE = 0.2
# rights not traded within this many days of the newest right trade are left out
RIGHTS_RECENT_DAYS = 30


def _out(p: PeriodInflation | None, source: str) -> InflationOut | None:
    if p is None:
        return None
    return InflationOut(
        source=source,
        value=p.value,
        method=p.method,
        releases=[
            InflationReleaseOut(
                ref_period=r.ref_period,
                release_date=r.release_date,
                value=r.value,
                source_url=r.source_url,
            )
            for r in p.releases
        ],
    )


def _releases(session: Session, series: str, source: str) -> list[Release]:
    return [
        Release(m.ref_period, m.release_date or m.ref_period, m.value, m.source_url)
        for m in session.scalars(
            select(MacroSeries).where(MacroSeries.series == series, MacroSeries.source == source)
        )
    ]


def _row(
    series: str,
    source: str,
    label: str,
    a: tuple[date, float],
    b: tuple[date, float],
    infl: PeriodInflation | None,
) -> CompareRow:
    nominal = b[1] / a[1] - 1
    rr = real_return(nominal, infl.value) if infl else None
    return CompareRow(
        series=series,
        label=label,
        source=source,
        start_date=a[0],
        end_date=b[0],
        start_value=a[1],
        end_value=b[1],
        nominal_return=nominal,
        real_return=rr,
        beats_inflation=None if rr is None else rr > 0,
    )


@router.get("/compare", response_model=CompareOut)
def compare(
    session: SessionDep,
    months: Annotated[int, Query(ge=1, le=36)] = 12,
    inflation_source: Annotated[str, Query(pattern="^(sci|cbi)$")] = "sci",
) -> CompareOut:
    """Nominal and real return of free-market USD, gold, coin and the one-year treasury yield
    over the last ``months`` months, against inflation released by the as-of day (docs/07)."""
    as_of = session.scalar(
        select(func.max(MacroSeries.ref_period)).where(MacroSeries.source == "tgju")
    )
    if as_of is None:
        return CompareOut(months=months, inflation_source=inflation_source, rows=[])
    start = months_back(as_of, months)
    mom = _releases(session, "cpi_mom", inflation_source)
    yoy = _releases(session, "cpi_yoy", inflation_source)
    infl = period_inflation(mom, yoy, as_of, months)
    last_month = period_inflation(mom, [], as_of, 1)

    rows: list[CompareRow] = []
    for series, source, label in ASSETS:
        pts = [
            (d, v)
            for d, v in session.execute(
                select(MacroSeries.ref_period, MacroSeries.value)
                .where(MacroSeries.series == series, MacroSeries.source == source)
                .order_by(MacroSeries.ref_period)
            )
        ]
        a, b = value_on_or_before(pts, start), value_on_or_before(pts, as_of)
        if not a or not b or a[1] <= 0:
            rows.append(
                CompareRow(series=series, label=label, source=source, note="داده کافی نیست")
            )
        else:
            rows.append(_row(series, source, label, a, b, infl))

    rf = session.scalars(
        select(MacroSeries)
        .where(MacroSeries.series == RF_SERIES, MacroSeries.ref_period <= start)
        .order_by(MacroSeries.ref_period.desc())
        .limit(1)
    ).first()
    if rf is None:
        rows.append(
            CompareRow(
                series=RF_SERIES,
                label="اخزا",
                source="tsetmc:treasury-bills",
                note="نرخ اخزا برای ابتدای دوره ثبت نشده است",
            )
        )
    else:
        # the yield bought at the start, held for the horizon
        growth = (1 + rf.value) ** (months / 12)
        r = _row(
            RF_SERIES,
            rf.source,
            "اخزا (بازده تا سررسید، قفل‌شده در ابتدای دوره)",
            (rf.ref_period, 1.0),
            (as_of, growth),
            infl,
        )
        rows.append(r.model_copy(update={"start_value": rf.value, "end_value": None}))
    return CompareOut(
        as_of=as_of,
        months=months,
        inflation_source=inflation_source,
        inflation=_out(infl, inflation_source),
        monthly_inflation=_out(last_month, inflation_source),
        annualised_monthly=annualised(last_month.value) if last_month else None,
        rows=rows,
    )


@router.get("/funds", response_model=FundsOut)
def funds(session: SessionDep, listed_only: bool = True) -> FundsOut:
    """Latest NAV per fund (fipiran) and, for listed units, the bubble against the close of
    the same day (docs/06)."""
    nav_date = session.scalar(select(func.max(FundNav.date)))
    latest = (
        select(FundNav.reg_no, func.max(FundNav.date).label("d"))
        .group_by(FundNav.reg_no)
        .subquery()
    )
    q = select(FundNav).join(
        latest, (FundNav.reg_no == latest.c.reg_no) & (FundNav.date == latest.c.d)
    )
    if listed_only:
        q = q.where(FundNav.instrument_id.is_not(None))
    navs = session.scalars(q.order_by(FundNav.net_asset.desc().nulls_last())).all()
    ids = [n.instrument_id for n in navs if n.instrument_id]
    insts = {i.id: i for i in session.scalars(select(Instrument).where(Instrument.id.in_(ids)))}
    closes = {
        (iid, d): c
        for iid, d, c in session.execute(
            select(PriceDaily.instrument_id, PriceDaily.date, PriceDaily.close).where(
                PriceDaily.instrument_id.in_(ids),
                PriceDaily.date.in_({n.date for n in navs}),
            )
        )
    }
    out = []
    for n in navs:
        price = closes.get((n.instrument_id, n.date)) if n.instrument_id else None
        inst = insts.get(n.instrument_id) if n.instrument_id else None
        tags = (inst.tags or {}) if inst else {}
        kind, industry = fund_kind(
            tags.get("subsector_code"),
            n.fund_type,
            inst.instrument_type if inst else None,
            tags.get("fund_desc"),
        )
        b, note = None, None
        if n.instrument_id:
            if n.fund_type == LEVERAGED_FUND_TYPE:
                note = "صندوق اهرمی: NAV واحد معامله‌شونده در دسترس نیست"
            elif price is None:
                note = "قیمت پایانی روز NAV ثبت نشده است"
            else:
                b = bubble(float(price), n.cancel_nav)
                if b is not None and abs(b) > SUSPECT_BUBBLE:
                    note = "حباب غیرعادی؛ احتمال ناهمخوانی واحد یا تعدیل"
                elif n.date != nav_date:
                    note = "NAV این صندوق مال روزی قدیمی‌تر از بقیه است"
        out.append(
            FundOut(
                reg_no=n.reg_no,
                name=n.name,
                symbol=inst.symbol_fa if inst else None,
                instrument_id=n.instrument_id,
                fund_type=n.fund_type,
                kind=kind,
                industry=industry,
                listed=n.instrument_id is not None,
                nav_date=n.date,
                cancel_nav=n.cancel_nav,
                issue_nav=n.issue_nav,
                net_asset=n.net_asset,
                price=float(price) if price is not None else None,
                bubble=b,
                bubble_note=note,
                website=n.website,
                manager=n.manager,
            )
        )
    return FundsOut(nav_date=nav_date, funds=out)


@router.get("/funds/leveraged", response_model=LeveragedFundsOut)
def leveraged_funds() -> LeveragedFundsOut:
    """What each leveraged fund did against the market, from the PC's daily document
    (``tmon.tools.leveraged_funds``). Empty until that tool has run."""
    try:
        doc = read_artifact(LEVERAGED_KEY)
    except Exception:  # store unreachable: an empty section, not a failing page
        log.warning("%s unreadable", LEVERAGED_KEY, exc_info=True)
        doc = None
    return LeveragedFundsOut.model_validate(doc) if doc else LeveragedFundsOut()


@router.get("/rights", response_model=RightsOut)
def rights(session: SessionDep) -> RightsOut:
    """Recently traded right issues against their base stock: a right is worth the base close
    minus the nominal price, so the bubble is (price - value) / value (docs/06)."""
    rights_q = select(Instrument).where(
        Instrument.instrument_type == "right", Instrument.delisted_at.is_(None)
    )
    rts = {i.id: i for i in session.scalars(rights_q)}
    last = dict(
        session.execute(
            select(PriceDaily.instrument_id, func.max(PriceDaily.date))
            .where(PriceDaily.instrument_id.in_(rts), PriceDaily.close.is_not(None))
            .group_by(PriceDaily.instrument_id)
        ).all()
    )
    if not last:
        return RightsOut(nominal=RIGHT_NOMINAL, rights=[])
    as_of = max(last.values())
    since = as_of - timedelta(days=RIGHTS_RECENT_DAYS)
    last = {i: d for i, d in last.items() if d >= since}
    bases: dict[str, list[Instrument]] = {}
    want = {right_base_symbol(rts[i].symbol_fa) for i in last} - {None}
    for b in session.scalars(
        select(Instrument).where(
            Instrument.symbol_fa.in_(want), Instrument.instrument_type == "stock"
        )
    ):
        bases.setdefault(b.symbol_fa, []).append(b)
    out = []
    for iid, d in last.items():
        r = rts[iid]
        price = session.scalar(
            select(PriceDaily.close).where(PriceDaily.instrument_id == iid, PriceDaily.date == d)
        )
        if price is None:
            continue
        price = float(price)
        base_rows = []
        for b in bases.get(right_base_symbol(r.symbol_fa) or "", []):
            row = session.execute(
                select(PriceDaily.date, PriceDaily.close)
                .where(
                    PriceDaily.instrument_id == b.id,
                    PriceDaily.date <= d,
                    PriceDaily.close.is_not(None),
                )
                .order_by(PriceDaily.date.desc())
                .limit(1)
            ).first()
            if row and row[1] is not None:
                base_rows.append((row[0], b, float(row[1])))
        # a symbol can be reused by an old delisted instrument: take the newest price
        base = max(base_rows, key=lambda x: x[0]) if base_rows else None
        b_, value, note = None, None, None
        if base is None:
            note = "سهم پایه پیدا نشد"
        else:
            value = base[2] - RIGHT_NOMINAL
            b_ = right_bubble(price, base[2])
            if b_ is None:
                note = "قیمت سهم پایه به قیمت اسمی نرسیده است"
            elif base[0] != d:
                note = "سهم پایه در روز آخر معاملهٔ حق‌تقدم بسته بود"
            elif abs(b_) > SUSPECT_BUBBLE:
                note = "حباب غیرعادی؛ شاید سهم پایه هنوز تعدیل نشده یا قیمت پذیره‌نویسی اسمی نیست"
        out.append(
            RightOut(
                instrument_id=iid,
                symbol=r.symbol_fa,
                name=r.name_fa,
                date=d,
                price=price,
                base_id=base[1].id if base else None,
                base_symbol=base[1].symbol_fa if base else None,
                base_date=base[0] if base else None,
                base_close=base[2] if base else None,
                value=value,
                bubble=b_,
                bubble_note=note,
            )
        )
    out.sort(key=lambda x: (x.bubble is None or x.bubble_note is not None, x.bubble or 0.0))
    return RightsOut(as_of=as_of, nominal=RIGHT_NOMINAL, rights=out)


@router.get("/macro/gold-oil", response_model=GoldOilOut)
def gold_oil(session: SessionDep) -> GoldOilOut:
    """18k gold and the Emami coin against their gold value at the ounce and the free dollar,
    and Brent in ounces of gold, each against its own past (docs/reports/gold-oil-2026-11.md)."""
    newest = session.scalar(
        select(func.max(MacroSeries.ref_period)).where(MacroSeries.series == "gold_18k")
    )
    if newest is None:
        raise HTTPException(404, "no gold series yet")
    since = newest - timedelta(days=gr.RANK_DAYS + 7 * gr.MEAN_WEEKS + 30)
    points: dict[str, list[tuple[date, float]]] = {s: [] for s in (*gr.SERIES, gr.BAHAR)}
    for series, d, v in session.execute(
        select(MacroSeries.series, MacroSeries.ref_period, MacroSeries.value).where(
            MacroSeries.series.in_(points), MacroSeries.ref_period >= since
        )
    ):
        if v is not None:
            points[series].append((d, float(v)))
    g = gr.gold_oil(points)
    if g is None:
        raise HTTPException(404, "not enough gold history")

    def ratio(r: gr.Ratio) -> GoldRatioOut:
        return GoldRatioOut(
            value=r.value,
            mean_52w=r.mean_52w,
            deviation=r.deviation,
            pct_rank_3y=r.pct_rank_3y,
            state=r.state,
        )

    return GoldOilOut(
        week=g.week,
        usd_free=g.usd_free,
        gold_18k=g.gold_18k,
        coin_emami=g.coin_emami,
        gold_usd=g.gold_usd,
        brent_usd=g.brent_usd,
        gold_18k_fair=g.gold_18k_fair,
        coin_fair=g.coin_fair,
        usd_implied=g.usd_implied,
        gold_prem=ratio(g.gold_prem),
        coin_bubble=ratio(g.coin_bubble),
        oil_gold=ratio(g.oil_gold),
        coin_bahar=g.coin_bahar,
        coin_bahar_bubble=None if g.coin_bahar_bubble is None else ratio(g.coin_bahar_bubble),
        gold_prem_cuts=gr.GOLD_PREM_CUTS,
        coin_bubble_cuts=gr.COIN_BUBBLE_CUTS,
    )


# calendar-day return of api.returns that matches each period of /compare
_PERIOD_RETURN = {1: "ret_month", 3: "ret_3m", 12: "ret_year"}
_FUND_TYPES = ("etf_equity", "etf_fixed_income", "etf_mixed", "etf_leveraged", "etf_commodity")


@router.get("/compare/symbols", response_model=SymbolsValueOut)
def compare_symbols(
    session: SessionDep,
    months: Annotated[int, Query()] = 12,
    inflation_source: Annotated[str, Query(pattern="^(sci|cbi)$")] = "sci",
) -> SymbolsValueOut:
    """Every stock, fund and right that traded on the newest day: the bubble where a value is
    known (fund NAV, right = base - nominal), and the adjusted return over the period against
    inflation released by that day (docs/06)."""
    if months not in _PERIOD_RETURN:
        raise HTTPException(422, "months must be 1, 3 or 12")
    last = session.scalar(select(func.max(PriceDaily.date)))
    if last is None:
        return SymbolsValueOut(months=months, inflation_source=inflation_source, rows=[])
    yoy = _releases(session, "cpi_yoy", inflation_source)
    p_infl = period_inflation(_releases(session, "cpi_mom", inflation_source), yoy, last, months)
    infl = p_infl.value if p_infl else None
    infl_note = None
    known = [r for r in yoy if r.release_date <= last]
    if infl is None and known:
        # fewer monthly releases than months: spread the latest point-to-point figure evenly
        y = max(known, key=lambda r: r.ref_period).value
        infl = (1 + y) ** (months / 12) - 1
        infl_note = "تخمین: تورم نقطه‌به‌نقطه به‌طور یکنواخت روی ماه‌ها پخش شده است"
    periods = period_table(session, last)
    sectors = {
        c.strip().zfill(2): normalize_fa(n)
        for c, n in session.execute(select(SectorName.code, SectorName.name))
    }
    fund_rows = {f.instrument_id: f for f in funds(session).funds if f.instrument_id}
    right_rows = {r.instrument_id: r for r in rights(session).rights}
    traded = session.execute(
        select(PriceDaily, Instrument)
        .join(Instrument, Instrument.id == PriceDaily.instrument_id)
        .where(
            PriceDaily.date == last,
            PriceDaily.market_halt.is_(False),
            Instrument.instrument_type.in_(("stock", "right", *_FUND_TYPES)),
        )
    ).all()
    out = []
    for p, inst in traded:
        tags = inst.tags or {}
        fair, b, note = None, None, None
        industry = sectors.get((inst.sector_code or "").strip().zfill(2))
        if inst.instrument_type == "stock":
            kind = "سهم"
        elif inst.instrument_type == "right":
            kind = "حق‌تقدم"
            r = right_rows.get(inst.id)
            if r:
                fair, b, note = r.value, r.bubble, r.bubble_note
        else:
            f = fund_rows.get(inst.id)
            if f:
                kind, industry = f.kind or "صندوق", f.industry
                fair, b, note = f.cancel_nav, f.bubble, f.bubble_note
            else:
                kind, industry = fund_kind(
                    tags.get("subsector_code"), None, inst.instrument_type, tags.get("fund_desc")
                )
                note = "NAV این صندوق ثبت نشده است"
        pr = periods.get(inst.id)
        nominal = getattr(pr, _PERIOD_RETURN[months]) if pr else None
        out.append(
            SymbolValueOut(
                instrument_id=inst.id,
                symbol=inst.symbol_fa,
                name=inst.name_fa,
                kind=kind,
                industry=industry,
                close=None if p.close is None else float(p.close),
                traded_value=None if p.value is None else float(p.value),
                fair_value=fair,
                bubble=b,
                bubble_note=note,
                nominal_return=nominal,
                real_return=real_return(nominal, infl)
                if nominal is not None and infl is not None
                else None,
            )
        )
    # a right that did not trade on the newest day still has a bubble from its own last trade
    seen = {r.instrument_id for r in out}
    for r in right_rows.values():
        if r.instrument_id in seen:
            continue
        out.append(
            SymbolValueOut(
                instrument_id=r.instrument_id,
                symbol=r.symbol,
                name=r.name,
                kind="حق‌تقدم",
                close=r.price,
                fair_value=r.value,
                bubble=r.bubble,
                bubble_note=r.bubble_note or "در آخرین روز معامله نشد؛ قیمت آخرین معاملهٔ خودش",
            )
        )
    return SymbolsValueOut(
        prices_date=last,
        months=months,
        inflation_source=inflation_source,
        inflation=infl,
        inflation_note=infl_note,
        rows=out,
    )
