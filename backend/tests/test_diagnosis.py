"""The "why no recommendation" funnel: exact counts, binding stage and nearest misses."""

from __future__ import annotations

import polars as pl

from tmon.core.engine_config import get_engine_config
from tmon.engine.diagnosis import build_diagnosis
from tmon.engine.gating import evaluate_gate

TH = get_engine_config().thresholds


def _pred() -> pl.DataFrame:
    n = TH.min_bucket_samples
    return pl.DataFrame(
        {
            "instrument_id": [1, 2, 3, 4, 5],
            "p_win": [0.60, 0.40, 0.30, None, 0.55],
            "ev": [0.020, 0.004, -0.010, None, 0.010],
            "p_min": [0.50, 0.45, 0.45, None, 0.50],
            "p_breakeven": [0.40, 0.38, 0.40, None, 0.40],
            "bucket_n": [n, n, n, 0, n - 1],
            "signal": [True, False, False, False, False],
        }
    )


def test_funnel_counts_are_exact_and_monotone():
    d = build_diagnosis(_pred(), TH, selected=1)
    counts = {s["key"]: s["count"] for s in d["stages"]}
    assert counts["universe"] == 5
    assert counts["scored"] == 4  # one symbol has no score
    assert counts["bucket"] == 3  # id 5 sits in a bucket one sample short
    assert counts["signal"] == 1 and counts["portfolio"] == 1
    seq = [s["count"] for s in d["stages"]]
    assert seq == sorted(seq, reverse=True)
    assert sum(s["lost"] for s in d["stages"][1:]) == 5 - 1


def test_nearest_misses_carry_the_shortfall_and_failed_checks():
    d = build_diagnosis(_pred(), TH, selected=0)
    top = d["nearest"][0]
    assert top["instrument_id"] == 5 and top["failed"] == ["bucket"]
    second = next(m for m in d["nearest"] if m["instrument_id"] == 2)
    assert abs(second["shortfall"] - 0.05) < 1e-9
    assert "p_min" in second["failed"]
    assert d["stats"]["p_win_max"] == 0.60 and d["stats"]["n_ev_positive"] == 3
    assert d["stats"]["n_distinct_p_win"] == 4


def test_empty_day_has_no_stages():
    d = build_diagnosis(pl.DataFrame(), TH, selected=0)
    assert d["stages"] == [] and d["universe"] == 0


def test_gate_reasons_state_the_numbers():
    chal = {
        "trades": {"n_trades": 900, "expectancy_net": -0.0123},
        "portfolio": {"total_return": -0.31},
        "probabilistic": {"brier_skill": -0.021},
    }
    base = {
        "trades": {"n_trades": 800, "expectancy_net": 0.0021},
        "portfolio": {"total_return": 0.12},
    }
    reasons = evaluate_gate(chal, base).reasons
    text = " ".join(reasons)
    for needle in ("-1.23", "+0.21", "-31.00", "+12.00", "-0.021"):
        assert needle in text, needle
