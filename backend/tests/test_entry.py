"""Entry review and guard: what a purchase at the open cost, and when not to buy."""

from __future__ import annotations

from tmon.portfolio.entry import bucket_for, guard, review_entry
from tmon.portfolio.liveprice import Bar

# Opened 2.9% above yesterday, closed (volume-weighted) above yesterday, last trade below the buy.
BAR = Bar(
    day=None,
    first=19_450,
    high=19_500,
    low=18_900,
    last=18_950,
    close=19_100,
    yesterday=18_900,
    limit_up=19_740,
    limit_down=18_600,
)


def test_review_flags_chasing_the_gap_and_a_green_candle_loss() -> None:
    r = review_entry(19_450, BAR, edge=0.03, cost=0.0175)
    keys = {f["key"] for f in r["flags"]}
    assert {"gap_chase", "top_of_range", "green_but_loss"} <= keys
    assert r["pnl_last"] < 0
    assert r["grade"] == "poor"


def test_review_of_a_fair_entry_is_clean() -> None:
    bar = Bar(None, 18_900, 19_000, 18_800, 18_950, 18_960, 18_900)
    r = review_entry(18_850, bar, edge=0.03, cost=0.0175)
    assert r["flags"] == []
    assert r["grade"] == "good"


def test_guard_blocks_a_price_that_ate_the_edge() -> None:
    high = Bar(None, 19_450, 19_500, 18_900, 19_450, 19_400, 18_900, 19_740, 18_600)
    g = guard(high, edge=0.03, cost=0.0175, fade=None)
    assert g["state"] in {"wait", "avoid"}
    assert g["max_price"] is not None and g["max_price"] < 19_450


def test_guard_allows_a_small_gap() -> None:
    bar = Bar(None, 18_950, 19_000, 18_850, 18_940, 18_940, 18_900)
    g = guard(bar, edge=0.03, cost=0.0175, fade=None)
    assert g["state"] == "ok"


def test_guard_without_edge_never_blocks_on_edge_alone() -> None:
    bar = Bar(None, 18_950, 19_000, 18_850, 18_940, 18_940, 18_900)
    assert guard(bar, edge=None, cost=0.0175, fade=None)["state"] == "ok"


def test_bucket_for_picks_the_matching_gap_row() -> None:
    table = {"rows": [{"low": 0.015, "high": 0.025, "label": "x", "n": 100}]}
    assert bucket_for(table, 0.02) is not None
    assert bucket_for(table, 0.04) is None
    assert bucket_for(None, 0.02) is None


def _history(session) -> None:  # type: ignore[no-untyped-def]
    """120 days x 40 symbols where a day that opens above yesterday fades by half of the gap."""
    import datetime as dt

    import numpy as np

    from tmon.storage.models import Instrument, PriceDaily

    rng = np.random.default_rng(3)
    at = dt.datetime(2026, 1, 1, tzinfo=dt.UTC)
    d0 = dt.date(2026, 1, 1)
    for n in range(40):
        ins = Instrument(ins_code=str(n + 1), symbol_fa=f"س{n}")
        session.add(ins)
        session.flush()
        ref = 1000.0
        for k in range(120):
            gap = float(np.clip(rng.normal(0.004, 0.012), -0.04, 0.04))
            o = ref * (1 + gap)
            last = o * (1 - 0.5 * gap + float(rng.normal(0, 0.004)))
            hi, lo = max(o, last) * 1.003, min(o, last) * 0.997
            session.add(
                PriceDaily(
                    instrument_id=ins.id,
                    date=d0 + dt.timedelta(days=k),
                    open=o,
                    high=hi,
                    low=lo,
                    last=last,
                    close=last,
                    prev_close=ref,
                    volume=1e6,
                    value=last * 1e6,
                    fetched_at=at,
                )
            )
            ref = last
    session.flush()


def test_fade_table_and_fit_find_the_planted_gap_fade(session) -> None:  # type: ignore[no-untyped-def]
    from tmon.portfolio import entry

    _history(session)
    table = entry.fade_table(session)
    assert table is not None and table["rows"]
    top = [r for r in table["rows"] if r["low"] >= 0.015]
    assert top and all(r["open_to_last"] < 0 for r in top)
    model = entry.fit_open_model(session)
    assert model is not None
    gap = next(f for f in model["features"] if f["key"] == "gap")
    assert gap["beta"] < 0 and gap["weight"] < 0
    # a wide gap is predicted to drift down against the day's average, a small one is not
    assert (entry.drift_from_model(model, {"gap": 0.03}) or 0) < (
        entry.drift_from_model(model, {"gap": -0.01}) or 0
    )


