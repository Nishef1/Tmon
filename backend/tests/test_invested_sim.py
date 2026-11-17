"""ADR 0004 section 3: the always-invested book on small synthetic matrices."""

from __future__ import annotations

import numpy as np
import pytest

from tmon.backtest.invested_sim import QUEUE_BUY, InvestedParams, simulate_invested

N_INST = 6


def _inputs(
    days: int = 40,
    *,
    ret: np.ndarray | None = None,
    rank: np.ndarray | None = None,
    queue: np.ndarray | None = None,
    cost: float = 0.0,
    rf: float = 0.0,
    expo: float | None = None,
) -> dict[str, np.ndarray | None]:
    r = np.zeros((days, N_INST)) if ret is None else ret
    pct = np.linspace(0.0, 1.0, N_INST)  # instrument 5 scores best
    return {
        "ret": r,
        "rank": np.tile(pct, (days, 1)) if rank is None else rank,
        "queue": np.zeros((days, N_INST), dtype=int) if queue is None else queue,
        "median_value": np.full((days, N_INST), 1e12),
        "sector": np.arange(N_INST),
        "buy_cost": np.full(days, cost),
        "sell_cost": np.full(days, cost),
        "rf": np.full(days, rf),
        "expo": None if expo is None else np.full(days, expo),
    }


def _run(inp: dict[str, np.ndarray | None], p: InvestedParams, start: int = 0):
    return simulate_invested(
        inp["ret"],  # type: ignore[arg-type]
        inp["rank"],  # type: ignore[arg-type]
        inp["queue"],  # type: ignore[arg-type]
        inp["median_value"],  # type: ignore[arg-type]
        inp["sector"],  # type: ignore[arg-type]
        inp["buy_cost"],  # type: ignore[arg-type]
        inp["sell_cost"],  # type: ignore[arg-type]
        inp["rf"],  # type: ignore[arg-type]
        inp["expo"],
        p,
        start,
    )


SEL = {
    "n_names": 2,
    "n_tranches": 1,
    "review_every": 10,
    "buy_top_frac": 0.2,
    "hold_top_frac": 0.5,
}


def test_cash_earns_the_bill_when_exposure_is_below_one() -> None:
    inp = _inputs(rf=0.01, expo=0.5)
    res = _run(inp, InvestedParams(use_exposure=True))
    equity = np.cumprod(1.0 + res.ret)
    # day 1: all capital is still cash (earns one bill); then half moves to the core, which earns 0
    expected = 0.5 * 1.01**39 + 0.5 * 1.01
    assert equity[-1] == pytest.approx(expected, rel=1e-9)
    assert res.equity_share[-1] == pytest.approx(0.505 / expected, rel=1e-9)
    assert res.equity_share[2] < 0.55


def test_costs_are_charged_only_on_traded_amounts() -> None:
    cost = 0.01
    res = _run(_inputs(cost=cost), InvestedParams())
    assert res.ret[1] == pytest.approx(1.0 / (1.0 + cost) - 1.0, rel=1e-12)
    # nothing is traded afterwards: no cost, no return, nothing bought or sold
    assert np.all(np.abs(res.ret[2:]) < 1e-12)
    assert np.all(res.bought[2:] == 0.0)
    assert np.all(res.sold[2:] == 0.0)


def test_cost_multiplier_scales_the_cost() -> None:
    base = _run(_inputs(cost=0.01), InvestedParams())
    heavy = _run(_inputs(cost=0.01), InvestedParams(cost_multiplier=1.5))
    assert heavy.ret[1] == pytest.approx(1.0 / 1.015 - 1.0, rel=1e-12)
    assert heavy.ret[1] < base.ret[1]


def test_unfilled_selection_slot_sits_in_the_core_not_in_cash() -> None:
    # only instrument 5 scores in the top 10%: one of the two slots stays empty
    p = InvestedParams(**{**SEL, "buy_top_frac": 0.1})
    res = _run(_inputs(), p)
    assert res.n_selection.max() == 1
    assert np.all(res.equity_share[2:] == pytest.approx(1.0))
    # the core holds every tradable name, the selection name included
    assert res.n_names[-1] == N_INST


def test_selection_buy_is_paid_by_the_core_and_is_overweight() -> None:
    ret = np.zeros((40, N_INST))
    ret[5:, 5] = 0.01  # the selected name rises, the rest of the market is flat
    res_sel = _run(_inputs(ret=ret), InvestedParams(**SEL))
    res_core = _run(_inputs(ret=ret), InvestedParams())
    assert res_sel.n_buys >= 1
    assert np.prod(1.0 + res_sel.ret) > np.prod(1.0 + res_core.ret)


