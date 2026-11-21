import datetime as dt

from tmon.portfolio.position import STOP_STUDY_FA, position_plan

TODAY = dt.date(2026, 11, 21)


def plan(**kw):  # type: ignore[no-untyped-def]
    base = {
        "avg_price": 17_400.0,
        "shares": 1000.0,
        "price": 16_490.0,
        "sell_rate": 0.01,
        "stop_price": None,
        "default_stop_pct": 10.0,
        "bought_on": dt.date(2026, 11, 16),
        "today": TODAY,
        "buyer_code": "wait",
    }
    base.update(kw)
    return position_plan(**base)


def test_numbers_are_the_owners_money() -> None:
    p = plan()
    assert p is not None
    assert abs(p["breakeven"] - 17_400 / 0.99) < 1e-6
    assert abs(p["net_if_sold"] - (16_490 * 0.99 - 17_400) * 1000) < 1e-6
    assert p["stop"] == 17_400 * 0.9
    assert p["stop_source"] == "default"
    assert p["days_held"] == 5
    assert p["to_stop_pct"] < 0
    assert "زیان" in p["lines"][0]
    assert STOP_STUDY_FA in p["lines"]
    assert "«صبر»" in p["lines"][-1]


def test_own_stop_reached() -> None:
    p = plan(stop_price=16_500.0)
    assert p is not None
    assert p["stop_source"] == "user"
    assert "رسیده است" in p["lines"][1]
    assert STOP_STUDY_FA not in p["lines"]


def test_no_price_no_card() -> None:
    assert plan(price=None) is None


def test_no_stop_and_no_verdict() -> None:
    p = plan(default_stop_pct=None, buyer_code=None)
    assert p is not None
    assert p["stop"] is None
    assert len(p["lines"]) == 1
