"""Per-horizon decisions: buy needs a solid net edge, a weak group is not sold without evidence."""

from __future__ import annotations

from tmon.api.routers.dashboard import _horizon_decision, _horizons

COST = 0.017512
SIG = {"ind_buy_power": 0.9}


def _ev(top: float | None, t: float | None, bot: float | None = 0.0, days: int = 20) -> dict:
    return {
        "horizon_days": days,
        "top_excess": top,
        "bottom_excess": bot,
        "excess_t": t,
        "n_days": 1000,
        "ic": 0.05,
        "ic_t": 4.0,
        "signals": {"ind_buy_power": {"ic": 0.06, "t": 3.8}},
    }


def test_buy_needs_net_edge_and_t() -> None:
    h = _horizon_decision(20, _ev(0.04, 4.5), "buy", COST, SIG, True)
    assert h.verdict == "buy"
    assert h.net_excess is not None and abs(h.net_excess - (0.04 - COST)) < 1e-9


def test_week_below_minimum_net_edge_is_hold_with_the_reason() -> None:
    h = _horizon_decision(5, _ev(0.0187, 10.0), "buy", COST, SIG, True)
    assert h.verdict == "hold"
    assert "کمتر است" in h.headline


def test_low_t_blocks_buy_even_with_a_big_edge() -> None:
    h = _horizon_decision(60, _ev(0.0755, 2.4), "buy", COST, SIG, True)
    assert h.verdict == "hold"
    assert "اطمینان آماری" in h.headline


def test_edge_below_cost_means_do_not_trade() -> None:
    h = _horizon_decision(1, _ev(0.0048, 18.0), "buy", COST, SIG, True)
    assert h.verdict == "hold"
    assert "هزینهٔ رفت‌وبرگشت" in h.headline


def test_avoid_zone_is_sell_only_when_the_weak_group_lost_to_the_market() -> None:
    assert _horizon_decision(20, _ev(0.04, 4.5, -0.03), "avoid", COST, SIG, True).verdict == "sell"
    assert _horizon_decision(20, _ev(0.04, 4.5, 0.0), "avoid", COST, SIG, True).verdict == "hold"


def test_horizons_need_the_cost_in_the_document() -> None:
    assert _horizons({"evidence": [_ev(0.04, 4.5)]}, "buy", SIG) == []
    out = _horizons({"round_trip_cost": COST, "evidence": [_ev(0.04, 4.5)]}, "buy", SIG)
    assert [h.key for h in out] == ["M1"]
