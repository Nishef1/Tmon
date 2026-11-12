"""Backtester: costs, walk-forward hygiene, simulation arithmetic, and end-to-end sanity on
synthetic markets (a random walk must not make money; a planted edge must be visible)."""

from __future__ import annotations

import itertools
from datetime import date, timedelta
from typing import ClassVar

import numpy as np
import polars as pl
import pytest

from tmon.backtest.baseline import BaselineD1
from tmon.backtest.costs import add_costs
from tmon.backtest.report import render_markdown, to_dict
from tmon.backtest.runner import prepare_dataset, run_backtest
from tmon.backtest.simulate import simulate
from tmon.backtest.synthetic import make_market
from tmon.backtest.walkforward import make_folds, run_walk_forward, training_rows
from tmon.core.engine_config import get_engine_config
from tmon.domain.rules import CostModel
from tmon.storage.seed import seed_rulebook

RULES = seed_rulebook()
CFG = get_engine_config()


# --- costs ---------------------------------------------------------------------------------


def test_vectorised_costs_match_the_scalar_cost_model():
    d = date(2025, 3, 1)
    df = pl.DataFrame(
        {"realized_return": [0.05, -0.02, 0.0], "entry_date": [d] * 3, "exit_date": [d] * 3}
    )
    out = add_costs(df, RULES, CFG.costs.slippage_fraction)
    model = CostModel.from_rules(RULES, d, CFG.costs.slippage_fraction)
    for g, net in zip(df["realized_return"], out["net_return"], strict=True):
        assert net == pytest.approx(model.net_return(g))
    assert out["round_trip_cost"][0] == pytest.approx(model.round_trip)


# --- walk-forward ----------------------------------------------------------------------------


def test_folds_leave_a_purge_gap_and_do_not_overlap():
    dates = [date(2024, 1, 1) + timedelta(days=i) for i in range(400)]
    folds = make_folds(dates, horizon=3, embargo=3, retrain_every=20, min_train_days=250)
    assert folds[0].test_start == dates[250 + 4]
    idx = {d: i for i, d in enumerate(dates)}
    for f in folds:
        assert idx[f.test_start] - idx[f.train_cutoff] == 4  # embargo + 1
        assert f.test_start <= f.test_end
    for a, b in itertools.pairwise(folds):
        assert idx[b.test_start] == idx[a.test_end] + 1  # contiguous, no overlap
    assert folds[-1].test_end == dates[-1]


def test_training_rows_never_reach_into_the_test_period():
    prices, clients, sectors = make_market(500, 8, seed=2)
    ds = prepare_dataset(prices, clients, RULES, sectors=sectors)
    wf = run_walk_forward(ds, BaselineD1)
    assert wf.folds
    for fold in wf.folds:
        tr = training_rows(ds, fold)
        assert tr.height > 0
        assert tr["date"].max() <= fold.train_cutoff
        assert tr["exit_date"].max() < fold.test_start  # label windows resolved before the test


class Recorder:
    name = "rec"
    seen: ClassVar[list[tuple[date, date]]] = []

    def fit(self, train: pl.DataFrame) -> None:
        self.max_exit = train["exit_date"].max()

    def predict(self, test: pl.DataFrame) -> pl.DataFrame:
        Recorder.seen.append((self.max_exit, test["date"].min()))
        return test.select(
            "instrument_id", "date", pl.lit(False).alias("signal"), pl.lit(0.0).alias("score")
        )


def test_every_fold_is_fitted_only_on_resolved_labels():
    prices, clients, sectors = make_market(450, 6, seed=4)
    ds = prepare_dataset(prices, clients, RULES, sectors=sectors)
    Recorder.seen = []
    run_walk_forward(ds, Recorder)
    assert Recorder.seen
    assert all(max_exit < test_start for max_exit, test_start in Recorder.seen)


# --- simulation arithmetic --------------------------------------------------------------------


