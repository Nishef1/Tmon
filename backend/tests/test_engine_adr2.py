"""ADR 0002 sections 3-5: break-even thresholds, signal rule and tiers, the nested barrier grid and
the training-window split used for calibration."""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import polars as pl
import pytest

from tmon.backtest.runner import prepare_dataset, prepare_label_sets
from tmon.backtest.synthetic import make_market
from tmon.backtest.walkforward import make_folds, run_walk_forward
from tmon.core.engine_config import get_engine_config
from tmon.engine.thresholds import (
    breakeven_probability,
    decide,
    expected_value,
    minimum_probability,
)
from tmon.labeling.grid import grid_combos, with_labels
from tmon.models.lgbm import LightGBMStrategy
from tmon.models.splits import split_training_window
from tmon.storage.seed import seed_rulebook

CFG = get_engine_config()
RULES = seed_rulebook()
T = CFG.thresholds


def _arr(*v: float) -> np.ndarray:
    return np.array(v, dtype=float)


# --- break-even formula ---------------------------------------------------------------------


def test_breakeven_probability_is_the_root_of_net_expected_value():
    w, loss, c = _arr(0.12, 0.05, 0.03), _arr(0.01, 0.04, 0.02), _arr(0.0175, 0.0175, 0.0175)
    p_be = breakeven_probability(w, loss, c)
    assert p_be == pytest.approx((loss + c) / (w + loss))
    assert p_be[0] == pytest.approx(0.0275 / 0.13)
    # p_breakeven is where EV_net = p*W - (1-p)*L - c crosses zero
    assert expected_value(p_be, w, -loss, c) == pytest.approx(0.0, abs=1e-12)
    assert (expected_value(p_be + 0.01, w, -loss, c) > 0).all()
    assert (expected_value(p_be - 0.01, w, -loss, c) < 0).all()


def test_breakeven_handles_negative_loss_and_missing_payoff():
    # non-winners that average a gain (L < 0): still the root of the same EV
    p_be = breakeven_probability(_arr(0.05), _arr(-0.01), _arr(0.02))
    assert expected_value(p_be, _arr(0.05), _arr(0.01), _arr(0.02)) == pytest.approx(0.0, abs=1e-12)
    # no payoff to break even on: NaN, never a signal
    assert np.isnan(breakeven_probability(_arr(0.0), _arr(0.0), _arr(0.02))).all()
    assert np.isnan(breakeven_probability(_arr(-0.02), _arr(0.01), _arr(0.02))).all()


# --- threshold selection and tiers ------------------------------------------------------------


def test_minimum_probability_is_breakeven_plus_margin_but_never_below_the_floor():
    p_be = _arr(0.20, 0.45, np.nan)
    out = minimum_probability(p_be, T.margin, T.p_floor)
    assert out[0] == pytest.approx(T.p_floor)  # 0.25 < floor 0.35
    assert out[1] == pytest.approx(0.45 + T.margin)
    assert np.isnan(out[2])
    bumped = minimum_probability(p_be, T.margin, T.p_floor, 0.05)
    assert bumped[:2] == pytest.approx(out[:2] + 0.05)  # defensive mode raises the bar


def _decide(p: float, *, e_win=0.12, e_loss=-0.01, cost=0.0175, n=500.0, recent_acc=0.8, **kw):
    ones = np.ones(1)
    return decide(
        _arr(p),
        e_win * ones,
        e_loss * ones,
        cost * ones,
        n * ones,
        100.0 * ones,
        recent_acc * ones,
        thresholds=T,
        model=CFG.model,
        **kw,
    )


