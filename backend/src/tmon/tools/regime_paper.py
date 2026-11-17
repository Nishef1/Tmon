"""The market-state plan, run forward on paper (docs/reports/regime-switch-2026-11.md).

Every close the plan reads the market state from breadth: the share of the frozen 100-stock liquid
basket above its 60-day mean. At or below ``breadth_low`` the market is falling, above
``breadth_high`` rising, flat in between; a new state counts only after it held ``confirm_days``
closes in a row. Each state has its own action, chosen in the study from 2019-2024 data:

  falling  dust   the 10 basket stocks deepest below their own peak (bottom fifth by drawdown)
  flat     cash   out of stocks, earning the one-year bond yield
  rising   trend  the 10 best 120-day returns among stocks in the upper part of their 60-day range

A decision is taken at a close when the state changes or ``renew_days`` trading days have passed
since the last fill: enter (cash to stocks), exit (stocks to cash), switch (other stocks) or wait
(stay in cash). It is filled at the next close (a name locked in a buy queue that day is skipped
for the next one on the list), with 0.62% cost on what is bought and 1.13% on what is sold.

Decisions already logged stay frozen: a later run only appends, so the test cannot be rewritten
after the fact. The account is compared with holding the whole basket and with cash.
Nothing here places an order.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Any

import polars as pl
from sqlalchemy import select

from tmon.core.db import session_scope
from tmon.core.engine_config import RegimePlanCfg, get_engine_config
from tmon.core.timeutil import utcnow
from tmon.features.adjustment import apply_adjustments
from tmon.features.store import load_benchmark_inputs, load_inputs
from tmon.storage.models import Instrument
from tmon.storage.objectstore import read_artifact, write_artifact

KEY = "v2/regime_paper.json"
BASKET_FILE = Path(__file__).resolve().parents[4] / "data" / "liquid-basket.json"
BUY, SELL = 0.0062, 0.0113
STATES = ("falling", "flat", "rising")
PLAN = {"falling": "dust", "flat": "cash", "rising": "trend"}
SHORTLIST = 20  # ranked names kept per decision, so a queue-locked name can be replaced
C = pl.col
G = "instrument_id"


def raw_state(breadth: float | None, lo: float, hi: float) -> str:
    if breadth is None or math.isnan(breadth):
        return "flat"
    return "falling" if breadth <= lo else "rising" if breadth > hi else "flat"


def confirmed(raw: list[str], confirm: int) -> tuple[list[str], list[int]]:
    """The confirmed state per day and how many days in a row the raw state has held."""
    out, runs, cur, run, last = [], [], "flat", 0, None
    for s in raw:
        run = run + 1 if s == last else 1
        last = s
        if run >= confirm:
            cur = s
        out.append(cur)
        runs.append(run)
    return out, runs


def kind(in_cash: bool, to_cash: bool) -> str:
    if to_cash:
        return "wait" if in_cash else "exit"
    return "enter" if in_cash else "switch"


def panel(prices: pl.DataFrame, ids: list[int]) -> pl.DataFrame:
    """Per stock and day: return, drawdown from peak, 120-day return, 60-day range position and
    gap to the 60-day mean, quintiles within the day, and whether the day was locked up."""
    a = apply_adjustments(prices).filter((C("close") > 0) & C(G).is_in(ids))
    a = a.with_columns(C("date").cast(pl.Date)).sort(G, "date")
    c = C("adj_close")
    a = a.with_columns(
        ret=(c / c.shift(1) - 1).over(G),
        dd=(c / c.cum_max() - 1).over(G),
        r120=(c / c.shift(120) - 1).over(G),
        pos60=((c - c.rolling_min(60)) / (c.rolling_max(60) - c.rolling_min(60) + 1e-9)).over(G),
        gap60=(c / c.rolling_mean(60) - 1).over(G),
        buy_lock=((C("high") == C("low")) & (C("close") > C("close").shift(1))).over(G),
    ).filter(C("date") >= pl.date(2019, 1, 1))
    for f in ("dd", "r120", "pos60"):
        a = a.with_columns(
            ((C(f).rank("average").over("date") - 1) / (C(f).count().over("date") - 1) * 5)
            .floor()
            .clip(0, 4)
            .cast(pl.Int8)
            .alias("q_" + f)
        )
    return a


def shortlist(day: pl.DataFrame, action: str) -> list[int]:
    if action == "dust":
        d = day.filter(C("q_dd") == 0).sort("dd", nulls_last=True)
    elif action == "trend":
        d = day.filter((C("q_r120") == 4) & (C("q_pos60") >= 3))
        d = d.sort("r120", descending=True, nulls_last=True)
    else:
        return []
    return d.head(SHORTLIST)[G].to_list()


@dataclass
class Book:
    """The paper account while it is replayed."""

    value: float
    hold: list[int] = field(default_factory=list)
    age: int = 0  # trading days since the last fill
    state: str | None = None  # confirmed state at the last decision


def replay(
    a: pl.DataFrame,
    rf: dict[date, float],
    cfg: RegimePlanCfg,
    frozen: list[dict[str, Any]],
    symbols: dict[int, str],
) -> dict[str, Any]:
    """Run the plan from ``cfg.start`` over the data. Logged decisions in ``frozen`` are reused
    as they were; new decisions are added only after the last logged date."""
    m = (
        a.group_by("date")
        .agg(m_ret=C("ret").clip(-0.15, 0.15).mean(), breadth=(C("gap60") > 0).mean())
        .sort("date")
    )
    dates: list[date] = m["date"].to_list()
    raw = [raw_state(b, cfg.breadth_low, cfg.breadth_high) for b in m["breadth"].to_list()]
    st, runs = confirmed(raw, cfg.confirm_days)
    rets = {
        d: dict(zip(g[G].to_list(), g["ret"].fill_null(0).clip(-0.15, 0.15).to_list(), strict=True))
        for (d,), g in a.group_by("date")
    }
    locks = {
        d: set(g.filter(C("buy_lock").fill_null(False))[G].to_list())
        for (d,), g in a.group_by("date")
    }
    by_day = {d: g for (d,), g in a.partition_by("date", as_dict=True).items()}
    sym_id = {v: k for k, v in symbols.items()}
    old = {x["date"]: x for x in frozen}
    last_frozen = max(old) if old else ""
    yld = 0.0
    book = Book(cfg.capital)
    basket = cash = cfg.capital
    pending: dict[str, Any] | None = None
    log: list[dict[str, Any]] = []
    path: list[dict[str, Any]] = []
    for i, d in enumerate(dates):
        if d < cfg.start:
            continue
        yld = rf.get(d, yld)
        r_cash = (1 + yld) ** (1 / 250) - 1
        if path:  # earn today's return on what was held since the last close
            r = (
                sum(rets[d].get(x, 0.0) for x in book.hold) / len(book.hold)
                if book.hold
                else r_cash
            )
            book.value *= 1 + r
            basket *= 1 + m["m_ret"][i]
            cash *= 1 + r_cash
        else:
            basket *= 1 - BUY
        if pending is not None:  # fill yesterday's decision at this close
            locked = locks.get(d, set())
            new = [sym_id[x] for x in pending["ranked"] if sym_id[x] not in locked][: cfg.top]
            sold = len(set(book.hold) - set(new)) / len(book.hold) if book.hold else 0.0
            bought = len(set(new) - set(book.hold)) / len(new) if new else 0.0
            book.value *= (1 - SELL * sold) * (1 - BUY * bought)
            book.hold, book.age = new, 0
            pending["filled_on"] = str(d)
            pending["names"] = [symbols[x] for x in new]  # the log entry itself
            pending = None
        book.age += 1
        ds = str(d)
        entry: dict[str, Any] | None = None
        if ds in old:
            entry = {k: v for k, v in old[ds].items() if k not in ("names", "filled_on")}
        elif ds > last_frozen and (st[i] != book.state or book.age >= cfg.renew_days):
            ranked = [symbols[x] for x in shortlist(by_day[d], PLAN[st[i]])]
            entry = {
                "date": ds,
                "state": st[i],
                "breadth": round(float(m["breadth"][i]), 4),
                "action": PLAN[st[i]],
                "kind": kind(not book.hold, not ranked),
                "ranked": ranked,
            }
        if entry is not None:
            book.state = entry["state"]
            log.append(entry)
            pending = entry
        path.append(
            {"date": ds, "plan": round(book.value), "basket": round(basket), "cash": round(cash)}
        )
    i = len(dates) - 1
    return {
        "as_of": str(dates[-1]),
        "breadth": round(float(m["breadth"][i]), 4),
        "raw_state": raw[i],
        "run_days": runs[i],
        "state": st[i],
        "action": PLAN[st[i]],
        "holding": [symbols[x] for x in book.hold],
        "pending": (
            {k: pending[k] for k in ("date", "kind", "action")}
            | {"names": pending["ranked"][: cfg.top]}
            if pending is not None
            else None
        ),
        "days_to_renew": max(cfg.renew_days - book.age, 0) if book.hold else None,
        "bond_yield": yld,
        "path": path,
        "log": log,
    }


def _universe(previous: dict[str, Any] | None) -> list[str]:
    """The basket is frozen at the first run, so the test always trades the same 100 names."""
    if previous and previous.get("universe"):
        return list(previous["universe"])
    return list(json.loads(BASKET_FILE.read_text(encoding="utf-8"))["symbols"])


def run() -> dict[str, Any]:
    cfg = get_engine_config().regime_plan
    previous = read_artifact(KEY)
    universe = _universe(previous)
    with session_scope() as s:
        prices, _clients, _sectors = load_inputs(s)
        _idx, rf = load_benchmark_inputs(s)
        rows = s.execute(
            select(Instrument.id, Instrument.symbol_fa)
            .where(Instrument.instrument_type == "stock")
            .order_by(Instrument.id)
        ).all()
    symbols: dict[int, str] = {}
    for iid, sym in rows:
        if sym in universe and sym not in symbols.values():
            symbols[iid] = sym
    a = panel(prices, list(symbols))
    yields = dict(zip(rf["date"].to_list(), rf["value"].to_list(), strict=True))
    res = replay(a, yields, cfg, (previous or {}).get("log") or [], symbols)
    doc = {
        "checked_at": utcnow().isoformat(timespec="seconds"),
        "start": str(cfg.start),
        "capital": cfg.capital,
        "edges": [cfg.breadth_low, cfg.breadth_high],
        "confirm_days": cfg.confirm_days,
        "renew_days": cfg.renew_days,
        "plan": PLAN,
        "universe": universe,
        **res,
    }
    write_artifact(KEY, doc)
    return {k: doc[k] for k in ("as_of", "state", "breadth", "holding", "pending")}


def main() -> None:
    print(json.dumps(run(), ensure_ascii=False))


if __name__ == "__main__":
    main()
