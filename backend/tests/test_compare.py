"""Comparison with inflation (docs/06, docs/07) and the fund bubble endpoint."""

from __future__ import annotations

from datetime import date

import pytest
from fastapi.testclient import TestClient

from tmon.api.main import create_app
from tmon.core.db import get_session
from tmon.domain.compare import (
    Release,
    annualised,
    months_back,
    period_inflation,
    real_return,
    value_on_or_before,
)
from tmon.storage.models import FundNav, Instrument, MacroSeries, PriceDaily


def test_formulas():
    assert real_return(0.5, 0.25) == pytest.approx(0.2)
    assert annualised(0.044) == pytest.approx(0.6765, abs=1e-4)  # docs/07: ≈ 67%
    assert months_back(date(2026, 3, 31), 1) == date(2026, 2, 28)
    assert months_back(date(2026, 1, 15), 12) == date(2025, 1, 15)
    pts = [(date(2026, 1, 1), 1.0), (date(2026, 1, 3), 2.0)]
    assert value_on_or_before(pts, date(2026, 1, 2)) == (date(2026, 1, 1), 1.0)
    assert value_on_or_before(pts, date(2025, 12, 31)) is None


def test_inflation_is_point_in_time():
    mom = [
        Release(date(2026, 9, 22), date(2026, 9, 28), 0.03, None),
        Release(date(2026, 10, 22), date(2026, 10, 28), 0.044, None),
    ]
    # Mehr's figure is not known before its release on 28 October (docs/08)
    before = period_inflation(mom, [], date(2026, 10, 27), 1)
    assert before is not None and before.value == pytest.approx(0.03)
    after = period_inflation(mom, [], date(2026, 10, 28), 2)
    assert after is not None and after.value == pytest.approx(1.03 * 1.044 - 1)
    assert period_inflation(mom, [], date(2026, 10, 28), 3) is None
    yoy = [Release(date(2026, 10, 22), date(2026, 10, 28), 0.887, None)]
    twelve = period_inflation(mom, yoy, date(2026, 11, 1), 12)
    assert twelve is not None and (twelve.value, twelve.method) == (0.887, "cpi_yoy")


@pytest.fixture
def client(session):
    app = create_app()
    app.dependency_overrides[get_session] = lambda: session
    return TestClient(app)


def _macro(series, source, d, v, rel=None, url=None):
    return MacroSeries(
        series=series, source=source, ref_period=d, value=v, release_date=rel or d, source_url=url
    )


def test_compare_reads_macro_series(session, client):
    session.add_all(
        [
            _macro("usd_free", "tgju", date(2025, 11, 1), 100.0),
            _macro("usd_free", "tgju", date(2026, 11, 1), 250.0),
            _macro("rf_1y_ytm", "tsetmc:treasury-bills", date(2025, 10, 30), 0.30),
            _macro("cpi_yoy", "sci", date(2026, 10, 22), 0.887, date(2026, 10, 28), "https://x/1"),
            _macro("cpi_mom", "sci", date(2026, 10, 22), 0.044, date(2026, 10, 28), "https://x/1"),
        ]
    )
    session.flush()
    j = client.get("/compare?months=12").json()
    assert j["as_of"] == "2026-11-01"
    assert j["inflation"]["value"] == pytest.approx(0.887)
    assert j["inflation"]["releases"][0]["source_url"] == "https://x/1"
    assert j["annualised_monthly"] == pytest.approx(annualised(0.044))
    rows = {r["series"]: r for r in j["rows"]}
    assert rows["usd_free"]["nominal_return"] == pytest.approx(1.5)
    assert rows["usd_free"]["real_return"] == pytest.approx(2.5 / 1.887 - 1)
    assert rows["usd_free"]["beats_inflation"] is True
    assert rows["rf_1y_ytm"]["nominal_return"] == pytest.approx(0.30)
    assert rows["rf_1y_ytm"]["beats_inflation"] is False
    assert rows["gold_18k"]["note"]  # no data: said, not invented
    # with the central bank chosen and nothing imported for it, real returns stay empty
    cbi = client.get("/compare?months=12&inflation_source=cbi").json()
    assert cbi["inflation"] is None
    assert all(r["real_return"] is None for r in cbi["rows"])


def test_compare_empty(client):
    j = client.get("/compare").json()
    assert j["as_of"] is None and j["rows"] == []


def test_funds_bubble(session, client):
    etf = Instrument(ins_code="1", symbol_fa="عیار", instrument_type="etf")
    lev = Instrument(ins_code="2", symbol_fa="اهرم", instrument_type="etf")
    session.add_all([etf, lev])
    session.flush()
    d = date(2026, 11, 10)
    session.add_all(
        [
            FundNav(reg_no="1", date=d, instrument_id=etf.id, fund_type=5, cancel_nav=100.0),
            FundNav(reg_no="2", date=d, instrument_id=lev.id, fund_type=22, cancel_nav=100.0),
            FundNav(reg_no="3", date=d, fund_type=4, cancel_nav=10.0),
            PriceDaily(instrument_id=etf.id, date=d, close=103),
            PriceDaily(instrument_id=lev.id, date=d, close=200),
        ]
    )
    session.flush()
    j = client.get("/funds").json()
    by = {f["reg_no"]: f for f in j["funds"]}
    assert set(by) == {"1", "2"}  # unlisted fund only with listed_only=false
    assert by["1"]["bubble"] == pytest.approx(0.03) and by["1"]["bubble_note"] is None
    assert by["2"]["bubble"] is None and "اهرمی" in by["2"]["bubble_note"]
    assert len(client.get("/funds?listed_only=false").json()["funds"]) == 3
