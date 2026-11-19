"""Read raw tables into Polars frames and persist feature frames.

The ``features`` table keeps one JSON document per ``(instrument, date, feature_set_version)``
for serving and inspection. Training reads a Parquet snapshot from MinIO instead (faster and
immutable, which is what ``data_snapshot_id`` refers to).
"""

from __future__ import annotations

import math
from datetime import date
from typing import Any

import polars as pl
from sqlalchemy import Float, cast, select
from sqlalchemy.orm import Session

from tmon.domain.rules import RuleBook
from tmon.features.builder import KEYS, FeatureSet, build_features, get_feature_set
from tmon.features.quality import clean_clients, clean_prices
from tmon.ingest.tsetmc.classify import Classifier, get_classifier
from tmon.ingest.tsetmc.risk_free import SERIES as RF_SERIES
from tmon.storage.models import (
    ClientTypeDaily,
    FeatureRow,
    Instrument,
    MacroSeries,
    MarketIndexDaily,
    PriceDaily,
)
from tmon.storage.repositories import upsert

READ_SLICE = 100_000  # database rows turned into a frame at a time
WRITE_SLICE = 50_000  # feature rows turned into JSON documents at a time

PRICE_FLOAT_COLS = (
    "open", "high", "low", "close", "last", "prev_close", "volume", "value", "base_volume",
)  # fmt: skip
CLIENT_COLS = tuple(
    f"{s}_{m}_{k}"
    for s in ("buy", "sell")
    for m in ("count", "volume", "value")
    for k in ("i", "n")
)


PLACEHOLDER_PRICE = 1.0


def drop_placeholder_bars(prices: pl.DataFrame) -> pl.DataFrame:
    """Drop bars whose whole range is the 1-rial placeholder (``high <= 1``).

    TSETMC's daily history has such rows for second fund lines (symbols ending in "2") and a
    few other days: open, high, low and close are all 1 and value equals volume, while
    ``prev_close`` is the fund's real price (~10,000 rial). They are not trades at a market
    price; kept, they turn returns and adjustment factors into nonsense and, through the
    cross-sectional averages, poison the market features of every instrument
    (docs/reports/instrument-classification-audit.md)."""
    return prices.filter(~(pl.col("high") <= PLACEHOLDER_PRICE).fill_null(False))


def _frame(session: Session, stmt: Any, schema: dict[str, Any]) -> pl.DataFrame:
    """The rows of ``stmt`` as a frame, read from the driver a slice at a time. SQLAlchemy's
    row objects for the whole history need several GB; a small server has 4."""
    conn = session.connection()
    sql = str(stmt.compile(dialect=conn.dialect, compile_kwargs={"literal_binds": True}))
    cur = conn.connection.dbapi_connection.cursor()  # type: ignore[union-attr]
    names = list(schema)
    raw = {
        k: (pl.Utf8 if v == pl.Date else pl.Float64 if v == pl.Boolean else v)
        for k, v in schema.items()
    }
    parts: list[pl.DataFrame] = []
    try:
        cur.execute(sql)
        while rows := cur.fetchmany(READ_SLICE):
            parts.append(pl.DataFrame(rows, schema=raw, orient="row"))
    finally:
        cur.close()
    out = pl.concat(parts) if parts else pl.DataFrame(schema=raw)
    return out.with_columns(
        [
            pl.col(k).str.slice(0, 10).str.to_date() if v == pl.Date else pl.col(k).cast(v)
            for k, v in schema.items()
            if raw[k] != v
        ]
    ).select(names)


