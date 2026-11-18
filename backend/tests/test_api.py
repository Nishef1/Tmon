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
from tmon.domain.agm import monthly_from_annual
from tmon.features.builder import get_feature_set
from tmon.storage.models import (
    CodalLetter,
    CorporateEvent,
    FeatureRow,
    Instrument,
    MacroSeries,
    PriceDaily,
    Shareholder,
)
from tmon.storage.seed import seed_market_rules

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


def test_health(client: TestClient) -> None:
    assert client.get("/health").json() == {"status": "ok"}


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
    assert "signals" not in d  # the v1 signal model is no longer published
    assert "توصیه سرمایه‌گذاری نیست" in d["disclaimer"]


def test_cors_allows_get_only(client: TestClient) -> None:
    r = client.options(
        "/freshness",
        headers={"Origin": "http://localhost:3000", "Access-Control-Request-Method": "POST"},
    )
    assert r.status_code == 400


def test_live_snapshot_and_book_with_staleness_and_change(
    client: TestClient, session: Session
) -> None:
    from tmon.core.timeutil import utcnow
    from tmon.storage.models import IntradaySnapshot, OrderBookSnapshot

    a = _inst(session, "1", "فولاد")
    assert client.get(f"/instruments/{a.id}/live").json()["available"] is False
    assert client.get("/instruments/999/live").status_code == 404

    now = utcnow()
    yesterday = now.astimezone(dt.UTC).date() - dt.timedelta(days=1)
    session.add(PriceDaily(instrument_id=a.id, date=yesterday, close=1000.0))
    session.add(IntradaySnapshot(instrument_id=a.id, ts=now, last_price=1030.0, cum_volume=500.0))
    level = {
        "row": 1,
        "bid_price": 1029.0,
        "bid_volume": 100.0,
        "bid_count": 3,
        "ask_price": 1031.0,
        "ask_volume": 80.0,
        "ask_count": 2,
    }
    session.add(OrderBookSnapshot(instrument_id=a.id, ts=now, levels=[level]))
    session.flush()
    body = client.get(f"/instruments/{a.id}/live").json()
    assert body["available"] and not body["stale"] and body["age_seconds"] < 60
    assert body["last_price"] == 1030.0 and body["reference_price"] == 1000.0
    assert body["change_pct"] == pytest.approx(0.03)
    assert body["book"][0]["bid_price"] == 1029.0 and "توصیه سرمایه‌گذاری نیست" in body["disclaimer"]

    old = now - dt.timedelta(minutes=30)
    session.add(IntradaySnapshot(instrument_id=a.id, ts=old, last_price=900.0, cum_volume=1.0))
    session.flush()
    assert client.get(f"/instruments/{a.id}/live").json()["last_price"] == 1030.0  # newest wins
    session.query(IntradaySnapshot).filter(IntradaySnapshot.ts == now).delete()
    session.flush()
    assert client.get(f"/instruments/{a.id}/live").json()["stale"] is True


def _priced(session: Session, symbol: str = "فملی", close: float = 10000.0) -> Instrument:
    a = _inst(session, "77", symbol)
    session.add(
        PriceDaily(instrument_id=a.id, date=DAY, open=close, high=close, low=close, last=close,
                   close=close, prev_close=close, volume=1.0, market_halt=False)
    )  # fmt: skip
    session.flush()
    return a


def test_instrument_detail_lists_codal_events(client: TestClient, session: Session) -> None:
    a = _priced(session)
    session.add(
        CorporateEvent(instrument_id=a.id, type="agm_dividend", stage="decisions",
                       title="تصمیمات مجمع عمومی عادی سالیانه", announced_at=DAY,
                       source="codal", source_url="https://www.codal.ir/Reports/x", tracing_no=1)
    )  # fmt: skip
    session.flush()
    ev = client.get(f"/instruments/{a.id}").json()["events"]
    assert ev == [
        {
            "type": "agm_dividend",
            "stage": "decisions",
            "title": "تصمیمات مجمع عمومی عادی سالیانه",
            "announced_at": DAY.isoformat(),
            "url": "https://www.codal.ir/Reports/x",
        }
    ]


