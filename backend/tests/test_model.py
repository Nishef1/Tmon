"""M4: the LightGBM strategy, calibration, EV/threshold arithmetic, SHAP and
the Tier-A gate."""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import polars as pl
import pytest
from sklearn.metrics import roc_auc_score

from tmon.backtest.costs import round_trip_expr
from tmon.backtest.runner import prepare_dataset
from tmon.backtest.synthetic import make_market
from tmon.core.engine_config import get_engine_config
from tmon.engine.defensive import defensive_flags
from tmon.engine.gating import brier_degraded, evaluate_gate
from tmon.features.builder import get_feature_set
from tmon.models.explain import contributions, top_reasons
from tmon.models.lgbm import BucketTable, LightGBMStrategy, _matrix, build_buckets
from tmon.storage.seed import seed_rulebook

RULES = seed_rulebook()
CFG = get_engine_config()


def _split(ds: pl.DataFrame, train_end: int = 480, gap: int = 5, test_days: int = 40):
    dates = ds["date"].unique().sort().to_list()
    train = ds.filter(
        pl.col("trainable")
        & (pl.col("date") <= dates[train_end])
        & (pl.col("exit_date") < dates[train_end + gap])
    )
    test = ds.filter(
        pl.col("in_universe")
        & pl.col("valid")
        & (pl.col("date") >= dates[train_end + gap])
        & (pl.col("date") <= dates[train_end + gap + test_days])
    )
    return train, test


@pytest.fixture(scope="module")
def edge_ds():
    prices, clients, sectors = make_market(700, 30, seed=11, edge=0.03)
    return prepare_dataset(prices, clients, RULES, sectors=sectors)


@pytest.fixture(scope="module")
def walk_ds():
    prices, clients, sectors = make_market(700, 30, seed=11, edge=0.0)
    return prepare_dataset(prices, clients, RULES, sectors=sectors)


@pytest.fixture(scope="module")
def fitted(edge_ds):
    train, test = _split(edge_ds)
    m = LightGBMStrategy(RULES, enforce_thresholds=False)
    m.fit(train)
    return m, train, test


# --- learning -------------------------------------------------------------------------------


def test_model_learns_a_planted_edge_out_of_sample(fitted):
    m, _, test = fitted
    assert m.info["usable"]
    _, p = m.predict_proba(test)
    assert roc_auc_score(test["y"].to_numpy(), p) > 0.6


def test_model_finds_nothing_on_a_random_walk(walk_ds):
    train, test = _split(walk_ds)
    m = LightGBMStrategy(RULES)
    m.fit(train)
    if m.info.get("usable"):
        _, p = m.predict_proba(test)
        assert 0.42 < roc_auc_score(test["y"].to_numpy(), p) < 0.58
    # and the production thresholds publish no signal on a market with no edge
    assert not m.predict(test)["signal"].any()


def test_calibration_map_is_monotone_and_probabilities_valid(fitted):
    m, _, test = fitted
    assert np.all(np.diff(m.cal_y) >= -1e-12)
    raw, p = m.predict_proba(test)
    assert p.min() >= 0 and p.max() <= 1
    order = np.argsort(raw)
    assert np.all(np.diff(p[order]) >= -1e-12)  # a higher raw score never lowers the probability


def test_walk_forward_split_never_trains_on_the_calibration_window(edge_ds):
    """Trees are fitted on rows resolved before the early-stopping window starts."""
    train, _ = _split(edge_ds)
    m = LightGBMStrategy(RULES)
    m.fit(train)
    es_cut = train["date"].unique().sort()[int(m.info["n_days"] * (1 - 0.2 - 0.15))]
    assert m.info["n_fit"] <= train.filter(pl.col("exit_date") < es_cut).height


def test_artifact_round_trip_predicts_identically(fitted):
    m, _, test = fitted
    twin = LightGBMStrategy.from_bytes(m.to_bytes(), RULES, enforce_thresholds=False)
    a = m.predict(test).sort("instrument_id", "date")
    b = twin.predict(test).sort("instrument_id", "date")
    assert np.allclose(a["p_win"].to_numpy(), b["p_win"].to_numpy())
    assert np.allclose(a["ev"].to_numpy(), b["ev"].to_numpy(), equal_nan=True)


