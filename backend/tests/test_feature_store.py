"""DB round trip for the feature store, using the in-memory SQLite session."""

from __future__ import annotations

import polars as pl
from sqlalchemy import select

from tests.test_features import synthetic_market
from tmon.features.builder import get_feature_set
from tmon.features.store import build_from_db, export_parquet, read_features, refresh_features
from tmon.storage.models import ClientTypeDaily, FeatureRow, Instrument, PriceDaily
from tmon.storage.objectstore import MemoryStore
from tmon.storage.repositories import upsert
from tmon.storage.seed import seed_market_rules


def _load(session) -> pl.DataFrame:
    prices, clients = synthetic_market(n_days=200, n_inst=3)
    session.add_all(
        Instrument(
            id=i, ins_code=str(i), symbol_fa=f"s{i}", instrument_type="stock", sector_code="x"
        )
        for i in (1, 2, 3)
    )
    session.flush()
    upsert(session, PriceDaily, prices.drop("market_halt").to_dicts())
    upsert(session, ClientTypeDaily, clients.to_dicts())
    seed_market_rules(session)
    session.flush()
    return prices


def test_build_from_db_matches_in_memory_build(session):
    prices = _load(session)
    feats = build_from_db(session)
    assert feats.height == prices.height
    assert feats["limit_pct"].drop_nulls().unique().to_list() == [0.03]  # from market_rules
    assert feats["market_halt"].sum() == 0


def test_write_and_read_back_features(session):
    _load(session)
    fs = get_feature_set("D1")
    n = refresh_features(session)
    session.flush()
    assert n == 600
    assert session.scalars(select(FeatureRow)).first().feature_set_version == fs.key

    back = read_features(session, fs)
    assert back.height == 600 and back.columns[:2] == ["instrument_id", "date"]
    original = build_from_db(session).sort("instrument_id", "date")
    for col in ("rsi_14", "ind_buy_power", "breadth", "queue_code"):
        a = original[col].to_list()
        b = back[col].to_list()
        assert all(
            (x is None and y is None) or abs(float(x) - float(y)) < 1e-9
            for x, y in zip(a, b, strict=True)
        )
    # idempotent
    assert refresh_features(session) == 600
    session.flush()
    assert len(session.scalars(select(FeatureRow)).all()) == 600


def test_parquet_snapshot_round_trip():
    prices, _ = synthetic_market(n_days=60, n_inst=2)
    df = prices.select("instrument_id", "date", "close")
    store = MemoryStore()
    key = export_parquet(df, store, "snap", "features/x.parquet")
    import io

    assert pl.read_parquet(io.BytesIO(store.get("snap", key))).equals(df)