def load_inputs(
    session: Session, *, classifier: Classifier | None = None, comparison_funds: bool = False
) -> tuple[pl.DataFrame, pl.DataFrame, pl.DataFrame]:
    """``(prices, client_types, sectors)`` for RECOMMENDABLE instruments (ADR 0002 section 1),
    as float Polars frames. Funds kept only for comparison never reach the model.

    With ``comparison_funds`` it returns exactly those funds instead (fixed income, commodity,
    leveraged): the stock page shows them next to the model without changing a single stock's
    score, because they are never part of the model's cross-section."""
    clf = classifier or get_classifier()
    inst = session.execute(
        select(
            Instrument.id,
            Instrument.instrument_type,
            Instrument.board,
            Instrument.sector_code,
            Instrument.tags,
        )
    ).all()

    def model(r: Any) -> bool:
        return clf.is_recommendable(
            r.instrument_type, board=r.board, group_title=(r.tags or {}).get("group_title")
        )

    tradable = [
        r
        for r in inst
        if (
            clf.is_tradable(r.instrument_type)
            and r.instrument_type.startswith("etf_")
            and not model(r)
            if comparison_funds
            else model(r)
        )
    ]
    ids = [r.id for r in tradable]
    sectors = pl.DataFrame(
        {"instrument_id": ids, "sector_code": [r.sector_code for r in tradable]},
        schema={"instrument_id": pl.Int64, "sector_code": pl.Utf8},
    )
    tag_base = {r.id: (r.tags or {}).get("base_volume") for r in tradable}

    prices = _frame(
        session,
        select(
            PriceDaily.instrument_id,
            PriceDaily.date,
            *[cast(getattr(PriceDaily, c), Float).label(c) for c in PRICE_FLOAT_COLS],
            PriceDaily.market_halt,
        ).where(PriceDaily.instrument_id.in_(ids)),
        {
            "instrument_id": pl.Int64,
            "date": pl.Date,
            **dict.fromkeys(PRICE_FLOAT_COLS, pl.Float64),
            "market_halt": pl.Boolean,
        },
    )
    # base volume: the daily column when present, else the instrument's last known value
    # (an approximation for history; see docs/OPEN_QUESTIONS.md)
    fallback = pl.DataFrame(
        {
            "instrument_id": list(tag_base),
            "_tag_base": [float(v) if v else None for v in tag_base.values()],
        },
        schema={"instrument_id": pl.Int64, "_tag_base": pl.Float64},
    )
    prices = (
        prices.join(fallback, on="instrument_id", how="left")
        .with_columns(pl.coalesce("base_volume", "_tag_base").alias("base_volume"))
        .drop("_tag_base")
    )
    prices = clean_prices(drop_placeholder_bars(prices))

    clients = _frame(
        session,
        select(
            ClientTypeDaily.instrument_id,
            ClientTypeDaily.date,
            *[cast(getattr(ClientTypeDaily, c), Float).label(c) for c in CLIENT_COLS],
        ).where(ClientTypeDaily.instrument_id.in_(ids)),
        {
            "instrument_id": pl.Int64,
            "date": pl.Date,
            **dict.fromkeys(CLIENT_COLS, pl.Float64),
        },
    )
    return prices, clean_clients(clients, prices), sectors


def load_benchmark_inputs(session: Session) -> tuple[pl.DataFrame, pl.DataFrame]:
    """``(index_daily, rf)`` for the backtest comparison lines (ADR 0002 section 6).

    ``index_daily``: ``index_code``, ``date``, ``close`` of the official indices.
    ``rf``: ``date``, ``value`` of the one-year treasury-bill yield (``rf_1y_ytm``) as an annual
    fraction, dated by the day it refers to (``ref_period``). Either frame is empty when the
    ingestion has not run; the report then says so.
    """
    idx = session.execute(
        select(MarketIndexDaily.index_code, MarketIndexDaily.date, MarketIndexDaily.close).order_by(
            MarketIndexDaily.index_code, MarketIndexDaily.date
        )
    ).all()
    index_daily = pl.DataFrame(
        [tuple(r) for r in idx],
        schema={"index_code": pl.Utf8, "date": pl.Date, "close": pl.Float64},
        orient="row",
    )
    rf_rows = session.execute(
        select(MacroSeries.ref_period, MacroSeries.value)
        .where(MacroSeries.series == RF_SERIES)
        .order_by(MacroSeries.ref_period)
    ).all()
    rf = pl.DataFrame(
        [tuple(r) for r in rf_rows],
        schema={"date": pl.Date, "value": pl.Float64},
        orient="row",
    )
    return index_daily, rf


def build_from_db(session: Session) -> pl.DataFrame:
    prices, clients, sectors = load_inputs(session)
    return build_features(prices, clients, RuleBook.from_session(session), sectors=sectors)


def _clean(v: object) -> float | None:
    if v is None:
        return None
    f = float(v)  # type: ignore[arg-type]
    return None if math.isnan(f) or math.isinf(f) else f


def write_features(
    session: Session, features: pl.DataFrame, fs: FeatureSet, *, since: date | None = None
) -> int:
    """Upsert model columns as JSON documents. JSON serialisation is the one place rows are
    visited individually; it is an I/O boundary, not a computation."""
    df = features.filter(pl.col("date") >= since) if since else features
    if df.is_empty():
        return 0
    cols = list(fs.columns)
    written = 0
    # a slice at a time: the documents of the whole history would not fit a small server
    for part in df.select(*KEYS, *cols).iter_slices(WRITE_SLICE):
        rows = [
            {
                "instrument_id": inst,
                "date": d,
                "feature_set_version": fs.key,
                "values": {c: _clean(v) for c, v in zip(cols, vals, strict=True)},
            }
            for inst, d, *vals in part.iter_rows()
        ]
        written += upsert(session, FeatureRow, rows)
    return written


def refresh_features(session: Session, timeframe: str = "D1") -> int:
    """Rebuild features from stored raw data and upsert them. Returns rows written."""
    fs = get_feature_set(timeframe)
    return write_features(session, build_from_db(session), fs)