def test_signal_needs_probability_ev_and_a_populated_bucket():
    assert _decide(0.40).signal[0]
    assert not _decide(0.30).signal[0]  # below the 0.35 floor
    assert not _decide(0.40, n=T.min_bucket_samples - 1).signal[0]  # thin bucket
    assert _decide(0.40, n=T.min_bucket_samples).signal[0]
    # p >= p_min but EV under 0.5%: W + L = 0.04 makes p_min ~0.74 and EV ~0.2% there
    thin = _decide(0.745, e_win=0.03)
    assert thin.p_min[0] < 0.745 and thin.ev[0] < T.ev_min_abs and not thin.signal[0]
    assert not _decide(0.99, e_win=0.0, e_loss=0.0).signal[0]  # no payoff: NaN thresholds


def test_tiers_are_offsets_above_the_breakeven_probability():
    d = _decide(0.40, allow_tier_a=True)
    be = d.p_breakeven[0]
    assert be + T.tiers.A.p_win_margin <= 0.40 and d.tier[0] == "A"
    assert _decide(0.40).tier[0] == "B"  # tier A not allowed: stays B, but eligible
    assert _decide(0.40).tier_a_eligible[0]
    # recent accuracy under p_breakeven + 0.08 blocks tier A
    assert (
        _decide(
            0.40, recent_acc=be + T.tiers.A.recent_bucket_accuracy_margin - 0.01, allow_tier_a=True
        ).tier[0]
        == "B"
    )
    # a 1:1 payoff with 1.75% costs puts p_breakeven at (0.02 + 0.0175) / 0.04, so p = 0.62 loses
    even = _decide(0.62, e_win=0.02, e_loss=-0.02, allow_tier_a=True)
    assert even.p_breakeven[0] == pytest.approx((0.02 + 0.0175) / 0.04)
    assert even.tier[0] == "C" and not even.signal[0]


# --- calibration split ------------------------------------------------------------------------


def _window(n_days: int = 200, horizon: int = 3) -> pl.DataFrame:
    days = [date(2024, 1, 1) + timedelta(days=i) for i in range(n_days)]
    return pl.DataFrame(
        {
            "instrument_id": [1] * n_days,
            "date": days,
            "exit_date": [days[min(i + horizon, n_days - 1)] for i in range(n_days)],
            "i": list(range(n_days)),
        }
    )


def test_split_is_chronological_purged_and_never_overlaps():
    w = _window()
    sp = split_training_window(w, CFG.model)
    assert sp is not None
    # each part is resolved before the next one begins: no label uses a later part's prices
    assert sp.fit["exit_date"].max() < sp.es_start
    assert sp.es["exit_date"].max() < sp.cal_a_start
    assert sp.cal_a["exit_date"].max() < sp.cal_b_start
    # chronological order, no row in two parts
    assert (
        sp.fit["date"].max() < sp.es["date"].min() <= sp.es["date"].max() < sp.cal_a["date"].min()
    )
    assert sp.cal_a["date"].max() < sp.cal_b["date"].min()
    seen = pl.concat([sp.fit, sp.es, sp.cal_a, sp.cal_b])["i"]
    assert seen.n_unique() == seen.len()
    # cal_b (bucket statistics) is the newest part, so it never saw the trees or the isotonic map
    assert sp.cal_b["date"].max() == w["date"].max()
    assert sp.calibration.height == sp.cal_a.height + sp.cal_b.height
    assert sp.cal_a_start <= sp.recent_cut or sp.recent_cut >= sp.es_start


def test_split_needs_enough_history():
    assert split_training_window(_window(20), CFG.model) is None


@pytest.fixture(scope="module")
def market_ds():
    prices, clients, sectors = make_market(700, 30, seed=11, edge=0.03)
    ds = prepare_dataset(prices, clients, RULES, sectors=sectors)
    return prices, ds


def test_isotonic_and_buckets_come_from_different_slices(market_ds):
    _, ds = market_ds
    train = ds.filter(pl.col("trainable") & (pl.col("date") <= ds["date"].unique().sort()[480]))
    m = LightGBMStrategy(RULES)
    m.fit(train)
    assert m.info["usable"]
    assert m.info["n_cal_a"] > 0 and m.info["n_cal_b"] > 0
    # the bucket statistics describe exactly the cal_b rows, not the isotonic slice
    assert m.buckets is not None and m.buckets.n.sum() == m.info["n_cal_b"]
    assert m.info["cal_start"] < m.info["cal_b_start"]


