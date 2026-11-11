"""M4: the LightGBM strategy, calibration, EV/threshold arithmetic, SHAP, portfolio filters,
the Tier-A gate and the publishing service."""

from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import polars as pl
import pytest
from sklearn.metrics import roc_auc_score
from sqlalchemy import select

from tmon.backtest.costs import round_trip_expr
from tmon.backtest.runner import prepare_dataset
from tmon.backtest.synthetic import make_market
from tmon.core.engine_config import get_engine_config
from tmon.engine.defensive import defensive_flags
from tmon.engine.gating import brier_degraded, evaluate_gate
from tmon.engine.portfolio import select_portfolio
from tmon.engine.service import train_and_publish
from tmon.features.builder import get_feature_set
from tmon.models.explain import contributions, top_reasons
from tmon.models.lgbm import BucketTable, LightGBMStrategy, _matrix, build_buckets
from tmon.storage.models import ModelRun, Signal, SignalNote
from tmon.storage.objectstore import MemoryStore
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


# --- portfolio constraints -------------------------------------------------------------------


def _returns(n_days: int, series: dict[int, np.ndarray]) -> pl.DataFrame:
    days = [date(2025, 1, 1) + timedelta(days=i) for i in range(n_days)]
    return pl.DataFrame(
        {
            "instrument_id": [i for i, s in series.items() for _ in s],
            "date": [d for s in series.values() for d in days[: len(s)]],
            "ret_1": [v for s in series.values() for v in s],
        }
    )


def _cands(rows: list[tuple[int, float, float, str, float]]) -> pl.DataFrame:
    return pl.DataFrame(
        rows,
        schema=["instrument_id", "ev", "weight", "sector_code", "median_value_20"],
        orient="row",
    )


CAPITAL = 1e9
BIG = 1e12  # liquid enough that the liquidity cap never binds


def test_correlated_candidate_with_lower_ev_is_dropped():
    rng = np.random.default_rng(0)
    base = rng.normal(size=60)
    rets = _returns(60, {1: base, 2: base + rng.normal(size=60) * 0.01, 3: rng.normal(size=60)})
    cands = _cands(
        [(1, 0.05, 0.05, "a", BIG), (2, 0.04, 0.05, "b", BIG), (3, 0.03, 0.05, "c", BIG)]
    )
    sel, dropped = select_portfolio(cands, rets, capital=CAPITAL)
    assert sel["instrument_id"].to_list() == [1, 3]
    assert dropped["instrument_id"].to_list() == [2] and dropped["reason"][0] == "correlation"


def test_sector_cap_trims_and_then_drops():
    rng = np.random.default_rng(1)
    rets = _returns(60, {i: rng.normal(size=60) for i in (1, 2, 3, 4)})
    cands = _cands([(i, 0.1 - i / 100, 0.10, "same", BIG) for i in (1, 2, 3, 4)])
    sel, dropped = select_portfolio(cands, rets, capital=CAPITAL, max_positions=10)
    cap = CFG.sizing.sector_cap_pct
    assert sel["position_pct"].sum() == pytest.approx(cap)  # 0.10 + 0.10 + 0.05 trimmed
    assert sel["position_pct"].to_list()[-1] == pytest.approx(cap - 0.2)
    assert dropped["reason"].to_list() == ["sector_cap"]


def test_liquidity_cap_limits_position_size():
    rng = np.random.default_rng(2)
    rets = _returns(60, {1: rng.normal(size=60)})
    # 5% of a 10bn median value is 500m = 50% of 1bn capital -> weight stays; 1bn median -> 5%
    thin = _cands([(1, 0.05, 0.10, "a", 1e9)])
    sel, _ = select_portfolio(thin, rets, capital=CAPITAL)
    assert sel["position_pct"][0] == pytest.approx(
        CFG.sizing.liquidity_cap_of_median_value * 1e9 / CAPITAL
    )


def test_illiquid_candidate_is_dropped_and_positions_are_limited():
    rng = np.random.default_rng(3)
    rets = _returns(60, {i: rng.normal(size=60) for i in range(1, 9)})
    cands = _cands(
        [(i, 0.2 - i / 100, 0.02, f"s{i}", BIG) for i in range(1, 8)] + [(8, 0.0, 0.05, "z", 0.0)]
    )
    sel, dropped = select_portfolio(cands, rets, capital=CAPITAL)
    assert sel.height == CFG.backtest.max_new_positions_per_day
    reasons = dict(
        zip(dropped["instrument_id"].to_list(), dropped["reason"].to_list(), strict=True)
    )
    assert reasons[8] == "liquidity" and reasons[6] == "max_positions"
    assert sel["rank"].to_list() == list(range(1, sel.height + 1))


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


# --- service ------------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def market():
    return make_market(700, 30, seed=11, edge=0.03)


def test_service_publishes_nothing_honestly_when_thresholds_are_not_met(session, market):
    store = MemoryStore()
    res = train_and_publish(session, store, inputs=market, rules=RULES)
    session.commit()
    assert res.n_recommended == 0 and "توصیه‌ای" in res.message
    assert session.scalars(select(Signal)).all() == []
    note = session.scalars(select(SignalNote)).one()
    assert note.n_recommended == 0 and note.date == res.as_of
    assert res.gate is not None and not res.gate.tier_a_allowed and res.gate.reasons
    assert any(k[1].endswith(".parquet") for k in store.objects)  # snapshot stored