def test_cancelled_buy_is_replaced_the_next_day() -> None:
    queue = np.zeros((40, N_INST), dtype=int)
    queue[1, 5] = QUEUE_BUY  # the best name is locked on its execution day
    # candidates are 5, 4 and 3; the two slots take 5 and 4, so 3 is the reserve
    res = _run(_inputs(queue=queue), InvestedParams(**{**SEL, "buy_top_frac": 0.4}))
    assert res.n_cancelled_buys == 1
    assert res.n_replacements == 1
    replaced = [d for d in res.decisions if d[1] == "replace"]
    assert replaced[0][0] == 1  # decided at the close of the cancellation day
    assert replaced[0][2] == 3  # the next-ranked candidate of the same review
    assert res.n_selection[1] == 1  # one slot is open on the cancellation day
    assert res.n_selection[2] == 2  # the replacement executes the next day


def test_core_buy_into_a_buy_queue_is_skipped_not_forced() -> None:
    queue = np.zeros((40, N_INST), dtype=int)
    queue[1, 3] = QUEUE_BUY
    res = _run(_inputs(queue=queue, rf=0.001), InvestedParams())
    assert res.n_core_skipped >= 1
    assert res.equity_share[1] < 1.0  # the skipped slice waits in cash


def test_decisions_up_to_t_do_not_depend_on_rows_after_t() -> None:
    rng = np.random.default_rng(7)
    days = 80
    ret = rng.normal(0, 0.01, (days, N_INST))
    rank = rng.uniform(0, 1, (days, N_INST))
    queue = (rng.uniform(size=(days, N_INST)) < 0.05).astype(int)
    p = InvestedParams(**SEL, core_review_every=15, core_drop_bottom_frac=0.3)
    base = _run(_inputs(days, ret=ret, rank=rank, queue=queue, cost=0.002), p)

    cut = 40
    ret2, rank2, queue2 = ret.copy(), rank.copy(), queue.copy()
    ret2[cut + 1 :] = rng.normal(0, 0.05, (days - cut - 1, N_INST))
    rank2[cut + 1 :] = rng.uniform(0, 1, (days - cut - 1, N_INST))
    queue2[cut + 1 :] = (rng.uniform(size=(days - cut - 1, N_INST)) < 0.5).astype(int)
    other = _run(_inputs(days, ret=ret2, rank=rank2, queue=queue2, cost=0.002), p)

    early = [d for d in base.decisions if d[0] <= cut]
    assert early  # the comparison is not empty
    assert early == [d for d in other.decisions if d[0] <= cut]
    # money moves up to the cut agree as well: orders execute at t + 1 on the same inputs
    assert np.allclose(base.ret[: cut + 1], other.ret[: cut + 1])


def test_order_decided_on_t_executes_at_the_close_of_t_plus_one() -> None:
    ret = np.zeros((40, N_INST))
    ret[1, :] = 0.05  # the day the order is decided on and the day after: both pre-execution
    res = _run(_inputs(ret=ret), InvestedParams())
    # all capital was cash through day 1; the 5% of day 1 is earned by nobody
    assert res.ret[1] == pytest.approx(0.0, abs=1e-12)


def _reference_core_only(ret: np.ndarray, rank: np.ndarray, every: int, start: int) -> np.ndarray:
    """Independent loop for S0 without costs, queues or cash yield: equal weights over the names
    ranked at the close of a review day, set at the next close, drifting in between."""
    out = np.zeros(ret.shape[0])
    w = np.zeros(ret.shape[1])
    for j in range(start + 1, ret.shape[0]):
        grown = w * (1.0 + ret[j])
        total = grown.sum() if w.any() else 0.0
        out[j] = total - 1.0 if w.any() else 0.0
        w = grown / total if w.any() else w
        decided = j - 1
        if (decided - start) % every == 0:
            member = np.isfinite(rank[decided])
            if member.any():
                w = member / member.sum()
    return out


def test_core_only_book_matches_an_independent_loop() -> None:
    rng = np.random.default_rng(11)
    days = 200
    ret = rng.normal(0.0005, 0.02, (days, N_INST))
    rank = rng.uniform(size=(days, N_INST))
    rank[rng.uniform(size=rank.shape) < 0.3] = np.nan
    res = _run(_inputs(days, ret=ret, rank=rank), InvestedParams(core_review_every=25), start=7)
    ref = _reference_core_only(ret, rank, 25, 7)
    assert np.allclose(res.ret, ref, atol=1e-12)


def test_redeploy_idle_puts_a_skipped_slice_back_into_the_core_next_day() -> None:
    queue = np.zeros((40, N_INST), dtype=int)
    queue[1, 3] = QUEUE_BUY
    res = _run(_inputs(queue=queue, rf=0.001), InvestedParams(redeploy_idle=True))
    assert res.equity_share[1] < 1.0
    assert res.equity_share[2] == pytest.approx(1.0)
