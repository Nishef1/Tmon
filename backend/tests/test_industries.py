"""Industry candles (consensus of the member symbols), the market index page and their endpoints."""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterator

import polars as pl
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from tmon.api.industry_series import (
    Composite,
    composites,
    horizon_return,
    member_moves,
    spark,
    trend_table,
)
from tmon.api.main import create_app
from tmon.api.routers import industries as ind
from tmon.core.db import get_session
from tmon.core.engine_config import get_engine_config
from tmon.storage.models import (
    ClientTypeDaily,
    Instrument,
    MarketIndexDaily,
    PriceDaily,
    SectorName,
)

DAY = dt.date(2026, 11, 18)
N = 70


def _adj(rows: list[tuple[int, dt.date, float, float, float, float, float]]) -> pl.DataFrame:
    return pl.DataFrame(
        rows,
        schema={
            "instrument_id": pl.Int64,
            "date": pl.Date,
            "adj_open": pl.Float64,
            "adj_high": pl.Float64,
            "adj_low": pl.Float64,
            "adj_close": pl.Float64,
            "value": pl.Float64,
        },
        orient="row",
    )


def _two_symbols() -> tuple[pl.DataFrame, dict[int, str]]:
    """A (value 1) goes 100 -> 110 and B (value 9) goes 100 -> 90 on the second day."""
    d1, d2 = dt.date(2026, 1, 1), dt.date(2026, 1, 2)
    rows = [
        (1, d1, 100, 100, 100, 100, 1.0),
        (1, d2, 100, 112, 99, 110, 1.0),
        (2, d1, 100, 100, 100, 100, 9.0),
        (2, d2, 100, 101, 88, 90, 9.0),
    ]
    return _adj(rows), {1: "27", 2: "27"}


def test_equal_weight_candle_is_the_plain_average_of_the_members() -> None:
    adj, sector = _two_symbols()
    c = composites(member_moves(adj), sector, "equal")["27"]
    assert c.dates == [dt.date(2026, 1, 2)]
    assert c.close[0] == pytest.approx(100.0)  # (+10% and -10%) / 2
    assert c.open[0] == pytest.approx(100.0)
    assert c.high[0] == pytest.approx(100 * (1.12 + 1.01) / 2)
    assert c.low[0] == pytest.approx(100 * (0.99 + 0.88) / 2)
    assert (c.up[0], c.down[0], c.flat[0], c.members[0]) == (1, 1, 0, 2)


def test_value_weight_follows_the_money_of_the_day_before() -> None:
    adj, sector = _two_symbols()
    c = composites(member_moves(adj), sector, "value")["27"]
    assert c.close[0] == pytest.approx(100 * (1.1 * 1 + 0.9 * 9) / 10)


def test_candle_never_excludes_its_own_open_or_close() -> None:
    adj, sector = _two_symbols()
    for w in ("equal", "value"):
        c = composites(member_moves(adj), sector, w)["27"]
        assert c.low[0] <= min(c.open[0], c.close[0])
        assert c.high[0] >= max(c.open[0], c.close[0])


def test_a_stale_reference_price_is_dropped_not_averaged_in() -> None:
    d1, d2 = dt.date(2026, 1, 1), dt.date(2026, 1, 2)
    adj = _adj(
        [
            (1, d1, 100, 100, 100, 100, 1.0),
            (1, d2, 100, 100, 100, 100, 1.0),
            (2, d1, 100, 100, 100, 100, 1.0),
            (2, d2, 300, 300, 300, 300, 1.0),  # +200% in a day: a missed adjustment
        ]
    )
    c = composites(member_moves(adj), {1: "27", 2: "27"}, "equal")["27"]
    assert c.close[0] == pytest.approx(100.0)
    assert c.members[0] == 1


def test_level_compounds_across_days() -> None:
    days = [dt.date(2026, 1, 1) + dt.timedelta(days=i) for i in range(3)]
    rows = [(1, d, p, p, p, p, 1.0) for d, p in zip(days, (100, 110, 121), strict=True)]
    c = composites(member_moves(_adj(rows)), {1: "27"}, "equal")["27"]
    assert c.close == pytest.approx([110.0, 121.0])


