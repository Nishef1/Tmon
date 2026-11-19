"""Derived columns: the pure helpers, the statement ratios, the table on a small synthetic market and
the endpoints that serve it."""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterator

import numpy as np
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from tmon.api.main import create_app
from tmon.api.routers import industries as ind
from tmon.core.db import get_session
from tmon.core.engine_config import get_engine_config
from tmon.features import columns as cols
from tmon.features import fundamentals as fnd
from tmon.storage.models import (
    ClientTypeDaily,
    FinancialStatement,
    Instrument,
    MacroSeries,
    MarketIndexDaily,
    OrderBookDaily,
    PriceDaily,
    SectorName,
    Shareholder,
)

DAY = dt.date(2026, 11, 18)
N = 260


# ------------------------------------------------------------------ pure helpers


def test_catalog_keys_are_unique_and_every_group_is_named() -> None:
    keys = [c.key for c in cols.CATALOG]
    assert len(keys) == len(set(keys))
    assert {c.group for c in cols.CATALOG} <= set(cols.GROUPS)


def test_rsi_of_a_pure_rise_is_100_and_needs_fifteen_closes() -> None:
    up = np.arange(1.0, 40.0)
    assert cols.rsi(up) == 100.0
    assert cols.rsi(up[:14]) is None


def test_macd_histogram_is_positive_in_an_accelerating_rise() -> None:
    x = np.cumsum(np.linspace(0.1, 3.0, 80)) + 100
    h = cols.macd_hist(x)
    assert h is not None and h > 0
    assert cols.macd_hist(x[:20]) is None


def test_swing_levels_pick_the_nearest_confirmed_extremes() -> None:
    low = np.array([10, 9, 8, 7, 8, 9, 10, 11, 12, 11, 10, 9.5, 10, 11, 12], float)
    high = low + 1
    sup, res = cols.swing_levels(high, low, close=10.2, k=2)
    assert sup == 9.5  # the higher of the two confirmed lows (7 and 9.5) under the close
    assert res == 13  # the high at index 8
    assert cols.swing_levels(high[:3], low[:3], 10.0) == (None, None)


def test_candle_patterns() -> None:
    o, h = np.array([100.0, 98.0]), np.array([101.0, 105.0])
    lo, c = np.array([97.0, 97.0]), np.array([98.0, 104.0])
    assert cols.candle_pattern(o, h, lo, c) == "بلعیدن صعودی"
    doji = cols.candle_pattern(
        np.array([100.0]), np.array([105.0]), np.array([95.0]), np.array([100.2])
    )
    assert doji == "دوجی"
    hammer = cols.candle_pattern(
        np.array([100.0]), np.array([100.5]), np.array([94.0]), np.array([100.3])
    )
    assert hammer == "چکش"
    flat = cols.candle_pattern(
        np.array([100.0]), np.array([100.0]), np.array([100.0]), np.array([100.0])
    )
    assert flat is None  # a bar locked at one price says nothing


def test_medians_skip_missing_and_text() -> None:
    rows: list[cols.Row] = [{"a": 1.0}, {"a": 3.0}, {"a": None}, {"a": "x"}, {}]
    assert cols.medians(rows, ["a", "b"]) == {"a": 2.0, "b": None}


# ------------------------------------------------------------------ statement ratios


def _stmt(
    months: int,
    fy_end: dt.date,
    income: list[list[object]],
    balance: list[list[object]] | None = None,
    published: dt.datetime | None = None,
    kind: str = "separate",
) -> fnd.Stmt:
    return fnd.Stmt(
        published or dt.datetime(2026, 5, 1, tzinfo=dt.UTC),
        kind,
        fy_end
        if months == 12
        else fy_end.replace(year=fy_end.year - 1) + dt.timedelta(days=30 * months),
        fy_end,
        months,
        fnd._table(balance or []),
        fnd._table(income),
    )


FY = dt.date(2026, 3, 20)
BAL = [
    ["جمع دارایی ها", 1000.0, 900.0],
    ["جمع بدهی ها", 400.0, 380.0],
    ["جمع حقوق مالکانه", 600.0, 520.0],
    ["جمع دارایی های جاری", 500.0, 450.0],
    ["جمع بدهی های جاری", 250.0, 240.0],
    ["تسهیلات مالی", 60.0, 50.0],
]


