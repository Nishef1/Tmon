"""Trend ride rules (tmon.backtest.trend_ride): entry trigger, buy and sell queues, trailing exit."""

from __future__ import annotations

import numpy as np
import polars as pl

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