def test_horizon_return_needs_a_base_within_ten_days() -> None:
    c = Composite(
        dates=[dt.date(2026, 1, 1), dt.date(2026, 1, 31)], close=[100.0, 150.0], open=[], high=[]
    )
    assert horizon_return(c, dt.date(2026, 1, 31), 30) == pytest.approx(0.5)
    assert horizon_return(c, dt.date(2026, 1, 31), 7) is None  # nearest base is 20 days earlier
    assert horizon_return(c, dt.date(2026, 2, 2), 30) is None  # not traded on that day


def test_spark_is_rebased_to_one_hundred() -> None:
    c = Composite(close=[50.0, 60.0, 75.0])
    assert spark(c) == [100.0, 120.0, 150.0]
    assert spark(Composite()) == []


def test_trend_flags_need_their_full_window() -> None:
    d0 = dt.date(2026, 1, 1)
    rows = [(1, d0 + dt.timedelta(days=i), 10, 10, 10, 10 + i, 1.0) for i in range(30)]
    rows += [(2, d0 + dt.timedelta(days=i), 10, 10, 10, 10, 1.0) for i in range(5, 30)]
    last = d0 + dt.timedelta(days=29)
    t = trend_table(_adj(rows), last)
    assert t[1].above_sma20 is True and t[1].above_sma50 is None
    assert t[1].from_year_high == pytest.approx(0.0)
    assert t[2].above_sma20 is False  # flat: not above its own average
    assert len(t[1].spark) == 30
    assert trend_table(_adj(rows), last + dt.timedelta(days=1)) == {}


