"""Turning-point states (tmon.backtest.turning): fixed priority, tone rule, API part."""

from __future__ import annotations

import datetime as dt

import numpy as np
import polars as pl
import pytest

from tmon.backtest import turning as tp


def _row(**over: object) -> dict[str, object]:
    base: dict[str, object] = {
        "dd": -0.1, "ret20": 0.0, "ret60": 0.0, "close": 100.0, "sma20": 100.0,
        "sma50": 100.0, "sma200": 100.0, "net5": 0.0, "power5": 1.0,
        "mkt_bull": True, "mkt_dd": 0.0,
    }  # fmt: skip
    base.update(over)
    return base


CASES = {
    # overheated first, whatever else holds
    "hot_breaking": _row(ret60=1.5, close=90.0, dd=-0.6, net5=0.2, power5=2.0),
    "hot_flow_out": _row(ret60=1.5, close=110.0, net5=-0.1, power5=0.5),
    "hot": _row(ret60=1.5, close=110.0),
    # deep falls: money in beats a price turn, which beats "still falling"
    "deep_flow_in": _row(dd=-0.6, net5=0.06, power5=1.3, ret20=-0.2),
    "deep_turn_with_market": _row(dd=-0.6, close=110.0, ret20=0.05, mkt_bull=False),
    "deep_turn_alone": _row(dd=-0.6, close=110.0, ret20=0.05, mkt_bull=True, mkt_dd=-0.05),
    "deep_falling": _row(dd=-0.6, ret20=-0.2),
    "deep_base": _row(dd=-0.6, ret20=-0.05),
    "mid_fall": _row(dd=-0.4),
    "uptrend_high": _row(dd=-0.02, sma20=99.0, sma50=98.0, sma200=90.0),
    "normal": _row(dd=-0.2),
}


def test_every_state_is_reachable_with_the_fixed_priority() -> None:
    df = pl.DataFrame(list(CASES.values()))
    got = df.with_columns(state=tp.state_expr())["state"].to_list()
    assert got == list(CASES)
    assert set(CASES) == {s.key for s in tp.STATES}


def test_market_drawdown_counts_as_a_weak_market() -> None:
    row = _row(dd=-0.6, close=110.0, ret20=0.05, mkt_bull=True, mkt_dd=-0.25)
    assert pl.DataFrame([row]).select(tp.state_expr()).item() == "deep_turn_with_market"


def test_no_state_without_a_year_of_history() -> None:
    assert pl.DataFrame([_row(dd=None)]).select(tp.state_expr()).item() is None


def _half(x: float, dn: float = 0.3) -> dict[str, object]:
    return {"h120": {"excess_mean": x, "p_dn20": dn}}


@pytest.mark.parametrize(
    ("halves", "tone"),
    [
        ([_half(0.05), _half(0.03)], "up"),  # beats the 1.75% cost in both halves
        ([_half(0.05), _half(0.01)], "none"),  # one half below the cost
        ([_half(-0.05), _half(-0.03)], "down"),
        ([_half(-0.01, 0.40), _half(-0.01, 0.40)], "down"),  # small loss, much likelier crash
        ([_half(-0.01), _half(-0.01)], "none"),
        ([_half(0.05), {"h120": None}], "none"),
    ],
)
def test_tone_needs_both_halves(halves: list[dict[str, object]], tone: str) -> None:
    base = [_half(0.0, 0.3), _half(0.0, 0.3)]
    assert tp._tone(halves, base, 0.0175) == tone


def test_state_stats_on_a_synthetic_panel() -> None:
    rng = np.random.default_rng(0)
    n = 4000
    days = [dt.date(2020, 1, 1) + dt.timedelta(days=i % 200) for i in range(n)]
    state = np.where(np.arange(n) % 2 == 0, "deep_flow_in", "normal")
    x = np.where(state == "deep_flow_in", 0.05, -0.05) + rng.normal(0, 0.01, n)
    panel = pl.DataFrame(
        {
            "instrument_id": np.arange(n) % 50,
            "date": days,
            "state": state,
            "liquid": True,
            **{f"x{h}": x for h in tp.HORIZONS},
            **{f"f{h}": x for h in tp.HORIZONS},
            "mae60": -np.abs(x),
        }
    )
    out = tp.state_stats(panel, 0.0175)
    s = out["states"]["deep_flow_in"]
    assert s["tone"] == "up" and out["states"]["normal"]["tone"] == "down"
    assert s["h120"]["beat"] == pytest.approx(1.0)
    assert out["states"]["hot"]["n"] == 0 and out["states"]["hot"]["h120"] is None


