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


def test_symbol_in_a_limit_queue_gets_no_decision() -> None:
    doc = _doc()
    doc["rows"][0]["queue_state"] = "buy_queue"
    d = dash.decide(_inst("الف"), doc, None)
    assert d.verdict == "none" and "صف خرید" in d.headline
    assert d.rank == 1


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


def _uni_doc() -> dict[str, Any]:
    doc = _doc()
    sig = {"ind_buy_power": 0.9, "rv_20": 0.3, "dist_high_52w": 0.7, "mom_12_1": 0.6}
    doc["universe"] = [
        {"id": 1, "eligible": True, "halted": False, "queue_state": "none", "median_value": 9e11,
         "missing": [], "score": 0.95, "zone": "buy", "signals": sig},
        {"id": 7, "eligible": False, "halted": False, "queue_state": "none", "median_value": 3e9,
         "missing": [], "score": 0.97, "zone": "buy", "signals": sig},
        {"id": 8, "eligible": False, "halted": False, "queue_state": "none", "median_value": 3e9,
         "missing": [], "score": 0.1, "zone": "avoid", "signals": sig},
        {"id": 9, "eligible": False, "halted": False, "queue_state": "none", "median_value": 3e9,
         "missing": ["mom_12_1"], "score": None, "zone": None, "signals": {}},
        {"id": 10, "eligible": False, "halted": False, "queue_state": "buy_queue",
         "median_value": 3e9, "missing": [], "score": 0.8, "zone": "hold", "signals": sig},
    ]  # fmt: skip
    return doc


def _with_id(i: int, sym: str) -> Instrument:
    return Instrument(id=i, ins_code=f"c{i}", symbol_fa=sym, instrument_type="stock")


def test_every_scored_stock_gets_a_gauge_but_only_basket_names_are_advice() -> None:
    doc = _uni_doc()
    doc["recommendation_allowed"] = True
    inside = dash.decide(_with_id(1, "الف"), doc, None)
    assert inside.gauge == pytest.approx(95) and inside.in_basket and inside.advice_allowed
    out = dash.decide(_with_id(7, "ثالث"), doc, 3e9)
    assert out.verdict == "buy" and out.gauge == pytest.approx(97)
    assert not out.in_basket and not out.advice_allowed
    assert "کم‌اعتبار" in out.headline
    assert any("اثبات نشده" in r for r in out.reasons)
    assert any("رتبهٔ" in r and "نماد دارای امتیاز" in r for r in out.reasons)
    assert dash.decide(_with_id(8, "رابع"), doc, 3e9).verdict == "sell"


def test_unscored_and_queued_stocks_say_exactly_why() -> None:
    doc = _uni_doc()
    d = dash.decide(_with_id(9, "خامس"), doc, 3e9)
    assert d.verdict == "none" and d.gauge is None and "روند ۱۲ ماهه" in d.headline
    q = dash.decide(_with_id(10, "سادس"), doc, 3e9)
    assert q.verdict == "none" and "صف خرید" in q.headline and q.gauge == pytest.approx(80)


def test_stock_not_traded_on_the_last_day_gets_no_score() -> None:
    d = dash.decide(_with_id(99, "غایب"), _uni_doc(), None)
    assert d.verdict == "none" and d.gauge is None and "معامله نشده" in d.headline


def test_decision_explains_in_plain_words_and_says_how_long_to_hold() -> None:
    doc = _doc()
    doc["evidence"] = [{"horizon_days": 20, "top_excess": 0.04}, {"horizon_days": 5}]
    d = dash.decide(_inst("الف"), doc, None)
    assert "۱۰٪ برتر" in d.summary
    assert d.signals[0].key == "ind_buy_power"
    assert d.signals[0].pct == pytest.approx(90)
    assert "بهتر از 90٪" in " ".join(d.reasons)
    assert d.holding is not None and d.holding.horizon_days == 20
    assert d.holding.expected_excess == pytest.approx(0.04)
    text = " ".join(d.holding.lines)
    assert "همان روز" in text and "4.0٪" in text and "هر ماه" in text
    assert "توصیهٔ مطمئن نیست" in text  # the gates have not passed in this document
    hold = dash.decide(_inst("ب"), doc, None)
    assert hold.holding is not None and "خرید تازه" in " ".join(hold.holding.lines)
    assert dash.decide(_inst("د"), doc, None).holding is None


def test_dashboard_shows_the_next_meeting_and_skips_cancelled_or_past_ones(
    client: TestClient, session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tmon.storage.models import CorporateEvent

    today = dt.datetime.now(dt.UTC).date()
    session.add(_inst("الف"))
    base = {"instrument_id": 1, "type": "agm_dividend", "title": "آگهی"}
    session.add_all(
        [
            CorporateEvent(**base, stage="invitation", announced_at=today,
                           event_date=today + dt.timedelta(days=9)),
            CorporateEvent(**base, stage="egm_invitation", announced_at=today,
                           event_date=today + dt.timedelta(days=3)),
            CorporateEvent(**base, stage="meeting_cancelled", announced_at=today),
            CorporateEvent(**base, stage="invitation", announced_at=today - dt.timedelta(days=60),
                           event_date=today - dt.timedelta(days=30)),
        ]
    )  # fmt: skip
    session.commit()
    monkeypatch.setattr(dash, "_ranking_doc", lambda: _doc())
    j = client.get("/instruments/1/dashboard").json()
    # the cancellation (same day as both invitations) removes both; the past one is not "next"
    assert j["meeting"] is None
    assert any(e["label"] == "لغو مجمع" for e in j["events"])
    session.add(
        CorporateEvent(**base, stage="invitation", announced_at=today + dt.timedelta(days=1),
                       event_date=today + dt.timedelta(days=20))
    )  # fmt: skip
    session.commit()
    assert client.get("/instruments/1/dashboard").json()["meeting"]["days_left"] == 20
