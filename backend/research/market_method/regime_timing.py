"""Entry and exit timing on top of the three-state plan: can candles and chart rules buy nearer the
bottom and sell nearer the top? (docs/reports/timing-and-codal-2026-11.md)

Base: the plan of regime_switch.py (breadth state with 5-day confirmation; falling -> 10 deepest
drawdowns, flat -> cash, rising -> 10 trend names; renewed every 20 trading days or on a state
change; decided at a close, filled at the next; 0.62% buy, 1.13% sell; cash earns the bond yield).
The book is split into 10 slots; each slot holds one name or cash.

Timing rules, all fixed before the run from earlier reports (none tuned here):
  entry
    rsi_cross   a name is bought only on the first close its 14-day RSI is back above 30 after
                being below (the one bottom trigger that held in both halves, entry-odds report),
                or at once if RSI is already above 30 and the name is not a dust pick; waits at
                most 10 days, else the slot stays in cash
    green_day   buy on the first up close (no blind buying on a red day), at most 10 days
    no_red6     skip names with 6+ red closes in a row (worse in both halves, entry-odds report)
    skip_dust   control: dust names are never bought (falling market = cash)
  exit
    trail10/15  sell a name when it closes 10% / 15% under its highest close since bought
    ma20        sell when the close falls under its 20-day mean
    runup50     sell when a name is up 50% since bought (sharp run-ups lagged, turning-points)
    take10      sell at +10% since bought (the "sell at the top" target)
A sold slot stays in cash until the next renewal.

Judged per period (O 2019-01..2023-03, A 2023-04..2024-12, B 2025-01 on): monthly growth, worst
fall, share of losing months. A rule counts only if it beats the base in both O and A and does
not lose in B. B was already seen in earlier studies.
Run from backend/ with the live env:  python research/market_method/regime_timing.py
Output: results_regime_timing.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import polars as pl

sys.argv = sys.argv[:1]  # treasure_hunt reads a horizon from argv
sys.path.insert(0, str(Path(__file__).parent))
import universe as uv
from regime_switch import BUY, PERIODS, SELL, market, picks, states
from treasure_hunt import panel

C = pl.col
G = "instrument_id"
HERE = Path(__file__).parent
H, TOP, WAIT = 20, 10, 10
PLAN = {"falling": "dust", "flat": "cash", "rising": "trend"}

ENTRY = ("now", "rsi_cross", "green_day", "no_red6", "skip_dust")
EXIT = ("none", "trail10", "trail15", "ma20", "runup50", "take10")


def extras(a: pl.DataFrame) -> pl.DataFrame:
    c = C("adj_close")
    d = c - c.shift(1)
    up = pl.when(d > 0).then(d).otherwise(0.0)
    dn = pl.when(d < 0).then(-d).otherwise(0.0)
    a = a.sort(G, "date").with_columns(
        rsi=(
            100 - 100 / (1 + up.ewm_mean(alpha=1 / 14) / (dn.ewm_mean(alpha=1 / 14) + 1e-12))
        ).over(G),
        ma20=c.rolling_mean(20).over(G),
        red=(d < 0).cast(pl.Int32).over(G),
    )
    # red streak: consecutive red closes ending today
    a = a.with_columns(
        grp=(C("red") == 0).cum_sum().over(G),
    ).with_columns(red_run=C("red").cum_sum().over(G, "grp"))
    return a.with_columns(rsi_prev=C("rsi").shift(1).over(G))


def simulate(
    a: pl.DataFrame,
    m: pl.DataFrame,
    st: list[str],
    entry: str,
    exit_: str,
    full: pl.DataFrame | None = None,
) -> dict:
    """Picks come from ``a`` (the day's universe); prices and exits from ``full``, which also has the
    days a held name spent outside the universe."""
    dates = m["date"].to_list()
    rf = m["rf"].to_list()
    by_day = {k[0]: g for k, g in a.partition_by("date", as_dict=True).items()}
    rows = by_day if full is None else {k[0]: g for k, g in full.partition_by("date", as_dict=True).items()}
    info = {
        d: {
            r[G]: r
            for r in g.select(
                G, "ret", "adj_close", "rsi", "rsi_prev", "ma20", "red_run", "queue_next"
            ).iter_rows(named=True)
        }
        for d, g in rows.items()
    }
    # slot: [value, name or None, status ('cash'|'wait'|'held'), entry px, peak px, waited]
    slots: list[list] = [[0.1, None, "cash", 0.0, 0.0, 0] for _ in range(TOP)]
    pending: list[int] | None = None
    age, cur, dust = 0, None, False
    path: list[float] = []
    inv: list[float] = []
    for i, d in enumerate(dates):
        today = info.get(d, {})
        for s in slots:  # earn the day
            if s[2] == "held" and s[1] in today:
                r = today[s[1]]["ret"]
                s[0] *= 1 + (0.0 if r is None else max(-0.15, min(0.15, r)))
            elif s[2] != "held":
                s[0] *= 1 + rf[i]
        if pending is not None:  # renewal at this close: pool and re-split
            total = sum(s[0] for s in slots)
            held = {s[1] for s in slots if s[2] == "held"}
            new = pending[:TOP]
            keep = held & set(new)
            sold = sum(s[0] for s in slots if s[2] == "held" and s[1] not in keep)
            total -= sold * SELL
            per = total / TOP
            slots = []
            for k in range(TOP):
                if k < len(new):
                    name = new[k]
                    px = today.get(name, {}).get("adj_close") or 0.0
                    if name in keep:
                        slots.append([per, name, "held", px, px, 0])
                    else:
                        slots.append([per, name, "wait", 0.0, 0.0, 0])
                else:
                    slots.append([per, None, "cash", 0.0, 0.0, 0])
            pending = None
        for s in slots:  # entries and exits at this close
            row = today.get(s[1]) if s[1] is not None else None
            if s[2] == "wait":
                ok = row is not None and not row["queue_next"]
                if ok and entry == "rsi_cross":
                    rs, rp = row["rsi"] or 50, row["rsi_prev"] or 50
                    ok = (rp < 30 <= rs) or (not dust and rs >= 30)
                elif ok and entry == "green_day":
                    ok = (row["red_run"] or 0) == 0 and (row["ret"] or 0) > 0
                if entry in ("now", "no_red6"):
                    ok = row is not None
                if entry == "skip_dust":  # control: falling market = cash
                    ok = row is not None and not dust
                if ok:
                    s[0] *= 1 - BUY
                    s[2], s[3], s[4] = "held", row["adj_close"], row["adj_close"]
                else:
                    s[5] += 1
                    if s[5] >= WAIT or entry in ("now", "no_red6", "skip_dust"):
                        s[1], s[2] = None, "cash"
            elif s[2] == "held" and row is not None:
                px = row["adj_close"]
                s[4] = max(s[4], px)
                g = px / s[3] - 1 if s[3] else 0.0
                out = (
                    (exit_ == "trail10" and px <= 0.90 * s[4])
                    or (exit_ == "trail15" and px <= 0.85 * s[4])
                    or (exit_ == "ma20" and row["ma20"] is not None and px < row["ma20"])
                    or (exit_ == "runup50" and g >= 0.50)
                    or (exit_ == "take10" and g >= 0.10)
                )
                if out:
                    s[0] *= 1 - SELL
                    s[1], s[2] = None, "cash"
        age += 1
        q = st[i]
        if (q != cur or age >= H) and d in by_day:
            act = PLAN[q]
            lst = picks(by_day[d], act)
            if entry == "no_red6" and lst:
                day = by_day[d]
                bad = set(day.filter(C("red_run") >= 6)[G].to_list())
                filt, rank, desc = (
                    (C("q_dd") == 0, "dd", False)
                    if act == "dust"
                    else ((C("q_r120") == 4) & (C("q_pos60") >= 3), "r120", True)
                )
                lst = (
                    day.filter(filt & ~C("queue_next").fill_null(False) & ~C(G).is_in(list(bad)))
                    .sort(rank, descending=desc, nulls_last=True)
                    .head(TOP)[G]
                    .to_list()
                )
            pending, dust, cur, age = lst, act == "dust", q, 0
        path.append(sum(s[0] for s in slots) * 10)
        inv.append(sum(s[0] for s in slots if s[2] == "held") / sum(s[0] for s in slots))
    p = np.array(path)
    out: dict = {}
    per = m["period"].to_list()
    for name in PERIODS:
        idx = [k for k, x in enumerate(per) if x == name]
        seg = p[idx[0] : idx[-1] + 1] / (p[idx[0] - 1] if idx[0] > 0 else 1.0)
        months = len(idx) / H
        mon = seg[H - 1 :: H] / np.concatenate([[1.0], seg[H - 1 :: H][:-1]]) - 1
        out[name] = {
            "per_month": float(seg[-1] ** (1 / months) - 1),
            "max_dd": float((seg / np.maximum.accumulate(seg) - 1).min()),
            "neg_months": float((mon < 0).mean()),
            "invested": float(np.mean([inv[k] for k in idx])),
        }
    return out


def main() -> None:
    full, _ids = panel(drop_queue=False, keep_out=True)
    full = extras(full)
    a = full.filter(C("in_u"))
    m = market(a)
    st = states(m, "breadth", 5)
    res: dict = {}
    for e in ENTRY:
        for x in EXIT:
            r = simulate(a, m, st, e, x, full)
            res[f"{e}/{x}"] = r
            print(
                f"{e:10s} {x:8s}",
                "  ".join(
                    f"{k} {v['per_month'] * 100:+.1f}% dd {v['max_dd'] * 100:.0f}% "
                    f"neg {v['neg_months'] * 100:.0f}% in {v['invested'] * 100:.0f}%"
                    for k, v in r.items()
                ),
                flush=True,
            )
    base = res["now/none"]
    for k, r in res.items():
        r["passes"] = all(r[p]["per_month"] > base[p]["per_month"] for p in ("O", "A")) and (
            r["B"]["per_month"] >= base["B"]["per_month"]
        )
    (HERE / f"results_regime_timing{uv.suffix()}.json").write_text(
        json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    print("passes:", [k for k, r in res.items() if r["passes"]])


if __name__ == "__main__":
    main()
