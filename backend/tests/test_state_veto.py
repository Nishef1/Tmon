"""A high score does not become a buy for a symbol whose own state trailed the market."""

from __future__ import annotations

from typing import Any

from tmon.engine.verdict import final_verdict, state_veto

COST = 0.017512


def _stat(mean: float, n: int = 40000, dn: float = 0.11) -> dict[str, Any]:
    return {"n": n, "excess_mean": mean, "excess_median": -0.04, "beat": 0.4, "p_dn20": dn}


def _turning(symbol_state: str | None, mean: float, n: int = 40000) -> dict[str, Any]:
    return {
        "states": [],
        "symbols": {"7": {"state": symbol_state}} if symbol_state else {},
        "history": {
            "states": {
                "hot": {"n": n, "h20": _stat(mean, n), "h60": _stat(mean, n)},
                "normal": {"n": 500000, "h20": _stat(-0.001, 500000), "h60": _stat(-0.001, 500000)},
                "uptrend_high": {"n": 170000, "h20": _stat(0.008, 170000, 0.04), "h60": None},
            },
            "base": {"h20": _stat(0.0, 1000000, 0.05), "h60": _stat(0.0, 1000000, 0.13)},
        },
    }


def _doc(grade: str = "proven") -> dict[str, Any]:
    return {
        "verdict": {
            "horizon_days": 60,
            "candidate_top_frac": 0.5,
            "avoid_bottom_frac": 0.4,
            "candidate_grade": grade,
            "avoid_grade": "unproven",
        },
        "exposure": {"exposure": 0.9},
        "round_trip_cost": COST,
        "zones": {},
    }


def test_a_state_that_trailed_the_market_vetoes_the_buy() -> None:
    v = state_veto(_turning("hot", -0.002), 7, 60)
    assert v is not None and v["key"] == "hot" and v["title"] == "رشد بسیار تند"
    out = final_verdict(_doc(), {"band": "candidate"}, _turning("hot", -0.002), 7)
    assert out is not None and out.code == "wait" and out.vetoed
    assert "فعلاً نخرید" in out.headline and "رشد بسیار تند" in out.headline
    assert "۱۱" in out.headline and "۱۳" in out.headline  # 11 in 100 fell by 20%, market 13 in 100


def test_a_state_that_beat_the_market_keeps_the_buy() -> None:
    assert state_veto(_turning("uptrend_high", 0.008), 7, 20) is None
    out = final_verdict(_doc(), {"band": "candidate"}, _turning("hot", 0.01), 7)
    assert out is not None and out.code == "buy"


def test_the_baseline_state_and_thin_evidence_never_veto() -> None:
    assert state_veto(_turning("normal", -0.001), 7, 60) is None
    assert state_veto(_turning("hot", -0.01, n=500), 7, 60) is None


def test_horizons_without_a_state_table_and_unknown_symbols_are_not_vetoed() -> None:
    doc = _turning("hot", -0.01)
    assert state_veto(doc, 7, 5) is None and state_veto(doc, 7, 1) is None
    assert state_veto(doc, 99, 60) is None and state_veto(None, 7, 60) is None


def test_the_veto_only_lowers_a_candidate() -> None:
    turn = _turning("hot", -0.01)
    for band in ("middle", "avoid"):
        out = final_verdict(_doc(), {"band": band}, turn, 7)
        assert out is not None and not out.vetoed and out.code != "wait"
    # for an owner nothing changes
    held = final_verdict(_doc(), {"band": "candidate"}, turn, 7)
    assert held is not None and held.holder_code == "hold"
    # the list and the page agree: same call, same answer
    assert final_verdict(_doc(), {"band": "candidate"}, turn, 7).code == "wait"  # type: ignore[union-attr]
    assert final_verdict(_doc(), {"band": "candidate"}, turn, 8).code == "buy"  # type: ignore[union-attr]