def test_panel_is_not_rebuilt_while_the_data_is_unchanged(session) -> None:  # type: ignore[no-untyped-def]
    from tmon.portfolio import entry

    _history(session)
    assert entry.panel(session) is entry.panel(session)


def test_lessons_name_the_pattern() -> None:
    rows = [
        review_entry(19_450, BAR, edge=0.03, cost=0.0175),
        review_entry(19_400, BAR, edge=0.03, cost=0.0175),
    ]
    from tmon.portfolio.entry import lessons

    text = " ".join(lessons(rows))
    assert "۱٫۵٪" in text and "کندل سبز" in text


def test_open_features_works_on_decimal_columns(session) -> None:  # type: ignore[no-untyped-def]
    """Postgres returns Decimal for price columns; the arithmetic must not mix it with floats."""
    import datetime as dt
    from decimal import Decimal

    from sqlalchemy import select

    from tmon.portfolio import entry
    from tmon.storage.models import PriceDaily

    _history(session)
    session.commit()
    session.expire_all()
    row = session.scalars(select(PriceDaily).order_by(PriceDaily.date.desc())).first()
    assert row is not None
    row.prev_close = Decimal(str(row.prev_close))
    bar = Bar(
        day=row.date + dt.timedelta(days=1),
        first=1010.0,
        high=1015.0,
        low=1000.0,
        last=1005.0,
        close=1005.0,
        yesterday=float(row.close),
    )
    x = entry.open_features(session, row.instrument_id, bar)
    assert x["gap"] is not None and x["ret_prev"] is not None and x["pos_prev"] is not None
    assert all(isinstance(v, float) for v in x.values() if v is not None)


def test_wide_static_band_is_not_a_daily_limit() -> None:
    from tmon.portfolio.liveprice import parse_info

    info = {"dEven": 20261116, "priceYesterday": 5170.0, "pDrCotVal": 5150.0}
    normal = parse_info(info, {"psGelStaMax": 5320.0, "psGelStaMin": 5020.0})
    assert normal.limit_up == 5320.0 and normal.limit_down == 5020.0
    wide = parse_info(info, {"psGelStaMax": 1_000_000.0, "psGelStaMin": 1.0})
    assert wide.limit_up is None and wide.limit_down is None


