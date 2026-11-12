from __future__ import annotations

import datetime as dt
from typing import Annotated

import polars as pl
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from tmon.api.routers.recommendations import instrument_out, signal_out
from tmon.api.schemas import (
    AgmDecisionOut,
    AgmInputOut,
    BookLevelOut,
    Candle,
    CodalLetterOut,
    CorporateEventOut,
    FeatureValue,
    InstrumentDetail,
    LiveOut,
)
from tmon.core.db import get_session
from tmon.core.engine_config import get_engine_config
from tmon.core.timeutil import TEHRAN, utcnow
from tmon.domain.agm import AgmInputs, hold_or_sell, monthly_from_annual
from tmon.domain.rules import CostModel, MissingRuleError, RuleBook
from tmon.features.adjustment import apply_adjustments
from tmon.features.builder import get_feature_set
from tmon.ingest.tsetmc.risk_free import SERIES as RF_SERIES
from tmon.storage.models import (
    CodalLetter,
    CorporateEvent,
    FeatureRow,
    Instrument,
    IntradaySnapshot,
    MacroSeries,
    OrderBookSnapshot,
    PriceDaily,
    Signal,
)

router = APIRouter(tags=["instruments"])
SessionDep = Annotated[Session, Depends(get_session)]

# Features shown on the instrument page; each has a glossary entry in the frontend.
SHOWN_FEATURES = (
    "rsi_14", "macd_hist_pct", "adx_14", "atr_14_pct", "bb_pct_b", "vwap_gap",
    "ind_buy_power", "ind_net_flow_ratio", "rel_volume", "smart_money_flag",
    "mkt_ret_ew", "breadth",
)  # fmt: skip

LETTERS_SHOWN = 30  # latest Codal letters on the instrument page
EVENTS_SHOWN = 20  # latest Codal events on the instrument page
STALE_AFTER_SECONDS = 300  # a snapshot older than this is shown as stale

PRICE_FIELDS = ("open", "high", "low", "close", "last", "prev_close", "volume")


@router.get("/instruments/{instrument_id}", response_model=InstrumentDetail)
def instrument_detail(
    instrument_id: int,
    session: SessionDep,
    days: Annotated[int, Query(ge=20, le=1500)] = 250,
) -> InstrumentDetail:
    """Adjusted daily candles (never raw prices), the latest stored features and this symbol's
    published signals."""
    inst = session.get(Instrument, instrument_id)
    if inst is None:
        raise HTTPException(status_code=404, detail="نماد پیدا نشد")

    rows = session.execute(
        select(PriceDaily)
        .where(PriceDaily.instrument_id == instrument_id, PriceDaily.market_halt.is_(False))
        .order_by(PriceDaily.date.desc())
        .limit(days + 1)
    ).scalars()
    data: dict[str, list[object]] = {"instrument_id": [], "date": []}
    data.update({f: [] for f in PRICE_FIELDS})
    for r in reversed(list(rows)):  # I/O boundary: at most `days` rows of one symbol
        data["instrument_id"].append(r.instrument_id)
        data["date"].append(r.date)
        for f in PRICE_FIELDS:
            v = getattr(r, f)
            data[f].append(None if v is None else float(v))
    candles: list[Candle] = []
    if data["date"]:
        raw = pl.DataFrame(
            data,
            schema={
                "instrument_id": pl.Int64,
                "date": pl.Date,
                **dict.fromkeys(PRICE_FIELDS, pl.Float64),
            },
        )
        adj = apply_adjustments(raw).tail(days)
        candles = [
            Candle(date=d, open=o, high=h, low=lo, close=c, volume=v)
            for d, o, h, lo, c, v in adj.select(
                "date", "adj_open", "adj_high", "adj_low", "adj_close", "adj_volume"
            ).iter_rows()
        ]

    fs = get_feature_set("D1")
    frow = session.scalars(
        select(FeatureRow)
        .where(FeatureRow.instrument_id == instrument_id, FeatureRow.feature_set_version == fs.key)
        .order_by(FeatureRow.date.desc())
        .limit(1)
    ).first()
    features = (
        [FeatureValue(feature=f, value=(frow.values or {}).get(f)) for f in SHOWN_FEATURES]
        if frow
        else []
    )
    sigs = session.scalars(
        select(Signal)
        .where(Signal.instrument_id == instrument_id)
        .order_by(Signal.date.desc(), Signal.rank)
        .limit(50)
    ).all()
    events = session.scalars(
        select(CorporateEvent)
        .where(CorporateEvent.instrument_id == instrument_id)
        .order_by(CorporateEvent.announced_at.desc(), CorporateEvent.id.desc())
        .limit(EVENTS_SHOWN)
    ).all()
    letters = session.scalars(
        select(CodalLetter)
        .where(CodalLetter.instrument_id == instrument_id)
        .order_by(CodalLetter.published_at.desc(), CodalLetter.tracing_no.desc())
        .limit(LETTERS_SHOWN)
    ).all()
    return InstrumentDetail(
        instrument=instrument_out(inst),
        adjusted=True,
        candles=candles,
        features_date=frow.date if frow else None,
        features=features,
        signals=[signal_out(s, inst) for s in sigs],
        letters=[
            CodalLetterOut(
                title=x.title,
                letter_code=x.letter_code,
                published_at=x.published_at.date() if x.published_at else None,
                url=x.url,
                has_excel=x.has_excel,
                has_pdf=x.has_pdf,
            )
            for x in letters
        ],
        events=[
            CorporateEventOut(
                type=e.type,
                stage=e.stage,
                title=e.title,
                announced_at=e.announced_at,
                url=e.source_url,
            )
            for e in events
        ],
    )


