from datetime import date, timedelta

import polars as pl
import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from tmon.features.adjustment import apply_adjustments, detect_adjustments


def _frame(closes, prev_closes, iid=1):
    n = len(closes)
    return pl.DataFrame(
        {
            "instrument_id": [iid] * n,
            "date": [date(2025, 1, 1) + timedelta(days=i) for i in range(n)],
            "open": closes,
            "high": closes,
            "low": closes,
            "close": closes,
            "last": closes,
            "prev_close": prev_closes,
            "volume": [1000.0] * n,
        }
    )


def test_dividend_event_reference_values():
    # day3 opens on a reset basis: 1100 -> 990 (factor 0.9)
    df = _frame([1000.0, 1100.0, 1000.0], [950.0, 1000.0, 990.0])
    ev = detect_adjustments(df)
    assert ev.height == 1
    row = ev.row(0, named=True)
    assert row["date"] == date(2025, 1, 3)
    assert row["close_before"] == 1100.0
    assert row["adj_factor"] == pytest.approx(0.9)

    adj = apply_adjustments(df)
    assert adj["adj_close"].to_list() == pytest.approx([900.0, 990.0, 1000.0])
    assert adj["adj_factor_cum"].to_list() == pytest.approx([0.9, 0.9, 1.0])
    # volume is restated in post-event share terms
    assert adj["adj_volume"].to_list() == pytest.approx([1000 / 0.9, 1000 / 0.9, 1000.0])


def test_two_events_compound():
    df = _frame(
        [100.0, 100.0, 100.0, 100.0],
        [100.0, 100.0, 80.0, 40.0],  # day3: x0.8 ; day4: 40/100 = x0.4
    )
    adj = apply_adjustments(df)
    assert adj["adj_factor_cum"].to_list() == pytest.approx([0.32, 0.32, 0.4, 1.0])


def test_no_events_is_identity():
    df = _frame([10.0, 11.0, 12.0], [10.0, 10.0, 11.0])
    assert detect_adjustments(df).is_empty()
    assert apply_adjustments(df)["adj_close"].to_list() == [10.0, 11.0, 12.0]


def test_instruments_are_independent():
    a = _frame([100.0, 100.0], [100.0, 50.0], iid=1)
    b = _frame([100.0, 100.0], [100.0, 100.0], iid=2)
    adj = apply_adjustments(pl.concat([a, b]))
    out = {
        i: g["adj_factor_cum"].to_list()
        for i, g in adj.group_by("instrument_id", maintain_order=True)
    }
    assert out[(1,)] == pytest.approx([0.5, 1.0])
    assert out[(2,)] == [1.0, 1.0]


@settings(max_examples=60, deadline=None)
@given(st.lists(st.tuples(st.floats(0.5, 1.5), st.floats(0.2, 1.0)), min_size=3, max_size=40))
def test_adjusted_returns_match_exchange_reference(steps):
    """Invariant: after adjustment, close_t / close_{t-1} == close_t / prev_close_t."""
    closes, prevs = [], []
    price = 100000.0
    for move, reset in steps:
        prev = max(10, round(price * reset)) if reset < 0.999 else round(price)
        close = max(10.0, round(prev * move))
        prevs.append(float(prev))
        closes.append(float(close))
        price = close
    adj = apply_adjustments(_frame(closes, prevs)).sort("date")
    ac = adj["adj_close"].to_list()
    for t in range(1, len(closes)):
        expected = closes[t] / prevs[t]
        assert ac[t] / ac[t - 1] == pytest.approx(expected, rel=1e-9)


def test_small_upward_gap_is_a_missing_day_not_an_event():
    # 100 -> (missing day at 106) -> prev_close 106: a real move, no adjustment
    ev = detect_adjustments(_frame([100.0, 107.0], [99.0, 106.0]))
    assert ev.is_empty()


def test_capital_decrease_and_dividend_stay_events():
    ev = detect_adjustments(_frame([100.0, 150.0, 140.0, 130.0], [99.0, 150.0, 150.0, 120.0]))
    assert ev["adj_factor"].to_list() == pytest.approx([1.5, 120.0 / 140.0])


def test_absurd_factor_is_ignored():
    ev = detect_adjustments(_frame([1000.0, 40.0], [990.0, 30.0]))
    assert ev.is_empty()


def test_fixed_income_payout_is_adjusted_only_for_payout_ids():
    # a monthly-paying fixed-income fund: 10250 -> 10010 with no prev_close reset (TSETMC data)
    closes = [10200.0, 10250.0, 10010.0, 10020.0]
    df = _frame(closes, [10190.0, 10200.0, 10250.0, 10010.0])
    assert detect_adjustments(df).height == 0
    assert apply_adjustments(df)["adj_close"].to_list() == pytest.approx(closes)

    adj = apply_adjustments(df, payout_ids=[1])["adj_close"].to_list()
    # the payout is reinvested: the return over the payout day is the fund's real carry
    assert adj[3] / adj[0] - 1 == pytest.approx(10250 / 10200 * 10020 / 10010 - 1)
    assert adj[2] == pytest.approx(adj[1])


def test_small_fixed_income_dip_is_not_a_payout():
    df = _frame([10200.0, 10250.0, 10200.0], [10190.0, 10200.0, 10250.0])  # -0.5%
    assert apply_adjustments(df, payout_ids=[1])["adj_close"].to_list() == pytest.approx(
        [10200.0, 10250.0, 10200.0]
    )
