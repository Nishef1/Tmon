from __future__ import annotations

import datetime as dt

import numpy as np

from tmon.api.routers.instruments import trend_scales
from tmon.api.schemas import Candle
from tmon.backtest.trend_ride import swing_leg


def _candles(closes: list[float]) -> list[Candle]:
    d0 = dt.date(2025, 1, 1)
    return [
        Candle(date=d0 + dt.timedelta(days=i), open=c, high=c, low=c, close=c, volume=1.0)
        for i, c in enumerate(closes)
    ]


# up 50%, down 20%, up 40%, then a small dip: a 15% size sees every swing, a 25% size misses the
# 20% fall
WAVE = [100.0 + i for i in range(51)] + [150.0 - 1.5 * i for i in range(1, 21)]
WAVE += [120.0 + 2.5 * i for i in range(1, 29)] + [188.0 - 2 * i for i in range(1, 4)]


def test_swing_leg_names_the_leg_the_price_is_in() -> None:
    leg = swing_leg(np.array(WAVE), 0.15)
    kinds = [k for _, k in leg["swings"]]
    assert kinds == ["low", "high", "low"]  # first low at the start, the 150 peak, the 120 trough
    assert leg["direction"] == "up"
    assert WAVE[leg["since"]] == 120.0  # the newest confirmed swing is the 120 low
    assert WAVE[leg["extreme"]] == 190.0  # the running high, not yet confirmed
    assert abs(leg["from_extreme"] - (182.0 / 190.0 - 1)) < 1e-12
    assert abs(leg["from_since"] - (182.0 / 120.0 - 1)) < 1e-12


def test_a_larger_size_sees_fewer_swings() -> None:
    small = swing_leg(np.array(WAVE), 0.08)["swings"]
    big = swing_leg(np.array(WAVE), 0.25)["swings"]
    assert len(small) > len(big)


def test_scales_for_the_page_and_a_short_history() -> None:
    assert trend_scales(_candles([100.0] * 10)) == []
    out = trend_scales(_candles(WAVE))
    assert [s.label for s in out] == ["کوتاه", "میانی", "بلند"]
    mid = out[1]
    assert mid.direction == "up" and mid.extreme is not None and mid.since is not None
    assert mid.extreme.kind == "high" and mid.since.kind == "low"
    flat = trend_scales(_candles([100.0 + (i % 2) for i in range(60)]))
    assert all(s.direction is None and s.swings == [] for s in flat)
