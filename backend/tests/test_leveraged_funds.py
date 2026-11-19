"""Leveraged-fund stats (tmon.backtest.leveraged_funds), their document and the API route."""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pytest
from fastapi.testclient import TestClient

from tmon.api.main import create_app
from tmon.backtest import leveraged_funds as lf
from tmon.core.db import get_session
from tmon.storage.models import FundNav, Instrument, MarketIndexDaily, PriceDaily
from tmon.tools import leveraged_funds as tool


@pytest.fixture
def client(session):
    app = create_app()
    app.dependency_overrides[get_session] = lambda: session
    return TestClient(app)


def _world(n: int = 300) -> tuple[np.ndarray, np.ndarray]:
    rng = np.random.default_rng(3)
    m = rng.normal(0.002, 0.01, n)
    index = 100 * np.r_[1.0, np.cumprod(1 + m)]
    fund = 100 * np.r_[1.0, np.cumprod(1 + 2 * m)]
    return fund, index


def test_a_fund_that_doubles_the_market_has_beta_two_and_no_alpha() -> None:
    fund, index = _world()
    row = lf.fund_row(fund, index)
    assert row is not None
    assert row["beta"] == pytest.approx(2.0, abs=1e-6)
    assert row["corr"] == pytest.approx(1.0)
    assert row["alpha_year"] == pytest.approx(0.0, abs=1e-9)
    assert row["max_drawdown"] <= 0
    assert 0 <= row["share_ge_target"] <= 1
    assert row["last_month"] == pytest.approx(fund[-1] / fund[-1 - lf.MONTH] - 1)
    assert row["last_month_index"] == pytest.approx(index[-1] / index[-1 - lf.MONTH] - 1)


def test_a_short_history_gives_no_row() -> None:
    fund, index = _world(100)
    assert lf.fund_row(fund, index) is None


def test_basket_ignores_missing_days_and_reports_the_same_shape() -> None:
    fund, _ = _world()
    other = fund.copy()
    other[:50] = np.nan  # the second fund started later
    row = lf.basket_row(np.column_stack([fund, other]))
    assert row is not None and row["funds"] == 2
    assert row["max_drawdown"] <= 0 and row["worst_month"] <= row["month_median"]


def test_document_and_route(session, client, monkeypatch) -> None:
    fund, index = _world()
    inst = Instrument(ins_code="9", symbol_fa="اهرم", instrument_type="etf_leveraged")
    session.add(inst)
    session.flush()
    start = date(2025, 1, 1)
    for i, (f, x) in enumerate(zip(fund, index, strict=True)):
        d = start + timedelta(days=i)
        session.add(PriceDaily(instrument_id=inst.id, date=d, close=float(f), value=5e10))
        session.add(MarketIndexDaily(index_code=tool.TEPIX, date=d, close=float(x)))
    session.add(
        FundNav(
            reg_no="9",
            date=start + timedelta(days=len(fund) - 1),
            instrument_id=inst.id,
            fund_type=22,
            cancel_nav=float(fund[-1]) / 2,
        )
    )
    session.flush()
    doc = tool.build_document(session)
    assert doc["as_of"] == str(start + timedelta(days=len(fund) - 1))
    [f] = doc["funds"]
    assert f["symbol"] == "اهرم" and f["beta"] == pytest.approx(2.0, abs=1e-3)
    assert f["price_over_nav"] == pytest.approx(2.0)
    assert doc["types"] == []  # under 500 days of history: no type basket is made

    monkeypatch.setattr("tmon.api.routers.macro.read_artifact", lambda key: doc)
    j = client.get("/funds/leveraged").json()
    assert j["funds"][0]["symbol"] == "اهرم" and j["target"] == 0.10
    assert "disclaimer" in j

    monkeypatch.setattr("tmon.api.routers.macro.read_artifact", lambda key: None)
    assert client.get("/funds/leveraged").json()["funds"] == []