def _doc() -> dict[str, object]:
    blk = {
        "n": 100, "symbols": 10, "episodes": 20, "tone": "up", "skewed": True,
        "h20": None, "h60": None,
        "h120": {"n": 90, "excess_mean": 0.05, "excess_median": -0.02, "beat": 0.48,
                 "raw_median": 0.01, "p_up50": 0.2, "p_dn20": 0.25},
        "mae60_median": -0.1, "mae60_p10": -0.33,
        "halves": [{"h120": {"excess_mean": 0.08}}, {"h120": {"excess_mean": 0.04}}],
    }  # fmt: skip
    return {
        "as_of": "2026-11-11",
        "round_trip_cost": 0.0175,
        "states": [
            {
                "key": s.key,
                "title": s.title,
                "meaning": s.meaning,
                "triggers": [{"to": k, "when": w} for k, w in tp.TRIGGERS.get(s.key, [])],
            }
            for s in tp.STATES
        ],
        "history": {
            "first": "2003-07-14",
            "last": "2026-11-11",
            "split_date": "2015-01-01",
            "base": {**blk, "tone": "none"},
            "states": {s.key: blk for s in tp.STATES},
        },
        "market": {"date": "2026-11-11", "bull": True, "drawdown": -0.01},
        "symbols": {
            "1": {
                "date": "2026-11-11",
                "state": "deep_falling",
                "dd": -0.6,
                "ret20": -0.2,
                "liquid": True,
            }
        },
    }


def test_turning_out_gives_the_state_and_its_triggers() -> None:
    from tmon.api.routers.dashboard import turning_out

    t = turning_out(_doc(), 1)
    assert t is not None and t.state.key == "deep_falling"
    assert [g.state.key for g in t.triggers] == ["deep_flow_in", "deep_turn_with_market",
                                                 "deep_turn_alone"]  # fmt: skip
    assert t.state.horizons[0].horizon_days == 120 and t.state.halves_excess_120 == [0.08, 0.04]
    assert t.base.tone == "none" and t.market_bull is True
    assert turning_out(_doc(), 2) is None and turning_out(None, 1) is None


def test_rank_peers_orders_by_score_and_keeps_the_symbol() -> None:
    from tmon.api.routers.dashboard import PEERS_SHOWN, rank_peers
    from tmon.storage.models import Instrument

    n = PEERS_SHOWN + 3
    peers = [Instrument(id=i, symbol_fa=f"s{i}", tags={"eps": 10.0}) for i in range(1, n + 1)]
    rank = {
        "rows": [{"symbol": "s1"}],
        "universe": [{"id": i, "score": i / 100, "zone": "buy" if i > 5 else "avoid"}
                     for i in range(1, n)],  # the last one is not scored
    }  # fmt: skip
    out = rank_peers(peers, 1, rank, _doc(), {1: 50.0})
    assert out.scored == out.total == n - 1  # the unscored, stateless one is dropped
    assert [x.id for x in out.items][:2] == [n - 1, n - 2]
    me = out.items[-1]
    assert me.is_self and out.position == n - 1 and len(out.items) == PEERS_SHOWN + 1
    assert me.verdict == "sell" and me.in_basket and me.pe == pytest.approx(5.0)
    assert me.turning_key == "deep_falling" and me.turning_tone == "up" and me.dd == -0.6


def test_state_names_come_from_the_code_not_the_stored_document() -> None:
    from tmon.api.routers.dashboard import turning_out

    doc = _doc()
    for m in doc["states"]:  # type: ignore[attr-defined]
        m["title"] = "old name"
    t = turning_out(doc, 1)
    assert t is not None and t.state.title == tp.STATE_BY_KEY["deep_falling"].title
    assert "داغ" not in {s.title for s in tp.STATES}
