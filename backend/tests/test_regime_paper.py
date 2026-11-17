"""The market-state plan: state reading, confirmation, decision kinds and the frozen log."""

from __future__ import annotations

from datetime import date, timedelta

import polars as pl

from tmon.api.regime_paper import regime_paper_out
from tmon.core.engine_config import get_engine_config
from tmon.tools import regime_paper as rp


def test_raw_state_edges() -> None:
    assert rp.raw_state(0.30, 0.377, 0.836) == "falling"
    assert rp.raw_state(0.377, 0.377, 0.836) == "falling"
    assert rp.raw_state(0.836, 0.377, 0.836) == "flat"
    assert rp.raw_state(0.90, 0.377, 0.836) == "rising"
    assert rp.raw_state(None, 0.377, 0.836) == "flat"
    assert rp.raw_state(float("nan"), 0.377, 0.836) == "flat"


def test_state_counts_only_after_it_held() -> None:
    raw = ["rising"] * 4 + ["flat"] + ["rising"] * 5
    st, runs = rp.confirmed(raw, 5)
    assert st[:9] == ["flat"] * 9  # four days, a break, then four again: not yet
    assert st[9] == "rising"
    assert runs[-1] == 5


def test_decision_kinds() -> None:
    assert rp.kind(in_cash=True, to_cash=False) == "enter"
    assert rp.kind(in_cash=False, to_cash=True) == "exit"
    assert rp.kind(in_cash=False, to_cash=False) == "switch"
    assert rp.kind(in_cash=True, to_cash=True) == "wait"


def _panel(breadth: list[float], n: int = 12) -> pl.DataFrame:
    """``n`` stocks over ``len(breadth)`` days; stock k has drawdown -k% and 120-day return k%."""
    rows = []
    d0 = date(2026, 11, 1)
    for t, b in enumerate(breadth):
        above = round(b * n)
        for k in range(n):
            rows.append(
                {
                    "date": d0 + timedelta(days=t),
                    "instrument_id": k,
                    "ret": 0.01,
                    "gap60": 0.1 if k < above else -0.1,
                    "dd": -k / 100,
                    "q_dd": 0 if k >= n - 3 else 2,
                    "r120": k / 100,
                    "q_r120": 4 if k >= n - 3 else 1,
                    "q_pos60": 4,
                    "buy_lock": False,
                }
            )
    return pl.DataFrame(rows)


def test_replay_follows_the_state_and_freezes_the_log() -> None:
    cfg = get_engine_config().regime_plan.model_copy(
        update={"start": date(2026, 11, 1), "confirm_days": 2, "top": 2, "capital": 100.0}
    )
    syms = {k: f"S{k}" for k in range(12)}
    # flat, then falling for 3 days, then rising
    a = _panel([0.5, 0.5, 0.25, 0.25, 0.25, 0.9, 0.9, 0.9])
    res = rp.replay(a, {}, cfg, [], syms)
    kinds = [(e["date"], e["state"], e["kind"]) for e in res["log"]]
    assert kinds == [
        ("2026-11-01", "flat", "wait"),
        ("2026-11-04", "falling", "enter"),
        ("2026-11-07", "rising", "switch"),
    ]
    dust = res["log"][1]
    assert dust["ranked"][:2] == ["S11", "S10"]  # deepest drawdown first
    assert dust["filled_on"] == "2026-11-05" and dust["names"] == ["S11", "S10"]
    assert res["log"][2]["ranked"][:2] == ["S11", "S10"]  # best 120-day return first
    assert res["log"][2]["filled_on"] == "2026-11-08" and res["pending"] is None
    assert res["holding"] == ["S11", "S10"]

    # a later run keeps the logged decisions even if the data now says otherwise
    frozen = [dict(e) for e in res["log"]]
    frozen[1]["ranked"] = ["S9", "S8"]
    again = rp.replay(a, {}, cfg, frozen, syms)
    assert again["log"][1]["names"] == ["S9", "S8"]
    assert [e["kind"] for e in again["log"]] == ["wait", "enter", "switch"]


def test_buy_locked_name_is_skipped_for_the_next() -> None:
    cfg = get_engine_config().regime_plan.model_copy(
        update={"start": date(2026, 11, 1), "confirm_days": 1, "top": 2, "capital": 100.0}
    )
    syms = {k: f"S{k}" for k in range(12)}
    a = _panel([0.25, 0.25, 0.25]).with_columns(
        buy_lock=(pl.col("date") == date(2026, 11, 2)) & (pl.col("instrument_id") == 11)
    )
    res = rp.replay(a, {}, cfg, [], syms)
    assert res["log"][0]["names"] == ["S10", "S9"]


def test_api_without_a_document() -> None:
    assert regime_paper_out(None).available is False
