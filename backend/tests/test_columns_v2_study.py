"""The add-one test of the new columns against the four-signal ranking: its daily statistic."""

from __future__ import annotations

import math

import numpy as np

from tmon.backtest.columns_v2_study import _both, _daily, _turnover


def test_a_score_that_orders_the_stocks_like_the_return_has_ic_one() -> None:
    n = 100
    y = np.linspace(-0.5, 0.5, n)
    f = np.linspace(-0.2, 0.3, n)
    ic, ex, top = _daily(y.copy(), y, f, np.arange(n))
    assert abs(ic - 1.0) < 1e-9
    assert ex > 0  # the top tenth beat the median stock
    assert top == frozenset(range(90, 100))


def test_too_few_stocks_gives_no_reading() -> None:
    ic, ex, top = _daily(np.arange(5.0), np.arange(5.0), np.arange(5.0), np.arange(5))
    assert math.isnan(ic) and math.isnan(ex) and not top


def test_a_flat_score_gives_no_reading() -> None:
    n = 100
    ic, _, _ = _daily(np.zeros(n), np.linspace(0, 1, n), np.linspace(0, 1, n), np.arange(n))
    assert math.isnan(ic)


def test_turnover_is_the_share_of_new_names() -> None:
    assert _turnover(frozenset({1, 2, 3, 4}), frozenset({1, 2, 9, 8})) == 0.5
    assert math.isnan(_turnover(frozenset({1}), frozenset()))


def test_both_halves_must_be_positive() -> None:
    x = np.array([np.nan, 1.0, 2.0, -1.0, 3.0])
    assert _both(x, 1, 3) is True  # 1.5 and 1.0
    assert _both(np.array([1.0, 1.0, -5.0, 1.0]), 0, 2) is False
