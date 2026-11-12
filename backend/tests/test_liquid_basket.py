"""The liquid-basket restriction is point in time and the Codal backfill reads the basket file."""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import numpy as np

from tmon.backtest.v2_gates import Matrices, restrict_top_liquid
from tmon.ingest.codal.backfill import basket_symbols


def _m(rank: np.ndarray, med: np.ndarray) -> Matrices:
    days, n = rank.shape
    return Matrices(
        dates=[date(2026, 1, 1 + d) for d in range(days)],
        ret=np.zeros((days, n)),
        rank=rank,
        queue=np.zeros((days, n)),
        median_value=med,
        sector=np.array(["a"] * n, dtype=object),
        buy_cost=np.zeros(days),
        sell_cost=np.zeros(days),
        start=0,
    )


def test_keeps_only_top_n_by_value_each_day() -> None:
    rank = np.array([[0.9, 0.5, 0.1, 0.7], [0.9, 0.5, 0.1, 0.7]])
    # day 0: names 2 and 3 are the most liquid; day 1: names 0 and 1
    med = np.array([[1.0, 2.0, 9.0, 8.0], [9.0, 8.0, 1.0, 2.0]])
    out = restrict_top_liquid(_m(rank, med), 2, min_cross_section=2)
    assert np.isfinite(out.rank[0]).tolist() == [False, False, True, True]
    assert np.isfinite(out.rank[1]).tolist() == [True, True, False, False]
    assert np.isfinite(rank).all()  # the input is not modified


def test_unranked_or_unmeasured_names_never_enter() -> None:
    rank = np.array([[0.9, np.nan, 0.5]])
    med = np.array([[5.0, 99.0, np.nan]])
    out = restrict_top_liquid(_m(rank, med), 3, min_cross_section=1)
    assert np.isfinite(out.rank[0]).tolist() == [True, False, False]


def test_start_moves_to_first_day_with_enough_names() -> None:
    rank = np.array([[0.9, np.nan], [0.9, 0.5]])
    med = np.array([[5.0, 5.0], [5.0, 5.0]])
    assert restrict_top_liquid(_m(rank, med), 2, min_cross_section=2).start == 1


def test_basket_symbols_keep_file_order(tmp_path: Path) -> None:
    f = tmp_path / "b.json"
    f.write_text(json.dumps({"symbols": ["فملی", "فولاد"]}, ensure_ascii=False), "utf-8")
    assert basket_symbols(f) == ["فملی", "فولاد"]


def test_basket_index_pays_costs_only_on_traded_amount() -> None:
    from tmon.backtest.v2_gates import basket_index

    days = 8
    ret = np.zeros((days, 2))
    ret[2, 0] = 1.0  # name 0 doubles on day 2
    m = _m(np.full((days, 2), 0.5), np.ones((days, 2)))
    m.ret, m.start = ret, 1
    m.buy_cost, m.sell_cost = np.full(days, 0.01), np.full(days, 0.01)
    r = dict(zip(basket_index(m, review_every=5)["date"], basket_index(m, 5)["ret"], strict=True))
    d = m.dates
    assert abs(r[d[1]] - (-0.01)) < 1e-12  # first purchase: the whole book is bought
    assert abs(r[d[2]] - 0.5) < 1e-12  # equal weights, one name doubles
    # day 6 resets 2/3-1/3 back to 1/2-1/2: one sixth bought and one sixth sold
    assert abs(r[d[6]] - (-(1 / 6) * 0.01 * 2)) < 1e-12
    assert r[d[3]] == 0.0
