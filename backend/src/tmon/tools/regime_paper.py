"""The market-state plan, run forward on paper (docs/reports/regime-switch-2026-11.md,
docs/reports/timing-and-codal-2026-11.md).

Every close the plan reads the market state from breadth: the share of the day's universe above its
60-day mean. The universe is the ``universe_top`` stocks with the highest ``universe_window``-day
median traded value up to the previous close, so nothing from the day itself or later picks it
(docs/reports/survivorship-basket-2026-11.md). Until 2026-11-18 it was a 100-name basket frozen from
one day's traded value, which flattered every past number. At or below ``breadth_low`` the market
is falling, above ``breadth_high`` rising, flat in between; a new state counts only after it
held ``confirm_days`` closes in a row. Each state has its own action:

  falling  cash   out of stocks, earning the one-year bond yield
  flat     cash   the same
  rising   trend  the 10 best 120-day returns among stocks in the upper part of their 60-day range

Until 2026-11-18 a falling market bought "dust" (the 10 stocks deepest below their peak). With
buy-and-hold accounting dust earned no more than cash and fell twice as far, so it was dropped
before the paper account had made any trade (timing-and-codal report).

The book is ``top`` equal slots, each holding one name or cash. A held name whose close falls
under its ``exit_ma``-day mean is sold at the next close and its slot stays in cash until the next
renewal. A held name that leaves the universe keeps earning until it is sold; only new picks come
from the universe.

A decision is taken at a close when the state changes or ``renew_days`` trading days have passed
since the last renewal: enter (cash to stocks), exit (stocks to cash), switch (other stocks) or
wait (stay in cash); a sale under the mean is "sell". It is filled at the next close (a name
locked in a buy queue that day is skipped for the next one on the list), with 0.62% cost on what
is bought and 1.13% on what is sold.

Decisions already logged stay frozen: a later run only appends, so the test cannot be rewritten
after the fact. The account is compared with holding the whole universe and with cash.
Nothing here places an order.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from datetime import date
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
BUY, SELL = 0.0062, 0.0113
STATES = ("falling", "flat", "rising")
PLAN = {"falling": "cash", "flat": "cash", "rising": "trend"}
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


def panel(
    prices: pl.DataFrame, ids: list[int], ma: int = 20, top: int = 100, window: int = 20
) -> pl.DataFrame:
    """Per stock and day: return, drawdown from peak, 120-day return, 60-day range position and
    gap to the 60-day mean, whether the close is under its ``ma``-day mean, whether the day was
    locked up, ``in_u`` (among the day's ``top`` by ``window``-day median traded value up to the
    previous close) and quintiles among those members."""
    a = apply_adjustments(prices).filter((C("close") > 0) & C(G).is_in(ids))
    a = a.with_columns(C("date").cast(pl.Date)).sort(G, "date")
    c = C("adj_close")
    a = a.with_columns(
        ret=(c / c.shift(1) - 1).over(G),
        dd=(c / c.cum_max() - 1).over(G),
        r120=(c / c.shift(120) - 1).over(G),
        pos60=((c - c.rolling_min(60)) / (c.rolling_max(60) - c.rolling_min(60) + 1e-9)).over(G),
        gap60=(c / c.rolling_mean(60) - 1).over(G),
        under_ma=(c < c.rolling_mean(ma)).over(G),
        buy_lock=((C("high") == C("low")) & (C("close") > C("close").shift(1))).over(G),
        med=C("value").cast(pl.Float64).rolling_median(window).shift(1).over(G),
    ).filter(C("date") >= pl.date(2019, 1, 1))
    a = a.with_columns(
        in_u=(C("med").rank("ordinal", descending=True).over("date") <= top).fill_null(False)
    )
    for f in ("dd", "r120", "pos60"):
        v = pl.when(C("in_u")).then(C(f))
        a = a.with_columns(
            ((v.rank("average").over("date") - 1) / (v.count().over("date") - 1) * 5)
            .fill_nan(None)
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
    """The paper account while it is replayed: one value per held name, the rest in cash."""

    cash: float
    hold: dict[int, float] = field(default_factory=dict)  # name -> value, in buying order
    age: int = 0  # trading days since the last renewal
    state: str | None = None  # confirmed state at the last decision

    @property
    def value(self) -> float:
        return self.cash + sum(self.hold.values())

    def renew(self, new: list[int], top: int) -> None:
        """Sell what is not in ``new``, then split the whole book into ``top`` equal slots."""
        total = self.value - SELL * sum(v for x, v in self.hold.items() if x not in new)
        per = total / top
        self.hold = {x: per if x in self.hold else per * (1 - BUY) for x in new}
        self.cash = per * (top - len(new))

    def sell(self, names: list[int]) -> None:
        for x in names:
            if x in self.hold:
                self.cash += self.hold.pop(x) * (1 - SELL)


def replay(
    a: pl.DataFrame,
    rf: dict[date, float],
    cfg: RegimePlanCfg,
    frozen: list[dict[str, Any]],
    symbols: dict[int, str],
) -> dict[str, Any]:
    """Run the plan from ``cfg.start`` over the data. Logged decisions in ``frozen`` are reused
    as they were; new decisions are added only after the last logged date. Breadth, the universe
    line and new picks use the rows with ``in_u`` (all rows when the column is absent); returns,
    queues and the sale under the mean use every row."""
    u = a.filter(C("in_u")) if "in_u" in a.columns else a
    m = (
        u.group_by("date")
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
    under = {
        d: set(g.filter(C("under_ma").fill_null(False))[G].to_list())
        for (d,), g in a.group_by("date")
    }
    by_day = {d: g for (d,), g in u.partition_by("date", as_dict=True).items()}
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
            book.hold = {x: v * (1 + rets[d].get(x, 0.0)) for x, v in book.hold.items()}
            book.cash *= 1 + r_cash
            basket *= 1 + m["m_ret"][i]
            cash *= 1 + r_cash
        else:
            basket *= 1 - BUY
        if pending is not None and pending["kind"] == "sell":  # fill yesterday's sale
            book.sell([sym_id[x] for x in pending["sold"]])
            pending["filled_on"] = str(d)
            pending = None
        elif pending is not None:  # fill yesterday's renewal at this close
            locked = locks.get(d, set())
            new = [sym_id[x] for x in pending["ranked"] if sym_id[x] not in locked][: cfg.top]
            book.renew(new, cfg.top)
            book.age = 0
            pending["filled_on"] = str(d)
            pending["names"] = [symbols[x] for x in new]  # the log entry itself
            pending = None
        book.age += 1
        ds = str(d)
        entry: dict[str, Any] | None = None
        if ds in old:
            entry = {k: v for k, v in old[ds].items() if k not in ("names", "filled_on")}
        elif ds > last_frozen and (st[i] != book.state or book.age >= cfg.renew_days):
            ranked = [symbols[x] for x in shortlist(by_day.get(d, u.clear()), PLAN[st[i]])]
            entry = {
                "date": ds,
                "state": st[i],
                "breadth": round(float(m["breadth"][i]), 4),
                "action": PLAN[st[i]],
                "kind": kind(not book.hold, not ranked),
                "ranked": ranked,
            }
        elif ds > last_frozen and (out := [x for x in book.hold if x in under.get(d, set())]):
            entry = {
                "date": ds,
                "state": st[i],
                "breadth": round(float(m["breadth"][i]), 4),
                "action": f"under_ma{cfg.exit_ma}",
                "kind": "sell",
                "ranked": [],
                "sold": [symbols[x] for x in out],
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
            | {"names": pending["ranked"][: cfg.top], "sold": pending.get("sold")}
            if pending is not None
            else None
        ),
        "days_to_renew": max(cfg.renew_days - book.age, 0) if book.hold else None,
        "bond_yield": yld,
        "path": path,
        "log": log,
    }


def run() -> dict[str, Any]:
    cfg = get_engine_config().regime_plan
    previous = read_artifact(KEY)
    with session_scope() as s:
        prices, _clients, _sectors = load_inputs(s)
        _idx, rf = load_benchmark_inputs(s)
        rows = s.execute(
            select(Instrument.id, Instrument.symbol_fa)
            .where(Instrument.instrument_type == "stock")
            .order_by(Instrument.id)
        ).all()
    symbols: dict[int, str] = {}
    for iid, sym in rows:  # one id per symbol, the lowest
        if sym not in symbols.values():
            symbols[iid] = sym
    a = panel(prices, list(symbols), cfg.exit_ma, cfg.universe_top, cfg.universe_window)
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
        "exit_ma": cfg.exit_ma,
        "universe": f"top {cfg.universe_top} by {cfg.universe_window}-day median value",
        **res,
    }
    write_artifact(KEY, doc)
    return {k: doc[k] for k in ("as_of", "state", "breadth", "holding", "pending")}


def main() -> None:
    print(json.dumps(run(), ensure_ascii=False))


if __name__ == "__main__":
    main()
