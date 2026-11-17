"""ADR 0004 section 3: the always-invested book, simulated day by day.

Three buckets make up the capital: the **selection names** (the R3 book: equal slots, tranches,
review rhythm), the **core** (S0: the equal-weight tradable universe, held and reviewed every
``core_review_every`` days) and **cash** (earns the daily treasury-bill return, nothing when the
series has no value). The rules, all fixed before the data was seen:

* Equity share. ``e`` is 1 for S0-S3. For S4-S6 it is the exposure decided at the close of ``t`` and
  executed at the close of ``t + entry_delay``; the rest of the capital is cash.
* The core is the residual. Equity capital the selection names do not hold sits in the core, never
  in cash: a name bought is paid for by selling the core, a name sold buys the core back, a change
  of ``e`` scales the core. Every such move pays the sell cost and the buy cost on the amount moved.
* Replacement. A buy cancelled because the name is in a buy queue on the execution day is replaced
  the next day by the next-ranked candidate of the same review (ranked on the original decision
  day) that is not held, not pending, and passes the sector and liquidity caps.
* An order that cannot execute is skipped, not forced: a core sell into a sell queue and a core buy
  into a buy queue are left for the next review, and the money meanwhile earns the bill. (The
  ``redeploy_idle`` sensitivity instead puts idle cash back into the core, in names not in a buy
  queue, on the next day; every configuration gets the same rule.)

Day ``t`` decisions read only rows ``<= t`` of every input; orders execute at the close of
``t + entry_delay`` and earn the return of the days after it. ``decisions`` records every order so a
test can prove that rows after ``t`` cannot change what was decided on ``t``.

Pure numpy over (day x instrument) matrices; the loop is over days.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np

QUEUE_BUY, QUEUE_SELL = 1, 2
_EPS = 1e-9  # amounts below this share of the capital are not traded


@dataclass(frozen=True)
class InvestedParams:
    n_names: int = 0  # 0: no selection layer (S0, S1, S4)
    n_tranches: int = 1
    review_every: int = 1
    buy_top_frac: float = 0.0
    hold_top_frac: float = 0.0
    sector_cap_pct: float = 1.0
    name_cap_pct: float = 1.0
    liquidity_cap: float = 1.0
    capital: float = 1.0
    core_review_every: int = 60
    core_drop_bottom_frac: float = 0.0  # S1: tradable names scoring below this are left out
    entry_delay: int = 1
    cost_multiplier: float = 1.0
    selection_phase: int = 0  # offset of the selection review cycle
    core_phase: int = 0  # offset of the core review cycle
    use_exposure: bool = False
    redeploy_idle: bool = False  # sensitivity: idle cash is put back into the core at once


@dataclass
class InvestedResult:
    ret: np.ndarray  # daily return of the whole capital, after costs
    bought: np.ndarray  # value bought that day / capital at the previous close
    sold: np.ndarray
    equity_share: np.ndarray
    n_names: np.ndarray  # distinct names held (core and selection)
    n_selection: np.ndarray  # names held by the selection layer
    n_buys: int = 0
    n_cancelled_buys: int = 0
    n_replacements: int = 0
    n_postponed_sells: int = 0
    n_core_skipped: int = 0
    decisions: list[tuple[Any, ...]] = field(default_factory=list)


def simulate_invested(
    ret: np.ndarray,
    rank: np.ndarray,
    queue: np.ndarray,
    median_value: np.ndarray,
    sector: np.ndarray,
    buy_cost: np.ndarray,
    sell_cost: np.ndarray,
    rf: np.ndarray,
    expo: np.ndarray | None,
    p: InvestedParams,
    start: int,
) -> InvestedResult:
    """Matrices are ``(days, instruments)``; ``buy_cost``, ``sell_cost``, ``rf`` and ``expo`` are
    ``(days,)``. ``rf`` is the treasury-bill return of the day (0 where unknown), ``expo`` the
    exposure decided at that day's close (required, finite from ``start`` on, when
    ``use_exposure``). ``rank`` is the percentile of the composite score (NaN: not in the basket).
    The book decides from day ``start`` on."""
    t_days, n_inst = ret.shape
    sel = p.n_names > 0
    if sel and p.n_names * p.name_cap_pct < 1.0 - 1e-9:
        raise ValueError("name cap is below 1 / n_names: the book cannot be fully invested")
    if p.use_exposure and (expo is None or not np.all(np.isfinite(expo[start:]))):
        raise ValueError("exposure is needed (and finite) from the first day of the book")
    d = p.entry_delay
    cap_per_sector = max(int(p.sector_cap_pct * p.n_names + 1e-9), 1) if sel else 1
    slots = (
        [p.n_names // p.n_tranches + (k < p.n_names % p.n_tranches) for k in range(p.n_tranches)]
        if sel
        else []
    )
    res = InvestedResult(
        ret=np.zeros(t_days),
        bought=np.zeros(t_days),
        sold=np.zeros(t_days),
        equity_share=np.zeros(t_days),
        n_names=np.zeros(t_days, dtype=int),
        n_selection=np.zeros(t_days, dtype=int),
    )
    cash = 1.0
    core = np.zeros(n_inst)
    w_core = np.zeros(n_inst)  # membership weights of the latest core review
    held: dict[int, float] = {}
    tranche_of: dict[int, int] = {}
    # (due day, kind, instrument, tranche, extra); kind in sell / buy / core
    pending: list[tuple[Any, ...]] = []
    equity_prev = 1.0
    e_prev: float | None = None
    for i in range(start, t_days):
        if i > start:
            # ---- growth: names and core earn their return, cash earns the bill
            cash *= 1.0 + rf[i]
            core *= 1.0 + ret[i]
            for j in held:
                held[j] *= 1.0 + ret[i, j]
            bc, sc = buy_cost[i] * p.cost_multiplier, sell_cost[i] * p.cost_multiplier
            sellable = queue[i] != QUEUE_SELL
            buyable = queue[i] != QUEUE_BUY
            bought = sold = 0.0
            due = [o for o in pending if o[0] == i]
            pending = [o for o in pending if o[0] != i]
            due_buys = {o[2] for o in due if o[1] == "buy"}  # decided earlier, not yet executed
            rebalance = False
            sold_sel = False
            # ---- selection sells first: they fund the core
            for _, kind, j, k, _ex in due:
                if kind != "sell" or j not in held:
                    continue
                if queue[i, j] == QUEUE_SELL:
                    pending.append((i + 1, "sell", j, k, None))
                    res.n_postponed_sells += 1
                    continue
                v = held.pop(j)
                tranche_of.pop(j, None)
                cash += v * (1.0 - sc)
                sold += v
                sold_sel = True
            for _, kind, _j, _k, ex in due:
                if kind == "core":
                    w_core = ex
                    rebalance = True
            e_now = float(expo[i - d]) if p.use_exposure and expo is not None else 1.0
            # ---- selection buys, paid by selling the core (cash pays what the core cannot)
            for _, kind, j, k, reserve in due:
                if kind != "buy" or j in held:
                    continue
                sleeve_now = e_now * (cash + float(core.sum()) + sum(held.values()))
                if queue[i, j] == QUEUE_BUY:
                    res.n_cancelled_buys += 1
                    j2 = _replacement(
                        reserve,
                        i,
                        set(held) | {o[2] for o in pending if o[1] == "buy"} | due_buys,
                        sector,
                        median_value,
                        cap_per_sector,
                        p,
                        sleeve_now,
                    )
                    if j2 is not None:
                        pending.append((i + 1, "buy", j2, k, reserve))
                        res.n_replacements += 1
                        res.decisions.append((i, "replace", j2))
                    continue
                pool = core * sellable
                avail = float(pool.sum())
                amount = sleeve_now / p.n_names
                need = amount * (1.0 + bc) / (1.0 - sc)  # core sold: proceeds pay amount + cost
                from_cash = 0.0
                if need > avail:
                    # the core cannot pay in full (e.g. on the first day): cash pays the rest
                    need = avail
                    short = amount * (1.0 + bc) - avail * (1.0 - sc)
                    if short > cash:
                        amount = (avail * (1.0 - sc) + cash) / (1.0 + bc)
                        short = cash
                    from_cash = short
                if amount <= _EPS * equity_prev:
                    continue
                if avail > 0:
                    core -= pool * (need / avail)
                cash -= from_cash
                held[j], tranche_of[j] = amount, k
                bought += amount
                sold += need
                res.n_buys += 1
            # ---- settle: the core takes whatever equity the names do not hold. It only trades
            # on an event (a selection sell, a change of exposure, a core review), not on drift.
            idle = p.redeploy_idle and cash > (
                (1.0 - e_now) * (cash + float(core.sum()) + sum(held.values())) + 1e-6
            )
            settle = rebalance or sold_sel or idle or e_prev is None or abs(e_now - e_prev) > 1e-9
            e_prev = e_now
            if settle:
                names_v = sum(held.values())
                total = cash + float(core.sum()) + names_v
                target = max(e_now * total - names_v, 0.0)
                if rebalance:
                    goal = target * w_core
                    delta = goal - core
                    cut = (delta < -_EPS * total) & sellable
                    add = (delta > _EPS * total) & buyable
                    res.n_core_skipped += int(((delta < -_EPS * total) & ~sellable).sum())
                    res.n_core_skipped += int(((delta > _EPS * total) & ~buyable).sum())
                    got = float(-delta[cut].sum())
                    core[cut] += delta[cut]
                    cash += got * (1.0 - sc)
                    sold += got
                    b = float(delta[add].sum())
                    if b > 0:
                        scale = min(1.0, cash / (b * (1.0 + bc)))
                        core[add] += delta[add] * scale
                        cash -= b * scale * (1.0 + bc)
                        bought += b * scale
                else:
                    diff = target - float(core.sum())
                    if diff < -_EPS * total:
                        pool = core * sellable
                        avail = float(pool.sum())
                        amt = min(-diff, avail)
                        if amt > 0:
                            core -= pool * (amt / avail)
                            cash += amt * (1.0 - sc)
                            sold += amt
                    elif diff > _EPS * total:
                        amt = min(diff, cash / (1.0 + bc))
                        base = core * buyable
                        if base.sum() <= 0:
                            base = w_core * buyable
                        if amt > 0 and base.sum() > 0:
                            core += amt * base / base.sum()
                            cash -= amt * (1.0 + bc)
                            bought += amt
            equity = cash + float(core.sum()) + sum(held.values())
            res.ret[i] = equity / equity_prev - 1.0
            res.bought[i] = bought / equity_prev
            res.sold[i] = sold / equity_prev
            res.equity_share[i] = 1.0 - cash / equity if equity > 0 else 0.0
            mask = core > 0
            for j in held:
                mask[j] = True
            res.n_names[i] = int(mask.sum())
            res.n_selection[i] = len(held)
            equity_prev = equity
        # ---- decisions at the close of day i (rows <= i only)
        row = rank[i]
        if i == start or (i > start and (i - start - p.core_phase) % p.core_review_every == 0):
            member = np.isfinite(row) & (queue[i] != QUEUE_BUY)
            if p.core_drop_bottom_frac > 0:
                member &= row >= p.core_drop_bottom_frac
            if member.any():
                w = member / member.sum()
                pending.append((i + d, "core", -1, -1, w))
                res.decisions.append((i, "core", tuple(np.flatnonzero(member).tolist())))
        if (
            sel
            and i >= start + p.selection_phase
            and (i - start - p.selection_phase) % p.review_every == 0
        ):
            k = ((i - start - p.selection_phase) // p.review_every) % p.n_tranches
            sells = [
                j
                for j in held
                if tranche_of[j] == k and (np.isnan(row[j]) or row[j] < 1.0 - p.hold_top_frac)
            ]
            for j in sells:
                pending.append((i + d, "sell", j, k, None))
                res.decisions.append((i, "sell", j))
            keep = [j for j in held if tranche_of[j] == k and j not in sells]
            free = slots[k] - len(keep) - sum(1 for o in pending if o[1] == "buy" and o[3] == k)
            if free > 0:
                taken = set(held) | {o[2] for o in pending if o[1] == "buy"}
                sec_count: dict[object, int] = {}
                for j in taken:
                    sec_count[sector[j]] = sec_count.get(sector[j], 0) + 1
                e_dec = float(expo[i]) if p.use_exposure and expo is not None else 1.0
                sleeve = e_dec * (cash + float(core.sum()) + sum(held.values())) * p.capital
                cand = np.where(row >= 1.0 - p.buy_top_frac)[0]
                ordered = [int(j) for j in cand[np.argsort(-row[cand], kind="stable")]]
                for j in ordered:
                    if free <= 0:
                        break
                    if j in taken or sec_count.get(sector[j], 0) >= cap_per_sector:
                        continue
                    mv = median_value[i, j]
                    if not np.isfinite(mv) or sleeve / p.n_names > p.liquidity_cap * mv:
                        continue
                    pending.append((i + d, "buy", j, k, ordered))
                    res.decisions.append((i, "buy", j))
                    taken.add(j)
                    sec_count[sector[j]] = sec_count.get(sector[j], 0) + 1
                    free -= 1
    return res


def _replacement(
    reserve: list[int] | None,
    i: int,
    taken: set[int],
    sector: np.ndarray,
    median_value: np.ndarray,
    cap_per_sector: int,
    p: InvestedParams,
    sleeve_value: float,
) -> int | None:
    """Next candidate of the review (ranked on its decision day) that is not ``taken`` (held or
    pending) and passes the sector and liquidity caps as known at the close of day ``i``."""
    if not reserve:
        return None
    sec_count: dict[object, int] = {}
    for j in taken:
        sec_count[sector[j]] = sec_count.get(sector[j], 0) + 1
    for j in reserve:
        if j in taken or sec_count.get(sector[j], 0) >= cap_per_sector:
            continue
        mv = median_value[i, j]
        if not np.isfinite(mv) or sleeve_value * p.capital / p.n_names > p.liquidity_cap * mv:
            continue
        return j
    return None
