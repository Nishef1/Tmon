"""The v2 ranking page: zones follow the configured fractions and the API never invents a verdict."""

from __future__ import annotations

import json
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from tmon.api.main import create_app
from tmon.api.routers import ranking as rk
from tmon.core.db import get_session
from tmon.storage.objectstore import MemoryStore
from tmon.tools.v2_ranking import _zone

DOC = {
    "as_of": "2026-11-10",
    "basket_size": 100,
    "recommendation_allowed": False,
    "buy_top_frac": 0.1,
    "hold_top_frac": 0.3,
    "exposure": {"trend": 1.0, "abs_mom": 1.0, "vol_cap": 1.0, "stress": 0.99, "exposure": 0.99},
    "exposure_date": "2026-11-10",
    "rows": [
        {
            "rank": 1,
            "symbol": "الف",
            "name": None,
            "sector_code": None,
            "score": 0.95,
            "zone": "buy",
            "queue_state": "none",
            "median_value": 1e9,
            "signals": {"ind_buy_power": 0.9, "rv_20": None},
        }
    ],
    "evidence": [
        {
            "horizon_days": 20,
            "ic": 0.1,
            "ic_t": 3.0,
            "top_excess": 0.04,
            "bottom_excess": 0.0,
            "excess_t": 4.0,
            "n_days": 100,
        }
    ],
    "gates": [],
    "book": {"n_buys": 1, "cancelled_buys": 0, "postponed_sells": 0, "avg_held": 1.0},
}


@pytest.fixture
def client(session: Session) -> Iterator[TestClient]:
    app = create_app()
    app.dependency_overrides[get_session] = lambda: session
    with TestClient(app) as c:
        yield c


def test_zones_follow_the_configured_fractions() -> None:
    assert _zone(0.95, 0.1, 0.3) == "buy"
    assert _zone(0.9, 0.1, 0.3) == "hold"  # the boundary belongs to the lower zone
    assert _zone(0.75, 0.1, 0.3) == "hold"
    assert _zone(0.7, 0.1, 0.3) == "avoid"
    assert _zone(0.0, 0.1, 0.3) == "avoid"


def test_endpoint_without_a_stored_ranking_says_unavailable(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(rk, "get_object_store", lambda: MemoryStore())
    body = client.get("/v2/ranking").json()
    assert body["available"] is False
    assert body["recommendation_allowed"] is False
    assert body["rows"] == []


def test_endpoint_serves_the_stored_document_and_keeps_the_disclaimer(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tmon.core.config import get_settings
    from tmon.tools.v2_ranking import KEY

    store = MemoryStore()
    store.put(
        get_settings().minio_artifact_bucket,
        KEY,
        json.dumps(DOC, ensure_ascii=False).encode(),
        "application/json",
    )
    monkeypatch.setattr(rk, "get_object_store", lambda: store)
    body = client.get("/v2/ranking").json()
    assert body["available"] is True
    assert body["recommendation_allowed"] is False
    assert body["rows"][0]["zone"] == "buy"
    assert body["evidence"][0]["horizon_days"] == 20
    assert "توصیه سرمایه‌گذاری نیست" in body["disclaimer"]


def test_universe_scores_match_the_engine_for_members_and_extend_to_the_rest() -> None:
    import datetime as dt

    import numpy as np
    import polars as pl

    from tmon.backtest.signal_decay import build_panel
    from tmon.core.engine_config import get_engine_config
    from tmon.tools.v2_ranking import universe_scores

    cfg = get_engine_config()
    rng = np.random.default_rng(7)
    days = [dt.date(2025, 1, 1) + dt.timedelta(days=i) for i in range(300)]
    n = 40
    adj_rows, feat_rows = [], []
    for i in range(n):
        px = 1000 * np.exp(np.cumsum(rng.normal(0.001 * (i - 20) / 20, 0.02, len(days))))
        for d, p in zip(days, px, strict=True):
            adj_rows.append({"instrument_id": i, "date": d, "adj_close": float(p)})
            feat_rows.append(
                {
                    "instrument_id": i,
                    "date": d,
                    "eligible": i < 30,  # the last ten are "thin": outside the engine universe
                    "market_halt": False,
                    "queue_state": "none",
                    "median_value_20": 1e11 if i < 30 else 1e9,
                    "ind_buy_power": float(rng.uniform(0.2, 3)),
                    "rv_20": float(rng.uniform(0.1, 0.8)),
                    "dist_high_52w": float(rng.uniform(0.5, 1.0)),
                }
            )
    feats = pl.DataFrame(feat_rows).with_columns(
        pl.when(pl.col("instrument_id") == 39).then(None).otherwise(pl.col("rv_20")).alias("rv_20")
    )
    adj = pl.DataFrame(adj_rows)
    last = days[-1]
    got = {r["id"]: r for r in universe_scores(feats, adj, cfg, last)}
    assert len(got) == n
    panel = build_panel(feats, adj, cfg, horizons=(5,)).filter(pl.col("date") == last)
    for r in panel.iter_rows(named=True):
        # equal composites are one tie here and may be split by float noise in the engine: a
        # difference of at most half a rank of the 30 members
        assert abs(got[r["instrument_id"]]["score"] - r["r_composite"]) <= 0.5 / 30 + 1e-9
    thin = got[35]
    assert thin["eligible"] is False and thin["score"] is not None and 0 <= thin["score"] <= 1
    assert thin["zone"] in ("buy", "hold", "avoid")
    assert got[39]["score"] is None and got[39]["missing"] == ["rv_20"]