def test_full_year_ratios() -> None:
    s = _stmt(
        12,
        FY,
        [
            ["درآمدهای عملیاتی", 1200.0, 1000.0],
            ["سود(زیان) ناخالص", 360.0, 300.0],
            ["سود(زیان) عملیاتی", 240.0, 200.0],
            ["سود(زیان) خالص", 180.0, 150.0],
        ],
        BAL,
    )
    r = fnd.ratios([s], mcap=1.8e9)  # 1800 million rial
    assert r["rev_yoy"] == pytest.approx(0.2)
    assert r["net_yoy"] == pytest.approx(0.2)
    assert r["gross_margin"] == pytest.approx(0.3)
    assert r["net_margin"] == pytest.approx(0.15)
    assert r["roe"] == pytest.approx(180 / 600)
    assert r["roa"] == pytest.approx(0.18)
    assert r["debt_to_assets"] == pytest.approx(0.4)
    assert r["current_ratio"] == pytest.approx(2.0)
    assert r["pe_ttm"] == pytest.approx(10.0)
    assert r["ps_ttm"] == pytest.approx(1.5)
    assert r["pb"] == pytest.approx(3.0)
    assert r["fund_score"] == 100.0


def test_trailing_twelve_months_from_a_partial_year_and_quarter_growth() -> None:
    prev = dt.date(2025, 3, 20)
    year = _stmt(12, prev, [["درآمدهای عملیاتی", 800.0], ["سود(زیان) خالص", 80.0]], BAL)
    q1 = _stmt(3, FY, [["درآمدهای عملیاتی", 300.0, 150.0], ["سود(زیان) خالص", 60.0, 20.0]], BAL)
    q2 = _stmt(6, FY, [["درآمدهای عملیاتی", 500.0, 350.0], ["سود(زیان) خالص", 90.0, 50.0]], BAL)
    r = fnd.ratios([year, q1, q2], mcap=None)
    # TTM = 6m this year + last full year - the same 6m a year earlier
    assert r["roe"] == pytest.approx((90 + 80 - 50) / 600)
    # the second quarter (200 on revenue) against the first (300)
    assert r["rev_qoq"] == pytest.approx(200 / 300 - 1)
    assert r["pe_ttm"] is None  # no market cap given


def test_a_loss_has_no_growth_and_no_pe() -> None:
    s = _stmt(12, FY, [["درآمدهای عملیاتی", 100.0, 100.0], ["سود(زیان) خالص", -20.0, -10.0]], BAL)
    r = fnd.ratios([s], mcap=1e9)
    assert r["net_yoy"] is None  # a loss base has no growth
    assert r["pe_ttm"] is None  # a loss has no P/E
    assert r["net_margin"] == pytest.approx(-0.2)  # a loss margin is a real number
    assert r["roe"] is not None and r["roe"] < 0


def test_a_symbol_without_statements_gets_nothing() -> None:
    assert fnd.ratios([], mcap=1e9) == {}


def test_consolidated_statements_win_over_separate() -> None:
    sep = _stmt(12, FY, [["درآمدهای عملیاتی", 100.0, 100.0]], BAL, kind="separate")
    con = _stmt(12, FY, [["درآمدهای عملیاتی", 300.0, 200.0]], BAL, kind="consolidated")
    assert fnd.ratios([sep, con], None)["statement_kind"] == "consolidated"
    assert fnd.ratios([sep, con], None)["rev_yoy"] == pytest.approx(0.5)


def test_labels_match_across_spaces_and_brackets() -> None:
    assert fnd.key("سود (زیان) خالص") == fnd.key("سود(زیان)خالص")


# ------------------------------------------------------------------ the table on a small market


def _market(session: Session) -> None:
    tedpix = get_engine_config().benchmarks.indices["tedpix"]
    session.add_all([SectorName(code="27", name="فلزات"), SectorName(code="44", name="شیمیایی")])
    spec = {1: ("27", 1.002), 2: ("27", 0.999), 3: ("44", 1.0005)}
    for i, (sec, _) in spec.items():
        session.add(
            Instrument(
                id=i, ins_code=f"c{i}", symbol_fa=f"س{i}", name_fa=f"نام {i}",
                instrument_type="stock", sector_code=sec, tags={"shares": 1e9 * i},
            )
        )  # fmt: skip
    session.add(Instrument(id=9, ins_code="f9", symbol_fa="صندوق", instrument_type="etf_equity"))
    rng = np.random.default_rng(7)
    ix = 1000.0
    days = [DAY - dt.timedelta(days=N - 1 - k) for k in range(N)]
    for d in days:
        step = float(rng.normal(0, 0.01))
        ix *= 1 + step
        session.add(MarketIndexDaily(index_code=tedpix, date=d, close=ix))
    for i, (_, drift) in spec.items():
        price = 1000.0 * i
        rng2 = np.random.default_rng(i)
        for k, d in enumerate(days):
            move = drift + 0.005 * float(rng2.normal())
            prev, price = price, price * move
            session.add(
                PriceDaily(
                    instrument_id=i, date=d, open=prev, high=max(prev, price) * 1.005,
                    low=min(prev, price) * 0.995, last=price, close=price, prev_close=prev,
                    volume=1000 + k, value=price * (1000 + k), trades=10, market_halt=False,
                )
            )  # fmt: skip
    session.add(MacroSeries(series="usd_free", source="t", ref_period=DAY, value=1e6))
    for i in (1, 2):
        session.add(
            ClientTypeDaily(
                instrument_id=i, date=DAY, buy_count_i=10, sell_count_i=20, buy_count_n=1,
                sell_count_n=1, buy_volume_i=1, sell_volume_i=1, buy_volume_n=1, sell_volume_n=1,
                buy_value_i=4e9, sell_value_i=2e9, buy_value_n=1e9, sell_value_n=3e9,
            )
        )  # fmt: skip
    session.add(Shareholder(instrument_id=1, holder_key=1, name="الف", shares=1, percent=40.0))
    session.add(Shareholder(instrument_id=1, holder_key=2, name="ب", shares=1, percent=10.0))
    session.add(
        OrderBookDaily(
            instrument_id=1, date=DAY, n_events=5, close_bid_price=1000.0, close_bid_volume=500.0,
            close_ask_price=1010.0, close_ask_volume=100.0, close_imbalance=0.6,
            peak_queue_volume=300.0,
        )
    )  # fmt: skip
    session.add(
        FinancialStatement(
            instrument_id=1, published_at=dt.datetime(2026, 5, 1, tzinfo=dt.UTC), kind="separate",
            title="t", period_end=FY, fiscal_year_end=FY, period_months=12,
            balance=BAL, income=[["درآمدهای عملیاتی", 1200.0, 1000.0], ["سود(زیان) خالص", 180.0, 150.0]],
        )
    )  # fmt: skip
    session.commit()


