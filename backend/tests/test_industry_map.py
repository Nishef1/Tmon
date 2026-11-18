"""The industry map endpoint serves the PC cycle's document (tmon.tools.industry_map)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tmon.api.main import create_app
from tmon.core.config import get_settings
from tmon.storage import objectstore
from tmon.storage.objectstore import MemoryStore
from tmon.tools.industry_map import KEY

ROW = {
    "sector": "فلزات اساسی",
    "group": "export",
    "n_stocks": 22,
    "symbols": ["فولاد", "فملی"],
    "beta": 0.99,
    "cohesion": 0.06,
    "axis": 0.51,
    "usd_corr": 0.31,
    "usd_corr_h1": 0.2,
    "usd_corr_h2": 0.36,
    "dollar_tie": "up_steady",
    "ret_4w": 0.09,
    "ret_13w": 0.66,
    "ret_52w": 3.13,
    "vs_market_13w": 0.18,
    "closest": [{"sector": "استخراج کانه های فلزی", "corr": 0.4}],
}
DOC = {
    "as_of": "2026-11-17",
    "start": "2023-11-20",
    "mid": "2025-03-31",
    "n_weeks": 142,
    "n_stocks": 230,
    "dollar_tie_cut": 0.15,
    "group_cut": 0.33,
    "axis_share": 0.144,
    "market": {"ret_4w": 0.09, "ret_13w": 0.48, "ret_52w": 2.4},
    "sectors": [ROW],
    "corr": {"order": ["فلزات اساسی"], "values": [[1.0]]},
}


def _client(monkeypatch: pytest.MonkeyPatch, doc: dict | None) -> TestClient:
    store = MemoryStore()
    if doc is not None:
        store.put(
            get_settings().minio_artifact_bucket,
            KEY,
            json.dumps(doc, ensure_ascii=False).encode(),
            "application/json",
        )
    monkeypatch.setattr(objectstore, "get_object_store", lambda: store)
    return TestClient(create_app())


def test_missing_document_is_a_404(monkeypatch: pytest.MonkeyPatch) -> None:
    assert _client(monkeypatch, None).get("/industries/map").status_code == 404


def test_endpoint_serves_the_stored_document(monkeypatch: pytest.MonkeyPatch) -> None:
    body = _client(monkeypatch, DOC).get("/industries/map").json()
    assert body["sectors"][0]["group"] == "export"
    assert body["sectors"][0]["dollar_tie"] == "up_steady"
    assert body["corr"]["values"] == [[1.0]]


def test_cut_points_named_in_the_docs_match_the_code() -> None:
    from tmon.tools import industry_map as im

    report = (Path(__file__).parents[2] / "docs/reports/correlation-map-2026-11.md").read_text(
        encoding="utf-8"
    )
    assert im.DOLLAR_TIE == 0.15 and "۰٫۱۵" in report
    assert abs(im.GROUP_CUT - 1 / 3) < 1e-9 and "یک‌سوم محور" in report
