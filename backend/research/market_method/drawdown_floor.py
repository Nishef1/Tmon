"""Staged buying at each stock's usual drawdown floor, from a Telegram educator's note.
(docs/reports/drawdown-floor-2026-11.md)

The claim: every stock falls by a fairly steady depth from its peak. Wait for that depth and buy
in steps: step 1 just before the usual depth, step 2 at it, steps 3-4 deeper. Buy the stock
"sitting in the dust", not the one with many green candles; the company must be sound.

Exact rules, 100-symbol liquid basket, adjusted closes:
  peak      highest close so far; an episode runs from one new high to the next
  depth     the lowest close / peak - 1 inside an episode; episodes shallower than -20% are ignored
  usual     median depth of the stock's completed episodes that ended before the day (at least 2),
            so nothing from the future is used
  steps     S1 = 0.75 x usual, S2 = 1.00 x usual (the floor), S3 = 1.15 x, S4 = 1.30 x
            each fires on the first close at or below its level inside the current episode
  sound     latest filing known that day: EPS (TTM) > 0 and liabilities / assets < 0.7
  GREEN     control for "many green candles": close at a 60-day high after 5 up days of the last 7
Each step is an event; entry = close of t+1, hold 60 and 250 trading days, cost 1.75% round
trip, excess over the basket mean on the same entry day. Events from 2023-04 (last three years),
both halves. Also: does the usual depth repeat? (correlation of the past median with the next
episode's depth, and how often the next trough fell inside the usual range [p25, p75]).
Run from backend/ with the live env:  python research/market_method/drawdown_floor.py
Output: results_drawdown_floor.json
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import polars as pl

sys.path.insert(0, str(Path(__file__).parent))
import fundamental_model as fm

from tmon.core.db import session_scope
from tmon.features.adjustment import apply_adjustments
from tmon.features.store import load_inputs

C = pl.col
G = "instrument_id"
HERE = Path(__file__).parent
COST = 0.0175
MIN_DEPTH = -0.20
FROM = np.datetime64("2023-04-01")
STEPS = {"S1": 0.75, "S2": 1.00, "S3": 1.15, "S4": 1.30}


def episodes(close: np.ndarray) -> list[tuple[int, int, float]]:
    """Completed episodes as (trough index, end index = new high, depth)."""
    out = []
    peak, start, low, low_i = close[0], 0, close[0], 0
    for i in range(1, len(close)):
        if close[i] > peak:
            d = low / peak - 1
            if i > start + 1 and d <= MIN_DEPTH:
                out.append((low_i, i, d))
            peak, start, low, low_i = close[i], i, close[i], i
        elif close[i] < low:
            low, low_i = close[i], i
    return out


def scan(dates: np.ndarray, close: np.ndarray) -> tuple[list[dict], list[dict], dict]:
    eps = episodes(close)
    ev: list[dict] = []
    rep: list[dict] = []
    peak, fired = close[0], set()
    done: list[float] = []
    k = 0
    for i in range(1, len(close)):
        while k < len(eps) and eps[k][1] <= i:
            done.append(eps[k][2])
            k += 1
        if close[i] > peak:
            peak, fired = close[i], set()
            continue
        if len(done) < 2 or dates[i] < FROM:
            continue
        usual = float(np.median(done))
        dd = close[i] / peak - 1
        for name, m in STEPS.items():
            if name not in fired and dd <= m * usual:
                fired.add(name)
                ev.append({"i": i, "step": name, "usual": usual, "dd": dd})
    # repeat check: each completed episode with >= 2 earlier ones
    for j in range(2, len(eps)):
        past = [e[2] for e in eps[:j]]
        if dates[eps[j][1]] >= FROM:
            rep.append(
                {
                    "med": float(np.median(past)),
                    "lo": float(np.percentile(past, 25)),
                    "hi": float(np.percentile(past, 75)),
                    "next": eps[j][2],
                }
            )
    allp = [e[2] for e in eps if dates[e[0]] >= np.datetime64("2020-01-01")]
    cur = close[-1] / close.max() - 1
    stats = {
        "n": len(allp),
        "mean": float(np.mean(allp)) if allp else None,
        "median": float(np.median(allp)) if allp else None,
        "p25": float(np.percentile(allp, 75)) if allp else None,  # shallower edge
        "p75": float(np.percentile(allp, 25)) if allp else None,  # deeper edge
        "max": float(np.min(allp)) if allp else None,
        "now": float(cur),
    }
    return ev, rep, stats


def judge(e: pl.DataFrame, name: str) -> dict:
    out: dict = {"name": name, "n": e.height}
    if e.height == 0:
        return out
    dates = e["date"].unique().sort()
    mid = dates[len(dates) // 2]
    for h in ("x60", "x250"):
        s = e.filter(C(h).is_not_null())
        out[h] = {
            "n": s.height,
            "mean": s[h].mean(),
            "median": s[h].median(),
            "win": (s[h] > 0).mean() if s.height else None,
            "first": s.filter(C("date") < mid)[h].mean(),
            "second": s.filter(C("date") >= mid)[h].mean(),
        }
    return out


def main() -> None:
    p, ids = fm.build()
    fund = p.select("date", G, "eps_ttm", "liab_ratio")
    with session_scope() as s:
        prices, _cl, _ = load_inputs(s)
    a = apply_adjustments(prices).filter((C("close") > 0) & C(G).is_in(list(ids))).sort(G, "date")
    a = a.with_columns(C("date").cast(pl.Date))
    c = C("adj_close")
    a = a.with_columns(
        f60=(c.shift(-61) / c.shift(-1) - 1 - COST).over(G),
        f250=(c.shift(-251) / c.shift(-1) - 1 - COST).over(G),
        hi60=(c >= c.rolling_max(60)).over(G),
        up7=((c > c.shift(1)).cast(pl.Int8).rolling_sum(7) >= 5).over(G),
    )
    a = a.with_columns(
        x60=C("f60") - C("f60").mean().over("date"),
        x250=C("f250") - C("f250").mean().over("date"),
    )
    rows, reps, table = [], [], []
    for (iid,), g in a.group_by(G, maintain_order=True):
        dts = g["date"].to_numpy().astype("datetime64[D]")
        ev, rep, st = scan(dts, g["adj_close"].to_numpy())
        reps += rep
        table.append({"symbol": ids[iid], **st})
        rows.extend({G: iid, "date": g["date"][x.pop("i")], **x} for x in ev)
    e = pl.DataFrame(rows).join(a.select(G, "date", "x60", "x250"), on=[G, "date"], how="left")
    e = e.sort("date").join_asof(fund.sort("date"), on="date", by=G, strategy="backward")
    e = e.with_columns(sound=(C("eps_ttm") > 0) & (C("liab_ratio") < 0.7))
    green = a.filter((C("date") >= pl.date(2023, 4, 1)) & C("hi60") & C("up7"))

    res = [judge(e.filter(C("step") == s), s) for s in STEPS]
    res += [judge(e.filter((C("step") == s) & C("sound")), s + "+sound") for s in STEPS]
    res.append(judge(e.unique([G, "date"]), "any step"))
    res.append(judge(green, "GREEN"))
    r = pl.DataFrame(reps)
    repeat = {
        "n": r.height,
        "corr": float(np.corrcoef(r["med"], r["next"])[0, 1]) if r.height > 2 else None,
        "inside_range": float(((r["next"] >= r["lo"]) & (r["next"] <= r["hi"])).mean()),
        "deeper_than_range": float((r["next"] < r["lo"]).mean()),
        "shallower_than_range": float((r["next"] > r["hi"]).mean()),
        "mae_vs_median": float((r["next"] - r["med"]).abs().mean()),
    }
    table.sort(key=lambda t: t["median"] if t["median"] is not None else 0)
    out = {"results": res, "repeat": repeat, "table": table}
    (HERE / "results_drawdown_floor.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=1, default=str), encoding="utf-8"
    )
    for x in res:
        print(x["name"], x["n"], {h: x[h] for h in ("x60", "x250") if h in x})
    print("repeat", repeat)


if __name__ == "__main__":
    main()
