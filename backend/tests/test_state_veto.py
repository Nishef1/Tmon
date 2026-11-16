"""A high score does not become a "buy" for a symbol whose own state trailed the market."""

from __future__ import annotations

from typing import Any

from tmon.api.routers import dashboard as dash
from tmon.api.routers.dashboard import _horizon_decision, _horizons, final_verdict, state_veto

COST = 0.017512
SIG = {"ind_buy_power": 0.9}


def _ev(days: int = 20) -> dict[str, Any]:
    return {
        "horizon_days": days,
        "top_excess": 0.04,
        "bottom_excess": 0.0,
        "excess_t": 4.5,
        "n_days": 1000,
        "ic": 0.05,
        "ic_t": 4.0,
        "signals": {},
    }


def _stat(mean: float, n: int = 40000, dn: float = 0.11) -> dict[str, Any]:
    return {"n": n, "excess_mean": mean, "excess_median": -0.04, "beat": 0.4, "p_dn20": dn}


def _turning(symbol_state: str | None, mean: float, n: int = 40000) -> dict[str, Any]:
    return {
        "states": [],
        "symbols": {"7": {"state": symbol_state}} if symbol_state else {},
        "history": {
            "states": {
                "hot": {"n": n, "h20": _stat(mean, n), "h60": _stat(mean, n)},
                "normal": {"n": 500000, "h20": _stat(-0.001, 500000), "h60": None},
                "uptrend_high": {"n": 170000, "h20": _stat(0.008, 170000, 0.04), "h60": None},
            },
            "base": {"h20": _stat(0.0, 1000000, 0.05), "h60": _stat(0.0, 1000000, 0.13)},
        },
    }


def test_a_state_that_trailed_the_market_vetoes_the_buy_at_the_month() -> None:
    v = state_veto(_turning("hot", -0.002), 7, 20)
    assert v is not None and v["key"] == "hot" and v["title"] == "رشد بسیار تند"
    h = _horizon_decision(20, _ev(), "buy", COST, SIG, True, v)
    assert h.verdict == "hold"
    assert "فعلاً نخرید" in h.headline and "رشد بسیار تند" in h.headline
    assert "۱۱" in h.headline and "۵" in h.headline  # 11 in 100 fell by 20%, market 5 in 100


def test_a_state_that_beat_the_market_keeps_the_buy() -> None:
    assert state_veto(_turning("uptrend_high", 0.008), 7, 20) is None
    assert _horizon_decision(20, _ev(), "buy", COST, SIG, True, None).verdict == "buy"


def test_the_baseline_state_and_thin_evidence_never_veto() -> None:
    assert state_veto(_turning("normal", -0.001), 7, 20) is None
    assert state_veto(_turning("hot", -0.01, n=500), 7, 20) is None


def test_horizons_without_a_state_table_and_unknown_symbols_are_not_vetoed() -> None:
    doc = _turning("hot", -0.01)
    assert state_veto(doc, 7, 5) is None and state_veto(doc, 7, 1) is None
    assert state_veto(doc, 99, 20) is None and state_veto(None, 7, 20) is None


def test_the_veto_only_lowers_a_buy() -> None:
    v = state_veto(_turning("hot", -0.01), 7, 20)
    h = _horizon_decision(20, _ev(), "hold", COST, SIG, True, v)
    assert h.verdict == "hold" and "فعلاً نخرید" not in h.headline
    avoid = _horizon_decision(20, {**_ev(), "bottom_excess": -0.03}, "avoid", COST, SIG, True, v)
    assert avoid.verdict == "sell"


def test_final_verdict_and_horizons_agree_with_the_page() -> None:
    doc = {"round_trip_cost": COST, "evidence": [_ev(20)]}
    turn = _turning("hot", -0.002)
    assert final_verdict(doc, "buy", SIG) == "buy"  # no state document: unchanged
    assert final_verdict(doc, "buy", SIG, turn, 7) == "hold"
    assert final_verdict(doc, "buy", SIG, turn, 8) == "buy"  # another symbol, no veto
    month = _horizons(doc, "buy", SIG, turn, 7)[0]
    assert month.verdict == final_verdict(doc, "buy", SIG, turn, 7)
    assert dash.HOLD_DAYS == 20
