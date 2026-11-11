"""HTTP API: shapes, the "no recommendation" state, history summaries, adjusted candles.

All rows are hand-made fixtures; nothing here is market data.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from tmon.api.main import create_app
from tmon.core.db import get_session
from tmon.features.builder import get_feature_set
from tmon.storage.models import (
    FeatureRow,
    Instrument,
    ModelRun,
    PriceDaily,
    Signal,
    SignalNote,
)

DAY = dt.date(2025, 3, 1)
NOW = dt.datetime(2025, 3, 1, 12, 0, tzinfo=dt.UTC)


@pytest.fixture
def client(session: Session) -> Iterator[TestClient]:
    app = create_app()
    app.dependency_overrides[get_session] = lambda: session
    with TestClient(app) as c:
        yield c


def _inst(session: Session, code: str, symbol: str) -> Instrument:
    i = Instrument(ins_code=code, symbol_fa=symbol, name_fa=f"شرکت {symbol}", sector_code="27")
    session.add(i)
    session.flush()
    return i


def _signal(
    session: Session, inst: Instrument, day: dt.date, rank: int = 1, **over: object
) -> Signal:
    row = {
        "date": day,
        "timeframe": "D1",
        "instrument_id": inst.id,
        "entry_price": 1000.0,
        "entry_rule": "open_next_day",
        "take_profit": 1060.0,
        "stop_loss": 970.0,
        "horizon_days": 3,
        "p_win": 0.66,
        "ev": 0.031,
        "rank": rank,
        "confidence_tier": "B",
        "position_pct": 0.05,
        "top_reasons": [{"feature": "rsi_14", "value": 55.0, "contribution": 0.4}],
        "risks": ["نوسان بالا"],
        "model_version": "m1",
        "data_snapshot_id": "snap",
        "outcome": "pending",
        "created_at": NOW,
    }
    row.update(over)
    s = Signal(**row)
    session.add(s)
    session.flush()
    return s


def _note(session: Session, day: dt.date, n_rec: int, message: str | None = None) -> None:
    session.add(
        SignalNote(
            date=day,
            timeframe="D1",
            model_version="m1",
            data_snapshot_id="snap",
            n_candidates=12,
            n_recommended=n_rec,
            defensive_mode=False,
            message=message,
            created_at=NOW,
        )
    )
    session.flush()


def test_health(client: TestClient) -> None:
    assert client.get("/health").json() == {"status": "ok"}


def test_recommendations_before_any_run(client: TestClient) -> None:
    r = client.get("/recommendations").json()
    assert r["no_recommendation"] is True
    assert r["supported"] is True
    assert r["date"] is None
    assert r["signals"] == []
    assert "توصیه سرمایه‌گذاری نیست" in r["disclaimer"]


def test_unsupported_timeframes_are_explicit(client: TestClient) -> None:
    for tf in ("W1", "M1"):
        r = client.get("/recommendations", params={"timeframe": tf}).json()
        assert r["supported"] is False
        assert r["no_recommendation"] is True
        assert r["signals"] == []
    assert client.get("/recommendations", params={"timeframe": "H1"}).status_code == 422


def test_no_recommendation_day_carries_the_engine_message(
    client: TestClient, session: Session
) -> None:
    _note(session, DAY, 0, "امروز توصیه‌ای وجود ندارد")
    r = client.get("/recommendations").json()
    assert r["date"] == "2025-03-01"
    assert r["no_recommendation"] is True
    assert r["message"] == "امروز توصیه‌ای وجود ندارد"
    assert r["run"]["n_candidates"] == 12
    assert r["run"]["n_recommended"] == 0


def test_recommendations_are_ranked_and_joined(client: TestClient, session: Session) -> None:
    a, b = _inst(session, "1", "فولاد"), _inst(session, "2", "خودرو")
    _signal(session, b, DAY, rank=2)
    _signal(session, a, DAY, rank=1)
    _note(session, DAY, 2)
    session.add(
        ModelRun(
            timeframe="D1",
            version="m1",
            train_window={"end": "2025-02-28"},
            metrics={"gate": {"tier_a_allowed": False, "reasons": ["کمتر از حداقل"]}},
            created_at=NOW,
        )
    )
    session.flush()
    r = client.get("/recommendations").json()
    assert r["no_recommendation"] is False
    assert [s["instrument"]["symbol"] for s in r["signals"]] == ["فولاد", "خودرو"]
    assert r["signals"][0]["top_reasons"][0]["feature"] == "rsi_14"
    assert r["gate"] == {"tier_a_allowed": False, "reasons": ["کمتر از حداقل"]}
    assert r["available_dates"] == ["2025-03-01"]


def test_recommendations_for_a_specific_date(client: TestClient, session: Session) -> None:
    a = _inst(session, "1", "فولاد")
    _signal(session, a, DAY)
    _note(session, DAY, 1)
    r = client.get("/recommendations", params={"date": "2025-02-20"}).json()
    assert r["date"] == "2025-02-20"
    assert r["no_recommendation"] is True
    assert r["signals"] == []


def test_history_filters_and_summary(client: TestClient, session: Session) -> None:
    a = _inst(session, "1", "فولاد")
    _signal(session, a, dt.date(2025, 2, 1), outcome="tp", realized_return=0.06)
    _signal(session, a, dt.date(2025, 2, 2), outcome="sl", realized_return=-0.03)
    _signal(session, a, dt.date(2025, 2, 3), outcome="expiry", realized_return=0.0)
    _signal(session, a, dt.date(2025, 2, 4))
    h = client.get("/signals/history").json()
    assert h["total"] == 4
    assert h["items"][0]["date"] == "2025-02-04"  # newest first
    s = h["summary"]
    assert (s["total"], s["resolved"], s["pending"]) == (4, 3, 1)
    assert (s["take_profit"], s["stop_loss"], s["expired"]) == (1, 1, 1)
    assert s["mean_realized_return"] == pytest.approx(0.01)

    only = client.get("/signals/history", params={"outcome": "tp"}).json()
    assert only["total"] == 1
    assert only["summary"]["total"] == 4  # the summary covers the whole scope, not the filter
    _signal(session, a, dt.date(2025, 2, 5), outcome="sl_same_day", realized_return=-0.03)
    stops = client.get("/signals/history", params={"outcome": "sl"}).json()
    assert stops["total"] == 2  # "sl" covers both stop-loss variants
    assert client.get("/signals/history", params={"outcome": "bogus"}).status_code == 422
    page = client.get("/signals/history", params={"limit": 2, "offset": 2}).json()
    assert len(page["items"]) == 2


def test_history_empty(client: TestClient) -> None:
    h = client.get("/signals/history").json()
    assert h["items"] == []
    assert h["summary"]["mean_realized_return"] is None


def test_instrument_404(client: TestClient) -> None:
    assert client.get("/instruments/999").status_code == 404


def test_instrument_detail_uses_adjusted_prices(client: TestClient, session: Session) -> None:
    a = _inst(session, "1", "فولاد")
    # A 2-for-1 capital increase: the raw close halves on day 4 although the stock did not move.
    closes = [1000.0, 1000.0, 1000.0, 500.0, 500.0]
    for n, c in enumerate(closes):
        session.add(
            PriceDaily(
                instrument_id=a.id,
                date=dt.date(2025, 2, 1) + dt.timedelta(days=n),
                open=c,
                high=c,
                low=c,
                last=c,
                close=c,
                prev_close=closes[n - 1] if n != 3 else 500.0,  # the exchange's adjusted reference
                volume=1000.0,
                market_halt=False,
            )
        )
    fs = get_feature_set("D1")
    session.add(
        FeatureRow(
            instrument_id=a.id,
            date=DAY,
            feature_set_version=fs.key,
            values={"rsi_14": 61.5, "breadth": 0.55},
        )
    )
    _signal(session, a, DAY)
    session.flush()
    d = client.get(f"/instruments/{a.id}").json()
    assert d["instrument"]["symbol"] == "فولاد"
    assert d["adjusted"] is True
    assert len(d["candles"]) == 5
    closes_out = [c["close"] for c in d["candles"]]
    assert max(closes_out) - min(closes_out) < 1e-6  # no phantom crash in the adjusted series
    feats = {f["feature"]: f["value"] for f in d["features"]}
    assert feats["rsi_14"] == 61.5
    assert feats["adx_14"] is None  # missing stays null, never zero
    assert len(d["signals"]) == 1
    assert "توصیه سرمایه‌گذاری نیست" in d["disclaimer"]


def test_calibration_without_a_model(client: TestClient) -> None:
    c = client.get("/metrics/calibration").json()
    assert c["model_version"] is None
    assert c["backtest"] is None
    assert c["live"]["n"] == 0
    assert c["warnings"]


def test_calibration_reports_backtest_live_and_gate(client: TestClient, session: Session) -> None:
    a = _inst(session, "1", "فولاد")
    prob = {
        "n": 500,
        "base_rate": 0.3,
        "auc": 0.62,
        "brier": 0.2,
        "brier_base_rate": 0.21,
        "brier_skill": 0.05,
        "calibration": [{"bucket": "0.3-0.4", "n": 100, "mean_p": 0.35, "hit_rate": 0.33}],
    }
    session.add(
        ModelRun(
            timeframe="D1",
            version="m1",
            train_window={"end": "2025-02-28"},
            metrics={
                "gate": {"tier_a_allowed": False, "reasons": ["x"]},
                "backtest": {"baseline": {"trades": {}}, "lgbm": {"probabilistic": prob}},
                "warnings": ["هزینه‌ها تأیید نشده‌اند"],
            },
            created_at=NOW,
        )
    )
    _signal(session, a, dt.date(2025, 2, 1), p_win=0.7, outcome="tp", realized_return=0.06)
    _signal(session, a, dt.date(2025, 2, 2), p_win=0.6, outcome="sl", realized_return=-0.03)
    _signal(session, a, dt.date(2025, 2, 3), p_win=0.65)  # pending: excluded
    session.flush()
    c = client.get("/metrics/calibration").json()
    assert c["model_version"] == "m1"
    assert c["trained_through"] == "2025-02-28"
    assert c["backtest"]["auc"] == 0.62
    assert c["backtest"]["buckets"][0]["bucket"] == "0.3-0.4"
    assert c["live"]["n"] == 2
    assert c["live"]["base_rate"] == pytest.approx(0.5)
    assert c["live"]["brier"] == pytest.approx((0.3**2 + 0.6**2) / 2)
    assert c["gate"]["tier_a_allowed"] is False
    assert c["warnings"] == ["هزینه‌ها تأیید نشده‌اند"]


def test_calibration_unsupported_timeframe(client: TestClient) -> None:
    c = client.get("/metrics/calibration", params={"timeframe": "M1"}).json()
    assert c["supported"] is False


def test_cors_allows_get_only(client: TestClient) -> None:
    r = client.options(
        "/recommendations",
        headers={"Origin": "http://localhost:3000", "Access-Control-Request-Method": "POST"},
    )
    assert r.status_code == 400
