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
    inflation_since,
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


def test_inflation_since_a_buy_day():
    mom = [
        Release(date(2026, 8, 22), date(2026, 8, 29), 0.02, None),
        Release(date(2026, 9, 22), date(2026, 9, 29), 0.03, None),
        Release(date(2026, 10, 22), date(2026, 10, 28), 0.044, None),
    ]
    # a full month counts its whole figure; the 6 days after it are carried at its rate
    whole = inflation_since(mom, date(2026, 9, 22), date(2026, 10, 28))
    assert whole is not None and whole.value == pytest.approx(1.044 ** (36 / 30) - 1)
    assert whole.estimated_days == 6
    # half of Mehr (15 of 30 days), then 10 days past the last release at Mehr's rate
    part = inflation_since(mom, date(2026, 10, 7), date(2026, 11, 1))
    assert part is not None
    assert part.value == pytest.approx(1.044 ** (15 / 30) * 1.044 ** (10 / 30) - 1)
    assert part.estimated_days == 10 and part.last_ref == date(2026, 10, 22)
    # Mehr is not out on 27 October, so Shahrivar's rate is carried instead
    early = inflation_since(mom, date(2026, 10, 1), date(2026, 10, 27))
    assert early is not None and early.estimated_days == 26
    assert early.value == pytest.approx(1.03 ** (26 / 31) - 1)
    # before the first placeable month there is nothing to say
    assert inflation_since(mom, date(2026, 8, 1), date(2026, 10, 1)) is None


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


def test_fund_kind_and_industry(session, client):
    etf = Instrument(
        ins_code="9",
        symbol_fa="دارونو",
        instrument_type="etf_equity",
        tags={"subsector_code": "6819", "fund_desc": "نوع صندوق : سهامی بخشی در صنعت دارویی"},
    )
    session.add(etf)
    session.flush()
    session.add(FundNav(reg_no="9", date=date(2026, 11, 10), instrument_id=etf.id, fund_type=21))
    session.flush()
    f = client.get("/funds").json()["funds"][0]
    assert f["kind"] == "صندوق سهامی بخشی" and f["industry"] == "دارویی"


def test_rights_bubble(session, client):
    base = Instrument(ins_code="10", symbol_fa="فجهان", instrument_type="stock")
    right = Instrument(ins_code="11", symbol_fa="فجهانح", instrument_type="right")
    odd = Instrument(ins_code="12", symbol_fa="کمح", instrument_type="right")
    old = Instrument(ins_code="13", symbol_fa="قدیمح", instrument_type="right")
    session.add_all([base, right, odd, old])
    session.flush()
    d = date(2026, 11, 16)
    session.add_all(
        [
            PriceDaily(instrument_id=base.id, date=d, close=3000),
            PriceDaily(instrument_id=right.id, date=d, close=1800),
            PriceDaily(instrument_id=odd.id, date=d, close=500),
            PriceDaily(instrument_id=old.id, date=date(2026, 9, 1), close=500),
        ]
    )
    session.flush()
    j = client.get("/rights").json()
    by = {r["symbol"]: r for r in j["rights"]}
    assert set(by) == {"فجهانح", "کمح"}  # not traded in the last 30 days: left out
    assert by["فجهانح"]["value"] == 2000 and by["فجهانح"]["bubble"] == pytest.approx(-0.1)
    assert by["کمح"]["bubble"] is None and by["کمح"]["bubble_note"] == "سهم پایه پیدا نشد"
    assert j["rights"][0]["symbol"] == "فجهانح"


def test_compare_symbols_real_return(session, client):
    from datetime import timedelta

    stock = Instrument(ins_code="20", symbol_fa="شکام", instrument_type="stock")
    session.add(stock)
    session.flush()
    d = date(2026, 11, 16)
    session.add_all(
        [
            PriceDaily(instrument_id=stock.id, date=d - timedelta(days=370), close=100),
            PriceDaily(instrument_id=stock.id, date=d, close=300, value=1e9),
            MacroSeries(
                series="cpi_yoy",
                source="sci",
                ref_period=date(2026, 10, 22),
                release_date=date(2026, 10, 28),
                value=1.0,
            ),
        ]
    )
    session.flush()
    j = client.get("/compare/symbols?months=12").json()
    row = j["rows"][0]
    assert row["kind"] == "سهم" and row["bubble"] is None
    assert row["nominal_return"] == pytest.approx(2.0)
    assert row["real_return"] == pytest.approx(0.5)  # 3x the money against 2x the prices
    assert j["inflation"] == pytest.approx(1.0) and j["inflation_note"] is None
    j3 = client.get("/compare/symbols?months=3").json()
    assert j3["inflation"] == pytest.approx(2**0.25 - 1) and "تخمین" in j3["inflation_note"]
    assert client.get("/compare/symbols?months=6").status_code == 422
