"""Trend ride rules (tmon.backtest.trend_ride): entry trigger, buy and sell queues, trailing exit."""

from __future__ import annotations

import numpy as np
import polars as pl
import pytest

from tmon.backtest import trend_ride as tr


def _flat(n: int) -> np.ndarray:
    return np.zeros(n, dtype=bool)


def test_signal_fires_on_the_first_day_only() -> None:
    close = np.array([90.0, 96.0, 97.0, 98.0, 80.0, 99.0])
    sma50 = np.full(6, 85.0)
    sma200 = np.full(6, 80.0)
    hi250 = np.full(6, 100.0)
    sig = tr.entry_signals(close, sma50, sma200, hi250, near_high=0.05)
    assert sig.tolist() == [False, True, False, False, False, True]


def test_trailing_exit_sells_at_the_next_close() -> None:
    close = np.array([100.0, 100.0, 150.0, 200.0, 160.0, 149.0, 140.0, 130.0])
    sig = _flat(8)
    sig[0] = True
    (r,) = tr.rides(close, _flat(8), _flat(8), sig, trail=0.25, max_hold=250)
    assert (r.entry, r.peak, r.exit_signal, r.exit) == (1, 3, 5, 6)


def test_buy_waits_for_a_buy_queue_to_open() -> None:
    close = np.array([100.0, 103.0, 106.0, 107.0, 108.0])
    up = np.array([False, True, True, False, False])
    sig = _flat(5)
    sig[0] = True
    (r,) = tr.rides(close, up, _flat(5), sig, trail=0.25, max_hold=250)
    assert r.entry == 3
    assert r.exit is None


def test_sell_waits_for_a_sell_queue_to_open() -> None:
    close = np.array([100.0, 100.0, 70.0, 68.0, 66.0, 65.0])
    down = np.array([False, False, False, True, True, False])
    sig = _flat(6)
    sig[0] = True
    (r,) = tr.rides(close, _flat(6), down, sig, trail=0.25, max_hold=250)
    assert (r.exit_signal, r.exit) == (2, 5)


def test_a_signal_while_riding_is_ignored_and_open_ride_has_a_stop() -> None:
    close = np.array([100.0, 100.0, 120.0, 130.0, 125.0])
    sig = np.array([True, False, True, False, False])
    rs = tr.rides(close, _flat(5), _flat(5), sig, trail=0.25, max_hold=250)
    assert len(rs) == 1 and rs[0].exit_signal is None
    g = pl.DataFrame({"date": list(range(5)), "close": close, "liquid": [True] * 5})
    cur = tr.current(g, rs, trail=0.25)
    assert cur is not None
    assert cur["status"] == "open"
    assert cur["stop"] == 130.0 * 0.75
    assert cur["gain"] == 125.0 / 100.0 - 1


def test_signal_on_the_last_day_means_buy_at_the_next_close() -> None:
    close = np.array([100.0, 101.0])
    sig = np.array([False, True])
    rs = tr.rides(close, _flat(2), _flat(2), sig, trail=0.25, max_hold=250)
    g = pl.DataFrame({"date": [0, 1], "close": close, "liquid": [True, True]})
    cur = tr.current(g, rs, trail=0.25)
    assert cur is not None and cur["status"] == "buy_next"


def test_ranges_are_ratios_of_the_signal_close_and_of_the_stop() -> None:
    close = np.array([100.0, 100.0, 120.0, 130.0, 125.0])
    sig = np.array([True, False, True, False, False])
    rs = tr.rides(close, _flat(5), _flat(5), sig, trail=0.35, max_hold=250)
    g = pl.DataFrame({"date": list(range(5)), "close": close, "liquid": [True] * 5})
    cur = tr.current(g, rs, 0.35, (-0.03, 0.05), (0.9, 1.02))
    assert cur is not None
    assert cur["buy_low"] == pytest.approx(100.0 * 0.97)
    assert cur["buy_high"] == pytest.approx(105.0)
    assert cur["stop"] == pytest.approx(130.0 * 0.65)
    assert cur["stop_low"] == pytest.approx(cur["stop"] * 0.9)
    assert cur["stop_high"] == pytest.approx(cur["stop"] * 1.02)


def test_current_lists_every_ride_for_the_chart_marks() -> None:
    close = np.array([100.0, 100.0, 200.0, 100.0, 100.0, 100.0, 150.0, 160.0, 170.0, 171.0])
    sig = _flat(10)
    sig[[0, 5]] = True
    rs = tr.rides(close, _flat(10), _flat(10), sig, trail=0.25, max_hold=250)
    g = pl.DataFrame({"date": list(range(10)), "close": close, "liquid": [True] * 10})
    cur = tr.current(g, rs, trail=0.25)
    assert cur is not None
    assert cur["rides"] == [
        {"entry_date": "1", "exit_date": "4", "gain": 0.0},
        {"entry_date": "6", "exit_date": None, "gain": pytest.approx(171 / 150 - 1)},
    ]


def test_the_hold_cap_renews_a_ride_while_the_trend_holds() -> None:
    # the price keeps rising: without the trend flags the cap sells after 3 days, with them the
    # ride goes on, so no sale mark lands in the middle of a rising trend
    close = np.array([100.0, 100.0, 110.0, 120.0, 130.0, 140.0, 150.0, 160.0])
    sig = _flat(8)
    sig[0] = True
    (capped,) = tr.rides(close, _flat(8), _flat(8), sig, trail=0.35, max_hold=3)
    assert (capped.entry, capped.exit_signal, capped.exit) == (1, 4, 5)
    trend = np.ones(8, dtype=bool)
    (kept,) = tr.rides(close, _flat(8), _flat(8), sig, trail=0.35, max_hold=3, trend=trend)
    assert kept.entry == 1 and kept.exit is None and kept.exit_signal is None


def test_the_hold_cap_still_sells_when_the_trend_is_gone() -> None:
    close = np.array([100.0, 100.0, 110.0, 120.0, 115.0, 112.0, 111.0])
    sig = _flat(7)
    sig[0] = True
    trend = np.array([True, True, True, True, False, False, False])
    (r,) = tr.rides(close, _flat(7), _flat(7), sig, trail=0.35, max_hold=3, trend=trend)
    assert (r.exit_signal, r.exit) == (4, 5)


def test_swings_mark_only_lows_and_highs_a_full_move_confirmed() -> None:
    close = np.array([100.0, 90.0, 80.0, 100.0, 130.0, 120.0, 140.0, 100.0, 90.0, 95.0, 110.0])
    # 80 -> 140 is a rise of 75% (low confirmed at row 2 once 108 is passed), 140 -> 90 a fall
    # of 36% (high at row 6); the dip 130 -> 120 is too small and the last low is not confirmed
    assert tr.swings(close, 0.35) == [(2, "low"), (6, "high")]
    assert tr.swings(close[:4], 0.35) == []