def test_live_marks_only_replace_an_older_stored_day(session, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """While the market is open the portfolio is priced at the exchange's last trade; once the
    stored day is today's, the stored row stands and the feed is ignored."""
    import datetime as dt

    from tmon.portfolio import advice, liveprice
    from tmon.storage.models import Instrument, PriceDaily

    ins = Instrument(ins_code="777", symbol_fa="تست")
    session.add(ins)
    session.flush()
    stored = dt.date(2026, 11, 14)
    session.add(
        PriceDaily(
            instrument_id=ins.id,
            date=stored,
            close=1000.0,
            last=990.0,
            prev_close=1000.0,
            volume=1e6,
            value=1e9,
            fetched_at=dt.datetime(2026, 11, 14, tzinfo=dt.UTC),
        )
    )
    session.flush()

    def feed(day: dt.date):  # type: ignore[no-untyped-def]
        return lambda code: Bar(day, 1010.0, 1030.0, 1005.0, 1020.0, 1015.0, 1000.0)

    monkeypatch.setattr(liveprice, "fetch", feed(dt.date(2026, 11, 16)))
    got = advice.last_prices(session, [ins.id], live=True)
    assert got[ins.id] == (1020.0, 1015.0, "2026-11-16")
    assert advice.last_prices(session, [ins.id])[ins.id][0] == 990.0  # not asked for live

    monkeypatch.setattr(liveprice, "fetch", feed(stored))
    assert advice.last_prices(session, [ins.id], live=True)[ins.id][0] == 990.0


def test_entry_plan_ladder_and_recommendation(session) -> None:  # type: ignore[no-untyped-def]
    from tmon.portfolio import entry
    from tmon.storage.models import Instrument

    _history(session)
    iid = session.query(Instrument).first().id
    bar = Bar(None, 1010.0, 1018.0, 1000.0, 1008.0, 1008.0, 1000.0, 1050.0, 950.0)
    plan = entry.entry_plan(
        session, iid, bar, edge=0.04, cost=0.0175, in_session=True, now_minutes=30, verdict="buy"
    )
    assert plan["available"] and plan["mode"] == "today"
    ladder = plan["ladder"]
    assert ladder, "some level must sit below the current price"
    prices = [s["price"] for s in ladder]
    probs = [s["day_fill_prob"] for s in ladder]
    assert prices == sorted(prices, reverse=True)  # deeper levels cost less
    assert probs == sorted(probs, reverse=True)  # and fill less often
    assert all(s["price"] < 1008.0 for s in ladder)
    assert all(abs(s["price"] % 10) < 1e-9 for s in ladder)
    best = plan["recommended"]
    assert best is not None and best["ev"] > 0 and best["price"] < 1008.0
    assert best["ev"] == max(s["ev"] for s in ladder)


def test_entry_plan_has_no_price_when_the_model_does_not_say_buy(session) -> None:  # type: ignore[no-untyped-def]
    from tmon.portfolio import entry
    from tmon.storage.models import Instrument

    _history(session)
    iid = session.query(Instrument).first().id
    bar = Bar(None, 1010.0, 1018.0, 1000.0, 1008.0, 1008.0, 1000.0)
    plan = entry.entry_plan(
        session, iid, bar, edge=0.04, cost=0.0175, in_session=True, verdict="hold"
    )
    assert plan["recommended"] is None and plan["ladder"]
    assert all(s["ev"] is None for s in plan["ladder"])


def test_entry_plan_for_tomorrow_uses_the_official_close(session) -> None:  # type: ignore[no-untyped-def]
    from tmon.portfolio import entry
    from tmon.storage.models import Instrument

    _history(session)
    iid = session.query(Instrument).first().id
    bar = Bar(None, 1010.0, 1018.0, 1000.0, 1008.0, 1006.0, 1000.0)
    plan = entry.entry_plan(
        session, iid, bar, edge=0.04, cost=0.0175, in_session=False, verdict="buy"
    )
    assert plan["mode"] == "next" and plan["reference"] == 1006.0
    assert all(s["touched_today"] is False for s in plan["ladder"])


def test_exit_plan_ladder_is_above_the_price_and_picks_the_best_gain(session) -> None:  # type: ignore[no-untyped-def]
    from tmon.portfolio import entry
    from tmon.storage.models import Instrument

    _history(session)
    iid = session.query(Instrument).first().id
    bar = Bar(None, 1010.0, 1018.0, 1000.0, 1008.0, 1008.0, 1000.0, 1050.0, 950.0)
    plan = entry.exit_plan(session, iid, bar, in_session=True, now_minutes=30, verdict="sell")
    assert plan["available"] and plan["mode"] == "today"
    ladder = plan["ladder"]
    assert ladder, "some level must sit above the current price"
    assert all(s["price"] > 1008.0 for s in ladder)
    assert all(abs(s["price"] % 10) < 1e-9 for s in ladder)
    prices = [s["price"] for s in ladder]
    probs = [s["day_fill_prob"] for s in ladder]
    assert prices == sorted(prices)  # higher levels fill less often
    assert probs == sorted(probs, reverse=True)
    best = plan["recommended"]
    if best is not None:
        assert best["gain_vs_now"] == max(s["gain_vs_now"] for s in ladder) > 0
        assert "حدی فروش" in plan["headline"]
    else:
        assert "همین حالا" in plan["headline"]
    assert any("کارمزد" in n for n in plan["notes"])


def test_exit_plan_never_proposes_a_price_above_the_daily_limit(session) -> None:  # type: ignore[no-untyped-def]
    from tmon.portfolio import entry
    from tmon.storage.models import Instrument

    _history(session)
    iid = session.query(Instrument).first().id
    bar = Bar(None, 1010.0, 1018.0, 1000.0, 1008.0, 1008.0, 1000.0, 1030.0, 970.0)
    plan = entry.exit_plan(session, iid, bar, in_session=True, verdict="hold")
    assert all(s["price"] <= 1030.0 for s in plan["ladder"])


def test_exit_plan_without_history_says_so(session) -> None:  # type: ignore[no-untyped-def]
    from tmon.portfolio import entry

    bar = Bar(None, 1010.0, 1018.0, 1000.0, 1008.0, 1008.0, 1000.0)
    plan = entry.exit_plan(session, 1, bar, in_session=True)
    assert plan == {"available": False, "message": "تاریخچهٔ کافی برای برنامهٔ خروج نیست."}


def test_entry_endpoint_carries_the_exit_ladder_and_the_time_of_day(session) -> None:  # type: ignore[no-untyped-def]
    from fastapi.testclient import TestClient

    from tmon.api.main import create_app
    from tmon.core.db import get_session
    from tmon.portfolio import timing
    from tmon.storage.models import Instrument

    timing._memo.clear()
    _history(session)
    iid = session.query(Instrument).first().id
    app = create_app()
    app.dependency_overrides[get_session] = lambda: session
    with TestClient(app) as c:
        r = c.get(f"/instruments/{iid}/entry")
    assert r.status_code == 200
    body = r.json()
    assert body["available"] and body["exit_plan"]["available"]
    assert body["exit_plan"]["now"] > 0 and "ladder" in body["exit_plan"]
    # no 15-minute history stored: the answer says so instead of inventing an hour
    assert body["timing"]["available"] is False and body["timing"]["message"]
