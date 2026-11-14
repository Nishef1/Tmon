"""The living ranking: the gate, the champion choice, causality and the weights the product may use."""

from __future__ import annotations

import datetime as dt

import numpy as np
import polars as pl
import pytest

from tmon.backtest.walkforward_study import BASE, CANDS, HORIZONS, STATE, WARMUP, Panel
from tmon.core.engine_config import AdaptCfg
from tmon.engine import adapt

CFG = AdaptCfg(
    window_dates=200,
    min_half_dates=60,
    min_t=2.0,
    switch_margin_t=1.0,
    history_keep=5,
    replay_every_dates=21,
    candidates=("ridge4_x120", "icw_x250"),
)
RT = 0.0175


def _series(n: int, mean: float, sd: float = 0.05, seed: int = 1) -> np.ndarray:
    return np.random.default_rng(seed).normal(mean, sd, n)


def test_gate_passes_a_steady_gain_that_beats_the_cost() -> None:
    n = 200
    eq = _series(n, 0.05, seed=1)
    cand = eq + _series(n, 0.03, sd=0.02, seed=2)
    ex_eq = np.full(n, 0.02)
    v = adapt.gate(cand, eq, ex_eq + 0.01, ex_eq, 5, CFG, RT)
    assert v.passed and not v.reasons
    assert v.d_ic is not None and v.d_ic > 0 and v.t is not None and v.t >= 2


def test_gate_rejects_a_gain_that_is_only_in_one_half() -> None:
    n = 200
    eq = _series(n, 0.05, seed=3)
    gain = np.concatenate([np.full(100, 0.08), np.full(100, -0.005)])
    v = adapt.gate(eq + gain, eq, np.full(n, 0.05), np.full(n, 0.02), 1, CFG, RT)
    assert not v.passed and adapt.R_HALVES in v.reasons


def test_gate_rejects_an_edge_smaller_than_the_round_trip_cost() -> None:
    n = 200
    eq = _series(n, 0.05, seed=4)
    cand = eq + 0.03
    v = adapt.gate(cand, eq, np.full(n, 0.01), np.full(n, 0.005), 5, CFG, RT)
    assert not v.passed and v.reasons == (adapt.R_COST,)


def test_gate_refuses_to_judge_a_thin_window() -> None:
    v = adapt.gate(np.zeros(50), np.zeros(50), np.zeros(50), np.zeros(50), 1, CFG, RT)
    assert not v.passed and v.reasons == (adapt.NOT_ENOUGH,)


def _v(t: float | None, passed: bool = True) -> adapt.Verdict:
    return adapt.Verdict(passed=passed, reasons=() if passed else ("x",), n=300, t=t)


def test_equal_weights_stay_when_nobody_passes() -> None:
    name, _ = adapt.choose({"a": _v(3.0, False), "b": _v(None, False)}, "a", 1.0)
    assert name == adapt.EQUAL


def test_best_passing_candidate_wins_and_the_champion_is_sticky() -> None:
    assert adapt.choose({"a": _v(2.5), "b": _v(3.5)}, None, 1.0)[0] == "b"
    # a is sitting and still passes; b is better by less than the margin: a stays
    assert adapt.choose({"a": _v(2.5), "b": _v(3.0)}, "a", 1.0)[0] == "a"
    # b beats a by more than the margin: switch
    assert adapt.choose({"a": _v(2.5), "b": _v(4.0)}, "a", 1.0)[0] == "b"
    # the sitting champion fell out of the gate: it is dropped even if nobody is better
    assert adapt.choose({"a": _v(2.5, False), "b": _v(2.2)}, "a", 1.0)[0] == "b"


def test_weights_for_defaults_to_equal_and_only_adopts_production_expressible() -> None:
    eq = {s: 1 / len(BASE) for s in BASE}
    assert adapt.weights_for(None, 20) == eq
    state = {
        "horizons": {
            "20": {
                "champion": "ridge4_x120",
                "production_expressible": True,
                "weights": {BASE[0]: 0.7, BASE[1]: 0.3},
            },
            "60": {"champion": "gbm", "production_expressible": False, "weights": {}},
            "5": {"champion": "equal", "production_expressible": True, "weights": {}},
        }
    }
    w = adapt.weights_for(state, 20)
    assert w[BASE[0]] == pytest.approx(0.7) and w[BASE[2]] == 0.0
    assert adapt.weights_for(state, 60) == eq  # shadow-only champion never reaches the product
    assert adapt.weights_for(state, 5) == eq
    assert adapt.weights_for(state, 120) == eq  # horizon absent


