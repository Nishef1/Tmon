from __future__ import annotations

import datetime as dt
from typing import Annotated

import polars as pl
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from tmon.api.routers.recommendations import instrument_out, signal_out
from tmon.api.schemas import BookLevelOut, Candle, FeatureValue, InstrumentDetail, LiveOut
from tmon.core.db import get_session
from tmon.core.timeutil import TEHRAN, utcnow
from tmon.features.adjustment import apply_adjustments
from tmon.features.builder import get_feature_set
from tmon.storage.models import (
    FeatureRow,
    Instrument,
    IntradaySnapshot,
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
    return InstrumentDetail(
        instrument=instrument_out(inst),
        adjusted=True,
        candles=candles,
        features_date=frow.date if frow else None,
        features=features,
        signals=[signal_out(s, inst) for s in sigs],
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
