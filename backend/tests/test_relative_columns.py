"""Relative columns of features/relative.py: no look-ahead, and what each reading means."""

from __future__ import annotations

import numpy as np
import polars as pl

from tests.test_extra_columns import CUT, _build, _inputs
from tests.test_features import RULES
from tmon.features.extra import build_extra
from tmon.features.relative import REL_COLUMNS, REL_GROUPS, build_relative


def _rel(until=None):
    prices, clients, ix, shares, stmts = _inputs()
    if until is not None:
        prices = prices.filter(pl.col("date") <= until)
        clients = clients.filter(pl.col("date") <= until)
        ix = ix.filter(pl.col("date") <= until)
    sectors = pl.DataFrame({"instrument_id": [1, 2, 3, 4], "sector_code": list("aabb")})
    extra = build_extra(
        prices, clients, RULES, sectors=sectors, index_close=ix, shares=shares, stmts=stmts
    )
    return build_relative(prices, clients, extra, sectors=sectors, index_close=ix), prices


def test_columns_up_to_t_do_not_depend_on_later_data() -> None:
    full, _ = _rel()
    cut, _ = _rel(until=CUT)
    a = full.filter(pl.col("date") <= CUT).sort("instrument_id", "date")
    b = cut.sort("instrument_id", "date")
    assert a.height == b.height
    for name in a.columns:
        x, y = a[name].to_numpy().astype(float), b[name].to_numpy().astype(float)
        ok = (np.isnan(x) & np.isnan(y)) | np.isclose(x, y, rtol=1e-9, atol=1e-9, equal_nan=True)
        assert ok.all(), f"{name} uses data after the cut"


def test_every_relative_column_is_present_once_and_finite() -> None:
    rel, _ = _rel()
    assert list(rel.columns) == ["instrument_id", "date", *REL_COLUMNS]
    assert len(set(REL_COLUMNS)) == len(REL_COLUMNS)
    assert sum(len(g) for g in REL_GROUPS.values()) == len(REL_COLUMNS)
    for k in REL_COLUMNS:
        assert not rel[k].is_infinite().any(), k


def test_rank_is_a_share_between_zero_and_one_and_orders_the_stocks() -> None:
    rel, _ = _rel()
    day = rel.filter(pl.col("date") == rel["date"].max())
    r = day["vol_vs_30_rank"].drop_nulls()
    assert r.min() > 0 and r.max() <= 1.0 + 1e-12
    assert abs(r.max() - 1.0) < 1e-12  # somebody is top of the day


def test_gap_to_the_industry_median_is_zero_for_the_median_member() -> None:
    rel, _ = _rel()
    day = rel.filter(pl.col("date") == rel["date"].max())
    # two industries of two stocks: each member sits equally far above and below the median
    pairs = day.sort("instrument_id")["val_vs_30_ind"].to_list()
    assert abs(pairs[0] + pairs[1]) < 1e-9
    assert abs(pairs[2] + pairs[3]) < 1e-9


def test_flow_with_trend_flips_sign_against_the_trend() -> None:
    rel, _ = _rel()
    ext = _build(*_inputs()).join(rel, on=["instrument_id", "date"])
    both = ext.drop_nulls(["real_net_with_trend", "real_net_pct", "stock_trend"])
    assert both.height > 0
    same = np.sign(both["stock_trend"].to_numpy()) * both["real_net_pct"].to_numpy()
    mask = both["stock_trend"].to_numpy() != 0
    assert np.allclose(both["real_net_with_trend"].to_numpy()[mask], same[mask])