# --- EV, thresholds, tiers, sizing (stubbed probabilities) --------------------------------------


class StubModel(LightGBMStrategy):
    """Fixed probabilities so the decision arithmetic is tested without a fitted booster."""

    def __init__(self, p: list[float], **kw):
        super().__init__(RULES, **kw)
        self._p = np.array(p)
        self.booster = object()  # type: ignore[assignment]  # only checked for None
        n = 10
        self.buckets = BucketTable(
            edges=np.linspace(0, 1, n + 1),
            n=np.full(n, 500.0),
            accuracy=np.linspace(0.05, 0.95, n),
            e_win=np.full(n, 0.12),
            e_loss=np.full(n, -0.01),
            recent_n=np.full(n, 100.0),
            recent_accuracy=np.full(n, 0.8),
        )

    def predict_proba(self, df):
        return self._p, self._p


def _frame(n: int, defensive: bool = False) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "instrument_id": list(range(1, n + 1)),
            "date": [date(2025, 6, 1)] * n,
            "atr_14_pct": [0.02] * n,
            "defensive": [defensive] * n,
        }
    )


def test_ev_matches_the_formula_and_costs_come_from_rules():
    p = [0.65, 0.75]
    out = StubModel(p).predict(_frame(2))
    cost = _cost()
    for pi, ev in zip(p, out["ev"], strict=True):
        assert ev == pytest.approx(pi * 0.12 + (1 - pi) * -0.01 - cost)
    assert out["round_trip_cost"][0] == pytest.approx(cost)


def _cost() -> float:
    return pl.DataFrame({"date": [date(2025, 6, 1)]}).select(
        round_trip_expr(RULES, CFG.costs.slippage_fraction).alias("c")
    )["c"][0]


def test_thresholds_and_tiers():
    out = StubModel([0.30, 0.36, 0.65, 0.99], allow_tier_a=True).predict(_frame(4))
    # p_breakeven + 0.05 is ~0.26 here, so the 0.35 floor binds: p < 0.35 is never a signal
    assert out["p_min"].to_list() == pytest.approx([CFG.thresholds.p_floor] * 4)
    assert out["signal"].to_list() == [False, True, True, True]
    assert out["tier"].to_list() == ["C", "A", "A", "A"]  # all clear p_breakeven + 0.12


def test_tier_a_needs_explicit_permission():
    out = StubModel([0.75], allow_tier_a=False).predict(_frame(1))
    assert out["tier"][0] == "B" and out["tier_a_eligible"][0]  # eligible, but not allowed


def test_tier_a_needs_recent_accuracy():
    m = StubModel([0.75], allow_tier_a=True)
    m.buckets.recent_accuracy[:] = 0.2  # below p_breakeven + 0.08 (~0.29)
    assert m.predict(_frame(1))["tier"][0] == "B"


def test_thin_buckets_block_signals():
    m = StubModel([0.75])
    m.buckets.n[:] = 199
    assert not m.predict(_frame(1))["signal"][0]


def test_defensive_mode_raises_the_bar_by_the_configured_bump():
    bump = CFG.defensive_mode.p_min_bump
    p = CFG.thresholds.p_floor + bump / 2  # passes normally, not when defensive
    assert StubModel([p]).predict(_frame(1, defensive=False))["signal"][0]
    assert not StubModel([p]).predict(_frame(1, defensive=True))["signal"][0]


def test_ev_must_clear_the_absolute_floor_even_above_p_min():
    m = StubModel([0.745])
    m.buckets.e_win[:] = 0.03  # W + L = 0.04: p_min ~0.74 is met, but EV ~0.2% < 0.5%
    out = m.predict(_frame(1))
    assert out["p_win"][0] >= out["p_min"][0]
    assert not out["signal"][0] and out["ev"][0] < CFG.thresholds.ev_min_abs


def test_kelly_sizing_is_fractional_and_capped():
    m = StubModel([0.75])
    out = m.predict(_frame(1))
    b = 0.12 / 0.01
    kelly = 0.75 - 0.25 / b
    expected = min(
        CFG.sizing.kelly_fraction * kelly,
        CFG.sizing.max_position_pct,
        CFG.sizing.risk_per_trade / (m.barrier[1] * 0.02),
    )
    assert out["weight"][0] == pytest.approx(expected)
    assert 0 < out["weight"][0] <= CFG.sizing.max_position_pct


