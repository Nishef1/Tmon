from __future__ import annotations

import datetime as dt
import json
from collections.abc import Iterator

import numpy as np
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from tmon.api.main import create_app
from tmon.core.db import get_session
from tmon.portfolio import advice as advice_mod
from tmon.portfolio import alerts as alert_store
from tmon.portfolio.briefing import rule_call
from tmon.portfolio.forecast import Position, forecast
from tmon.portfolio.keys import hash_key, matches, new_key
from tmon.portfolio.notify import masked, parse_callback
from tmon.portfolio.watch import (
    URGENT,
    WARN,
    Finding,
    HoldingView,
    WatchState,
    detect_holding,
    parse_quote,
    settings_for,
)
from tmon.storage.models import Instrument, PriceDaily
from tmon.storage.objectstore import MemoryStore
from tmon.tools.v2_ranking import KEY

AT = dt.datetime(2026, 11, 14, 7, 0, tzinfo=dt.UTC)


def _view(**over: object) -> HoldingView:
    base: dict[str, object] = {
        "holding_id": 1,
        "portfolio_id": 1,
        "instrument_id": 10,
        "ins_code": "111",
        "symbol": "خودرو",
        "shares": 1000.0,
        "avg_price": 3000.0,
        "stop_price": None,
        "avg_daily_volume": 1_000_000.0,
    }
    base.update(over)
    return HoldingView(**base)  # type: ignore[arg-type]


def _row(**over: object) -> dict[str, object]:
    row: dict[str, object] = {
        "insCode": "111",
        "lVal18AFC": "خودرو",
        "pDrCotVal": 2950.0,
        "pClosing": 2960.0,
        "priceYesterday": 3000.0,
        "pMax": 3090.0,
        "pMin": 2910.0,
        "qTotTran5J": 100_000.0,
        "qTotCap": 3e8,
        "blDs": [{"n": 1, "pmd": 2940, "qmd": 5000, "pmo": 2950, "qmo": 4000}],
    }
    row.update(over)
    return row


# -- detectors ---------------------------------------------------------------------------------
def test_a_big_sell_queue_is_urgent_and_asks_to_exit() -> None:
    q = parse_quote(
        _row(pDrCotVal=2910.0, blDs=[{"n": 1, "pmd": 0, "qmd": 0, "pmo": 2910, "qmo": 900_000}])
    )
    found = detect_holding(_view(), q, WatchState(), settings_for(None), AT, 210)
    sq = next(f for f in found if f.kind == "sell_queue")
    assert sq.severity == URGENT and sq.ask_exit
    assert any(f.kind == "price_drop" for f in found)


def test_a_sudden_volume_burst_while_falling_alerts() -> None:
    """Iran Khodro at 10:00: a block is dumped within minutes."""
    st = WatchState()
    cfg = settings_for(None)
    h = _view()
    st.push(parse_quote(_row(qTotTran5J=100_000.0, pDrCotVal=3000.0)), AT)
    later = AT + dt.timedelta(minutes=4)
    q = parse_quote(_row(qTotTran5J=900_000.0, pDrCotVal=2900.0))
    st.push(q, later)
    found = detect_holding(h, q, st, cfg, later, 210)
    surge = next(f for f in found if f.kind == "volume_surge")
    assert surge.severity >= WARN and surge.ask_exit
    assert surge.data["pace_x"] > cfg["volume_surge_x"]


def test_the_owners_stop_price_fires() -> None:
    q = parse_quote(_row(pDrCotVal=2700.0))
    found = detect_holding(_view(stop_price=2800.0), q, WatchState(), settings_for(None), AT, 210)
    assert any(f.kind == "stop_loss" and f.severity == URGENT for f in found)


def test_a_quiet_stock_raises_nothing() -> None:
    q = parse_quote(_row(pDrCotVal=3010.0))
    assert detect_holding(_view(), q, WatchState(), settings_for(None), AT, 210) == []


def test_custom_settings_are_merged_with_defaults() -> None:
    cfg = settings_for({"drop_warn_pct": -1})
    assert cfg["drop_warn_pct"] == -1 and cfg["drop_urgent_pct"] == -5


# -- notify / keys -----------------------------------------------------------------------------
def test_callback_data_round_trip() -> None:
    assert parse_callback("a:42:exit") == (42, "exit")
    assert parse_callback("a:x:exit") is None
    assert parse_callback("a:1:sell_all") is None


def test_secrets_are_masked() -> None:
    m = masked({"type": "bale", "token": "123456789:abcdefgh", "chat_id": 5})
    assert "abcdefgh" not in str(m) and m["chat_id"] == 5
    assert masked({"type": "apprise", "url": "ntfy://secret-topic"})["url"] == "ntfy://…"