@router.get("/instruments/{instrument_id}/agm", response_model=AgmDecisionOut)
def agm_decision(
    instrument_id: int,
    session: SessionDep,
    dps: Annotated[float, Query(ge=0, description="dividend per share, rial")],
    months_to_payment: Annotated[float, Query(ge=0, le=60, description="k")],
    expected_drop_after: Annotated[float, Query(description="E[ΔP_after], rial")] = 0.0,
    dividend_tax: Annotated[float, Query(ge=0, description="rial per share")] = 0.0,
    months_alt: Annotated[float | None, Query(ge=0, le=60, description="k'; default k")] = None,
    monthly_discount: Annotated[float | None, Query(gt=-1, description="r_m")] = None,
    alt_monthly_return: Annotated[float | None, Query(gt=-1, description="r_alt")] = None,
) -> AgmDecisionOut:
    """Hold for the AGM or sell before it (docs/05). DPS and timing come from the caller; the
    price, the risk-free rate (default for r_m and r_alt) and the costs come from the database,
    and every input says where it came from."""
    inst = session.get(Instrument, instrument_id)
    if inst is None:
        raise HTTPException(status_code=404, detail="نماد پیدا نشد")
    bar = session.scalars(
        select(PriceDaily)
        .where(PriceDaily.instrument_id == instrument_id, PriceDaily.close.is_not(None))
        .order_by(PriceDaily.date.desc())
        .limit(1)
    ).first()
    if bar is None or not bar.close or float(bar.close) <= 0:
        raise HTTPException(status_code=422, detail="قیمتی برای این نماد ثبت نشده است")
    price = float(bar.close)
    inputs: list[AgmInputOut] = [
        AgmInputOut(name="dps", value=dps, source="user"),
        AgmInputOut(name="price_now", value=price, source=f"prices_daily.close {bar.date}"),
        AgmInputOut(name="months_to_payment", value=months_to_payment, source="user"),
    ]

    rf = None
    if monthly_discount is None or alt_monthly_return is None:
        rf = session.scalars(
            select(MacroSeries)
            .where(MacroSeries.series == RF_SERIES)
            .order_by(MacroSeries.ref_period.desc())
            .limit(1)
        ).first()
        if rf is None:
            raise HTTPException(
                status_code=422,
                detail="نرخ بدون ریسک ثبت نشده است؛ r_m و r_alt را وارد کنید",
            )
    rf_src = f"macro_series.{RF_SERIES} {rf.ref_period}, monthly" if rf else ""
    r_m = monthly_discount if monthly_discount is not None else monthly_from_annual(rf.value)  # type: ignore[union-attr]
    r_alt = (
        alt_monthly_return if alt_monthly_return is not None else monthly_from_annual(rf.value)  # type: ignore[union-attr]
    )
    inputs.append(
        AgmInputOut(
            name="monthly_discount",
            value=r_m,
            source="user" if monthly_discount is not None else rf_src,
        )
    )
    inputs.append(
        AgmInputOut(
            name="alt_monthly_return",
            value=r_alt,
            source="user" if alt_monthly_return is not None else rf_src,
        )
    )
    k_alt = months_alt if months_alt is not None else months_to_payment
    inputs.append(
        AgmInputOut(
            name="months_alt",
            value=k_alt,
            source="user" if months_alt is not None else "= months_to_payment",
        )
    )

    try:
        costs = CostModel.from_rules(
            RuleBook.from_session(session),
            utcnow().astimezone(TEHRAN).date(),
            get_engine_config().costs.slippage_fraction,
        )
    except MissingRuleError as exc:
        raise HTTPException(status_code=422, detail=f"قاعدهٔ هزینه ثبت نشده است: {exc}") from exc
    rt = price * costs.round_trip
    inputs.append(
        AgmInputOut(
            name="round_trip_costs",
            value=rt,
            source=f"market_rules + slippage, {costs.round_trip:.4%} of price",
        )
    )
    inputs.append(
        AgmInputOut(
            name="expected_drop_after",
            value=expected_drop_after,
            source="user" if expected_drop_after else "default 0 (not estimated yet)",
        )
    )
    inputs.append(
        AgmInputOut(
            name="dividend_tax",
            value=dividend_tax,
            source="user" if dividend_tax else "default 0 (not verified)",
        )
    )
    try:
        out = hold_or_sell(
            AgmInputs(
                dps=dps,
                price_now=price,
                months_to_payment=months_to_payment,
                monthly_discount=r_m,
                expected_drop_after=expected_drop_after,
                dividend_tax=dividend_tax,
                alt_monthly_return=r_alt,
                months_alt=k_alt,
                round_trip_costs=rt,
            )
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return AgmDecisionOut(
        instrument_id=instrument_id,
        decision=out.decision,
        pv_dividend=out.pv_dividend,
        net_hold=out.net_hold,
        net_sell=out.net_sell,
        inputs=inputs,
    )


def _utc(ts: dt.datetime) -> dt.datetime:
    return ts if ts.tzinfo else ts.replace(tzinfo=dt.UTC)


@router.get("/instruments/{instrument_id}/live", response_model=LiveOut)
def instrument_live(instrument_id: int, session: SessionDep) -> LiveOut:
    """The latest stored intraday snapshot and 5-level order book. ``available=false`` is a normal
    state (market closed, or the live poller is not running)."""
    if session.get(Instrument, instrument_id) is None:
        raise HTTPException(status_code=404, detail="نماد پیدا نشد")
    snap = session.scalars(
        select(IntradaySnapshot)
        .where(IntradaySnapshot.instrument_id == instrument_id)
        .order_by(IntradaySnapshot.ts.desc())
        .limit(1)
    ).first()
    if snap is None:
        return LiveOut(
            instrument_id=instrument_id,
            available=False,
            message="داده لحظه‌ای ذخیره نشده است؛ بازار بسته است یا دریافت زنده فعال نیست.",
        )
    ts = _utc(snap.ts)
    day = ts.astimezone(TEHRAN).date()
    prev = session.scalars(
        select(PriceDaily.close)
        .where(PriceDaily.instrument_id == instrument_id, PriceDaily.date < day)
        .order_by(PriceDaily.date.desc())
        .limit(1)
    ).first()
    last = None if snap.last_price is None else float(snap.last_price)
    ref = None if prev is None else float(prev)
    book_row = session.scalars(
        select(OrderBookSnapshot)
        .where(OrderBookSnapshot.instrument_id == instrument_id)
        .order_by(OrderBookSnapshot.ts.desc())
        .limit(1)
    ).first()
    age = max(0, int((utcnow() - ts).total_seconds()))
    return LiveOut(
        instrument_id=instrument_id,
        available=True,
        as_of=ts,
        age_seconds=age,
        stale=age > STALE_AFTER_SECONDS,
        last_price=last,
        cum_volume=None if snap.cum_volume is None else float(snap.cum_volume),
        reference_price=ref,
        change_pct=(last / ref - 1.0) if last and ref else None,
        book_as_of=_utc(book_row.ts) if book_row else None,
        book=[BookLevelOut(**lv) for lv in book_row.levels] if book_row else [],
    )
