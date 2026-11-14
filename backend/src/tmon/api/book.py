"""Order book and queue: the research document and one symbol's recent book days.

The research part serves what ``python -m tmon.tools.orderbook_research`` stored; the symbol part
reads ``order_book_daily`` and ranks the symbol among the stocks that have a stored book on the same
day, with the five features that held up in ``tmon.backtest.book_study`` (``features/book_signal``).
"""

from __future__ import annotations

from typing import Any

import polars as pl
from sqlalchemy import select
from sqlalchemy.orm import Session

from tmon.api.schemas import (
    BookAssumptions,
    BookCapacityRow,
    BookDay,
    BookFeature,
    BookFeatureRank,
    BookIc,
    BookLadderRow,
    BookPoint,
    BookRandom,
    BookScoreSim,
    BookSelection,
    InstrumentBookOut,
    OrderbookResearchOut,
)
from tmon.features.book_signal import SHORT_FEATURES
from tmon.storage.models import OrderBookDaily, PriceDaily
from tmon.tools.orderbook_research import FEATURES, KEY

DAYS = 20
COLUMNS = (
    "close_imbalance",
    "open_imbalance",
    "tw_imbalance",
    "tw_size_ratio",
    "frac_buy_queue",
    "frac_sell_queue",
    "peak_queue_volume",
    "close_bid_volume",
    "close_ask_volume",
    "tw_spread",
    "tw_depth_value",
)

__all__ = ["KEY", "book_out", "research_out"]


def research_out(doc: dict[str, Any] | None) -> OrderbookResearchOut:
    if not doc:
        return OrderbookResearchOut(available=False)
    return OrderbookResearchOut(
        available=True,
        generated=doc["generated"],
        book_days=doc["book_days"],
        book_rows=doc["book_rows"],
        split=doc["split"],
        assumptions=BookAssumptions(**doc["assumptions"]),
        ladder=[
            BookLadderRow(
                universe=r["universe"],
                review=r["review"],
                ideal=BookPoint(**r["ideal"]),
                locks=BookPoint(**r["locks"]),
                missed_buys=r.get("missed_buys"),
            )
            for r in doc["ladder"]
        ],
        capacity=[
            BookCapacityRow(
                notional_rial=r["notional_rial"],
                cells={k: BookPoint(**v) for k, v in r["cells"].items()},
            )
            for r in doc["capacity"]
        ],
        random=BookRandom(**doc["random"]),
        base_ic={h: BookIc(**v) for h, v in doc["base_ic"].items()},
        features=[BookFeature(**f) for f in doc["features"]],
        selection={k: BookSelection(**v) for k, v in doc["selection"].items()},
        score_sim=[
            BookScoreSim(label=r["label"], base=BookPoint(**r["base"]), book=BookPoint(**r["book"]))
            for r in doc["score_sim"]
        ],
        limits=doc["limits"],
    )


def _frame(session: Session, day_from: Any, day_to: Any) -> pl.DataFrame:
    """Stored book rows of the window with the last-trade gap from the daily prices."""
    stmt = (
        select(
            OrderBookDaily.instrument_id,
            OrderBookDaily.date,
            *[getattr(OrderBookDaily, c) for c in COLUMNS],
            PriceDaily.last,
            PriceDaily.close,
        )
        .join(
            PriceDaily,
            (PriceDaily.instrument_id == OrderBookDaily.instrument_id)
            & (PriceDaily.date == OrderBookDaily.date),
            isouter=True,
        )
        .where(OrderBookDaily.date >= day_from, OrderBookDaily.date <= day_to)
    )
    rows = session.execute(stmt).all()
    df = pl.DataFrame(
        [tuple(r) for r in rows],
        schema=["instrument_id", "date", *COLUMNS, "last", "close"],
        orient="row",
        infer_schema_length=None,
    )
    return df.with_columns(
        pl.when(pl.col("close") > 0)
        .then((pl.col("last") - pl.col("close")) / pl.col("close"))
        .otherwise(None)
        .alias("last_close_gap")
    )


def book_out(session: Session, instrument_id: int) -> InstrumentBookOut:
    latest = session.scalar(
        select(OrderBookDaily.date)
        .where(OrderBookDaily.instrument_id == instrument_id)
        .order_by(OrderBookDaily.date.desc())
        .limit(1)
    )
    if latest is None:
        return InstrumentBookOut(
            instrument_id=instrument_id,
            available=False,
            message="تاریخچهٔ تابلو برای این نماد ذخیره نشده است (فقط ۱۰۰ نمادِ پرمعامله).",
        )
    dates = session.scalars(
        select(OrderBookDaily.date)
        .where(OrderBookDaily.instrument_id == instrument_id)
        .order_by(OrderBookDaily.date.desc())
        .limit(DAYS)
    ).all()
    df = _frame(session, min(dates), latest)
    mine = df.filter(pl.col("instrument_id") == instrument_id).sort("date", descending=True)
    today = df.filter(pl.col("date") == latest)
    n = today.height
    ranks: list[BookFeatureRank] = []
    pcts: list[float] = []
    row = today.filter(pl.col("instrument_id") == instrument_id)
    for col, sign in SHORT_FEATURES:
        v = row[col][0] if row.height else None
        pct = None
        if v is not None and n > 1:
            vals = today[col].drop_nulls()
            if vals.len() > 1:
                below = float((vals < v).sum()) + 0.5 * float((vals == v).sum())
                pct = below / vals.len() if sign > 0 else 1 - below / vals.len()
        if pct is not None:
            pcts.append(pct)
        ranks.append(
            BookFeatureRank(
                key=col,
                label=FEATURES[col][0],
                value=None if v is None else float(v),
                percentile=pct,
            )
        )
    days = [
        BookDay(
            date=r["date"],
            **{c: (None if r[c] is None else float(r[c])) for c in (*COLUMNS, "last_close_gap")},
        )
        for r in mine.iter_rows(named=True)
    ]
    return InstrumentBookOut(
        instrument_id=instrument_id,
        available=True,
        as_of=latest,
        universe_size=n,
        score_percentile=sum(pcts) / len(pcts) if pcts else None,
        ranks=ranks,
        days=days,
    )
