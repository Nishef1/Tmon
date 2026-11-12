"""Symbol dashboard: price/flow numbers and the buy / hold / sell / none decision with reasons."""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from tmon.api.main import create_app
from tmon.api.routers import dashboard as dash
from tmon.core.db import get_session
from tmon.storage.models import ClientTypeDaily, Instrument, PriceDaily

DAY = dt.date(2026, 11, 10)


def _doc(allowed: bool = False) -> dict[str, Any]:
    sig = {"ind_buy_power": 0.9, "rv_20": 0.5, "dist_high_52w": 0.7, "mom_12_1": 0.1}
    rows = [
        {"rank": 1, "symbol": "الف", "zone": "buy", "score": 0.95, "signals": sig,
         "median_value": 9e11},
        {"rank": 2, "symbol": "ب", "zone": "hold", "score": 0.8, "signals": sig,
         "median_value": 8e11},
        {"rank": 3, "symbol": "ج", "zone": "avoid", "score": 0.2, "signals": sig,
         "median_value": 7e11},
        {"rank": 4, "symbol": "د", "zone": "excluded", "score": None, "signals": {},
         "median_value": 6e11},
    ]  # fmt: skip
    return {
        "recommendation_allowed": allowed,
        "basket_size": 4,
        "as_of": "2026-11-10",
        "buy_top_frac": 0.1,
        "hold_top_frac": 0.3,
        "rows": rows,
    }


def _inst(sym: str, kind: str = "stock") -> Instrument:
    return Instrument(id=1, ins_code="c1", symbol_fa=sym, instrument_type=kind)


@pytest.mark.parametrize(
    ("sym", "verdict"), [("الف", "buy"), ("ب", "hold"), ("ج", "sell"), ("د", "none"), ("ه", "none")]
)
def test_verdict_by_zone(sym: str, verdict: str) -> None:
    d = dash.decide(_inst(sym), _doc(), 1e11)
    assert d.verdict == verdict
    assert d.headline and d.label


def test_reasons_carry_rank_and_signals_and_gate_status() -> None:
    d = dash.decide(_inst("الف"), _doc(allowed=False), None)
    text = " ".join(d.reasons)
    assert "رتبهٔ 1 از 4" in text and "قدرت خریدار حقیقی" in text and "روند ۱۲ ماههٔ" in text
    assert not d.advice_allowed
    assert dash.decide(_inst("الف"), _doc(allowed=True), None).advice_allowed


def test_outside_basket_states_the_value_floor() -> None:
    d = dash.decide(_inst("ه"), _doc(), 5e10)
    assert d.verdict == "none"
    assert any("حداقل لازم" in r for r in d.reasons)


def test_non_stock_and_missing_ranking() -> None:
    assert "صندوق" in dash.decide(_inst("ف", "etf_equity"), _doc(), None).headline
    assert "اختیار" in dash.decide(_inst("ف", "option_call"), _doc(), None).headline
    assert dash.decide(_inst("الف"), None, None).verdict == "none"


@pytest.fixture
def client(session: Session) -> Iterator[TestClient]:
    app = create_app()
    app.dependency_overrides[get_session] = lambda: session
    with TestClient(app) as c:
        yield c


def test_endpoint_numbers(
    client: TestClient, session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    session.add(_inst("الف"))
    for i in range(35):
        session.add(
            PriceDaily(
                instrument_id=1,
                date=DAY - dt.timedelta(days=i),
                open=100,
                high=104,
                low=99,
                last=103,
                close=102,
                prev_close=100,
                volume=1000 if i else 3000,
                value=1e9,
                trades=50,
                limit_up=103,
                limit_down=97,
            )
        )
    session.add(
        ClientTypeDaily(
            instrument_id=1,
            date=DAY,
            buy_count_i=10,
            sell_count_i=20,
            buy_count_n=1,
            sell_count_n=1,
            buy_volume_i=800,
            sell_volume_i=300,
            buy_volume_n=200,
            sell_volume_n=700,
            buy_value_i=4e9,
            sell_value_i=1e9,
            buy_value_n=1e9,
            sell_value_n=4e9,
        )
    )
    session.commit()
    monkeypatch.setattr(dash, "_ranking_doc", lambda: _doc())
    r = client.get("/instruments/1/dashboard")
    assert r.status_code == 200
    j = r.json()
    p, f = j["price"], j["flow"]
    assert p["close_change"] == pytest.approx(0.02)
    assert p["volume_ratio_30"] == pytest.approx(3.0)
    assert p["avg_volume_10"] == pytest.approx((3000 + 9 * 1000) / 10)
    assert f["per_capita_buy"] == pytest.approx(4e8)
    assert f["per_capita_sell"] == pytest.approx(5e7)
    assert f["power"] == pytest.approx(8.0)
    assert f["net_real_value"] == pytest.approx(3e9)
    assert j["decision"]["verdict"] == "buy"
    assert client.get("/instruments/999/dashboard").status_code == 404