@pytest.fixture
def market(session: Session) -> cols.Table:
    _market(session)
    return cols.compute(session, DAY, DAY)


def test_every_stock_that_traded_has_a_row_and_the_fund_has_none(market: cols.Table) -> None:
    assert set(market.rows) == {1, 2, 3}


def test_period_returns_use_the_adjusted_close_and_need_their_history(market: cols.Table) -> None:
    r = market.rows[1]
    assert isinstance(r["ret_1w"], float)
    assert "ret_1y" not in r  # the first bar is 259 days back, so a year has no base
    assert r.get("ret_5y") is None  # only 260 days of bars exist


def test_distance_from_limits_uses_the_band_when_the_bar_stores_none(market: cols.Table) -> None:
    r = market.rows[1]
    assert r["dist_ceiling"] is not None and float(r["dist_ceiling"]) <= 0.0 + 1e-9
    assert r["dist_floor"] is not None and float(r["dist_floor"]) >= 0.0 - 1e-9


def test_volume_ratio_compares_with_the_days_before(market: cols.Table) -> None:
    r = market.rows[1]
    expected = (1000 + N - 1) / np.mean([1000 + k for k in range(N - 31, N - 1)])
    assert r["vol_vs_30"] == pytest.approx(expected)


def test_betas_exist_for_the_three_window_shapes(market: cols.Table) -> None:
    r = market.rows[1]
    assert isinstance(r["beta_90d"], float)
    # 37 weekly and 8 monthly returns are below the 40 and 24 these windows need
    assert "beta_60w" not in r and "beta_36m" not in r


def test_flow_columns(market: cols.Table) -> None:
    r = market.rows[1]
    assert r["real_net_pct"] == pytest.approx((4e9 - 2e9) / 5e9)
    assert r["legal_net_pct"] == pytest.approx((1e9 - 3e9) / 5e9)
    assert r["real_buy_power"] == pytest.approx((4e9 / 10) / (2e9 / 20))
    assert 3 not in {i for i, x in market.rows.items() if x.get("real_net_pct") is not None}


def test_order_book_columns_only_where_a_book_is_stored(market: cols.Table) -> None:
    r = market.rows[1]
    assert r["buy_order_value"] == pytest.approx(500_000.0)
    assert r["sell_order_value"] == pytest.approx(101_000.0)
    assert r["net_order_value"] == pytest.approx(399_000.0)
    assert r["demand_pressure"] == 0.6
    assert "buy_order_value" not in market.rows[2]


def test_float_and_index_weight(market: cols.Table) -> None:
    r = market.rows[1]
    assert r["float_pct"] == pytest.approx(0.5)  # 100% minus the 50% held by listed holders
    assert "float_pct" not in market.rows[2]  # no holder list, no estimate
    total = sum(float(x["index_weight"]) for x in market.rows.values())  # type: ignore[arg-type]
    assert total == pytest.approx(1.0)
    assert r["industry_value_share"] is not None


def test_dollar_values_use_the_free_rate(market: cols.Table) -> None:
    r = market.rows[1]
    assert r["price_usd"] == pytest.approx(float(r["mcap"]) / 1e9 / 1e6 * 1e9 / float(r["shares"]))  # type: ignore[arg-type]
    assert r["mcap_usd"] == pytest.approx(float(r["mcap"]) / 1e6)  # type: ignore[arg-type]