def _synthetic_panel(days: int, names: int, edge: float, seed: int = 0) -> Panel:
    """Ranks of the candidates; signal 0 predicts the later returns with strength ``edge``."""
    rng = np.random.default_rng(seed)
    rows: list[dict[str, object]] = []
    d0 = dt.date(2020, 1, 1)
    for t in range(days):
        x = rng.random((names, len(CANDS))) - 0.5
        latent = edge * x[:, 0] + rng.normal(0, 1, names)
        base = {f"y_{h}": (latent.argsort().argsort() + 0.5) / names - 0.5 for h in HORIZONS}
        fwd = {f"fwd_{h}": latent * 0.02 for h in HORIZONS}
        state = rng.normal(0, 1, len(STATE))
        for i in range(names):
            row: dict[str, object] = {"date": d0 + dt.timedelta(days=t), "instrument_id": i}
            row |= {f"r_{c}": float(x[i, k]) for k, c in enumerate(CANDS)}
            row |= {k: float(v[i]) for k, v in base.items()} | {
                k: float(v[i]) for k, v in fwd.items()
            }
            row |= {s: float(state[j]) for j, s in enumerate(STATE)}
            rows.append(row)
    df = pl.DataFrame(rows)
    # the last `h` dates have no outcome yet, as in real data
    return Panel(_mask_unlabeled(df, days))


def _mask_unlabeled(df: pl.DataFrame, days: int) -> pl.DataFrame:
    dates = sorted(df["date"].unique().to_list())
    out = df
    for h in HORIZONS:
        cut = dates[days - h] if h < days else dates[0]
        out = out.with_columns(
            pl.when(pl.col("date") >= cut).then(None).otherwise(pl.col(f"y_{h}")).alias(f"y_{h}"),
            pl.when(pl.col("date") >= cut)
            .then(None)
            .otherwise(pl.col(f"fwd_{h}"))
            .alias(f"fwd_{h}"),
        )
    return out


@pytest.fixture(scope="module")
def panel() -> Panel:
    return _synthetic_panel(WARMUP + 330, 60, edge=0.0)


def test_cycle_on_pure_noise_keeps_equal_weights_everywhere(panel: Panel) -> None:
    state = adapt.run_cycle(panel, CFG, RT, None)
    assert state["as_of"] == str(panel.dates[-1])
    for h in HORIZONS:
        cell = state["horizons"][str(h)]
        assert cell["champion"] == adapt.EQUAL
        assert cell["live_scores"] is None
        assert cell["weights"] == {s: pytest.approx(0.25) for s in BASE}
        assert set(cell["candidates"]) == set(CFG.candidates)
    assert state["drift"]["20"]["series"][BASE[0]]  # the weight drift is reported
    assert state["history"][-1]["champions"] == {str(h): adapt.EQUAL for h in HORIZONS}


def test_cycle_history_keeps_the_previous_cycles_and_replaces_the_same_day(panel: Panel) -> None:
    first = adapt.run_cycle(panel, CFG, RT, None)
    old = {"as_of": "2000-01-01", "champions": {"20": "x"}}
    again = adapt.run_cycle(panel, CFG, RT, first | {"history": [old, *first["history"]]})
    assert [r["as_of"] for r in again["history"]] == ["2000-01-01", first["as_of"]]


def test_a_future_label_never_reaches_the_choice(panel: Panel) -> None:
    """Replacing every outcome the cycle may not know with noise changes nothing it reports."""
    p2 = _synthetic_panel(WARMUP + 330, 60, edge=0.0)
    a = adapt.run_cycle(panel, CFG, RT, None)
    for hi, h in enumerate(HORIZONS):
        for t in range(p2.D - h, p2.D):  # outcomes still unknown on the last date
            p2.Y[t][:, hi] = np.random.default_rng(t).random(p2.Y[t].shape[0])
    b = adapt.run_cycle(p2, CFG, RT, None)
    for h in HORIZONS:
        assert a["horizons"][str(h)]["champion"] == b["horizons"][str(h)]["champion"]
        assert (
            a["horizons"][str(h)]["reference_weights"] == b["horizons"][str(h)]["reference_weights"]
        )


def test_a_planted_edge_is_promoted_and_weights_follow_it() -> None:
    """Signal 0 truly predicts the outcome; the three other production signals are noise."""
    p = _synthetic_panel(WARMUP + 330, 60, edge=3.0, seed=5)
    cfg = CFG.model_copy(update={"candidates": ("ridge4_x120",)})
    state = adapt.run_cycle(p, cfg, RT, None)
    cell = state["horizons"]["5"]
    assert cell["champion"] == "ridge4_x120", cell["candidates"]["ridge4_x120"]
    assert cell["weights"][BASE[0]] > 0.6  # the weight moved onto the signal that works
    assert cell["production_expressible"] is True
    assert cell["live_scores"] is not None and len(cell["live_scores"]) == 60
    assert adapt.weights_for(state, 5)[BASE[0]] == pytest.approx(cell["weights"][BASE[0]], abs=1e-3)