def _mini_dataset(rows: list[dict]) -> pl.DataFrame:
    base = {
        "valid": True,
        "executable": True,
        "atr_14_pct": 0.02,
        "y": 0,
        "exit_reason": "expiry",
        "exit_delayed": False,
    }
    return pl.DataFrame([{**base, **r} for r in rows])


def _sim(preds_rows, ds_rows, cfg=CFG):
    ds = _mini_dataset(ds_rows)
    preds = pl.DataFrame(preds_rows)
    return simulate(preds, ds, RULES, "D1", cfg)


D0 = date(2025, 1, 1)


def _day(i: int) -> date:
    return D0 + timedelta(days=i)


def _calendar_rows(extra: list[dict]) -> list[dict]:
    """Rows for every day 0..9 (a calendar) plus ``extra`` labelled rows that override."""
    rows = {
        i: {
            "instrument_id": 99,
            "date": _day(i),
            "entry_date": _day(i),
            "exit_date": _day(i),
            "realized_return": 0.0,
            "valid": False,
        }
        for i in range(10)
    }
    out = list(rows.values())
    out.extend(extra)
    return out


def test_single_trade_pnl_is_weight_times_net_return():
    ds_rows = _calendar_rows(
        [
            {
                "instrument_id": 1,
                "date": _day(1),
                "entry_date": _day(2),
                "exit_date": _day(4),
                "realized_return": 0.06,
                "y": 1,
                "exit_reason": "tp",
            }
        ]
    )
    r = _sim(
        [{"instrument_id": 1, "date": _day(1), "signal": True, "score": 1.0}],
        ds_rows,
    )
    t = r.trades
    assert t.height == 1
    w = min(CFG.sizing.max_position_pct, CFG.sizing.risk_per_trade / (1.0 * 0.02))
    assert t["weight_applied"][0] == pytest.approx(w)
    net = (1.06 * (1 - t["sell_cost"][0])) / (1 + t["buy_cost"][0]) - 1
    assert t["net_return"][0] == pytest.approx(net)
    booked = r.daily.filter(pl.col("date") == _day(4))["ret"][0]
    assert booked == pytest.approx(w * net)
    assert r.daily.filter(pl.col("date") != _day(4))["ret"].abs().sum() == 0  # booked at exit only


def test_buy_queue_entries_are_unfilled_and_unlabelled_are_dropped():
    ds_rows = _calendar_rows(
        [
            {
                "instrument_id": 1,
                "date": _day(1),
                "entry_date": _day(2),
                "exit_date": _day(4),
                "realized_return": 0.1,
                "executable": False,
            },
            {
                "instrument_id": 2,
                "date": _day(1),
                "entry_date": _day(2),
                "exit_date": _day(4),
                "realized_return": 0.1,
                "valid": False,
            },
        ]
    )
    preds = [
        {"instrument_id": 1, "date": _day(1), "signal": True, "score": 2.0},
        {"instrument_id": 2, "date": _day(1), "signal": True, "score": 1.0},
    ]
    r = _sim(preds, ds_rows)
    assert r.trades.height == 0
    assert r.counts["unfilled_buy_queue"] == 1 and r.counts["unresolved"] == 1


def test_only_the_top_scores_are_taken_each_day():
    cap = CFG.backtest.max_new_positions_per_day
    n = cap + 3
    ds_rows = _calendar_rows(
        [
            {
                "instrument_id": i,
                "date": _day(1),
                "entry_date": _day(2),
                "exit_date": _day(3),
                "realized_return": 0.01,
            }
            for i in range(1, n + 1)
        ]
    )
    preds = [
        {"instrument_id": i, "date": _day(1), "signal": True, "score": float(i)}
        for i in range(1, n + 1)
    ]
    r = _sim(preds, ds_rows)
    assert r.trades.height == cap
    assert set(r.trades["instrument_id"]) == set(range(n, n - cap, -1))