def test_buckets_borrow_pooled_means_when_a_bucket_is_empty():
    p = np.array([0.1, 0.1, 0.9, 0.9])
    y = np.array([0, 1, 1, 1])
    ret = np.array([-0.01, 0.05, 0.04, 0.06])
    bk = build_buckets(p, y, ret, np.ones(4, dtype=bool), 10)
    assert bk.n[1] == 2 and bk.n[9] == 2 and bk.n[5] == 0
    assert bk.e_win[5] == pytest.approx(0.05) and bk.e_loss[5] == pytest.approx(-0.01)


# --- defensive flag ---------------------------------------------------------------------------


def test_defensive_flag_from_breadth_and_three_negative_flow_days():
    d0 = date(2025, 1, 1)
    days = [d0 + timedelta(days=i) for i in range(6)]
    ds = pl.DataFrame(
        {
            "date": days,
            "breadth": [0.6, 0.6, 0.6, 0.6, 0.2, 0.6],
            "mkt_ind_net_flow": [1.0, -1.0, -1.0, -1.0, 1.0, 1.0],
        }
    )
    flags = defensive_flags(ds)["defensive"].to_list()
    assert flags == [False, False, False, True, True, False]  # 3rd negative day; low breadth day


def test_defensive_mode_can_be_switched_off():
    cfg = CFG.model_copy(
        update={"defensive_mode": CFG.defensive_mode.model_copy(update={"enabled": False})}
    )
    ds = pl.DataFrame({"date": [date(2025, 1, 1)], "breadth": [0.0], "mkt_ind_net_flow": [-1.0]})
    assert not defensive_flags(ds, cfg)["defensive"][0]


# --- SHAP ---------------------------------------------------------------------------------------


def test_top_reasons_are_the_five_strongest_contributions(fitted):
    m, _, test = fitted
    x = _matrix(test.head(6), m.features)
    reasons = top_reasons(m.booster, x, m.features, 5)
    assert len(reasons) == 6 and all(len(r) == 5 for r in reasons)
    c = contributions(m.booster, x)
    for row, r in zip(c, reasons, strict=True):
        mags = [abs(e["contribution"]) for e in r]
        assert mags == sorted(mags, reverse=True)
        assert mags[0] == pytest.approx(np.abs(row).max())
        assert {e["feature"] for e in r} <= set(get_feature_set("D1").columns)


# --- gate ---------------------------------------------------------------------------------------


def _summary(n=500, exp=0.01, tr=0.3, skill=0.05):
    s = {"trades": {"n_trades": n, "expectancy_net": exp}, "portfolio": {"total_return": tr}}
    if skill is not None:
        s["probabilistic"] = {"brier_skill": skill}
    return s


def test_gate_opens_only_when_the_model_beats_the_baseline_after_costs():
    base = _summary(n=300, exp=0.002, tr=0.1, skill=None)
    assert evaluate_gate(_summary(), base).tier_a_allowed
    assert not evaluate_gate(_summary(exp=0.001), base).tier_a_allowed  # worse than baseline
    assert not evaluate_gate(_summary(tr=0.05), base).tier_a_allowed  # lower total return
    assert not evaluate_gate(_summary(exp=-0.001, tr=0.5), base).tier_a_allowed  # not positive
    assert not evaluate_gate(_summary(n=10), base).tier_a_allowed  # too few trades
    assert not evaluate_gate(_summary(skill=-0.01), base).tier_a_allowed  # worse than base rate


def test_gate_closed_for_a_model_with_no_trades_and_it_says_why():
    g = evaluate_gate({"trades": {"n_trades": 0}, "portfolio": {}}, _summary())
    assert not g.tier_a_allowed and len(g.reasons) >= 2


def test_brier_monitor_trips_at_twenty_percent_degradation():
    y = np.array([1.0, 0.0, 0.0, 0.0])
    p = np.array([0.3, 0.3, 0.3, 0.3])
    b = float(np.mean((p - y) ** 2))
    assert not brier_degraded(p, y, b * 0.95 + 1e-9)  # within tolerance
    assert brier_degraded(p, y, b / 1.3)  # recent is 30% worse than the backtest