def test_keys_hash_and_match() -> None:
    k = new_key()
    assert matches(k, hash_key(k)) and not matches(k + "x", hash_key(k))


# -- alert store -------------------------------------------------------------------------------
def test_an_alert_repeats_only_when_it_gets_worse(session: Session) -> None:
    from tmon.storage.models import Portfolio

    p = Portfolio(name="p", key_hash="h", cash=0, settings={}, channels=[], created_at=AT)
    session.add(p)
    session.flush()
    f = Finding("price_drop", WARN, None, "t", "b", "k1")
    assert len(alert_store.record(session, p.id, [f], AT)) == 1
    assert alert_store.record(session, p.id, [f], AT) == []
    worse = Finding("price_drop", URGENT, None, "t", "b", "k1")
    assert len(alert_store.record(session, p.id, [worse], AT)) == 1


# -- briefing rule -----------------------------------------------------------------------------
def test_strong_negative_news_means_exit() -> None:
    h = {"symbol": "خودرو", "verdict": "hold", "reasons": []}
    ev = {"news": [{"title": "زیان سنگین", "direction": -1, "magnitude": 4}], "codal": []}
    assert rule_call(h, ev).action == "exit"
    assert rule_call(h, {"news": [], "codal": []}).action == "hold"


# -- forecast ----------------------------------------------------------------------------------
def test_forecast_bands_are_ordered_and_backtested() -> None:
    rng = np.random.default_rng(1)
    t, n = 700, 2
    lr = rng.normal(0.0005, 0.02, size=(t, n))
    closes = 1000 * np.exp(np.vstack([np.zeros((1, n)), np.cumsum(lr, axis=0)]))
    dates = [dt.date(2023, 1, 1) + dt.timedelta(days=i) for i in range(t + 1)]
    pos = [
        Position(1, "الف", 100, float(closes[-1, 0]), 1000.0),
        Position(2, "ب", 100, float(closes[-1, 1]), 1000.0),
    ]
    doc = forecast(pos, dates, closes)
    assert doc["available"]
    keys = [h["key"] for h in doc["horizons"]]
    assert keys[0] == "week" and keys[-1] == "year"
    for h in doc["horizons"]:
        b = h["portfolio"]
        assert b["q05"] <= b["q50"] <= b["q95"]
        assert 0 <= b["p_gain"] <= 1
        assert {s["symbol"] for s in h["symbols"]} == {"الف", "ب"}
    week = doc["horizons"][0]["backtest"]
    assert week["n"] > 0 and 0 <= week["coverage80"] <= 1


# -- API ---------------------------------------------------------------------------------------
@pytest.fixture
def client(session: Session) -> Iterator[TestClient]:
    app = create_app()
    app.dependency_overrides[get_session] = lambda: session
    with TestClient(app) as c:
        yield c


def _prices(session: Session, symbol: str, code: str, start: float, days: int = 300) -> int:
    i = Instrument(ins_code=code, symbol_fa=symbol, name_fa=f"شرکت {symbol}", sector_code="34")
    session.add(i)
    session.flush()
    rng = np.random.default_rng(int(code))
    p = start
    d0 = dt.date(2025, 9, 1)
    for k in range(days):
        p *= float(np.exp(rng.normal(0, 0.02)))
        session.add(
            PriceDaily(
                instrument_id=i.id,
                date=d0 + dt.timedelta(days=k),
                open=p,
                high=p,
                low=p,
                last=p,
                close=p,
                prev_close=p,
                volume=1e6,
                value=p * 1e6,
                fetched_at=AT,
            )
        )
    session.flush()
    return i.id


