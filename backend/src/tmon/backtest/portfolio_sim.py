"""R3 (ADR 0003 section 6): the low-turnover baseline portfolio, simulated day by day.

* ``n_names`` equal-weight slots split into ``n_tranches`` tranches; every ``review_every`` days one
  tranche is reviewed (weekly review in four tranches);
* a held name is sold at its tranche's review only when it left the top ``hold_top_frac`` of the
  day's universe by the composite score, or left the universe; empty slots are filled from the top
  ``buy_top_frac`` (the hold/buy gap is the turnover buffer), best score first, subject to the
  sector cap (count of names), the name cap and the liquidity cap;
* an order decided at the close of ``t`` executes at the close of ``t + entry_delay``: a buy into a
  buy queue is cancelled, a sell into a sell queue is impossible and is retried the next day;
* costs per side: commission (+ sales tax on sells) from ``market_rules`` plus half the configured
  round-trip slippage, scaled by ``cost_multiplier`` (robustness gate G5).

Pure numpy over (day x instrument) matrices; the loop is over days, not over market rows.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

QUEUE_BUY, QUEUE_SELL = 1, 2


@dataclass(frozen=True)
class BookParams:
    n_names: int
    n_tranches: int
    review_every: int
    buy_top_frac: float
    hold_top_frac: float
    sector_cap_pct: float
    name_cap_pct: float
    liquidity_cap: float
    capital: float
    entry_delay: int = 1
    cost_multiplier: float = 1.0


@dataclass
class BookResult:
    ret: np.ndarray  # daily return of the equity sleeve, after costs
    buy_frac: np.ndarray  # value bought that day / sleeve equity (one-way turnover)
    n_held: np.ndarray
    n_buys: int
    n_cancelled_buys: int
    n_postponed_sells: int


def simulate_book(
    ret: np.ndarray,
    rank: np.ndarray,
    queue: np.ndarray,
    median_value: np.ndarray,
    sector: np.ndarray,
    buy_cost: np.ndarray,
    sell_cost: np.ndarray,
    p: BookParams,
    start: int,
) -> BookResult:
    """All matrices are ``(days, instruments)`` except the cost vectors ``(days,)`` and
    ``sector`` ``(instruments,)``. ``rank`` is the percentile rank of the composite score inside
    the day's universe (NaN: not in the universe). Decisions begin at day index ``start``."""
    if p.n_names * p.name_cap_pct < 1.0 - 1e-9:
        raise ValueError("name cap is below 1 / n_names: the book cannot be fully invested")
    t_days = ret.shape[0]
    cap_per_sector = max(int(p.sector_cap_pct * p.n_names + 1e-9), 1)
    slots = [
        p.n_names // p.n_tranches + (k < p.n_names % p.n_tranches) for k in range(p.n_tranches)
    ]
    cash = 1.0
    held: dict[int, float] = {}
    tranche_of: dict[int, int] = {}
    pending: list[tuple[int, str, int, int]] = []  # (exec_day, side, instrument, tranche)
    out = np.zeros(t_days)
    buy_frac = np.zeros(t_days)
    n_held = np.zeros(t_days, dtype=int)
    equity_prev = 1.0
    n_buys = n_cancel = n_post = 0
    for i in range(1, t_days):
        for j in held:
            held[j] *= 1.0 + ret[i, j]
        # ---- execute orders due today
        due = [o for o in pending if o[0] == i]
        pending = [o for o in pending if o[0] != i]
        for _, side, j, k in sorted(due, key=lambda o: o[1] != "sell"):  # sells fund buys
            if side == "sell":
                if j not in held:
                    continue
                if queue[i, j] == QUEUE_SELL:
                    pending.append((i + 1, "sell", j, k))
                    n_post += 1
                    continue
                cash += held.pop(j) * (1.0 - sell_cost[i] * p.cost_multiplier)
                tranche_of.pop(j, None)
            else:
                if j in held:
                    continue
                if queue[i, j] == QUEUE_BUY:
                    n_cancel += 1
                    continue
                cost = buy_cost[i] * p.cost_multiplier
                equity = cash + sum(held.values())
                amount = min(equity / p.n_names, cash / (1.0 + cost))
                if amount <= 0:
                    continue
                cash -= amount * (1.0 + cost)
                held[j], tranche_of[j] = amount, k
                buy_frac[i] += amount / equity_prev
                n_buys += 1
        equity = cash + sum(held.values())
        out[i] = equity / equity_prev - 1.0
        equity_prev = equity
        n_held[i] = len(held)
        # ---- weekly review of one tranche
        if i < start or (i - start) % p.review_every:
            continue
        k = ((i - start) // p.review_every) % p.n_tranches
        row = rank[i]
        sells = [
            j
            for j in held
            if tranche_of[j] == k and (np.isnan(row[j]) or row[j] < 1.0 - p.hold_top_frac)
        ]
        for j in sells:
            pending.append((i + p.entry_delay, "sell", j, k))
        keep = [j for j in held if tranche_of[j] == k and j not in sells]
        free = slots[k] - len(keep) - sum(1 for o in pending if o[1] == "buy" and o[3] == k)
        if free <= 0:
            continue
        taken = set(held) | {o[2] for o in pending if o[1] == "buy"}
        sec_count: dict[object, int] = {}
        for j in taken:
            sec_count[sector[j]] = sec_count.get(sector[j], 0) + 1
        sleeve_value = equity_prev * p.capital
        cand = np.where(row >= 1.0 - p.buy_top_frac)[0]
        for j in cand[np.argsort(-row[cand])]:
            if free <= 0:
                break
            if j in taken or sec_count.get(sector[j], 0) >= cap_per_sector:
                continue
            mv = median_value[i, j]
            if not np.isfinite(mv) or sleeve_value / p.n_names > p.liquidity_cap * mv:
                continue
            pending.append((i + p.entry_delay, "buy", int(j), k))
            taken.add(int(j))
            sec_count[sector[j]] = sec_count.get(sector[j], 0) + 1
            free -= 1
    return BookResult(out, buy_frac, n_held, n_buys, n_cancel, n_post)
