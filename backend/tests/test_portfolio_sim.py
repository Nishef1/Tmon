"""R3 baseline portfolio: order timing, queues, buffer, caps, PBO."""

from __future__ import annotations

import numpy as np

from tmon.backtest.portfolio_sim import BookParams, simulate_book
from tmon.backtest.v2_gates import pbo_cscv

T, J = 80, 12


def _params(**kw) -> BookParams:
    base = dict(
        n_names=4,
        n_tranches=2,
        review_every=2,
        buy_top_frac=0.4,
        hold_top_frac=0.5,
        sector_cap_pct=1.0,
        name_cap_pct=1.0,
        liquidity_cap=1.0,
        capital=1.0,
        entry_delay=1,
    )
    base.update(kw)
    return BookParams(**base)


def _world(rank=None, queue=None, ret=None):
    r = np.tile(np.linspace(0.05, 0.95, J), (T, 1)) if rank is None else rank
    q = np.zeros((T, J)) if queue is None else queue
    rt = np.zeros((T, J)) if ret is None else ret
    med = np.full((T, J), 1e12)
    sec = np.array([f"s{j % 6}" for j in range(J)], dtype=object)
    return rt, r, q, med, sec, np.zeros(T), np.zeros(T)


def test_buys_the_best_ranked_names_and_executes_the_next_day():
    ret, rank, q, med, sec, bc, sc = _world()
    res = simulate_book(ret, rank, q, med, sec, bc, sc, _params(), start=1)
    assert res.n_held[-1] == 4 and res.n_buys == 4
    first_buy_day = int(np.nonzero(res.buy_frac)[0][0])
    assert first_buy_day == 2  # decided at the close of day 1, executed at the close of day 2


def test_costs_reduce_the_return_and_zero_cost_keeps_it():
    ret = np.full((T, J), 0.001)
    w = _world(ret=ret)
    free = simulate_book(*w, _params(), start=1)
    costly = simulate_book(*w[:5], np.full(T, 0.01), np.full(T, 0.01), _params(), start=1)
    assert (1 + free.ret).prod() > (1 + costly.ret).prod()


def test_buy_into_a_buy_queue_is_cancelled():
    ret, rank, q, med, sec, bc, sc = _world()
    q[:, :] = 1  # everything is in a buy queue
    res = simulate_book(ret, rank, q, med, sec, bc, sc, _params(), start=1)
    assert res.n_buys == 0 and res.n_cancelled_buys > 0


def test_sell_in_a_sell_queue_is_postponed_not_skipped():
    ret, rank, q, med, sec, bc, sc = _world()
    held = simulate_book(ret, rank, q, med, sec, bc, sc, _params(), start=1)
    assert held.n_held[-1] == 4
    # the held names collapse to the bottom of the ranking while stuck in a sell queue
    rank2 = rank.copy()
    rank2[30:, :] = rank2[30:, ::-1]
    q2 = q.copy()
    q2[30:40, :] = 2
    res = simulate_book(ret, rank2, q2, med, sec, bc, sc, _params(), start=1)
    assert res.n_postponed_sells > 0


def test_buffer_keeps_a_name_inside_the_hold_zone():
    ret, rank, q, med, sec, bc, sc = _world()
    base = simulate_book(ret, rank, q, med, sec, bc, sc, _params(), start=1)
    # rank wobbles inside the top half: no name leaves the hold zone, so nothing is sold
    wob = rank + np.where(np.arange(T)[:, None] % 2, 0.02, -0.02)
    wob = np.where(rank >= 0.7, np.clip(wob, 0.55, 1.0), rank)
    res = simulate_book(ret, wob, q, med, sec, bc, sc, _params(), start=1)
    assert res.n_buys == base.n_buys == 4


def test_sector_cap_limits_names_per_sector():
    ret, rank, q, med, _, bc, sc = _world()
    one_sector = np.array(["x"] * J, dtype=object)
    res = simulate_book(
        ret, rank, q, med, one_sector, bc, sc, _params(sector_cap_pct=0.25), start=1
    )
    assert res.n_held.max() == 1  # 25% of 4 names = 1 per sector


def test_liquidity_cap_blocks_illiquid_names():
    ret, rank, q, med, sec, bc, sc = _world()
    res = simulate_book(ret, rank, q, med * 0 + 1.0, sec, bc, sc, _params(capital=1e6), start=1)
    assert res.n_buys == 0


def test_pbo_is_high_for_pure_noise_and_low_when_one_config_dominates():
    # on pure noise the in-sample winner is a coin flip out of sample: PBO averages near one half
    runs = [pbo_cscv(np.random.default_rng(s).normal(0, 1, (48, 6)), 8) for s in range(30)]
    assert 0.35 < float(np.mean(runs)) < 0.75
    rng = np.random.default_rng(0)
    noise = rng.normal(0, 1, (48, 6))
    dom = rng.normal(0, 1, (48, 6))
    dom[:, 0] += 3.0
    assert pbo_cscv(dom, 8) == 0.0
    assert pbo_cscv(noise[:, :1], 8) is None and pbo_cscv(noise[:4], 8) is None
