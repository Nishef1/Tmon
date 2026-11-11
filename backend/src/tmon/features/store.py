"""Read raw tables into Polars frames and persist feature frames.

The ``features`` table keeps one JSON document per ``(instrument, date, feature_set_version)``
for serving and inspection. Training reads a Parquet snapshot from MinIO instead (faster and
immutable, which is what ``data_snapshot_id`` refers to).
"""

from __future__ import annotations

import io
import math
from datetime import date

import polars as pl
from sqlalchemy import Float, cast, select
from sqlalchemy.orm import Session

from tmon.domain.rules import RuleBook
from tmon.features.builder import KEYS, FeatureSet, build_features, get_feature_set
from tmon.ingest.tsetmc.classify import Classifier, get_classifier
from tmon.storage.models import ClientTypeDaily, FeatureRow, Instrument, PriceDaily
from tmon.storage.objectstore import ObjectStore
from tmon.storage.repositories import upsert

PRICE_FLOAT_COLS = (
    "open", "high", "low", "close", "last", "prev_close", "volume", "value", "base_volume",
)  # fmt: skip
CLIENT_COLS = tuple(
    f"{s}_{m}_{k}"
    for s in ("buy", "sell")
    for m in ("count", "volume", "value")
    for k in ("i", "n")
)


def load_inputs(
    session: Session, *, classifier: Classifier | None = None
) -> tuple[pl.DataFrame, pl.DataFrame, pl.DataFrame]:
    """``(prices, client_types, sectors)`` for RECOMMENDABLE instruments (ADR 0002 section 1),
    as float Polars frames. Funds kept only for comparison never reach the model."""
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
    tradable = [
        r
        for r in inst
        if clf.is_recommendable(
            r.instrument_type, board=r.board, group_title=(r.tags or {}).get("group_title")
        )
    ]
    ids = [r.id for r in tradable]
    sectors = pl.DataFrame(
        {"instrument_id": ids, "sector_code": [r.sector_code for r in tradable]},
        schema={"instrument_id": pl.Int64, "sector_code": pl.Utf8},
    )
    tag_base = {r.id: (r.tags or {}).get("base_volume") for r in tradable}

    price_rows = session.execute(
        select(
            PriceDaily.instrument_id,
            PriceDaily.date,
            *[cast(getattr(PriceDaily, c), Float).label(c) for c in PRICE_FLOAT_COLS],
            PriceDaily.market_halt,
        ).where(PriceDaily.instrument_id.in_(ids))
    ).all()
    prices = pl.DataFrame(
        [tuple(r) for r in price_rows],
        schema={
            "instrument_id": pl.Int64,
            "date": pl.Date,
            **dict.fromkeys(PRICE_FLOAT_COLS, pl.Float64),
            "market_halt": pl.Boolean,
        },
        orient="row",
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

    client_rows = session.execute(
        select(
            ClientTypeDaily.instrument_id,
            ClientTypeDaily.date,
            *[cast(getattr(ClientTypeDaily, c), Float).label(c) for c in CLIENT_COLS],
        ).where(ClientTypeDaily.instrument_id.in_(ids))
    ).all()
    clients = pl.DataFrame(
        [tuple(r) for r in client_rows],
        schema={
            "instrument_id": pl.Int64,
            "date": pl.Date,
            **dict.fromkeys(CLIENT_COLS, pl.Float64),
        },
        orient="row",
    )
    return prices, clients, sectors


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
    rows = [
        {
            "instrument_id": inst,
            "date": d,
            "feature_set_version": fs.key,
            "values": {c: _clean(v) for c, v in zip(cols, vals, strict=True)},
        }
        for inst, d, *vals in df.select(*KEYS, *cols).iter_rows()
    ]
    return upsert(session, FeatureRow, rows)


def read_features(
    session: Session, fs: FeatureSet, *, start: date | None = None, end: date | None = None
) -> pl.DataFrame:
    q = select(FeatureRow.instrument_id, FeatureRow.date, FeatureRow.values).where(
        FeatureRow.feature_set_version == fs.key
    )
    if start:
        q = q.where(FeatureRow.date >= start)
    if end:
        q = q.where(FeatureRow.date <= end)
    rows = session.execute(q).all()
    data = {c: [(r.values or {}).get(c) for r in rows] for c in fs.columns}
    return pl.DataFrame(
        {"instrument_id": [r.instrument_id for r in rows], "date": [r.date for r in rows], **data},
        schema_overrides={"date": pl.Date},
    ).sort(*KEYS)


def export_parquet(features: pl.DataFrame, store: ObjectStore, bucket: str, key: str) -> str:
    """Write an immutable training snapshot and return its object key."""
    buf = io.BytesIO()
    features.write_parquet(buf)
    store.put(bucket, key, buf.getvalue(), "application/vnd.apache.parquet")
    return key


def refresh_features(session: Session, timeframe: str = "D1") -> int:
    """Rebuild features from stored raw data and upsert them. Returns rows written."""
    fs = get_feature_set(timeframe)
    return write_features(session, build_from_db(session), fs)