def test_statement_columns_only_for_symbols_that_filed(market: cols.Table) -> None:
    assert market.rows[1]["rev_yoy"] == pytest.approx(0.2)
    assert market.rows[1]["fund_score"] is not None
    assert "rev_yoy" not in market.rows[2]
    assert "pe_ttm" not in market.rows[3]


def test_tech_score_is_a_share_between_zero_and_a_hundred(market: cols.Table) -> None:
    for r in market.rows.values():
        v = r["tech_score"]
        assert v is None or 0.0 <= float(v) <= 100.0  # type: ignore[arg-type]


def test_market_summary_has_the_index_in_dollars(session: Session, market: cols.Table) -> None:
    m = cols.market_summary(session, market)
    assert m["usd"] == 1e6
    assert m["mcap_usd"] == pytest.approx(float(m["mcap"]) / 1e6)  # type: ignore[arg-type]
    assert m["index_usd"] is not None


def test_a_changed_bar_is_never_served_from_an_old_block(session: Session) -> None:
    _market(session)
    before = cols.compute(session, DAY, DAY).rows[1]["ret_1w"]
    bar = session.get(PriceDaily, (1, DAY))
    assert bar is not None
    bar.close = float(bar.close or 0.0) * 1.5
    bar.fetched_at = dt.datetime.now(dt.UTC)
    session.commit()
    after = cols.compute(session, DAY, DAY).rows[1]["ret_1w"]
    assert before != after


def test_listing_gives_the_first_day_and_its_reference_price(session: Session) -> None:
    _market(session)
    first = cols.listing(session, 1)
    assert first["first_day"] == (DAY - dt.timedelta(days=N - 1)).isoformat()
    assert first["ipo_price"] == pytest.approx(1000.0)


# ------------------------------------------------------------------ endpoints


@pytest.fixture
def client(session: Session, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setattr(ind, "_ranking_doc", lambda: None)
    monkeypatch.setattr(ind, "_turning_doc", lambda: None)
    app = create_app()
    app.dependency_overrides[get_session] = lambda: session
    with TestClient(app) as c:
        yield c


def test_catalog_endpoint_lists_every_column(client: TestClient) -> None:
    j = client.get("/columns/catalog").json()
    assert len(j["columns"]) == len(cols.CATALOG)
    assert {g["key"] for g in j["groups"]} == set(cols.GROUPS)


def test_instrument_columns_have_sections_and_medians(client: TestClient, session: Session) -> None:
    _market(session)
    j = client.get("/instruments/1/columns").json()
    assert j["available"] is True
    sections = {s["key"]: s for s in j["sections"]}
    assert sections["returns"]["items"][0]["key"] == "ret_1w"
    assert sections["growth"]["note"] is None
    pe = {i["key"]: i for i in sections["multiples"]["items"]}["pe_ttm"]
    assert pe["value"] is not None
    first = {i["key"]: i for i in sections["listing"]["items"]}["first_day"]
    assert first["value"] is not None


def test_a_symbol_without_statements_says_so(client: TestClient, session: Session) -> None:
    _market(session)
    j = client.get("/instruments/2/columns").json()
    notes = {s["key"]: s["note"] for s in j["sections"]}
    assert notes["growth"] == cols.NO_STMT
    assert notes["multiples"] == cols.NO_STMT
    assert notes["book"] == cols.NO_BOOK


def test_a_fund_has_no_columns(client: TestClient, session: Session) -> None:
    _market(session)
    assert client.get("/instruments/9/columns").json()["available"] is False


def test_screener_adds_and_sorts_by_derived_columns(client: TestClient, session: Session) -> None:
    _market(session)
    j = client.get("/screener?columns=ret_1m,pe_ttm&sort_col=mcap&limit=10").json()
    assert j["columns"] == ["ret_1m", "pe_ttm", "mcap"]
    caps = [r["cols"]["mcap"] for r in j["rows"]]
    assert caps == sorted(caps, reverse=True)
    plain = client.get("/screener?limit=3").json()
    assert plain["columns"] == [] and plain["rows"][0]["cols"] == {}
    bad = client.get("/screener?columns=nope,ret_1m").json()
    assert bad["columns"] == ["ret_1m"]


def test_industry_pages_carry_columns_medians_and_the_market_block(
    client: TestClient, session: Session
) -> None:
    _market(session)
    d = client.get("/industries/27/detail").json()
    assert d["medians"]["beta_90d"] is not None
    assert "ret_1m" in d["members"][0]["cols"]
    o = client.get("/industries/overview").json()
    assert o["market"]["mcap_usd"] is not None
    assert "beta_90d" in o["industries"][0]["medians"]
    assert client.get("/columns/market").json()["usd"] == 1e6
