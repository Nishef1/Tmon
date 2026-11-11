from __future__ import annotations

from typing import Annotated

import polars as pl
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from tmon.api.routers.recommendations import instrument_out, signal_out
from tmon.api.schemas import Candle, FeatureValue, InstrumentDetail
from tmon.core.db import get_session
from tmon.features.adjustment import apply_adjustments
from tmon.features.builder import get_feature_set
from tmon.storage.models import FeatureRow, Instrument, PriceDaily, Signal

router = APIRouter(tags=["instruments"])
SessionDep = Annotated[Session, Depends(get_session)]

# Features shown on the instrument page; each has a glossary entry in the frontend.
SHOWN_FEATURES = (
    "rsi_14", "macd_hist_pct", "adx_14", "atr_14_pct", "bb_pct_b", "vwap_gap",
    "ind_buy_power", "ind_net_flow_ratio", "rel_volume", "smart_money_flag",
    "mkt_ret_ew", "breadth",
)  # fmt: skip

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