def test_gross_exposure_cap_shrinks_overlapping_positions():
    tight = CFG.model_copy(
        update={"backtest": CFG.backtest.model_copy(update={"max_gross_exposure": 0.15})}
    )
    ds_rows = _calendar_rows(
        [
            {
                "instrument_id": i,
                "date": _day(1),
                "entry_date": _day(2),
                "exit_date": _day(4),
                "realized_return": 0.0,
            }
            for i in (1, 2)
        ]
    )
    preds = [
        {"instrument_id": 1, "date": _day(1), "signal": True, "score": 2.0, "weight": 0.1},
        {"instrument_id": 2, "date": _day(1), "signal": True, "score": 1.0, "weight": 0.1},
    ]
    r = _sim(preds, ds_rows, tight)
    assert r.trades["weight_applied"].sum() == pytest.approx(0.15)  # 0.2 requested, capped
    loose = _sim(preds, ds_rows)
    assert loose.trades["weight_applied"].sum() == pytest.approx(0.2)


# --- end to end ------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def random_walk_run():
    prices, clients, sectors = make_market(700, 40, seed=11, edge=0.0)
    ds = prepare_dataset(prices, clients, RULES, sectors=sectors)
    return run_backtest(ds, RULES, {"baseline_d1": BaselineD1})


@pytest.fixture(scope="module")
def edge_run():
    prices, clients, sectors = make_market(700, 40, seed=11, edge=0.012)
    ds = prepare_dataset(prices, clients, RULES, sectors=sectors)
    return run_backtest(ds, RULES, {"baseline_d1": BaselineD1})


def test_random_walk_has_no_edge_after_costs(random_walk_run):
    s = random_walk_run.strategies["baseline_d1"].summary
    assert s["trades"]["n_trades"] > 100
    assert s["trades"]["expectancy_net"] < 0  # costs are paid, nothing is earned
    # gross expectation of a 2:1 barrier on a driftless walk is about zero
    assert abs(s["trades"]["expectancy_gross"]) < 0.01


def test_planted_edge_is_detected(random_walk_run, edge_run):
    a = random_walk_run.strategies["baseline_d1"].summary["trades"]
    b = edge_run.strategies["baseline_d1"].summary["trades"]
    assert b["expectancy_gross"] > a["expectancy_gross"] + 0.005
    assert b["barrier_hit_rate"] > a["barrier_hit_rate"] + 0.05


def test_halt_regime_has_no_trades_and_split_is_reported(random_walk_run):
    reg = random_walk_run.strategies["baseline_d1"].summary["by_regime"]
    assert "halt" not in reg  # the market was closed; nothing is traded or evaluated
    assert "normal" in reg or "post_reopen" in reg


def test_report_contains_caveats_and_benchmarks(random_walk_run):
    md = render_markdown(random_walk_run, "t", synthetic=True)
    assert "داده مصنوعی" in md
    assert "تطبیق داده نشده‌اند" in md  # unverified commission/tax rules are flagged
    assert "هم‌وزن" in md
    d = to_dict(random_walk_run)
    assert "equal_weight_all" in d["benchmarks"]
    assert np.isfinite(d["benchmarks"]["equal_weight_all"]["portfolio"]["total_return"])


def test_universe_benchmark_does_not_peek_at_todays_queue_state():
    from tmon.backtest.runner import benchmark_series

    d1, d2 = date(2025, 1, 1), date(2025, 1, 2)
    ds = pl.DataFrame(
        {
            "instrument_id": [1, 1, 2, 2],
            "date": [d1, d2, d1, d2],
            "in_universe": [True, False, True, True],  # stock 1 closes limit-down on d2
            "ret_1": [0.0, -0.03, 0.0, 0.01],
            "mkt_ret_ew": [0.0, -0.01, 0.0, -0.01],
        }
    )
    out = benchmark_series(ds, d1, d2, CFG)["equal_weight_universe"].sort("date")
    assert out.filter(pl.col("date") == d2)["ret"][0] == pytest.approx(-0.01)  # includes stock 1
