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