def test_instrument_detail_lists_codal_letters_newest_first(
    client: TestClient, session: Session
) -> None:
    a = _priced(session)
    for no, day, title in ((1, 1, "قدیمی"), (2, 5, "جدید")):
        session.add(
            CodalLetter(tracing_no=no, instrument_id=a.id, symbol="فملی", title=title,
                        published_at=dt.datetime(2025, 3, day, 9, 0, tzinfo=dt.UTC),
                        url=f"https://www.codal.ir/{no}",
                        fetched_at=dt.datetime(2025, 3, 6, tzinfo=dt.UTC))
        )  # fmt: skip
    session.flush()
    letters = client.get(f"/instruments/{a.id}").json()["letters"]
    assert [x["title"] for x in letters] == ["جدید", "قدیمی"]
    assert letters[0]["published_at"] == "2025-03-05"


def test_agm_decision_uses_stored_price_rate_and_costs(
    client: TestClient, session: Session
) -> None:
    seed_market_rules(session)
    a = _priced(session)
    session.add(MacroSeries(series="rf_1y_ytm", source="tsetmc", ref_period=DAY, value=0.30))
    session.flush()
    r = client.get(f"/instruments/{a.id}/agm", params={"dps": 1000, "months_to_payment": 6})
    assert r.status_code == 200, r.text
    d = r.json()
    inputs = {i["name"]: i for i in d["inputs"]}
    assert inputs["price_now"]["value"] == 10000.0
    r_m = monthly_from_annual(0.30)
    assert inputs["monthly_discount"]["value"] == pytest.approx(r_m)
    assert "rf_1y_ytm" in inputs["monthly_discount"]["source"]
    assert inputs["months_alt"]["value"] == 6
    assert inputs["dividend_tax"]["source"].startswith("default 0")
    assert d["net_hold"] == pytest.approx(1000 / (1 + r_m) ** 6)
    rt = inputs["round_trip_costs"]["value"]
    assert rt > 0
    assert d["net_sell"] == pytest.approx(10000 * ((1 + r_m) ** 6 - 1) - rt)
    assert d["decision"] == ("hold" if d["net_hold"] > d["net_sell"] else "sell")


def test_agm_decision_needs_a_rate_when_none_is_stored(
    client: TestClient, session: Session
) -> None:
    seed_market_rules(session)
    a = _priced(session)
    r = client.get(f"/instruments/{a.id}/agm", params={"dps": 1000, "months_to_payment": 6})
    assert r.status_code == 422
    ok = client.get(
        f"/instruments/{a.id}/agm",
        params={"dps": 1000, "months_to_payment": 6, "monthly_discount": 0.03,
                "alt_monthly_return": 0.02},
    )  # fmt: skip
    assert ok.status_code == 200
    assert {i["name"]: i["source"] for i in ok.json()["inputs"]}["monthly_discount"] == "user"


def test_screener_joins_prices_and_features(client: TestClient, session: Session) -> None:
    a = _inst(session, "s1", "الف")
    b = _inst(session, "s2", "ب")
    for inst, close, prev in ((a, 1100.0, 1000.0), (b, 950.0, 1000.0)):
        session.add(
            PriceDaily(instrument_id=inst.id, date=DAY, close=close, prev_close=prev,
                       value=5e9, trades=10, market_halt=False)
        )  # fmt: skip
    session.add(
        FeatureRow(instrument_id=a.id, date=DAY, feature_set_version=get_feature_set("D1").key,
                   values={"rsi_14": 61.0, "ind_buy_power": 1.8})
    )  # fmt: skip
    session.flush()

    body = client.get("/screener", params={"sort": "change_pct"}).json()
    assert body["prices_date"] == DAY.isoformat()
    assert [r["instrument"]["symbol"] for r in body["rows"]] == ["الف", "ب"]
    top = body["rows"][0]
    assert top["change_pct"] == pytest.approx(0.1)
    assert top["rsi_14"] == 61.0 and top["ind_buy_power"] == 1.8
    assert "p_win" not in top and "scores_date" not in body

    by_change = client.get("/screener", params={"sort": "change_pct", "q": "الف"}).json()
    assert by_change["total"] == 1 and by_change["rows"][0]["instrument"]["symbol"] == "الف"
    assert client.get("/screener", params={"sort": "ev"}).status_code == 422


