"""Read the market state (rising, flat, falling), then take the action that did best in that state:
enter, exit to cash, switch names, or wait. (docs/reports/regime-switch-2026-11.md)

State: the equal-weight 100-stock basket, point in time. Three readings are compared:
  trend    60-day basket return in terciles
  breadth  share of stocks above their 60-day mean, in terciles
  both     rising = both in the top tercile, falling = both in the bottom one, else flat
Tercile edges come from O and A only (O 2019-01..2023-03, A 2023-04..2024-12); B (2025-01 on) is
the check. A state counts only after it held `confirm` days in a row.

Actions (10 names, equal weight): cash at the one-year bond yield (rf_1y_ytm), the whole basket,
top individual buying power (5 days), trend (top 120-day return in the upper 60-day range), dust
(deepest drawdown from peak), dip + power (a mild 5-day dip with strong buying power), low
volatility. For each state, the action with the best weaker-of-O-and-A 20-day mean (after the
1.75% cost) is picked.

The policy is then simulated day by day: decided at a close, traded at the next close, names
renewed every 20 trading days or when the state changes; cost 0.62% on what is bought and 1.13% on
what is sold. Compared with holding the basket and with cash, per period.
Run from backend/ with the live env:  python research/market_method/regime_switch.py
Output: results_regime_switch.json
"""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

import numpy as np
import polars as pl

sys.path.insert(0, str(Path(__file__).parent))
from fundamentals_study import DB
from treasure_hunt import panel

C = pl.col
G = "instrument_id"
HERE = Path(__file__).parent
H = 20
TOP = 10
BUY, SELL = 0.0062, 0.0113
COST = BUY + SELL
PERIODS = {"O": ("2019-01-01", "2023-04-01"), "A": ("2023-04-01", "2025-01-01"), "B": ("2025-01-01", "2100-01-01")}  # fmt: skip
STATES = ("falling", "flat", "rising")

ACTIONS: dict[str, tuple[pl.Expr | None, str | None, bool]] = {
    # name: (stock filter, rank column, descending)
    "cash": (None, None, False),
    "basket": (pl.lit(True), None, False),
    "power": (pl.lit(True), "pow5", True),
    "trend": ((C("q_r120") == 4) & (C("q_pos60") >= 3), "r120", True),
    "dust": (C("q_dd") == 0, "dd", False),
    "dip_power": ((C("q_r5") == 1) & (C("q_pow5") >= 3), "pow5", True),
    "low_vol": (pl.lit(True), "vol20", False),
}


def rf_daily() -> pl.DataFrame:
    rows = (
        sqlite3.connect(DB, uri=True)
        .execute(
            "select ref_period, value from macro_series where series = 'rf_1y_ytm' order by ref_period"
        )
        .fetchall()
    )
    return (
        pl.DataFrame(rows, schema={"date": pl.Utf8, "y": pl.Float64}, orient="row")
        .with_columns(C("date").str.to_date())
        .with_columns(rf=(1 + C("y")) ** (1 / 250) - 1)
        .select("date", "rf")
    )


def market(a: pl.DataFrame) -> pl.DataFrame:
    m = (
        a.group_by("date")
        .agg(m_ret=C("ret").clip(-0.15, 0.15).mean(), breadth=(C("gap60") > 0).mean())
        .sort("date")
        .with_columns(idx=(1 + C("m_ret").fill_null(0)).cum_prod())
        .with_columns(m_r60=C("idx") / C("idx").shift(60) - 1)
    )
    m = m.join_asof(rf_daily().sort("date"), on="date", strategy="backward")
    return m.with_columns(
        rf=C("rf").fill_null(strategy="backward"),
        period=pl.when(C("date") < pl.date(2023, 4, 1))
        .then(pl.lit("O"))
        .when(C("date") < pl.date(2025, 1, 1))
        .then(pl.lit("A"))
        .otherwise(pl.lit("B")),
    )


def states(m: pl.DataFrame, kind: str, confirm: int) -> list[str]:
    fit = m.filter(C("period") != "B")
    tr = (fit["m_r60"].quantile(1 / 3), fit["m_r60"].quantile(2 / 3))
    br = (fit["breadth"].quantile(1 / 3), fit["breadth"].quantile(2 / 3))

    def terc(v: float | None, e: tuple) -> int:
        if v is None or v != v:
            return 1
        return 0 if v <= e[0] else 2 if v > e[1] else 1

    raw = []
    for r60, b in zip(m["m_r60"].to_list(), m["breadth"].to_list(), strict=True):
        t, w = terc(r60, tr), terc(b, br)
        s = t if kind == "trend" else w if kind == "breadth" else (t if t == w else 1)
        raw.append(STATES[s])
    out, cur, run, last = [], "flat", 0, None
    for s in raw:
        run = run + 1 if s == last else 1
        last = s
        if run >= confirm:
            cur = s
        out.append(cur)
    return out


def picks(day: pl.DataFrame, action: str) -> list[int]:
    filt, rank, desc = ACTIONS[action]
    if filt is None:
        return []
    d = day.filter(filt & ~C("queue_next").fill_null(False))
    if rank is None:
        return d[G].to_list()
    return d.sort(rank, descending=desc, nulls_last=True).head(TOP)[G].to_list()