# --- nested grid ------------------------------------------------------------------------------


class _PickBest:
    """Chooses the pair with the highest mean realised return in its *training* rows and records
    what it was allowed to see."""

    name = "pick_best"

    def __init__(self) -> None:
        self.info: dict = {}

    def fit(self, train: pl.DataFrame) -> None:
        return None

    def fit_grid(self, combos, train_for):
        best, best_score = None, -np.inf
        for combo in combos:
            tr = train_for(combo)
            assert tr["trainable"].all()
            score = float(tr["realized_return"].mean())
            if score > best_score:
                best, best_score = combo, score
        self.info = {"n_train_rows": 1, "grid_selected_by_score": True, "grid": []}
        return best

    def predict(self, test: pl.DataFrame) -> pl.DataFrame:
        return test.select(
            "instrument_id", "date", pl.lit(True).alias("signal"), pl.lit(0.0).alias("score")
        )


def _small_cfg():
    return CFG.model_copy(
        update={
            "validation": CFG.validation.model_copy(
                update={"min_train_days": 150, "retrain_every_days": 60}
            )
        }
    )


def test_grid_selection_never_touches_the_test_fold(market_ds):
    prices, ds = market_ds
    cfg = _small_cfg()
    sets = prepare_label_sets(prices, RULES, cfg=cfg)
    assert list(sets) == grid_combos("D1", cfg) and len(sets) == 6  # 3 k_tp x 2 k_sl

    base = run_walk_forward(ds, _PickBest, cfg=cfg, label_sets=sets)
    assert len(base.folds) >= 2 and len(base.fold_infos) == len(base.folds)

    # poison every label that resolves on or after the first test start, for the pair that loses
    # in training; a selector that peeked at the test period would now switch to it
    first = base.folds[0]
    chosen = (base.fold_infos[0]["k_tp"], base.fold_infos[0]["k_sl"])
    victim = next(c for c in sets if c != chosen)
    poisoned = dict(sets)
    poisoned[victim] = sets[victim].with_columns(
        pl.when(pl.col("exit_date") >= first.test_start)
        .then(pl.lit(5.0))
        .otherwise(pl.col("realized_return"))
        .alias("realized_return")
    )
    again = run_walk_forward(ds, _PickBest, cfg=cfg, label_sets=poisoned)
    pair = lambda r: (r.fold_infos[0]["k_tp"], r.fold_infos[0]["k_sl"])  # noqa: E731
    assert pair(again) == pair(base)  # fold 0 chose from its training window only

    # every training row of every pair is resolved before the test start and not after the cutoff
    for fold in base.folds:
        window = ds.filter(pl.col("in_universe") & (pl.col("date") <= fold.train_cutoff))
        for lab in sets.values():
            tr = with_labels(window, lab).filter(
                pl.col("trainable") & (pl.col("exit_date") < fold.test_start)
            )
            assert tr.is_empty() or tr["exit_date"].max() < fold.test_start

    # the test rows carry the labels of the pair the fold chose
    row = base.predictions.filter(pl.col("fold") == 0).row(0, named=True)
    assert (row["k_tp"], row["k_sl"]) == chosen
    expect = sets[chosen].filter(
        (pl.col("instrument_id") == row["instrument_id"]) & (pl.col("date") == row["date"])
    )
    assert expect["y"][0] == row["y"]


def test_folds_embargo_the_horizon():
    dates = [date(2024, 1, 1) + timedelta(days=i) for i in range(400)]
    folds = make_folds(dates, horizon=3, embargo=3, retrain_every=20, min_train_days=250)
    for f in folds:
        assert dates.index(f.test_start) - dates.index(f.train_cutoff) >= 4