def test_portfolio_flow(
    client: TestClient, session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    weak = _prices(session, "ضعیف", "1001", 1000)
    strong = _prices(session, "قوی", "1002", 2000)
    store = MemoryStore()
    doc = {
        "as_of": "2026-11-14",
        "recommendation_allowed": False,
        "round_trip_cost": 0.017512,
        "evidence": [
            {"horizon_days": 20, "top_excess": 0.06, "bottom_excess": -0.04, "excess_t": 4.0}
        ],
        "universe": [
            {"id": weak, "score": 0.1, "zone": "avoid", "queue_state": "none"},
            {"id": strong, "score": 0.95, "zone": "buy", "queue_state": "none"},
        ],
    }
    store.put("artifacts", KEY, json.dumps(doc).encode(), "application/json")
    monkeypatch.setattr(advice_mod, "get_object_store", lambda: store)
    monkeypatch.setattr(
        advice_mod, "get_settings", lambda: type("S", (), {"minio_artifact_bucket": "artifacts"})
    )

    r = client.post("/portfolios", json={"name": "من", "cash": 50_000_000})
    assert r.status_code == 201
    pid, key = r.json()["id"], r.json()["key"]
    hdr = {"X-Portfolio-Key": key}
    assert client.get(f"/portfolios/{pid}").status_code == 404
    assert client.get(f"/portfolios/{pid}", headers={"X-Portfolio-Key": "nope"}).status_code == 404

    r = client.post(
        f"/portfolios/{pid}/holdings",
        json={"symbol": "ضعيف", "shares": 1000, "avg_price": 900},
        headers=hdr,
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["holdings"][0]["symbol"] == "ضعیف" and body["holdings"][0]["close"] is not None

    adv = client.get(f"/portfolios/{pid}/advice", headers=hdr).json()
    assert adv["holdings"][0]["verdict"] == "weak"
    assert adv["switches"] and adv["switches"][0]["buy"]["symbol"] == "قوی"
    assert adv["validated"] is False

    fc = client.get(f"/portfolios/{pid}/forecast", headers=hdr).json()
    assert fc["available"] and len(fc["horizons"]) == 5

    r = client.patch(
        f"/portfolios/{pid}",
        json={"channels": [{"type": "bale", "token": "123456789:secretsecret", "chat_id": "9"}]},
        headers=hdr,
    )
    assert r.status_code == 200 and "secretsecret" not in r.text
    # sending the masked channel back keeps the stored token
    r = client.patch(f"/portfolios/{pid}", json={"channels": r.json()["channels"]}, headers=hdr)
    assert r.status_code == 200, r.text

    from tmon.storage.models import Portfolio

    p = session.get(Portfolio, pid)
    assert p is not None and p.channels[0]["token"] == "123456789:secretsecret"
    a = alert_store.record(
        session, pid, [Finding("sell_queue", URGENT, weak, "صف فروش", "b", "x", ask_exit=True)], AT
    )[0]
    session.commit()
    alerts = client.get(f"/portfolios/{pid}/alerts", headers=hdr).json()
    assert alerts[0]["ask_exit"] and alerts[0]["symbol"] == "ضعیف"
    r = client.post(f"/portfolios/{pid}/alerts/{a.id}/answer", json={"answer": "exit"}, headers=hdr)
    assert r.json()["answer"] == "exit"
    assert client.get(f"/portfolios/{pid}/alerts?after={a.id}", headers=hdr).json() == []

    b = client.post(f"/portfolios/{pid}/briefing", headers=hdr)
    assert b.status_code == 200, b.text
    assert b.json()["method"] == "rules"
    assert client.get(f"/portfolios/{pid}/briefing", headers=hdr).json()["id"] == b.json()["id"]


# -- macro / foreign ---------------------------------------------------------------------------
def test_a_measured_macro_sensitivity_becomes_pressure(session: Session) -> None:
    from tmon.portfolio import macro
    from tmon.storage.models import MacroSeries

    rng = np.random.default_rng(5)
    i = Instrument(ins_code="777", symbol_fa="مسی", name_fa="مس", sector_code="27")
    session.add(i)
    session.flush()
    d0 = dt.date(2025, 1, 1)
    cu = 4.0 * np.cumprod(1 + rng.normal(0, 0.015, 300))
    px = 1000.0
    for k in range(300):
        day = d0 + dt.timedelta(days=k)
        session.add(MacroSeries(series="copper_usd", source="t", ref_period=day, value=cu[k]))
        # Tehran's session on day k prices copper's move between days k-2 and k-1, beta 1
        move = cu[k - 1] / cu[k - 2] - 1 if k >= 2 else 0.0
        prev = px
        px *= 1 + move + float(rng.normal(0, 0.004))
        session.add(
            PriceDaily(
                instrument_id=i.id,
                date=day,
                open=px,
                high=px,
                low=px,
                last=px,
                close=px,
                prev_close=prev,
                volume=1e6,
                value=px * 1e6,
                fetched_at=AT,
            )
        )
    session.flush()
    series = macro.load_series(session)
    beta, t, n = macro.sensitivities(session, i.id, series)["copper_usd"]
    assert 0.7 < beta < 1.3 and t > 5 and n > 200
    # copper falls 5% after the stock's last close
    last_day = d0 + dt.timedelta(days=299)
    session.add(
        MacroSeries(
            series="copper_usd",
            source="t",
            ref_period=last_day + dt.timedelta(days=1),
            value=cu[-1] * 0.95,
        )
    )
    session.flush()
    series = macro.load_series(session)
    p = macro.holding_pressure(session, i.id, last_day, series, macro.moves(series))
    assert p["items"][0]["series"] == "copper_usd" and p["total"] < -0.03
    call = rule_call(
        {"symbol": "مسی", "verdict": "hold", "reasons": []},
        {"news": [], "codal": [], "macro": p},
    )
    assert call.action == "reduce" and any("مس" in r for r in call.reasons_fa)


def test_only_real_shocks_raise_market_news() -> None:
    from tmon.portfolio.monitor import FOREIGN_SHOCK, news_finding
    from tmon.storage.models import NewsRaw

    assert FOREIGN_SHOCK.search("Iran reports tanker fire after mine strike in Hormuz")
    assert not FOREIGN_SHOCK.search("Iran braces for a budget without oil revenue")
    assert not FOREIGN_SHOCK.search("Warning issued toward Iran budget")
    item = NewsRaw(
        id=1,
        source="cnbc_world",
        url="u",
        title="US strikes on Iran resume",
        title_norm="x",
        summary=None,
    )
    f = news_finding(1, item, None, None)
    assert f is not None and f.severity == WARN and not f.ask_exit
    calm = NewsRaw(id=2, source="irna", url="u", title="افتتاح نمایشگاه", title_norm="x")
    assert news_finding(1, calm, None, None) is None


def test_entries_empty_portfolio(client: TestClient) -> None:
    r = client.post("/portfolios", json={"name": "ورود", "cash": 1_000_000})
    pid, key = r.json()["id"], r.json()["key"]
    body = client.get(f"/portfolios/{pid}/entries", headers={"X-Portfolio-Key": key})
    assert body.status_code == 200
    doc = body.json()
    assert doc["reviews"] == [] and doc["skipped"] == [] and doc["lessons"] == []
    assert (
        client.get(f"/portfolios/{pid}/entries", headers={"X-Portfolio-Key": "x"}).status_code
        == 404
    )


def test_duplicate_symbol_resolves_to_the_instrument_with_prices(session: Session) -> None:
    """A listing twin without prices must not shadow the real one (it showed 'no price')."""
    from tmon.api.routers.portfolios import _best_candidate

    empty = Instrument(ins_code="9001", symbol_fa="فزرین")
    real = Instrument(ins_code="9002", symbol_fa="فزرین")
    session.add_all([empty, real])
    session.flush()
    for k in range(3):
        session.add(
            PriceDaily(
                instrument_id=real.id,
                date=dt.date(2026, 11, 10 + k),
                close=12_000.0,
                prev_close=12_000.0,
                volume=1e6,
                value=1e10,
                fetched_at=AT,
            )
        )
    session.flush()
    assert _best_candidate(session, [empty, real]) is real
    assert _best_candidate(session, [real, empty]) is real
    assert _best_candidate(session, [empty]) is empty
    assert _best_candidate(session, []) is None


def _series(drifts: list[float], sigma: float = 0.012, seed: int = 5) -> tuple[list, np.ndarray]:
    rng = np.random.default_rng(seed)
    lr = np.concatenate([rng.normal(m, sigma, size=(n, 1)) for n, m in drifts])
    closes = 1000 * np.exp(np.vstack([np.zeros((1, 1)), np.cumsum(lr, axis=0)]))
    dates = [dt.date(2022, 1, 1) + dt.timedelta(days=i) for i in range(len(closes))]
    return dates, closes


def test_a_trend_that_did_not_persist_is_not_extrapolated() -> None:
    """A strong run followed by a long fall: the drift weight must come out low, and the band
    without any trend is reported next to the one with it."""
    dates, closes = _series([(400, 0.004), (500, -0.003)])
    pos = [Position(1, "الف", 100, float(closes[-1, 0]), 1000.0)]
    doc = forecast(pos, dates, closes)
    month = next(h for h in doc["horizons"] if h["key"] == "month")
    assert month["drift_weight"] <= 0.25
    assert {"q10", "q50", "q90"} <= set(month["no_trend"])
    assert abs(month["no_trend"]["q50"]) < abs(0.02 * 20)  # no trend: the median stays near zero


def test_a_trend_that_kept_going_keeps_a_larger_weight() -> None:
    dates, closes = _series([(900, 0.003)], sigma=0.006)
    pos = [Position(1, "الف", 100, float(closes[-1, 0]), 1000.0)]
    doc = forecast(pos, dates, closes)
    month = next(h for h in doc["horizons"] if h["key"] == "month")
    assert month["drift_weight"] >= 0.5
    assert month["portfolio"]["q50"] > month["no_trend"]["q50"]
