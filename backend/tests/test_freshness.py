"""Nothing served may outlive the data behind it: no clock-based caches."""

from __future__ import annotations

import datetime as dt
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from tmon.api import returns, technical
from tmon.api.main import create_app
from tmon.api.returns import period_table
from tmon.storage.models import Instrument, PriceDaily
from tmon.storage.objectstore import FileStore, MemoryStore

LAST = dt.date(2026, 11, 10)


def test_rewritten_document_is_served_on_the_very_next_request(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = FileStore(tmp_path)
    monkeypatch.setattr(technical, "get_object_store", lambda: store)
    technical._cache.clear()
    bucket = technical.get_settings().minio_artifact_bucket
    assert technical.load_doc("k.json") is None
    store.put(bucket, "k.json", b'{"v": 1}', "application/json")
    assert technical.load_doc("k.json") == {"v": 1}
    store.put(bucket, "k.json", b'{"v": 2, "more": true}', "application/json")  # different size
    assert technical.load_doc("k.json") == {"v": 2, "more": True}
    store.put(bucket, "k.json", b'{"v": 3, "more": true}', "application/json")  # same size
    assert technical.load_doc("k.json") == {"v": 3, "more": True}


def test_unchanged_document_is_parsed_once(monkeypatch: pytest.MonkeyPatch) -> None:
    store = MemoryStore()
    monkeypatch.setattr(technical, "get_object_store", lambda: store)
    technical._cache.clear()
    bucket = technical.get_settings().minio_artifact_bucket
    store.put(bucket, "k.json", b'{"v": 1}', "application/json")
    first = technical.load_doc("k.json")
    assert technical.load_doc("k.json") is first


def test_a_corrected_bar_changes_the_period_table(session: Session) -> None:
    returns._cache.clear()
    session.add(Instrument(id=1, ins_code="c1", symbol_fa="س", instrument_type="stock"))
    for k in range(10, -1, -1):
        session.add(
            PriceDaily(
                instrument_id=1,
                date=LAST - dt.timedelta(days=k),
                close=1000 + 10 * (10 - k),
                prev_close=1000 + 10 * (9 - k),
                market_halt=False,
            )
        )
    session.commit()
    before = period_table(session, LAST)[1].ret_week
    bar = session.get(PriceDaily, (1, LAST))
    assert bar is not None
    bar.close = float(bar.close) * 1.2
    session.commit()
    assert period_table(session, LAST)[1].ret_week != before


def test_api_answers_are_never_cacheable(session: Session) -> None:
    with TestClient(create_app()) as c:
        r = c.get("/health")
    assert r.headers["cache-control"] == "no-store"
