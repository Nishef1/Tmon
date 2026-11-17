"""The market-state plan: state reading, confirmation, decision kinds, the frozen log, the slots
and the sale under the mean."""

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
                    "under_ma": False,
                }
            )
    return pl.DataFrame(rows)


def test_replay_follows_the_state_and_freezes_the_log() -> None:
    cfg = get_engine_config().regime_plan.model_copy(
        update={"start": date(2026, 11, 1), "confirm_days": 2, "top": 2, "capital": 100.0}
    )
    syms = {k: f"S{k}" for k in range(12)}
    # flat, then falling for 3 days (cash), then rising (trend)
    a = _panel([0.5, 0.5, 0.25, 0.25, 0.25, 0.9, 0.9, 0.9])
    res = rp.replay(a, {}, cfg, [], syms)
    kinds = [(e["date"], e["state"], e["kind"]) for e in res["log"]]
    assert kinds == [
        ("2026-11-01", "flat", "wait"),
        ("2026-11-04", "falling", "wait"),
        ("2026-11-07", "rising", "enter"),
    ]
    assert res["log"][1]["names"] == []
    assert res["log"][2]["ranked"][:2] == ["S11", "S10"]  # best 120-day return first
    assert res["log"][2]["filled_on"] == "2026-11-08" and res["pending"] is None
    assert res["holding"] == ["S11", "S10"]
    assert res["path"][-1]["plan"] < 100  # bought at the last close: only the cost so far

    # a later run keeps the logged decisions even if the data now says otherwise
    frozen = [dict(e) for e in res["log"]]
    frozen[2]["ranked"] = ["S9", "S8"]
    again = rp.replay(a, {}, cfg, frozen, syms)
    assert again["log"][2]["names"] == ["S9", "S8"]
    assert [e["kind"] for e in again["log"]] == ["wait", "wait", "enter"]


def test_buy_locked_name_is_skipped_for_the_next() -> None:
    cfg = get_engine_config().regime_plan.model_copy(
        update={"start": date(2026, 11, 1), "confirm_days": 1, "top": 2, "capital": 100.0}
    )
    syms = {k: f"S{k}" for k in range(12)}
    a = _panel([0.9, 0.9, 0.9]).with_columns(
        buy_lock=(pl.col("date") == date(2026, 11, 2)) & (pl.col("instrument_id") == 11)
    )
    res = rp.replay(a, {}, cfg, [], syms)
    assert res["log"][0]["names"] == ["S10", "S9"]


def test_name_under_its_mean_is_sold_and_its_slot_stays_cash() -> None:
    cfg = get_engine_config().regime_plan.model_copy(
        update={"start": date(2026, 11, 1), "confirm_days": 1, "top": 2, "capital": 100.0}
    )
    syms = {k: f"S{k}" for k in range(12)}
    a = _panel([0.9] * 5).with_columns(
        under_ma=(pl.col("date") == date(2026, 11, 3)) & (pl.col("instrument_id") == 11)
    )
    res = rp.replay(a, {}, cfg, [], syms)
    assert [(e["date"], e["kind"]) for e in res["log"]] == [
        ("2026-11-01", "enter"),
        ("2026-11-03", "sell"),
    ]
    assert res["log"][1]["sold"] == ["S11"] and res["log"][1]["filled_on"] == "2026-11-04"
    assert res["holding"] == ["S10"]

    book = rp.Book(0.0, {1: 50.0, 2: 50.0})
    book.sell([1])
    assert book.cash == 50.0 * (1 - rp.SELL) and list(book.hold) == [2]
    total = book.value
    book.renew([2, 3], 2)  # 2 is kept at no cost, 3 is bought
    assert book.cash == 0.0
    assert book.hold[2] == total / 2
    assert book.hold[3] == total / 2 * (1 - rp.BUY)


def test_api_without_a_document() -> None:
    assert regime_paper_out(None).available is False
