"""Triple-barrier labels on hand-built bars where the right answer is obvious."""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import polars as pl
import pytest

from tests.test_features import RULES, synthetic_market
from tmon.domain.rules import RuleBook, RuleRecord
from tmon.labeling.triple_barrier import triple_barrier_labels

HALT_RULES = RuleBook(
    [
        RuleRecord("IR", "price_limit", {"pct": 0.03}, date(2000, 1, 1), None),
        RuleRecord("IR", "market_halt", {}, date(2026, 2, 28), date(2026, 5, 18)),
    ]
)

T = 20  # decision day index; ATR14 is flat at 10 by then (TR = 10 on every bar)
START = date(2023, 1, 1)


def bars(overrides: dict[int, dict[str, float]], n: int = 40, iid: int = 1) -> pl.DataFrame:
    """Flat market at 1000 (high 1005, low 995 => ATR 10) with per-day overrides. ``prev_close``
    always equals the previous close so no capital event is detected."""
    rows = []
    prev = 1000.0
    for i in range(n):
        b = {"open": prev, "high": prev + 5, "low": prev - 5, "close": prev}
        b.update(overrides.get(i, {}))
        rows.append(
            {
                "instrument_id": iid, "date": START + timedelta(days=i), "open": b["open"],
                "high": b["high"], "low": b["low"], "close": b["close"], "last": b["close"],
                "prev_close": prev, "volume": 1e5, "value": 1e5 * b["close"],
                "base_volume": 1e5, "market_halt": False,
            }
        )  # fmt: skip
        prev = b["close"]
    return pl.DataFrame(rows)


def label_at(overrides, *, n=40, tf="D1") -> dict:
    lab = triple_barrier_labels(bars(overrides, n), RULES, tf)
    return lab.filter(pl.col("date") == START + timedelta(days=T)).to_dicts()[0]


def test_take_profit_hit_first():
    r = label_at({T + 2: {"high": 1025.0, "close": 1015.0}})
    assert r["entry_price"] == 1000.0  # open of t+1 (= previous close, flat)
    assert (r["tp_price"], r["sl_price"]) == (1020.0, 990.0)
    assert r["y"] == 1 and r["exit_reason"] == "tp" and r["exit_day"] == 2
    assert r["realized_return"] == pytest.approx(0.02)
    assert r["valid"] and r["executable"]


def test_stop_loss_before_take_profit():
    r = label_at({T + 1: {"low": 985.0, "close": 995.0}, T + 2: {"high": 1030.0}})
    assert r["y"] == 0 and r["exit_reason"] == "sl" and r["exit_day"] == 1
    assert r["realized_return"] == pytest.approx(-0.01)


def test_same_day_tp_and_sl_is_a_loss():
    r = label_at({T + 2: {"high": 1025.0, "low": 985.0, "close": 1000.0}})
    assert r["y"] == 0 and r["exit_reason"] == "sl_same_day"
    assert r["realized_return"] == pytest.approx(-0.01)


def test_expiry_returns_horizon_close_and_label_zero():
    r = label_at({T + 3: {"close": 1004.0, "high": 1006.0}})
    assert r["y"] == 0 and r["exit_reason"] == "expiry" and r["exit_day"] == 3
    assert r["realized_return"] == pytest.approx(0.004)


def test_take_profit_after_horizon_does_not_count():
    r = label_at({T + 4: {"high": 1100.0, "close": 1050.0}})
    assert r["y"] == 0 and r["exit_reason"] == "expiry"


def test_gap_down_through_stop_exits_at_the_open():
    r = label_at({T + 2: {"open": 975.0, "high": 980.0, "low": 970.0, "close": 972.0}})
    assert r["y"] == 0 and r["realized_return"] == pytest.approx(-0.025)


def test_buy_queue_entry_is_not_executable():
    # t+1 opens, trades and closes at the +3% limit all day: nobody could have bought
    r = label_at({T + 1: {"open": 1030.0, "high": 1030.0, "low": 1030.0, "close": 1030.0}}, tf="D1")
    assert r["executable"] is False


def test_locked_limit_down_exit_slips_to_next_open():
    # SL day is a locked -3% bar: cannot sell; the exit moves to the next open
    r = label_at(
        {
            T + 2: {"open": 970.0, "high": 970.0, "low": 970.0, "close": 970.0},
            T + 3: {"open": 960.0, "high": 965.0, "low": 955.0, "close": 958.0},
        }
    )
    assert r["y"] == 0 and r["exit_delayed"] is True
    assert r["realized_return"] == pytest.approx(960.0 / 1000.0 - 1)


def test_tail_and_warmup_rows_are_invalid_and_blank():
    lab = triple_barrier_labels(bars({}), RULES, "D1").sort("date")
    assert not lab["valid"][:13].any()  # ATR(14) not defined yet
    assert not lab["valid"][-3:].any()  # horizon runs past the data
    bad = lab.filter(~pl.col("valid"))
    assert bad["y"].null_count() == bad.height
    assert lab["valid"][20]


def test_instruments_do_not_bleed_into_each_other():
    a = bars({}, iid=1)
    b = bars({38: {"high": 1100.0, "close": 1050.0}}, iid=2)
    lab = triple_barrier_labels(pl.concat([a, b]), RULES, "D1")
    last_a = lab.filter(pl.col("instrument_id") == 1).sort("date")
    assert not last_a["valid"][-3:].any()  # must not read instrument 2's bars


def test_window_crossing_a_halt_is_invalid():
    # the seeded halt covers 2026-02-28..2026-05-18; place bars around its start
    n = 40
    base = date(2026, 2, 10)
    b = bars({}, n).with_columns(
        (pl.lit(base) + pl.duration(days=pl.int_range(pl.len()))).alias("date")
    )
    b = b.filter(pl.col("date") <= date(2026, 2, 27))  # market closed afterwards
    lab = triple_barrier_labels(b, HALT_RULES, "D1")
    assert lab["valid"].sum() > 0
    # reopen after the halt: first post-halt bars cannot be labelled from pre-halt decisions
    tail = bars({}, 30).with_columns(
        (pl.lit(date(2026, 5, 19)) + pl.duration(days=pl.int_range(pl.len()))).alias("date")
    )
    both = pl.concat([b, tail])
    lab = triple_barrier_labels(both, HALT_RULES, "D1").sort("date")
    pre = lab.filter(pl.col("date") >= date(2026, 2, 25)).filter(
        pl.col("date") <= date(2026, 2, 27)
    )
    assert not pre["valid"].any()


def test_labels_are_independent_of_adjustment_events():
    prices, _ = synthetic_market(n_days=330, n_inst=3)
    lab = triple_barrier_labels(prices, RULES, "D1")
    ev = lab.filter(pl.col("instrument_id") == 2).filter(pl.col("valid"))
    # the 2:1 event must not create fake -50% stop-outs
    assert ev["realized_return"].min() > -0.2
    assert np.isfinite(ev["realized_return"].to_numpy()).all()


def test_label_rate_is_plausible_on_a_random_walk():
    prices, _ = synthetic_market(n_days=330, n_inst=4)
    lab = triple_barrier_labels(prices, RULES, "D1").filter(pl.col("valid"))
    rate = lab["y"].mean()
    assert 0.0 < rate < 0.5  # 2:1 barriers in 3 days: wins are the minority