def test_screener_carries_flow_columns_and_decision(
    client: TestClient, session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tmon.api.routers import screener as scr
    from tmon.storage.models import ClientTypeDaily

    a = _inst(session, "s1", "الف")
    b = _inst(session, "s2", "ب")
    for i, inst in enumerate((a, b)):
        for k in range(3):
            session.add(
                PriceDaily(instrument_id=inst.id, date=DAY - dt.timedelta(days=k), close=1100,
                           prev_close=1000, volume=3000 if k == 0 else 1000, value=5e9,
                           trades=10, market_halt=False)
            )  # fmt: skip
        session.add(
            ClientTypeDaily(instrument_id=inst.id, date=DAY, buy_count_i=10, sell_count_i=20,
                            buy_value_i=4e9 * (i + 1), sell_value_i=1e9)
        )  # fmt: skip
    session.flush()
    doc = {"recommendation_allowed": False, "basket_size": 2, "as_of": DAY.isoformat(),
           "buy_top_frac": 0.1, "hold_top_frac": 0.3,
           "verdict": {"horizon_days": 60, "candidate_top_frac": 0.5, "avoid_bottom_frac": 0.4,
                       "candidate_grade": "unproven", "avoid_grade": "unproven"},
           "exposure": {"exposure": 0.8},
           "rows": [{"rank": 1, "symbol": "ب", "zone": "buy", "band": "candidate", "score": 0.9,
                     "signals": {}, "median_value": 5e9},
                    {"rank": 2, "symbol": "الف", "zone": "avoid", "band": "avoid", "score": 0.1,
                     "signals": {}, "median_value": 5e9}]}  # fmt: skip
    monkeypatch.setattr(scr, "_ranking_doc", lambda: doc)
    body = client.get("/screener", params={"sort": "rank"}).json()
    assert [r["instrument"]["symbol"] for r in body["rows"]] == ["ب", "الف"]
    top = body["rows"][0]
    assert top["verdict"] == "candidate" and top["code"] == "candidate" and top["rank"] == 1
    assert top["volume_ratio_30"] == pytest.approx(3.0)
    assert top["per_capita_buy"] == pytest.approx(8e8) and top["per_capita_sell"] == pytest.approx(
        5e7
    )
    assert top["power"] == pytest.approx(16.0) and top["net_real_value"] == pytest.approx(7e9)
    assert body["rows"][1]["verdict"] == "hold" and body["rows"][1]["code"] == "with_market"
    assert body["verdict_counts"] == {"candidate": 1, "hold": 1}
    only = client.get("/screener", params={"verdict": "hold"}).json()
    assert [r["instrument"]["symbol"] for r in only["rows"]] == ["الف"]
    assert only["verdict_counts"] == {"candidate": 1, "hold": 1}  # counts ignore the filter
    by_power = client.get("/screener", params={"sort": "power"}).json()
    assert by_power["rows"][0]["instrument"]["symbol"] == "ب"
    assert body["flow_date"] == DAY.isoformat() and body["ranking_date"] == DAY.isoformat()


def test_instrument_detail_lists_shareholders_largest_first(
    client: TestClient, session: Session
) -> None:
    a = _priced(session)
    for key, name, pct in ((1, "کوچک", 1.5), (2, "بزرگ", 40.2)):
        session.add(
            Shareholder(instrument_id=a.id, holder_key=key, name=name, shares=1000 * key,
                        percent=pct, change_amount=0,
                        fetched_at=dt.datetime(2025, 3, 6, 8, 0, tzinfo=dt.UTC))
        )  # fmt: skip
    session.flush()
    d = client.get(f"/instruments/{a.id}").json()
    assert [h["name"] for h in d["shareholders"]] == ["بزرگ", "کوچک"]
    assert d["shareholders_at"] == "2025-03-06"


def test_instrument_news_matches_the_symbol_as_a_whole_word(
    client: TestClient, session: Session
) -> None:
    from tmon.storage.models import NewsRaw

    a = _inst(session, "IRO1FOLD0001", "فولاد")
    now = dt.datetime.now(dt.UTC)
    rows = [
        ("فولاد رکورد فروش ماهانه را شکست", now - dt.timedelta(days=1)),
        ("صنایع فولادی در صف خرید", now - dt.timedelta(days=1)),  # another word that contains it
        ("سود فولاد در سال گذشته", now - dt.timedelta(days=90)),  # too old
        ("فولاد رکورد فروش ماهانه را شکست", now - dt.timedelta(days=2)),  # the same headline again
    ]
    for i, (title, at) in enumerate(rows):
        session.add(
            NewsRaw(
                source="tejarat",
                url=f"https://example.com/{i}",
                title=title,
                title_norm=title,
                published_at=at,
            )
        )
    session.flush()
    news = client.get(f"/instruments/{a.id}").json()["news"]
    assert [n["title"] for n in news] == ["فولاد رکورد فروش ماهانه را شکست"]
