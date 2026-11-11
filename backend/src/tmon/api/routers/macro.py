"""Comparison with inflation (reads ``macro_series`` only) and fund NAV / ETF bubble."""

from __future__ import annotations

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from tmon.api.schemas import (
    CompareOut,
    CompareRow,
    FundOut,
    FundsOut,
    InflationOut,
    InflationReleaseOut,
)
from tmon.core.db import get_session
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
from tmon.ingest.tsetmc.risk_free import SERIES as RF_SERIES
from tmon.storage.models import FundNav, Instrument, MacroSeries, PriceDaily

router = APIRouter(tags=["macro"])
SessionDep = Annotated[Session, Depends(get_session)]

ASSETS: tuple[tuple[str, str, str], ...] = (
    ("usd_free", "tgju", "دلار بازار آزاد"),
    ("gold_18k", "tgju", "طلای ۱۸ عیار (گرم)"),
    ("coin_emami", "tgju", "سکه امامی"),
)
# leveraged funds list their leveraged unit, whose NAV the fund-level figure is not
LEVERAGED_FUND_TYPE = 22
SUSPECT_BUBBLE = 0.2


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
    symbols = dict(
        session.execute(
            select(Instrument.id, Instrument.symbol_fa).where(Instrument.id.in_(ids))
        ).all()
    )
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
        out.append(
            FundOut(
                reg_no=n.reg_no,
                name=n.name,
                symbol=symbols.get(n.instrument_id) if n.instrument_id else None,
                instrument_id=n.instrument_id,
                fund_type=n.fund_type,
                listed=n.instrument_id is not None,
                nav_date=n.date,
                cancel_nav=n.cancel_nav,
                issue_nav=n.issue_nav,
                net_asset=n.net_asset,
                price=float(price) if price is not None else None,
                bubble=b,
                bubble_note=note,
            )
        )
    return FundsOut(nav_date=nav_date, funds=out)