@pytest.fixture
def client(session: Session, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setattr(ind, "_ranking_doc", lambda: None)
    monkeypatch.setattr(ind, "_turning_doc", lambda: None)
    app = create_app()
    app.dependency_overrides[get_session] = lambda: session
    with TestClient(app) as c:
        yield c


def _market(session: Session) -> None:
    session.add_all([SectorName(code="27", name="فلزات"), SectorName(code="44", name="شیمیایی")])
    sectors = {1: "27", 2: "27", 3: "44"}
    for i, sec in sectors.items():
        session.add(
            Instrument(
                id=i, ins_code=f"c{i}", symbol_fa=f"س{i}", name_fa=f"نام {i}",
                instrument_type="stock", sector_code=sec,
            )
        )  # fmt: skip
    session.add(Instrument(id=9, ins_code="f9", symbol_fa="صندوق", instrument_type="etf_equity"))
    for i in (1, 2, 3, 9):
        price = 100.0
        for k in range(N):
            d = DAY - dt.timedelta(days=N - 1 - k)
            move = {1: 1.01, 2: 0.995, 3: 1.0, 9: 1.2}[i]
            prev, price = price, price * move
            session.add(
                PriceDaily(
                    instrument_id=i, date=d, open=prev, high=price * 1.01, low=prev * 0.99,
                    last=price, close=price, prev_close=prev, volume=1000, value=1e9 * i,
                    trades=10, market_halt=False,
                )
            )  # fmt: skip
    for i in (1, 2):
        session.add(
            ClientTypeDaily(
                instrument_id=i, date=DAY, buy_count_i=1, sell_count_i=1, buy_count_n=1,
                sell_count_n=1, buy_volume_i=1, sell_volume_i=1, buy_volume_n=1, sell_volume_n=1,
                buy_value_i=3e9 * i, sell_value_i=1e9, buy_value_n=1e9, sell_value_n=3e9 * i,
            )
        )  # fmt: skip
    code = get_engine_config().benchmarks.indices["equal_weight"]
    for k in range(N):
        d = DAY - dt.timedelta(days=N - 1 - k)
        session.add(
            MarketIndexDaily(index_code=code, date=d, close=1000 + k, high=1001 + k, low=999 + k)
        )
    session.commit()


def test_overview_has_a_card_per_industry_with_its_stocks_only(
    client: TestClient, session: Session
) -> None:
    _market(session)
    j = client.get("/industries/overview").json()
    assert j["available"] and j["as_of"] == str(DAY)
    cards = {c["code"]: c for c in j["industries"]}
    assert set(cards) == {"27", "44"}  # the fund is in no industry
    m = cards["27"]
    assert m["name"] == "فلزات" and m["n"] == 2 and m["n_traded"] == 2
    assert m["day"] == pytest.approx((1.01 + 0.995) / 2 - 1, abs=1e-4)
    assert m["value"] == pytest.approx(3e9)
    assert m["value_share"] == pytest.approx(3 / 6)
    assert m["net_real_flow"] == pytest.approx((3e9 - 1e9) + (6e9 - 1e9))
    assert m["up"] == 1 and m["down"] == 1
    assert len(m["spark"]) == 60
    values = [c["value"] for c in j["industries"]]
    assert values == sorted(values, reverse=True)  # biggest value first; a tie keeps no order
    assert cards["44"]["day"] == pytest.approx(0.0, abs=1e-4)


def test_detail_gives_consensus_candles_and_a_row_per_symbol(
    client: TestClient, session: Session
) -> None:
    _market(session)
    j = client.get("/industries/27/detail?days=60").json()
    assert j["name"] == "فلزات" and j["n_members"] == 2 and j["n_traded"] == 2
    assert len(j["candles"]) == 60 and len(j["candles_value"]) == 60
    last = j["candles"][-1]
    assert last["low"] <= min(last["open"], last["close"])
    assert last["high"] >= max(last["open"], last["close"])
    assert j["breadth"]["up"] == 1 and j["breadth"]["down"] == 1
    assert j["breadth"]["above_sma20"] == 1
    assert [r["label"] for r in j["returns"]] == ["هفته", "ماه", "سه ماه", "سال"]
    assert j["returns"][0]["vs_market"] is not None
    assert j["returns"][3]["value"] is None  # only 70 days of history
    rows = {m["symbol"]: m for m in j["members"]}
    assert set(rows) == {"س1", "س2"}
    assert rows["س1"]["day"] == pytest.approx(0.01, abs=1e-4)
    assert rows["س2"]["contrib"] == pytest.approx((0.995 - 1) / 2, abs=1e-4)
    assert rows["س1"]["contrib"] + rows["س2"]["contrib"] == pytest.approx(j["day"], abs=1e-4)
    assert rows["س1"]["net_real_flow"] == pytest.approx(2e9)
    assert rows["س1"]["verdict"] != "buy"  # no ranking loaded: never invents advice
    assert j["flow"][-1]["net_real"] == pytest.approx(j["net_real_flow"])
    assert j["value_share"] == pytest.approx(0.5)


@pytest.mark.parametrize("code", ["99", "abc", "27x"])
def test_unknown_industry_is_a_404(client: TestClient, session: Session, code: str) -> None:
    _market(session)
    assert client.get(f"/industries/{code}/detail").status_code == 404


def test_empty_database_says_unavailable(client: TestClient) -> None:
    assert client.get("/industries/overview").json()["available"] is False
    assert client.get("/market/index").json()["available"] is False
    assert client.get("/industries/27/detail").status_code == 404


def test_market_index_candles_clamp_the_open_into_the_day(
    client: TestClient, session: Session
) -> None:
    _market(session)
    j = client.get("/market/index?days=60").json()
    assert j["available"]
    s = {x["key"]: x for x in j["series"]}["equal_weight"]
    assert s["date"] == str(DAY) and len(s["candles"]) == 60
    assert s["close"] == pytest.approx(1000 + N - 1)
    assert s["change"] == pytest.approx((1000 + N - 1) / (1000 + N - 2) - 1)
    assert s["position"] == pytest.approx(0.5)
    for c in s["candles"]:
        assert c["low"] <= c["open"] <= c["high"]
    assert s["returns"][0]["label"] == "هفته" and s["returns"][3]["value"] is None
    assert j["days"] and j["days"][-1]["date"] == str(DAY)
    assert j["days"][-1]["up"] == 1 and j["days"][-1]["down"] == 1
