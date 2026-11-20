"""Training columns of features/extra.py: no look-ahead, and the plain meaning of each group."""

from __future__ import annotations

import datetime as dt
from datetime import date, timedelta

import numpy as np
import polars as pl

from tests.test_features import RULES, synthetic_market
from tmon.features import fundamentals as fu
from tmon.features.extra import EXTRA_COLUMNS, GROUPS, build_extra, shares_frame

START = date(2023, 1, 1)
CUT = START + timedelta(days=280)


def _stmt(published: dt.datetime, net: float, equity: float) -> fu.Stmt:
    period = published.date() - timedelta(days=30)
    inc = {fu.REVENUE: [1000.0, 800.0], fu.NET: [net, net / 2], fu.GROSS: [400.0, 300.0]}
    bal = {fu.ASSETS: [5000.0], fu.LIABILITIES: [2000.0], fu.EQUITY: [equity]}
    return fu.Stmt(published, "consolidated", period, period, 12, bal, inc)


def _inputs():
    prices, clients = synthetic_market(n_days=340, n_inst=4)
    ix = (
        prices.group_by("date")
        .agg(pl.col("close").mean())
        .sort("date")
        .with_columns(pl.col("close") * 10)
    )
    shares = shares_frame([(1, START + timedelta(days=300), 1e6, 2e6)], {2: 1e6, 3: 1e6, 4: 1e6})
    # one filing before the cut, one after it
    stmts = {
        1: [
            _stmt(dt.datetime(2023, 4, 1), 100.0, 3000.0),
            _stmt(dt.datetime(2023, 12, 1), 900.0, 3500.0),
        ]
    }
    return prices, clients, ix, shares, stmts


def _build(prices, clients, ix, shares, stmts, until=None):
    if until is not None:
        prices = prices.filter(pl.col("date") <= until)
        clients = clients.filter(pl.col("date") <= until)
        ix = ix.filter(pl.col("date") <= until)
    sectors = pl.DataFrame({"instrument_id": [1, 2, 3, 4], "sector_code": list("aabb")})
    return build_extra(
        prices, clients, RULES, sectors=sectors, index_close=ix, shares=shares, stmts=stmts
    )


def test_columns_up_to_t_do_not_depend_on_later_data() -> None:
    prices, clients, ix, shares, stmts = _inputs()
    full = _build(prices, clients, ix, shares, stmts).filter(pl.col("date") <= CUT)
    cut = _build(prices, clients, ix, shares, stmts, until=CUT)
    a = full.sort("instrument_id", "date")
    b = cut.sort("instrument_id", "date")
    assert a.height == b.height
    for name in a.columns:
        x, y = a[name].to_numpy().astype(float), b[name].to_numpy().astype(float)
        ok = (np.isnan(x) & np.isnan(y)) | np.isclose(x, y, rtol=1e-9, atol=1e-9, equal_nan=True)
        assert ok.all(), f"{name} uses data after the cut"


def test_a_filing_counts_only_from_the_day_after_it_is_published() -> None:
    prices, clients, ix, shares, stmts = _inputs()
    e = _build(prices, clients, ix, shares, stmts).filter(pl.col("instrument_id") == 1)
    day = lambda d: e.filter(pl.col("date") == d)["net_margin"][0]  # noqa: E731
    assert day(date(2023, 3, 31)) is None  # nothing public yet
    assert day(date(2023, 4, 1)) is None  # filed that day: still not known at its close
    assert abs(day(date(2023, 4, 2)) - 0.1) < 1e-9  # 100 / 1000
    assert abs(day(date(2023, 12, 2)) - 0.9) < 1e-9


def test_symbols_without_statements_have_null_fundamentals() -> None:
    prices, clients, ix, shares, stmts = _inputs()
    e = _build(prices, clients, ix, shares, stmts).filter(pl.col("instrument_id") == 2)
    for c in GROUPS["fund"]:
        assert e[c].null_count() == e.height, c


def test_share_count_in_force_changes_the_market_cap_weight() -> None:
    sh = shares_frame([(1, date(2023, 6, 1), 1e6, 2e6)], {})
    got = sh.filter(pl.col("instrument_id") == 1).sort("date")
    assert got["shares"].to_list() == [1e6, 2e6]  # before the change: the old count


def test_dated_samples_replace_todays_count_in_the_past() -> None:
    # instrument 2: today's count is 9e6, but the dated pages showed 3e6 then 4e6
    dated = [(2, date(2023, 3, 1), 3e6), (2, date(2023, 9, 1), 4e6)]
    sh = shares_frame([], {2: 9e6}, dated).filter(pl.col("instrument_id") == 2)
    assert sh["shares"].to_list() == [3e6, 3e6, 4e6]  # base from the first sample, not 9e6
    # a change and a sample: the earlier of the two sets the count before both
    sh = shares_frame([(1, date(2023, 6, 1), 1e6, 2e6)], {}, [(1, date(2023, 3, 1), 1e6)])
    got = sh.filter(pl.col("instrument_id") == 1)
    assert got["shares"].to_list() == [1e6, 1e6, 2e6]


def test_every_extra_column_is_present_once() -> None:
    prices, clients, ix, shares, stmts = _inputs()
    e = _build(prices, clients, ix, shares, stmts)
    assert list(e.columns) == ["instrument_id", "date", *EXTRA_COLUMNS]
    assert len(set(EXTRA_COLUMNS)) == len(EXTRA_COLUMNS)


def test_volume_ratio_excludes_today_from_its_own_average() -> None:
    prices, clients, ix, shares, stmts = _inputs()
    e = _build(prices, clients, ix, shares, stmts).filter(pl.col("instrument_id") == 2)
    v = prices.filter(pl.col("instrument_id") == 2).sort("date")["value"].to_numpy()
    i = 100
    want = v[i] / v[i - 30 : i].mean()
    assert abs(e["val_vs_30"][i] - want) < 1e-9
