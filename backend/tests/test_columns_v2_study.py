"""The add-one test of the new columns against the four-signal ranking: its daily statistic."""

from __future__ import annotations

import math

import numpy as np

from tmon.backtest.columns_v2_study import _daily


def test_a_score_that_orders_the_stocks_like_the_return_has_ic_one() -> None:
    n = 100
    y = np.linspace(-0.5, 0.5, n)
    f = np.linspace(-0.2, 0.3, n)
    ic, ex = _daily(y.copy(), y, f)
    assert abs(ic - 1.0) < 1e-9
    assert ex > 0  # the top tenth beat the median stock


def test_too_few_stocks_gives_no_reading() -> None:
    ic, ex = _daily(np.arange(5.0), np.arange(5.0), np.arange(5.0))
    assert math.isnan(ic) and math.isnan(ex)


def test_a_flat_score_gives_no_reading() -> None:
    n = 100
    ic, _ = _daily(np.zeros(n), np.linspace(0, 1, n), np.linspace(0, 1, n))
    assert math.isnan(ic)