def action_table(a: pl.DataFrame, m: pl.DataFrame, st: list[str]) -> dict:
    """Mean 20-day return (after cost) of each action on days in each state, per period."""
    s = m.select("date", "period", "rf").with_columns(state=pl.Series(st))
    d = a.filter(~C("queue_next").fill_null(False) & C("f20").is_not_null()).join(s, on="date")
    out: dict = {}
    for act, (filt, rank, desc) in ACTIONS.items():
        if filt is None:
            r = s.with_columns(r=(1 + C("rf")) ** H - 1).select("date", "period", "state", "r")
        else:
            x = d.filter(filt)
            if rank is not None:
                x = (
                    x.sort("date", rank, descending=[False, desc], nulls_last=True)
                    .group_by("date", maintain_order=True)
                    .head(TOP)
                )
            r = x.group_by("date", "period", "state").agg(r=C("f20").mean())
        t = r.group_by("period", "state").agg(mean=C("r").mean(), n=pl.len())
        out[act] = {f"{p}|{q}": (mn, n) for p, q, mn, n in t.iter_rows()}
    return out


def choose(tab: dict) -> dict[str, str]:
    best = {}
    for q in STATES:
        score = {}
        for act, v in tab.items():
            o, a_ = v.get(f"O|{q}"), v.get(f"A|{q}")
            if o and a_:
                score[act] = min(o[0], a_[0])
        best[q] = max(score, key=lambda k: score[k])
    return best


def simulate(a: pl.DataFrame, m: pl.DataFrame, st: list[str], plan: dict[str, str]) -> dict:
    dates = m["date"].to_list()
    rets = {
        k[0]: dict(
            zip(g[G].to_list(), g["ret"].fill_null(0).clip(-0.15, 0.15).to_list(), strict=True)
        )
        for k, g in a.group_by("date")
    }
    by_day = dict(a.partition_by("date", as_dict=True))
    rf = m["rf"].to_list()
    hold: list[int] = []
    in_cash = True
    pending: tuple[list[int], bool] | None = None
    age, cur_state = 0, None
    val = 1.0
    path, log = [], []
    for i, dt in enumerate(dates):
        r = rf[i] if in_cash or not hold else float(np.mean([rets[dt].get(x, 0.0) for x in hold]))
        val *= 1 + r
        if pending is not None:  # trade at this close
            new, cash = pending
            old = set(hold) if not in_cash else set()
            nw = set(new) if not cash else set()
            if old or nw:
                sold = len(old - nw) / max(len(old), 1) if old else 0.0
                bought = len(nw - old) / max(len(nw), 1) if nw else 0.0
                val *= (1 - SELL * sold) * (1 - BUY * bought)
            hold, in_cash, age = new, cash, 0
            pending = None
        age += 1
        q = st[i]
        act = plan[q]
        if q != cur_state or age >= H:
            if (dt,) in by_day:
                new = picks(by_day[(dt,)], act)
                cash = act == "cash" or not new
                kind = (
                    "exit" if cash and not in_cash
                    else "wait" if cash
                    else "enter" if in_cash
                    else "switch"
                )  # fmt: skip
                log.append(kind)
                pending = (new, cash)
            cur_state = q
        path.append(val)
    p = np.array(path)
    out = {}
    per = m["period"].to_list()
    for name in PERIODS:
        idx = [k for k, x in enumerate(per) if x == name]
        if not idx:
            continue
        seg = p[idx[0] : idx[-1] + 1] / (p[idx[0] - 1] if idx[0] > 0 else 1.0)
        months = len(idx) / H
        monthly = seg[H - 1 :: H] / np.concatenate([[1.0], seg[H - 1 :: H][:-1]]) - 1
        out[name] = {
            "growth": float(seg[-1]),
            "per_month": float(seg[-1] ** (1 / months) - 1),
            "max_dd": float((seg / np.maximum.accumulate(seg) - 1).min()),
            "neg_months": float((monthly < 0).mean()),
        }
    out["actions"] = {k: log.count(k) for k in ("enter", "exit", "switch", "wait")}
    return out


def main() -> None:
    a, _ids = panel(drop_queue=False)
    m = market(a)
    res: dict = {}
    for kind in ("trend", "breadth", "both"):
        for confirm in (1, 5):
            st = states(m, kind, confirm)
            tab = action_table(a, m, st)
            plan = choose(tab)
            sim = simulate(a, m, st, plan)
            share = {q: st.count(q) / len(st) for q in STATES}
            key = f"{kind}/confirm{confirm}"
            res[key] = {"plan": plan, "share": share, "sim": sim, "table": tab}
            print(key, plan, {k: v for k, v in sim.items()})
    for base in ("basket", "cash", "power", "trend"):
        st = ["flat"] * m.height
        sim = simulate(a, m, st, dict.fromkeys(STATES, base))
        res[f"always {base}"] = {"sim": sim}
        print("always", base, sim)
    (HERE / "results_regime_switch.json").write_text(
        json.dumps(res, ensure_ascii=False, indent=1, default=str), encoding="utf-8"
    )


if __name__ == "__main__":
    main()
