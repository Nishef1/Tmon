"""The deep study as a document: the gate applied to its numbers, and what the API says of it."""

from __future__ import annotations

import copy
from typing import Any

from tmon.api.deep import deep_out
from tmon.engine.adapt import NOT_ENOUGH, R_COST, R_EXCESS, R_HALVES, R_IC
from tmon.tools.deep_doc import finalize, judge

COST = 0.0175


def stat(mean: float, t: float | None = None, n: int = 800) -> dict[str, Any]:
    return {"n": n, "mean": mean, "t": t, "pos": 0.5}


def cell(**kw: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "ic": stat(0.12, 9.0),
        "ex": stat(0.02, 9.0),
        "d_ic": stat(0.02, 3.5),
        "d_ex": stat(0.002, 1.0),
        "d_ic_early": stat(0.015),
        "d_ic_late": stat(0.025),
        "seed_ic": None,
    }
    base.update(kw)
    return base


def test_a_steady_gain_that_beats_the_cost_passes() -> None:
    assert judge(cell(), COST, 2.0) == {"passed": True, "reasons": []}


def test_each_condition_fails_on_its_own() -> None:
    assert judge(cell(d_ic=stat(0.02, 1.5)), COST, 2.0)["reasons"] == [R_IC]
    assert judge(cell(d_ic=stat(-0.01, 3.0)), COST, 2.0)["reasons"] == [R_IC]
    assert judge(cell(d_ic_late=stat(-0.001)), COST, 2.0)["reasons"] == [R_HALVES]
    assert judge(cell(d_ex=stat(-0.001)), COST, 2.0)["reasons"] == [R_EXCESS]
    assert judge(cell(ex=stat(0.01, 5.0)), COST, 2.0)["reasons"] == [R_COST]


def test_a_thin_sample_is_not_judged() -> None:
    out = judge(cell(d_ic=stat(0.05, 9.0, n=100)), COST, 2.0)
    assert out == {"passed": False, "reasons": [NOT_ENOUGH]}


def doc() -> dict[str, Any]:
    eq = cell(d_ic=None, d_ex=None, d_ic_early=None, d_ic_late=None)
    return {
        "first": "2019-12-24",
        "last": "2026-11-11",
        "oos_from": "2022-11-07",
        "mid": "2024-10-02",
        "device": "cuda",
        "torch": "2.14.1",
        "seeds": [11, 12],
        "settings": {"seq": 16, "epochs": 14},
        "horizons": [5],
        "results": {"5": {"equal": eq, "gbm": cell(), "tcn": cell(d_ic=stat(-0.01, -1.0))}},
    }


def test_finalize_adds_cost_and_a_gate_to_every_method_but_equal() -> None:
    d = finalize(copy.deepcopy(doc()), COST, 2.0)
    r = d["results"]["5"]
    assert d["round_trip_cost"] == COST and r["equal"]["gate"] is None
    assert r["gbm"]["gate"]["passed"] is True and r["tcn"]["gate"]["passed"] is False


def test_api_says_so_when_there_is_no_judged_study() -> None:
    assert deep_out(None).available is False
    assert deep_out(doc()).available is False  # raw numbers without the verdicts are not served


def test_api_serves_the_judged_study() -> None:
    out = deep_out(finalize(copy.deepcopy(doc()), COST, 2.0))
    assert out.available and out.round_trip_cost == COST
    m = out.horizons[0].methods
    assert out.horizons[0].horizon_days == 5 and set(m) == {"equal", "gbm", "tcn"}
    assert m["gbm"].gate is not None and m["gbm"].gate.passed
    assert m["equal"].gate is None and m["equal"].d_ic is None
