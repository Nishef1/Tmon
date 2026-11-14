from __future__ import annotations

import datetime as dt
import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from tmon.api.main import create_app
from tmon.api.routers import research
from tmon.core.db import get_session
from tmon.storage.models import Instrument, OrderBookDaily, PriceDaily
from tmon.tools import orderbook_research as obr

DATA = Path(__file__).resolve().parents[2] / "docs" / "data"
DAY = dt.date(2026, 11, 11)


@pytest.fixture
def client(session: Session) -> Iterator[TestClient]:
    app = create_app()
    app.dependency_overrides[get_session] = lambda: session
    with TestClient(app) as c:
        yield c


def _inst(i: int) -> Instrument:
    return Instrument(
        id=i, ins_code=f"{i}", symbol_fa=f"ن{i}", name_fa=f"نام{i}", instrument_type="stock"
    )


def _book(i: int, day: dt.date, imb: float) -> OrderBookDaily:
    return OrderBookDaily(
        instrument_id=i,
        date=day,
        n_events=100,
        close_imbalance=imb,
        open_imbalance=imb,
        tw_imbalance=imb,
        tw_size_ratio=imb,
        frac_buy_queue=0.0,
        frac_sell_queue=0.0,
    )


@pytest.mark.skipif(
    not (DATA / "book-study.json").exists(), reason="study data files are not in this checkout"
)
def test_document_is_built_from_the_study_files_and_served(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    doc = obr.build_document(DATA)
    json.dumps(doc)  # plain JSON
    status = {f["key"]: f["status"] for f in doc["features"]}
    assert status["tw_imbalance"] == "kept" and status["tw_spread"] == "dropped"
    assert status["early_imbalance"] == "redundant"
    assert sum(s == "kept" for s in status.values()) == 5
    monkeypatch.setattr(research, "load_doc", lambda key: doc if key == obr.KEY else None)
    body = client.get("/research/orderbook-queue").json()
    assert body["available"] and body["book_days"] > 200
    row = next(r for r in body["ladder"] if r["universe"] == "all" and r["review"] == 5)
    # the realistic result sits below the ideal one: queue locks cost return
    assert 0 < row["locks"]["excess"] < row["ideal"]["excess"]
    assert body["capacity"][0]["notional_rial"] < body["capacity"][-1]["notional_rial"]
    assert body["disclaimer"]


def test_document_missing_is_unavailable(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(research, "load_doc", lambda key: None)
    assert client.get("/research/orderbook-queue").json()["available"] is False


def test_symbol_book_ranks_against_the_same_day(client: TestClient, session: Session) -> None:
    for i in (1, 2, 3):
        session.add(_inst(i))
        for d, imb in ((DAY - dt.timedelta(days=1), 0.0), (DAY, (i - 2) * 0.5)):
            session.add(_book(i, d, imb))
            session.add(PriceDaily(instrument_id=i, date=d, open=100, high=105, low=95,
                                   last=102, close=100, volume=10, value=1000))  # fmt: skip
    session.commit()
    body = client.get("/instruments/3/book").json()
    assert body["available"] and body["as_of"] == DAY.isoformat()
    assert body["universe_size"] == 3 and len(body["days"]) == 2
    # strongest buyer-leaning book of the three on the latest day
    top = next(r for r in body["ranks"] if r["key"] == "tw_imbalance")
    assert top["percentile"] > 0.8
    low = client.get("/instruments/1/book").json()
    assert low["score_percentile"] < body["score_percentile"]
    assert body["days"][0]["last_close_gap"] == pytest.approx(0.02)


def test_symbol_without_book_and_unknown_symbol(client: TestClient, session: Session) -> None:
    session.add(_inst(1))
    session.commit()
    body = client.get("/instruments/1/book").json()
    assert body["available"] is False and "۱۰۰" in body["message"]
    assert client.get("/instruments/99/book").status_code == 404
