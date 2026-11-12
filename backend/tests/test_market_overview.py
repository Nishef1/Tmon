"""Market overview: breadth, flow date with full coverage, mover tables."""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from tmon.api.main import create_app
from tmon.core.db import get_session
from tmon.storage.models import ClientTypeDaily, Instrument, PriceDaily

D1, D2 = dt.date(2026, 11, 9), dt.date(2026, 11, 10)


@pytest.fixture
def client(session: Session) -> Iterator[TestClient]:
    app = create_app()
    app.dependency_overrides[get_session] = lambda: session
    with TestClient(app) as c:
        yield c


def _seed(s: Session) -> None:
    for n, (sym, close) in enumerate([("الف", 110.0), ("ب", 95.0), ("ج", 100.0)], 1):
        s.add(
            Instrument(
                id=n, ins_code=f"c{n}", symbol_fa=sym, instrument_type="stock", sector_code="1"
            )
        )
        for d in (D1, D2):
            s.add(
                PriceDaily(
                    instrument_id=n,
                    date=d,
                    close=close,
                    prev_close=100.0,
                    value=1e9 * n,
                    limit_up=110.0,
                    limit_down=90.0,
                )
            )
        for d in (D1, D2) if n < 3 else (D1,):
            s.add(
                ClientTypeDaily(
                    instrument_id=n,
                    date=d,
                    buy_count_i=10,
                    sell_count_i=5,
                    buy_value_i=2e9 if n == 1 else 1e9,
                    sell_value_i=1e9,
                    buy_value_n=0,
                    sell_value_n=1e9,
                )
            )
    s.commit()


def test_empty_db_is_unavailable(client: TestClient) -> None:
    assert client.get("/market/overview").json()["available"] is False


def test_overview_numbers(client: TestClient, session: Session) -> None:
    _seed(session)
    d = client.get("/market/overview").json()
    assert (d["up"], d["down"], d["flat"], d["n_stocks"]) == (1, 1, 1, 3)
    assert d["at_limit_up"] == 1 and d["at_limit_down"] == 1
    assert d["gainers"][0]["symbol"] == "الف"
    assert d["losers"][0]["symbol"] == "ب"
    assert d["inflow"][0]["symbol"] == "الف"
    assert d["flow"]["date"] == "2026-11-10"
    assert d["flow"]["n_symbols"] == 2
    assert d["flow"]["real_net"] == pytest.approx(1e9)
    assert sum(b["count"] for b in d["bands"]) == 3