def test_service_persists_signals_with_levels_reasons_and_snapshot(session, market):
    loose = CFG.model_copy(
        update={
            "thresholds": CFG.thresholds.model_copy(
                update={
                    "margin": -1.0,
                    "p_floor": 0.15,
                    "ev_min_abs": 0.0,
                    "min_bucket_samples": 20,
                }
            )
        }
    )
    store = MemoryStore()
    res = train_and_publish(session, store, inputs=market, rules=RULES, cfg=loose)
    session.commit()
    rows = session.scalars(select(Signal).order_by(Signal.rank)).all()
    if not rows:
        pytest.skip("this seed produced no EV-positive candidate on the last day")
    assert len(rows) == res.n_recommended <= CFG.backtest.max_new_positions_per_day
    for s in rows:
        assert s.stop_loss < s.entry_price < s.take_profit
        assert s.horizon_days == 3 and s.entry_rule == "open_next_day"
        assert 0 < s.position_pct <= CFG.sizing.max_position_pct
        assert len(s.top_reasons) == 5 and "feature" in s.top_reasons[0]
        assert s.confidence_tier in {"A", "B", "C"}
        assert s.confidence_tier != "A"  # gate closed: no tier A without beating the baseline
        assert s.data_snapshot_id == res.data_snapshot_id and s.model_version == res.model_version
    assert [s.rank for s in rows] == list(range(1, len(rows) + 1))
    assert [s.ev for s in rows] == sorted((s.ev for s in rows), reverse=True)
    run = session.scalars(select(ModelRun)).one()
    assert run.version == res.model_version and run.metrics["gate"]["tier_a_allowed"] is False
    assert run.artifact_uri in {k[1] for k in store.objects}


def test_service_is_idempotent_for_the_same_day(session, market):
    store = MemoryStore()
    a = train_and_publish(session, store, inputs=market, rules=RULES)
    b = train_and_publish(session, store, inputs=market, rules=RULES)
    session.commit()
    assert a.model_version == b.model_version  # deterministic training, same snapshot
    assert len(session.scalars(select(SignalNote)).all()) == 1
    assert len(session.scalars(select(ModelRun)).all()) == 1


def test_service_with_no_prices_says_so(session):
    empty = pl.DataFrame(schema={"instrument_id": pl.Int64, "date": pl.Date})
    res = train_and_publish(session, MemoryStore(), inputs=(empty, empty, empty), rules=RULES)
    assert res.as_of is None and res.n_recommended == 0 and res.message


def test_later_run_resolves_earlier_pending_signals(session, market):
    """Regression: resolving outcomes must UPDATE existing signals (a partial-row upsert violates
    the NOT NULL constraints)."""
    prices, clients, sectors = market
    loose = CFG.model_copy(
        update={
            "thresholds": CFG.thresholds.model_copy(
                update={
                    "margin": -1.0,
                    "p_floor": 0.15,
                    "ev_min_abs": 0.0,
                    "min_bucket_samples": 20,
                }
            )
        }
    )
    dates = prices["date"].unique().sort().to_list()
    for d in (dates[-12], dates[-1]):
        cut = (prices.filter(pl.col("date") <= d), clients.filter(pl.col("date") <= d), sectors)
        train_and_publish(session, MemoryStore(), inputs=cut, rules=RULES, cfg=loose)
        session.commit()
    rows = session.scalars(select(Signal).where(Signal.date == dates[-12])).all()
    if not rows:
        pytest.skip("this seed produced no candidate on the earlier day")
    assert any(s.outcome != "pending" and s.outcome_date is not None for s in rows)


@pytest.mark.parametrize("timeframe", ["W1", "M1"])
def test_weekly_and_monthly_models_train_and_publish_on_their_own_horizon(session, timeframe):
    # 900 days leave room for the 60-day M1 horizon, its embargo and several walk-forward folds.
    market = make_market(900, 30, seed=13, edge=0.03)
    loose = CFG.model_copy(
        update={
            "thresholds": CFG.thresholds.model_copy(
                update={
                    "margin": -1.0,
                    "p_floor": 0.0,
                    "ev_min_abs": -1.0,
                    "min_bucket_samples": 20,
                }
            )
        }
    )
    res = train_and_publish(
        session, MemoryStore(), inputs=market, rules=RULES, cfg=loose, timeframe=timeframe
    )
    session.commit()
    assert res.model_version and res.model_version.startswith(f"lgbm-{timeframe.lower()}-")
    run = session.scalars(select(ModelRun).where(ModelRun.timeframe == timeframe)).one()
    assert run.feature_set_version.startswith(f"{timeframe}_v1_")
    note = session.scalars(select(SignalNote).where(SignalNote.timeframe == timeframe)).one()
    assert note.date == res.as_of
    horizon = CFG.labeling.timeframes[timeframe].horizon_days
    for s in session.scalars(select(Signal).where(Signal.timeframe == timeframe)):
        assert s.horizon_days == horizon
        assert s.stop_loss < s.entry_price < s.take_profit
